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
    if not isinstance(created_by,int) or isinstance(created_by,bool) or created_by<0: raise ValueError("Administrador inválido.")
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
    if not isinstance(campaign_id,int) or isinstance(campaign_id,bool) or campaign_id<=0: raise ValueError("Campanha inválida.")
    if not isinstance(active,bool): raise ValueError("Status inválido.")
    with sqlite3.connect(path,timeout=30) as c:
        cur=c.execute("UPDATE extra_campaigns SET active=? WHERE id=?",(int(active),campaign_id));c.commit()
        return cur.rowcount==1

def _award_active_seasons(c, user_id, points):
    """Add reward points to active seasons after timezone-normalized validation."""
    if not isinstance(points, int) or isinstance(points, bool) or points<=0:
        return
    now=datetime.now(timezone.utc)
    seasons=c.execute("SELECT id,start_at,end_at FROM extra_seasons WHERE active=1").fetchall()
    for season_id,start_at,end_at in seasons:
        try:
            start=_parse_utc(start_at)
            end=_parse_utc(end_at)
            if start>=end or not (start<=now<=end):
                continue
        except (ValueError,TypeError):
            # Invalid season dates cannot receive score.
            continue
        c.execute("INSERT INTO extra_season_scores(season_id,user_id,score) VALUES(?,?,?) ON CONFLICT(season_id,user_id) DO UPDATE SET score=score+excluded.score",(season_id,user_id,points))

def claim_campaign(path,campaign_id,user_id,claim_key="standard"):
    """Idempotent claim; credit and claim record are atomic against users/ledger."""
    if not isinstance(campaign_id,int) or isinstance(campaign_id,bool) or campaign_id<=0: raise ValueError("Campanha inválida.")
    if not isinstance(user_id,int) or isinstance(user_id,bool) or user_id<=0: raise ValueError("Usuário inválido.")
    if not isinstance(claim_key,str) or not claim_key.strip() or len(claim_key)>100: raise ValueError("Chave de resgate inválida.")
    with sqlite3.connect(path,timeout=30) as c:
        c.execute("BEGIN IMMEDIATE")
        campaign=c.execute("SELECT * FROM extra_campaigns WHERE id=? AND active=1",(campaign_id,)).fetchone()
        if not campaign: raise ValueError("Campanha inexistente ou inativa.")
        reward=campaign[7]
        if not isinstance(reward,int) or isinstance(reward,bool) or reward<0 or reward>10**12: raise ValueError("Recompensa da campanha inválida.")
        if not _active_window(campaign[4],campaign[5]): raise ValueError("Campanha fora do período.")
        if campaign[1]=="collective_goal":
            total=c.execute("SELECT COALESCE(SUM(progress),0) FROM extra_campaign_progress WHERE campaign_id=?",(campaign_id,)).fetchone()[0]
            if total<campaign[8]: raise ValueError("Meta coletiva ainda não alcançada.")
        elif campaign[1]=="challenge":
            progress=c.execute("SELECT COALESCE(SUM(progress),0) FROM extra_campaign_progress WHERE campaign_id=? AND user_id=?",(campaign_id,user_id)).fetchone()[0]
            if progress<campaign[8]: raise ValueError("Desafio ainda não concluído.")
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
    if not isinstance(campaign_id,int) or isinstance(campaign_id,bool) or campaign_id<=0: raise ValueError("Campanha inválida.")
    if not isinstance(user_id,int) or isinstance(user_id,bool) or user_id<=0: raise ValueError("Usuário inválido.")
    if not isinstance(amount,int) or isinstance(amount,bool) or amount<=0 or amount>10**12: raise ValueError("Contribuição deve ser positiva e válida.")
    with sqlite3.connect(path,timeout=30) as c:
        c.execute("BEGIN IMMEDIATE")
        row=c.execute("SELECT kind,active,start_at,end_at,target_value FROM extra_campaigns WHERE id=?",(campaign_id,)).fetchone()
        if not row or row[0]!="collective_goal" or not row[1]:raise ValueError("Meta coletiva inválida.")
        if not _active_window(row[2],row[3]):raise ValueError("Meta coletiva fora do período.")
        total=c.execute("SELECT COALESCE(SUM(progress),0) FROM extra_campaign_progress WHERE campaign_id=?",(campaign_id,)).fetchone()[0]
        if not isinstance(total,int) or isinstance(total,bool) or total<0 or total>row[4]: raise ValueError("Progresso da meta inconsistente.")
        remaining=int(row[4])-int(total)
        if remaining<=0:raise ValueError("Meta coletiva já atingida.")
        if amount>remaining: raise ValueError("Contribuição excede o restante da meta.")
        c.execute("INSERT INTO extra_campaign_progress(campaign_id,user_id,progress) VALUES(?,?,?) ON CONFLICT(campaign_id,user_id) DO UPDATE SET progress=progress+excluded.progress,updated_at=CURRENT_TIMESTAMP",(campaign_id,user_id,amount))
        c.commit()

