"""Refresh the public ESPN school directory and cache logos for the chosen weeks.
Run from the repository: python infra/fetch_team_logos.py --season 2026 --weeks 11 12 13
"""
import argparse
import concurrent.futures
import datetime
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]

def fetch_json(url):
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.load(response)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--season', type=int, default=datetime.datetime.now().year)
    parser.add_argument('--weeks', type=int, nargs='+', default=[11, 12, 13])
    args = parser.parse_args()
    base = 'https://site.api.espn.com/apis/site/v2/sports/football/college-football/'
    directory = fetch_json(base + 'teams?limit=1000')['sports'][0]['leagues'][0]['teams']
    ids = set()
    for week in args.weeks:
        feed = fetch_json(base + f'scoreboard?groups=80&limit=200&dates={args.season}&seasontype=2&week={week}')
        ids.update(team['team']['id'] for event in feed.get('events', [])
                   for competition in event['competitions'] for team in competition['competitors'])
    folder = ROOT / 'dist/assets/team-logos'
    folder.mkdir(parents=True, exist_ok=True)
    def download(team_id):
        try:
            with urllib.request.urlopen(f'https://a.espncdn.com/i/teamlogos/ncaa/500/{team_id}.png', timeout=20) as response:
                data = response.read()
            if not data.startswith(b'\x89PNG'):
                return False
            (folder / (team_id + '.png')).write_bytes(data)
            return True
        except (OSError, ValueError):
            return False
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        cached = sum(pool.map(download, sorted(ids)))
    teams = []
    for entry in directory:
        team = entry['team']; team_id = team['id']
        teams.append({'id': team_id, 'name': team['displayName'],
                      'aliases': list(dict.fromkeys(team[key] for key in
                          ['displayName', 'shortDisplayName', 'location', 'abbreviation', 'name'] if team.get(key))),
                      'logo': f'assets/team-logos/{team_id}.png' if (folder / (team_id + '.png')).exists()
                          else f'https://a.espncdn.com/i/teamlogos/ncaa/500/{team_id}.png'})
    (ROOT / 'dist/teams.js').write_text('window.COLLEGE_TEAMS = ' + json.dumps(teams, separators=(',', ':')) + ';\n')
    print(f'Cached {cached}/{len(ids)} logos; indexed {len(teams)} schools. Missing logos use the public CDN or an abbreviation fallback.')

if __name__ == '__main__':
    main()
