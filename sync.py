"""Background feed worker. Poll only weeks with selected games near kickoff."""
import time, datetime
from server import db, sync_feed, kickoff
import json
while True:
    try:
        with db() as c:
            periods=set()
            for row in c.execute('SELECT season,week,data FROM games'):
                g=json.loads(row['data'])
                if g.get('included') and g.get('status') not in ('final','void') and -86400<kickoff(g)-time.time()<86400:
                    periods.add((row['season'],row['week']))
        for season,week in periods:
            try:print(datetime.datetime.now().isoformat(),sync_feed(season,week),flush=True)
            except Exception as e:print('Feed temporarily unavailable:',type(e).__name__,flush=True)
    except Exception as e:print('Worker error:',type(e).__name__,flush=True)
    time.sleep(30)
