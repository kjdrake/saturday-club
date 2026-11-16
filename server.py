"""Saturday Club: portable WSGI application, SQLite persistence, public feed adapters."""
import os, json, sqlite3, hashlib, secrets, hmac, time, datetime, urllib.request, urllib.parse, threading, math
from pathlib import Path
from http.cookies import SimpleCookie
BASE=Path(__file__).parent
SCORE_REFRESH_SECONDS=15
DB=os.getenv('DATABASE_PATH',str(BASE/'data'/'club.db'))
CONFERENCES={'1': 'ACC', '4': 'Big 12', '5': 'Big Ten', '8': 'SEC', '9': 'Pac-12', '12': 'Conference USA', '15': 'MAC', '17': 'Mountain West', '18': 'FBS Independents', '37': 'Sun Belt', '151': 'American'}
SECURE=os.getenv('COOKIE_SECURE','true').lower()=='true'
SCHEMA='''
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,name TEXT NOT NULL,email TEXT UNIQUE NOT NULL,password TEXT NOT NULL,role TEXT NOT NULL,active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id TEXT NOT NULL,expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS invites(code TEXT PRIMARY KEY,name TEXT NOT NULL,expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS games(id TEXT NOT NULL,season INTEGER NOT NULL,week INTEGER NOT NULL,data TEXT NOT NULL,PRIMARY KEY(id,season,week));
CREATE TABLE IF NOT EXISTS picks(user_id TEXT NOT NULL,game_id TEXT NOT NULL,season INTEGER NOT NULL,week INTEGER NOT NULL,side TEXT NOT NULL,PRIMARY KEY(user_id,game_id,season,week));
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT);
'''
def db():
    Path(DB).parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(DB,timeout=20);c.row_factory=sqlite3.Row;c.execute('PRAGMA journal_mode=WAL');return c
def pw_hash(password,salt=None):
    salt=salt or secrets.token_hex(16)
    return salt+':'+hashlib.scrypt(password.encode(),salt=salt.encode(),n=16384,r=8,p=1).hex()
def verify(password,hashed):return hmac.compare_digest(pw_hash(password,hashed.split(':')[0]),hashed)
def initialize():
    with db() as c:
        c.executescript(SCHEMA)
        email=os.getenv('ADMIN_EMAIL');password=os.getenv('ADMIN_PASSWORD')
        if not c.execute('SELECT 1 FROM users LIMIT 1').fetchone() and email and password:
            if len(password)<12:raise ValueError('ADMIN_PASSWORD must be at least 12 characters')
            c.execute('INSERT INTO users VALUES(?,?,?,?,?,1)',(secrets.token_hex(12),os.getenv('ADMIN_NAME','Commissioner'),email.lower(),pw_hash(password),'admin'))
def now_iso():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def kickoff(g):
    try:return datetime.datetime.fromisoformat(g['kickoff'].replace('Z','+00:00')).timestamp()
    except (KeyError,ValueError,TypeError):return 0
def locked(g):return g.get('status')!='scheduled' or kickoff(g)<=time.time()
def game_rows(c,season,week=None):
    if week is None:rows=c.execute('SELECT data FROM games WHERE season=?',(season,))
    else:rows=c.execute('SELECT data FROM games WHERE season=? AND week=?',(season,week))
    return [json.loads(r['data']) for r in rows]
def put_game(c,g,season,week):c.execute('INSERT OR REPLACE INTO games VALUES(?,?,?,?)',(g['id'],season,week,json.dumps(g)))
def points(g,side,include_live=False):
    statuses=('final','live') if include_live else ('final',)
    if g.get('status') not in statuses or g.get('spread') is None or not g.get('included'):return None
    if g.get('homeScore') is None or g.get('awayScore') is None:return None
    margin=g['homeScore']+g['spread']-g['awayScore']
    return .5 if margin==0 else int((side=='home' and margin>0)or(side=='away' and margin<0))
def ranked(rows,key):
    ordered=sorted(rows,key=lambda row:(-row[key],row['name'].casefold(),row['id']))
    previous=None;rank=0
    for index,row in enumerate(ordered,1):
        if row[key]!=previous:rank=index
        row['rank']=rank;previous=row[key]
    return ordered
