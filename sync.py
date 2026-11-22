"""Background feed worker. Poll only weeks with selected games near kickoff."""
import time, datetime, subprocess, sys, signal
from pathlib import Path
from server import db, sync_feed, kickoff, SCORE_REFRESH_SECONDS
import json
def stop_worker(signum, frame):
    raise SystemExit(0)

if __name__=='__main__':
    signal.signal(signal.SIGTERM,stop_worker)
    email_worker=None
    try:
        while True:
            if email_worker is None or email_worker.poll() is not None:
                email_worker=subprocess.Popen([sys.executable,str(Path(__file__).with_name('notify.py'))])
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
            time.sleep(SCORE_REFRESH_SECONDS)
    finally:
        if email_worker is not None:
            email_worker.terminate()
            try:email_worker.wait(timeout=5)
            except subprocess.TimeoutExpired:
                email_worker.kill();email_worker.wait()
