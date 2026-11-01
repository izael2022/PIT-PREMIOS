import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
BASE_DIR=Path(__file__).resolve().parent
BOT_TOKEN=os.getenv("BOT_TOKEN","").strip()
DATABASE_PATH=Path(os.getenv("DATABASE_PATH","data/pit_premios.db"))
if not DATABASE_PATH.is_absolute(): DATABASE_PATH=BASE_DIR/DATABASE_PATH
def parse_ids(raw):
    try: return {int(x.strip()) for x in raw.split(",") if x.strip()}
    except ValueError as e: raise ValueError("ADMIN_IDS deve conter IDs numéricos.") from e
ADMIN_IDS=parse_ids(os.getenv("ADMIN_IDS",""))
POINTS_PER_REFERRAL=max(0,int(os.getenv("POINTS_PER_REFERRAL","10")))
DAILY_REWARD=max(0,int(os.getenv("DAILY_REWARD","2")))
MIN_REDEEM_POINTS=max(1,int(os.getenv("MIN_REDEEM_POINTS","100")))
if not BOT_TOKEN: raise RuntimeError("Configure BOT_TOKEN no .env.")
if not ADMIN_IDS: raise RuntimeError("Configure ADMIN_IDS no .env.")