def standings(c,season,include_live=False):
    # One snapshot of every saved game/pick in this season, across all weeks.
    gs={(row['id'],row['week']):json.loads(row['data']) for row in c.execute('SELECT id,week,data FROM games WHERE season=?',(season,))}
    rows={u['id']:{**dict(u),'wins':0,'losses':0,'pushes':0,'points':0} for u in c.execute('SELECT id,name FROM users')}
    live={uid:{'livePoints':0,'liveWins':0,'liveLosses':0,'livePushes':0,'livePicks':0} for uid in rows}
    for pick in c.execute('SELECT user_id,game_id,week,side FROM picks WHERE season=?',(season,)):
        row=rows.get(pick['user_id']);game=gs.get((pick['game_id'],pick['week']),{})
        if row is None:continue
        score=points(game,pick['side'])
        if score is not None:
            row['points']+=score;row['wins' if score==1 else 'pushes' if score==.5 else 'losses']+=1
        elif game.get('status')=='live':
            projected=points(game,pick['side'],include_live=True)
            if projected is not None:
                item=live[pick['user_id']];item['livePoints']+=projected;item['livePicks']+=1
                item['liveWins' if projected==1 else 'livePushes' if projected==.5 else 'liveLosses']+=1
    official=ranked(list(rows.values()),'points')
    if not include_live:return official
    projections=[{**row,**live[row['id']],'officialRank':row['rank'],'projectedPoints':row['points']+live[row['id']]['livePoints']} for row in official]
    projections=ranked(projections,'projectedPoints')
    for row in projections:row['movement']=row['officialRank']-row['rank']
    live_games=[(key,g) for key,g in gs.items() if g.get('included') and g.get('status')=='live']
    stamps=[];missing=False
    week_stamps={week:c.execute('SELECT value FROM meta WHERE key=?',(f'last-{season}-{week}',)).fetchone() for week in {key[1] for key,g in live_games}}
    for key,game in live_games:
        value=game.get('feedCheckedAt') or (week_stamps[key[1]]['value'] if week_stamps[key[1]] else None)
        if value:
            try:stamps.append(datetime.datetime.fromisoformat(value.replace('Z','+00:00')))
            except (ValueError,TypeError):missing=True
        else:missing=True
    oldest=min(stamps) if stamps else None
    incomplete=sum(points(game,'home',include_live=True) is None for key,game in live_games)
    stale=bool(live_games) and (incomplete>0 or missing or oldest is None or time.time()-oldest.timestamp()>60)
    return official,{'rows':projections,'activeGames':len(live_games),'incompleteGames':incomplete,'updatedAt':oldest.isoformat() if oldest else None,'stale':stale,'scoreRefreshSeconds':SCORE_REFRESH_SECONDS}
def fetch_json(url):
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'SaturdayClub/1.0'}),timeout=15) as r:return json.load(r)
def betting_odds():
    # Scores can refresh quickly without spending a betting-feed credit each time.
    with db() as c:
        record=c.execute("SELECT value FROM meta WHERE key='betting-odds-cache'").fetchone()
    cached=json.loads(record['value']) if record else None
    if cached and time.time()-cached['fetchedAt']<600:return cached['events']
    try:
        events=fetch_json('https://api.the-odds-api.com/v4/sports/americanfootball_ncaaf/odds/?'+urllib.parse.urlencode({'apiKey':os.environ['ODDS_API_KEY'],'regions':'us','markets':'spreads','oddsFormat':'american'}))
        if not isinstance(events,list):raise ValueError('Unexpected betting feed response')
        with db() as c:c.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',('betting-odds-cache',json.dumps({'fetchedAt':time.time(),'events':events})))
        return events
    except Exception:
        if cached:return cached['events']
        raise
