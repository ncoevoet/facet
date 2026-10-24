"""Strict capture walltimes; no timezone or precision inference."""
import re
from datetime import datetime


def parse_capture_date(value: str | None) -> datetime | None:
    if not isinstance(value, str):
        return None
    if re.fullmatch(r"[0-9]{4}:[0-9]{2}:[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}", value):
        fmt = "%Y:%m:%d %H:%M:%S"
    elif re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9]{2}:[0-9]{2}:[0-9]{2}", value):
        fmt = "%Y-%m-%dT%H:%M:%S" if "T" in value else "%Y-%m-%d %H:%M:%S"
    else:
        return None
    try:
        return datetime.strptime(value, fmt)
    except ValueError:
        return None


def format_capture_date(value: datetime) -> str:
    return f"{value.year:04d}:{value.month:02d}:{value.day:02d} {value.hour:02d}:{value.minute:02d}:{value.second:02d}"
