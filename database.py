import sqlite3
from contextlib import contextmanager
from config import DATABASE_PATH

@contextmanager
def connect():
    DATABASE_PATH.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(str(DATABASE_PATH),timeout=20)
    db.row_factory=sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=20000")
    try:
        yield db
    finally:
        db.close()

def init_db():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY,username TEXT,first_name TEXT NOT NULL DEFAULT '',points INTEGER NOT NULL DEFAULT 0 CHECK(points>=0),referred_by INTEGER,is_vip INTEGER NOT NULL DEFAULT 0,created_at TEXT DEFAULT CURRENT_TIMESTAMP,last_daily TEXT,daily_streak INTEGER NOT NULL DEFAULT 0,FOREIGN KEY(referred_by) REFERENCES users(user_id));
        CREATE TABLE IF NOT EXISTS point_history(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,amount INTEGER NOT NULL,reason TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY(user_id) REFERENCES users(user_id));
        CREATE TABLE IF NOT EXISTS redemptions(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,points INTEGER NOT NULL,reward TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',created_at TEXT DEFAULT CURRENT_TIMESTAMP,reviewed_by INTEGER,FOREIGN KEY(user_id) REFERENCES users(user_id));
        CREATE INDEX IF NOT EXISTS idx_history_user ON point_history(user_id);
        CREATE INDEX IF NOT EXISTS idx_redemption_status ON redemptions(status);
        CREATE TABLE IF NOT EXISTS referral_milestones(
            user_id INTEGER NOT NULL,
            milestone INTEGER NOT NULL,
            bonus_points INTEGER NOT NULL,
            claimed_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(user_id,milestone),
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        );
        CREATE TABLE IF NOT EXISTS referral_reviews(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER NOT NULL,
            referred_user_id INTEGER NOT NULL UNIQUE,
            risk_level TEXT NOT NULL DEFAULT 'normal',
            risk_reason TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            reviewed_by INTEGER,
            reviewed_at TEXT,
            FOREIGN KEY(referrer_id) REFERENCES users(user_id),
            FOREIGN KEY(referred_user_id) REFERENCES users(user_id)
        );
        CREATE INDEX IF NOT EXISTS idx_referral_reviews_status ON referral_reviews(status);
        CREATE TABLE IF NOT EXISTS payout_requests(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            points INTEGER NOT NULL CHECK(points > 0),
            amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
            pix_key TEXT NOT NULL,
            pix_key_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            reviewed_by INTEGER,
            reviewed_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        );
        CREATE INDEX IF NOT EXISTS idx_payout_status ON payout_requests(status);
        CREATE TABLE IF NOT EXISTS bot_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        """)
        columns={r["name"] for r in db.execute("PRAGMA table_info(users)")}
        if "daily_streak" not in columns:
            db.execute("ALTER TABLE users ADD COLUMN daily_streak INTEGER NOT NULL DEFAULT 0")
        db.commit()

def get_auto_delete_settings():
    with connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS bot_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
        rows={r["key"]:r["value"] for r in db.execute("SELECT key,value FROM bot_settings WHERE key IN ('auto_delete_enabled','auto_delete_seconds')")}
        return {"enabled":rows.get("auto_delete_enabled","0")=="1","seconds":int(rows.get("auto_delete_seconds","60"))}

def set_auto_delete_settings(enabled=None,seconds=None):
    with connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS bot_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
        if enabled is not None: db.execute("INSERT INTO bot_settings(key,value) VALUES('auto_delete_enabled',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",("1" if enabled else "0",))
        if seconds is not None:
            if seconds not in (30,60,120,300): raise ValueError("Tempo inválido.")
            db.execute("INSERT INTO bot_settings(key,value) VALUES('auto_delete_seconds',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(str(seconds),))
        db.commit()
def today():
    from datetime import datetime, timezone, timedelta
    return datetime.now(timezone(timedelta(hours=-3))).date().isoformat()

def get_profile(uid):
    with connect() as db:
        row=db.execute("SELECT u.*, (SELECT COUNT(*) FROM users x LEFT JOIN referral_reviews rr ON rr.referred_user_id=x.user_id WHERE x.referred_by=u.user_id AND (rr.status IS NULL OR rr.status='approved')) referrals FROM users u WHERE user_id=?",(uid,)).fetchone()
        return dict(row) if row else {"points":0,"referrals":0,"daily_streak":0,"created_at":today(),"last_daily":None}

def top_referrals(limit=10):
    with connect() as db:
        return db.execute("SELECT u.user_id,u.first_name,COUNT(x.user_id) referrals FROM users u JOIN users x ON x.referred_by=u.user_id LEFT JOIN referral_reviews rr ON rr.referred_user_id=x.user_id WHERE rr.status IS NULL OR rr.status='approved' GROUP BY u.user_id ORDER BY referrals DESC LIMIT ?",(limit,)).fetchall()

def history(uid,limit=8):
    with connect() as db:
        return db.execute("SELECT amount,reason,created_at FROM point_history WHERE user_id=? ORDER BY id DESC LIMIT ?",(uid,limit)).fetchall()

def register_user(uid,username,first_name,referrer=None,referral_reward=0,is_bot=False):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM users WHERE user_id=?",(uid,)).fetchone():
            db.execute("UPDATE users SET username=?,first_name=? WHERE user_id=?",(username,first_name,uid)); db.commit(); return False,None,None
        if referrer==uid or (referrer and not db.execute("SELECT 1 FROM users WHERE user_id=?",(referrer,)).fetchone()): referrer=None
        db.execute("INSERT INTO users(user_id,username,first_name,referred_by) VALUES(?,?,?,?)",(uid,username,first_name,referrer))
        review_id=None
        if referrer:
            reasons=[]
            if is_bot: reasons.append("Conta do Telegram identificada como bot")
            recent=db.execute("SELECT COUNT(*) total FROM users WHERE referred_by=? AND created_at>=datetime('now','-10 minutes')",(referrer,)).fetchone()["total"]
            if recent>=3: reasons.append("Volume elevado de cadastros em 10 minutos")
            if reasons:
                cur=db.execute("INSERT INTO referral_reviews(referrer_id,referred_user_id,risk_level,risk_reason,status) VALUES(?,?,?,?, 'pending')",(referrer,uid,"review","; ".join(reasons)))
                review_id=cur.lastrowid
            elif referral_reward>0:
                db.execute("UPDATE users SET points=points+? WHERE user_id=?",(referral_reward,referrer))
                db.execute("INSERT INTO point_history(user_id,amount,reason) VALUES(?,?,?)",(referrer,referral_reward,f"Indicação do usuário {uid}"))
        db.commit(); return True,referrer,review_id
def get_user(uid):
    with connect() as db: return db.execute("SELECT * FROM users WHERE user_id=?",(uid,)).fetchone()

def all_user_ids():
    with connect() as db:
        return [row["user_id"] for row in db.execute("SELECT user_id FROM users ORDER BY user_id").fetchall()]

def add_points(uid,amount,reason):
    if amount==0:return
    with connect() as db:
        db.execute("BEGIN IMMEDIATE"); row=db.execute("SELECT points FROM users WHERE user_id=?",(uid,)).fetchone()
        if not row:
            if amount<0: raise ValueError("Usuário não encontrado.")
            db.execute("INSERT INTO users(user_id) VALUES(?)",(uid,))
        elif row["points"]+amount<0: raise ValueError("Saldo insuficiente.")
        db.execute("UPDATE users SET points=points+? WHERE user_id=?",(amount,uid))
        db.execute("INSERT INTO point_history(user_id,amount,reason) VALUES(?,?,?)",(uid,amount,reason)); db.commit()

def daily_claim(uid,reward):
    from datetime import datetime, timezone, timedelta
    now=datetime.now(timezone(timedelta(hours=-3))); current=now.date().isoformat()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row=db.execute("SELECT last_daily,daily_streak FROM users WHERE user_id=?",(uid,)).fetchone()
        if not row or row["last_daily"]==current:
            db.rollback(); return False,(row["daily_streak"] if row else 0)
        yesterday=(now.date()-timedelta(days=1)).isoformat()
        streak=row["daily_streak"]+1 if row["last_daily"]==yesterday else 1
        db.execute("UPDATE users SET last_daily=?,daily_streak=?,points=points+? WHERE user_id=?",(current,streak,reward,uid))
        db.execute("INSERT INTO point_history(user_id,amount,reason) VALUES(?,?,?)",(uid,reward,"Bônus diário"))
        db.commit(); return True,streak

def ranking(limit=10):
    with connect() as db: return db.execute("SELECT user_id,first_name,username,points FROM users ORDER BY points DESC LIMIT ?",(limit,)).fetchall()

def create_redemption(uid,points,reward):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE"); row=db.execute("SELECT points FROM users WHERE user_id=?",(uid,)).fetchone()
        if not row or row["points"]<points: db.rollback(); raise ValueError("Saldo insuficiente.")
        db.execute("UPDATE users SET points=points-? WHERE user_id=?",(points,uid))
        cur=db.execute("INSERT INTO redemptions(user_id,points,reward) VALUES(?,?,?)",(uid,points,reward)); rid=cur.lastrowid
        db.execute("INSERT INTO point_history(user_id,amount,reason) VALUES(?,?,?)",(uid,-points,f"Resgate #{rid}")); db.commit(); return rid

def pending_redemptions():
    with connect() as db: return db.execute("SELECT * FROM redemptions WHERE status='pending' ORDER BY id").fetchall()

def review_redemption(rid,admin_id,approve):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE"); row=db.execute("SELECT * FROM redemptions WHERE id=? AND status='pending'",(rid,)).fetchone()
        if not row: db.rollback(); return None
        status="approved" if approve else "rejected"
        db.execute("UPDATE redemptions SET status=?,reviewed_by=? WHERE id=?",(status,admin_id,rid))
        if not approve:
            db.execute("UPDATE users SET points=points+? WHERE user_id=?",(row["points"],row["user_id"]))
            db.execute("INSERT INTO point_history(user_id,amount,reason) VALUES(?,?,?)",(row["user_id"],row["points"],f"Estorno resgate #{rid}"))
        db.commit(); return dict(row)

def set_vip(uid,enabled):
    with connect() as db: db.execute("UPDATE users SET is_vip=? WHERE user_id=?",(int(enabled),uid)); db.commit()

def stats():
    with connect() as db:
        total=dict(db.execute("SELECT COUNT(*) users,COALESCE(SUM(points),0) points FROM users").fetchone())
        total.update(dict(db.execute("SELECT COUNT(*) pending FROM redemptions WHERE status='pending'").fetchone())); return total

def referral_milestone_status(uid):
    milestones={1:100,5:650,10:1400}
    with connect() as db:
        row=db.execute("SELECT COUNT(*) total FROM users x LEFT JOIN referral_reviews rr ON rr.referred_user_id=x.user_id WHERE x.referred_by=? AND (rr.status IS NULL OR rr.status='approved')",(uid,)).fetchone()
        claimed={r["milestone"] for r in db.execute("SELECT milestone FROM referral_milestones WHERE user_id=?",(uid,))}
        total=row["total"]
        return [{"milestone":m,"bonus":bonus,"reached":total>=m,"claimed":m in claimed} for m,bonus in milestones.items()]

def claim_referral_milestone(uid,milestone):
    bonuses={1:100,5:650,10:1400}
    if milestone not in bonuses: raise ValueError("Meta inválida.")
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        total=db.execute("SELECT COUNT(*) total FROM users x LEFT JOIN referral_reviews rr ON rr.referred_user_id=x.user_id WHERE x.referred_by=? AND (rr.status IS NULL OR rr.status='approved')",(uid,)).fetchone()["total"]
        if total<milestone:
            db.rollback(); raise ValueError("Meta ainda não foi concluída.")
        try:
            db.execute("INSERT INTO referral_milestones(user_id,milestone,bonus_points) VALUES(?,?,?)",(uid,milestone,bonuses[milestone]))
        except sqlite3.IntegrityError:
            db.rollback(); raise ValueError("Essa recompensa já foi recebida.")
        db.execute("UPDATE users SET points=points+? WHERE user_id=?",(bonuses[milestone],uid))
        db.execute("INSERT INTO point_history(user_id,amount,reason) VALUES(?,?,?)",(uid,bonuses[milestone],f"Bônus da meta de {milestone} indicações"))
        db.commit(); return bonuses[milestone]

def create_payout_request(uid,points,pix_key,pix_key_type,min_points=1000):
    pix_key=pix_key.strip()
    if points<min_points or points%100!=0: raise ValueError("O saque mínimo é 1.000 pontos e o valor deve ser múltiplo de 100.")
    if not pix_key or len(pix_key)>200: raise ValueError("Chave Pix inválida.")
    if pix_key_type not in ("CPF","CNPJ","EMAIL","TELEFONE","ALEATORIA"): raise ValueError("Tipo de chave Pix inválido.")
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row=db.execute("SELECT points FROM users WHERE user_id=?",(uid,)).fetchone()
        if not row or row["points"]<points:
            db.rollback(); raise ValueError("Saldo insuficiente.")
        pending=db.execute("SELECT 1 FROM payout_requests WHERE user_id=? AND status='pending'",(uid,)).fetchone()
        if pending:
            db.rollback(); raise ValueError("Você já possui um saque aguardando análise.")
        db.execute("UPDATE users SET points=points-? WHERE user_id=?",(points,uid))
        cur=db.execute("INSERT INTO payout_requests(user_id,points,amount_cents,pix_key,pix_key_type) VALUES(?,?,?,?,?)",(uid,points,points, pix_key,pix_key_type))
        rid=cur.lastrowid
        db.execute("INSERT INTO point_history(user_id,amount,reason) VALUES(?,?,?)",(uid,-points,f"Reserva para saque #{rid}"))
        db.commit(); return rid

def pending_payouts():
    with connect() as db:
        return db.execute("SELECT * FROM payout_requests WHERE status='pending' ORDER BY id").fetchall()

def review_payout(rid,admin_id,approve):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row=db.execute("SELECT * FROM payout_requests WHERE id=? AND status='pending'",(rid,)).fetchone()
        if not row:
            db.rollback(); return None
        status="approved" if approve else "rejected"
        db.execute("UPDATE payout_requests SET status=?,reviewed_by=?,reviewed_at=CURRENT_TIMESTAMP WHERE id=?",(status,admin_id,rid))
        if not approve:
            db.execute("UPDATE users SET points=points+? WHERE user_id=?",(row["points"],row["user_id"]))
            db.execute("INSERT INTO point_history(user_id,amount,reason) VALUES(?,?,?)",(row["user_id"],row["points"],f"Estorno do saque #{rid}"))
        db.commit(); return dict(row)

def pending_referral_reviews():
    with connect() as db:
        return db.execute("SELECT rr.*,u.first_name,u.username FROM referral_reviews rr JOIN users u ON u.user_id=rr.referred_user_id WHERE rr.status='pending' ORDER BY rr.id").fetchall()

def review_referral(rid,admin_id,approve):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row=db.execute("SELECT * FROM referral_reviews WHERE id=? AND status='pending'",(rid,)).fetchone()
        if not row:
            db.rollback(); return None
        status="approved" if approve else "rejected"
        db.execute("UPDATE referral_reviews SET status=?,reviewed_by=?,reviewed_at=CURRENT_TIMESTAMP WHERE id=?",(status,admin_id,rid))
        if approve:
            db.execute("UPDATE users SET points=points+100 WHERE user_id=?",(row["referrer_id"],))
            db.execute("INSERT INTO point_history(user_id,amount,reason) VALUES(?,?,?)",(row["referrer_id"],100,f"Indicação aprovada #{rid}"))
        db.commit(); return dict(row)
