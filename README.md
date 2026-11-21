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

Open http://localhost:8000. In another terminal run `python sync.py` for background updates. Set the same DATABASE_PATH if overriding it. For production use Gunicorn via Docker; wsgiref is only a development server. ADMIN_PASSWORD bootstraps the first account only. Remove the bootstrap environment values after creating the admin. Keep the password in a password manager. Members can use Forgot password? once SES email is configured; see [password recovery and security](docs/security.md). Changing ADMIN_PASSWORD after bootstrap does not change an existing account password.

## Automatic AWS deployments with GitHub Actions

For the recommended EC2 + ECR + GitHub OIDC pipeline, follow [the one-time AWS setup guide](infra/README.md). Pull requests run tests; passing changes merged into `main` deploy automatically after AWS setup. It includes a CloudFormation stack, persistent encrypted storage, HTTPS, scheduled S3 backups, and health-check rollback. No AWS resources are provisioned just by committing the workflow.

## Manual deployment on Lightsail or EC2 (alternative)

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
- The background worker polls selected weeks about every 15 seconds near game day. Visible browser tabs refresh the leaderboard every 5 seconds, including while picks or a commissioner slate are being edited. Unsaved selections are merged with server updates; started games always use the saved server-side pick. Feed failures retain the last known results and update time, and a feed without a successful check for 60 seconds is labeled delayed. Admin sync is rate-limited to once per 12 seconds per week. The optional betting feed is cached for 10 minutes independently of the score refresh, and published spreads stay fixed unless a commissioner explicitly corrects them before kickoff. No simulated live updates are used in shared mode.
- Lines freeze when a game is first included. Feed refreshes do not change a published line. Commissioners can explicitly correct it before kickoff using Edit beside the spread, with a scoring-impact confirmation and a visible correction notice. Picks and spreads lock on the server at kickoff. A game with picks cannot be removed. If no spread is available, the commissioner must enter a line before selecting it.
- Cover: 1 point. Push: 0.5. Miss or no pick: 0. Final games are graded dynamically, so score corrections update standings. Canceled/postponed games are void (0 points). Commissioners can use Set result to grade a manually added game or correct a result. Feed-backed games may be overwritten by a subsequent sync. Ties share a rank. Missed picks earn 0 but are not recorded as losses in W–L–P.
- Seasons are retained independently. The UI initially lists 2024–2026. Use Commissioner tools → Season & week → Open season to manage any new season from 2000–2100. Seasons with saved games appear automatically in the season selector and archive. Postseason and multiple independent friend groups are not included.

## Security and operation

Passwords use salted scrypt, session tokens are stored as SHA-256 hashes, cookies are HttpOnly/SameSite with Secure enabled by default. All API mutations enforce authentication/roles, JSON content type, and same-origin checks. Disabled accounts lose active sessions. The API never exposes other members' unstarted-game picks. There is a bounded in-process login limiter; put AWS WAF or equivalent edge rate limits in front for broader public access. This is a small-group implementation, not a hardened high-volume service. SQLite transactions keep slate saves and pick submissions atomic.

## Checks

```sh
python -m unittest discover -s tests -v
node --check dist/app.js
```

## Team logos and appearance

The interface uses the 4th & Soul family palette: warm charcoal, cream, and antique gold. Saturday Club has its own SC badge, with shared identity rules in [the brand guide](BRAND.md). Weekly game selection uses shared grid columns for matchups, result buttons, and spreads at desktop and mobile widths. Team marks come from ESPN's public team directory/CDN; 142 logos are cached locally in `dist/assets/team-logos/`. The school directory also resolves manually entered names (for example, Texas A&M). Other schools use the CDN, with an abbreviation badge if no logo is available.

To refresh the directory and cache logos for another set of regular-season weeks:

```sh
python infra/fetch_team_logos.py --season 2026 --weeks 11 12 13
```

## Build a weekly slate

In **Commissioner tools**, choose the week at the top and click **Refresh games**. Use the search, conference selector, and ranking selector to find matchups. A conference filter includes games involving either team from that conference; **Conference matchups only** requires both teams to share a conference and excludes independents. Rankings support **Any Top 25 team** or **Top 25 vs. Top 25** (both teams ranked 1–25).

Check games individually or use **Add visible** / **Remove visible** for the filtered results. Selections survive filter changes and feed refreshes while you keep the page open. **Your slate** shows the selected games for review; **Publish weekly slate** saves only changed games, preserving selections hidden by a filter. Draft changes are held in the browser until published; publish or discard them before changing weeks or reloading the page. A missing spread must be entered before a game can be selected. Started games and games with submitted picks cannot be removed, and published spreads stay fixed unless a commissioner explicitly corrects them before kickoff.

Players receive only published games and may pick as many or as few as they like. Clicking an already selected side again clears it before kickoff; save picks to persist the change. A skipped game earns 0 points and does not count as a loss in W–L–P. Existing season records and picks are preserved by this update.

Conference IDs are captured from the public ESPN game feed when refreshed. The local school directory supplies conference labels for manually entered games and older records that have no stored conference metadata; that directory reflects the season used to generate it. Unknown schools appear as **Other / unknown** rather than being assigned a conference by guesswork.


## Live projected standings

