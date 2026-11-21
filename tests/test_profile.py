import unittest
import test_app
import server

class ProfileTests(unittest.TestCase):
    setUp=test_app.AppTests.setUp
    tearDown=test_app.AppTests.tearDown
    call=test_app.AppTests.call
    login=test_app.AppTests.login
    game=test_app.AppTests.game

    def test_only_signed_in_account_name_changes_preserving_identity_and_history(self):
        self.login();admin=self.call('state')[1]['user']
        with server.db() as c:
            c.execute('INSERT INTO users VALUES(?,?,?,?,?,1)',('member','Original','member@example.com',server.pw_hash('member-password-123'),'member'))
            before=dict(c.execute('SELECT * FROM users WHERE id=?',('member',)).fetchone())
            c.execute('INSERT INTO picks VALUES(?,?,?,?,?)',('member','g1',2026,12,'home'))
            c.execute('INSERT INTO picks VALUES(?,?,?,?,?)',('member','g1',2025,12,'home'))
        self.game(status='final',offset=-3600)
        self.call('logout',{});self.assertEqual(self.call('login',{'email':'member@example.com','password':'member-password-123'})[0],200)
        status,result=self.call('profile',{'name':'  Coach   K  ','id':admin['id'],'role':'admin','email':'attacker@example.com','password':'replacement'})
        self.assertEqual(status,200);self.assertEqual(result['user'],{'id':'member','name':'Coach K','role':'member'})
        with server.db() as c:
            after=dict(c.execute('SELECT * FROM users WHERE id=?',('member',)).fetchone())
            self.assertEqual(after,{**before,'name':'Coach K'})
            self.assertEqual(c.execute('SELECT name FROM users WHERE id=?',(admin['id'],)).fetchone()[0],admin['name'])
            self.assertEqual(c.execute('SELECT count(*) FROM picks WHERE user_id=?',('member',)).fetchone()[0],2)
        state=self.call('state')[1];self.assertEqual(state['user']['name'],'Coach K');self.assertEqual(state['picks'],{'g1':'home'})
        self.assertEqual(next(row for row in state['standings'] if row['id']=='member')['name'],'Coach K')
        self.assertEqual(state['lockedPicks']['g1']['home'][0]['name'],'Coach K')
        archive=self.call('state?season=2025&week=12')[1]
        self.assertEqual(next(row for row in archive['standings'] if row['id']=='member')['name'],'Coach K')
        self.assertEqual(self.call('admin/invite',{'name':'Other'})[0],403)

    def test_auth_validation_unicode_and_origin(self):
        self.assertEqual(self.call('profile',{'name':'New'})[0],401);self.login()
        for name in ['', '   ', 'x'*81, None, 123, ['name'], 'Hi\nThere', 'Hi\x00There', '\u200b', '\ud800']:
            self.assertEqual(self.call('profile',{'name':name})[0],400,repr(name))
        name='José 🏈'
        self.assertEqual(self.call('profile',{'name':name})[1]['user']['name'],name)
        self.assertEqual(self.call('profile',{'name':'Blocked'},origin='https://evil.example')[0],403)
        self.assertEqual(self.call('state')[1]['user']['name'],name)
        self.assertEqual(self.call('profile',{'name':'x'*80})[0],200)
        with server.db() as c:c.execute('UPDATE users SET active=0')
        self.assertEqual(self.call('profile',{'name':'Blocked'})[0],401)
