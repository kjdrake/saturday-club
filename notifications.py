"""Durable, commissioner-triggered slate emails; recipients never share an email."""
import hashlib
import json
import re
import secrets
import time
import invitations

SCHEMA = '''
CREATE TABLE IF NOT EXISTS notification_preferences(user_id TEXT PRIMARY KEY,slate_emails INTEGER NOT NULL CHECK(slate_emails IN (0,1)));
CREATE TABLE IF NOT EXISTS text_preferences(user_id TEXT PRIMARY KEY,enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),phone TEXT NOT NULL,updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS slate_publications(season INTEGER NOT NULL,week INTEGER NOT NULL,revision TEXT NOT NULL,published REAL NOT NULL,PRIMARY KEY(season,week));
CREATE TABLE IF NOT EXISTS slate_notices(id TEXT PRIMARY KEY,season INTEGER NOT NULL,week INTEGER NOT NULL,revision TEXT NOT NULL,created REAL NOT NULL,created_by TEXT NOT NULL,game_count INTEGER NOT NULL,UNIQUE(season,week,revision));
CREATE TABLE IF NOT EXISTS slate_deliveries(notice_id TEXT NOT NULL,user_id TEXT NOT NULL,status TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,updated REAL NOT NULL,PRIMARY KEY(notice_id,user_id));
CREATE INDEX IF NOT EXISTS slate_delivery_status ON slate_deliveries(status,updated);
'''

def opted_in(c, uid):
    row=c.execute('SELECT slate_emails FROM notification_preferences WHERE user_id=?',(uid,)).fetchone()
    return row is None or bool(row['slate_emails'])

def text_preference(c,uid):
    row=c.execute('SELECT enabled,phone FROM text_preferences WHERE user_id=?',(uid,)).fetchone()
    return {'slateTexts':bool(row['enabled']),'phone':row['phone']} if row else {'slateTexts':False,'phone':''}

def valid_phone(value):
    if not isinstance(value,str) or len(value)>40:raise ValueError('Enter a phone number with country code, such as +1 555 123 4567.')
    phone=re.sub(r'[ ()-]','',value.strip())
    if phone and not re.fullmatch(r'\+[1-9][0-9]{7,14}',phone):raise ValueError('Enter a phone number with country code, such as +1 555 123 4567.')
    return phone

def text_recipients(c):
    return [dict(row) for row in c.execute('SELECT u.id,u.name,p.phone FROM users u JOIN text_preferences p ON p.user_id=u.id WHERE u.active=1 AND p.enabled=1') if row['phone']]

