import requests
import anthropic
import base64
import json
import re
from datetime import datetime
from urllib.parse import urljoin
from bs4 import BeautifulSoup

PRODUCT_KEYWORDS = {
    'chicken':      ['鶏むね', '鶏胸', 'とりむね', '若どり', '若鶏'],
    'pork':         ['豚バラ', '豚ばら', '豚肉'],
    'ground':       ['合いびき', '合挽き', 'ひき肉', '挽き肉'],
    'tofu':         ['豆腐', 'とうふ', '絹ごし', '木綿豆腐', '厚揚げ', '絹厚あげ'],
    'egg':          ['卵', '玉子', 'たまご'],
    'bean_sprouts': ['もやし', 'モヤシ'],
    'cabbage':      ['キャベツ'],
    'onion':        ['玉ねぎ', 'たまねぎ', '玉葱'],
    'carrot':       ['にんじん', 'ニンジン', '人参'],
    'potato':       ['じゃがいも', 'ジャガイモ'],
    'mushroom':     ['しめじ', 'えのき', 'エノキ', 'きのこ'],
    'gyoza':        ['餃子', 'ぎょうざ', 'ギョーザ'],
    'karaage':      ['唐揚げ', 'からあげ', 'から揚げ'],
    'curry_roux':   ['カレールー', 'カレールウ'],
    'pasta':        ['パスタ', 'スパゲッティ'],
    'rice':         ['お米', '白米', 'こしひかり', 'ひとめぼれ'],
    'frozen_veg':   ['冷凍野菜', '冷凍ミックス'],
    'sausage':      ['ウインナー', 'ソーセージ', 'フランク'],
    'ham_bacon':    ['ロースハム', 'ベーコン', 'ハーフベーコン'],
    'natto':        ['納豆'],
    'bread':        ['食パン', 'パン'],
}

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
REGION = 'west'  # hokkaido / east（南関東） / west（近畿） / kyusyu（九州）

def get_flyer_image_urls(session):
    page_url = f'{BASE}/bargain/'
    resp = session.get(page_url, headers=FETCH_HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, 'html.parser')
    urls = []
    for img in soup.find_all('img'):
        src = img.get('src') or img.get('data-src') or ''
        if not src:
            continue
        absolute = urljoin(page_url, src)
        if f'bargain_{REGION}_' in absolute and re.search(r'\.(jpg|jpeg|png)', absolute, re.I):
            urls.append(absolute)
    return urls

def analyze_image_with_claude(client, image_data, media_type='image/jpeg'):
    """Claude APIで画像からセール商品を抽出"""
    image_b64 = base64.standard_b64encode(image_data).decode()
    message = client.messages.create(
        model='claude-haiku-4-5-20251001',
        max_tokens=1024,
        messages=[{
            'role': 'user',
            'content': [
                {
                    'type': 'image',
                    'source': {
                        'type': 'base64',
                        'media_type': media_type,
                        'data': image_b64,
                    },
                },
                {
                    'type': 'text',
                    'text': (
                        'この業務スーパーのチラシ画像から、セール商品の情報をすべて読み取ってください。\n'
                        '以下のJSON形式で返してください（他の文字は不要）：\n'
                        '[{"name": "商品名", "price": 価格（税抜き・整数）}, ...]\n'
                        '価格が読み取れない商品は含めないでください。'
                    ),
                },
            ],
        }],
    )
    return message.content[0].text

def match_product(name):
    for prod_id, keywords in PRODUCT_KEYWORDS.items():
        if any(kw in name for kw in keywords):
            return prod_id
    return None

def fetch():
    session = requests.Session()
    try:
        session.get(f'{BASE}/', headers=FETCH_HEADERS, timeout=20)
    except Exception:
        pass

    client = anthropic.Anthropic()
    all_raw_items = []
    matched_items = []
    success = False
    message = ''

    try:
        image_urls = get_flyer_image_urls(session)
        print(f'チラシ画像: {len(image_urls)}件')

        for img_url in image_urls:
            print(f'  解析中: {img_url.split("/")[-1]}')
            resp = session.get(img_url, headers=FETCH_HEADERS, timeout=30)
            resp.raise_for_status()

            raw_text = analyze_image_with_claude(client, resp.content)
            print(f'  Claude応答: {raw_text[:200]}')

            # JSONを抽出
            json_match = re.search(r'\[.*\]', raw_text, re.DOTALL)
            if not json_match:
                print('  JSONが見つかりませんでした')
                continue

            items = json.loads(json_match.group())
            for item in items:
                name = item.get('name', '')
                price = item.get('price')
                if not name or not price:
                    continue
                all_raw_items.append({'name': name, 'price': int(price)})
                prod_id = match_product(name)
                if prod_id:
                    matched_items.append({
                        'productId': prod_id,
                        'salePrice': int(price),
                        'raw': name,
                    })

        success = True
        message = f'Claude解析完了: {len(all_raw_items)}品取得、{len(matched_items)}品マッチ'
        print(message)

    except Exception as e:
        message = f'エラー: {e}'
        print(message)

    result = {
        'updated': datetime.now().strftime('%Y-%m-%d'),
        'success': success,
        'message': message,
        'items': matched_items,
        'allSaleItems': all_raw_items,
    }

    with open('sale_data.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f'完了: {len(matched_items)}件マッチ')

if __name__ == '__main__':
    fetch()
