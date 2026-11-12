import sqlite3
import json
import os
import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from backup_utils import _load_key
from contextlib import contextmanager
from config import DATABASE_PATH, ADMIN_IDS

@contextmanager
def connect():
    DATABASE_PATH.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(str(DATABASE_PATH),timeout=30)
    db.row_factory=sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=30000")
    db.execute("PRAGMA synchronous=NORMAL")
    db.execute("PRAGMA temp_store=MEMORY")
    db.execute("PRAGMA cache_size=-2000")
    db.execute("PRAGMA wal_autocheckpoint=1000")
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
        CREATE TABLE IF NOT EXISTS referral_milestones(
            user_id INTEGER NOT NULL,
            milestone INTEGER NOT NULL,
            bonus_points INTEGER NOT NULL,
            claimed_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(user_id,milestone),
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        );
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
        CREATE TABLE IF NOT EXISTS pix_profiles(
            user_id INTEGER PRIMARY KEY,
            pix_key_encrypted TEXT NOT NULL,
            pix_key_type TEXT NOT NULL CHECK(pix_key_type IN ('CPF','CNPJ','EMAIL','TELEFONE','ALEATORIA')),
            owner_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            reviewed_by INTEGER,
            reviewed_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        );
        CREATE TABLE IF NOT EXISTS pix_setup_state(
            user_id INTEGER PRIMARY KEY,
            step TEXT NOT NULL CHECK(step IN ('key','owner')),
            pix_key_type TEXT NOT NULL,
            pix_key_encrypted TEXT,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        );
        CREATE TABLE IF NOT EXISTS payout_requests(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            points INTEGER NOT NULL CHECK(points > 0),
            amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
            conversion_version INTEGER NOT NULL DEFAULT 1,
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
        CREATE TABLE IF NOT EXISTS daily_games(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            game TEXT NOT NULL CHECK(game IN ('chest','roulette','scratch')),
            points INTEGER NOT NULL CHECK(points>=0),
            played_on TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id,game,played_on),
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        );
        CREATE INDEX IF NOT EXISTS idx_daily_games_date ON daily_games(played_on,game);
        CREATE TABLE IF NOT EXISTS notification_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        );
        CREATE INDEX IF NOT EXISTS idx_notification_events_user ON notification_events(user_id,id DESC);
        CREATE TABLE IF NOT EXISTS processed_updates(
            update_id INTEGER PRIMARY KEY,
            processed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS durable_updates(
            update_id INTEGER PRIMARY KEY,
            payload TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','completed')),
            received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_durable_updates_status ON durable_updates(status,update_id);
        CREATE TABLE IF NOT EXISTS idempotency_keys(
            update_id INTEGER PRIMARY KEY,
            action TEXT NOT NULL,
            result TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_idempotency_created ON idempotency_keys(created_at);
        CREATE TABLE IF NOT EXISTS pending_task_proofs(
            user_id INTEGER PRIMARY KEY,
            task_id INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(user_id),
            FOREIGN KEY(task_id) REFERENCES tasks(id)
        );
        CREATE INDEX IF NOT EXISTS idx_processed_updates_time ON processed_updates(processed_at);
        CREATE TABLE IF NOT EXISTS admin_audit_log(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            details TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_admin_audit_created ON admin_audit_log(created_at);
        CREATE TABLE IF NOT EXISTS health_alert_state(
            alert_key TEXT PRIMARY KEY,
            status TEXT NOT NULL CHECK(status IN ('active','resolved')),
            details TEXT NOT NULL DEFAULT '',
            first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_notified_at TEXT,
            resolved_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_health_alert_status ON health_alert_state(status,last_seen_at);
        CREATE TABLE IF NOT EXISTS health_monitor_state(metric_key TEXT PRIMARY KEY,metric_value TEXT NOT NULL,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS notification_preferences(
            user_id INTEGER PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        );
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS redeem_codes(
                code TEXT PRIMARY KEY,
                points INTEGER NOT NULL CHECK(points>0),
                max_uses INTEGER NOT NULL CHECK(max_uses>0),
                uses INTEGER NOT NULL DEFAULT 0 CHECK(uses>=0),
                active INTEGER NOT NULL DEFAULT 1,
                created_by INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS redeem_code_uses(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                points INTEGER NOT NULL CHECK(points>0),
                redeemed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(code,user_id),
                FOREIGN KEY(code) REFERENCES redeem_codes(code),
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_redeem_code_uses_user ON redeem_code_uses(user_id,redeemed_at)")
        db.execute("""
            CREATE TABLE IF NOT EXISTS user_input_states(
                user_id INTEGER PRIMARY KEY,
                state TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
        """)
        columns={r["name"] for r in db.execute("PRAGMA table_info(users)")}
        if "daily_streak" not in columns:
            db.execute("ALTER TABLE users ADD COLUMN daily_streak INTEGER NOT NULL DEFAULT 0")
        if "vip_expires_at" not in columns:
            db.execute("ALTER TABLE users ADD COLUMN vip_expires_at TEXT")
        payout_columns={r["name"] for r in db.execute("PRAGMA table_info(payout_requests)")}
        if "conversion_version" not in payout_columns:
            # Registros já existentes mantêm a conversão histórica (100 pontos = R$ 1).
            db.execute("ALTER TABLE payout_requests ADD COLUMN conversion_version INTEGER NOT NULL DEFAULT 1")
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


def create_reward_order(user_id,reward_id,update_id=None):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        found,result=_idempotency_lookup(db,update_id,"shop.purchase")
        if found:
            db.rollback()
            return int(result)
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
        _idempotency_save(db,update_id,"shop.purchase",order_id)
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

def register_user(uid,username,first_name,referrer=None,referral_reward=0,is_bot=False,welcome_reward=0):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM users WHERE user_id=?",(uid,)).fetchone():
            db.execute("UPDATE users SET username=?,first_name=? WHERE user_id=?",(username,first_name,uid)); db.commit(); return False,None,None
        if referrer==uid or (referrer and not db.execute("SELECT 1 FROM users WHERE user_id=?",(referrer,)).fetchone()): referrer=None
        db.execute("INSERT INTO users(user_id,username,first_name,referred_by) VALUES(?,?,?,?)",(uid,username,first_name,referrer))
        if not is_bot and int(welcome_reward)>0:
            welcome_points=int(welcome_reward)
            db.execute("UPDATE users SET points=points+? WHERE user_id=?",(welcome_points,uid))
            db.execute("INSERT INTO point_history(user_id,amount,reason) VALUES(?,?,?)",(uid,welcome_points,"Bônus de boas-vindas"))
            db.execute("INSERT INTO weekly_earnings(user_id,points,source) VALUES(?,?,?)",(uid,welcome_points,"welcome"))
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

def admin_user_ids_page(page=0,page_size=30):
    page=max(0,int(page))
    page_size=max(1,min(int(page_size),100))
    with connect() as db:
        total=db.execute("SELECT COUNT(*) AS total FROM users").fetchone()["total"]
        rows=db.execute("SELECT user_id FROM users ORDER BY user_id LIMIT ? OFFSET ?",(page_size,page*page_size)).fetchall()
        return total,[row["user_id"] for row in rows]

def add_points(uid,amount,reason,update_id=None):
    if amount==0:return
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        found,_=_idempotency_lookup(db,update_id,"admin.points_adjustment")
        if found:
            db.rollback()
            return False
        row=db.execute("SELECT points FROM users WHERE user_id=?",(uid,)).fetchone()
        if not row:
            if amount<0:
                db.rollback()
                raise ValueError("Usuário não encontrado.")
            db.execute("INSERT INTO users(user_id) VALUES(?)",(uid,))
        elif row["points"]+amount<0:
            db.rollback()
            raise ValueError("Saldo insuficiente.")
        db.execute("UPDATE users SET points=points+? WHERE user_id=?",(amount,uid))
        db.execute("INSERT INTO point_history(user_id,amount,reason) VALUES(?,?,?)",(uid,amount,reason))
        if amount>0: db.execute("INSERT INTO weekly_earnings(user_id,points,source) VALUES(?,?,?)",(uid,amount,"admin_adjustment"))
        _idempotency_save(db,update_id,"admin.points_adjustment",True)
        db.commit()
        return True

def daily_claim(uid,reward):
    from datetime import datetime, timezone, timedelta
    rewards=tuple(int(value) for value in reward) if isinstance(reward,(list,tuple)) else (int(reward),)
    if not rewards or any(value < 0 for value in rewards):
        raise ValueError("A sequência de recompensas diárias é inválida.")
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
        if earned>0:
            db.execute("INSERT INTO point_history(user_id,amount,reason) VALUES(?,?,?)",(uid,earned,f"Check-in — dia {(streak-1)%len(rewards)+1} da sequência"))
            db.execute("INSERT INTO weekly_earnings(user_id,points,source) VALUES(?,?,?)",(uid,earned,"daily_checkin"))
        db.commit(); return True,streak,earned

def ranking(limit=10):
    with connect() as db: return db.execute("SELECT user_id,first_name,username,points FROM users ORDER BY points DESC LIMIT ?",(limit,)).fetchall()

def _idempotency_lookup(db,update_id,action):
    if update_id is None:
        return False,None
    row=db.execute("SELECT action,result FROM idempotency_keys WHERE update_id=?",(int(update_id),)).fetchone()
    if not row:
        return False,None
    if row["action"]!=action:
        raise ValueError("Identificador de atualização já utilizado em outra operação.")
    try:
        return True,json.loads(row["result"])
    except (TypeError,ValueError):
        return True,None

def _idempotency_save(db,update_id,action,result):
    if update_id is None:
        return
    db.execute(
        "INSERT INTO idempotency_keys(update_id,action,result) VALUES(?,?,?)",
        (int(update_id),action,json.dumps(result,ensure_ascii=False,separators=(",",":")))
    )

def create_redemption(uid,points,reward,update_id=None):
    points=int(points)
    reward=(reward or "").strip()
    if points<1 or points>10000000:
        raise ValueError("Quantidade de pontos inválida.")
    if not reward or len(reward)>500:
        raise ValueError("Informe uma descrição válida para o resgate (até 500 caracteres).")
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        found,result=_idempotency_lookup(db,update_id,"redemption.create")
        if found:
            db.rollback()
            return int(result)
        row=db.execute("SELECT points FROM users WHERE user_id=?",(uid,)).fetchone()
        if not row or row["points"]<points: db.rollback(); raise ValueError("Saldo insuficiente.")
        db.execute("UPDATE users SET points=points-? WHERE user_id=?",(points,uid))
        cur=db.execute("INSERT INTO redemptions(user_id,points,reward) VALUES(?,?,?)",(uid,points,reward)); rid=cur.lastrowid
        db.execute("INSERT INTO point_history(user_id,amount,reason) VALUES(?,?,?)",(uid,-points,f"Resgate #{rid}"))
        _idempotency_save(db,update_id,"redemption.create",rid)
        db.commit(); return rid

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
        cur=db.execute("UPDATE users SET is_vip=?,vip_expires_at=NULL WHERE user_id=?",(int(bool(enabled)),uid))
        db.commit()
        return cur.rowcount==1

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


def play_daily_game(uid,game,points):
    if game not in ("chest","roulette","scratch"): raise ValueError("Jogo inválido.")
    points=max(0,min(int(points),100))
    current=today()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute("INSERT INTO daily_games(user_id,game,points,played_on) VALUES(?,?,?,?)",(uid,game,points,current))
        except sqlite3.IntegrityError:
            db.rollback()
            raise ValueError("Você já utilizou sua tentativa deste jogo hoje. Volte amanhã!")
        if points:
            db.execute("UPDATE users SET points=points+? WHERE user_id=?",(points,uid))
            reason={"chest":"Baú surpresa diário","roulette":"Roleta de pontos","scratch":"Raspadinha virtual"}[game]
            db.execute("INSERT INTO point_history(user_id,amount,reason) VALUES(?,?,?)",(uid,points,reason))
            db.execute("INSERT INTO weekly_earnings(user_id,points,source) VALUES(?,?,?)",(uid,points,"game_"+game))
        db.commit()
        return points

def game_status(uid):
    current=today()
    with connect() as db:
        rows=db.execute("SELECT game,points FROM daily_games WHERE user_id=? AND played_on=?",(uid,current)).fetchall()
        return {r["game"]:int(r["points"]) for r in rows}

def notification_history(uid,limit=10):
    with connect() as db:
        return db.execute("SELECT category,title,message,created_at FROM notification_events WHERE user_id=? ORDER BY id DESC LIMIT ?",(uid,limit)).fetchall()

def record_notification(uid,category,title,message):
    with connect() as db:
        db.execute("INSERT INTO notification_events(user_id,category,title,message) VALUES(?,?,?,?)",(uid,category,title,message))
        db.commit()

def financial_dashboard():
    with connect() as db:
        row=db.execute("""
            SELECT
              COALESCE((SELECT SUM(amount) FROM point_history WHERE amount>0),0) AS points_issued,
              COALESCE((SELECT -SUM(amount) FROM point_history WHERE amount<0),0) AS points_debited,
              COALESCE((SELECT SUM(points) FROM payout_requests WHERE status='pending'),0) AS points_reserved,
              COALESCE((SELECT SUM(amount_cents) FROM payout_requests WHERE status='approved'),0) AS pix_paid_cents,
              COALESCE((SELECT SUM(amount_cents) FROM payout_requests WHERE status='pending'),0) AS pix_pending_cents,
              COALESCE((SELECT SUM(points) FROM payout_requests WHERE status='rejected'),0) AS rejected_payout_points,
              COALESCE((SELECT SUM(points) FROM redemptions WHERE status='approved'),0) AS approved_redemptions,
              COALESCE((SELECT SUM(points_spent) FROM reward_orders WHERE status='approved'),0) AS approved_store_points,
              COALESCE((SELECT SUM(points) FROM daily_games),0) AS game_points,
              COALESCE((SELECT SUM(points) FROM users),0) AS wallet_balance_points,
              COALESCE((SELECT SUM(amount) FROM point_history),0) AS ledger_net_points,
              COALESCE((SELECT SUM(points) FROM redemptions WHERE status='pending'),0) AS pending_redemption_points,
              COALESCE((SELECT SUM(points_spent) FROM reward_orders WHERE status='pending'),0) AS pending_store_points
        """).fetchone()
        result=dict(row)
        result["ledger_difference"]=int(result["wallet_balance_points"])-int(result["ledger_net_points"])
        result["ledger_reconciled"]=result["ledger_difference"]==0
        return result

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

def create_payout_request(uid,points,pix_key,pix_key_type,min_points=10000,update_id=None):
    points=int(points)
    min_points=int(min_points)
    pix_key=(pix_key or "").strip()
    pix_key_type=(pix_key_type or "").strip().upper()
    if min_points<1:
        raise ValueError("O valor mínimo de saque configurado é inválido.")
    if points<min_points or points%10!=0:
        raise ValueError(f"O saque mínimo é de {min_points:,} pontos e o valor deve ser múltiplo de 10.")
    if not pix_key or len(pix_key)>200: raise ValueError("Chave Pix inválida.")
    if pix_key_type not in ("CPF","CNPJ","EMAIL","TELEFONE","ALEATORIA"): raise ValueError("Tipo de chave Pix inválido.")
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        found,result=_idempotency_lookup(db,update_id,"payout.create")
        if found:
            db.rollback()
            return int(result)
        row=db.execute("SELECT points FROM users WHERE user_id=?",(uid,)).fetchone()
        if not row or row["points"]<points:
            db.rollback(); raise ValueError("Saldo insuficiente.")
        pending=db.execute("SELECT 1 FROM payout_requests WHERE user_id=? AND status='pending'",(uid,)).fetchone()
        if pending:
            db.rollback(); raise ValueError("Você já possui um saque aguardando análise.")
        db.execute("UPDATE users SET points=points-? WHERE user_id=?",(points,uid))
        cur=db.execute("INSERT INTO payout_requests(user_id,points,amount_cents,conversion_version,pix_key,pix_key_type) VALUES(?,?,?,?,?,?)",(uid,points,points//10,2,_encrypt_payout_pix_key(pix_key),pix_key_type))
        rid=cur.lastrowid
        db.execute("INSERT INTO point_history(user_id,amount,reason) VALUES(?,?,?)",(uid,-points,f"Reserva para saque #{rid}"))
        _idempotency_save(db,update_id,"payout.create",rid)
        db.commit(); return rid

_PAYOUT_PIX_PREFIX="enc:v1:"

def _encrypt_payout_pix_key(value):
    return _PAYOUT_PIX_PREFIX+_encrypt_pix_value(value)

def _decrypt_payout_pix_key(value):
    value=str(value or "")
    if value.startswith(_PAYOUT_PIX_PREFIX):
        return _decrypt_pix_value(value[len(_PAYOUT_PIX_PREFIX):])
    # Registros anteriores à correção permanecem legíveis durante a migração.
    return value

def _migrate_legacy_payout_pix_keys(db):
    rows=db.execute("SELECT id,pix_key FROM payout_requests WHERE pix_key NOT LIKE ?",(_PAYOUT_PIX_PREFIX+"%",)).fetchall()
    for row in rows:
        encrypted=_encrypt_payout_pix_key(row["pix_key"])
        db.execute("UPDATE payout_requests SET pix_key=? WHERE id=? AND pix_key=?", (encrypted,row["id"],row["pix_key"]))

def _masked_pix_key(value):
    value=str(value or "")
    if not value: return "não informada"
    return (value[:2]+"••••"+value[-2:]) if len(value)>6 else "••••"

def pending_payouts():
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        _migrate_legacy_payout_pix_keys(db)
        rows=db.execute("SELECT * FROM payout_requests WHERE status='pending' ORDER BY id").fetchall()
        result=[]
        for row in rows:
            item=dict(row)
            item["pix_key"]=_decrypt_payout_pix_key(item["pix_key"])
            result.append(item)
        db.commit()
        return result

def user_payout_requests(user_id,limit=10):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        _migrate_legacy_payout_pix_keys(db)
        rows=db.execute("""
            SELECT id,points,amount_cents,pix_key_type,pix_key,status,created_at,reviewed_at
            FROM payout_requests
            WHERE user_id=?
            ORDER BY id DESC LIMIT ?
        """,(user_id,limit)).fetchall()
        result=[]
        for row in rows:
            item=dict(row)
            item["pix_key_masked"]=_masked_pix_key(_decrypt_payout_pix_key(item["pix_key"]))
            item.pop("pix_key",None)
            result.append(item)
        db.commit()
        return result

def cancel_payout_request(user_id,payout_id):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        _migrate_legacy_payout_pix_keys(db)
        row=db.execute("SELECT * FROM payout_requests WHERE id=? AND user_id=? AND status='pending'",(payout_id,user_id)).fetchone()
        if not row:
            db.rollback()
            return None
        cur=db.execute("UPDATE payout_requests SET status='cancelled',reviewed_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=? AND status='pending'",(payout_id,user_id))
        if cur.rowcount != 1:
            db.rollback()
            return None
        db.execute("UPDATE users SET points=points+? WHERE user_id=?",(row["points"],user_id))
        db.execute("INSERT INTO point_history(user_id,amount,reason) VALUES(?,?,?)",(user_id,row["points"],f"Cancelamento do saque #{payout_id}"))
        db.commit()
        return dict(row)

def reduce_pending_payout(rid,new_points,admin_id,min_points=10000):
    rid=int(rid); new_points=int(new_points); admin_id=int(admin_id); min_points=int(min_points)
    if admin_id not in ADMIN_IDS:
        raise ValueError('Apenas administradores podem diminuir saques.')
    if min_points<1:
        raise ValueError('O valor mínimo de saque configurado é inválido.')
    if new_points<min_points:
        raise ValueError(f'O novo saque não pode ser inferior ao mínimo de {min_points:,} pontos.')
    if new_points%10!=0:
        raise ValueError('O novo valor deve ser múltiplo de 10 pontos.')
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute("SELECT * FROM payout_requests WHERE id=? AND status='pending'",(rid,)).fetchone()
        if not row:
            db.rollback(); return None
        old_points=int(row['points'])
        if new_points>=old_points:
            db.rollback(); raise ValueError('O novo valor precisa ser menor que o valor atual do saque.')
        refunded=old_points-new_points
        # Pedidos anteriores à nova taxa preservam sua conversão histórica.
        conversion_version=int(row['conversion_version']) if 'conversion_version' in row.keys() else 1
        divisor=10 if conversion_version>=2 else 1
        amount_cents=new_points//divisor
        payout_update=db.execute("UPDATE payout_requests SET points=?,amount_cents=? WHERE id=? AND status='pending'",(new_points,amount_cents,rid))
        if payout_update.rowcount != 1:
            db.rollback(); return None
        wallet_update=db.execute('UPDATE users SET points=points+? WHERE user_id=?',(refunded,row['user_id']))
        if wallet_update.rowcount != 1:
            db.rollback(); raise ValueError('Não foi possível localizar a carteira do usuário; saque não foi alterado.')
        db.execute('INSERT INTO point_history(user_id,amount,reason) VALUES(?,?,?)',(row['user_id'],refunded,'Devolução após redução do saque #'+str(rid)))
        db.execute('INSERT INTO admin_audit_log(admin_id,action,details) VALUES(?,?,?)',(admin_id,'payout_reduced',f'Saque #{rid}: {old_points} para {new_points}; devolvidos {refunded} pontos'))
        result=dict(row); result.update({'points':new_points,'amount_cents':amount_cents,'refunded_points':refunded})
        db.commit(); return result

def review_payout(rid,admin_id,approve):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        _migrate_legacy_payout_pix_keys(db)
        row=db.execute("SELECT * FROM payout_requests WHERE id=? AND status='pending'",(rid,)).fetchone()
        if not row:
            db.rollback(); return None
        status="approved" if approve else "rejected"
        db.execute("UPDATE payout_requests SET status=?,reviewed_by=?,reviewed_at=CURRENT_TIMESTAMP WHERE id=?",(status,admin_id,rid))
        if not approve:
            db.execute("UPDATE users SET points=points+? WHERE user_id=?",(row["points"],row["user_id"]))
            db.execute("INSERT INTO point_history(user_id,amount,reason) VALUES(?,?,?)",(row["user_id"],row["points"],f"Estorno do saque #{rid}"))
        else:
            db.execute("INSERT INTO point_history(user_id,amount,reason) VALUES(?,?,?)",(row["user_id"],0,f"Pagamento Pix confirmado — saque #{rid} (R$ {row['amount_cents']/100:.2f})"))
        result=dict(row)
        result["pix_key"]=_decrypt_payout_pix_key(result["pix_key"])
        db.commit(); return result

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

def review_referral(rid,admin_id,approve,reward_points):
    reward_points=int(reward_points)
    if reward_points<0:
        raise ValueError("A recompensa da indicação não pode ser negativa.")
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
        db.execute("UPDATE referral_reviews SET status=?,reviewed_by=?,reviewed_at=CURRENT_TIMESTAMP WHERE id=? AND status='pending'",(status,admin_id,rid))
        if approve and reward_points>0:
            db.execute("UPDATE users SET points=points+? WHERE user_id=?",(reward_points,row["referrer_id"]))
            db.execute("INSERT INTO point_history(user_id,amount,reason) VALUES(?,?,?)",(row["referrer_id"],reward_points,f"Indicação aprovada #{rid}"))
            db.execute("INSERT INTO weekly_earnings(user_id,points,source) VALUES(?,?,?)",(row["referrer_id"],reward_points,"referral_approved"))
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


def enqueue_update(update):
    update_id=int(update["update_id"])
    payload=json.dumps(update,ensure_ascii=False,separators=(",",":"))
    with connect() as db:
        cur=db.execute("INSERT OR IGNORE INTO durable_updates(update_id,payload) VALUES(?,?)",(update_id,payload))
        db.commit()
        return cur.rowcount == 1

def pending_updates(limit=500,after_update_id=0):
    with connect() as db:
        rows=db.execute("SELECT payload FROM durable_updates WHERE status='pending' AND update_id>? ORDER BY update_id LIMIT ?",(int(after_update_id),max(1,min(int(limit),2000)))).fetchall()
        return [json.loads(row["payload"]) for row in rows]

def set_pending_task_proof(user_id,task_id):
    with connect() as db:
        db.execute("INSERT INTO pending_task_proofs(user_id,task_id) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET task_id=excluded.task_id,created_at=CURRENT_TIMESTAMP",(int(user_id),int(task_id)))
        db.commit()

def get_pending_task_proof(user_id):
    with connect() as db:
        row=db.execute("SELECT task_id FROM pending_task_proofs WHERE user_id=?",(int(user_id),)).fetchone()
        return int(row["task_id"]) if row else None

def clear_pending_task_proof(user_id):
    with connect() as db:
        cur=db.execute("DELETE FROM pending_task_proofs WHERE user_id=?",(int(user_id),))
        db.commit()
        return cur.rowcount==1

def update_was_processed(update_id):
    with connect() as db:
        return db.execute("SELECT 1 FROM processed_updates WHERE update_id=?",(int(update_id),)).fetchone() is not None

def mark_update_processed(update_id):
    with connect() as db:
        db.execute("INSERT OR IGNORE INTO processed_updates(update_id) VALUES(?)",(int(update_id),))
        db.execute("UPDATE durable_updates SET status='completed',completed_at=CURRENT_TIMESTAMP WHERE update_id=?",(int(update_id),))
        db.commit()

def cleanup_processed_updates(keep_days=14):
    with connect() as db:
        cur=db.execute("DELETE FROM processed_updates WHERE processed_at<datetime('now',?)",(f"-{int(keep_days)} days",))
        db.execute("DELETE FROM durable_updates WHERE status='completed' AND completed_at<datetime('now',?)",(f"-{int(keep_days)} days",))
        db.execute("DELETE FROM idempotency_keys WHERE created_at<datetime('now','-30 days')")
        db.commit()
        return cur.rowcount

def log_admin_action(admin_id,action,details=""):
    with connect() as db:
        db.execute("INSERT INTO admin_audit_log(admin_id,action,details) VALUES(?,?,?)",(int(admin_id),str(action)[:100],str(details)[:1000]))
        db.commit()

def recent_admin_audit(limit=30):
    with connect() as db:
        return [dict(r) for r in db.execute("SELECT * FROM admin_audit_log ORDER BY id DESC LIMIT ?",(max(1,min(int(limit),100)),)).fetchall()]


def health_snapshot():
    with connect() as db:
        integrity=db.execute("PRAGMA quick_check").fetchone()
        pending=db.execute("SELECT COUNT(*) AS total, MIN(received_at) AS oldest FROM durable_updates WHERE status='pending'").fetchone()
        return {
            "database_integrity": integrity[0] if integrity else "unknown",
            "pending_updates": int(pending["total"] or 0),
            "oldest_pending_at": pending["oldest"],
        }


def should_notify_health_alert(alert_key, details, cooldown_minutes=30):
    key=str(alert_key)[:80]
    message=str(details)[:1000]
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row=db.execute("SELECT status,last_notified_at FROM health_alert_state WHERE alert_key=?",(key,)).fetchone()
        should_notify=(
            row is None or row["status"]!="active" or row["last_notified_at"] is None
            or db.execute(
                "SELECT datetime(?) <= datetime('now',?)",
                (row["last_notified_at"],f"-{max(1,int(cooldown_minutes))} minutes")
            ).fetchone()[0]
        )
        db.execute(
            """INSERT INTO health_alert_state(alert_key,status,details,first_seen_at,last_seen_at,last_notified_at,resolved_at)
               VALUES(?,'active',?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END,NULL)
               ON CONFLICT(alert_key) DO UPDATE SET
                 status='active',details=excluded.details,last_seen_at=CURRENT_TIMESTAMP,
                 last_notified_at=CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE health_alert_state.last_notified_at END,
                 resolved_at=NULL""",
            (key,message,int(should_notify),int(should_notify))
        )
        db.commit()
        return bool(should_notify)


def resolve_health_alert(alert_key):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row=db.execute("SELECT status FROM health_alert_state WHERE alert_key=?",(str(alert_key)[:80],)).fetchone()
        if not row or row["status"]!="active":
            db.rollback()
            return False
        db.execute(
            "UPDATE health_alert_state SET status='resolved',last_seen_at=CURRENT_TIMESTAMP,resolved_at=CURRENT_TIMESTAMP WHERE alert_key=?",
            (str(alert_key)[:80],)
        )
        db.commit()
        return True


def active_health_alerts(limit=50):
    with connect() as db:
        rows=db.execute(
            "SELECT alert_key,details,first_seen_at,last_seen_at,last_notified_at FROM health_alert_state WHERE status='active' ORDER BY last_seen_at DESC LIMIT ?",
            (max(1,min(int(limit),100)),)
        ).fetchall()
        return [dict(row) for row in rows]


def set_health_metric(metric_key, metric_value):
    key=str(metric_key)[:80]
    value=str(metric_value)[:500]
    with connect() as db:
        db.execute(
            """INSERT INTO health_monitor_state(metric_key,metric_value,updated_at)
               VALUES(?,?,CURRENT_TIMESTAMP)
               ON CONFLICT(metric_key) DO UPDATE SET
                 metric_value=excluded.metric_value,updated_at=CURRENT_TIMESTAMP""",
            (key,value)
        )
        db.commit()


def get_health_metric(metric_key):
    with connect() as db:
        row=db.execute(
            "SELECT metric_value,updated_at FROM health_monitor_state WHERE metric_key=?",
            (str(metric_key)[:80],)
        ).fetchone()
        return dict(row) if row else None


def recent_health_alerts(limit=10):
    with connect() as db:
        rows=db.execute(
            """SELECT alert_key,status,details,first_seen_at,last_seen_at,resolved_at
               FROM health_alert_state ORDER BY last_seen_at DESC LIMIT ?""",
            (max(1,min(int(limit),50)),)
        ).fetchall()
        return [dict(row) for row in rows]


def _encrypt_pix_value(value):
    key=_load_key()
    nonce=os.urandom(12)
    encrypted=AESGCM(key).encrypt(nonce,str(value).encode("utf-8"),b"PITPIX1")
    return base64.urlsafe_b64encode(nonce+encrypted).decode("ascii")


def _decrypt_pix_value(value):
    raw=base64.urlsafe_b64decode(str(value).encode("ascii"))
    if len(raw)<29:
        raise ValueError("Cadastro Pix criptografado inválido.")
    return AESGCM(_load_key()).decrypt(raw[:12],raw[12:],b"PITPIX1").decode("utf-8")


def set_pix_setup_step(user_id,step,key_type,pix_key=None):
    encrypted=_encrypt_pix_value(pix_key) if pix_key is not None else None
    with connect() as db:
        db.execute("""INSERT INTO pix_setup_state(user_id,step,pix_key_type,pix_key_encrypted,updated_at)
                      VALUES(?,?,?,?,CURRENT_TIMESTAMP)
                      ON CONFLICT(user_id) DO UPDATE SET step=excluded.step,pix_key_type=excluded.pix_key_type,
                      pix_key_encrypted=excluded.pix_key_encrypted,updated_at=CURRENT_TIMESTAMP""",
                   (int(user_id),str(step),str(key_type).upper(),encrypted))
        if str(step)=="key":
            db.execute("UPDATE pix_profiles SET status='pending',reviewed_by=NULL,reviewed_at=NULL WHERE user_id=?",(int(user_id),))
        db.commit()


def get_pix_setup_step(user_id):
    with connect() as db:
        row=db.execute("SELECT * FROM pix_setup_state WHERE user_id=?",(int(user_id),)).fetchone()
        if not row: return None
        result=dict(row)
        if result["pix_key_encrypted"]:
            result["pix_key"]=_decrypt_pix_value(result["pix_key_encrypted"])
        return result


def clear_pix_setup_step(user_id):
    with connect() as db:
        db.execute("DELETE FROM pix_setup_state WHERE user_id=?",(int(user_id),))
        db.commit()


def save_pix_profile(user_id,key_type,pix_key,owner_name):
    encrypted=_encrypt_pix_value(pix_key)
    with connect() as db:
        db.execute("""INSERT INTO pix_profiles(user_id,pix_key_encrypted,pix_key_type,owner_name,status)
                      VALUES(?,?,?,?, 'pending')
                      ON CONFLICT(user_id) DO UPDATE SET pix_key_encrypted=excluded.pix_key_encrypted,
                      pix_key_type=excluded.pix_key_type,owner_name=excluded.owner_name,status='pending',
                      created_at=CURRENT_TIMESTAMP,reviewed_by=NULL,reviewed_at=NULL""",
                   (int(user_id),encrypted,str(key_type).upper(),str(owner_name).strip()[:120]))
        db.commit()


def get_pix_profile(user_id):
    with connect() as db:
        row=db.execute("SELECT * FROM pix_profiles WHERE user_id=?",(int(user_id),)).fetchone()
        if not row: return None
        result=dict(row)
        result["pix_key"]=_decrypt_pix_value(result["pix_key_encrypted"])
        return result


def delete_pix_profile(user_id):
    with connect() as db:
        db.execute("DELETE FROM pix_profiles WHERE user_id=?",(int(user_id),))
        db.commit()


def review_pix_profile(user_id,admin_id,approve):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row=db.execute("SELECT status FROM pix_profiles WHERE user_id=?",(int(user_id),)).fetchone()
        if not row or row["status"]!="pending":
            db.rollback()
            return None
        status="approved" if approve else "rejected"
        db.execute("UPDATE pix_profiles SET status=?,reviewed_by=?,reviewed_at=CURRENT_TIMESTAMP WHERE user_id=? AND status='pending'",
                   (status,int(admin_id),int(user_id)))
        db.commit()
    return {"user_id":int(user_id),"status":status}


def create_redeem_code(points,max_uses,admin_id):
    import secrets
    points=int(points); max_uses=int(max_uses)
    if points<1 or points>10000000:
        raise ValueError("A quantidade deve ser de 1 a 10.000.000 pontos.")
    if max_uses<1 or max_uses>10000:
        raise ValueError("A quantidade de usos deve ser de 1 a 10.000.")
    with connect() as db:
        for _ in range(5):
            code="PIT-"+secrets.token_hex(4).upper()
            try:
                db.execute("INSERT INTO redeem_codes(code,points,max_uses,created_by) VALUES(?,?,?,?)",(code,points,max_uses,int(admin_id)))
                db.execute("INSERT INTO admin_audit_log(admin_id,action,details) VALUES(?,?,?)",(int(admin_id),"redeem_code_created",f"{code}: {points} pontos; {max_uses} usos"))
                db.commit()
                return code
            except sqlite3.IntegrityError:
                db.rollback()
        raise RuntimeError("Não foi possível gerar um código exclusivo. Tente novamente.")

def redeem_code(code,user_id):
    code=str(code or "").strip().upper()
    if len(code)>40 or not code:
        raise ValueError("Código inválido.")
    user_id=int(user_id)
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row=db.execute("SELECT * FROM redeem_codes WHERE code=? AND active=1",(code,)).fetchone()
        if not row:
            db.rollback()
            raise ValueError("Código inválido, inexistente ou desativado.")
        if int(row["uses"])>=int(row["max_uses"]):
            db.rollback()
            raise ValueError("Esse código já atingiu o limite de resgates.")
        if db.execute("SELECT 1 FROM redeem_code_uses WHERE code=? AND user_id=?",(code,user_id)).fetchone():
            db.rollback()
            raise ValueError("Você já resgatou esse código.")
        user=db.execute("SELECT points FROM users WHERE user_id=?",(user_id,)).fetchone()
        if not user:
            db.rollback()
            raise ValueError("Abra o bot com /start antes de resgatar um código.")
        points=int(row["points"])
        db.execute("INSERT INTO redeem_code_uses(code,user_id,points) VALUES(?,?,?)",(code,user_id,points))
        db.execute("UPDATE redeem_codes SET uses=uses+1,active=CASE WHEN uses+1>=max_uses THEN 0 ELSE active END WHERE code=?",(code,))
        db.execute("UPDATE users SET points=points+? WHERE user_id=?",(points,user_id))
        db.execute("INSERT INTO point_history(user_id,amount,reason) VALUES(?,?,?)",(user_id,points,f"Código de resgate {code}"))
        db.execute("INSERT INTO weekly_earnings(user_id,points,source) VALUES(?,?,?)",(user_id,points,"redeem_code"))
        db.commit()
        return {"code":code,"points":points,"balance":int(user["points"])+points}


def set_user_input_state(user_id,state):
    if state not in ("redeem_code","payout_points"):
        raise ValueError("Estado de entrada inválido.")
    with connect() as db:
        db.execute("INSERT INTO user_input_states(user_id,state) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET state=excluded.state,updated_at=CURRENT_TIMESTAMP",(int(user_id),state))
        db.commit()

def get_user_input_state(user_id):
    with connect() as db:
        row=db.execute("SELECT state FROM user_input_states WHERE user_id=?",(int(user_id),)).fetchone()
        return row["state"] if row else None

def clear_user_input_state(user_id):
    with connect() as db:
        db.execute("DELETE FROM user_input_states WHERE user_id=?",(int(user_id),))
        db.commit()
