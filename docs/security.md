# Account security and recovery operations

## Member password resets

Configure SES using [account setup](account-setup.md), including the existing-host deployer update, then redeploy. On the sign-in screen choose **Forgot password?**, enter the league email and follow the email link. Passwords or passphrases must be 12–256 characters when reset. The browser checks confirmation; the server validates the token and length. No new account or role is created. Picks and historical standings are preserved.

Tokens use 32 random bytes, are stored only as SHA-256 hashes, expire after 30 minutes, and are redeemed in an atomic SQLite transaction. Reset links carry the token in a fragment, keeping it out of normal HTTP request URLs; the app removes it from the address bar and keeps it only in page memory. Refreshing requires reopening the email link. Scanning/opening a link does not consume it. Successful submission stores a new salted scrypt hash, deletes all account sessions and outstanding reset links, and removes pending social-account linking attempts. The user must sign in again; recovery does not automatically create a session.

The request endpoint responds with the same message for active, disabled and nonexistent accounts. Account lookup and delivery occur in bounded background threads so provider/lookup timing is not reflected in the HTTP response. Request and redemption attempts are rate-limited. Each account can have at most three unexpired reset links; requesting another link does not invalidate earlier links. Invalid/expired/reused tokens return the same reset error. If SES is unconfigured, the endpoint returns a setup error for all addresses.

Delivery is best effort: accepted requests do not guarantee email arrival, and an application restart can interrupt an in-flight delivery. Failed sends remove the corresponding token without exposing provider errors to the requester. Request another link if necessary; monitor SES bounce/complaint/delivery data. The application has no durable email outbox or delivery-receipt UI. No real message or provider credentials are used in automated tests.

## Implemented protection and its limits

- Caddy provides HTTPS, redirects HTTP, and sets HSTS. Secure/HttpOnly/SameSite cookies contain random session tokens; only their hashes are stored in SQLite. Verify production responses and AWS configuration rather than assuming a source template was applied.
- Passwords in the league database use salted scrypt. The initial `ADMIN_PASSWORD` runtime secret is only a bootstrap value; changing it does not update an existing account. Remove the bootstrap password from Secrets Manager after initial setup and redeploy if you do not need it retained. The existing account remains intact.
- Membership is invitation-only. APIs enforce user/admin roles, active status, JSON mutation requests and same-origin checks. Disabled users cannot sign in or reset passwords. Other members' unstarted picks are not included in API state.
- Database and WAL/SHM files use owner-only permissions. The infrastructure template encrypts EBS data/root disks and blocks public S3 backup access, with encrypted backups and a TLS-only bucket policy. These are storage-layer controls, not field encryption; privileged AWS/server operators can access data.
- Browser responses include a Content Security Policy restricting scripts/connections to this site, denying object embeds/framing and restricting forms/base URLs; permissions policy disables camera, microphone and geolocation. The logo fallback uses a script event listener rather than an inline handler. External fonts and selected ESPN logos remain permitted.
- Secrets and provider tokens stay server-side; OAuth provider tokens are discarded. Reset tokens/passwords are not returned in API responses or deliberately logged. The in-process rate limiter is intended for this small single-instance league, not as a substitute for edge-level abuse protection.

These changes are not an independent penetration test or compliance certification. The application does not implement MFA, automatic breach-password checks, or self-service account deletion. S3 database backup lifecycle settings expire current backups after 35 days and noncurrent versions after 7 days; operator-created snapshots/retained resources may persist separately. Review actual AWS configuration, dependency updates, access permissions and restore procedures as operations responsibilities.

## Operator recovery when email is unavailable

Changing `ADMIN_PASSWORD` in Secrets Manager or redeploying will not replace an existing account's password. In **AWS Systems Manager → Session Manager**, connect to the application instance and run this command. It prompts privately; do not paste a password into chat, command-line arguments or logs.

```sh
sudo docker exec -it saturday-club-app python -c '
import getpass, server
email = input("Account email: ").strip().lower()
password = getpass.getpass("New password (12+ characters): ")
confirm = getpass.getpass("Confirm new password: ")
if len(password) < 12 or len(password) > 256 or password != confirm:
    raise SystemExit("Passwords must match and be 12–256 characters.")
with server.db() as c:
    account = c.execute("SELECT id FROM users WHERE lower(email)=?", (email,)).fetchone()
    if not account:
        raise SystemExit("Account not found. Nothing changed.")
    c.execute("UPDATE users SET password=? WHERE id=?", (server.pw_hash(password), account["id"]))
    c.execute("DELETE FROM sessions WHERE user_id=?", (account["id"],))
    c.execute("DELETE FROM password_resets WHERE user_id=?", (account["id"],))
    c.execute("DELETE FROM oauth_requests WHERE link_user=?", (account["id"],))
print("Password changed. Sign in again with your new password.")
'
```

This takes effect immediately without a redeploy. It does not reactivate a disabled member or change their role, picks or standings. The `password_resets` cleanup requires the password-recovery release to be deployed.
