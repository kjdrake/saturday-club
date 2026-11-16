import os
from unittest.mock import patch
import test_social_auth
import server
import invitations

# Reuse the HTTP harness without duplicating its test cases.
class InvitationTests(__import__('unittest').TestCase):
    setUp=test_social_auth.SocialAuthTests.setUp
    tearDown=test_social_auth.SocialAuthTests.tearDown
    call=test_social_auth.SocialAuthTests.call
    begin=test_social_auth.SocialAuthTests.begin
    finish=test_social_auth.SocialAuthTests.finish

    def login(self):
        self.assertEqual(self.call('login',{'email':'admin@example.com','password':'test-admin-password-123'})['status'],200)

    def test_admin_only_and_link_mode_does_not_send(self):
        with patch.object(invitations,'send_email') as send:
            self.assertEqual(self.call('admin/invite',{'name':'Friend'})['status'],401)
            self.login()
            response=self.call('admin/invite',{'name':'Friend'})
            self.assertEqual(response['body']['delivery'],'link')
            send.assert_not_called()
            self.call('logout',{})
            code=response['body']['code']
            self.assertEqual(self.call('register',{'email':'f@example.com','password':'friend-password-123','code':code})['status'],200)
            self.assertEqual(self.call('admin/invite',{'name':'Other','delivery':'email','email':'f@example.com'})['status'],403)

    def test_email_sends_persisted_single_use_link_and_new_member_joins(self):
        self.login()
        def send(recipient,name,link):
            self.assertEqual(recipient,'friend@example.com')
            self.assertEqual(name,'Friend')
            self.assertTrue(link.startswith('https://4thandsoul.com/?invite='))
            with server.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM invites').fetchone()[0],1)
            return 'message-id'
        with patch.dict(os.environ,{'SES_FROM_EMAIL':'invitations@4thandsoul.com'}),patch.object(invitations,'send_email',side_effect=send):
            response=self.call('admin/invite',{'name':'Friend','delivery':'email','email':'friend@example.com'})
        self.assertEqual(response['status'],200)
        self.assertEqual(response['body']['delivery'],'email')
        self.call('logout',{})
        state=self.begin(code=response['body']['code'])
        self.assertEqual(self.finish(state)['headers']['Location'],'/?auth_success=1')

    def test_failure_cancels_invite_and_hides_provider_error(self):
        self.login()
        with patch.dict(os.environ,{'SES_FROM_EMAIL':'invitations@4thandsoul.com'}),patch.object(invitations,'send_email',side_effect=RuntimeError('private-provider-details')):
            response=self.call('admin/invite',{'name':'Friend','delivery':'email','email':'friend@example.com'})
        self.assertEqual(response['status'],502)
        self.assertNotIn('private-provider-details',str(response))
        with server.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM invites').fetchone()[0],0)

    def test_recipient_config_and_delivery_validation(self):
        self.login()
        with patch.dict(os.environ,{'SES_FROM_EMAIL':''}):
            self.assertEqual(self.call('admin/invite',{'name':'Friend','delivery':'email','email':'f@example.com'})['status'],503)
        for email in ['f@example.com,g@example.com','Someone <f@example.com>','f@example.com\r\nBcc: other@example.com','not-an-email']:
            self.assertEqual(self.call('admin/invite',{'name':'Friend','delivery':'email','email':email})['status'],400)
        self.assertEqual(self.call('admin/invite',{'name':'Friend','delivery':'sms'})['status'],400)
        with patch.dict(os.environ,{'APP_URL':'http://4thandsoul.com','SES_FROM_EMAIL':'invitations@4thandsoul.com'}):self.assertFalse(invitations.ready())

    def test_email_rate_limit_does_not_send_more_than_twenty(self):
        self.login()
        with patch.dict(os.environ,{'SES_FROM_EMAIL':'invitations@4thandsoul.com'}),patch.object(invitations,'send_email') as send:
            with server.db() as c:uid=c.execute('SELECT id FROM users').fetchone()[0]
            server._attempts.pop('invite-'+uid,None)
            for _ in range(20):self.assertEqual(self.call('admin/invite',{'name':'Friend','delivery':'email','email':'f@example.com'})['status'],200)
            self.assertEqual(self.call('admin/invite',{'name':'Friend','delivery':'email','email':'f@example.com'})['status'],429)
            self.assertEqual(send.call_count,20)

    def test_ses_sdk_accepts_request_without_real_delivery(self):
        try:
            import boto3
            from botocore.stub import Stubber, ANY
        except ImportError:
            self.skipTest('Install requirements.txt to exercise SES SDK validation')
        client=boto3.client('sesv2',region_name='us-east-1',aws_access_key_id='test-only',aws_secret_access_key='test-only')
        with Stubber(client) as stub, patch('boto3.client',return_value=client), patch.dict(os.environ,{'SES_FROM_EMAIL':'invitations@4thandsoul.com'}):
            stub.add_response('send_email',{'MessageId':'test-message-id'},{'FromEmailAddress':'invitations@4thandsoul.com','Destination':{'ToAddresses':['f@example.com']},'Content':ANY})
            self.assertEqual(invitations.send_email('f@example.com','Friend','https://4thandsoul.com/?invite=test'),'test-message-id')
            stub.assert_no_pending_responses()
