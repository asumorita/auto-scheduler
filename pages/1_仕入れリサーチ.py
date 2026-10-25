import pandas as pd
import streamlit as st

from research import config
from research.keepa_lookup import COLUMNS as AMAZON_COLUMNS
from research.profit import REFERENCE_PRICES, add_profit_columns

# ページ設定
st.set_page_config(page_title="仕入れリサーチ", page_icon="💰", layout="wide")

st.title("💰 仕入れリサーチ")
st.write("スーパーデリバリーの仕入れ値と Amazon の価格を比べて、利益が出る商品を探します")
st.warning("⚠️ 卸価格は会員限定の情報です。この画面は自分の PC だけで使い、Streamlit Cloud などで公開しないでください。")

if not config.SD_PRODUCTS_CSV.exists():
    st.info("まだデータがありません。3_collect.bat → 4_keepa.bat の順に実行してください。")
    st.stop()

sd = pd.read_csv(config.SD_PRODUCTS_CSV, dtype={"商品ID": str, "企業ID": str, "JAN": str}, encoding="utf-8-sig")
if config.AMAZON_CSV.exists():
    amazon = pd.read_csv(config.AMAZON_CSV, dtype={"JAN": str, "ASIN": str}, encoding="utf-8-sig")
else:
    amazon = pd.DataFrame(columns=AMAZON_COLUMNS)
    st.info("Amazon の価格がまだありません。4_keepa.bat を実行してください。")

# サイドバー：計算の条件
st.sidebar.header("🧮 計算の条件")
set_qty = st.sidebar.selectbox("セット数", [1, 2, 3], index=1)
use_bulk_price = st.sidebar.radio("仕入れ単価", ["まとめ買い価格", "単品価格"]) == "まとめ買い価格"
reference = st.sidebar.selectbox("Amazon の基準価格", list(REFERENCE_PRICES))
shipping = st.sidebar.number_input("送料（1回分・円）", min_value=0, value=int(config.SHIPPING_COST), step=10)
tax_rate = st.sidebar.number_input("仕入れ値に足す消費税（%）", min_value=0, value=10, step=1,
                                   help="仕入れ価格が税抜なら 10（食品などは 8）。税込なら 0")
default_fee_rate = st.sidebar.number_input("販売手数料率（Keepa に無いとき・%）", min_value=0.0,
                                           value=config.DEFAULT_FEE_RATE, step=0.5)
min_rate = st.sidebar.number_input("利益率がこれ以上（%）", value=config.MIN_PROFIT_RATE, step=1.0)

df = sd.merge(amazon[amazon["ASIN"].fillna("") != ""], on="JAN", how="inner")
df = add_profit_columns(df, reference=reference, set_qty=set_qty, use_bulk_price=use_bulk_price,
                        tax_rate=tax_rate, shipping=shipping, default_fee_rate=default_fee_rate)
df["Amazon"] = "https://www.amazon.co.jp/dp/" + df["ASIN"]
hits = df[df["利益率"] >= min_rate].sort_values("利益率", ascending=False)

col1, col2, col3, col4 = st.columns(4)
col1.metric("集めた商品", len(sd))
col2.metric("JAN あり", int((sd["JAN"].fillna("") != "").sum()))
col3.metric("Amazon で見つかった", df["商品ID"].nunique())
col4.metric(f"利益率 {min_rate:g}% 以上", hits["商品ID"].nunique())

st.subheader(f"📈 儲かる商品（{set_qty}個セット・自己発送）")
columns = ["商品名", "JAN", "利益率", "利益", "販売価格", "仕入れ値", "販売手数料", "送料", "基準価格",
           "単品価格", "まとめ買い価格", "まとめ買い数量", "ランキング", "新品出品者数", "月間販売数",
           "Amazon商品名", "Amazon", "商品URL"]
st.dataframe(
    hits[columns],
    hide_index=True,
    column_config={
        "利益率": st.column_config.NumberColumn(format="%.1f%%"),
        "Amazon": st.column_config.LinkColumn(display_text="Amazon"),
        "商品URL": st.column_config.LinkColumn("スーパーデリバリー", display_text="開く"),
    },
)

csv = hits[columns].to_csv(index=False).encode("utf-8-sig")
st.download_button("📥 この一覧を CSV でダウンロード", data=csv, file_name="profitable_items.csv", mime="text/csv")

with st.expander("Amazon と照合できなかった商品"):
    no_jan = sd[sd["JAN"].fillna("") == ""]
    not_found = sd[(sd["JAN"].fillna("") != "") & ~sd["JAN"].isin(df["JAN"])]
    st.write(f"JAN が読み取れなかった: {len(no_jan)}件 / Amazon に見つからなかった・未照合: {len(not_found)}件")
    st.dataframe(pd.concat([no_jan, not_found])[["商品名", "JAN", "単品価格", "商品URL"]], hide_index=True)

st.caption("※ 販売価格は「基準価格 × セット数」で計算しています。大口出品の月額料金などの固定費は含みません。")
