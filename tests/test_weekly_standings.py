import unittest
import test_app
import server

class WeeklyStandingsTests(unittest.TestCase):
    setUp=test_app.AppTests.setUp
    tearDown=test_app.AppTests.tearDown
    call=test_app.AppTests.call
    login=test_app.AppTests.login
    game=test_app.AppTests.game

    def test_week_season_and_percentage_isolation(self):
        self.login()
        uid=self.call('state')[1]['user']['id']
        with server.db() as c:
            for week,side,spread,status,included in [(12,'home',-3.5,'final',True),(12,'away',-3.5,'final',True),(12,'home',-4,'final',True),(11,'home',-3.5,'final',True),(12,'home',-3.5,'scheduled',True),(12,'home',-3.5,'void',True),(12,'home',-3.5,'final',False)]:
                gid=str(c.execute('SELECT count(*) FROM games').fetchone()[0])
                game={'id':gid,'home':'Home','away':'Away','spread':spread,'status':status,'included':included,'homeScore':24,'awayScore':20}
                server.put_game(c,game,2026,week)
                c.execute('INSERT INTO picks VALUES(?,?,?,?,?)',(uid,gid,2026,week,side))
            c.execute('INSERT INTO users VALUES(?,?,?,?,?,1)',('empty','No Picks','empty@example.com','unused','member'))
        state=self.call('state?season=2026&week=12')[1]
        week=next(row for row in state['weeklyStandings'] if row['id']==uid)
        overall=next(row for row in state['standings'] if row['id']==uid)
        self.assertEqual((week['wins'],week['losses'],week['pushes'],week['points'],week['winPercentage']),(1,1,1,1.5,50.0))
        self.assertEqual((overall['wins'],overall['losses'],overall['points'],overall['winPercentage']),(2,1,2.5,66.7))
        self.assertIsNone(next(row for row in state['weeklyStandings'] if row['id']=='empty')['winPercentage'])
        self.assertTrue(all(row['points']==0 for row in self.call('state?season=2025&week=12')[1]['weeklyStandings']))
        other=self.call('state?season=2026&week=11')[1]
        self.assertEqual(next(row for row in other['weeklyStandings'] if row['id']==uid)['winPercentage'],100.0)
        self.assertEqual(next(row for row in other['standings'] if row['id']==uid)['points'],2.5)

    def test_weekly_live_projection_and_privacy(self):
        self.login();g=self.game(status='live',offset=-3600)
        uid=self.call('state')[1]['user']['id']
        with server.db() as c:
            c.execute('INSERT INTO picks VALUES(?,?,?,?,?)',(uid,'g1',2026,12,'home'))
            server.put_game(c,{**g,'id':'prior'},2026,11)
            c.execute('INSERT INTO picks VALUES(?,?,?,?,?)',(uid,'prior',2026,11,'home'))
        state=self.call('state')[1]
        row=next(row for row in state['weeklyLiveStandings']['rows'] if row['id']==uid)
        self.assertEqual(row['projectedPoints'],1)
        self.assertEqual(row['wins'],0);self.assertIsNone(row['winPercentage'])
        self.assertEqual(next(row for row in state['liveStandings']['rows'] if row['id']==uid)['projectedPoints'],2)
        with server.db() as c:server.put_game(c,{**g,'status':'scheduled','kickoff':'2099-01-01T00:00:00Z'},2026,12)
        self.assertEqual(next(row for row in self.call('state')[1]['weeklyLiveStandings']['rows'] if row['id']==uid)['projectedPoints'],0)
