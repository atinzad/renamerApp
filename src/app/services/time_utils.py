from __future__ import annotations

from datetime import datetime


def now_local_iso() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def local_date_yyyy_mm_dd(dt_iso_or_datetime: datetime | str | None) -> str:
    if isinstance(dt_iso_or_datetime, datetime):
        local_date = (
            dt_iso_or_datetime.astimezone().date()
            if dt_iso_or_datetime.tzinfo
            else dt_iso_or_datetime.date()
        )
        return local_date.isoformat()
    if isinstance(dt_iso_or_datetime, str):
        try:
            parsed = datetime.fromisoformat(dt_iso_or_datetime)
            local_date = parsed.astimezone().date() if parsed.tzinfo else parsed.date()
            return local_date.isoformat()
        except ValueError:
            pass
    return datetime.now().astimezone().date().isoformat()
