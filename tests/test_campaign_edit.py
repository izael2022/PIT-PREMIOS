import sqlite3
from datetime import datetime, timedelta, timezone
import systems_extra as extras

def dates():
    now=datetime.now(timezone.utc)
    return now.isoformat(), (now+timedelta(days=2)).isoformat()

def test_update_campaign_preserves_claims_and_progress(tmp_path):
    db=tmp_path/"campaigns.db"
    extras.initialize(str(db))
    start,end=dates()
    cid=extras.create_campaign(str(db),"event","Original","desc",start,end,20,0,123)
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO extra_campaign_claims(campaign_id,user_id,claim_key,points) VALUES(?,?,?,?)",(cid,5,"standard",20))
        c.execute("INSERT INTO extra_campaign_progress(campaign_id,user_id,progress) VALUES(?,?,?)",(cid,5,7))
        c.commit()
    assert extras.update_campaign(str(db),cid,"challenge","Alterada","nova descrição",start,end,50,10)
    with sqlite3.connect(db) as c:
        row=c.execute("SELECT title,reward_points,target_value FROM extra_campaigns WHERE id=?",(cid,)).fetchone()
        claims=c.execute("SELECT COUNT(*) FROM extra_campaign_claims WHERE campaign_id=?",(cid,)).fetchone()[0]
        progress=c.execute("SELECT progress FROM extra_campaign_progress WHERE campaign_id=? AND user_id=?",(cid,5)).fetchone()[0]
    assert row==("Alterada",50,10)
    assert claims==1 and progress==7

def test_update_missing_campaign_returns_false(tmp_path):
    db=tmp_path/"campaigns.db"
    extras.initialize(str(db))
    start,end=dates()
    assert extras.update_campaign(str(db),999,"event","Title","",start,end)==False

def test_update_campaign_rejects_invalid_inputs(tmp_path):
    db=tmp_path/"campaigns.db"
    extras.initialize(str(db))
    start,end=dates()
    for args in [
        ("bad","Title","",start,end,0,0),
        ("event"," ","",start,end,0,0),
        ("event","Title","",end,start,0,0),
        ("event","Title","",start,end,-1,0),
    ]:
        try:
            extras.update_campaign(str(db),1,*args)
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid campaign data should be rejected")
