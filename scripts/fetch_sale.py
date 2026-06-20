import requests
from bs4 import BeautifulSoup
import json
import re
from datetime import datetime

PRODUCT_KEYWORDS = {
    'chicken':      ['鶏むね', '鶏胸', 'とりむね', '若どり むね', '若鶏むね'],
    'pork':         ['豚バラ', '豚ばら', 'ぶたバラ', '豚バラ肉'],
    'ground':       ['合いびき', '合挽き', 'ひき肉', '挽き肉', '牛豚'],
    'tofu':         ['豆腐', 'とうふ', '絹ごし', '木綿豆腐'],
    'egg':          ['卵', '玉子', 'たまご', 'Mサイズ卵', 'Lサイズ卵'],
    'bean_sprouts': ['もやし', 'モヤシ', '大豆もやし'],
    'cabbage':      ['キャベツ', 'きゃべつ'],
    'onion':        ['玉ねぎ', 'たまねぎ', '玉葱', '北海道産玉ねぎ'],
    'carrot':       ['にんじん', 'ニンジン', '人参'],
    'potato':       ['じゃがいも', 'ジャガイモ', 'じゃが芋', 'メークイン'],
    'mushroom':     ['しめじ', 'えのき', 'エノキ', 'きのこ'],
    'gyoza':        ['餃子', 'ぎょうざ', 'ギョーザ', 'ぎょうざ'],
    'karaage':      ['唐揚げ', 'からあげ', 'から揚げ', '竜田揚げ'],
    'curry_roux':   ['カレー', 'カレールー', 'カレールウ'],
    'pasta':        ['パスタ', 'スパゲッティ', 'スパゲティ'],
    'rice':         ['米', 'お米', 'ご飯', '白米', 'こしひかり'],
    'frozen_veg':   ['冷凍野菜', '冷凍ミックス', '冷凍ほうれん草'],
}

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'ja-JP,ja;q=0.9,en-US;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Referer': 'https://www.gyomusuper.jp/',
}

URLS = [
    'https://www.gyomusuper.jp/bargain/',
    'https://www.gyomusuper.jp/saiyasune.php',
]

def extract_price(text):
    text = text.replace(',', '').replace('，', '')
    m = re.search(r'(\d{2,5})', text)
    return int(m.group(1)) if m else None

def match_product(name):
    for prod_id, keywords in PRODUCT_KEYWORDS.items():
        if any(kw in name for kw in keywords):
            return prod_id
    return None

def parse_html(html):
    soup = BeautifulSoup(html, 'html.parser')
    items = []

    # 価格パターンを含む要素を広く探す
    price_pattern = re.compile(r'[\d,]{2,6}円|¥\s*[\d,]+')
    candidates = soup.find_all(string=price_pattern)

    seen = set()
    for price_text in candidates:
        price = extract_price(price_text)
        if not price or price > 9999 or price < 50:
            continue

        # 近くにある商品名テキストを探す
        parent = price_text.parent
        for _ in range(4):
            if parent is None:
                break
            block_text = parent.get_text(' ', strip=True)
            # 商品名に該当するキーワードがあるか確認
            prod_id = match_product(block_text)
            if prod_id and prod_id not in seen:
                items.append({
                    'productId': prod_id,
                    'salePrice': price,
                    'raw': block_text[:40],
                })
                seen.add(prod_id)
                break
            parent = parent.parent

    return items

def fetch():
    session = requests.Session()
    # まずトップページにアクセスしてCookieを取得
    try:
        session.get('https://www.gyomusuper.jp/', headers=HEADERS, timeout=20)
    except Exception:
        pass

    items = []
    success = False
    message = ''

    for url in URLS:
        try:
            resp = session.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            items = parse_html(resp.text)
            success = True
            message = f'取得成功: {len(items)}件マッチ ({url})'
            print(message)
            break
        except requests.HTTPError as e:
            message = f'HTTPエラー {e.response.status_code}: {url}'
            print(message)
        except Exception as e:
            message = f'エラー: {e}'
            print(message)

    result = {
        'updated': datetime.now().strftime('%Y-%m-%d'),
        'success': success,
        'message': message,
        'items': items,
    }

    with open('sale_data.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f'sale_data.json を保存しました ({len(items)}件)')

if __name__ == '__main__':
    fetch()