def feed_game_details(event,competition,teams,checked_at):
    status=event.get('status') or competition.get('status') or {}
    status_type=status.get('type') or {}
    situation=competition.get('situation') or {}
    play=situation.get('lastPlay') or {}
    venue=competition.get('venue') or {};address=venue.get('address') or {}
    possession=situation.get('possession')
    if isinstance(possession,dict):possession=possession.get('id') or (possession.get('team') or {}).get('id')
    def text(value):return value.strip() if isinstance(value,str) and value.strip() else None
    quarter=status.get('period')
    field=text(situation.get('possessionText')) or text(situation.get('fieldPosition'))
    if not field and situation.get('ballOn') is not None:field=str(situation['ballOn'])
    networks=[name for broadcast in competition.get('broadcasts',[]) for name in broadcast.get('names',[]) if isinstance(name,str)]
    if not networks and text(competition.get('broadcast')):networks=[competition['broadcast']]
    if not networks:networks=[broadcast['media']['shortName'] for broadcast in competition.get('geoBroadcasts',[]) if isinstance(broadcast.get('media'),dict) and text(broadcast['media'].get('shortName'))]
    result={'network':', '.join(dict.fromkeys(networks)),'clock':text(status.get('displayClock')),'quarter':quarter if isinstance(quarter,int) and not isinstance(quarter,bool) and quarter>0 else None,
            'statusName':text(status_type.get('name')),'statusDetail':text(status_type.get('shortDetail')) or text(status_type.get('detail')),
            'possessionId':str(possession) if possession is not None else None,
            'downDistance':text(situation.get('shortDownDistanceText')) or text(situation.get('downDistanceText')),
            'fieldPosition':field,'redZone':situation.get('isRedZone') is True or situation.get('redZone') is True,
            'lastPlay':text(play.get('text')) or text(play.get('shortText')),'lastPlayId':str(play['id']) if play.get('id') is not None else None,
            'lastPlayScoring':play.get('scoringPlay') is True,'venue':text(venue.get('fullName')) or text(venue.get('name')),
            'venueLocation':', '.join(filter(None,[text(address.get('city')),text(address.get('state'))])) or None,'feedCheckedAt':checked_at}
    for side in ('home','away'):
        timeouts=situation.get(side+'Timeouts',teams.get(side,{}).get('timeouts'))
        result[side+'Timeouts']=timeouts if isinstance(timeouts,int) and not isinstance(timeouts,bool) and 0<=timeouts<=3 else None
    return result
def feed_score(value):
    if isinstance(value,dict):value=value.get('value',value.get('displayValue'))
    try:
        if isinstance(value,bool) or (isinstance(value,float) and not value.is_integer()):return None
        score=int(value)
        return score if score>=0 else None
    except (TypeError,ValueError,OverflowError):return None
_sync_lock=threading.Lock()
def sync_feed(season,week):
    if not _sync_lock.acquire(blocking=False):return 'A feed sync is already in progress.'
    try:
        with db() as c:
            last=c.execute('SELECT value FROM meta WHERE key=?',(f'sync-{season}-{week}',)).fetchone()
            if last and time.time()-float(last['value'])<12:return 'Feed was refreshed less than 12 seconds ago.'
        feed=fetch_json(f'https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?groups=80&limit=100&dates={season}&seasontype=2&week={week}')
        feed_checked_at=now_iso()
        parsed=[]
        for e in feed.get('events',[]):
            comp=e['competitions'][0];teams={t['homeAway']:t for t in comp['competitors']}
            if 'home' not in teams or 'away' not in teams:continue
            state=e['status']['type'];status='final' if state.get('completed') else 'live' if state.get('state')=='in' else 'scheduled'
            if any(x in state.get('name','') for x in ['CANCELED','POSTPONED']):status='void'
            odds=comp.get('odds',[]);odd=odds[0] if odds else {};line=odd.get('spread');detail=odd.get('details','')
            if line is not None:
                line=abs(float(line));line=-line if detail.startswith(teams['home']['team'].get('abbreviation','!')) else line
            g={'id':e['id'],'kickoff':e['date'],'status':status,'period':e['status'].get('type',{}).get('shortDetail',''),'included':False,'spread':line,'bookmaker':odd.get('provider',{}).get('name','ESPN public odds'),'network':', '.join(n for b in comp.get('broadcasts',[]) for n in b.get('names',[]))}
            g.update(feed_game_details(e,comp,teams,feed_checked_at))
            for side,t in teams.items():
                g[side+'ConferenceId']=str(t['team'].get('conferenceId',''));g[side+'Conference']=CONFERENCES.get(g[side+'ConferenceId'],'Other / unknown');g[side]=t['team']['displayName'];g[side+'Abbr']=t['team']['abbreviation'];g[side+'Id']=t['team']['id'];g[side+'Score']=feed_score(t.get('score'));g[side+'Rank']=t.get('curatedRank',{}).get('current');g[side+'Record']=next((r.get('summary','') for r in t.get('records',[]) if r.get('type')=='total'),'')
                if g[side+'Rank'] and g[side+'Rank']>25:g[side+'Rank']=None
            parsed.append(g)
        warning=''
        if os.getenv('ODDS_API_KEY'):
            try:
                odds=betting_odds()
                for g in parsed:
                    for e in odds:
                        if e['home_team'].casefold()==g['home'].casefold() and e['away_team'].casefold()==g['away'].casefold():
                            for b in e.get('bookmakers',[]):
                                outcome=next((o for m in b.get('markets',[]) if m['key']=='spreads' for o in m['outcomes'] if o['name']==e['home_team']),None)
                                if outcome:g['spread']=outcome['point'];g['bookmaker']=b['title'];break
            except Exception:warning=' Additional odds provider unavailable; ESPN odds retained.'
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            old={g['id']:g for g in game_rows(c,season,week)}
            for g in parsed:
                if g['id'] in old:
                    previous=old[g['id']];g['included']=previous.get('included',False)
                    if g['included'] or locked(previous):g['spread']=previous.get('spread');g['bookmaker']=previous.get('bookmaker','Commissioner')
                put_game(c,g,season,week)
            stamp=feed_checked_at;c.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',(f'sync-{season}-{week}',str(time.time())));c.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',(f'last-{season}-{week}',stamp))
        return f'Updated {len(parsed)} games.'+warning
    finally:_sync_lock.release()
