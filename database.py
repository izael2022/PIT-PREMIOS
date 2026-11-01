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
        CREATE TABLE IF NOT EXISTS tasks(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            reward_points INTEGER NOT NULL CHECK(reward_points>0),
            requires_proof INTEGER NOT NULL DEFAULT 1,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS task_submissions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            proof TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            reviewed_by INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            reviewed_at TEXT,
            UNIQUE(task_id,user_id),
            FOREIGN KEY(task_id) REFERENCES tasks(id),
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        );
        CREATE INDEX IF NOT EXISTS idx_task_submissions_status ON task_submissions(status);
        CREATE TABLE IF NOT EXISTS weekly_earnings(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            points INTEGER NOT NULL CHECK(points>0),
            source TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        );
        CREATE INDEX IF NOT EXISTS idx_weekly_earnings_created ON weekly_earnings(created_at,user_id);
        CREATE TABLE IF NOT EXISTS referral_vip_milestones(
            user_id INTEGER NOT NULL,
            milestone INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(user_id,milestone),
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        );
        CREATE TABLE IF NOT EXISTS rewards(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            points_cost INTEGER NOT NULL CHECK(points_cost>0),
            stock INTEGER NOT NULL DEFAULT -1,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS reward_orders(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reward_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            points_spent INTEGER NOT NULL CHECK(points_spent>0),
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            reviewed_by INTEGER,
            reviewed_at TEXT,
            FOREIGN KEY(reward_id) REFERENCES rewards(id),
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        );
        CREATE INDEX IF NOT EXISTS idx_reward_orders_status ON reward_orders(status);
        CREATE TABLE IF NOT EXISTS notification_preferences(
            user_id INTEGER PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        );
        """)
        columns={r["name"] for r in db.execute("PRAGMA table_info(users)")}
        if "daily_streak" not in columns:
            db.execute("ALTER TABLE users ADD COLUMN daily_streak INTEGER NOT NULL DEFAULT 0")
        if "vip_expires_at" not in columns:
            db.execute("ALTER TABLE users ADD COLUMN vip_expires_at TEXT")
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
def create_task(title,description,reward_points,requires_proof=True):
    title=title.strip(); description=description.strip(); reward_points=int(reward_points)
    if not title or len(title)>100 or reward_points<1 or reward_points>1000000:
        raise ValueError("Título ou quantidade de pontos inválida.")
    with connect() as db:
        cur=db.execute("INSERT INTO tasks(title,description,reward_points,requires_proof) VALUES(?,?,?,?)",(title,description,reward_points,int(bool(requires_proof))))
        db.commit(); return cur.lastrowid

def active_tasks():
    with connect() as db:
        return db.execute("SELECT * FROM tasks WHERE active=1 ORDER BY id DESC").fetchall()

def deactivate_task(task_id):
    with connect() as db:
        cur=db.execute("UPDATE tasks SET active=0 WHERE id=? AND active=1",(task_id,))
        db.commit()
        return cur.rowcount>0

def active_tasks_for_user(user_id):
    with connect() as db:
        return db.execute("""
            SELECT t.* FROM tasks t
            WHERE t.active=1
              AND NOT EXISTS (
                  SELECT 1 FROM task_submissions s
                  WHERE s.task_id=t.id AND s.user_id=? AND s.status='approved'
              )
            ORDER BY t.id DESC
        """,(user_id,)).fetchall()

def submit_task(task_id,user_id,proof=""):
    with connect() as db:
        task=db.execute("SELECT * FROM tasks WHERE id=? AND active=1",(task_id,)).fetchone()
        if not task: raise ValueError("Essa tarefa não está disponível.")
        if task["requires_proof"] and not proof.strip(): raise ValueError("Envie a comprovação solicitada.")
        try:
            cur=db.execute("INSERT INTO task_submissions(task_id,user_id,proof) VALUES(?,?,?)",(task_id,user_id,proof.strip()[:1500]))
        except sqlite3.IntegrityError:
            raise ValueError("Você já enviou essa tarefa.")
        db.commit(); return cur.lastrowid

def pending_task_submissions():
    with connect() as db:
        return db.execute("SELECT s.*,t.title,t.reward_points,u.first_name,u.username FROM task_submissions s JOIN tasks t ON t.id=s.task_id JOIN users u ON u.user_id=s.user_id WHERE s.status='pending' ORDER BY s.id").fetchall()

def review_task_submission(submission_id,admin_id,approve):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row=db.execute("SELECT s.*,t.title,t.reward_points FROM task_submissions s JOIN tasks t ON t.id=s.task_id WHERE s.id=? AND s.status='pending'",(submission_id,)).fetchone()
        if not row: db.rollback(); return None
        status='approved' if approve else 'rejected'
        db.execute("UPDATE task_submissions SET status=?,reviewed_by=?,reviewed_at=CURRENT_TIMESTAMP WHERE id=?",(status,admin_id,submission_id))
        if approve:
            points=row["reward_points"]
            db.execute("UPDATE users SET points=points+? WHERE user_id=?",(points,row["user_id"]))
            db.execute("INSERT INTO point_history(user_id,amount,reason) VALUES(?,?,?)",(row["user_id"],points,f"Tarefa: {row['title']}"))
            db.execute("INSERT INTO weekly_earnings(user_id,points,source) VALUES(?,?,?)",(row["user_id"],points,"task"))
        db.commit(); return dict(row)

def weekly_ranking(limit=10):
    with connect() as db:
        return db.execute("SELECT u.user_id,u.first_name,u.username,COALESCE(SUM(w.points),0) points FROM weekly_earnings w JOIN users u ON u.user_id=w.user_id WHERE w.created_at>=datetime('now','-7 days') GROUP BY u.user_id ORDER BY points DESC LIMIT ?",(limit,)).fetchall()

def create_reward(title,description,points_cost,stock=-1):
    title=title.strip(); points_cost=int(points_cost); stock=int(stock)
    if not title or len(title)>100 or points_cost<1 or stock < -1:
        raise ValueError("Dados do prêmio inválidos.")
    with connect() as db:
        cur=db.execute("INSERT INTO rewards(title,description,points_cost,stock) VALUES(?,?,?,?)",(title,description.strip(),points_cost,stock))
        db.commit(); return cur.lastrowid

def active_rewards():
    with connect() as db:
        return db.execute("SELECT * FROM rewards WHERE active=1 AND (stock=-1 OR stock>0) ORDER BY id DESC").fetchall()

def create_reward_order(user_id,reward_id):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        reward=db.execute("SELECT * FROM rewards WHERE id=? AND active=1",(reward_id,)).fetchone()
        user=db.execute("SELECT points FROM users WHERE user_id=?",(user_id,)).fetchone()
        if not reward: db.rollback(); raise ValueError("Prêmio indisponível.")
        if reward["stock"]==0: db.rollback(); raise ValueError("Prêmio esgotado.")
        if not user or user["points"]<reward["points_cost"]: db.rollback(); raise ValueError("Saldo insuficiente.")
        db.execute("UPDATE users SET points=points-? WHERE user_id=?",(reward["points_cost"],user_id))
        if reward["stock"]>0: db.execute("UPDATE rewards SET stock=stock-1 WHERE id=?",(reward_id,))
        cur=db.execute("INSERT INTO reward_orders(reward_id,user_id,points_spent) VALUES(?,?,?)",(reward_id,user_id,reward["points_cost"]))
        order_id=cur.lastrowid
        db.execute("INSERT INTO point_history(user_id,amount,reason) VALUES(?,?,?)",(user_id,-reward["points_cost"],f"Pedido de recompensa #{order_id}"))
        db.commit(); return order_id

def pending_reward_orders():
    with connect() as db:
        return db.execute("SELECT o.*,r.title,u.first_name,u.username FROM reward_orders o JOIN rewards r ON r.id=o.reward_id JOIN users u ON u.user_id=o.user_id WHERE o.status='pending' ORDER BY o.id").fetchall()

def review_reward_order(order_id,admin_id,approve):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row=db.execute("SELECT * FROM reward_orders WHERE id=? AND status='pending'",(order_id,)).fetchone()
        if not row: db.rollback(); return None
        status='approved' if approve else 'rejected'
        db.execute("UPDATE reward_orders SET status=?,reviewed_by=?,reviewed_at=CURRENT_TIMESTAMP WHERE id=?",(status,admin_id,order_id))
        if not approve:
            db.execute("UPDATE users SET points=points+? WHERE user_id=?",(row["points_spent"],row["user_id"]))
            db.execute("INSERT INTO point_history(user_id,amount,reason) VALUES(?,?,?)",(row["user_id"],row["points_spent"],f"Estorno recompensa #{order_id}"))
            db.execute("UPDATE rewards SET stock=stock+1 WHERE id=? AND stock>=0",(row["reward_id"],))
        db.commit(); return dict(row)

def set_notifications(user_id,enabled):
    with connect() as db:
        db.execute("INSERT INTO notification_preferences(user_id,enabled,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) ON CONFLICT(user_id) DO UPDATE SET enabled=excluded.enabled,updated_at=CURRENT_TIMESTAMP",(user_id,int(bool(enabled))))
        db.commit()

def notifications_enabled(user_id):
    with connect() as db:
        row=db.execute("SELECT enabled FROM notification_preferences WHERE user_id=?",(user_id,)).fetchone()
        return bool(row["enabled"]) if row else True

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
    rewards=[3,4,5,6,7,8,10]
    now=datetime.now(timezone(timedelta(hours=-3))); current=now.date().isoformat()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row=db.execute("SELECT last_daily,daily_streak FROM users WHERE user_id=?",(uid,)).fetchone()
        if not row or row["last_daily"]==current:
            db.rollback(); return False,(row["daily_streak"] if row else 0),0
        yesterday=(now.date()-timedelta(days=1)).isoformat()
        streak=row["daily_streak"]+1 if row["last_daily"]==yesterday else 1
        earned=rewards[(streak-1)%len(rewards)]
        db.execute("UPDATE users SET last_daily=?,daily_streak=?,points=points+? WHERE user_id=?",(current,streak,earned,uid))
        db.execute("INSERT INTO point_history(user_id,amount,reason) VALUES(?,?,?)",(uid,earned,f"Check-in — dia {(streak-1)%7+1} da sequência"))
        db.commit(); return True,streak,earned

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

def referral_vip_status(uid):
    goals=[{"milestone":25,"days":7},{"milestone":50,"days":30}]
    with connect() as db:
        total=db.execute("SELECT COUNT(*) n FROM users x LEFT JOIN referral_reviews rr ON rr.referred_user_id=x.user_id WHERE x.referred_by=? AND (rr.status IS NULL OR rr.status='approved')",(uid,)).fetchone()["n"]
        claimed={r["milestone"] for r in db.execute("SELECT milestone FROM referral_vip_milestones WHERE user_id=?",(uid,))}
        return [{"milestone":g["milestone"],"days":g["days"],"reached":total>=g["milestone"],"claimed":g["milestone"] in claimed} for g in goals]

def claim_referral_vip(uid,milestone):
    durations={25:7,50:30}
    if milestone not in durations: raise ValueError("Meta VIP inválida.")
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        total=db.execute("SELECT COUNT(*) n FROM users x LEFT JOIN referral_reviews rr ON rr.referred_user_id=x.user_id WHERE x.referred_by=? AND (rr.status IS NULL OR rr.status='approved')",(uid,)).fetchone()["n"]
        if total<milestone: db.rollback(); raise ValueError("Você ainda não atingiu essa meta.")
        try:
            db.execute("INSERT INTO referral_vip_milestones(user_id,milestone) VALUES(?,?)",(uid,milestone))
        except sqlite3.IntegrityError:
            db.rollback(); raise ValueError("Essa recompensa VIP já foi resgatada.")
        days=durations[milestone]
        db.execute("UPDATE users SET is_vip=1, vip_expires_at=CASE WHEN vip_expires_at IS NOT NULL AND vip_expires_at>datetime('now') THEN datetime(vip_expires_at, ?) ELSE datetime('now', ?) END WHERE user_id=?", (f"+{days} days",f"+{days} days",uid))
        expiry=db.execute("SELECT vip_expires_at FROM users WHERE user_id=?",(uid,)).fetchone()["vip_expires_at"]
        db.commit(); return days,expiry

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
