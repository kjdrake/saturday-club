"""Separate email worker so notification delivery never delays game-score polling."""
import time
from server import db
from notifications import process_one

while True:
    try:
        if process_one(db):continue
    except Exception:
        print('Notification worker temporarily unavailable.',flush=True)
    time.sleep(2)
