"""スーパーデリバリーの商品ページを、自分のブラウザーで1件ずつ開いて保存する。

使い方:
    python -m research.collect                       # URL を聞かれるので貼り付ける
    python -m research.collect <企業の商品一覧URL> ...
    python -m research.collect --limit 2 <URL>       # 見本用に2件だけ

ブラウザーが開いたら自分でログインし、終わったらこの画面で Enter を押す。
パスワードはこのプログラムには渡らない（ブラウザーにだけ入力する）。
保存したページは data/raw/ に入る。途中で止めても、次回は続きから再開する。
"""

import argparse
import csv
import random
import re
import time
from datetime import datetime
from urllib.parse import urljoin

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from research.config import INDEX_CSV, PROFILE_DIR, RAW_DIR, ensure_dirs

TOP_URL = "https://www.superdelivery.com/"
PRODUCT_URL_RE = re.compile(r"/p/r/pd_p/(\d+)/")
SUPPLIER_URL_RE = re.compile(r"/p/do/dpsl/(\d+)/")
INDEX_FIELDS = ["商品ID", "企業ID", "商品URL", "一覧URL", "保存日時"]

# 「次のページ」リンクを探す。同じ企業の一覧ページへのリンクだけを対象にする
FIND_NEXT_JS = """
(supplierPath) => {
  const sameSupplier = (a) => a.href && a.href.includes(supplierPath);
  const rel = [...document.querySelectorAll('a[rel="next"]')].find(sameSupplier);
  if (rel) return rel.href;
  const labels = ["次へ", "次のページ", "次", "›", "»", ">"];
  const a = [...document.querySelectorAll("a[href]")]
    .find((el) => sameSupplier(el) && labels.includes(el.textContent.trim()));
  return a ? a.href : null;
}
"""


def polite_wait(delay):
    # サーバーに負担をかけないよう、毎回少しずつ間隔を変えて待つ
    time.sleep(delay + random.uniform(0, 2))


def ask_urls():
    print("企業の商品一覧ページ（または商品ページ）の URL を貼り付けて Enter（複数なら1行に1つ。空のまま Enter で開始）")
    urls = []
    while True:
        line = input("> ").strip()
        if not line:
            return urls
        urls.append(line)


def open_browser(p):
    # 自分の PC の Chrome を使う。ログイン状態は data/browser_profile に残るので、次回はログイン不要のことが多い
    options = dict(user_data_dir=str(PROFILE_DIR), headless=False, no_viewport=True)
    try:
        return p.chromium.launch_persistent_context(channel="chrome", **options)
    except PlaywrightError:
        print("Chrome が見つからないので、Playwright の Chromium を使います")
        return p.chromium.launch_persistent_context(**options)


def collect_product_urls(page, list_url, max_pages, delay):
    m = SUPPLIER_URL_RE.search(list_url)
    supplier_id = m.group(1) if m else "unknown"
    products = {}
    visited = set()
    url = list_url
    for n in range(1, max_pages + 1):
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
        (RAW_DIR / f"list_{supplier_id}_p{n}.html").write_text(page.content(), encoding="utf-8")
        visited.add(url)

        new = 0
        for href in page.eval_on_selector_all("a[href*='/p/r/pd_p/']", "els => els.map(e => e.href)"):
            pm = PRODUCT_URL_RE.search(href)
            if pm and pm.group(1) not in products:
                products[pm.group(1)] = urljoin(TOP_URL, pm.group(0))
                new += 1
        print(f"  一覧 {n}ページ目: 新しい商品 {new}件（合計 {len(products)}件）")

        next_url = page.evaluate(FIND_NEXT_JS, f"/p/do/dpsl/{supplier_id}/")
        if not next_url or next_url in visited or new == 0:
            break
        url = next_url
        polite_wait(delay)
    return supplier_id, products


def append_index(row):
    is_new = not INDEX_CSV.exists()
    with INDEX_CSV.open("a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=INDEX_FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow(row)


def main():
    parser = argparse.ArgumentParser(description="スーパーデリバリーの商品ページを保存する")
    parser.add_argument("urls", nargs="*", help="企業の商品一覧ページの URL")
    parser.add_argument("--limit", type=int, default=0, help="1社あたりの最大件数（0 = 全部）")
    parser.add_argument("--max-pages", type=int, default=100, help="一覧ページをたどる最大ページ数")
    parser.add_argument("--delay", type=float, default=3.0, help="ページを開く間隔（秒）")
    parser.add_argument("--refresh", action="store_true", help="保存済みの商品も取り直す")
    args = parser.parse_args()

    urls = args.urls or ask_urls()
    if not urls:
        print("URL がないので終了します")
        return
    ensure_dirs()

    with sync_playwright() as p:
        context = open_browser(p)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(TOP_URL)
        input("\nブラウザーでスーパーデリバリーにログインしてください。終わったらここで Enter → ")

        for list_url in urls:
            print(f"\n■ {list_url}")
            single = PRODUCT_URL_RE.search(list_url)
            if single:
                # 商品ページの URL がそのまま貼られたときは、その1件だけ保存する
                supplier_id, products = "", {single.group(1): urljoin(TOP_URL, single.group(0))}
            else:
                supplier_id, products = collect_product_urls(page, list_url, args.max_pages, args.delay)
            items = list(products.items())
            if args.limit:
                items = items[: args.limit]

            for i, (product_id, product_url) in enumerate(items, 1):
                out = RAW_DIR / f"product_{product_id}.html"
                if out.exists() and not args.refresh:
                    print(f"  [{i}/{len(items)}] {product_id} は保存済み → スキップ")
                    continue
                polite_wait(args.delay)
                try:
                    page.goto(product_url, wait_until="domcontentloaded")
                    page.wait_for_timeout(1500)
                    out.write_text(page.content(), encoding="utf-8")
                except PlaywrightError as e:
                    print(f"  [{i}/{len(items)}] {product_id} 失敗: {e}")
                    continue
                append_index({
                    "商品ID": product_id,
                    "企業ID": supplier_id,
                    "商品URL": product_url,
                    "一覧URL": list_url,
                    "保存日時": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })
                print(f"  [{i}/{len(items)}] {product_id} 保存")

        context.close()
    print(f"\n✅ 完了。保存先: {RAW_DIR}")


if __name__ == "__main__":
    main()
