"""Per-user time-zone display helpers.

Event instants stay stored and exchanged in UTC; this module is the
single place that converts them for display using the signed-in
user's saved IANA zone (`users.timezone`, default "UTC").

Rules enforced here:
- Naive datetimes are treated as UTC (SQLite returns naive values).
- Localized strings carry a NUMERIC UTC offset (+01:00) so repeated
  local clock times around fall-back stay distinguishable; a `Z`
  suffix is never produced for localized output.
- An invalid/unavailable zone identifier NEVER raises for display —
  it falls back to UTC (restore safety net lives in backup.py).
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, available_timezones

UTC = ZoneInfo("UTC")
FALLBACK = "UTC"

# Cached zone list — the IANA db is static per process.
_ALL_ZONES: list[str] | None = None


def all_zones() -> list[str]:
    global _ALL_ZONES
    if _ALL_ZONES is None:
        _ALL_ZONES = sorted(available_timezones())
    return _ALL_ZONES


# Primary-zone list for the picker: zone1970.tab is the table OS
# installers (Linux/Windows-style pickers) use — one IANA zone per
# region, without alias/backward-compat duplicates. The datalist still
# accepts ANY valid IANA name typed in (validated server-side), so
# nothing becomes unreachable — the suggestions are just curated.
_FALLBACK_PRIMARY = [
    "Pacific/Midway", "America/Anchorage", "America/Los_Angeles",
    "America/Denver", "America/Chicago", "America/New_York",
    "America/Toronto", "America/Mexico_City", "America/Bogota",
    "America/Santiago", "America/Sao_Paulo", "America/Argentina/Buenos_Aires",
    "Atlantic/Azores", "UTC", "Europe/London", "Europe/Lisbon",
    "Europe/Dublin", "Europe/Paris", "Europe/Madrid", "Europe/Berlin",
    "Europe/Rome", "Europe/Warsaw", "Europe/Prague", "Europe/Vienna",
    "Europe/Budapest", "Europe/Stockholm", "Europe/Oslo",
    "Europe/Copenhagen", "Europe/Amsterdam", "Europe/Brussels",
    "Europe/Zurich", "Europe/Helsinki", "Europe/Athens",
    "Europe/Bucharest", "Europe/Sofia", "Europe/Kyiv", "Europe/Istanbul",
    "Europe/Moscow", "Africa/Cairo", "Africa/Johannesburg",
    "Africa/Lagos", "Africa/Nairobi", "Asia/Jerusalem", "Asia/Riyadh",
    "Asia/Dubai", "Asia/Tehran", "Asia/Karachi", "Asia/Kolkata",
    "Asia/Dhaka", "Asia/Bangkok", "Asia/Jakarta", "Asia/Shanghai",
    "Asia/Singapore", "Asia/Hong_Kong", "Asia/Taipei", "Asia/Tokyo",
    "Asia/Seoul", "Australia/Perth", "Australia/Sydney",
    "Australia/Melbourne", "Australia/Brisbane", "Pacific/Auckland",
    "Pacific/Fiji", "Pacific/Honolulu",
]

_PRIMARY_ZONES: list[str] | None = None


def _zone1970_tab_paths() -> list[str]:
    import os
    from zoneinfo import TZPATH
    paths = [os.path.join(d, "zone1970.tab") for d in TZPATH]
    try:
        import tzdata
        paths.append(os.path.join(os.path.dirname(tzdata.__file__),
                                  "zoneinfo", "zone1970.tab"))
    except Exception:
        pass
    return paths


def primary_zones() -> list[str]:
    """Curated IANA primary zones (zone1970.tab — the same source OS
    time-zone pickers consume). UTC first; ~300 entries vs ~600 raw.
    Falls back to a compact built-in list if the file is missing."""
    global _PRIMARY_ZONES
    if _PRIMARY_ZONES is not None:
        return _PRIMARY_ZONES
    names: set[str] = {"UTC"}
    for path in _zone1970_tab_paths():
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("#") or not line.strip():
                        continue
                    parts = line.split("\t")
                    if len(parts) >= 3:
                        names.add(parts[2].strip())
            break                                   # first file wins
        except OSError:
            continue
    if len(names) <= 1:                             # file unavailable
        names = set(_FALLBACK_PRIMARY)
    _PRIMARY_ZONES = sorted(n for n in names if valid_zone(n))
    return _PRIMARY_ZONES


def valid_zone(name: str) -> bool:
    """True iff `name` is a loadable IANA identifier on this host."""
    if not name or len(name) > 64:
        return False
    try:
        ZoneInfo(name)
        return True
    except Exception:
        return False


def coerce_zone(name: str) -> ZoneInfo:
    """ZoneInfo for `name`; invalid/empty → UTC (never raises)."""
    try:
        return ZoneInfo(name) if name else UTC
    except Exception:
        return UTC


def user_zone(user) -> ZoneInfo:
    """The user's display zone; missing column/invalid → UTC."""
    return coerce_zone(getattr(user, "timezone", None) or FALLBACK)


