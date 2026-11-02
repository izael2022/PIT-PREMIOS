import sqlite3
from contextlib import contextmanager
from config import DATABASE_PATH

@contextmanager
def connect():
    DATABASE_PATH.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(str(DATABASE_PATH),timeout=30)
    db.row_factory=sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=30000")
    db.execute("PRAGMA synchronous=NORMAL")
    db.execute("PRAGMA temp_store=MEMORY")
    db.execute("PRAGMA cache_size=-8000")
    try:
        yield db
    finally:
        db.close()

def init_db():
    with connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
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
        CREATE TABLE IF NOT EXISTS account_blocks(
            user_id INTEGER PRIMARY KEY,
            reason TEXT NOT NULL,
            blocked_by INTEGER NOT NULL,
            blocked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        );
        CREATE TABLE IF NOT EXISTS account_block_history(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            action TEXT NOT NULL CHECK(action IN ('blocked','unblocked')),
            reason TEXT NOT NULL DEFAULT '',
            admin_id INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        );
        CREATE INDEX IF NOT EXISTS idx_account_block_history_user ON account_block_history(user_id,created_at);
        CREATE TABLE IF NOT EXISTS account_blocks(
            user_id INTEGER PRIMARY KEY,
            reason TEXT NOT NULL,
            blocked_by INTEGER NOT NULL,
            blocked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        );
        CREATE TABLE IF NOT EXISTS account_block_history(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            action TEXT NOT NULL CHECK(action IN ('blocked','unblocked')),
            reason TEXT NOT NULL DEFAULT '',
            admin_id INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        );
        CREATE INDEX IF NOT EXISTS idx_account_block_history_user ON account_block_history(user_id,created_at);
        CREATE TABLE IF NOT EXISTS referral_manual_holds(
            referrer_id INTEGER PRIMARY KEY,
            reason TEXT NOT NULL DEFAULT 'Monitoramento manual da equipe',
            created_by INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(referrer_id) REFERENCES users(user_id)
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
        CREATE TABLE IF NOT EXISTS task_submission_history(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            submission_id INTEGER NOT NULL,
            task_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            proof TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            reviewed_by INTEGER,
            submitted_at TEXT,
            reviewed_at TEXT,
            archived_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_task_submission_history_user ON task_submission_history(user_id,task_id,id);
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
                  WHERE s.task_id=t.id AND s.user_id=? AND s.status IN ('approved','pending')
              )
            ORDER BY t.id DESC
        """,(user_id,)).fetchall()

def submit_task(task_id,user_id,proof=""):
    proof=(proof or "").strip()[:1500]
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        task=db.execute("SELECT * FROM tasks WHERE id=? AND active=1",(task_id,)).fetchone()
        if not task:
            db.rollback(); raise ValueError("Essa tarefa não está disponível.")
        if task["requires_proof"] and not proof:
            db.rollback(); raise ValueError("Envie a comprovação solicitada.")
        existing=db.execute("SELECT * FROM task_submissions WHERE task_id=? AND user_id=?",(task_id,user_id)).fetchone()
        if existing:
            if existing["status"]=="approved":
                db.rollback(); raise ValueError("Essa tarefa já foi aprovada.")
            if existing["status"]=="pending":
                db.rollback(); raise ValueError("Sua comprovação já está aguardando análise.")
            db.execute("UPDATE task_submissions SET proof=?,status='pending',reviewed_by=NULL,reviewed_at=NULL,created_at=CURRENT_TIMESTAMP WHERE id=?",(proof,existing["id"]))
            submission_id=existing["id"]
        else:
            cur=db.execute("INSERT INTO task_submissions(task_id,user_id,proof) VALUES(?,?,?)",(task_id,user_id,proof))
            submission_id=cur.lastrowid
        db.commit()
        return submission_id

def pending_task_submissions():
    with connect() as db:
        return db.execute("SELECT s.*,t.title,t.reward_points,u.first_name,u.username FROM task_submissions s JOIN tasks t ON t.id=s.task_id JOIN users u ON u.user_id=s.user_id WHERE s.status='pending' ORDER BY s.id").fetchall()

def review_task_submission(submission_id,admin_id,approve):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row=db.execute("SELECT s.*,t.title,t.reward_points FROM task_submissions s JOIN tasks t ON t.id=s.task_id WHERE s.id=? AND s.status='pending'",(submission_id,)).fetchone()
        if not row: db.rollback(); return None
        status='approved' if approve else 'rejected'
        db.execute("INSERT INTO task_submission_history(submission_id,task_id,user_id,proof,status,reviewed_by,submitted_at,reviewed_at) VALUES(?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",(row["id"],row["task_id"],row["user_id"],row["proof"],status,admin_id,row["created_at"]))
        db.execute("UPDATE task_submissions SET status=?,reviewed_by=?,reviewed_at=CURRENT_TIMESTAMP WHERE id=?",(status,admin_id,submission_id))
        if approve:
            points=row["reward_points"]
            db.execute("UPDATE users SET points=points+? WHERE user_id=?",(points,row["user_id"]))
            db.execute("INSERT INTO point_history(user_id,amount,reason) VALUES(?,?,?)",(row["user_id"],points,f"Tarefa: {row['title']}"))
            db.execute("INSERT INTO weekly_earnings(user_id,points,source) VALUES(?,?,?)",(row["user_id"],points,"task"))
        db.commit(); return dict(row)


def user_task_submissions(user_id,limit=20):
    with connect() as db:
        return db.execute("""
            SELECT s.id,s.task_id,s.status,s.created_at,s.reviewed_at,t.title,t.reward_points,
                   (SELECT COUNT(*) FROM task_submission_history h WHERE h.submission_id=s.id) + CASE WHEN s.status='pending' OR NOT EXISTS (SELECT 1 FROM task_submission_history h WHERE h.submission_id=s.id) THEN 1 ELSE 0 END AS attempts,
                   (SELECT COUNT(*) FROM task_submission_history h WHERE h.submission_id=s.id AND h.status='rejected') AS previous_rejections
            FROM task_submissions s
            JOIN tasks t ON t.id=s.task_id
            WHERE s.user_id=?
            ORDER BY s.id DESC LIMIT ?
        """,(user_id,limit)).fetchall()

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


def all_rewards():
    with connect() as db:
        return db.execute("SELECT * FROM rewards ORDER BY id DESC").fetchall()

def deactivate_reward(reward_id):
    with connect() as db:
        cur=db.execute("UPDATE rewards SET active=0 WHERE id=? AND active=1",(reward_id,))
        db.commit()
        return cur.rowcount>0

def user_reward_orders(user_id,limit=15):
    with connect() as db:
        return db.execute("""
            SELECT o.id,o.points_spent,o.status,o.created_at,o.reviewed_at,r.title
            FROM reward_orders o
            JOIN rewards r ON r.id=o.reward_id
            WHERE o.user_id=?
            ORDER BY o.id DESC LIMIT ?
        """,(user_id,limit)).fetchall()


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

def cancel_reward_order(user_id,order_id):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row=db.execute("SELECT * FROM reward_orders WHERE id=? AND user_id=? AND status='pending'",(order_id,user_id)).fetchone()
        if not row:
            db.rollback()
            return None
        cur=db.execute("UPDATE reward_orders SET status='cancelled',reviewed_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=? AND status='pending'",(order_id,user_id))
        if cur.rowcount != 1:
            db.rollback()
            return None
        db.execute("UPDATE users SET points=points+? WHERE user_id=?",(row["points_spent"],user_id))
        db.execute("INSERT INTO point_history(user_id,amount,reason) VALUES(?,?,?)",(user_id,row["points_spent"],f"Cancelamento do pedido da loja #{order_id}"))
        db.execute("UPDATE rewards SET stock=stock+1 WHERE id=? AND stock>=0",(row["reward_id"],))
        db.commit()
        return dict(row)

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
        db.execute("UPDATE users SET is_vip=0,vip_expires_at=NULL WHERE user_id=? AND vip_expires_at IS NOT NULL AND vip_expires_at<=datetime('now')",(uid,))
        row=db.execute("SELECT u.*, (SELECT COUNT(*) FROM users x LEFT JOIN referral_reviews rr ON rr.referred_user_id=x.user_id WHERE x.referred_by=u.user_id AND (rr.status IS NULL OR rr.status='approved')) referrals FROM users u WHERE user_id=?",(uid,)).fetchone()
        return dict(row) if row else {"points":0,"referrals":0,"daily_streak":0,"created_at":today(),"last_daily":None}

def admin_user_details(user_id,history_limit=5):
    with connect() as db:
        user=db.execute("""
            SELECT u.*,
                   (SELECT COUNT(*) FROM users x LEFT JOIN referral_reviews rr ON rr.referred_user_id=x.user_id
                    WHERE x.referred_by=u.user_id AND (rr.status IS NULL OR rr.status='approved')) AS referrals
            FROM users u WHERE u.user_id=?
        """,(user_id,)).fetchone()
        if not user:
            return None
        history=db.execute("""
            SELECT amount,reason,created_at FROM point_history
            WHERE user_id=? ORDER BY id DESC LIMIT ?
        """,(user_id,history_limit)).fetchall()
        counts=db.execute("""
            SELECT
                (SELECT COUNT(*) FROM payout_requests WHERE user_id=? AND status='pending') AS pending_payouts,
                (SELECT COUNT(*) FROM reward_orders WHERE user_id=? AND status='pending') AS pending_reward_orders,
                (SELECT COUNT(*) FROM task_submissions WHERE user_id=? AND status='pending') AS pending_tasks,
                (SELECT COUNT(*) FROM redemptions WHERE user_id=? AND status='pending') AS pending_redemptions
        """,(user_id,user_id,user_id,user_id)).fetchone()
        totals=db.execute("""
            SELECT
                (SELECT COUNT(*) FROM task_submissions WHERE user_id=? AND status='approved') AS tasks_approved,
                (SELECT COUNT(*) FROM task_submissions WHERE user_id=? AND status='rejected') AS tasks_rejected,
                (SELECT COUNT(*) FROM reward_orders WHERE user_id=? AND status='approved') AS rewards_approved,
                (SELECT COUNT(*) FROM reward_orders WHERE user_id=? AND status='rejected') AS rewards_rejected,
                (SELECT COUNT(*) FROM payout_requests WHERE user_id=? AND status='approved') AS payouts_approved,
                (SELECT COUNT(*) FROM payout_requests WHERE user_id=? AND status='rejected') AS payouts_rejected,
                (SELECT COUNT(*) FROM redemptions WHERE user_id=? AND status='approved') AS redemptions_approved,
                (SELECT COUNT(*) FROM redemptions WHERE user_id=? AND status='rejected') AS redemptions_rejected
        """,(user_id,user_id,user_id,user_id,user_id,user_id,user_id,user_id)).fetchone()
        return {"user":dict(user),"history":[dict(x) for x in history],"pending":dict(counts),"totals":dict(totals)}

def user_referrals(user_id,limit=15):
    with connect() as db:
        return db.execute("""
            SELECT u.user_id,u.first_name,u.username,u.created_at,
                   COALESCE(rr.status,'approved') AS referral_status
            FROM users u
            LEFT JOIN referral_reviews rr ON rr.referred_user_id=u.user_id
            WHERE u.referred_by=?
            ORDER BY u.created_at DESC,u.user_id DESC
            LIMIT ?
        """,(user_id,limit)).fetchall()

def top_referrals(limit=10):
    with connect() as db:
        return db.execute("SELECT u.user_id,u.first_name,COUNT(x.user_id) referrals FROM users u JOIN users x ON x.referred_by=u.user_id LEFT JOIN referral_reviews rr ON rr.referred_user_id=x.user_id WHERE rr.status IS NULL OR rr.status='approved' GROUP BY u.user_id ORDER BY referrals DESC LIMIT ?",(limit,)).fetchall()

def history(uid,limit=8,offset=0):
    limit=max(1,min(int(limit),50)); offset=max(0,int(offset))
    with connect() as db:
        return db.execute("SELECT amount,reason,created_at FROM point_history WHERE user_id=? ORDER BY id DESC LIMIT ? OFFSET ?",(uid,limit,offset)).fetchall()

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
            manual_hold=db.execute("SELECT reason FROM referral_manual_holds WHERE referrer_id=?",(referrer,)).fetchone()
            if manual_hold: reasons.append("Monitoramento manual: "+manual_hold["reason"])
            blocked=db.execute("SELECT reason FROM account_blocks WHERE user_id=?",(referrer,)).fetchone()
            if blocked: reasons.append("Indicador bloqueado: "+blocked["reason"])
            reviewed=db.execute("SELECT COUNT(*) n,COALESCE(SUM(CASE WHEN status='rejected' THEN 1 ELSE 0 END),0) rejected FROM referral_reviews WHERE referrer_id=? AND status IN ('approved','rejected')",(referrer,)).fetchone()
            if reviewed["rejected"]>=2: reasons.append("Histórico de rejeições: "+str(reviewed["rejected"])+" indicações não aprovadas")
            if reviewed["n"]>=4 and reviewed["rejected"]/reviewed["n"]>=0.5: reasons.append("Taxa histórica de rejeição elevada: "+str(reviewed["rejected"])+"/"+str(reviewed["n"])+" análises")

            if is_bot: reasons.append("Conta do Telegram identificada como bot")
            recent=db.execute("SELECT COUNT(*) total FROM users WHERE referred_by=? AND created_at>=datetime('now','-10 minutes')",(referrer,)).fetchone()["total"]
            burst=db.execute("SELECT COUNT(*) total FROM users WHERE referred_by=? AND created_at>=datetime('now','-2 minutes')",(referrer,)).fetchone()["total"]
            daily=db.execute("SELECT COUNT(*) total FROM users WHERE referred_by=? AND created_at>=datetime('now','-24 hours')",(referrer,)).fetchone()["total"]
            weekly=db.execute("SELECT COUNT(*) total FROM users WHERE referred_by=? AND created_at>=datetime('now','-7 days')",(referrer,)).fetchone()["total"]
            monthly=db.execute("SELECT COUNT(*) total FROM users WHERE referred_by=? AND created_at>=datetime('now','-30 days')",(referrer,)).fetchone()["total"]
            referrer_age=db.execute("SELECT (julianday('now')-julianday(created_at))*24 hours FROM users WHERE user_id=?",(referrer,)).fetchone()["hours"]
            pending=db.execute("SELECT COUNT(*) total FROM referral_reviews WHERE referrer_id=? AND status='pending'",(referrer,)).fetchone()["total"]
            if burst>=2: reasons.append(f"Cadastros muito próximos: {burst} em 2 minutos")
            if recent>=3: reasons.append(f"Cadastros em sequência: {recent} em 10 minutos")
            if daily>=8: reasons.append(f"Volume diário elevado: {daily} em 24 horas")
            if weekly>=15: reasons.append(f"Volume semanal elevado: {weekly} em 7 dias")
            if monthly>=40: reasons.append(f"Volume mensal elevado: {monthly} em 30 dias")
            if referrer_age<24 and daily>=2: reasons.append("Indicador recém-cadastrado com múltiplas indicações em menos de 24 horas")
            if referrer_age<168 and weekly>=5: reasons.append("Conta do indicador com menos de 7 dias e volume alto de indicações")
            if pending>=3: reasons.append(f"Muitas indicações aguardando análise: {pending}")
            if reasons:
                cur=db.execute("INSERT INTO referral_reviews(referrer_id,referred_user_id,risk_level,risk_reason,status) VALUES(?,?,?,?, 'pending')",(referrer,uid,"high" if len(reasons)>=2 else "review","; ".join(reasons)))
                review_id=cur.lastrowid
            elif referral_reward>0:
                db.execute("UPDATE users SET points=points+? WHERE user_id=?",(referral_reward,referrer))
                db.execute("INSERT INTO point_history(user_id,amount,reason) VALUES(?,?,?)",(referrer,referral_reward,f"Indicação do usuário {uid}"))
                db.execute("INSERT INTO weekly_earnings(user_id,points,source) VALUES(?,?,?)",(referrer,referral_reward,"referral"))
        db.commit(); return True,referrer,review_id
def get_user(uid):
    with connect() as db:
        db.execute("UPDATE users SET is_vip=0,vip_expires_at=NULL WHERE user_id=? AND vip_expires_at IS NOT NULL AND vip_expires_at<=datetime('now')",(uid,))
        return db.execute("SELECT * FROM users WHERE user_id=?",(uid,)).fetchone()

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
        db.execute("INSERT INTO point_history(user_id,amount,reason) VALUES(?,?,?)",(uid,amount,reason))
        if amount>0: db.execute("INSERT INTO weekly_earnings(user_id,points,source) VALUES(?,?,?)",(uid,amount,"admin_adjustment"))
        db.commit()

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
        db.execute("INSERT INTO weekly_earnings(user_id,points,source) VALUES(?,?,?)",(uid,earned,"daily_checkin"))
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
    with connect() as db:
        db.execute("UPDATE users SET is_vip=?,vip_expires_at=NULL WHERE user_id=?",(int(enabled),uid))
        db.commit()

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
        row=db.execute("""
            SELECT
                (SELECT COUNT(*) FROM users) AS users,
                (SELECT COALESCE(SUM(points),0) FROM users) AS points,
                (SELECT COUNT(*) FROM redemptions WHERE status='pending') AS pending_redemptions,
                (SELECT COUNT(*) FROM payout_requests WHERE status='pending') AS pending_payouts,
                (SELECT COUNT(*) FROM reward_orders WHERE status='pending') AS pending_reward_orders,
                (SELECT COUNT(*) FROM task_submissions WHERE status='pending') AS pending_tasks,
                (SELECT COUNT(*) FROM referral_reviews WHERE status='pending') AS pending_fraud
        """).fetchone()
        return dict(row)

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
        db.execute("INSERT INTO weekly_earnings(user_id,points,source) VALUES(?,?,?)",(uid,bonuses[milestone],"referral_milestone"))
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

def user_payout_requests(user_id,limit=10):
    with connect() as db:
        return db.execute("""
            SELECT id,points,amount_cents,pix_key_type,pix_key,status,created_at,reviewed_at
            FROM payout_requests
            WHERE user_id=?
            ORDER BY id DESC LIMIT ?
        """,(user_id,limit)).fetchall()

def cancel_payout_request(user_id,payout_id):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row=db.execute("SELECT * FROM payout_requests WHERE id=? AND user_id=? AND status='pending'",(payout_id,user_id)).fetchone()
        if not row:
            db.rollback()
            return None
        db.execute("UPDATE payout_requests SET status='cancelled',reviewed_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=? AND status='pending'",(payout_id,user_id))
        if db.total_changes < 1:
            db.rollback()
            return None
        db.execute("UPDATE users SET points=points+? WHERE user_id=?",(row["points"],user_id))
        db.execute("INSERT INTO point_history(user_id,amount,reason) VALUES(?,?,?)",(user_id,row["points"],f"Cancelamento do saque #{payout_id}"))
        db.commit()
        return dict(row)

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
        return db.execute("""
            SELECT rr.*,u.first_name,u.username,
                   (SELECT COUNT(*) FROM users x WHERE x.referred_by=rr.referrer_id
                    AND x.created_at>=datetime('now','-10 minutes')) AS referrer_last_10m,
                   (SELECT COUNT(*) FROM users x WHERE x.referred_by=rr.referrer_id
                    AND x.created_at>=datetime('now','-24 hours')) AS referrer_last_24h,
                   (SELECT COUNT(*) FROM referral_reviews z WHERE z.referrer_id=rr.referrer_id
                    AND z.status='pending') AS referrer_pending
            FROM referral_reviews rr
            JOIN users u ON u.user_id=rr.referred_user_id
            WHERE rr.status='pending'
            ORDER BY CASE rr.risk_level WHEN 'high' THEN 0 ELSE 1 END,rr.id
        """).fetchall()

def fraud_profile(referrer_id,limit=10):
    with connect() as db:
        user=db.execute("SELECT user_id,first_name,username,created_at FROM users WHERE user_id=?",(referrer_id,)).fetchone()
        if not user:
            return None
        stats=db.execute("""
            SELECT
                (SELECT COUNT(*) FROM users WHERE referred_by=?) AS total,
                (SELECT COUNT(*) FROM users x LEFT JOIN referral_reviews rr ON rr.referred_user_id=x.user_id
                 WHERE x.referred_by=? AND (rr.status IS NULL OR rr.status='approved')) AS valid,
                (SELECT COUNT(*) FROM referral_reviews WHERE referrer_id=? AND status='pending') AS pending,
                (SELECT COUNT(*) FROM referral_reviews WHERE referrer_id=? AND status='rejected') AS rejected,
                (SELECT COUNT(*) FROM referral_reviews WHERE referrer_id=? AND status IN ('approved','rejected')) AS reviewed,
                (SELECT COUNT(*) FROM referral_reviews WHERE referrer_id=? AND created_at>=datetime('now','-30 days')) AS flagged_30d,
                (SELECT COUNT(*) FROM users WHERE referred_by=? AND created_at>=datetime('now','-10 minutes')) AS last_10m,
                (SELECT COUNT(*) FROM users WHERE referred_by=? AND created_at>=datetime('now','-24 hours')) AS last_24h,
                (SELECT COUNT(*) FROM users WHERE referred_by=? AND created_at>=datetime('now','-2 minutes')) AS last_2m,
                (SELECT COUNT(*) FROM users WHERE referred_by=? AND created_at>=datetime('now','-7 days')) AS last_7d,
                (SELECT COUNT(*) FROM users WHERE referred_by=? AND created_at>=datetime('now','-30 days')) AS last_30d,
                (SELECT (julianday('now')-julianday(created_at))*24 FROM users WHERE user_id=?) AS account_age_hours
        """,(referrer_id,referrer_id,referrer_id,referrer_id,referrer_id,referrer_id,referrer_id,referrer_id,referrer_id,referrer_id,referrer_id,referrer_id)).fetchone()
        recent=db.execute("""
            SELECT u.user_id,u.first_name,u.username,u.created_at,
                   COALESCE(rr.status,'approved') AS status,
                   COALESCE(rr.risk_level,'normal') AS risk_level,
                   COALESCE(rr.risk_reason,'') AS risk_reason
            FROM users u LEFT JOIN referral_reviews rr ON rr.referred_user_id=u.user_id
            WHERE u.referred_by=? ORDER BY u.created_at DESC,u.user_id DESC LIMIT ?
        """,(referrer_id,max(1,min(int(limit),20)))).fetchall()
        st=dict(stats)
        score=0; reasons=[]
        if st["last_10m"]>=3:
            score+=25; reasons.append(f"{st['last_10m']} cadastros em 10 minutos (+25)")
        if st["last_24h"]>=8:
            score+=20; reasons.append(f"{st['last_24h']} cadastros em 24 horas (+20)")
        if st["pending"]>=3:
            score+=15; reasons.append(f"{st['pending']} indicações pendentes (+15)")
        if st["rejected"]>=2:
            score+=25; reasons.append(f"{st['rejected']} indicações rejeitadas (+25)")
        if st["rejected"]>=5:
            score+=15; reasons.append("Cinco ou mais indicações rejeitadas (+15)")
        if st["reviewed"]>=4 and st["rejected"] / st["reviewed"] >= 0.5:
            score+=20; reasons.append(f"Taxa de rejeição de {st['rejected'] / st['reviewed']:.0%} em indicações analisadas (+20)")
        if st["flagged_30d"]>=3:
            score+=15; reasons.append(f"{st['flagged_30d']} alertas nos últimos 30 dias (+15)")
        if st["last_2m"]>=2:
            score+=15; reasons.append(f"{st['last_2m']} cadastros em 2 minutos (+15)")
        if st["last_7d"]>=15:
            score+=15; reasons.append(f"{st['last_7d']} indicações em 7 dias (+15)")
        if st["last_30d"]>=40:
            score+=15; reasons.append(f"{st['last_30d']} indicações em 30 dias (+15)")
        if st["account_age_hours"] is not None and st["account_age_hours"]<24 and st["last_24h"]>=2:
            score+=15; reasons.append("Conta com menos de 24 horas e múltiplas indicações (+15)")
        if st["account_age_hours"] is not None and st["account_age_hours"]<168 and st["last_7d"]>=5:
            score+=15; reasons.append("Conta com menos de 7 dias e cinco ou mais indicações (+15)")
        score=min(100,score)
        level="alto" if score>=60 else "moderado" if score>=30 else "baixo"
        return {"user":dict(user),"stats":st,"recent":[dict(x) for x in recent],"risk_score":score,"risk_level":level,"risk_reasons":reasons}

def review_referral(rid,admin_id,approve):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row=db.execute("SELECT * FROM referral_reviews WHERE id=? AND status='pending'",(rid,)).fetchone()
        if not row:
            db.rollback(); return None
        if approve and db.execute("SELECT 1 FROM account_blocks WHERE user_id=?",(row["referrer_id"],)).fetchone():
            db.rollback()
            return {"blocked_referrer":True,"referrer_id":row["referrer_id"]}
        if approve and db.execute("SELECT 1 FROM account_blocks WHERE user_id=?",(row["referred_user_id"],)).fetchone():
            db.rollback()
            return {"blocked_referred":True,"referred_user_id":row["referred_user_id"]}
        status="approved" if approve else "rejected"
        db.execute("UPDATE referral_reviews SET status=?,reviewed_by=?,reviewed_at=CURRENT_TIMESTAMP WHERE id=?",(status,admin_id,rid))
        if approve:
            db.execute("UPDATE users SET points=points+100 WHERE user_id=?",(row["referrer_id"],))
            db.execute("INSERT INTO point_history(user_id,amount,reason) VALUES(?,?,?)",(row["referrer_id"],100,f"Indicação aprovada #{rid}"))
            db.execute("INSERT INTO weekly_earnings(user_id,points,source) VALUES(?,?,?)",(row["referrer_id"],100,"referral_approved"))
        db.commit(); return dict(row)

def set_referral_manual_hold(referrer_id,enabled,admin_id,reason="Monitoramento manual da equipe"):
    with connect() as db:
        if not db.execute("SELECT 1 FROM users WHERE user_id=?",(referrer_id,)).fetchone():
            return False
        if enabled:
            db.execute("INSERT INTO referral_manual_holds(referrer_id,reason,created_by) VALUES(?,?,?) ON CONFLICT(referrer_id) DO UPDATE SET reason=excluded.reason,created_by=excluded.created_by,created_at=CURRENT_TIMESTAMP",(referrer_id,reason.strip()[:200],admin_id))
        else:
            db.execute("DELETE FROM referral_manual_holds WHERE referrer_id=?",(referrer_id,))
        db.commit()
        return True

def get_referral_manual_hold(referrer_id):
    with connect() as db:
        row=db.execute("SELECT * FROM referral_manual_holds WHERE referrer_id=?",(referrer_id,)).fetchone()
        return dict(row) if row else None


def get_account_block(user_id):
    with connect() as db:
        row=db.execute("SELECT * FROM account_blocks WHERE user_id=?",(user_id,)).fetchone()
        return dict(row) if row else None

def list_blocked_accounts(limit=30):
    with connect() as db:
        rows=db.execute("SELECT b.*,u.first_name,u.username FROM account_blocks b LEFT JOIN users u ON u.user_id=b.user_id ORDER BY b.blocked_at DESC LIMIT ?",(max(1,min(int(limit),100)),)).fetchall()
        return [dict(r) for r in rows]

def account_block_history(user_id,limit=20):
    with connect() as db:
        rows=db.execute("SELECT * FROM account_block_history WHERE user_id=? ORDER BY id DESC LIMIT ?",(user_id,max(1,min(int(limit),50)))).fetchall()
        return [dict(r) for r in rows]

def block_account(user_id,admin_id,reason):
    reason=(reason or "").strip()[:300]
    if not reason:
        raise ValueError("Informe o motivo do bloqueio.")
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if not db.execute("SELECT 1 FROM users WHERE user_id=?",(user_id,)).fetchone():
            db.rollback()
            return False
        db.execute("INSERT INTO account_blocks(user_id,reason,blocked_by) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET reason=excluded.reason,blocked_by=excluded.blocked_by,blocked_at=CURRENT_TIMESTAMP",(user_id,reason,admin_id))
        db.execute("INSERT INTO account_block_history(user_id,action,reason,admin_id) VALUES(?,'blocked',?,?)",(user_id,reason,admin_id))
        db.commit()
        return True

def unblock_account(user_id,admin_id):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row=db.execute("SELECT reason FROM account_blocks WHERE user_id=?",(user_id,)).fetchone()
        if not row:
            db.rollback()
            return False
        db.execute("DELETE FROM account_blocks WHERE user_id=?",(user_id,))
        db.execute("INSERT INTO account_block_history(user_id,action,reason,admin_id) VALUES(?,'unblocked',?,?)",(user_id,row["reason"],admin_id))
        db.commit()
        return True


def get_account_block(user_id):
    with connect() as db:
        row=db.execute("SELECT * FROM account_blocks WHERE user_id=?",(user_id,)).fetchone()
        return dict(row) if row else None

def block_account(user_id,admin_id,reason):
    reason=(reason or "").strip()[:300]
    if not reason:
        raise ValueError("Informe o motivo do bloqueio.")
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if not db.execute("SELECT 1 FROM users WHERE user_id=?",(user_id,)).fetchone():
            db.rollback()
            return False
        db.execute("INSERT INTO account_blocks(user_id,reason,blocked_by) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET reason=excluded.reason,blocked_by=excluded.blocked_by,blocked_at=CURRENT_TIMESTAMP",(user_id,reason,admin_id))
        db.execute("INSERT INTO account_block_history(user_id,action,reason,admin_id) VALUES(?,'blocked',?,?)",(user_id,reason,admin_id))
        db.commit()
        return True

def unblock_account(user_id,admin_id):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row=db.execute("SELECT reason FROM account_blocks WHERE user_id=?",(user_id,)).fetchone()
        if not row:
            db.rollback()
            return False
        db.execute("DELETE FROM account_blocks WHERE user_id=?",(user_id,))
        db.execute("INSERT INTO account_block_history(user_id,action,reason,admin_id) VALUES(?,'unblocked',?,?)",(user_id,row["reason"],admin_id))
        db.commit()
        return True
