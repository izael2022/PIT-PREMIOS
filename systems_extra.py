"""Safe isolated engine for PIT PRÊMIOS campaign systems (non-destructive)."""
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS extra_campaigns(
 id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
 title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
 start_at TEXT NOT NULL, end_at TEXT NOT NULL,
 active INTEGER NOT NULL DEFAULT 1, reward_points INTEGER NOT NULL DEFAULT 0,
 target_value INTEGER NOT NULL DEFAULT 0, created_by INTEGER NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS extra_campaign_claims(
 campaign_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
 claim_key TEXT NOT NULL, points INTEGER NOT NULL DEFAULT 0,
 claimed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(campaign_id,user_id,claim_key));
CREATE TABLE IF NOT EXISTS extra_campaign_progress(
 campaign_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
 progress INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(campaign_id,user_id));
CREATE TABLE IF NOT EXISTS extra_achievements(
 achievement_key TEXT PRIMARY KEY, title TEXT NOT NULL,
 description TEXT NOT NULL DEFAULT '', reward_points INTEGER NOT NULL DEFAULT 0,
 active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS extra_achievement_claims(
 achievement_key TEXT NOT NULL,user_id INTEGER NOT NULL,
 claimed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(achievement_key,user_id));
CREATE TABLE IF NOT EXISTS extra_seasons(
 id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT NOT NULL,
 start_at TEXT NOT NULL,end_at TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,
 created_by INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS extra_season_scores(
 season_id INTEGER NOT NULL,user_id INTEGER NOT NULL,score INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(season_id,user_id));
"""
def initialize(path):
    with sqlite3.connect(path, timeout=30) as c:
        c.execute("PRAGMA foreign_keys=ON")
        c.executescript(SCHEMA)
        c.commit()

def _now():
    return datetime.now(timezone.utc).isoformat()

def _parse_utc(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Data inválida.")
    try:
        parsed=datetime.fromisoformat(value.strip().replace("Z","+00:00"))
    except ValueError as exc:
        raise ValueError("Data inválida: use ISO-8601.") from exc
    if parsed.tzinfo is None:
        raise ValueError("A data precisa informar fuso horário.")
    return parsed.astimezone(timezone.utc)

def _active_window(start_at,end_at,now=None):
    start=_parse_utc(start_at); end=_parse_utc(end_at)
    if start>=end: raise ValueError("Período inválido.")
    now=now or datetime.now(timezone.utc)
    return start<=now<=end

def create_campaign(path, kind, title, description, start_at, end_at, reward_points=0, target_value=0, created_by=0):
    allowed={"calendar","event","surprise","challenge","collective_goal","special_mission"}
    if kind not in allowed: raise ValueError("Tipo de campanha inválido.")
    if not isinstance(title,str) or not title.strip() or len(title)>120: raise ValueError("Título inválido.")
    if not isinstance(description,str): raise ValueError("Descrição inválida.")
    if not isinstance(reward_points,int) or isinstance(reward_points,bool) or not isinstance(target_value,int) or isinstance(target_value,bool): raise ValueError("Recompensa e meta devem ser números inteiros.")
    if reward_points<0 or target_value<0 or reward_points>10**12 or target_value>10**12: raise ValueError("Valores fora do limite permitido.")
    if not isinstance(created_by,int) or created_by<0: raise ValueError("Administrador inválido.")
    start_utc=_parse_utc(start_at); end_utc=_parse_utc(end_at)
    if start_utc>=end_utc: raise ValueError("Período inválido.")
    start_at=start_utc.isoformat(); end_at=end_utc.isoformat()
    with sqlite3.connect(path,timeout=30) as c:
        cur=c.execute("INSERT INTO extra_campaigns(kind,title,description,start_at,end_at,reward_points,target_value,created_by) VALUES(?,?,?,?,?,?,?,?)",(kind,title.strip(),description[:2000],start_at,end_at,reward_points,target_value,created_by))
        c.commit(); return cur.lastrowid

def list_campaigns(path, kind=None, active_only=True):
    with sqlite3.connect(path,timeout=30) as c:
        c.row_factory=sqlite3.Row
        q="SELECT * FROM extra_campaigns WHERE 1=1"; args=[]
        if kind: q+=" AND kind=?";args.append(kind)
        if active_only:q+=" AND active=1"
        q+=" ORDER BY start_at,id"
        return [dict(x) for x in c.execute(q,args)]

def set_campaign_active(path,campaign_id,active):
    if not isinstance(campaign_id,int) or campaign_id<=0: raise ValueError("Campanha inválida.")
    if not isinstance(active,bool): raise ValueError("Status inválido.")
    with sqlite3.connect(path,timeout=30) as c:
        cur=c.execute("UPDATE extra_campaigns SET active=? WHERE id=?",(int(active),campaign_id));c.commit()
        return cur.rowcount==1

def _award_active_seasons(c, user_id, points):
    """Add reward points to currently active seasons, in the same transaction."""
    if points<=0:
        return
    now=datetime.now(timezone.utc).isoformat()
    seasons=c.execute("SELECT id FROM extra_seasons WHERE active=1 AND start_at<=? AND end_at>=?",(now,now)).fetchall()
    for season in seasons:
        c.execute("INSERT INTO extra_season_scores(season_id,user_id,score) VALUES(?,?,?) ON CONFLICT(season_id,user_id) DO UPDATE SET score=score+excluded.score",(season[0],user_id,int(points)))

def claim_campaign(path,campaign_id,user_id,claim_key="standard"):
    """Idempotent claim; credit and claim record are atomic against users/ledger."""
    if not isinstance(user_id,int) or user_id<=0: raise ValueError("Usuário inválido.")
    if not isinstance(claim_key,str) or not claim_key.strip() or len(claim_key)>100: raise ValueError("Chave de resgate inválida.")
    with sqlite3.connect(path,timeout=30) as c:
        c.execute("BEGIN IMMEDIATE")
        campaign=c.execute("SELECT * FROM extra_campaigns WHERE id=? AND active=1",(campaign_id,)).fetchone()
        if not campaign: raise ValueError("Campanha inexistente ou inativa.")
        if not _active_window(campaign[4],campaign[5]): raise ValueError("Campanha fora do período.")
        if campaign[0] and campaign[1] in ("collective_goal",): 
            total=c.execute("SELECT COALESCE(SUM(progress),0) FROM extra_campaign_progress WHERE campaign_id=?",(campaign_id,)).fetchone()[0]
            if total<campaign[8]: raise ValueError("Meta coletiva ainda não alcançada.")
        try:
            c.execute("INSERT INTO extra_campaign_claims(campaign_id,user_id,claim_key,points) VALUES(?,?,?,?)",(campaign_id,user_id,claim_key,campaign[7]))
        except sqlite3.IntegrityError: raise ValueError("Recompensa já resgatada.")
        points=int(campaign[7])
        if points:
            cur=c.execute("UPDATE users SET points=points+? WHERE user_id=?",(points,user_id))
            if cur.rowcount!=1: raise ValueError("Usuário não encontrado.")
            c.execute("INSERT INTO point_history(user_id,amount,reason) VALUES(?,?,?)",(user_id,points,f"Campanha #{campaign_id}"))
            _award_active_seasons(c,user_id,points)
        c.commit();return points

def contribute_goal(path,campaign_id,user_id,amount):
    if not isinstance(user_id,int) or user_id<=0: raise ValueError("Usuário inválido.")
    if not isinstance(amount,int) or amount<=0: raise ValueError("Contribuição deve ser positiva.")
    with sqlite3.connect(path,timeout=30) as c:
        c.execute("BEGIN IMMEDIATE")
        row=c.execute("SELECT kind,active,start_at,end_at,target_value FROM extra_campaigns WHERE id=?",(campaign_id,)).fetchone()
        if not row or row[0]!="collective_goal" or not row[1]:raise ValueError("Meta coletiva inválida.")
        if not _active_window(row[2],row[3]):raise ValueError("Meta coletiva fora do período.")
        total=c.execute("SELECT COALESCE(SUM(progress),0) FROM extra_campaign_progress WHERE campaign_id=?",(campaign_id,)).fetchone()[0]
        remaining=int(row[4])-int(total)
        if remaining<=0:raise ValueError("Meta coletiva já atingida.")
        if amount>remaining: raise ValueError("Contribuição excede o restante da meta.")
        c.execute("INSERT INTO extra_campaign_progress(campaign_id,user_id,progress) VALUES(?,?,?) ON CONFLICT(campaign_id,user_id) DO UPDATE SET progress=progress+excluded.progress,updated_at=CURRENT_TIMESTAMP",(campaign_id,user_id,amount))
        c.commit()

def create_achievement(path,key,title,description="",reward_points=0):
    if not key or len(key)>80 or reward_points<0:raise ValueError("Conquista inválida.")
    with sqlite3.connect(path,timeout=30) as c:
        c.execute("INSERT INTO extra_achievements(achievement_key,title,description,reward_points) VALUES(?,?,?,?) ON CONFLICT(achievement_key) DO UPDATE SET title=excluded.title,description=excluded.description,reward_points=excluded.reward_points",(key,title[:120],description[:1000],reward_points));c.commit()

def claim_achievement(path,key,user_id):
    if not isinstance(key,str) or not key.strip() or len(key)>80: raise ValueError("Conquista inválida.")
    if not isinstance(user_id,int) or user_id<=0: raise ValueError("Usuário inválido.")
    with sqlite3.connect(path,timeout=30) as c:
        c.execute("BEGIN IMMEDIATE")
        a=c.execute("SELECT reward_points,active FROM extra_achievements WHERE achievement_key=?",(key,)).fetchone()
        if not a or not a[1]:raise ValueError("Conquista indisponível.")
        c.execute("INSERT INTO extra_achievement_claims(achievement_key,user_id) VALUES(?,?)",(key,user_id))
        points=int(a[0])
        if points:
            cur=c.execute("UPDATE users SET points=points+? WHERE user_id=?",(points,user_id))
            if cur.rowcount!=1:raise ValueError("Usuário não encontrado.")
            c.execute("INSERT INTO point_history(user_id,amount,reason) VALUES(?,?,?)",(user_id,points,f"Conquista {key}"))
            _award_active_seasons(c,user_id,points)
        c.commit();return points

def create_season(path,title,start_at,end_at,created_by=0):
    if not title.strip():raise ValueError("Temporada inválida.")
    start_utc=_parse_utc(start_at); end_utc=_parse_utc(end_at)
    if start_utc>=end_utc:raise ValueError("Temporada inválida.")
    start_at=start_utc.isoformat(); end_at=end_utc.isoformat()
    with sqlite3.connect(path,timeout=30) as c:
        cur=c.execute("INSERT INTO extra_seasons(title,start_at,end_at,created_by) VALUES(?,?,?,?)",(title[:120],start_at,end_at,created_by));c.commit();return cur.lastrowid

def add_season_score(path,season_id,user_id,score):
    if score<=0:raise ValueError("Pontuação inválida.")
    with sqlite3.connect(path,timeout=30) as c:
        c.execute("INSERT INTO extra_season_scores(season_id,user_id,score) VALUES(?,?,?) ON CONFLICT(season_id,user_id) DO UPDATE SET score=score+excluded.score",(season_id,user_id,score));c.commit()

def season_ranking(path,season_id,limit=50):
    limit=max(1,min(int(limit),100))
    with sqlite3.connect(path,timeout=30) as c:
        c.row_factory=sqlite3.Row
        return [dict(r) for r in c.execute("SELECT user_id,score FROM extra_season_scores WHERE season_id=? ORDER BY score DESC,user_id ASC LIMIT ?",(season_id,limit))]

def update_campaign(path,campaign_id,kind,title,description,start_at,end_at,reward_points=0,target_value=0):
    """Update campaign metadata without touching claims, progress, wallets, or users."""
    allowed={"calendar","event","surprise","challenge","collective_goal","special_mission"}
    if kind not in allowed: raise ValueError("Tipo de campanha inválido.")
    if not isinstance(title,str) or not title.strip() or len(title)>120: raise ValueError("Título inválido.")
    if not isinstance(description,str): raise ValueError("Descrição inválida.")
    if not isinstance(reward_points,int) or reward_points<0 or not isinstance(target_value,int) or target_value<0:
        raise ValueError("Valores precisam ser inteiros não negativos.")
    start_utc=_parse_utc(start_at); end_utc=_parse_utc(end_at)
    if start_utc>=end_utc: raise ValueError("Período inválido.")
    with sqlite3.connect(path,timeout=30) as c:
        cur=c.execute("UPDATE extra_campaigns SET kind=?,title=?,description=?,start_at=?,end_at=?,reward_points=?,target_value=? WHERE id=?",
            (kind,title.strip(),description[:2000],start_utc.isoformat(),end_utc.isoformat(),reward_points,target_value,campaign_id))
        c.commit()
        return cur.rowcount==1