def zone_name(user) -> str:
    return getattr(user, "timezone", None) or FALLBACK


def _aware_utc(dt):
    if dt is None:
        return None
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except ValueError:
            return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def to_local(dt, tz: ZoneInfo):
    aware = _aware_utc(dt)
    return aware.astimezone(tz) if aware is not None else None


def _offset_str(dt_local) -> str:
    off = dt_local.utcoffset()
    if off is None:
        return "+00:00"
    total = int(off.total_seconds())
    sign = "+" if total >= 0 else "-"
    total = abs(total)
    return f"{sign}{total // 3600:02d}:{(total % 3600) // 60:02d}"


def offset_label(tz: ZoneInfo, at: datetime | None = None) -> str:
    """'UTC+01:00' for the zone's offset at `at` (default: now)."""
    at = at or datetime.now(timezone.utc)
    return "UTC" + _offset_str(at.astimezone(tz))


def fmt_local(dt, tz: ZoneInfo, seconds: bool = True) -> str:
    """'2026-11-22 14:30:05 +01:00' — the detailed, offset-bearing
    display form. Returns '' for missing values."""
    local = to_local(dt, tz)
    if local is None:
        return ""
    base = local.strftime("%Y-%m-%d %H:%M:%S" if seconds
                          else "%Y-%m-%d %H:%M")
    return f"{base} {_offset_str(local)}"


def fmt_local_date(dt, tz: ZoneInfo) -> str:
    local = to_local(dt, tz)
    return local.strftime("%Y-%m-%d") if local is not None else ""


def local_day(dt, tz: ZoneInfo) -> str:
    """Local calendar day key — analytics bucketing."""
    return fmt_local_date(dt, tz)


def utc_iso(dt) -> str:
    """Machine/canonical form — aware-UTC ISO-8601 ('...+00:00')."""
    aware = _aware_utc(dt)
    return aware.isoformat() if aware is not None else ""


def tz_choices(now: datetime | None = None) -> list[tuple[str, str]]:
    """(iana_name, 'Name (UTC+01:00 now — varies by date)') choices.

    UTC is listed first; offsets are the CURRENT offset — the label
    discloses that the offset changes with the date (DST)."""
    now = now or datetime.now(timezone.utc)
    out = [("UTC", "UTC (UTC+00:00)")]
    for name in primary_zones():
        if name == "UTC":
            continue
        try:
            off = offset_label(ZoneInfo(name), now)
        except Exception:
            continue
        out.append((name, f"{name} ({off} now — varies by date)"))
    return out


# ------------------------------------------------------------ requests


def request_tz():
    """Display zone of the signed-in user for the current request;
    UTC when unauthenticated or unavailable."""
    try:
        from flask_login import current_user
        if current_user is not None and current_user.is_authenticated:
            return user_zone(current_user)
    except Exception:
        pass
    return UTC


def request_tz_name() -> str:
    try:
        from flask_login import current_user
        if current_user is not None and current_user.is_authenticated:
            return zone_name(current_user)
    except Exception:
        pass
    return FALLBACK


def local_day_bounds(day_from, day_to, tz: ZoneInfo):
    """(utc_lo, utc_hi) instants bounding the local calendar-day
    interval [day_from, day_to] — None bounds stay None. `day_*` are
    'YYYY-MM-DD' strings or date objects."""
    lo = hi = None
    if day_from is not None:
        d = (day_from if not isinstance(day_from, str)
             else datetime.strptime(day_from, "%Y-%m-%d").date())
        lo = datetime(d.year, d.month, d.day, tzinfo=tz) \
            .astimezone(timezone.utc)
    if day_to is not None:
        d = (day_to if not isinstance(day_to, str)
             else datetime.strptime(day_to, "%Y-%m-%d").date())
        from datetime import timedelta
        n = d + timedelta(days=1)     # next LOCAL midnight (DST-safe)
        hi = datetime(n.year, n.month, n.day, tzinfo=tz) \
            .astimezone(timezone.utc)
    return lo, hi
