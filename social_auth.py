"""Server-side OAuth authorization-code flows. No provider tokens are persisted."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.parse
import urllib.request

SCHEMA = '''
CREATE TABLE IF NOT EXISTS social_identities(provider TEXT NOT NULL,subject TEXT NOT NULL,user_id TEXT NOT NULL,PRIMARY KEY(provider,subject),UNIQUE(provider,user_id));
CREATE TABLE IF NOT EXISTS oauth_requests(state TEXT PRIMARY KEY,browser TEXT NOT NULL,provider TEXT NOT NULL,invite TEXT,link_user TEXT,verifier TEXT NOT NULL,expires REAL NOT NULL);
'''
LABELS = {'google': 'Google', 'facebook': 'Facebook'}
ERRORS = {
    'expired': 'This sign-in attempt expired or was already used. Please try again.',
    'cancelled': 'Sign-in was cancelled. Your invitation has not been used.',
    'provider': 'We could not verify your provider account. Please try again.',
    'invite': 'A valid, unused invitation is required to join Saturday Club.',
    'email': 'Your provider must share an email address to create your account.',
    'existing': 'This email already has a league account. Sign in with your existing method, then connect this provider from your account.',
    'disabled': 'This league account is disabled. Contact your commissioner.',
    'link': 'Sign in to the original league account again before connecting this provider.',
    'connected': 'This provider account is already connected to another league account.',
}

class SocialError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(ERRORS.get(code, ERRORS['provider']))

def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

def config(provider):
    if provider not in LABELS:
        return None
    base = os.getenv('APP_URL', '').rstrip('/')
    parsed = urllib.parse.urlparse(base)
    client = os.getenv(provider.upper() + '_CLIENT_ID', '').strip()
    secret = os.getenv(provider.upper() + '_CLIENT_SECRET', '').strip()
    if parsed.scheme != 'https' or not parsed.netloc or parsed.path or parsed.query or parsed.fragment or parsed.username or not client or not secret:
        return None
    return {'client': client, 'secret': secret, 'redirect': base + '/api/oauth/' + provider + '/callback'}

def request_json(url, data=None, headers=None):
    request = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode() if data is not None else None, headers=headers or {})
    # Provider errors can include credentials. Never log their bodies or URLs.
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            result = json.load(response)
        if not isinstance(result, dict) or result.get('error'):
            raise SocialError('provider')
        return result
    except SocialError:
        raise
    except Exception:
        raise SocialError('provider') from None

def identity(provider, conf, code, verifier):
    if provider == 'google':
        token = request_json('https://oauth2.googleapis.com/token', {
            'client_id': conf['client'], 'client_secret': conf['secret'], 'code': code,
            'redirect_uri': conf['redirect'], 'grant_type': 'authorization_code', 'code_verifier': verifier,
        })
        access = token.get('access_token')
        if not isinstance(access, str) or not access:
            raise SocialError('provider')
        profile = request_json('https://openidconnect.googleapis.com/v1/userinfo', headers={'Authorization': 'Bearer ' + access})
        if profile.get('email_verified') is not True:
            raise SocialError('email')
        subject = profile.get('sub')
    else:
        token = request_json('https://graph.facebook.com/v23.0/oauth/access_token', {
            'client_id': conf['client'], 'client_secret': conf['secret'], 'code': code, 'redirect_uri': conf['redirect'],
        })
        access = token.get('access_token')
        if not isinstance(access, str) or not access:
            raise SocialError('provider')
        inspected = request_json('https://graph.facebook.com/v23.0/debug_token?' + urllib.parse.urlencode({'input_token': access}), headers={'Authorization': 'Bearer ' + conf['client'] + '|' + conf['secret']}).get('data', {})
        if inspected.get('is_valid') is not True or str(inspected.get('app_id')) != conf['client']:
            raise SocialError('provider')
        profile = request_json('https://graph.facebook.com/v23.0/me?' + urllib.parse.urlencode({
            'fields': 'id,email', 'appsecret_proof': hmac.new(conf['secret'].encode(), access.encode(), hashlib.sha256).hexdigest(),
        }), headers={'Authorization': 'Bearer ' + access})
        subject = profile.get('id')
        if str(inspected.get('user_id')) != str(subject):
            raise SocialError('provider')
    if not isinstance(subject, str) or not subject or len(subject) > 255:
        raise SocialError('provider')
    email = str(profile.get('email') or '').strip().lower()
    return subject, email

def start(c, provider, code, user):
    conf = config(provider)
    if not conf:
        raise SocialError('provider')
    invite = digest(code) if code and not user else None
    if invite and not c.execute('SELECT 1 FROM invites WHERE code=? AND expires>?', (invite, time.time())).fetchone():
        raise SocialError('invite')
    state, browser, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    c.execute('DELETE FROM oauth_requests WHERE expires<?', (time.time(),))
    c.execute('INSERT INTO oauth_requests VALUES(?,?,?,?,?,?,?)', (digest(state), digest(browser), provider, invite, user['id'] if user else None, verifier, time.time() + 600))
    params = {'client_id': conf['client'], 'redirect_uri': conf['redirect'], 'response_type': 'code', 'state': state}
    if provider == 'google':
        params.update(scope='openid email', code_challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode(), code_challenge_method='S256', prompt='select_account')
        url = 'https://accounts.google.com/o/oauth2/v2/auth'
    else:
        params.update(scope='email')
        url = 'https://www.facebook.com/v23.0/dialog/oauth'
    return url + '?' + urllib.parse.urlencode(params), browser

def complete(c, provider, data, browser, user, password_hash):
    conf = config(provider)
    if not conf:
        raise SocialError('provider')
    c.execute('BEGIN IMMEDIATE')
    attempt = c.execute('SELECT * FROM oauth_requests WHERE state=?', (digest(data.get('state', '')),)).fetchone()
    if not attempt or attempt['expires'] <= time.time() or attempt['provider'] != provider or not hmac.compare_digest(attempt['browser'], digest(browser)):
        raise SocialError('expired')
    c.execute('DELETE FROM oauth_requests WHERE state=?', (attempt['state'],))
    c.commit()  # Consume even failed/cancelled exchanges; a callback cannot be replayed.
    if data.get('error'):
        raise SocialError('cancelled')
    if not data.get('code'):
        raise SocialError('provider')
    subject, email = identity(provider, conf, data['code'], attempt['verifier'])
    c.execute('BEGIN IMMEDIATE')
    linked = c.execute('SELECT u.* FROM users u JOIN social_identities s ON s.user_id=u.id WHERE s.provider=? AND s.subject=?', (provider, subject)).fetchone()
    if linked and not linked['active']:
        raise SocialError('disabled')
    if attempt['link_user']:
        if not user or user['id'] != attempt['link_user'] or not c.execute('SELECT 1 FROM users WHERE id=? AND active=1', (user['id'],)).fetchone():
            raise SocialError('link')
        if linked and linked['id'] != user['id']:
            raise SocialError('connected')
        existing = c.execute('SELECT subject FROM social_identities WHERE provider=? AND user_id=?', (provider, user['id'])).fetchone()
        if existing and existing['subject'] != subject:
            raise SocialError('connected')
        uid = user['id']
    elif linked:
        uid = linked['id']
    else:
        invite = c.execute('SELECT * FROM invites WHERE code=? AND expires>?', (attempt['invite'], time.time())).fetchone()
        if not invite:
            raise SocialError('invite')
        if '@' not in email or len(email) > 254:
            raise SocialError('email')
        # Never merge by email, especially Facebook's unverified email claim.
        if c.execute('SELECT 1 FROM users WHERE lower(email)=?', (email,)).fetchone():
            raise SocialError('existing')
        uid = secrets.token_hex(12)
        c.execute('INSERT INTO users VALUES(?,?,?,?,?,1)', (uid, invite['name'], email, password_hash(secrets.token_urlsafe(48)), 'member'))
        c.execute('DELETE FROM invites WHERE code=?', (attempt['invite'],))
    c.execute('INSERT OR IGNORE INTO social_identities VALUES(?,?,?)', (provider, subject, uid))
    return uid
