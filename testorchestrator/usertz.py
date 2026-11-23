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

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

log = logging.getLogger(__name__)

try:
    UTC = ZoneInfo("UTC")
except ZoneInfoNotFoundError:  # no zone database installed on this host
    UTC = timezone.utc
    log.warning("zoneinfo database unavailable — all timestamps "
                "display as UTC until tzdata is present")

FALLBACK = "UTC"

# Cached zone list — the IANA db is static per process.
_ALL_ZONES: list[str] | None = None


def all_zones() -> list[str]:
    global _ALL_ZONES
    if _ALL_ZONES is None:
        try:
            _ALL_ZONES = sorted(available_timezones())
        except Exception:
            log.warning("zoneinfo database unavailable — zone list empty")
            _ALL_ZONES = []
    return _ALL_ZONES


# Picker suggestion list — the "main cities" set OS time-zone pickers
# offer (Windows ~135 entries). Any valid IANA name typed into the
# field is still accepted and validated server-side, so nothing
# becomes unreachable — the suggestions are convenience, not a fence.
_MAJOR_ZONES = [
    "UTC",
    # Europe / Atlantic
    "Atlantic/Azores", "Europe/London", "Europe/Dublin", "Europe/Lisbon",
    "Europe/Reykjavik", "Europe/Paris", "Europe/Madrid", "Europe/Berlin",
    "Europe/Rome", "Europe/Amsterdam", "Europe/Brussels",
    "Europe/Luxembourg", "Europe/Monaco", "Europe/Zurich",
    "Europe/Vienna", "Europe/Prague", "Europe/Warsaw",
    "Europe/Bratislava", "Europe/Budapest", "Europe/Zagreb",
    "Europe/Ljubljana", "Europe/Belgrade", "Europe/Sarajevo",
    "Europe/Podgorica", "Europe/Tirane", "Europe/Skopje",
    "Europe/Malta", "Europe/Gibraltar", "Europe/Andorra",
    "Europe/Stockholm", "Europe/Oslo", "Europe/Copenhagen",
    "Europe/Helsinki", "Europe/Tallinn", "Europe/Riga",
    "Europe/Vilnius", "Europe/Kaliningrad", "Europe/Minsk",
    "Europe/Kyiv", "Europe/Chisinau", "Europe/Bucharest",
    "Europe/Sofia", "Europe/Athens", "Europe/Istanbul",
    "Europe/Moscow", "Europe/Volgograd", "Europe/Samara",
    # Africa
    "Africa/Casablanca", "Africa/Algiers", "Africa/Tunis",
    "Africa/Tripoli", "Africa/Cairo", "Africa/Khartoum",
    "Africa/Lagos", "Africa/Accra", "Africa/Dakar",
    "Africa/Kinshasa", "Africa/Luanda", "Africa/Nairobi",
    "Africa/Dar_es_Salaam", "Africa/Addis_Ababa",
    "Africa/Johannesburg", "Africa/Harare", "Africa/Maputo",
    # Americas
    "Pacific/Honolulu", "America/Anchorage", "America/Los_Angeles",
    "America/Tijuana", "America/Phoenix", "America/Denver",
    "America/Chicago", "America/Mexico_City", "America/Guatemala",
    "America/New_York", "America/Toronto", "America/Winnipeg",
    "America/Halifax", "America/St_Johns", "America/Havana",
    "America/Panama", "America/Bogota", "America/Lima",
    "America/Quito", "America/Caracas", "America/La_Paz",
    "America/Santiago", "America/Asuncion", "America/Sao_Paulo",
    "America/Argentina/Buenos_Aires", "America/Montevideo",
    "America/Georgetown", "America/Puerto_Rico",
    # Asia
    "Asia/Jerusalem", "Asia/Beirut", "Asia/Amman", "Asia/Baghdad",
    "Asia/Riyadh", "Asia/Kuwait", "Asia/Dubai", "Asia/Muscat",
    "Asia/Tehran", "Asia/Baku", "Asia/Yerevan", "Asia/Tbilisi",
    "Asia/Kabul", "Asia/Karachi", "Asia/Kolkata", "Asia/Colombo",
    "Asia/Kathmandu", "Asia/Dhaka", "Asia/Almaty", "Asia/Tashkent",
    "Asia/Bishkek", "Asia/Yangon", "Asia/Bangkok", "Asia/Jakarta",
    "Asia/Kuala_Lumpur", "Asia/Singapore", "Asia/Manila",
    "Asia/Hong_Kong", "Asia/Shanghai", "Asia/Taipei", "Asia/Macau",
    "Asia/Ulaanbaatar", "Asia/Seoul", "Asia/Tokyo",
    "Asia/Vladivostok", "Asia/Novosibirsk", "Asia/Yekaterinburg",
    # Oceania / Pacific
    "Australia/Perth", "Australia/Darwin", "Australia/Adelaide",
    "Australia/Brisbane", "Australia/Sydney", "Australia/Melbourne",
    "Australia/Hobart", "Pacific/Auckland", "Pacific/Fiji",
    "Pacific/Guam", "Pacific/Port_Moresby", "Pacific/Noumea",
    "Pacific/Tahiti", "Pacific/Midway",
]

