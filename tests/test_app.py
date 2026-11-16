import unittest, tempfile, os, json, io, time, datetime
from unittest.mock import patch
os.environ['DATABASE_PATH']=tempfile.mktemp(suffix='.db')
os.environ['ADMIN_EMAIL']='admin@example.com'
os.environ['ADMIN_PASSWORD']='test-admin-password-123'
os.environ['COOKIE_SECURE']='false'
import server
class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();server.DB=self.temp.name+'/test.db';server.initialize();self.cookie=''
    def tearDown(self):self.temp.cleanup()
    def call(self,path,body=None,cookie=None,origin=None):
        raw=json.dumps(body).encode() if body is not None else b'';parts=path.split('?',1)
        env={'PATH_INFO':'/api/'+parts[0],'QUERY_STRING':parts[1] if len(parts)>1 else '','REQUEST_METHOD':'POST' if body is not None else 'GET','CONTENT_TYPE':'application/json','CONTENT_LENGTH':str(len(raw)),'wsgi.input':io.BytesIO(raw),'HTTP_COOKIE':self.cookie if cookie is None else cookie,'HTTP_HOST':'localhost','REMOTE_ADDR':'test-'+self.temp.name}
        if origin:env['HTTP_ORIGIN']=origin
        response={}
        def start(status,headers):response.update(status=int(status[:3]),headers=dict(headers))
        data=json.loads(b''.join(server.application(env,start)))
        if 'Set-Cookie' in response['headers']:self.cookie=response['headers']['Set-Cookie'].split(';')[0]
        return response['status'],data
    def login(self):self.assertEqual(self.call('login',{'email':'admin@example.com','password':'test-admin-password-123'})[0],200)
    def game(self,id='g1',status='scheduled',spread=-3.5,offset=3600):
        g={'id':id,'home':'Home','away':'Away','spread':spread,'status':status,'included':True,'kickoff':datetime.datetime.fromtimestamp(time.time()+offset,datetime.timezone.utc).isoformat(),'homeScore':24,'awayScore':20}
        with server.db() as c:server.put_game(c,g,2026,12)
        return g
    def test_auth_and_roles(self):
        self.assertEqual(self.call('state')[0],401);self.login()
        code=self.call('admin/invite',{'name':'Friend'})[1]['code']
        self.call('logout',{})
        self.assertEqual(self.call('register',{'email':'friend@example.com','password':'friend-password-123','code':code})[0],200)
        self.assertEqual(self.call('admin/invite',{'name':'Other'})[0],403)
        self.assertEqual(self.call('register',{'email':'other@example.com','password':'friend-password-123','code':code})[0],403)
    def test_locks_and_frozen_lines(self):
        self.login();g=self.game()
        self.assertEqual(self.call('picks',{'season':2026,'week':12,'picks':{'g1':'home'}})[0],200)
        self.call('admin/slate',{'season':2026,'week':12,'games':[{'id':'g1','included':True,'spread':-99}]})
        self.assertEqual(self.call('state')[1]['games'][0]['spread'],-3.5)
        self.assertEqual(self.call('admin/slate',{'season':2026,'week':12,'games':[{'id':'g1','included':False}]})[0],409)
        self.game(offset=-5)
        self.assertEqual(self.call('picks',{'season':2026,'week':12,'picks':{'g1':'away'}})[0],409)
        self.assertEqual(self.call('picks',{'season':2026,'week':12,'picks':{}})[0],409)
        self.assertEqual(self.call('state')[1]['picks']['g1'],'home')
    def test_grading_and_season_isolation(self):
        self.login();self.game();self.call('picks',{'season':2026,'week':12,'picks':{'g1':'home'}});g=self.game(status='final')
        self.assertEqual(self.call('state')[1]['standings'][0]['points'],1)
        self.assertEqual(self.call('state?season=2025&week=12')[1]['standings'][0]['points'],0)
        self.assertEqual(server.points({**g,'spread':-4},'home'),.5)
        self.assertEqual(server.points(g,'away'),0)
        self.assertIsNone(server.points({**g,'status':'void'},'home'))
    def test_csrf_and_disabled_sessions(self):
        self.login();self.assertEqual(self.call('admin/invite',{'name':'X'},origin='https://evil.example')[0],403)
        with server.db() as c:c.execute('UPDATE users SET active=0')
        self.assertEqual(self.call('state')[0],401)
    def test_sync_keeps_frozen_spread_and_updates_scores(self):
        self.game(id='100')
        team=lambda side,id,name: {'homeAway':side,'score':'28' if side=='home' else '24','team':{'id':id,'displayName':name,'abbreviation':name,'conferenceId':'8'},'records':[]}
        feed={'events':[{'id':'100','date':'2026-11-14T20:30Z','status':{'type':{'completed':True,'state':'post'}},'competitions':[{'competitors':[team('home','1','Home'),team('away','2','Away')],'odds':[{'spread':9,'details':'Home -9','provider':{'name':'Test book'}}]}]}]}
        with patch.object(server,'fetch_json',return_value=feed),patch.dict(os.environ,{'ODDS_API_KEY':''}):server.sync_feed(2026,12)
        with server.db() as c:g=server.game_rows(c,2026,12)[0]
        self.assertEqual(g['spread'],-3.5);self.assertEqual(g['status'],'final');self.assertEqual(g['homeScore'],28);self.assertEqual(g['homeConference'],'SEC');self.assertEqual(g['awayConferenceId'],'8')
    def test_commissioner_publishes_subset_and_member_can_skip_or_clear(self):
        self.login();admin_cookie=self.cookie
        for id in ['g1','g2','g3']:
            game=self.game(id=id);game['included']=False
            with server.db() as c:server.put_game(c,game,2026,12)
        self.assertEqual(self.call('admin/slate',{'season':2026,'week':12,'games':[{'id':'g1','included':True,'spread':-3.5},{'id':'g2','included':True,'spread':-3.5}]})[0],200)
        code=self.call('admin/invite',{'name':'Selective Friend'})[1]['code']
        self.assertEqual(self.call('register',{'email':'selective@example.com','password':'selective-password-123','code':code})[0],200)
        self.assertEqual({g['id'] for g in self.call('state')[1]['games']},{'g1','g2'})
        self.assertEqual(self.call('picks',{'season':2026,'week':12,'picks':{'g1':'away'}})[0],200)
        self.assertEqual(self.call('state')[1]['picks'],{'g1':'away'})
        admin_games=self.call('state',cookie=admin_cookie)[1]['games']
        self.assertTrue(next(g for g in admin_games if g['id']=='g1')['hasPicks'])
        self.assertEqual(self.call('picks',{'season':2026,'week':12,'picks':{}})[0],200)
        self.assertEqual(self.call('state')[1]['picks'],{})
        self.assertEqual(self.call('picks',{'season':2026,'week':12,'picks':{'g3':'home'}})[0],409)
    def test_publishing_preserves_hidden_games_and_protected_picks_atomically(self):
        self.login();self.game(id='protected');self.game(id='hidden')
        other=self.game(id='other');other['included']=False
        with server.db() as c:server.put_game(c,other,2026,12)
        self.call('picks',{'season':2026,'week':12,'picks':{'protected':'home'}})
        status,_=self.call('admin/slate',{'season':2026,'week':12,'games':[{'id':'other','included':True,'spread':-3.5},{'id':'protected','included':False,'spread':-3.5}]})
        self.assertEqual(status,409)
        games={g['id']:g for g in self.call('state')[1]['games']}
        self.assertFalse(games['other']['included']);self.assertTrue(games['protected']['included']);self.assertTrue(games['hidden']['included'])
        self.assertEqual(self.call('admin/slate',{'season':2026,'week':12,'games':[{'id':'other','included':True,'spread':-3.5}]})[0],200)
        games={g['id']:g for g in self.call('state')[1]['games']}
        self.assertTrue(all(g['included'] for g in games.values()))
    def test_started_games_and_missing_lines_cannot_be_added(self):
        self.login();past=self.game(id='past',offset=-5);past['included']=False
        missing=self.game(id='missing');missing.update(included=False,spread=None)
        with server.db() as c:server.put_game(c,past,2026,12);server.put_game(c,missing,2026,12)
        self.assertEqual(self.call('admin/slate',{'season':2026,'week':12,'games':[{'id':'past','included':True,'spread':-3.5}]})[0],409)
        self.assertEqual(self.call('admin/slate',{'season':2026,'week':12,'games':[{'id':'missing','included':True,'spread':None}]})[0],400)
        self.assertEqual(self.call('admin/slate',{'season':2026,'week':12,'games':[{'id':'missing','included':True,'spread':float('nan')}]})[0],400)
        self.assertEqual(self.call('admin/slate',{'season':2026,'week':12,'games':[{'id':'missing','included':True,'spread':7.5}]})[0],200)

    def live_fixture(self):
        with server.db() as c:
            for uid,name in [('alice','Alice'),('bob','Bob'),('carol','Carol')]:
                c.execute('INSERT INTO users VALUES(?,?,?,?,?,1)',(uid,name,uid+'@example.com',server.pw_hash('test-password-123'),'member'))
            live={'id':'live','home':'Home','away':'Away','spread':-3.5,'included':True,'status':'live','kickoff':datetime.datetime.fromtimestamp(time.time()-3600,datetime.timezone.utc).isoformat(),'homeScore':24,'awayScore':20}
            server.put_game(c,live,2026,12)
            c.execute('INSERT INTO picks VALUES(?,?,?,?,?)',('alice','live',2026,12,'home'))
            c.execute('INSERT INTO picks VALUES(?,?,?,?,?)',('bob','live',2026,12,'away'))
            c.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',('last-2026-12',server.now_iso()))
        return live
    def test_live_projection_flips_ranks_without_changing_official_points_or_picks(self):
        self.login();live=self.live_fixture()
        state=self.call('state')[1];board=state['liveStandings'];rows={r['id']:r for r in board['rows']}
        self.assertEqual(rows['alice']['projectedPoints'],1);self.assertEqual(rows['bob']['projectedPoints'],0)
        self.assertEqual(rows['alice']['rank'],1);self.assertEqual(rows['bob']['rank'],2)
        self.assertEqual(rows['alice']['points'],0);self.assertTrue(all(r['points']==0 for r in state['standings']))
        self.assertEqual(board['activeGames'],1);self.assertFalse(board['stale'])
        live['awayScore']=27
        with server.db() as c:server.put_game(c,live,2026,12)
        state=self.call('state')[1];rows={r['id']:r for r in state['liveStandings']['rows']}
        self.assertEqual(rows['bob']['rank'],1);self.assertEqual(rows['bob']['livePoints'],1)
        self.assertEqual(rows['alice']['livePoints'],0)
        with server.db() as c:self.assertEqual(c.execute('SELECT side FROM picks WHERE user_id=?',('alice',)).fetchone()[0],'home')
    def test_live_push_finalization_and_void_do_not_double_count(self):
        self.login();live=self.live_fixture();live['spread']=-4
        with server.db() as c:server.put_game(c,live,2026,12)
        rows={r['id']:r for r in self.call('state')[1]['liveStandings']['rows']}
        self.assertEqual(rows['alice']['livePoints'],.5);self.assertEqual(rows['bob']['livePoints'],.5)
        self.assertEqual(rows['alice']['livePushes'],1);self.assertEqual(rows['alice']['rank'],rows['bob']['rank'])
        live['status']='final'
        with server.db() as c:server.put_game(c,live,2026,12)
        state=self.call('state')[1];rows={r['id']:r for r in state['liveStandings']['rows']}
        self.assertEqual(rows['alice']['points'],.5);self.assertEqual(rows['alice']['livePoints'],0);self.assertEqual(rows['alice']['projectedPoints'],.5)
        self.assertEqual(state['liveStandings']['activeGames'],0)
        live['status']='void'
        with server.db() as c:server.put_game(c,live,2026,12)
        row=next(r for r in self.call('state')[1]['liveStandings']['rows'] if r['id']=='alice')
        self.assertEqual(row['projectedPoints'],0)
    def test_unstarted_picks_stay_private_and_stale_feed_is_labeled(self):
        self.login();live=self.live_fixture()
        scheduled={**live,'id':'scheduled','status':'scheduled','homeScore':99,'awayScore':0,'kickoff':datetime.datetime.fromtimestamp(time.time()+3600,datetime.timezone.utc).isoformat()}
        with server.db() as c:
            server.put_game(c,scheduled,2026,13);c.execute('INSERT INTO picks VALUES(?,?,?,?,?)',('carol','scheduled',2026,13,'home'))
            c.execute('UPDATE meta SET value=? WHERE key=?',((datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(minutes=5)).isoformat(),'last-2026-12'))
        board=self.call('state?season=2026&week=13')[1]['liveStandings'];rows={r['id']:r for r in board['rows']}
        self.assertEqual(rows['carol']['livePicks'],0);self.assertEqual(rows['carol']['projectedPoints'],0)
        self.assertTrue(board['stale']);self.assertEqual(board['activeGames'],1)
        other=self.call('state?season=2025&week=12')[1]['liveStandings']
        self.assertEqual(other['activeGames'],0);self.assertTrue(all(r['projectedPoints']==0 for r in other['rows']))
    def test_betting_odds_are_cached_independently_of_score_refresh(self):
        with patch.dict(os.environ,{'ODDS_API_KEY':'test-only-key'}),patch.object(server,'fetch_json',return_value=[{'id':'event'}]) as fetch:
            self.assertEqual(server.betting_odds(),[{'id':'event'}]);self.assertEqual(server.betting_odds(),[{'id':'event'}]);self.assertEqual(fetch.call_count,1)

if __name__=='__main__':unittest.main()
