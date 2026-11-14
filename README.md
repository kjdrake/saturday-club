# Saturday Club

College football against-the-spread pick’em for a group of friends. Includes a responsive browser app, authenticated Python WSGI API, SQLite storage, commissioner controls, ESPN score/odds adapter, optional The Odds API adapter, Docker Compose, and automatic HTTPS. No real-money wagering.

## Preview versus shared app

The published Sites version is a **static interactive preview**. Sample games, odds, scores, member records, and season history are explicitly labeled. Its picks and admin changes persist only in the current browser. It is not a shared live league.

Running the included Python server switches the same interface to authenticated shared mode. It starts with an empty league and no fabricated results. Use the admin account to sync games, select the weekly slate, and generate single-use invitation codes. Friends register using those codes; users cannot self-assign the admin role. This release supports one league with independent competitions by season and week (regular-season weeks 1–18).

## Run locally

Python 3.12 is recommended. The core server has no third-party dependencies.

```sh
export ADMIN_EMAIL=you@example.com
export ADMIN_NAME=Commissioner
read -s -p 'Initial admin password (12+ characters): ' ADMIN_PASSWORD
export ADMIN_PASSWORD
export COOKIE_SECURE=false
python server.py
```

Open http://localhost:8000. In another terminal run `python sync.py` for background updates. Set the same DATABASE_PATH if overriding it. For production use Gunicorn via Docker; wsgiref is only a development server. ADMIN_PASSWORD bootstraps the first account only. Remove the bootstrap environment values after creating the admin. Keep the password in a password manager. Password reset currently requires a server operator to update the stored password hash; there is no email reset flow.

## Deploy on AWS (single-instance Lightsail or EC2)

1. Create an Ubuntu instance with at least 1 GB RAM; attach a static IP. Allow inbound TCP 80 and 443 and restrict SSH to your IP. Do not expose 8000. Install Docker Engine and the Compose plugin using Docker's official Ubuntu instructions.
2. Point a domain's A record at the static IP. Copy this source to the instance.
3. Copy `.env.example` to `.env`, set DOMAIN, ADMIN_EMAIL, ADMIN_NAME, and a long random ADMIN_PASSWORD. Keep COOKIE_SECURE=true. Optionally set ODDS_API_KEY. Protect `.env` with `chmod 600 .env`.
4. Run `docker compose up -d --build`. Caddy provisions HTTPS; visit `https://YOUR_DOMAIN`. Sign in with the initial admin credentials.
5. Select season/week, click **Sync public feeds**, choose games with available lines, and save the slate. Create invite codes under Commissioner tools and share them yourself. Codes expire after 7 days and work once.
6. Check `docker compose logs --tail=50 app scores`. After bootstrap, remove ADMIN_PASSWORD from `.env` and recreate the containers. SQLite users persist in the Docker volume.

This is intentionally a simple, low-cost **single-instance** AWS deployment. Use EBS-backed storage and scheduled, encrypted EBS snapshots. Do not run independent replicas with separate SQLite databases. For multi-instance operation migrate persistence and sessions to RDS/PostgreSQL and use one scheduled feed worker. No AWS resources were provisioned by this task.

For a consistent manual backup while the app runs:

```sh
docker compose exec -T app python -c "import sqlite3; s=sqlite3.connect('/data/club.db'); d=sqlite3.connect('/data/backup.db'); s.backup(d); d.close()"
docker compose cp app:/data/backup.db ./backup.db
```

Encrypt and store backups outside the instance. Test a restore before relying on them.

## Feeds and rules

- ESPN public scoreboard: live scores and available bookmaker odds. No key required. This is an unofficial public endpoint with no availability guarantee; verify its usage terms before operating the app. Updates are polling, not a streaming feed.
- The Odds API: optional server-side ODDS_API_KEY; US college-football spreads from public bookmakers. An API subscription/quota may be required. Current provider team names must match ESPN names; unmatched games use ESPN odds or a manually entered line.
- The background worker polls selected weeks every 30 seconds near game day. The browser refreshes data every 30 seconds when there are no unsaved picks. Feed failures retain the last known results and update time. No simulated live updates are used in shared mode. Admin sync is rate-limited to once per 25 seconds per week.
- Lines freeze when a game is first included. They cannot change while selected, and picks lock on the server at kickoff. A game with picks cannot be removed. If no spread is available, the commissioner must enter a line before selecting it.
- Cover: 1 point. Push: 0.5. Miss or no pick: 0. Final games are graded dynamically, so score corrections update standings. Canceled/postponed games are void (0 points). Ties share a rank. Missed picks earn 0 but are not recorded as losses in W–L–P.
- Seasons are retained independently. The UI includes selectors for 2024–2026; add future years to the season select/archive list in `dist/index.html` and `dist/app.js`. The API supports 2000–2100. Postseason and multiple independent friend groups are not included.

## Security and operation

Passwords use salted scrypt, session tokens are stored as SHA-256 hashes, cookies are HttpOnly/SameSite with Secure enabled by default. All API mutations enforce authentication/roles, JSON content type, and same-origin checks. Disabled accounts lose active sessions. The API never exposes other members' unstarted-game picks. There is a bounded in-process login limiter; put AWS WAF or equivalent edge rate limits in front for broader public access. This is a small-group implementation, not a hardened high-volume service. SQLite transactions keep slate saves and pick submissions atomic.

## Checks

```sh
python -m unittest discover -s tests -v
node --check dist/app.js
```
