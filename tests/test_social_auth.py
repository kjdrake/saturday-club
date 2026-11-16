import io
import json
import os
import tempfile
import time
import unittest
import urllib.parse
from http.cookies import SimpleCookie
from unittest.mock import patch
import server
import social_auth

class SocialAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous_db = server.DB
        server.DB = self.temp.name + '/club.db'
        self.env = patch.dict(os.environ, {'ADMIN_EMAIL': 'admin@example.com', 'ADMIN_PASSWORD': 'test-admin-password-123', 'APP_URL': 'https://4thandsoul.com', 'GOOGLE_CLIENT_ID': 'google-client', 'GOOGLE_CLIENT_SECRET': 'google-secret', 'FACEBOOK_CLIENT_ID': 'facebook-client', 'FACEBOOK_CLIENT_SECRET': 'facebook-secret'})
        self.env.start()
        server.initialize()
        self.cookies = {}

    def tearDown(self):
        self.env.stop()
        server.DB = self.previous_db
        self.temp.cleanup()

    def call(self, path, body=None):
        path, _, query = path.partition('?')
        raw = json.dumps(body).encode() if body is not None else b''
        env = {'PATH_INFO': '/api/' + path, 'QUERY_STRING': query, 'REQUEST_METHOD': 'POST' if body is not None else 'GET', 'CONTENT_TYPE': 'application/json', 'CONTENT_LENGTH': str(len(raw)), 'wsgi.input': io.BytesIO(raw), 'HTTP_HOST': '4thandsoul.com', 'HTTP_COOKIE': '; '.join(k+'='+v for k,v in self.cookies.items()), 'REMOTE_ADDR': self.temp.name}
        response = {}
        def start(status, headers):
            response.update(status=int(status[:3]), headers=dict(headers))
            for key, value in headers:
                if key == 'Set-Cookie':
                    cookie = SimpleCookie();cookie.load(value)
                    for name, item in cookie.items():
                        self.cookies[name] = item.value
        content = b''.join(server.application(env, start))
        response['body'] = json.loads(content) if content else None
        return response

    def invite(self):
        self.assertEqual(self.call('login', {'email':'admin@example.com','password':'test-admin-password-123'})['status'], 200)
        code = self.call('admin/invite', {'name':'Invited Friend'})['body']['code']
        self.call('logout', {})
        return code

    def begin(self, provider='google', code=''):
        response = self.call('auth/start', {'provider':provider, 'code':code})
        self.assertEqual(response['status'], 200, response)
        params = urllib.parse.parse_qs(urllib.parse.urlsplit(response['body']['url']).query)
        self.assertEqual(params['redirect_uri'], ['https://4thandsoul.com/api/oauth/'+provider+'/callback'])
        return params['state'][0]

    def finish(self, state, provider='google', subject='subject-1', email='friend@example.com', **extra):
        with patch.object(social_auth, 'identity', return_value=(subject, email)):
            return self.call('oauth/'+provider+'/callback?'+urllib.parse.urlencode({'state':state,'code':'test-code',**extra}))

    def test_configuration_exposes_only_enabled_providers(self):
        result = self.call('auth/providers')
        self.assertEqual([p['id'] for p in result['body']['providers']], ['google','facebook'])
        self.assertNotIn('secret', json.dumps(result))
        with patch.dict(os.environ, {'GOOGLE_CLIENT_SECRET':'', 'FACEBOOK_CLIENT_SECRET':''}):
            self.assertEqual(self.call('auth/providers')['body']['providers'], [])
            self.assertEqual(self.call('auth/start', {'provider':'google'})['status'],403)

    def test_invitation_required_and_rechecked_after_provider_return(self):
        result = self.finish(self.begin())
        self.assertEqual(result['headers']['Location'], '/?auth_error=invite')
        code = self.invite();state = self.begin(code=code)
        with server.db() as c:c.execute('UPDATE invites SET expires=0')
        self.assertEqual(self.finish(state)['headers']['Location'], '/?auth_error=invite')
        with server.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM users').fetchone()[0],1)

    def test_google_signup_preserves_invite_name_member_role_and_can_return_without_invite(self):
        code = self.invite();state = self.begin(code=code)
        self.assertEqual(self.finish(state)['headers']['Location'], '/?auth_success=1')
        state = self.call('state')['body']
        self.assertEqual(state['user']['name'],'Invited Friend')
        self.assertEqual(state['user']['role'],'member')
        uid = state['user']['id']
        with server.db() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM invites').fetchone()[0],0)
            self.assertEqual(c.execute('SELECT count(*) FROM social_identities').fetchone()[0],1)
        self.call('logout',{})
        self.assertEqual(self.finish(self.begin())['headers']['Location'],'/?auth_success=1')
        self.assertEqual(self.call('state')['body']['user']['id'],uid)
        self.assertEqual(self.call('auth/start',{'provider':'facebook','code':code})['status'],200) # Signed-in linking needs no invite.

    def test_facebook_signup_and_single_use_invite_across_flows(self):
        code = self.invite();first = self.begin('facebook',code)
        browser = self.cookies['sc_oauth']
        second = self.begin('google',code)
        second_browser = self.cookies['sc_oauth']
        self.cookies['sc_oauth'] = browser
        self.assertEqual(self.finish(first,'facebook')['headers']['Location'],'/?auth_success=1')
        self.call('logout',{});self.cookies['sc_oauth'] = second_browser
        self.assertEqual(self.finish(second,subject='different',email='other@example.com')['headers']['Location'],'/?auth_error=invite')
        self.assertEqual(self.call('register',{'email':'third@example.com','password':'test-password-123','code':code})['status'],403)

    def test_state_cookie_provider_expiry_replay_and_cancellation(self):
        code = self.invite();state = self.begin(code=code);browser = self.cookies['sc_oauth']
        self.cookies['sc_oauth']='wrong'
        self.assertEqual(self.finish(state)['headers']['Location'],'/?auth_error=expired')
        self.cookies['sc_oauth']=browser
        self.assertEqual(self.finish(state,'facebook')['headers']['Location'],'/?auth_error=expired')
        self.cookies['sc_oauth']=browser
        self.assertEqual(self.finish(state,error='access_denied')['headers']['Location'],'/?auth_error=cancelled')
        self.cookies['sc_oauth']=browser
        self.assertEqual(self.finish(state)['headers']['Location'],'/?auth_error=expired')
        state=self.begin(code=code)
        with server.db() as c:c.execute('UPDATE oauth_requests SET expires=0')
        self.assertEqual(self.finish(state)['headers']['Location'],'/?auth_error=expired')
        with server.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM invites').fetchone()[0],1)

    def test_email_collision_cannot_take_over_existing_account_or_use_invite(self):
        code=self.invite();state=self.begin(code=code)
        self.assertEqual(self.finish(state,email='admin@example.com')['headers']['Location'],'/?auth_error=existing')
        with server.db() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM invites').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT count(*) FROM social_identities').fetchone()[0],0)

    def test_signed_in_linking_keeps_account_and_requires_original_session(self):
        self.call('login',{'email':'admin@example.com','password':'test-admin-password-123'})
        admin=self.call('state')['body']['user']['id']
        self.assertEqual(self.finish(self.begin(),email='other-address@example.com')['headers']['Location'],'/?auth_success=1')
        self.assertEqual(self.call('state')['body']['user']['id'],admin)
        self.assertEqual(self.call('auth/providers')['body']['providers'][0]['connected'],True)
        pending=self.begin('facebook');self.call('logout',{})
        self.assertEqual(self.finish(pending,'facebook')['headers']['Location'],'/?auth_error=link')
        self.assertEqual(self.finish(self.begin())['headers']['Location'],'/?auth_success=1')
        with server.db() as c:c.execute('UPDATE users SET active=0')
        self.call('logout',{})
        self.assertEqual(self.finish(self.begin())['headers']['Location'],'/?auth_error=disabled')

    def test_provider_failure_keeps_invitation_and_consumes_attempt(self):
        code=self.invite();state=self.begin(code=code);browser=self.cookies['sc_oauth']
        with patch.object(social_auth,'identity',side_effect=social_auth.SocialError('provider')):
            result=self.call('oauth/google/callback?'+urllib.parse.urlencode({'state':state,'code':'bad'}))
        self.assertEqual(result['headers']['Location'],'/?auth_error=provider')
        self.cookies['sc_oauth']=browser
        self.assertEqual(self.finish(state)['headers']['Location'],'/?auth_error=expired')
        with server.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM invites').fetchone()[0],1)

    def test_google_exchange_requires_verified_email_and_uses_pkce(self):
        conf=social_auth.config('google')
        with patch.object(social_auth,'request_json',side_effect=[{'access_token':'token'},{'sub':'google-id','email':'f@example.com','email_verified':True}]) as fetch:
            self.assertEqual(social_auth.identity('google',conf,'code','verifier'),('google-id','f@example.com'))
            self.assertEqual(fetch.call_args_list[0].args[1]['code_verifier'],'verifier')
            self.assertEqual(fetch.call_args_list[1].kwargs['headers']['Authorization'],'Bearer token')
        with patch.object(social_auth,'request_json',side_effect=[{'access_token':'token'},{'sub':'id','email':'f@example.com','email_verified':False}]):
            with self.assertRaises(social_auth.SocialError):social_auth.identity('google',conf,'code','verifier')

    def test_facebook_checks_app_subject_and_token_validity(self):
        conf=social_auth.config('facebook')
        for inspection in [{'is_valid':False,'app_id':'facebook-client','user_id':'id'}, {'is_valid':True,'app_id':'other-app','user_id':'id'}, {'is_valid':True,'app_id':'facebook-client','user_id':'wrong'}]:
            with patch.object(social_auth,'request_json',side_effect=[{'access_token':'token'},{'data':inspection},{'id':'id','email':'f@example.com'}]):
                with self.assertRaises(social_auth.SocialError):social_auth.identity('facebook',conf,'code','')
        with patch.object(social_auth,'request_json',side_effect=[{'access_token':'token'},{'data':{'is_valid':True,'app_id':'facebook-client','user_id':'id'}},{'id':'id','email':'f@example.com'}]):
            self.assertEqual(social_auth.identity('facebook',conf,'code',''),('id','f@example.com'))