def revision(games):
    snapshot=sorted([(g['id'],g.get('spread'),g.get('kickoff')) for g in games if g.get('included')],key=lambda g:g[0])
    return hashlib.sha256(json.dumps(snapshot,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()

def upcoming(games, kickoff):
    return [g for g in games if g.get('included') and g.get('status')=='scheduled' and kickoff(g)>time.time()]

def recipients(c):
    return [dict(row) for row in c.execute('SELECT u.id,u.email FROM users u LEFT JOIN notification_preferences p ON p.user_id=u.id WHERE u.active=1 AND coalesce(p.slate_emails,1)=1') if invitations.valid_email(row['email'])]

def summary(c,season,week,current_revision):
    notice=c.execute('SELECT * FROM slate_notices WHERE season=? AND week=? AND revision=?',(season,week,current_revision)).fetchone()
    if not notice:return None
    counts={key:0 for key in ('pending','sending','sent','failed','skipped')}
    for row in c.execute('SELECT status,count(*) AS n FROM slate_deliveries WHERE notice_id=? GROUP BY status',(notice['id'],)):counts[row['status']]=row['n']
    retryable=c.execute("SELECT count(*) FROM slate_deliveries WHERE notice_id=? AND status='failed' AND attempts<3",(notice['id'],)).fetchone()[0]
    return {'id':notice['id'],'createdAt':notice['created'],'total':sum(counts.values()),'retryable':retryable,**counts}

def publication(c,season,week):
    row=c.execute('SELECT revision,published FROM slate_publications WHERE season=? AND week=?',(season,week)).fetchone()
    return dict(row) if row else None

def admin_state(c,games,season,week,kickoff):
    current=revision(games)
    return {'emailReady':invitations.ready(),'textRecipientCount':len(text_recipients(c)),'recipientCount':len(recipients(c)),'currentRevision':current,'upcomingCount':len(upcoming(games,kickoff)),'campaign':summary(c,season,week,current)}

def queue(c,games,season,week,actor,kickoff):
    if not invitations.ready():raise ValueError('Email is not configured. The slate can still be published without email.')
    available=upcoming(games,kickoff)
    if not available:raise ValueError('There are no upcoming published games to notify members about.')
    current=revision(games)
    if summary(c,season,week,current):return summary(c,season,week,current)
    targets=recipients(c)
    if not targets:raise ValueError('No active members have slate emails enabled.')
    uid=secrets.token_hex(12);now=time.time()
    c.execute('INSERT INTO slate_notices VALUES(?,?,?,?,?,?,?)',(uid,season,week,current,now,actor,len([g for g in games if g.get('included')])))
    c.executemany('INSERT INTO slate_deliveries VALUES(?,?,?,?,?)',[(uid,target['id'],'pending',0,now) for target in targets])
    return summary(c,season,week,current)

def publish(c,games,season,week):
    current=revision(games);previous=publication(c,season,week)
    if not previous or previous['revision']!=current:
        c.execute('INSERT OR REPLACE INTO slate_publications VALUES(?,?,?,?)',(season,week,current,time.time()))

def retry(c,season,week,current):
    notice=summary(c,season,week,current)
    if not notice:raise ValueError('No notification exists for this published slate yet.')
    c.execute("UPDATE slate_deliveries SET status='pending',updated=? WHERE notice_id=? AND status='failed' AND attempts<3",(time.time(),notice['id']))
    return summary(c,season,week,current)

def email_text(notice,name):
    link=invitations.public_url()+'/?season='+str(notice['season'])+'&week='+str(notice['week'])+'#picks'
    return (f"Hi {name},\n\nWeek {notice['week']} of the {notice['season']} Saturday Club season is ready! "
            f"Your commissioner published {notice['game_count']} games.\n\nOpen your week's picks:\n{link}\n\n"
            "HOW TO MAKE AND SAVE YOUR PICKS\n"
            "1. Sign in with your existing league account. Returning members do not need another invitation.\n"
            "2. Choose either team against the displayed spread for any upcoming games you want to play.\n"
            "3. Tap Save picks. Selecting a team alone does NOT save your picks.\n"
            "4. Look for All picks saved, then return anytime to check your saved selections.\n\n"
            "You may skip games; skipped games earn 0 points. Each game locks at its own kickoff. "
            "Game times are shown in your local time on the site. You can change and save a pick again before that game locks.\n\n"
            "To turn off slate emails, open your account menu on the site and change Notification preferences.\n\n"
            "Saturday Club by 4th & Soul — just for fun. No money on the line.")

def process_one(database):
    # Claim before sending. A crashed/uncertain send is marked failed, never automatically resent.
    with database() as c:
        c.execute('BEGIN IMMEDIATE');now=time.time()
        c.execute("UPDATE slate_deliveries SET status='failed',updated=? WHERE status='sending' AND updated<?",(now,now-300))
        row=c.execute("SELECT d.notice_id,d.user_id,n.season,n.week,n.game_count FROM slate_deliveries d JOIN slate_notices n ON n.id=d.notice_id WHERE d.status='pending' ORDER BY n.created,d.user_id LIMIT 1").fetchone()
        if not row:return False
        item=dict(row)
        member=c.execute('SELECT name,email,active FROM users WHERE id=?',(item['user_id'],)).fetchone()
        # Skip disabled/deleted/opted-out members and obsolete revisions or completed slates.
        from server import game_rows,kickoff
        games=game_rows(c,item['season'],item['week'])
        old=c.execute('SELECT revision FROM slate_notices WHERE id=?',(item['notice_id'],)).fetchone()['revision']
        eligible=member and member['active'] and opted_in(c,item['user_id']) and invitations.valid_email(member['email']) and revision(games)==old and upcoming(games,kickoff)
        if not eligible:
            c.execute("UPDATE slate_deliveries SET status='skipped',updated=? WHERE notice_id=? AND user_id=?",(now,item['notice_id'],item['user_id']));return True
        # Configuration may be temporarily absent during setup; retain pending work.
        if not invitations.ready():return False
        member=dict(member)
        c.execute("UPDATE slate_deliveries SET status='sending',attempts=attempts+1,updated=? WHERE notice_id=? AND user_id=?",(now,item['notice_id'],item['user_id']))
    try:
        invitations.send_message(member['email'],f"Saturday Club: Week {item['week']} picks are ready",email_text(item,member['name']))
        status='sent'
    except Exception:
        status='failed'  # Do not log recipient, provider response or credentials.
    with database() as c:
        c.execute('UPDATE slate_deliveries SET status=?,updated=? WHERE notice_id=? AND user_id=?',(status,time.time(),item['notice_id'],item['user_id']))
    return True
