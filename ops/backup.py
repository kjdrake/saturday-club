"""Create a transactionally consistent SQLite backup; called inside the app container."""
import datetime
import os
import sqlite3
from pathlib import Path

def backup():
    database = Path(os.getenv('DATABASE_PATH', '/data/club.db'))
    target = database.parent / 'backups'
    target.mkdir(exist_ok=True)
    name = 'club-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.db'
    destination = target / name
    with sqlite3.connect(database) as source, sqlite3.connect(destination) as output:
        source.backup(output)
        if output.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('Database backup failed integrity check')
    os.chmod(destination, 0o600)
    return name

if __name__ == '__main__':
    print(backup())
