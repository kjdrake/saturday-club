import json
import os
import time
import unittest
from unittest.mock import patch
import test_app
import server
import invitations
import notifications

class NotificationTests(unittest.TestCase):
    setUp=test_app.AppTests.setUp
    tearDown=test_app.AppTests.tearDown
    call=test_app.AppTests.call
    login=test_app.AppTests.login
    game=test_app.AppTests.game

    def future_game(self,gid='g1'):
        game=self.game(id=gid);game['included']=False
        with server.db() as c:server.put_game(c,game,2026,12)
        return game

    def publish(self,ids=('g1',),notify=True):
        return self.call('admin/slate',{'season':2026,'week':12,'games':[{'id':gid,'included':True,'spread':-3.5} for gid in ids],'notifyMembers':notify})

    def settings(self):return self.call('state')[1]['notificationAdmin']

    def notify(self,retry=False,revision=None):
        return self.call('admin/slate/notify',{'season':2026,'week':12,'expectedRevision':revision or self.settings()['currentRevision'],'retryFailed':retry})

    def configured(self):return patch.dict(os.environ,{'APP_URL':'https://4thandsoul.com','SES_FROM_EMAIL':'invitations@4thandsoul.com'})

    def test_publish_commits_durable_queue_and_deduplicates_identical_slates(self):
        self.login();self.future_game()
        with server.db() as c:
            for uid,email,active in [('alice','alice@example.com',1),('bob','bob@example.com',1),('disabled','disabled@example.com',0),('invalid','not-an-email',1)]:
                c.execute('INSERT INTO users VALUES(?,?,?,?,?,?)',(uid,uid,email,server.pw_hash('member-password-123'),'member',active))
            c.execute('INSERT INTO notification_preferences VALUES(?,0)',('bob',))
        with self.configured(),patch.object(invitations,'send_message') as send:
            status,result=self.publish();self.assertEqual(status,200);self.assertEqual(result['campaign']['total'],2);send.assert_not_called()
            same=self.publish()[1]['campaign'];self.assertEqual(same['id'],result['campaign']['id'])
            self.assertEqual(self.notify()[1]['campaign']['id'],same['id'])
            self.assertTrue(notifications.process_one(server.db));self.assertTrue(notifications.process_one(server.db));self.assertFalse(notifications.process_one(server.db))
            self.assertEqual(send.call_count,2)
            self.assertEqual({args.args[0] for args in send.call_args_list},{'admin@example.com','alice@example.com'})
            for call in send.call_args_list:
                body=call.args[2];self.assertIn('season=2026&week=12#picks',body);self.assertIn('Selecting a team alone does NOT save',body);self.assertIn('Save picks',body);self.assertIn('All picks saved',body);self.assertIn('skip games',body)
            current=self.settings()['campaign'];self.assertEqual(current['sent'],2);self.assertEqual(current['pending'],0)
            self.notify();self.assertFalse(notifications.process_one(server.db));self.assertEqual(send.call_count,2)
            self.assertNotIn('alice@example.com',json.dumps(self.settings()))

    def test_publication_succeeds_without_email_and_can_notify_later(self):
        self.login();self.future_game()
        with patch.dict(os.environ,{'SES_FROM_EMAIL':''}):
            status,result=self.publish();self.assertEqual(status,200);self.assertIn('notificationWarning',result)
            self.assertTrue(self.call('state')[1]['games'][0]['included']);self.assertIsNotNone(self.call('state')[1]['slatePublication'])
        with self.configured():self.assertEqual(self.notify()[0],200)
        with server.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM slate_notices').fetchone()[0],1)

    def test_preferences_are_self_only_and_rechecked_before_delivery(self):
        self.login();self.future_game()
        with self.configured():self.publish()
        admin=self.call('state')[1]['user']['id']
        self.assertEqual(self.call('profile/notifications',{'slateEmails':False,'id':'someone-else'})[0],200)
        self.assertFalse(self.call('state')[1]['user']['slateEmails'])
        with self.configured(),patch.object(invitations,'send_message') as send:
            self.assertTrue(notifications.process_one(server.db));send.assert_not_called()
            self.assertEqual(self.settings()['campaign']['skipped'],1)
        self.assertEqual(self.call('profile/notifications',{'slateEmails':'false'})[0],400)
        self.assertEqual(self.call('profile/notifications',{'slateEmails':True},origin='https://evil.example')[0],403)
        with server.db() as c:self.assertEqual(c.execute('SELECT user_id FROM notification_preferences').fetchone()[0],admin)
        self.call('logout',{});self.assertEqual(self.call('profile/notifications',{'slateEmails':True})[0],401)

    def test_failed_attempts_require_explicit_retry_and_never_resend_accepted(self):
        self.login();self.future_game()
        with self.configured(),patch.object(invitations,'send_message',side_effect=RuntimeError('private-recipient-provider-details')) as send:
            self.publish()
            for attempt in range(3):
                self.assertTrue(notifications.process_one(server.db));self.assertFalse(notifications.process_one(server.db))
                campaign=self.settings()['campaign'];self.assertEqual(campaign['failed'],1)
                self.assertNotIn('private-recipient',json.dumps(campaign));self.notify(retry=True)
            self.assertFalse(notifications.process_one(server.db));self.assertEqual(send.call_count,3)
            self.assertEqual(self.settings()['campaign']['retryable'],0)

    def test_stale_editor_obsolete_revision_and_started_slates_are_not_sent(self):
        self.login();self.future_game();self.future_game('g2')
        with self.configured(),patch.object(invitations,'send_message') as send:
            self.publish();old_revision=self.settings()['currentRevision']
            self.publish(ids=('g1','g2'))
            self.assertEqual(self.notify(revision=old_revision)[0],409)
            self.assertTrue(notifications.process_one(server.db));send.assert_not_called() # obsolete queued version
            self.assertTrue(notifications.process_one(server.db));self.assertEqual(send.call_count,1)
            self.assertFalse(notifications.process_one(server.db))
            with server.db() as c:
                for g in server.game_rows(c,2026,12):g['status']='live';server.put_game(c,g,2026,12)
            self.assertEqual(self.notify()[0],409)

    def test_only_admin_can_queue_and_invalid_slate_rolls_back_notification(self):
        self.future_game();self.assertEqual(self.call('admin/slate/notify',{})[0],401);self.login()
        with self.configured():
            status,_=self.call('admin/slate',{'season':2026,'week':12,'games':[{'id':'g1','included':True,'spread':-3.5},{'id':'missing','included':True}],'notifyMembers':True})
            self.assertEqual(status,400)
            with server.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM slate_notices').fetchone()[0],0)
        code=self.call('admin/invite',{'name':'Member'})[1]['code'];self.call('register',{'email':'m@example.com','password':'member-password-123','code':code})
        self.assertEqual(self.call('admin/slate/notify',{})[0],403)
        self.assertIsNone(self.call('state')[1]['notificationAdmin'])

    def test_lease_recovery_does_not_automatically_duplicate_uncertain_sends(self):
        self.login();self.future_game()
        with self.configured(),patch.object(invitations,'send_message') as send:
            self.publish()
            with server.db() as c:c.execute("UPDATE slate_deliveries SET status='sending',attempts=1,updated=?",(time.time()-600,))
            self.assertFalse(notifications.process_one(server.db));send.assert_not_called()
            self.assertEqual(self.settings()['campaign']['failed'],1)
            self.notify(retry=True);self.assertTrue(notifications.process_one(server.db));self.assertEqual(send.call_count,1)

    def test_independent_text_preferences_validation_and_privacy(self):
        self.login()
        self.assertEqual(self.call('state')[1]['user']['slateTexts'],False)
        for payload in [dict(slateEmails=True,slateTexts=True,phone=''),dict(slateEmails=False,slateTexts=True,phone='5551234567'),dict(slateEmails=True,slateTexts='yes',phone='+15551234567')]:
            self.assertEqual(self.call('profile/notifications',payload)[0],400)
        self.assertTrue(self.call('state')[1]['user']['slateEmails'])
        status,result=self.call('profile/notifications',dict(slateEmails=False,slateTexts=True,phone='+1 (555) 123-4567',id='other'))
        self.assertEqual(status,200);self.assertEqual(result['phone'],'+15551234567')
        self.assertFalse(result['slateEmails']);self.assertTrue(result['slateTexts'])
        state=self.call('state')[1];self.assertEqual(state['user']['phone'],'+15551234567')
        self.assertNotIn('phone',state['members'][0]);self.assertEqual(state['notificationAdmin']['textRecipientCount'],1)
        # Legacy email-only saves preserve independent text consent and number.
        self.call('profile/notifications',dict(slateEmails=True))
        self.assertTrue(self.call('state')[1]['user']['slateTexts'])
        self.call('profile/notifications',dict(slateEmails=True,slateTexts=False,phone=''))
        self.assertEqual(self.call('state')[1]['user']['phone'],'')
        with server.db() as c:self.assertEqual(notifications.text_recipients(c),[])

    def test_manual_texts_recheck_consent_and_require_admin_upcoming_published_slate(self):
        self.login();self.future_game();self.publish(notify=False)
        self.call('profile/notifications',dict(slateEmails=False,slateTexts=True,phone='+15551234567'))
        uid=self.call('state')[1]['user']['id']
        payload=dict(season=2026,week=12,expectedRevision=self.settings()['currentRevision'])
        status,result=self.call('admin/slate/text',payload)
        self.assertEqual(status,200);self.assertEqual(result['recipients'][0]['id'],uid);self.assertNotIn('phone',result['recipients'][0])
        with self.configured():
            status,result=self.call('admin/slate/text',dict(payload,recipientId=uid))
            self.assertEqual(status,200);self.assertTrue(result['smsUrl'].startswith('sms:+15551234567?body='))
            message=server.urllib.parse.unquote(result['smsUrl']);self.assertIn('week=12#picks',message);self.assertIn('Save picks',message)
        self.assertEqual(self.call('admin/slate/text',dict(payload,expectedRevision='old'))[0],409)
        self.call('profile/notifications',dict(slateEmails=False,slateTexts=False))
        self.assertEqual(self.call('admin/slate/text',dict(payload,recipientId=uid))[0],409)
        self.assertEqual(self.call('admin/slate/text',payload)[1]['recipients'],[])
        self.call('profile/notifications',dict(slateEmails=False,slateTexts=True))
        with server.db() as c:c.execute("UPDATE users SET role='member' WHERE id=?",(uid,))
        self.assertEqual(self.call('admin/slate/text',payload)[0],403)
        state=self.call('state')[1];self.assertIsNone(state['notificationAdmin'])
        self.call('logout',{});self.assertEqual(self.call('admin/slate/text',payload)[0],401)
