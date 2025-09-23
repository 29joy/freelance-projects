from datetime import datetime, timezone


def utc_date():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def utc_datetime_minute():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M")
