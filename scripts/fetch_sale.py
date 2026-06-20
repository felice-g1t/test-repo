import requests
from bs4 import BeautifulSoup
import json
import re
import io
from datetime import datetime
from urllib.parse import urljoin
from PIL import Image
import pytesseract

PRODUCT_KEYWORDS = {
    'chicken':      ['鶏むね', '鶏胸', 'とりむね', '若どり', '若鶏'],
    'pork':         ['豚バラ', '豚ばら', '豚肉'],
    'ground':       ['合いびき', '合挽き', 'ひき肉', '挽き肉'],
    'tofu':         ['豆腐', 'とうふ', '絹ごし', '木綿豆腐'],
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
}

HEADERS = {
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

# ★ お住まいの地域に合わせて変更してください
# hokkaido / east（南関東） / west（近畿） / kyusyu（九州）
REGION = 'west'

def match_product(text):
    for prod_id, keywords in PRODUCT_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return prod_id
    return None

def parse_ocr_text(text):
    """OCRテキストから商品名・価格ペアを抽出"""
    items = []
    seen = set()
    lines = [l.strip() for l in text.split('\n') if l.strip()]

    for i, line in enumerate(lines):
        prod_id = match_product(line)
        if not prod_id or prod_id in seen:
            continue
        # 前後2行の範囲で価格を探す
        context = ' '.join(lines[max(0, i-2):min(len(lines), i+3)])
        prices = [int(p) for p in re.findall(r'(\d{2,5})\s*円', context)
                  if 50 <= int(p) <= 5000]
        if prices:
            items.append({
                'productId': prod_id,
                'salePrice': min(prices),
                'raw': line[:60],
            })
            seen.add(prod_id)

    return items

def get_image_urls(soup, page_url):
    """ページ内のチラシ画像URLを取得（相対パスを正しく解決）"""
    urls = []
    for img in soup.find_all('img'):
        src = img.get('src') or img.get('data-src') or ''
        if not src:
            continue
        absolute = urljoin(page_url, src)
        # 指定地域のチラシ画像のみ対象
        if f'bargain_{REGION}_' in absolute and re.search(r'\.(jpg|jpeg|png)', absolute, re.I):
            urls.append(absolute)
    return urls

def ocr_image(session, img_url):
    """画像をダウンロードしてOCR"""
    try:
        resp = session.get(img_url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content))
        # 小さいアイコン類はスキップ
        if img.width < 300 or img.height < 300:
            return ''
        # 大きすぎる場合は縮小（速度優先）
        if img.width > 1500:
            ratio = 1500 / img.width
            img = img.resize((1500, int(img.height * ratio)), Image.LANCZOS)
        # 小さい画像は2倍に拡大してOCR精度を上げる
        if img.width < 1000:
            img = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)
        text = pytesseract.image_to_string(img, lang='jpn')
        print(f'  OCR完了 ({img.width}x{img.height}): {len(text)}文字取得')
        print(f'  --- OCRテキスト先頭300文字 ---')
        print(text[:300])
        print(f'  --- ここまで ---')
        return text
    except Exception as e:
        print(f'  スキップ ({img_url[-40:]}): {e}')
        return ''

def fetch():
    session = requests.Session()
    try:
        session.get(f'{BASE}/', headers=HEADERS, timeout=20)
    except Exception:
        pass

    items = []
    success = False
    message = ''

    try:
        resp = session.get(f'{BASE}/bargain/', headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')

        page_url = f'{BASE}/bargain/'
        image_urls = get_image_urls(soup, page_url)
        print(f'画像URL発見: {len(image_urls)}件')
        for u in image_urls:
            print(f'  {u}')

        # 全画像をOCR
        all_ocr_text = ''
        for img_url in image_urls:
            all_ocr_text += ocr_image(session, img_url) + '\n'

        # デバッグ用にOCR結果を保存
        with open('debug_ocr.txt', 'w', encoding='utf-8') as f:
            f.write(f'画像数: {len(image_urls)}\n\n')
            f.write(all_ocr_text)

        items = parse_ocr_text(all_ocr_text)
        success = True
        message = f'OCR取得成功: {len(items)}件マッチ'
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

    print(f'完了: {len(items)}件')

if __name__ == '__main__':
    fetch()
