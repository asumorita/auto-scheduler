"""設定とファイルの置き場所。値は .env から読む。"""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# 集めたデータはすべて data/ に置く（.gitignore 済み。卸価格は会員限定なので公開しない）
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROFILE_DIR = DATA_DIR / "browser_profile"
INDEX_CSV = RAW_DIR / "index.csv"
SD_PRODUCTS_CSV = DATA_DIR / "sd_products.csv"
AMAZON_CSV = DATA_DIR / "amazon.csv"


def _env_float(name, default):
    value = os.getenv(name, "").strip()
    try:
        return float(value) if value else float(default)
    except ValueError:
        print(f"⚠️ .env の {name}={value!r} は数字ではないので {default} を使います")
        return float(default)


KEEPA_API_KEY = os.getenv("KEEPA_API_KEY", "").strip()
SHIPPING_COST = _env_float("SHIPPING_COST", 0)
MIN_PROFIT_RATE = _env_float("MIN_PROFIT_RATE", 10)
DEFAULT_FEE_RATE = _env_float("DEFAULT_FEE_RATE", 15)


def ensure_dirs():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
