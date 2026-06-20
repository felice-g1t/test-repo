import requests
import anthropic
import json
import re
from datetime import datetime
from urllib.parse import urljoin
from bs4 import BeautifulSoup

FETCH_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'ja-JP,ja;q=0.9',
    'Referer': 'https://www.gyomusuper.jp/',
}

BASE = 'https://www.gyomusuper.jp'

TARGETS = [
    {'url': f'{BASE}/recipe/',          'category': 'ミラクルレシピ'},
    {'url': f'{BASE}/topics/index.php', 'category': '特集・新商品'},
]

SKIP_TEXTS = {'ホーム', 'トップ', 'もっと見る', '一覧', 'メニュー', 'ページ', 'へ'}


def abs_url(src: str, base: str) -> str:
    if not src:
        return ''
    if src.startswith('//'):
        return 'https:' + src
    return urljoin(base, src)


def extract_cards(soup: BeautifulSoup, page_url: str) -> list:
    """ページのHTMLからレシピカード（名前・URL・画像）を抽出する"""
    cards = []
    seen_urls: set = set()

    for a in soup.find_all('a', href=True):
        href = a['href']
        full_url = abs_url(href, page_url)
        if full_url in seen_urls:
            continue

        # レシピ詳細ページっぽいURLだけ対象
        if not any(kw in full_url for kw in ['recipe', 'menu', 'special', 'topics']):
            continue
        if full_url == page_url:
            continue
        seen_urls.add(full_url)

        # 名前 = リンクテキスト or 内側 img の alt
        name = a.get_text(strip=True)
        img_tag = a.find('img')
        img_url = ''
        if img_tag:
            src = img_tag.get('src') or img_tag.get('data-src') or img_tag.get('data-lazy-src') or ''
            img_url = abs_url(src, page_url)
            if not name:
                name = img_tag.get('alt', '').strip()

        name = re.sub(r'\s+', ' ', name).strip()
        if not name or len(name) < 3:
            continue
        if any(s in name for s in SKIP_TEXTS):
            continue

        cards.append({'name': name, 'url': full_url, 'image_url': img_url})

    return cards


def fetch_detail_image(session: requests.Session, url: str) -> str:
    """個別レシピページからメイン画像を取得する（カード画像が空の場合のフォールバック）"""
    try:
        resp = session.get(url, headers=FETCH_HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        # og:image が最も確実
        og = soup.find('meta', property='og:image')
        if og and og.get('content'):
            return abs_url(og['content'], url)
        # 大きめの img タグを探す（ロゴ・アイコン除外）
        for img in soup.find_all('img'):
            src = img.get('src') or img.get('data-src') or ''
            if not src:
                continue
            if any(s in src.lower() for s in ('logo', 'icon', 'banner', 'btn', 'arrow')):
                continue
            return abs_url(src, url)
    except Exception:
        pass
    return ''


def fetch():
    session = requests.Session()
    try:
        session.get(f'{BASE}/', headers=FETCH_HEADERS, timeout=20)
    except Exception:
        pass

    client = anthropic.Anthropic()
    all_recipes: list = []
    debug_log = ''

    for target in TARGETS:
        url      = target['url']
        category = target['category']
        try:
            resp = session.get(url, headers=FETCH_HEADERS, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')

            # 1) HTMLからカードを直接抽出
            cards = extract_cards(soup, url)
            print(f'{category}: HTML抽出 {len(cards)}件')

            # 2) テキストからも Claude でレシピ名を補完
            text = soup.get_text(separator='\n', strip=True)[:6000]
            debug_log += f'\n=== {url} ===\n{text[:1000]}\n'

            message = client.messages.create(
                model='claude-haiku-4-5-20251001',
                max_tokens=1024,
                messages=[{'role': 'user', 'content': (
                    f'以下は業務スーパーサイト（{url}）のテキストです。\n'
                    'レシピ名・料理名・特集メニュー名を全て抽出してください。\n'
                    '商品名や会社情報は除外し、料理・レシピのタイトルだけ返してください。\n'
                    '以下のJSON形式のみ（他の文字は一切不要）:\n'
                    '[{"name": "料理名"}, ...]\n\n'
                    f'テキスト:\n{text}'
                )}],
            )
            raw = message.content[0].text
            json_match = re.search(r'\[.*\]', raw, re.DOTALL)
            claude_names: set = set()
            if json_match:
                for item in json.loads(json_match.group()):
                    n = item.get('name', '').strip()
                    if n and len(n) >= 3:
                        claude_names.add(n)

            # カードにある名前はそのまま使い、Claudeのみが知っている名前は URL を親ページに
            card_names = {c['name'] for c in cards}
            for n in claude_names:
                if n not in card_names:
                    cards.append({'name': n, 'url': url, 'image_url': ''})

            # 3) 画像が空のカードは詳細ページから取得（最大15件）
            for card in cards[:15]:
                if not card['image_url'] and card['url'] != url:
                    card['image_url'] = fetch_detail_image(session, card['url'])

            for card in cards:
                all_recipes.append({
                    'name': card['name'],
                    'url':  card['url'],
                    'category': category,
                    'image_url': card['image_url'],
                })

        except Exception as e:
            print(f'エラー ({url}): {e}')

    with open('debug_recipes.txt', 'w', encoding='utf-8') as f:
        f.write(debug_log)

    # 重複除去
    seen, unique = set(), []
    for r in all_recipes:
        if r['name'] not in seen:
            seen.add(r['name'])
            unique.append(r)

    result = {
        'updated': datetime.now().strftime('%Y-%m-%d'),
        'success': len(unique) > 0,
        'count':   len(unique),
        'recipes': unique,
    }

    with open('recipe_data.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f'完了: {len(unique)}件のレシピを保存')


if __name__ == '__main__':
    fetch()
