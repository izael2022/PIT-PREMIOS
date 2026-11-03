import os
from pathlib import Path

BASE_DIR=Path(__file__).resolve().parent
BOT_TOKEN=os.getenv("BOT_TOKEN","").strip()
DATABASE_PATH=Path(os.getenv("DATABASE_PATH","data/pit_premios.db"))
if not DATABASE_PATH.is_absolute(): DATABASE_PATH=BASE_DIR/DATABASE_PATH

def parse_ids(raw):
    try:return {int(x.strip()) for x in raw.split(",") if x.strip()}
    except ValueError as exc:raise ValueError("ADMIN_IDS deve conter IDs numéricos.") from exc

ADMIN_IDS=parse_ids(os.getenv("ADMIN_IDS",""))
POINTS_PER_REFERRAL=max(0,int(os.getenv("POINTS_PER_REFERRAL","100")))
def parse_daily_rewards(raw):
    try:
        rewards=tuple(int(value.strip()) for value in raw.split(",") if value.strip())
    except ValueError as exc:
        raise ValueError("DAILY_REWARDS deve conter apenas números inteiros separados por vírgula.") from exc
    if not rewards or any(value < 0 for value in rewards):
        raise ValueError("DAILY_REWARDS deve conter pelo menos um valor, todos iguais ou maiores que zero.")
    return rewards

# Recompensas dos dias 1 a 7; depois a sequência recomeça.
DAILY_REWARDS=parse_daily_rewards(os.getenv("DAILY_REWARDS","3,4,5,6,7,8,10"))
# Mantido para compatibilidade com configurações antigas; o check-in usa DAILY_REWARDS.
DAILY_REWARD=max(0,int(os.getenv("DAILY_REWARD","2")))
MIN_REDEEM_POINTS=max(1,int(os.getenv("MIN_REDEEM_POINTS","1000")))
if not BOT_TOKEN:raise RuntimeError("Configure BOT_TOKEN nas variáveis de ambiente.")
if not ADMIN_IDS:raise RuntimeError("Configure ADMIN_IDS nas variáveis de ambiente.")

# URL secreta de heartbeat fornecida por um monitor externo (ex.: Better Stack).
MONITOR_HEARTBEAT_URL=os.getenv("MONITOR_HEARTBEAT_URL","").strip()