class Problem(Exception):
    def __init__(self,message,status=400):self.message=message;self.status=status
_attempts={};_attempt_lock=threading.Lock()
def limit(ip):
    with _attempt_lock:
        # Bounded in-memory limiter; use WAF at the load balancer for production.
        if len(_attempts)>10000:_attempts.clear()
        ts=[t for t in _attempts.get(ip,[]) if t>time.time()-900]
        if len(ts)>=20:raise Problem('Too many attempts. Try again in 15 minutes.',429)
        ts.append(time.time());_attempts[ip]=ts

def application(environ,start_response):
    headers=[('X-Content-Type-Options','nosniff'),('Referrer-Policy','same-origin'),('X-Frame-Options','DENY')]
    try:
        path=environ.get('PATH_INFO','/');method=environ['REQUEST_METHOD']
        if not path.startswith('/api/'):
            if method not in ('GET','HEAD'):raise Problem('Method not allowed',405)
            p=BASE/'dist'/('index.html' if path=='/' else path.lstrip('/'))
            if not p.resolve().is_relative_to((BASE/'dist').resolve()) or not p.is_file():raise Problem('Not found',404)
            mime={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.png':'image/png'}.get(p.suffix,'application/octet-stream')
            content=p.read_bytes()
            if p.name=='index.html':content=content.replace(b'<html lang="en">',b'<html lang="en" data-server-backed="true">',1)
            start_response('200 OK',headers+[('Content-Type',mime)]);return [content if method=='GET' else b'']
        headers.append(('Cache-Control','no-store'))
        if method=='POST':
            # Same-origin checks plus JSON-only requests prevent cross-site form CSRF.
            origin=environ.get('HTTP_ORIGIN')
            if origin and urllib.parse.urlparse(origin).netloc!=environ.get('HTTP_HOST'):raise Problem('Origin rejected',403)
            if 'application/json' not in environ.get('CONTENT_TYPE',''):raise Problem('JSON required',415)
            size=int(environ.get('CONTENT_LENGTH') or 0)
            if size>1000000:raise Problem('Request too large',413)
            try:data=json.loads(environ['wsgi.input'].read(size))
            except Exception:raise Problem('Invalid JSON')
        elif method=='GET':data={k:v[0] for k,v in urllib.parse.parse_qs(environ.get('QUERY_STRING','')).items()}
        else:raise Problem('Method not allowed',405)
        route=path[5:];result={}
        with db() as c:
            cookie=SimpleCookie();cookie.load(environ.get('HTTP_COOKIE',''));token=cookie['sc_session'].value if 'sc_session' in cookie else ''
            u=c.execute('SELECT u.* FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token=? AND s.expires>? AND u.active=1',(hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
            user=dict(u) if u else None
            if route in ('login','register') and method=='POST':
                limit(environ.get('REMOTE_ADDR','unknown'));email=str(data.get('email','')).lower().strip();password=str(data.get('password',''))
                if len(password)<10 or len(password)>256 or '@' not in email or len(email)>254:raise Problem('Enter a valid email and a password of at least 10 characters.')
                if route=='register':
                    code=hashlib.sha256(str(data.get('code','')).encode()).hexdigest();invite=c.execute('SELECT * FROM invites WHERE code=? AND expires>?',(code,time.time())).fetchone()
                    if not invite:raise Problem('Invalid or expired invite code',403)
                    uid=secrets.token_hex(12)
                    try:c.execute('INSERT INTO users VALUES(?,?,?,?,?,1)',(uid,invite['name'],email,pw_hash(password),'member'))
                    except sqlite3.IntegrityError:raise Problem('This email is already registered.')
                    c.execute('DELETE FROM invites WHERE code=?',(code,));user=dict(c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone())
                else:
                    row=c.execute('SELECT * FROM users WHERE email=? AND active=1',(email,)).fetchone()
                    if not row or not verify(password,row['password']):raise Problem('Incorrect email or password',401)
                    user=dict(row)
                token=secrets.token_urlsafe(32);c.execute('DELETE FROM sessions WHERE expires<?',(time.time(),));c.execute('INSERT INTO sessions VALUES(?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),user['id'],time.time()+604800))
                headers.append(('Set-Cookie',f'sc_session={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=604800'+('; Secure' if SECURE else '')));result={'ok':True}
            elif route=='logout' and method=='POST':
                c.execute('DELETE FROM sessions WHERE token=?',(hashlib.sha256(token.encode()).hexdigest(),));headers.append(('Set-Cookie','sc_session=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0'));result={'ok':True}
            else:
                if route!='health' and not user:raise Problem('Sign in required',401)
                if route=='health':result={'ok':True}
                elif route=='state' and method=='GET':
                    season,week=period(data);c.execute('BEGIN');state_games=game_rows(c,season,week)
                    if user['role']=='admin':
                        picked={row[0] for row in c.execute('SELECT DISTINCT game_id FROM picks WHERE season=? AND week=?',(season,week))}
                        state_games=[{**g,'hasPicks':g['id'] in picked} for g in state_games]
                    else:state_games=[g for g in state_games if g.get('included')]
                    last=c.execute('SELECT value FROM meta WHERE key=?',(f'last-{season}-{week}',)).fetchone()
                    official,live_board=standings(c,season,include_live=True)
                    result={'liveStandings':live_board,'seasons':[r[0] for r in c.execute('SELECT DISTINCT season FROM games ORDER BY season DESC')],'user':{k:user[k] for k in ('id','name','role')},'games':state_games,'picks':{p['game_id']:p['side'] for p in c.execute('SELECT * FROM picks WHERE user_id=? AND season=? AND week=?',(user['id'],season,week))},'standings':official,'members':[dict(m) for m in c.execute('SELECT id,name,role,active FROM users')] if user['role']=='admin' else [],'lastSync':last['value'] if last else None}
                elif route=='picks' and method=='POST':
                    season,week=period(data);submitted=data.get('picks',{})
                    if not isinstance(submitted,dict):raise Problem('Invalid picks')
                    c.execute('BEGIN IMMEDIATE')
                    available=game_rows(c,season,week)
                    if set(submitted)-{g['id'] for g in available if g.get('included')}:raise Problem('The weekly slate has changed. Refresh before saving your picks.',409)
                    for g in available:
                        if not g.get('included') or g.get('spread') is None:continue
                        side=submitted.get(g['id'])
                        previous=c.execute('SELECT side FROM picks WHERE user_id=? AND game_id=? AND season=? AND week=?',(user['id'],g['id'],season,week)).fetchone()
                        if locked(g):
                            if side!=(previous['side'] if previous else None):raise Problem('A game has locked. Refresh your pick sheet.',409)
                            continue
                        if side in ('home','away'):c.execute('INSERT OR REPLACE INTO picks VALUES(?,?,?,?,?)',(user['id'],g['id'],season,week,side))
                        elif side is None:c.execute('DELETE FROM picks WHERE user_id=? AND game_id=? AND season=? AND week=?',(user['id'],g['id'],season,week))
                        else:raise Problem('Invalid pick side')
                    result={'ok':True}
                elif route.startswith('admin/') and method=='POST':
                    if user['role']!='admin':raise Problem('Admin access required',403)
                    if route=='admin/invite':
                        name=str(data.get('name','')).strip()[:80]
                        if not name:raise Problem('Name required')
                        code=secrets.token_urlsafe(18);c.execute('INSERT INTO invites VALUES(?,?,?)',(hashlib.sha256(code.encode()).hexdigest(),name,time.time()+604800));result={'code':code}
                    elif route=='admin/member':
                        if data['id']==user['id']:raise Problem('You cannot disable your own account')
                        c.execute('UPDATE users SET active=? WHERE id=?',(int(bool(data['active'])),data['id']));c.execute('DELETE FROM sessions WHERE user_id=?',(data['id'],));result={'ok':True}
                    elif route=='admin/sync':
                        season,week=period(data);result={'message':sync_feed(season,week)}
                    elif route=='admin/result':
                        season,week=period(data);g=next((g for g in game_rows(c,season,week) if g['id']==data.get('id')),None)
                        if not g:raise Problem('Unknown game',404)
                        if data.get('status') not in ('final','void'):raise Problem('Invalid result status')
                        if any(not isinstance(data.get(k),int) or not 0<=data[k]<=200 for k in ('homeScore','awayScore')):raise Problem('Scores must be integers from 0 to 200')
                        if kickoff(g)>time.time() and data['status']=='final':raise Problem('Cannot finalize a game before kickoff')
                        g.update(status=data['status'],homeScore=data['homeScore'],awayScore=data['awayScore']);put_game(c,g,season,week);result={'ok':True}
                    elif route=='admin/game':
                        season,week=period(data);g=data['game'];validate_game(g);g.update(id=secrets.token_hex(12),included=False,status='scheduled');put_game(c,g,season,week);result={'ok':True}
                    elif route=='admin/slate':
                        season,week=period(data);c.execute('BEGIN IMMEDIATE');old={g['id']:g for g in game_rows(c,season,week)}
                        for item in data.get('games',[]):
                            g=old.get(item['id'])
                            if not g:raise Problem('Unknown game')
                            if locked(g):
                                if bool(item.get('included'))!=bool(g.get('included')):raise Problem('A game has started and its slate selection is locked. Refresh the slate.',409)
                                continue
                            if not g.get('included'):
                                g['spread']=item.get('spread')
                                if g['spread'] is not None and (isinstance(g['spread'],bool) or not isinstance(g['spread'],(float,int)) or not math.isfinite(g['spread']) or abs(g['spread'])>100):raise Problem('Invalid spread')
                            if item.get('included') and g.get('spread') is None:raise Problem('Select a spread before including a game')
                            if not item.get('included') and g.get('included') and c.execute('SELECT 1 FROM picks WHERE game_id=? AND season=? AND week=?',(g['id'],season,week)).fetchone():raise Problem('Cannot remove a game after members have picked it',409)
                            g['included']=bool(item.get('included'));put_game(c,g,season,week)
                        result={'ok':True}
                    else:raise Problem('Not found',404)
                else:raise Problem('Not found',404)
        content=json.dumps(result).encode();status='200 OK'
    except Problem as e:content=json.dumps({'error':e.message}).encode();status=f'{e.status} Error'
    except Exception:
        import traceback;traceback.print_exc();content=b'{"error":"Server error. Please try again."}';status='500 Error'
    headers.append(('Content-Type','application/json'));start_response(status,headers);return [content]
def period(data):
    try:season=int(data.get('season',2026));week=int(data.get('week',12))
    except (ValueError,TypeError):raise Problem('Invalid season or week')
    if not (2000<=season<=2100 and 1<=week<=18):raise Problem('Season or week is out of range')
    return season,week
def validate_game(g):
    if not g.get('away') or not g.get('home') or not isinstance(g.get('spread'),(float,int)) or abs(g['spread'])>100 or kickoff(g)<=time.time():raise Problem('Teams, a valid spread, and a future kickoff are required')
initialize()
if __name__=='__main__':
    from wsgiref.simple_server import make_server
    print('Saturday Club listening on port '+os.getenv('PORT','8000'))
    make_server('0.0.0.0',int(os.getenv('PORT','8000')),application).serve_forever()
