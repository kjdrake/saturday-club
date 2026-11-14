"""Exercise the real deployment shell's health/rollback paths without AWS resources."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]

class RollbackTests(unittest.TestCase):
    def run_deploy(self, healthy, previous=True):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); install=root/'club'; install.mkdir(); bins=root/'bin';bins.mkdir()
            old='a'*40; new='b'*40
            (install/'releases'/old).mkdir(parents=True)
            (install/'releases'/old/'compose.prod.yaml').write_text('services: {}')
            (install/'config.env').write_text('AWS_REGION=us-east-1\nDOMAIN=pickem.example.com\nECR_REPOSITORY=123.dkr.ecr.us-east-1.amazonaws.com/club\nSECRET_ARN=test-secret\nBACKUP_BUCKET=test\n')
            (install/'ready').touch()
            if previous:(install/'current-sha').write_text(old+'\n')
            (install/'backup.sh').write_text('#!/bin/sh\nexit 0\n');(install/'backup.sh').chmod(0o700)
            mock='''#!/usr/bin/env python3
import os,sys,json
from pathlib import Path
name=Path(sys.argv[0]).name;args=sys.argv[1:]
with open(os.environ['MOCK_LOG'],'a') as out:out.write(json.dumps([name,args,os.getenv('APP_IMAGE')])+'\\n')
if name=='aws':
 if 'get-secret-value' in args:print(json.dumps({'ADMIN_EMAIL':'a@example.com','ADMIN_NAME':'Admin','ADMIN_PASSWORD':'test-only-password','ODDS_API_KEY':''}))
 else:print('test-token')
if name=='curl' and os.environ['HEALTHY']=='https-fail' and any(a.startswith('https://') for a in args):sys.exit(1)
if name=='docker':
 if args[0]=='login':sys.stdin.read()
 if args[0]=='create':print('container')
 if args[0]=='cp':Path(args[-1]).write_text('services: {}')
 if args[0]=='compose' and 'up' in args and os.environ['NEW_SHA'] in os.getenv('APP_IMAGE','') and os.environ['HEALTHY']=='no':sys.exit(1)
'''
            for name in ['aws','docker','curl']:
                p=bins/name;p.write_text(mock);p.chmod(0o700)
            driver=root/'deploy.sh'
            driver.write_text((ROOT/'infra/deploy.sh').read_text().replace('/opt/saturday-club',str(install)).replace('/run/saturday-club-deploy.lock',str(root/'deploy.lock')))
            env={**os.environ,'PATH':str(bins)+':'+os.environ['PATH'],'MOCK_LOG':str(root/'calls'),'NEW_SHA':new,'HEALTHY':healthy if isinstance(healthy,str) else 'yes' if healthy else 'no'}
            result=subprocess.run(['bash',str(driver),new],env=env,capture_output=True,text=True)
            calls=[json.loads(line) for line in (root/'calls').read_text().splitlines()]
            marker=(install/'current-sha').read_text().strip() if (install/'current-sha').exists() else None
            return result,calls,marker,old,new
    def test_failure_restores_previous_release_and_keeps_current_marker(self):
        result,calls,marker,old,new=self.run_deploy(False)
        self.assertNotEqual(result.returncode,0,result.stderr)
        self.assertEqual(marker,old)
        up=[row for row in calls if row[0]=='docker' and row[1][0]=='compose' and 'up' in row[1]]
        self.assertEqual([row[2].rsplit(':',1)[1] for row in up],[new,old])
        self.assertIn('Rolled back',result.stderr)
        self.assertNotIn('test-only-password',result.stdout+result.stderr)
    def test_https_health_failure_rolls_back_even_when_containers_started(self):
        result,calls,marker,old,new=self.run_deploy('https-fail')
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(marker,old)
        self.assertIn('Rolled back',result.stderr)
    def test_success_records_new_release(self):
        result,calls,marker,old,new=self.run_deploy(True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(marker,new)
    def test_failed_initial_deployment_stops_containers_without_removing_volumes(self):
        result,calls,marker,old,new=self.run_deploy(False,previous=False)
        self.assertNotEqual(result.returncode,0)
        self.assertIsNone(marker)
        down=[row for row in calls if row[0]=='docker' and 'down' in row[1]]
        self.assertEqual(len(down),1)
        self.assertNotIn('--volumes',down[0][1])

if __name__=='__main__':unittest.main()