The leaderboard defaults to **Live projections**, with **Final results** available separately. Projections combine settled season points with the current against-the-spread outcome of each saved pick on an in-progress published game: covering earns a projected 1 point, pushing earns 0.5, and trailing earns 0. Rank arrows compare that projected rank with the final-results rank. Standings and the scoreboard’s side leaderboard update automatically; changed scores, points, and ranks receive a brief highlight. Reduced-motion preferences are respected.

Only started games reported as in progress affect projections. Scheduled games never reveal another member’s picks through projected points or live-pick counts. Final games settle into official points and stop contributing live points, so they are not counted twice. Canceled/void games do not contribute. Ties share a rank, and calculations include all published games in the selected season across weeks. Only saved picks count; an unsaved selection is never used to calculate the league’s standings. If a game locks before a local change is submitted, the saved server pick wins.

Updates use polling rather than a streaming feed: roughly 15 seconds between score checks plus up to 5 seconds for the browser refresh, in addition to provider/network delay. The last successful feed-check timestamp is shown; a feed without a successful check for 60 seconds is labeled delayed, and a connection failure keeps the last standings visible. Hidden tabs pause polling and refresh when visible again. The implementation uses the existing server/database and requires no additional AWS service. Live CSV exports label final, live, and projected points separately.

## Watching games on the cards

Game cards now show larger live scores and the feed’s current quarter/clock, including halftime and overtime labels. When available in the public scoreboard feed, cards also show possession, down and distance, field position, red-zone status, timeouts, and last-play text. TV network and venue details are included when supplied. The clock is a feed snapshot, not a locally simulated countdown; optional play-by-play coverage varies by game.

Each card has a saved-pick panel showing its frozen spread, current cover/trailing/push status, projected points, and margin against the spread. Final games show settled results instead. Missing scores display a dash and await a valid score rather than inventing zero. Per-game feed-check times identify delayed cards, and an incomplete live score flags the leaderboard’s projections as incomplete. The standings page also includes **Games moving the board**, with cards for in-progress games in the selected week’s published slate.


## Scoring indicators

While the page is open, a newly received score change adds a 30-second **Score update** banner with the team and point change, a brief gold card glow, and a highlight on the scoring team. The banner survives unchanged polls and expires independently of polling; screen readers receive each update once. Reduced-motion settings disable the glow. The same indicator appears on weekly picks, the scoreboard, and live-game cards under standings.

Explicit feed-reported scoring plays receive a **Scoring play** banner even if the score totals have not arrived yet, and the latest scoring-play description is highlighted. Score decreases are labeled **Score correction** rather than celebrated. Initial loads, week/season/account changes, missing-score recovery, and a final-status change alone do not create score-change notices. Notices describe when an update was received, not the exact time a play occurred; normal polling/provider delays still apply. A point delta can include multiple plays between feed updates, so it is not interpreted as a touchdown or field goal without play data.

## Correct a published spread before kickoff

In **Commissioner tools**, choose the game’s week and click **Edit** beside its home spread. Enter the corrected home line (negative for a home favorite), optionally explain the correction, and confirm the impact before updating. This works for published manual games and feed-backed games.

Existing picks remain on the same team and use the corrected spread for scoring. A visible game-card notice shows the old/new line, correction time, and optional reason so players can review or change their selection before kickoff. Corrections record the commissioner’s name and survive feed refreshes. The server rejects edits after kickoff or once a game is live/final, rejects stale editors, and limits this action to commissioners. Ordinary bulk slate updates still cannot silently change a published line.

## Invitation links and social sign-in

Commissioner tools can create a seven-day, single-use invitation link, open a prefilled text, or send an invitation email through SES. Invitation links prefill the registration code. Google and Facebook sign-up remain invitation-only; existing members connect providers from their signed-in profile to keep their account and picks. Provider buttons appear only after configuration. Email/password sign-in remains available.

Follow [account and email setup](docs/account-setup.md) for provider callback URLs, Secrets Manager settings, SES domain verification, and the one-time infrastructure/deployer update required on existing servers. Real provider authorization and email delivery require that setup; deploying code alone does not activate them.

## Password recovery and member security

Sign in → **Forgot password?** emails a 30-minute, single-use recovery link when SES is configured. No account is created, the response does not disclose membership, and a successful reset revokes all sessions and outstanding recovery links while preserving picks and roles. See [security and recovery operations](docs/security.md) for setup, limitations, and operator recovery. The public [privacy and security page](https://4thandsoul.com/privacy.html) explains implemented controls without claiming a security certification.

## Who picked whom

Each published game card has an expandable **Who picked whom** section once the game locks. It groups saved picks under each team and its published spread, marks your own name, and lists members with no saved pick. The section keeps its open state during live refreshes and appears on picks, scoreboard and standings game cards. Existing historical/disabled members remain represented, matching season standings.

The server—not the browser clock—controls disclosure. State includes only names and IDs grouped by saved side for published games at/past a known kickoff, or confirmed live/final games. Upcoming picks, unpublished games, future canceled games and games with unknown start times are excluded. Every request is restricted to the selected season/week and requires an active signed-in account. A card can briefly show a waiting message between its local kickoff lock and the next server refresh. No game’s upcoming picks or team counts are revealed early, including to commissioners through this feature.

Phone navigation reserves its own space below the page and accounts for device safe-area insets. All five navigation targets have visible text labels and full-height tap areas; save/error toasts appear above the bar.
