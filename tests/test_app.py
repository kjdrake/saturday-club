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
        team=lambda side,id,name: {'homeAway':side,'score':'28' if side=='home' else '24','team':{'id':id,'displayName':name,'abbreviation':name},'records':[]}
        feed={'events':[{'id':'100','date':'2026-11-14T20:30Z','status':{'type':{'completed':True,'state':'post'}},'competitions':[{'competitors':[team('home','1','Home'),team('away','2','Away')],'odds':[{'spread':9,'details':'Home -9','provider':{'name':'Test book'}}]}]}]}
        with patch.object(server,'fetch_json',return_value=feed),patch.dict(os.environ,{'ODDS_API_KEY':''}):server.sync_feed(2026,12)
        with server.db() as c:g=server.game_rows(c,2026,12)[0]
        self.assertEqual(g['spread'],-3.5);self.assertEqual(g['status'],'final');self.assertEqual(g['homeScore'],28)
if __name__=='__main__':unittest.main()
