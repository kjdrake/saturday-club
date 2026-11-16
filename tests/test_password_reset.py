import os
import stat
import time
import unittest
import urllib.parse
from unittest.mock import patch
import test_social_auth
import server
import password_reset
import invitations

class PasswordResetTests(unittest.TestCase):
    setUp=test_social_auth.SocialAuthTests.setUp
    tearDown=test_social_auth.SocialAuthTests.tearDown
    call=test_social_auth.SocialAuthTests.call

    def request(self,email='admin@example.com',failure=False):
        with patch.dict(os.environ,{'SES_FROM_EMAIL':'invitations@4thandsoul.com'}),patch.object(password_reset,'dispatch',side_effect=lambda job:job()),patch.object(invitations,'send_password_reset',side_effect=RuntimeError('private-error') if failure else None) as send:
            result=self.call('password/forgot',{'email':email})
        return result,send

    def token(self,send):
        link=send.call_args.args[2]
        self.assertEqual(urllib.parse.urlparse(link).query,'')
        self.assertTrue(link.startswith('https://4thandsoul.com/#reset-password='))
        return link.split('#reset-password=')[1]

    def test_generic_responses_and_no_account_creation_or_disabled_delivery(self):
        known,send=self.request();self.assertEqual(send.call_count,1)
        unknown,send=self.request('missing@example.com');self.assertEqual(send.call_count,0)
        with server.db() as c:c.execute('UPDATE users SET active=0')
        disabled,send=self.request();self.assertEqual(send.call_count,0)
        self.assertEqual(known['body'],unknown['body']);self.assertEqual(known['body'],disabled['body'])
        with server.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM users').fetchone()[0],1)

    def test_only_hashed_token_stored_and_success_preserves_data_and_revokes_sessions(self):
        self.assertEqual(self.call('login',{'email':'admin@example.com','password':'test-admin-password-123'})['status'],200)
        old_cookie=dict(self.cookies)
        result,send=self.request();token=self.token(send)
        with server.db() as c:
            row=c.execute('SELECT * FROM password_resets').fetchone();uid=row['user_id']
            self.assertNotEqual(row['token'],token);self.assertEqual(row['token'],password_reset.digest(token));self.assertAlmostEqual(row['expires']-time.time(),1800,delta=3)
            c.execute('INSERT INTO picks VALUES(?,?,?,?,?)',(uid,'g1',2026,12,'home'))
        self.assertNotIn(token,str(result))
        self.assertEqual(self.call('password/reset',{'token':token,'password':'new-long-password-456'})['status'],200)
        self.cookies=old_cookie;self.assertEqual(self.call('state')['status'],401)
        self.assertEqual(self.call('login',{'email':'admin@example.com','password':'test-admin-password-123'})['status'],401)
        self.assertEqual(self.call('login',{'email':'admin@example.com','password':'new-long-password-456'})['status'],200)
        with server.db() as c:
            self.assertEqual(c.execute('SELECT side FROM picks').fetchone()[0],'home')
            self.assertEqual(c.execute('SELECT role FROM users').fetchone()[0],'admin')
            self.assertEqual(c.execute('SELECT count(*) FROM password_resets').fetchone()[0],0)
        self.assertEqual(self.call('password/reset',{'token':token,'password':'another-new-password'})['status'],400)

    def test_expired_invalid_disabled_weak_and_get_do_not_change_password(self):
        _,send=self.request();token=self.token(send)
        self.assertEqual(self.call('password/reset',{'token':token,'password':'short'})['status'],400)
        self.assertEqual(self.call('password/reset',{'token':'x'*43,'password':'long-password-123'})['status'],400)
        self.assertEqual(self.call('password/reset?token='+token)['status'],401)
        with server.db() as c:c.execute('UPDATE password_resets SET expires=0')
        self.assertEqual(self.call('password/reset',{'token':token,'password':'long-password-123'})['status'],400)
        _,send=self.request();token=self.token(send)
        with server.db() as c:c.execute('UPDATE users SET active=0')
        self.assertEqual(self.call('password/reset',{'token':token,'password':'long-password-123'})['status'],400)
        with server.db() as c:self.assertTrue(server.verify('test-admin-password-123',c.execute('SELECT password FROM users').fetchone()[0]))

    def test_multiple_links_remain_valid_until_reset_then_all_are_revoked(self):
        _,first=self.request();_,second=self.request()
        first_token=self.token(first);second_token=self.token(second)
        self.assertNotEqual(first_token,second_token)
        with server.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM password_resets').fetchone()[0],2)
        self.assertEqual(self.call('password/reset',{'token':first_token,'password':'new-password-12345'})['status'],200)
        self.assertEqual(self.call('password/reset',{'token':second_token,'password':'other-password-12345'})['status'],400)

    def test_delivery_failure_and_throttling_do_not_disclose_accounts(self):
        failed,send=self.request(failure=True)
        self.assertEqual(failed['status'],200);self.assertNotIn('private-error',str(failed))
        with server.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM password_resets').fetchone()[0],0)
        for _ in range(3):self.assertEqual(self.request()[1].call_count,1)
        limited,send=self.request();self.assertEqual(send.call_count,0);self.assertEqual(limited['body'],failed['body'])
        with patch.object(server,'limit',side_effect=server.Problem('Too many',429)):
            limited,send=self.request();self.assertEqual(send.call_count,0);self.assertEqual(limited['body'],failed['body'])

    def test_configuration_and_csrf_and_private_database_files(self):
        with patch.dict(os.environ,{'SES_FROM_EMAIL':''}):
            self.assertEqual(self.call('password/forgot',{'email':'admin@example.com'})['status'],503)
            self.assertEqual(self.call('password/forgot',{'email':'missing@example.com'})['status'],503)
        self.assertEqual(self.call('password/forgot',{'email':'not-email'})['status'],400)
        for suffix in ('','-wal','-shm'):
            if os.path.exists(server.DB+suffix):self.assertEqual(stat.S_IMODE(os.stat(server.DB+suffix).st_mode),0o600)
        headers=self.call('health')['headers']
        self.assertIn("script-src 'self'",headers['Content-Security-Policy'])
        self.assertIn("form-action 'self'",headers['Content-Security-Policy'])
        self.assertEqual(headers['Referrer-Policy'],'no-referrer')

    def test_concurrent_redemption_only_succeeds_once(self):
        from concurrent.futures import ThreadPoolExecutor
        _,send=self.request();token=self.token(send)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results=list(executor.map(lambda password:self.call('password/reset',{'token':token,'password':password})['status'],['first-password-1234','second-password-1234']))
        self.assertEqual(sorted(results),[200,400])

    def test_reset_endpoints_reject_cross_origin_requests(self):
        import io,json
        for route in ['password/forgot','password/reset']:
            raw=json.dumps({'email':'admin@example.com','token':'x'*43,'password':'long-password-123'}).encode()
            env={'PATH_INFO':'/api/'+route,'REQUEST_METHOD':'POST','CONTENT_TYPE':'application/json','CONTENT_LENGTH':str(len(raw)),'wsgi.input':io.BytesIO(raw),'HTTP_ORIGIN':'https://evil.example','HTTP_HOST':'4thandsoul.com'}
            status=[]
            result=b''.join(server.application(env,lambda code,headers:status.append(code)))
            self.assertTrue(status[0].startswith('403'));self.assertIn(b'Origin rejected',result)
