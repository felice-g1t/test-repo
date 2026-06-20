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

def parse_html(html, debug=False):
    soup = BeautifulSoup(html, 'html.parser')

    # デバッグ: ページ全体のテキストを確認
    all_text = soup.get_text(' ', strip=True)
    if debug:
        print('=== HTML先頭2000文字 ===')
        print(html[:2000])
        print('=== テキスト全体（先頭1000文字）===')
        print(all_text[:1000])

    # JS レンダリングか静的かを判定（テキストが少なすぎる場合はJS描画）
    if len(all_text) < 200:
        print('警告: テキストが少なすぎます。ページがJavaScriptで描画されている可能性があります。')
        with open('debug_html.txt', 'w', encoding='utf-8') as f:
            f.write(html[:5000])
        return []

    items = []
    # 価格パターンを含む要素を広く探す
    price_pattern = re.compile(r'[\d,]{2,6}円|¥\s*[\d,]+|税込[\d,]+')
    candidates = soup.find_all(string=price_pattern)

    print(f'価格っぽいテキスト: {len(candidates)}件')
    for t in candidates[:10]:
        print(f'  候補: {str(t)[:60]}')

    # キーワードマッチのデバッグ
    keyword_hits = []
    for prod_id, keywords in PRODUCT_KEYWORDS.items():
        for kw in keywords:
            if kw in all_text:
                keyword_hits.append(f'{prod_id}({kw})')
    print(f'キーワードヒット: {keyword_hits[:20]}')

    seen = set()
    for price_text in candidates:
        price = extract_price(price_text)
        if not price or price > 9999 or price < 50:
            continue

        parent = price_text.parent
        for _ in range(5):
            if parent is None:
                break
            block_text = parent.get_text(' ', strip=True)
            prod_id = match_product(block_text)
            if prod_id and prod_id not in seen:
                items.append({
                    'productId': prod_id,
                    'salePrice': price,
                    'raw': block_text[:60],
                })
                seen.add(prod_id)
                break
            parent = parent.parent

    # デバッグ用にHTMLスニペットを保存
    with open('debug_html.txt', 'w', encoding='utf-8') as f:
        f.write(f'URL取得成功\nテキスト長: {len(all_text)}\n\n')
        f.write('=== HTML先頭3000文字 ===\n')
        f.write(html[:3000])

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
            items = parse_html(resp.text, debug=True)
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