def create_achievement(path,key,title,description="",reward_points=0):
    if not isinstance(key,str) or not key.strip() or len(key)>80:raise ValueError("Chave de conquista inválida.")
    if not isinstance(title,str) or not title.strip() or len(title)>120:raise ValueError("Título inválido.")
    if not isinstance(description,str):raise ValueError("Descrição inválida.")
    if not isinstance(reward_points,int) or isinstance(reward_points,bool) or reward_points<0 or reward_points>10**12:raise ValueError("Recompensa inválida.")
    with sqlite3.connect(path,timeout=30) as c:
        c.execute("INSERT INTO extra_achievements(achievement_key,title,description,reward_points) VALUES(?,?,?,?) ON CONFLICT(achievement_key) DO UPDATE SET title=excluded.title,description=excluded.description,reward_points=excluded.reward_points",(key,title[:120],description[:1000],reward_points));c.commit()

def claim_achievement(path,key,user_id):
    if not isinstance(key,str) or not key.strip() or len(key)>80: raise ValueError("Conquista inválida.")
    if not isinstance(user_id,int) or isinstance(user_id,bool) or user_id<=0: raise ValueError("Usuário inválido.")
    with sqlite3.connect(path,timeout=30) as c:
        c.execute("BEGIN IMMEDIATE")
        a=c.execute("SELECT reward_points,active FROM extra_achievements WHERE achievement_key=?",(key,)).fetchone()
        if not a or not a[1]:raise ValueError("Conquista indisponível.")
        try:
            c.execute("INSERT INTO extra_achievement_claims(achievement_key,user_id) VALUES(?,?)",(key,user_id))
        except sqlite3.IntegrityError:
            raise ValueError("Conquista já resgatada.")
        points=a[0]
        if not isinstance(points,int) or isinstance(points,bool) or points<0 or points>10**12: raise ValueError("Recompensa da conquista inválida.")
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
    """Safely add score only for an existing, active, currently valid season."""
    if not isinstance(season_id,int) or isinstance(season_id,bool) or season_id<=0:
        raise ValueError("Temporada inválida.")
    if not isinstance(user_id,int) or isinstance(user_id,bool) or user_id<=0:
        raise ValueError("Usuário inválido.")
    if not isinstance(score,int) or isinstance(score,bool) or score<=0 or score>10**12:
        raise ValueError("Pontuação inválida.")
    with sqlite3.connect(path,timeout=30) as c:
        c.execute("BEGIN IMMEDIATE")
        row=c.execute("SELECT start_at,end_at,active FROM extra_seasons WHERE id=?",(season_id,)).fetchone()
        if not row or not row[2]:
            raise ValueError("Temporada inexistente ou inativa.")
        if not _active_window(row[0],row[1]):
            raise ValueError("Temporada fora do período.")
        current=c.execute("SELECT score FROM extra_season_scores WHERE season_id=? AND user_id=?",(season_id,user_id)).fetchone()
        current_score=current[0] if current else 0
        if isinstance(current_score,bool) or not isinstance(current_score,int) or current_score<0 or current_score>10**12:
            c.rollback()
            raise ValueError("Pontuação atual inválida.")
        if current_score+score>10**12:
            c.rollback()
            raise ValueError("Limite máximo de pontuação da temporada excedido.")
        c.execute("INSERT INTO extra_season_scores(season_id,user_id,score) VALUES(?,?,?) ON CONFLICT(season_id,user_id) DO UPDATE SET score=score+excluded.score",(season_id,user_id,score))
        c.commit()

def season_ranking(path,season_id,limit=50):
    if not isinstance(season_id,int) or isinstance(season_id,bool) or season_id<=0:
        raise ValueError("Temporada inválida.")
    try:
        limit=int(limit)
    except (TypeError,ValueError):
        limit=50
    limit=max(1,min(limit,100))
    with sqlite3.connect(path,timeout=30) as c:
        c.row_factory=sqlite3.Row
        season=c.execute("SELECT id FROM extra_seasons WHERE id=?",(season_id,)).fetchone()
        if not season:
            raise ValueError("Temporada inexistente.")
        # Filter invalid scores and user IDs; tie-break deterministically by user ID.
        return [dict(r) for r in c.execute("SELECT user_id,score FROM extra_season_scores WHERE season_id=? AND user_id>0 AND score>0 ORDER BY score DESC,user_id ASC LIMIT ?",(season_id,limit))]

