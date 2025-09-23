import random
import time

import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; DataCleanBot/1.0; +https://example.com/bot)"
}


def get_html(url, timeout=10.0, retry=2):
    for i in range(retry + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            if 200 <= r.status_code < 300:
                r.encoding = r.apparent_encoding or "utf-8"
                return r.text
        except requests.RequestException:
            pass
        time.sleep(0.5 + random.random() * 0.8)
    return None
