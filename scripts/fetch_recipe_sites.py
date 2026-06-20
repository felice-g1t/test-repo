"""
節約・ダイエット・映え系レシピを公開サイトから収集し recipe_sites_data.json に保存する。

対象:
  - 業務スーパー公式レシピ (recipe.gyomusuper.jp) — カテゴリ一覧も含めてより広く収集
  - E・レシピ (erecipe.woman.excite.co.jp) の業務スーパー特集ページ
  - kurashiru.com の業務スーパー検索結果（テキストのみ取得）
"""

import requests
import anthropic
import json
import re
from datetime import datetime
from bs4 import BeautifulSoup
import time

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'ja-JP,ja;q=0.9',
}

RECIPE_EXTRACT_PROMPT = """以下は料理レシピページのテキストです。
このページから料理レシピを全て抽出してください。

各レシピについて以下を抽出:
- name: 料理名（日本語）
- desc: 一行説明（主な材料3つ程度）
- theme: テーマ（節約/ダイエット/映え/業スー/普通　から最も当てはまるもの）
- ingredients_text: 材料リスト（そのままのテキスト）
- recipe_steps: 作り方（ステップごとに配列）

以下のJSON配列のみ返してください（他の文字は不要）:
[{
  "name": "料理名",
  "desc": "説明",
  "theme": "テーマ",
  "ingredients_text": "材料のテキスト",
  "recipe_steps": ["手順1", "手順2", ...]
}, ...]

テキスト:
"""

TARGET_URLS = [
    # 業務スーパー公式レシピカテゴリ
    ('https://recipe.gyomusuper.jp/category/meat/', '業スー公式・肉'),
    ('https://recipe.gyomusuper.jp/category/fish/', '業スー公式・魚'),
    ('https://recipe.gyomusuper.jp/category/vegetable/', '業スー公式・野菜'),
    ('https://recipe.gyomusuper.jp/category/processed/', '業スー公式・加工品'),
    ('https://recipe.gyomusuper.jp/category/frozen/', '業スー公式・冷凍'),
    ('https://recipe.gyomusuper.jp/category/noodles/', '業スー公式・麺'),
    ('https://recipe.gyomusuper.jp/category/rice/', '業スー公式・ご飯'),
    ('https://recipe.gyomusuper.jp/category/soup/', '業スー公式・スープ'),
    ('https://recipe.gyomusuper.jp/category/salad/', '業スー公式・サラダ'),
    ('https://recipe.gyomusuper.jp/category/budget/', '業スー公式・節約'),
    ('https://recipe.gyomusuper.jp/category/diet/', '業スー公式・ダイエット'),
    # メインレシピページ
    ('https://recipe.gyomusuper.jp/', '業スー公式・トップ'),
    ('https://recipe.gyomusuper.jp/category/staple/', '業スー公式・主食'),
    ('https://recipe.gyomusuper.jp/category/side/', '業スー公式・副菜'),
    ('https://recipe.gyomusuper.jp/category/dessert/', '業スー公式・デザート'),
]

KNOWN_PRODUCT_IDS = {
    '鶏むね肉': 'chicken', '鶏もも肉': 'chicken_thigh', '豚バラ': 'pork',
    '豚こま': 'pork_kom', '合いびき': 'ground', '絹ごし豆腐': 'tofu', '木綿豆腐': 'tofu',
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


def fetch_page(session: requests.Session, url: str) -> BeautifulSoup | None:
    try:
        resp = session.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, 'html.parser')
    except Exception as e:
        print(f'  取得失敗 ({url}): {e}')
        return None


def extract_recipes_from_page(client: anthropic.Anthropic, soup: BeautifulSoup, source: str) -> list:
    text = soup.get_text(separator='\n', strip=True)[:9000]
    try:
        msg = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=4096,
            messages=[{'role': 'user', 'content': RECIPE_EXTRACT_PROMPT + text}],
        )
        raw = msg.content[0].text
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        if not match:
            return []
        recipes = json.loads(match.group())
        for r in recipes:
            r['source'] = source
        return [r for r in recipes if r.get('name') and len(r['name']) >= 2]
    except Exception as e:
        print(f'  Claude抽出エラー ({source}): {e}')
        return []


def guess_ingredients(ingredients_text: str) -> dict:
    """材料テキストから既知の商品IDを推定する（ベストエフォート）"""
    ing = {}
    for keyword, pid in KNOWN_PRODUCT_IDS.items():
        if keyword in ingredients_text:
            ing[pid] = ing.get(pid, 0.25)
    return ing


def fetch_individual_recipe_pages(session: requests.Session, client: anthropic.Anthropic,
                                   soup: BeautifulSoup, base_url: str, source: str) -> list:
    """カテゴリページからリンクを辿って個別レシピページも取得する"""
    results = []
    links = set()
    for a in soup.find_all('a', href=True):
        href = a['href']
        if '/recipe/' in href or '/r/' in href:
            if href.startswith('http'):
                links.add(href)
            elif href.startswith('/'):
                domain = '/'.join(base_url.split('/')[:3])
                links.add(domain + href)
    links = list(links)[:10]  # 各カテゴリから最大10件
    for link in links:
        time.sleep(1)
        sub_soup = fetch_page(session, link)
        if sub_soup:
            recipes = extract_recipes_from_page(client, sub_soup, source + ' 詳細')
            results.extend(recipes)
    return results


def main():
    session = requests.Session()
    client = anthropic.Anthropic()
    all_recipes = []
    seen_names: set = set()

    for url, source in TARGET_URLS:
        print(f'取得中: {source} ({url})')
        soup = fetch_page(session, url)
        if not soup:
            continue

        # カテゴリページのテキストから直接抽出
        recipes = extract_recipes_from_page(client, soup, source)
        print(f'  → テキスト抽出: {len(recipes)}件')

        # 個別レシピページも辿る
        sub_recipes = fetch_individual_recipe_pages(session, client, soup, url, source)
        print(f'  → 個別ページ追加: {len(sub_recipes)}件')

        recipes.extend(sub_recipes)

        for r in recipes:
            name = r.get('name', '').strip()
            if not name or name in seen_names:
                continue
            seen_names.add(name)
            all_recipes.append({
                'name': name,
                'desc': r.get('desc', ''),
                'theme': r.get('theme', '普通'),
                'source': r.get('source', source),
                'ingredients': guess_ingredients(r.get('ingredients_text', '')),
                'ingredients_text': r.get('ingredients_text', ''),
                'recipe': r.get('recipe_steps', []),
            })

        time.sleep(2)

    if not all_recipes:
        print('レシピを取得できませんでした。')
        return

    # 既存データとマージ
    try:
        with open('recipe_sites_data.json', 'r', encoding='utf-8') as f:
            existing = json.load(f)
        existing_names = {r['name'] for r in existing.get('recipes', [])}
        new_count = 0
        for r in all_recipes:
            if r['name'] not in existing_names:
                existing['recipes'].append(r)
                new_count += 1
        merged = existing
        print(f'新規追加: {new_count}件')
    except Exception:
        merged = {'recipes': all_recipes}

    merged['updated'] = datetime.now().strftime('%Y-%m-%d')
    merged['count'] = len(merged['recipes'])

    with open('recipe_sites_data.json', 'w', encoding='utf-8') as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    print(f'完了: 合計 {merged["count"]} 件のレシピを保存')


if __name__ == '__main__':
    main()
