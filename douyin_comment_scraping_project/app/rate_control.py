
from __future__ import annotations
import random
import time

def polite_wait(base: float = 0.8, jitter: float = 0.6):
    time.sleep(base + random.random() * jitter)