def update_campaign(path,campaign_id,kind,title,description,start_at,end_at,reward_points=0,target_value=0):
    """Update campaign metadata without touching claims, progress, wallets, or users."""
    allowed={"calendar","event","surprise","challenge","collective_goal","special_mission"}
    if kind not in allowed: raise ValueError("Tipo de campanha inválido.")
    if not isinstance(title,str) or not title.strip() or len(title)>120: raise ValueError("Título inválido.")
    if not isinstance(description,str): raise ValueError("Descrição inválida.")
    if not isinstance(reward_points,int) or isinstance(reward_points,bool) or reward_points<0 or reward_points>10**12 or not isinstance(target_value,int) or isinstance(target_value,bool) or target_value<0 or target_value>10**12:
        raise ValueError("Valores precisam ser inteiros não negativos.")
    start_utc=_parse_utc(start_at); end_utc=_parse_utc(end_at)
    if start_utc>=end_utc: raise ValueError("Período inválido.")
    with sqlite3.connect(path,timeout=30) as c:
        cur=c.execute("UPDATE extra_campaigns SET kind=?,title=?,description=?,start_at=?,end_at=?,reward_points=?,target_value=? WHERE id=?",
            (kind,title.strip(),description[:2000],start_utc.isoformat(),end_utc.isoformat(),reward_points,target_value,campaign_id))
        c.commit()
        return cur.rowcount==1

def record_challenge_progress(path,campaign_id,user_id,amount,event_key):
    """Idempotently record challenge progress from a verified source event."""
    if not isinstance(campaign_id,int) or isinstance(campaign_id,bool) or campaign_id<=0: raise ValueError("Desafio inválido.")
    if not isinstance(user_id,int) or isinstance(user_id,bool) or user_id<=0: raise ValueError("Usuário inválido.")
    if not isinstance(amount,int) or isinstance(amount,bool) or amount<=0 or amount>10**12: raise ValueError("Progresso inválido.")
    if not isinstance(event_key,str) or not event_key.strip() or len(event_key)>160: raise ValueError("Identificador do evento inválido.")
    with sqlite3.connect(path,timeout=30) as c:
        c.execute("BEGIN IMMEDIATE")
        c.execute("CREATE TABLE IF NOT EXISTS extra_challenge_events (campaign_id INTEGER NOT NULL,user_id INTEGER NOT NULL,event_key TEXT NOT NULL,amount INTEGER NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(campaign_id,user_id,event_key))")
        row=c.execute("SELECT kind,active,start_at,end_at,target_value FROM extra_campaigns WHERE id=?",(campaign_id,)).fetchone()
        if not row or row[0]!="challenge" or not row[1]: raise ValueError("Desafio indisponível.")
        if not _active_window(row[2],row[3]): raise ValueError("Desafio fora do período.")
        current=c.execute("SELECT COALESCE(progress,0) FROM extra_campaign_progress WHERE campaign_id=? AND user_id=?",(campaign_id,user_id)).fetchone()[0]
        target=int(row[4])
        if target<=0: raise ValueError("Meta do desafio inválida.")
        if current<0 or current>target: raise ValueError("Progresso do desafio inconsistente.")
        if current>=target: raise ValueError("Meta do desafio já atingida.")
        if amount>target-current: raise ValueError("Evento excede o restante da meta.")
        try:
            c.execute("INSERT INTO extra_challenge_events(campaign_id,user_id,event_key,amount) VALUES(?,?,?,?)",(campaign_id,user_id,event_key,amount))
        except sqlite3.IntegrityError:
            c.rollback(); return False
        c.execute("INSERT INTO extra_campaign_progress(campaign_id,user_id,progress) VALUES(?,?,?) ON CONFLICT(campaign_id,user_id) DO UPDATE SET progress=progress+excluded.progress,updated_at=CURRENT_TIMESTAMP",(campaign_id,user_id,amount))
        c.commit()
        return True

def challenge_progress(path,campaign_id,user_id):
    """Return zero for a user with no progress record; validate identifiers."""
    if not isinstance(campaign_id,int) or isinstance(campaign_id,bool) or campaign_id<=0:
        raise ValueError("Desafio inválido.")
    if not isinstance(user_id,int) or isinstance(user_id,bool) or user_id<=0:
        raise ValueError("Usuário inválido.")
    with sqlite3.connect(path,timeout=30) as c:
        row=c.execute("SELECT progress FROM extra_campaign_progress WHERE campaign_id=? AND user_id=?",(campaign_id,user_id)).fetchone()
        if row is None:
            return 0
        value=row[0]
        if not isinstance(value,int) or isinstance(value,bool) or value<0:
            raise ValueError("Progresso armazenado inválido.")
        return value

