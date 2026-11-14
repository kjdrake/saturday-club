import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result
backup = module('backup', 'ops/backup.py')
deploy = module('deploy_ssm', 'infra/deploy_ssm.py')

class BackupTests(unittest.TestCase):
    def test_backup_includes_committed_wal_data_and_is_independent(self):
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / 'club.db'
            with sqlite3.connect(database) as c:
                c.execute('PRAGMA journal_mode=WAL')
                c.execute('CREATE TABLE picks(side TEXT)')
                c.execute("INSERT INTO picks VALUES ('home')")
                c.commit()
                with patch.dict(os.environ, {'DATABASE_PATH': str(database)}):
                    name = backup.backup()
                c.execute("UPDATE picks SET side='away'")
                c.commit()
            with sqlite3.connect(Path(temp) / 'backups' / name) as c:
                self.assertEqual(c.execute('SELECT side FROM picks').fetchone()[0], 'home')
                self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0], 'ok')

class DeploymentTests(unittest.TestCase):
    def test_waits_for_successful_command(self):
        with patch.dict(os.environ, {'INSTANCE_ID': 'i-test', 'DEPLOY_DOCUMENT': 'doc', 'IMAGE_TAG': 'a'*40}), \
             patch.object(deploy, 'aws', side_effect=[{'Command': {'CommandId': 'command'}}, {'Status': 'InProgress'}, {'Status': 'Success'}]) as aws, \
             patch.object(deploy.time, 'sleep'):
            deploy.main()
            self.assertEqual(aws.call_count, 3)
            self.assertIn(json.dumps({'ImageTag': ['a'*40]}), aws.call_args_list[0].args)
    def test_failed_remote_health_check_fails_pipeline(self):
        with patch.dict(os.environ, {'INSTANCE_ID': 'i-test', 'DEPLOY_DOCUMENT': 'doc', 'IMAGE_TAG': 'a'*40}), \
             patch.object(deploy, 'aws', side_effect=[{'Command': {'CommandId': 'command'}}, {'Status': 'Failed', 'StandardErrorContent': 'Rolled back'}]), \
             patch.object(deploy.time, 'sleep'):
            with self.assertRaises(SystemExit):
                deploy.main()
    def test_aws_permission_errors_are_not_silently_retried(self):
        error = subprocess.CalledProcessError(1, 'aws', stderr='AccessDeniedException')
        with patch.dict(os.environ, {'INSTANCE_ID': 'i-test', 'DEPLOY_DOCUMENT': 'doc', 'IMAGE_TAG': 'a'*40}), \
             patch.object(deploy, 'aws', side_effect=[{'Command': {'CommandId': 'command'}}, error]), \
             patch.object(deploy.time, 'sleep'):
            with self.assertRaises(subprocess.CalledProcessError):
                deploy.main()

if __name__ == '__main__':
    unittest.main()
