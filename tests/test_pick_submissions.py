import unittest
import test_app
import server

class PickSubmissionTests(unittest.TestCase):
    setUp=test_app.AppTests.setUp
    tearDown=test_app.AppTests.tearDown
    call=test_app.AppTests.call
    login=test_app.AppTests.login
    game=test_app.AppTests.game

    def status(self):return self.call('state')[1]['pickSubmissions']

    def test_saved_counts_timestamps_empty_saves_and_failed_saves(self):
        self.login();self.game();self.game(id='g2')
        uid=self.call('state')[1]['user']['id']
        before=self.status();self.assertEqual(before['gameCount'],2);self.assertFalse(before['firstGameStarted'])
        self.assertEqual(before['members'][0]['savedCount'],0);self.assertIsNone(before['members'][0]['lastSavedAt'])
        self.assertEqual(self.call('picks',dict(season=2026,week=12,picks={'g1':'away'}))[0],200)
        saved=self.status()['members'][0];self.assertEqual(saved['savedCount'],1);self.assertGreater(saved['lastSavedAt'],0)
        self.assertEqual(set(saved),{'id','name','savedCount','lastSavedAt'})
        self.assertEqual(self.call('picks',dict(season=2026,week=12,picks={'g1':'home','g2':'bad'}))[0],400)
        self.assertEqual(self.status()['members'][0],saved)
        self.assertEqual(self.call('state')[1]['picks']['g1'],'away')
        self.call('picks',dict(season=2026,week=12,picks={}))
        empty=self.status()['members'][0];self.assertEqual(empty['savedCount'],0);self.assertGreaterEqual(empty['lastSavedAt'],saved['lastSavedAt'])
        self.assertEqual(self.call('state?season=2027&week=12')[1]['pickSubmissions']['members'][0]['savedCount'],0)
        self.assertIsNone(self.call('state?season=2026&week=13')[1]['pickSubmissions']['members'][0]['lastSavedAt'])

    def test_active_roster_published_nonvoid_slate_and_legacy_picks(self):
        self.login();self.game();self.game(id='void',status='void',offset=-3600);draft=self.game(id='draft');draft['included']=False
        with server.db() as c:
            server.put_game(c,draft,2026,12)
            for uid,active in [('legacy',1),('inactive',0)]:
                c.execute('INSERT INTO users VALUES(?,?,?,?,?,?)',(uid,uid,uid+'@example.com',server.pw_hash('test-password-123'),'member',active))
                for gid in ['g1','void','draft','missing']:c.execute('INSERT INTO picks VALUES(?,?,?,?,?)',(uid,gid,2026,12,'away'))
        status=self.status();self.assertEqual(status['gameCount'],1);self.assertFalse(status['firstGameStarted'])
        rows={r['id']:r for r in status['members']};self.assertNotIn('inactive',rows);self.assertEqual(rows['legacy']['savedCount'],1);self.assertIsNone(rows['legacy']['lastSavedAt'])
        self.game(offset=-1);self.assertTrue(self.status()['firstGameStarted'])

    def test_counts_and_timestamps_are_commissioner_only(self):
        self.login();self.game();self.call('picks',dict(season=2026,week=12,picks={'g1':'away'}))
        uid=self.call('state')[1]['user']['id']
        with server.db() as c:c.execute("UPDATE users SET role='member' WHERE id=?",(uid,))
        state=self.call('state')[1];self.assertIsNone(state['pickSubmissions']);self.assertEqual(state['lockedPicks'],{})
        self.call('logout',{});self.assertEqual(self.call('state')[0],401)
