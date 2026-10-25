"""JAN コードで Keepa から Amazon.co.jp の価格・ランキングを取ってくる。

使い方:
    python -m research.keepa_lookup            # まだ調べていない JAN だけ調べる
    python -m research.keepa_lookup --refresh  # 全部調べ直す

Keepa のトークンは1商品につき1つ使う。足りなくなったら回復するまで自動で待つ。
"""

import argparse
import time
from datetime import datetime

import pandas as pd
import requests

from research.config import AMAZON_CSV, KEEPA_API_KEY, SD_PRODUCTS_CSV

API_URL = "https://api.keepa.com/product"
DOMAIN_JP = 5
# stats.current の並び（Keepa の CsvType）。日本の価格は「円」単位の整数、-1 は出品なし
AMAZON, NEW, SALES_RANK, NEW_FBM_SHIPPING, COUNT_NEW = 0, 1, 3, 7, 11
COLUMNS = ["JAN", "ASIN", "Amazon商品名", "新品最安値", "自己発送最安値_送料込", "Amazon本体価格",
           "ランキング", "新品出品者数", "販売手数料率", "月間販売数", "取得日時"]


def request_product(jan):
    params = {"key": KEEPA_API_KEY, "domain": DOMAIN_JP, "code": jan, "stats": 90, "history": 0}
    while True:
        r = requests.get(API_URL, params=params, timeout=60)
        if r.status_code == 429:
            try:
                wait = r.json().get("refillIn", 60000) / 1000 + 1
            except ValueError:
                wait = 60
            print(f"  トークン不足 → {wait:.0f}秒待ちます")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r.json()


def current_value(current, i):
    if not current or i >= len(current) or current[i] is None or current[i] < 0:
        return None
    return current[i]


def to_rows(jan, response):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for product in response.get("products") or []:
        current = (product.get("stats") or {}).get("current")
        rows.append({
            "JAN": jan,
            "ASIN": product.get("asin", ""),
            "Amazon商品名": product.get("title") or "",
            "新品最安値": current_value(current, NEW),
            "自己発送最安値_送料込": current_value(current, NEW_FBM_SHIPPING),
            "Amazon本体価格": current_value(current, AMAZON),
            "ランキング": current_value(current, SALES_RANK),
            "新品出品者数": current_value(current, COUNT_NEW),
            "販売手数料率": product.get("referralFeePercentage"),
            "月間販売数": product.get("monthlySold"),
            "取得日時": now,
        })
    if not rows:
        # Amazon に無かった JAN も記録して、次回また調べないようにする
        rows.append({"JAN": jan, "ASIN": "", "取得日時": now})
    return rows


def main():
    parser = argparse.ArgumentParser(description="Keepa で Amazon の価格を調べる")
    parser.add_argument("--refresh", action="store_true", help="調べ済みの JAN も調べ直す")
    args = parser.parse_args()

    if not KEEPA_API_KEY:
        print(".env の KEEPA_API_KEY が空です。Keepa の API キーを書いてください")
        return
    if not SD_PRODUCTS_CSV.exists():
        print("先に research.parse を実行してください")
        return

    sd = pd.read_csv(SD_PRODUCTS_CSV, dtype={"JAN": str}, encoding="utf-8-sig")
    jans = sorted(set(sd["JAN"].dropna()) - {""})
    done = pd.DataFrame(columns=COLUMNS)
    if AMAZON_CSV.exists() and not args.refresh:
        done = pd.read_csv(AMAZON_CSV, dtype={"JAN": str, "ASIN": str}, encoding="utf-8-sig")
    todo = [j for j in jans if j not in set(done["JAN"])]
    print(f"JAN {len(jans)}件のうち、これから調べるのは {len(todo)}件")

    rows = []

    def save():
        result = pd.concat([done, pd.DataFrame(rows, columns=COLUMNS)], ignore_index=True)
        result.to_csv(AMAZON_CSV, index=False, encoding="utf-8-sig")

    for i, jan in enumerate(todo, 1):
        try:
            response = request_product(jan)
        except requests.HTTPError as e:
            # キーの間違い・契約切れなどは、続けても全部失敗するので止める
            print(f"  [{i}/{len(todo)}] {jan} 失敗: {e}\nAPI キーと Keepa の契約状況を確認してください")
            break
        except requests.RequestException as e:
            print(f"  [{i}/{len(todo)}] {jan} 失敗: {e}")
            continue
        found = to_rows(jan, response)
        rows.extend(found)
        print(f"  [{i}/{len(todo)}] {jan} → {found[0]['ASIN'] or 'Amazon になし'}"
              f"（残りトークン {response.get('tokensLeft', '?')}）")
        if i % 20 == 0:
            save()

    save()
    print(f"✅ {AMAZON_CSV}")


if __name__ == "__main__":
    main()
