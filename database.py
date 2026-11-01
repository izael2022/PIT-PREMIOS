import aiosqlite
from config import DATABASE_PATH

async def connect():
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    db=await aiosqlite.connect(DATABASE_PATH)
    db.row_factory=aiosqlite.Row
    await db.execute("PRAGMA foreign_keys=ON")
    await db.execute("PRAGMA journal_mode=WAL")
    return db

async def init_db():
    async with await connect() as db:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS users(
          user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT NOT NULL DEFAULT '',
          points INTEGER NOT NULL DEFAULT 0 CHECK(points>=0), referred_by INTEGER,
          is_vip INTEGER NOT NULL DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          last_daily TEXT, FOREIGN KEY(referred_by) REFERENCES users(user_id));
        CREATE TABLE IF NOT EXISTS point_history(
          id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,amount INTEGER NOT NULL,
          reason TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(user_id) REFERENCES users(user_id));
        CREATE TABLE IF NOT EXISTS redemptions(
          id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,points INTEGER NOT NULL,
          reward TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',
          created_at TEXT DEFAULT CURRENT_TIMESTAMP,reviewed_by INTEGER,
          FOREIGN KEY(user_id) REFERENCES users(user_id));
        CREATE INDEX IF NOT EXISTS idx_history_user ON point_history(user_id);
        CREATE INDEX IF NOT EXISTS idx_redemption_status ON redemptions(status);
        """)
        await db.commit()

async def register_user(uid, username, first_name, referrer=None, referral_reward=0):
    async with await connect() as db:
        cur=await db.execute("SELECT user_id FROM users WHERE user_id=?",(uid,))
        if await cur.fetchone():
            await db.execute("UPDATE users SET username=?,first_name=? WHERE user_id=?",(username,first_name,uid))
            await db.commit()
            return False,None
        if referrer==uid: referrer=None
        if referrer:
            cur=await db.execute("SELECT user_id FROM users WHERE user_id=?",(referrer,))
            if not await cur.fetchone(): referrer=None
        await db.execute("INSERT INTO users(user_id,username,first_name,referred_by) VALUES(?,?,?,?)",(uid,username,first_name,referrer))
        if referrer and referral_reward > 0:
            await db.execute("UPDATE users SET points=points+? WHERE user_id=?",(referral_reward,referrer))
            await db.execute("INSERT INTO point_history(user_id,amount,reason) VALUES(?,?,?)",(referrer,referral_reward,f"Indicação do usuário {uid}"))
        await db.commit()
        return True,referrer

async def get_user(uid):
    async with await connect() as db:
        cur=await db.execute("SELECT * FROM users WHERE user_id=?",(uid,))
        return await cur.fetchone()

async def add_points(uid,amount,reason):
    if amount==0: return
    async with await connect() as db:
        await db.execute("BEGIN IMMEDIATE")
        cur=await db.execute("SELECT points FROM users WHERE user_id=?",(uid,))
        row=await cur.fetchone()
        if not row:
            if amount<0: raise ValueError("Usuário não encontrado.")
            await db.execute("INSERT INTO users(user_id) VALUES(?)",(uid,))
        elif row["points"]+amount<0: raise ValueError("Saldo insuficiente.")
        await db.execute("UPDATE users SET points=points+? WHERE user_id=?",(amount,uid))
        await db.execute("INSERT INTO point_history(user_id,amount,reason) VALUES(?,?,?)",(uid,amount,reason))
        await db.commit()

async def daily_claim(uid,reward):
    from datetime import date
    today=date.today().isoformat()
    async with await connect() as db:
        await db.execute("BEGIN IMMEDIATE")
        cur=await db.execute("SELECT last_daily FROM users WHERE user_id=?",(uid,))
        row=await cur.fetchone()
        if not row or row["last_daily"]==today:
            await db.rollback()
            return False
        await db.execute("UPDATE users SET last_daily=?,points=points+? WHERE user_id=?",(today,reward,uid))
        await db.execute("INSERT INTO point_history(user_id,amount,reason) VALUES(?,?,?)",(uid,reward,"Bônus diário"))
        await db.commit()
        return True

async def ranking(limit=10):
    async with await connect() as db:
        cur=await db.execute("SELECT user_id,first_name,username,points FROM users ORDER BY points DESC LIMIT ?",(limit,))
        return await cur.fetchall()

async def create_redemption(uid,points,reward):
    async with await connect() as db:
        await db.execute("BEGIN IMMEDIATE")
        cur=await db.execute("SELECT points FROM users WHERE user_id=?",(uid,))
        row=await cur.fetchone()
        if not row or row["points"]<points:
            await db.rollback()
            raise ValueError("Saldo insuficiente.")
        await db.execute("UPDATE users SET points=points-? WHERE user_id=?",(points,uid))
        cur=await db.execute("INSERT INTO redemptions(user_id,points,reward) VALUES(?,?,?)",(uid,points,reward))
        rid=cur.lastrowid
        await db.execute("INSERT INTO point_history(user_id,amount,reason) VALUES(?,?,?)",(uid,-points,f"Resgate #{rid}"))
        await db.commit()
        return rid

async def pending_redemptions():
    async with await connect() as db:
        cur=await db.execute("SELECT * FROM redemptions WHERE status='pending' ORDER BY id")
        return await cur.fetchall()

async def review_redemption(rid,admin_id,approve):
    async with await connect() as db:
        await db.execute("BEGIN IMMEDIATE")
        cur=await db.execute("SELECT * FROM redemptions WHERE id=? AND status='pending'",(rid,))
        row=await cur.fetchone()
        if not row:
            await db.rollback()
            return None
        status="approved" if approve else "rejected"
        await db.execute("UPDATE redemptions SET status=?,reviewed_by=? WHERE id=?",(status,admin_id,rid))
        if not approve:
            await db.execute("UPDATE users SET points=points+? WHERE user_id=?",(row["points"],row["user_id"]))
            await db.execute("INSERT INTO point_history(user_id,amount,reason) VALUES(?,?,?)",(row["user_id"],row["points"],f"Estorno resgate #{rid}"))
        await db.commit()
        return dict(row)

async def set_vip(uid,enabled):
    async with await connect() as db:
        await db.execute("UPDATE users SET is_vip=? WHERE user_id=?",(int(enabled),uid))
        await db.commit()

async def stats():
    async with await connect() as db:
        cur=await db.execute("SELECT COUNT(*) users,COALESCE(SUM(points),0) points FROM users")
        totals=dict(await cur.fetchone())
        cur=await db.execute("SELECT COUNT(*) pending FROM redemptions WHERE status='pending'")
        totals.update(dict(await cur.fetchone()))
        return totals
