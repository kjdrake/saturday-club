"""Email account recovery: random, hashed, expiring, single-use tokens."""
import hashlib
import secrets
import threading
import time
import invitations

SCHEMA = '''
CREATE TABLE IF NOT EXISTS password_resets(token TEXT PRIMARY KEY,user_id TEXT NOT NULL,expires REAL NOT NULL,created REAL NOT NULL);
'''
MESSAGE = 'If an active account matches that email, a password reset link will arrive shortly. Check your inbox and spam folder.'
_slots = threading.BoundedSemaphore(4)

def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

def dispatch(job):
    # Bounded background delivery keeps account lookup/provider timing out of HTTP responses.
    if not _slots.acquire(blocking=False):
        return
    def run():
        try:
            job()
        finally:
            _slots.release()
    try:
        threading.Thread(target=run, daemon=True).start()
    except Exception:
        _slots.release()
        # Same generic HTTP response; users can request another link.

def enqueue(email, database):
    def deliver():
        token_hash = None
        try:
            with database() as c:
                c.execute('BEGIN IMMEDIATE')
                now = time.time()
                c.execute('DELETE FROM password_resets WHERE expires<?', (now,))
                user = c.execute('SELECT id,email,name FROM users WHERE lower(email)=? AND active=1', (email,)).fetchone()
                if not user:
                    return
                # Do not invalidate a link because someone else requested another one.
                if c.execute('SELECT count(*) FROM password_resets WHERE user_id=? AND created>?', (user['id'], now - 1800)).fetchone()[0] >= 3:
                    return
                token = secrets.token_urlsafe(32)
                token_hash = digest(token)
                c.execute('INSERT INTO password_resets VALUES(?,?,?,?)', (token_hash, user['id'], now + 1800, now))
            link = invitations.public_url() + '/#reset-password=' + token
            invitations.send_password_reset(user['email'], user['name'], link)
        except Exception:
            # Never log email addresses, token links, provider errors, or credentials.
            if token_hash:
                try:
                    with database() as c:
                        c.execute('DELETE FROM password_resets WHERE token=?', (token_hash,))
                except Exception:
                    pass
    dispatch(deliver)
