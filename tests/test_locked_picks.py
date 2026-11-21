import datetime
import json
import time
import unittest
import test_app
import server

class LockedPickTests(unittest.TestCase):
    setUp=test_app.AppTests.setUp
    tearDown=test_app.AppTests.tearDown
    call=test_app.AppTests.call
    login=test_app.AppTests.login
    game=test_app.AppTests.game

    def members(self):
        with server.db() as c:
            for uid,name,active in [('alice','Alice',1),('bob','Bob',1),('carol','Carol',1),('retired','Former member',0)]:
                c.execute('INSERT INTO users VALUES(?,?,?,?,?,?)',(uid,name,uid+'@example.com',server.pw_hash('member-password-123'),'member',active))

    def pick(self,uid,gid,side,season=2026,week=12):
        with server.db() as c:c.execute('INSERT OR REPLACE INTO picks VALUES(?,?,?,?,?)',(uid,gid,season,week,side))

    def test_no_early_disclosure_for_members_or_admins(self):
        self.members();self.login();self.game();self.pick('alice','g1','home')
        admin_state=self.call('state')[1]
        self.assertEqual(admin_state['lockedPicks'],{})
        self.assertEqual(admin_state['picks'],{})
        self.call('logout',{})
        self.call('login',{'email':'bob@example.com','password':'member-password-123'})
        state=self.call('state')[1]
        self.assertEqual(state['lockedPicks'],{});self.assertEqual(state['picks'],{})
        self.assertNotIn('alice',json.dumps(state['games']))

    def test_reveal_names_and_sides_only_after_kickoff_even_with_delayed_feed(self):
        self.members();self.login();self.game(offset=-1)
        self.pick('alice','g1','home');self.pick('bob','g1','away');self.pick('retired','g1','home')
        self.call('logout',{});self.call('login',{'email':'alice@example.com','password':'member-password-123'})
        result=self.call('state')[1]['lockedPicks']['g1']
        self.assertEqual([m['name'] for m in result['away']],['Bob'])
        self.assertEqual([m['name'] for m in result['home']],['Alice','Former member'])
        self.assertIn('Carol',[m['name'] for m in result['none']])
        for group in result.values():
            for member in group:self.assertEqual(set(member),{'id','name'})
        self.assertEqual(self.call('picks',{'season':2026,'week':12,'picks':{'g1':'away'}})[0],409)
        self.assertEqual(self.call('state')[1]['lockedPicks']['g1'],result)

    def test_current_period_only_and_no_unpublished_or_future_void_or_unknown_kickoff(self):
        self.members();self.login()
        self.game(id='live',status='live',offset=-10);self.game(id='upcoming',offset=3600)
        hidden=self.game(id='hidden',status='live',offset=-10);hidden['included']=False
        future_void=self.game(id='future-void',status='void',offset=3600)
        unknown=self.game(id='unknown');unknown['kickoff']=None
        with server.db() as c:
            server.put_game(c,hidden,2026,12);server.put_game(c,unknown,2026,12)
            server.put_game(c,{**unknown,'id':'old-year','status':'final'},2025,12)
            server.put_game(c,{**unknown,'id':'other-week','status':'final'},2026,13)
        for gid in ['live','upcoming','hidden','future-void','unknown']:self.pick('alice',gid,'home')
        self.pick('alice','old-year','away',season=2025);self.pick('alice','other-week','away',week=13)
        data=self.call('state')[1]['lockedPicks'];self.assertEqual(set(data),{'live'})
        data=self.call('state?season=2025&week=12')[1]['lockedPicks'];self.assertEqual(set(data),{'old-year'})
        self.assertEqual(data['old-year']['away'][0]['name'],'Alice')
        self.assertEqual(set(self.call('state?season=2026&week=13')[1]['lockedPicks']),{'other-week'})

    def test_reveal_boundary_is_server_time_and_final_games_remain_visible(self):
        self.members();self.login();game=self.game(offset=3600);boundary=server.kickoff(game)
        self.pick('alice','g1','home')
        with server.db() as c:
            self.assertEqual(server.revealed_game_picks(c,[game],2026,12,at=boundary-.001),{})
            self.assertIn('g1',server.revealed_game_picks(c,[game],2026,12,at=boundary))
        game=self.game(status='final',offset=-3600)
        self.assertEqual(self.call('state')[1]['lockedPicks']['g1']['home'][0]['name'],'Alice')
        self.call('logout',{});self.assertEqual(self.call('state')[0],401)
