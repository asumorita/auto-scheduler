"""自己発送で N 個セットを売ったときの利益を計算する。

利益 = 販売価格 − 販売手数料 − 仕入れ値 − 送料（1回分）
  販売価格   = Amazon の基準価格 × セット数
  販売手数料 = 販売価格 × 手数料率（Keepa の値。無ければ設定のデフォルト値）
  仕入れ値   = 仕入れ単価 × セット数（必要なら消費税を足す）
"""

import pandas as pd

REFERENCE_PRICES = {
    "新品最安値（送料別）": "新品最安値",
    "自己発送の最安値（送料込）": "自己発送最安値_送料込",
    "Amazon本体の価格": "Amazon本体価格",
}


def add_profit_columns(df, *, reference, set_qty, use_bulk_price, tax_rate, shipping, default_fee_rate):
    df = df.copy()
    df["基準価格"] = pd.to_numeric(df[REFERENCE_PRICES[reference]], errors="coerce")

    single = pd.to_numeric(df["単品価格"], errors="coerce")
    bulk = pd.to_numeric(df["まとめ買い価格"], errors="coerce")
    # まとめ買い価格が無い商品は単品価格で計算する
    df["仕入れ単価"] = bulk.fillna(single) if use_bulk_price else single

    fee_rate = pd.to_numeric(df["販売手数料率"], errors="coerce").fillna(default_fee_rate) / 100
    df["販売価格"] = df["基準価格"] * set_qty
    df["販売手数料"] = (df["販売価格"] * fee_rate).round()
    df["仕入れ値"] = (df["仕入れ単価"] * set_qty * (1 + tax_rate / 100)).round()
    df["送料"] = shipping
    df["利益"] = df["販売価格"] - df["販売手数料"] - df["仕入れ値"] - df["送料"]
    df["利益率"] = (df["利益"] / df["販売価格"] * 100).round(1)
    return df
