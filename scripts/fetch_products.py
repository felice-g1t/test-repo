import requests
import anthropic
import json
import re
from datetime import datetime
from bs4 import BeautifulSoup

FETCH_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'ja-JP,ja;q=0.9',
}

BASE = 'https://www.gyomusuper.jp'

CATEGORY_MAP = {
    'seiku':   '精肉・ハム・ソーセージ',
    'gyokai':  '魚介・水産加工品',
    'yasai':   '野菜・果物',
    'reito':   '冷凍食品',
    'nyugan':  '乳製品・卵',
    'tofu':    '豆腐・大豆製品',
    'kokuhin': '米・麺・パン',
    'kanbutsu':'乾物・缶詰',
    'choumi':  '調味料・油',
    'sozai':   '惣菜・チルド',
    'okashi':  '菓子・スイーツ',
    'inryo':   '飲料',
}

# Preserve known IDs from existing meal system
KNOWN_IDS = {
    '鶏むね肉': 'chicken', '鶏もも肉': 'chicken_thigh', '豚バラ薄切り': 'pork',
    '豚こま切れ': 'pork_kom', '合いびき肉': 'ground', '絹ごし豆腐': 'tofu',
    '卵': 'egg', 'もやし': 'bean_sprouts', 'キャベツ': 'cabbage',
    '玉ねぎ': 'onion', 'にんじん': 'carrot', 'じゃがいも': 'potato',
    'ぶなしめじ': 'mushroom', 'えのき': 'enoki', '大根': 'daikon',
    '白菜': 'hakusai', '長ねぎ': 'spring_onion', '冷凍ほうれん草': 'spinach',
    '冷凍ブロッコリー': 'frozen_broccoli', '冷凍ミックス野菜': 'frozen_veg',
    '冷凍枝豆': 'frozen_edamame', '冷凍餃子': 'gyoza', '冷凍唐揚げ': 'karaage',
    'ウインナー': 'sausage', 'ロースハム': 'ham_bacon', 'キムチ': 'kimchi',
    'ツナ缶': 'tuna_can', '納豆': 'natto', '油揚げ': 'aburaage',
    'こんにゃく': 'konnyaku', 'ちくわ': 'chikuwa', 'とろけるチーズ': 'cheese',
    'コーン缶': 'canned_corn', 'わかめ': 'wakame', 'カレールー': 'curry_roux',
    'トマト缶': 'tomato_can', 'パスタ': 'pasta', '冷凍うどん': 'udon',
    '米': 'rice', '食パン': 'bread', '味噌': 'miso',
    'めんつゆ': 'mentsuyu', 'マヨネーズ': 'mayo', 'すりごま': 'sesame',
    '青じそ': 'shiso',
}


def make_id(name: str, seen: set) -> str:
    if name in KNOWN_IDS:
        return KNOWN_IDS[name]
    base = re.sub(r'[^\w]', '_', name)[:20].strip('_').lower()
    base = re.sub(r'_+', '_', base)
    cand = base
    i = 2
    while cand in seen:
        cand = f'{base}_{i}'
        i += 1
    return cand


def extract_image_map(soup, base: str) -> dict:
    """Return alt_text -> absolute_image_url mapping from page."""
    img_map = {}
    for img in soup.find_all('img'):
        src = img.get('src') or img.get('data-src') or ''
        alt = (img.get('alt') or '').strip()
        if not src or not alt or len(alt) < 2:
            continue
        if src.startswith('//'):
            src = 'https:' + src
        elif src.startswith('/'):
            src = base + src
        elif not src.startswith('http'):
            continue
        img_map[alt] = src
    return img_map


def match_image(name: str, img_map: dict) -> str:
    """Return image URL for product name, or empty string."""
    if name in img_map:
        return img_map[name]
    for alt, src in img_map.items():
        if name in alt or alt in name:
            return src
    return ''


def fetch_category_products(session, client, url: str, category: str) -> list:
    try:
        resp = session.get(url, headers=FETCH_HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        img_map = extract_image_map(soup, BASE)
        text = soup.get_text(separator='\n', strip=True)[:8000]

        message = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=2048,
            messages=[{
                'role': 'user',
                'content': (
                    f'以下は業務スーパーの商品一覧ページ（カテゴリ: {category}）のテキストです。\n'
                    '商品名・内容量・価格を全て抽出してください。\n'
                    '商品でない行（ナビ、会社情報、説明文）は除外してください。\n'
                    '価格は税抜き円数の数字のみ（例: 298）。不明な場合は0。\n'
                    '以下のJSON配列のみを返してください（他の文字は不要）:\n'
                    '[{"name":"商品名","amount":"内容量","price":298}, ...]\n\n'
                    f'テキスト:\n{text}'
                ),
            }],
        )
        raw = message.content[0].text
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        if not match:
            return []
        items = json.loads(match.group())
        result = []
        for item in items:
            if not item.get('name') or len(item['name']) < 2:
                continue
            img_url = match_image(item['name'].strip(), img_map)
            if img_url:
                item['image_url'] = img_url
            result.append(item)
        return result
    except Exception as e:
        print(f'  エラー ({url}): {e}')
        return []


def fetch():
    session = requests.Session()
    try:
        session.get(f'{BASE}/', headers=FETCH_HEADERS, timeout=20)
    except Exception:
        pass

    client = anthropic.Anthropic()
    all_products = []
    seen_ids: set = set()
    seen_names: set = set()

    # 全商品ページを試みる
    target_urls = [
        (f'{BASE}/allproduct/', '全カテゴリ'),
    ]
    # カテゴリ別も追加
    for k, cat in CATEGORY_MAP.items():
        target_urls.append((f'{BASE}/category/index.php?cid={k}', cat))

    for url, category in target_urls:
        print(f'取得中: {category} ({url})')
        items = fetch_category_products(session, client, url, category)
        print(f'  → {len(items)}件')
        for item in items:
            name = item['name'].strip()
            if name in seen_names:
                continue
            seen_names.add(name)
            pid = make_id(name, seen_ids)
            seen_ids.add(pid)
            entry = {
                'id': pid,
                'name': name,
                'amount': str(item.get('amount', '') or ''),
                'price': int(item.get('price', 0) or 0),
                'category': category,
            }
            if item.get('image_url'):
                entry['image_url'] = item['image_url']
            all_products.append(entry)

    if not all_products:
        print('商品を取得できませんでした。既存データを維持します。')
        return

    # 既存 products_data.json とマージ（image_url は更新、価格等は新規のみ追加）
    try:
        with open('products_data.json', 'r', encoding='utf-8') as f:
            existing = json.load(f)
        existing_map = {p['id']: p for p in existing.get('products', [])}
        for p in all_products:
            if p['id'] in existing_map:
                # image_url が新たに取得できた場合だけ更新
                if p.get('image_url') and not existing_map[p['id']].get('image_url'):
                    existing_map[p['id']]['image_url'] = p['image_url']
            else:
                existing['products'].append(p)
        merged = existing
    except Exception:
        merged = {'products': all_products}

    merged['updated'] = datetime.now().strftime('%Y-%m-%d')
    merged['success'] = True
    merged['count'] = len(merged['products'])

    with open('products_data.json', 'w', encoding='utf-8') as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    print(f'完了: 合計 {merged["count"]} 件の商品を保存')


if __name__ == '__main__':
    fetch()
