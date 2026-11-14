"""Smoke-test the actual production image, including auth and persistence across replacement."""
import datetime
import http.cookiejar
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request

image = sys.argv[1]
name = 'sc-smoke-' + str(os.getpid())
volume = name + '-data'
password = secrets.token_urlsafe(24)

def docker(*args):
    return subprocess.check_output(['docker', *args], text=True).strip()

def start():
    docker('run', '-d', '--name', name, '-p', '127.0.0.1::8000',
           '--mount', f'type=volume,source={volume},target=/data',
           '-e', 'ADMIN_EMAIL=ci@example.com', '-e', 'ADMIN_PASSWORD=' + password,
           '-e', 'COOKIE_SECURE=false', image)
    port = docker('port', name, '8000/tcp').rsplit(':', 1)[1]
    base = 'http://127.0.0.1:' + port
    for attempt in range(120):
        if attempt % 10 == 0 and docker('inspect', '-f', '{{.State.Running}}', name) != 'true':
            raise RuntimeError('Container exited before becoming healthy')
        try:
            with urllib.request.urlopen(base + '/api/health', timeout=2) as r:
                if json.load(r)['ok']:
                    return base
        except (OSError, ValueError):
            time.sleep(.5)
    raise RuntimeError('Container never became healthy')

def client(base):
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def request(path, data=None):
        raw = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(base + '/api/' + path, data=raw,
                                     headers={'Content-Type': 'application/json'} if raw else {})
        with opener.open(req, timeout=10) as response:
            return json.load(response)
    return request

try:
    base = start()
    with urllib.request.urlopen(base, timeout=5) as r:
        assert 'Saturday Club' in r.read().decode()
    admin = client(base)
    admin('login', {'email': 'ci@example.com', 'password': password})
    invitation = admin('admin/invite', {'name': 'CI Friend'})['code']
    future = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)).isoformat()
    admin('admin/game', {'season': 2026, 'week': 12, 'game': {
        'home': 'Home', 'away': 'Away', 'spread': -3.5, 'kickoff': future}})
    game = admin('state')['games'][0]
    admin('admin/slate', {'season': 2026, 'week': 12, 'games': [{**game, 'included': True}]})
    friend = client(base)
    friend('register', {'email': 'friend@example.com', 'password': password, 'code': invitation})
    friend('picks', {'season': 2026, 'week': 12, 'picks': {game['id']: 'home'}})
    try:
        friend('admin/invite', {'name': 'Forbidden'})
        raise AssertionError('Member obtained commissioner privileges')
    except urllib.error.HTTPError as error:
        assert error.code == 403
    assert friend('state')['picks'][game['id']] == 'home'
    assert docker('exec', name, 'python', '/app/ops/backup.py').startswith('club-')
    docker('rm', '-f', name)
    base = start()
    friend = client(base)
    friend('login', {'email': 'friend@example.com', 'password': password})
    assert friend('state')['picks'][game['id']] == 'home', 'Container replacement lost picks'
    print('Container smoke test passed: login, invites, roles, picks, backup, replacement persistence.')
except Exception:
    subprocess.run(['docker', 'logs', name], check=False)
    raise
finally:
    subprocess.run(['docker', 'rm', '-f', name], check=False, stdout=subprocess.DEVNULL)
    subprocess.run(['docker', 'volume', 'rm', volume], check=False, stdout=subprocess.DEVNULL)
