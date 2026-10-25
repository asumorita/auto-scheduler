"""保存した商品ページ(HTML)から、商品名・JAN・価格を取り出して CSV にする。

使い方:
    python -m research.parse                                   # data/raw の商品ページを全部読む
    python -m research.parse --diagnose data/raw/product_123.html

⚠️ 価格の読み取りルール（PRICE_PATTERNS）は、実際のページ見本を見る前の「仮」です。
   --diagnose の出力を見て調整する。読み取れなかった値は空欄のまま（推測で埋めない）。
"""

import argparse
import re
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup, NavigableString

from research.config import DATA_DIR, INDEX_CSV, RAW_DIR, SD_PRODUCTS_CSV

DIAGNOSE_TXT = DATA_DIR / "diagnose.txt"

YEN = r"([0-9][0-9,]*)\s*円"
JAN_RE = re.compile(r"JAN[^0-9]{0,15}(\d{13}|\d{8})(?!\d)")
PRICE_PATTERNS = {
    "上代": [r"上代", r"希望小売価格", r"参考小売価格"],
    "単品価格": [r"卸価格", r"卸単価", r"単価"],
}
BULK_RE = re.compile(r"(\d+)\s*(?:個|点|枚|本|セット)以上[^0-9円]{0,20}" + YEN)
COLUMNS = ["商品ID", "企業ID", "商品名", "JAN", "単品価格", "まとめ買い価格", "まとめ買い数量", "上代", "商品URL"]
DIAGNOSE_WORDS =("円", "JAN", "上代", "卸", "単価", "まとめ", "以上", "セット", "入数", "ロット", "ログイン")


def to_int(text):
    return int(text.replace(",", ""))


def page_text(soup):
    lines = (line.strip() for line in soup.get_text("\n").splitlines())
    return " ".join(line for line in lines if line)


def product_name(soup):
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        return og["content"].strip()
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        return h1.get_text(strip=True)
    return soup.title.get_text(strip=True) if soup.title else ""


def find_price(text, labels):
    for label in labels:
        m = re.search(label + r"[^0-9円]{0,20}" + YEN, text)
        if m:
            return to_int(m.group(1))
    return None


def parse_product(html):
    soup = BeautifulSoup(html, "lxml")
    text = page_text(soup)
    jan = JAN_RE.search(text)
    bulk = BULK_RE.search(text)
    row = {
        "商品名": product_name(soup),
        "JAN": jan.group(1) if jan else "",
        "まとめ買い数量": int(bulk.group(1)) if bulk else None,
        "まとめ買い価格": to_int(bulk.group(2)) if bulk else None,
    }
    for column, labels in PRICE_PATTERNS.items():
        row[column] = find_price(text, labels)
    return row


def element_path(el):
    parts = []
    while el is not None and el.name not in (None, "[document]", "html", "body") and len(parts) < 4:
        name = el.name
        if el.get("id"):
            name += "#" + el["id"]
        elif el.get("class"):
            name += "." + ".".join(el["class"])
        parts.append(name)
        el = el.parent
    return " > ".join(reversed(parts))


def diagnose(path):
    """価格やJANがページのどこにあるかを一覧にする（読み取りルールの調整用）。"""
    soup = BeautifulSoup(Path(path).read_text(encoding="utf-8"), "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    lines = [
        f"ファイル: {Path(path).name}",
        f"商品名の候補: {product_name(soup)}",
        f"今のルールでの読み取り結果: {parse_product(str(soup))}",
        "",
    ]
    seen = set()
    for node in soup.find_all(string=True):
        if not isinstance(node, NavigableString) or not node.strip():
            continue
        if not any(word in node for word in DIAGNOSE_WORDS):
            continue
        parent = node.parent
        context = " ".join(parent.get_text(" ", strip=True).split())[:120]
        key = (element_path(parent), context)
        if key in seen:
            continue
        seen.add(key)
        lines += [f"[{key[0]}]", f"    {context}"]
        if len(seen) >= 200:
            lines.append("…（200件で打ち切り）")
            break
    return "\n".join(lines)


def load_index():
    if not INDEX_CSV.exists():
        return pd.DataFrame(columns=["商品ID", "企業ID", "商品URL"])
    index = pd.read_csv(INDEX_CSV, dtype=str, encoding="utf-8-sig")
    return index.drop_duplicates("商品ID", keep="last")


def main():
    parser = argparse.ArgumentParser(description="保存した商品ページを CSV にする")
    parser.add_argument("--diagnose", metavar="HTML", nargs="?", const="latest",
                        help="価格・JANの位置を表示する（ファイル省略時は最後に保存した商品ページ3件）")
    args = parser.parse_args()
    if args.diagnose:
        if args.diagnose == "latest":
            paths = sorted(RAW_DIR.glob("product_*.html"), key=lambda p: p.stat().st_mtime)[-3:]
            if not paths:
                print(f"商品ページがありません。先に research.collect を実行してください（{RAW_DIR}）")
                return
        else:
            paths = [args.diagnose]
        report = ("\n\n" + "=" * 60 + "\n\n").join(diagnose(path) for path in paths)
        print(report)
        DIAGNOSE_TXT.write_text(report, encoding="utf-8")
        print(f"\n（同じ内容を {DIAGNOSE_TXT} に保存しました）")
        return

    index = load_index().set_index("商品ID")
    rows = []
    for path in sorted(RAW_DIR.glob("product_*.html")):
        product_id = path.stem.removeprefix("product_")
        row = {"商品ID": product_id}
        row.update(parse_product(path.read_text(encoding="utf-8")))
        if product_id in index.index:
            row["企業ID"] = index.at[product_id, "企業ID"]
            row["商品URL"] = index.at[product_id, "商品URL"]
        rows.append(row)

    if not rows:
        print(f"商品ページがありません。先に research.collect を実行してください（{RAW_DIR}）")
        return
    df = pd.DataFrame(rows).reindex(columns=COLUMNS)
    df.to_csv(SD_PRODUCTS_CSV, index=False, encoding="utf-8-sig")
    print(f"✅ {len(df)}件 → {SD_PRODUCTS_CSV}")
    print(f"   JAN あり {(df['JAN'] != '').sum()}件 / 単品価格あり {df['単品価格'].notna().sum()}件"
          f" / まとめ買い価格あり {df['まとめ買い価格'].notna().sum()}件")


if __name__ == "__main__":
    main()