_MAJOR_ZONE_LIST: list[str] | None = None


def picker_zones() -> list[str]:
    """Curated major-city IANA zones for the picker — UTC first,
    sorted after it. Entries that fail to load on this host are
    dropped (e.g. renamed zones on very old tzdata)."""
    global _MAJOR_ZONE_LIST
    if _MAJOR_ZONE_LIST is None:
        rest = sorted(z for z in _MAJOR_ZONES if z != "UTC"
                      and valid_zone(z))
        _MAJOR_ZONE_LIST = ["UTC", *rest]
    return _MAJOR_ZONE_LIST


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
    """ZoneInfo for `name`; invalid/empty/unloadable → UTC with a
    logged diagnostic (never raises)."""
    try:
        return ZoneInfo(name) if name else UTC
    except ZoneInfoNotFoundError:
        log.warning("time zone %r not loadable (identifier unknown or "
                    "tz database missing) — displaying UTC instead",
                    name)
        return UTC
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


def tz_choices(now: datetime | None = None) -> list[
        tuple[str, str, str]]:
    """(iana_name, full_label, short_label) choices.

    Labels lead with the CITY name ("Budapest — Europe/Budapest
    (UTC+01:00 now — varies by date)") so the native <select>
    type-ahead — which matches from the start of the option text —
    finds a zone by the city users actually type. Offsets are the
    CURRENT offset; the label discloses that the offset changes
    with the date (DST). UTC is listed first."""
    now = now or datetime.now(timezone.utc)
    out = [("UTC", "UTC (UTC+00:00)", "UTC")]
    for name in picker_zones():
        if name == "UTC":
            continue
        try:
            off = offset_label(ZoneInfo(name), now)
        except Exception:
            continue
        city = name.rsplit("/", 1)[-1].replace("_", " ")
        out.append((name, f"{city} — {name} ({off} now "
                          f"— varies by date)",
                    f"{city} — {name}"))
    return out


_REGION_LABELS = {
    "Africa": "Africa", "America": "Americas", "Antarctica": "Polar",
    "Arctic": "Polar", "Asia": "Asia", "Atlantic": "Atlantic",
    "Australia": "Oceania & Pacific", "Europe": "Europe",
    "Indian": "Indian Ocean", "Pacific": "Oceania & Pacific",
}


def tz_choice_groups(now: datetime | None = None
                     ) -> list[tuple[str, list[tuple[str, str]]]]:
    """Picker options grouped by world region — drives the <select>
    optgroups so the list behaves like an OS time-zone picker."""
    flat = tz_choices(now)
    groups: dict[str, list[tuple[str, str]]] = {"UTC": []}
    for row in flat:
        name = row[0]
        if name == "UTC":
            groups["UTC"].append(row)
            continue
        region = _REGION_LABELS.get(name.split("/", 1)[0], "Other")
        groups.setdefault(region, []).append(row)
    order = ["UTC", "Europe", "Africa", "Americas", "Asia",
             "Atlantic", "Indian Ocean", "Oceania & Pacific",
             "Polar", "Other"]
    return [(g, groups[g]) for g in order if groups.get(g)]


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
