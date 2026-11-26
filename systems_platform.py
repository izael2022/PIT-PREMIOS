"""Additive platform systems for PIT PRÊMIOS. Isolated SQLite helpers; never mutate wallet balances."""
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS platform_tickets(
 id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,subject TEXT NOT NULL,message TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','answered','closed')),
 response TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS platform_limits(
 scope TEXT NOT NULL,scope_id TEXT NOT NULL,limit_value INTEGER NOT NULL CHECK(limit_value>=0),
 updated_by INTEGER NOT NULL,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(scope,scope_id));
CREATE TABLE IF NOT EXISTS platform_limit_usage(
 scope TEXT NOT NULL,scope_id TEXT NOT NULL,user_id INTEGER NOT NULL,period_key TEXT NOT NULL,
 used INTEGER NOT NULL DEFAULT 0 CHECK(used>=0),PRIMARY KEY(scope,scope_id,user_id,period_key));
CREATE TABLE IF NOT EXISTS platform_fraud_reviews(
 id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,category TEXT NOT NULL,details TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected','blocked')),
 reviewed_by INTEGER,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,reviewed_at TEXT);
CREATE TABLE IF NOT EXISTS platform_user_levels(
 user_id INTEGER PRIMARY KEY,xp INTEGER NOT NULL DEFAULT 0 CHECK(xp>=0),updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS platform_badges(
 badge_key TEXT PRIMARY KEY,title TEXT NOT NULL,description TEXT NOT NULL DEFAULT '',active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS platform_user_badges(
 user_id INTEGER NOT NULL,badge_key TEXT NOT NULL,earned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(user_id,badge_key));
CREATE TABLE IF NOT EXISTS platform_announcements(
 id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,message TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,
 start_at TEXT,end_at TEXT,created_by INTEGER NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS platform_admin_logs(
 id INTEGER PRIMARY KEY AUTOINCREMENT,admin_id INTEGER NOT NULL,action TEXT NOT NULL,details TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS platform_notifications(
 id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,title TEXT NOT NULL,message TEXT NOT NULL,
 expires_at TEXT,read_at TEXT,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS idx_platform_notifications_user ON platform_notifications(user_id,read_at,id DESC);
CREATE INDEX IF NOT EXISTS idx_platform_ticket_status ON platform_tickets(status,id DESC);
CREATE INDEX IF NOT EXISTS idx_platform_reviews_status ON platform_fraud_reviews(status,id DESC);
"""
def initialize(path):
    with sqlite3.connect(path,timeout=30) as c:
        c.executescript(SCHEMA)
        c.executemany("INSERT OR IGNORE INTO platform_badges(badge_key,title,description) VALUES(?,?,?)",[
            ("xp_1000","Primeiro nível","Acumule 1.000 XP."),
            ("xp_5000","Veterano","Acumule 5.000 XP."),
            ("xp_10000","Lenda PIT","Acumule 10.000 XP."),
        ])
        c.commit()

def _valid_id(value,label):
    if not isinstance(value,int) or isinstance(value,bool) or value<=0:raise ValueError(label+" inválido.")

def _now():
    return datetime.now(timezone.utc).isoformat()

def open_ticket(path,user_id,subject,message):
    _valid_id(user_id,"Usuário")
    if not isinstance(subject,str) or not subject.strip() or len(subject.strip())>120:raise ValueError("Assunto inválido.")
    if not isinstance(message,str) or not message.strip() or len(message.strip())>4000:raise ValueError("Mensagem inválida.")
    with sqlite3.connect(path,timeout=30) as c:
        cur=c.execute("INSERT INTO platform_tickets(user_id,subject,message) VALUES(?,?,?)",(user_id,subject.strip(),message.strip()))
        c.commit();return cur.lastrowid

def ticket_list(path,user_id=None,status=None,limit=50):
    if user_id is not None:_valid_id(user_id,"Usuário")
    if status not in (None,"open","answered","closed"):raise ValueError("Status inválido.")
    limit=max(1,min(int(limit),100))
    q="SELECT * FROM platform_tickets WHERE 1=1";a=[]
    if user_id is not None:q+=" AND user_id=?";a.append(user_id)
    if status:q+=" AND status=?";a.append(status)
    q+=" ORDER BY id DESC LIMIT ?";a.append(limit)
    with sqlite3.connect(path,timeout=30) as c:
        c.row_factory=sqlite3.Row;return [dict(r) for r in c.execute(q,a)]

def answer_ticket(path,ticket_id,admin_id,response,close=False):
    _valid_id(ticket_id,"Ticket");_valid_id(admin_id,"Administrador")
    if not isinstance(response,str) or not response.strip() or len(response)>4000:raise ValueError("Resposta inválida.")
    status="closed" if close else "answered"
    with sqlite3.connect(path,timeout=30) as c:
        c.execute("BEGIN IMMEDIATE")
        cur=c.execute("UPDATE platform_tickets SET response=?,status=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND status IN ('open','answered')",(response.strip(),status,ticket_id))
        if cur.rowcount!=1:c.rollback();return False
        c.commit();return True

def set_limit(path,scope,scope_id,limit_value,admin_id):
    _valid_id(admin_id,"Administrador")
    if scope not in ("user","mission","event","period","global"):raise ValueError("Escopo inválido.")
    if not isinstance(scope_id,str) or not scope_id.strip() or len(scope_id)>100:raise ValueError("Identificador inválido.")
    if not isinstance(limit_value,int) or isinstance(limit_value,bool) or limit_value<0 or limit_value>10**9:raise ValueError("Limite inválido.")
    with sqlite3.connect(path,timeout=30) as c:
        c.execute("INSERT INTO platform_limits(scope,scope_id,limit_value,updated_by) VALUES(?,?,?,?) ON CONFLICT(scope,scope_id) DO UPDATE SET limit_value=excluded.limit_value,updated_by=excluded.updated_by,updated_at=CURRENT_TIMESTAMP",(scope,scope_id.strip(),limit_value,admin_id));c.commit()

def consume_limit(path,scope,scope_id,user_id,period_key,amount=1):
    _valid_id(user_id,"Usuário")
    if scope not in ("user","mission","event","period","global"):raise ValueError("Escopo inválido.")
    for v,l in ((scope_id,"Escopo"),(period_key,"Período")):
        if not isinstance(v,str) or not v.strip() or len(v)>100:raise ValueError(l+" inválido.")
    if not isinstance(amount,int) or isinstance(amount,bool) or amount<=0:raise ValueError("Quantidade inválida.")
    with sqlite3.connect(path,timeout=30) as c:
        c.execute("BEGIN IMMEDIATE")
        row=c.execute("SELECT limit_value FROM platform_limits WHERE scope=? AND scope_id=?",(scope,scope_id)).fetchone()
        if row is None:c.rollback();return True
        used=c.execute("SELECT used FROM platform_limit_usage WHERE scope=? AND scope_id=? AND user_id=? AND period_key=?",(scope,scope_id,user_id,period_key)).fetchone()
        current=used[0] if used else 0
        if current+amount>row[0]:c.rollback();return False
        c.execute("INSERT INTO platform_limit_usage(scope,scope_id,user_id,period_key,used) VALUES(?,?,?,?,?) ON CONFLICT(scope,scope_id,user_id,period_key) DO UPDATE SET used=used+excluded.used",(scope,scope_id,user_id,period_key,amount))
        c.commit();return True

def flag_user(path,user_id,category,details):
    _valid_id(user_id,"Usuário")
    if not isinstance(category,str) or not category.strip() or len(category)>80:raise ValueError("Categoria inválida.")
    if not isinstance(details,str) or not details.strip() or len(details)>2000:raise ValueError("Detalhes inválidos.")
    with sqlite3.connect(path,timeout=30) as c:
        cur=c.execute("INSERT INTO platform_fraud_reviews(user_id,category,details) VALUES(?,?,?)",(user_id,category.strip(),details.strip()));c.commit();return cur.lastrowid

def fraud_reviews(path,status="pending",limit=50):
    if status not in ("pending","approved","rejected","blocked"):raise ValueError("Status inválido.")
    limit=max(1,min(int(limit),100))
    with sqlite3.connect(path,timeout=30) as c:
        c.row_factory=sqlite3.Row
        return [dict(r) for r in c.execute("SELECT * FROM platform_fraud_reviews WHERE status=? ORDER BY id DESC LIMIT ?",(status,limit))]

def review_flag(path,review_id,admin_id,status):
    _valid_id(review_id,"Revisão");_valid_id(admin_id,"Administrador")
    if status not in ("approved","rejected","blocked"):raise ValueError("Decisão inválida.")
    with sqlite3.connect(path,timeout=30) as c:
        c.execute("BEGIN IMMEDIATE")
        cur=c.execute("UPDATE platform_fraud_reviews SET status=?,reviewed_by=?,reviewed_at=CURRENT_TIMESTAMP WHERE id=? AND status='pending'",(status,admin_id,review_id))
        if cur.rowcount!=1:c.rollback();return False
        c.commit();return True

def add_xp(path,user_id,amount):
    _valid_id(user_id,"Usuário")
    if not isinstance(amount,int) or isinstance(amount,bool) or amount<=0 or amount>10**9:raise ValueError("XP inválido.")
    initialize(path)
    with sqlite3.connect(path,timeout=30) as c:
        c.execute("BEGIN IMMEDIATE")
        c.execute("INSERT INTO platform_user_levels(user_id,xp) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET xp=xp+excluded.xp,updated_at=CURRENT_TIMESTAMP",(user_id,amount))
        xp=c.execute("SELECT xp FROM platform_user_levels WHERE user_id=?",(user_id,)).fetchone()[0]
        for threshold,key in ((1000,"xp_1000"),(5000,"xp_5000"),(10000,"xp_10000")):
            if xp>=threshold:c.execute("INSERT OR IGNORE INTO platform_user_badges(user_id,badge_key) VALUES(?,?)",(user_id,key))
        c.commit()

def level_info(path,user_id):
    _valid_id(user_id,"Usuário")
    with sqlite3.connect(path,timeout=30) as c:
        row=c.execute("SELECT xp FROM platform_user_levels WHERE user_id=?",(user_id,)).fetchone()
        xp=row[0] if row else 0
        # Levels are derived, so no payout or wallet mutation is associated.
        level=1+xp//1000
        return {"xp":xp,"level":level,"next_level_xp":level*1000}

def create_badge(path,key,title,description=""):
    if not isinstance(key,str) or not key.strip() or len(key)>80:raise ValueError("Chave inválida.")
    if not isinstance(title,str) or not title.strip() or len(title)>120:raise ValueError("Título inválido.")
    if not isinstance(description,str) or len(description)>1000:raise ValueError("Descrição inválida.")
    with sqlite3.connect(path,timeout=30) as c:
        c.execute("INSERT INTO platform_badges(badge_key,title,description) VALUES(?,?,?) ON CONFLICT(badge_key) DO UPDATE SET title=excluded.title,description=excluded.description",(key.strip(),title.strip(),description));c.commit()

def award_badge(path,user_id,key):
    _valid_id(user_id,"Usuário")
    with sqlite3.connect(path,timeout=30) as c:
        c.execute("BEGIN IMMEDIATE")
        row=c.execute("SELECT active FROM platform_badges WHERE badge_key=?",(key,)).fetchone()
        if not row or not row[0]:c.rollback();raise ValueError("Medalha indisponível.")
        cur=c.execute("INSERT OR IGNORE INTO platform_user_badges(user_id,badge_key) VALUES(?,?)",(user_id,key))
        c.commit();return cur.rowcount==1

def create_announcement(path,title,message,admin_id,start_at=None,end_at=None):
    _valid_id(admin_id,"Administrador")
    if not isinstance(title,str) or not title.strip() or len(title)>120:raise ValueError("Título inválido.")
    if not isinstance(message,str) or not message.strip() or len(message)>4000:raise ValueError("Mensagem inválida.")
    with sqlite3.connect(path,timeout=30) as c:
        cur=c.execute("INSERT INTO platform_announcements(title,message,created_by,start_at,end_at) VALUES(?,?,?,?,?)",(title.strip(),message.strip(),admin_id,start_at,end_at));c.commit();return cur.lastrowid

def active_announcements(path,now=None):
    now=now or _now()
    with sqlite3.connect(path,timeout=30) as c:
        c.row_factory=sqlite3.Row
        return [dict(r) for r in c.execute("SELECT * FROM platform_announcements WHERE active=1 AND (start_at IS NULL OR start_at<=?) AND (end_at IS NULL OR end_at>=?) ORDER BY id DESC",(now,now))]

def admin_log(path,admin_id,action,details=""):
    _valid_id(admin_id,"Administrador")
    if not isinstance(action,str) or not action.strip() or len(action)>120:raise ValueError("Ação inválida.")
    if not isinstance(details,str) or len(details)>2000:raise ValueError("Detalhes inválidos.")
    with sqlite3.connect(path,timeout=30) as c:
        c.execute("INSERT INTO platform_admin_logs(admin_id,action,details) VALUES(?,?,?)",(admin_id,action.strip(),details));c.commit()

def admin_logs(path,limit=50):
    limit=max(1,min(int(limit),100))
    with sqlite3.connect(path,timeout=30) as c:
        c.row_factory=sqlite3.Row;return [dict(r) for r in c.execute("SELECT * FROM platform_admin_logs ORDER BY id DESC LIMIT ?",(limit,))]

def add_notification(path,user_id,title,message,expires_at=None):
    _valid_id(user_id,"Usuário")
    for val,maxlen,label in ((title,120,"Título"),(message,4000,"Mensagem")):
        if not isinstance(val,str) or not val.strip() or len(val)>maxlen:raise ValueError(label+" inválido.")
    with sqlite3.connect(path,timeout=30) as c:
        cur=c.execute("INSERT INTO platform_notifications(user_id,title,message,expires_at) VALUES(?,?,?,?)",(user_id,title.strip(),message.strip(),expires_at));c.commit();return cur.lastrowid

def notifications(path,user_id,include_read=False,now=None,limit=50):
    _valid_id(user_id,"Usuário");now=now or _now();limit=max(1,min(int(limit),100))
    q="SELECT * FROM platform_notifications WHERE user_id=? AND (expires_at IS NULL OR expires_at>=?)"
    a=[user_id,now]
    if not include_read:q+=" AND read_at IS NULL"
    q+=" ORDER BY id DESC LIMIT ?";a.append(limit)
    with sqlite3.connect(path,timeout=30) as c:
        c.row_factory=sqlite3.Row;return [dict(r) for r in c.execute(q,a)]

def mark_notification_read(path,user_id,notification_id):
    _valid_id(user_id,"Usuário");_valid_id(notification_id,"Notificação")
    with sqlite3.connect(path,timeout=30) as c:
        cur=c.execute("UPDATE platform_notifications SET read_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=? AND read_at IS NULL",(notification_id,user_id));c.commit();return cur.rowcount==1

def history(path,user_id,limit=50):
    _valid_id(user_id,"Usuário");limit=max(1,min(int(limit),100))
    # This extension tracks only platform-system activity; financial ledger must be fetched separately.
    with sqlite3.connect(path,timeout=30) as c:
        c.row_factory=sqlite3.Row
        return [dict(r) for r in c.execute("SELECT id,title,message,read_at,created_at FROM platform_notifications WHERE user_id=? ORDER BY id DESC LIMIT ?",(user_id,limit))]
