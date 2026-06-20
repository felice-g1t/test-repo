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


def fetch():
    session = requests.Session()
    try:
        session.get(f'{BASE}/', headers=FETCH_HEADERS, timeout=20)
    except Exception:
        pass

    client = anthropic.Anthropic()
    all_recipes = []
    debug_log = ''

    for target in TARGETS:
        url      = target['url']
        category = target['category']
        try:
            resp = session.get(url, headers=FETCH_HEADERS, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, 'html.parser')
            # テキストだけ取り出してトークンを節約
            text = soup.get_text(separator='\n', strip=True)[:6000]
            debug_log += f'\n=== {url} ===\n{text[:1000]}\n'

            message = client.messages.create(
                model='claude-haiku-4-5-20251001',
                max_tokens=1024,
                messages=[{
                    'role': 'user',
                    'content': [{
                        'type': 'text',
                        'text': (
                            f'以下は業務スーパーサイト（{url}）のテキストです。\n'
                            'レシピ名・料理名・特集メニュー名を全て抽出してください。\n'
                            '商品名や会社情報は除外し、料理・レシピのタイトルだけ返してください。\n'
                            '以下のJSON形式で返してください（他の文字は一切不要）：\n'
                            '[{"name": "料理名"}, ...]\n\n'
                            f'テキスト:\n{text}'
                        ),
                    }],
                }],
            )

            raw = message.content[0].text
            print(f'{category} Claude応答: {raw[:200]}')
            json_match = re.search(r'\[.*\]', raw, re.DOTALL)
            if not json_match:
                print(f'  JSONなし')
                continue

            items = json.loads(json_match.group())
            for item in items:
                name = item.get('name', '').strip()
                if name and len(name) >= 3:
                    all_recipes.append({
                        'name': name,
                        'url': url,
                        'category': category,
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
        'count': len(unique),
        'recipes': unique,
    }

    with open('recipe_data.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f'完了: {len(unique)}件のレシピを保存')


if __name__ == '__main__':
    fetch()
