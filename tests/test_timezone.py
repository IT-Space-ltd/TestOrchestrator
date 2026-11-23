"""Per-user display time zones — preference, localized rendering,
zone-aware analytics, schedules unchanged, backup/restore.

Instants stay UTC; `users.timezone` (IANA) only affects display and
local-day bucketing for the signed-in viewer.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from testorchestrator.extensions import db
from testorchestrator.execution import (Execution, ExecutionState,
                                        Outcome, Project, Suite,
                                        TestResult)
from testorchestrator.models import AuditEvent, Role, User
from testorchestrator import usertz

from tests.conftest import login

BUDAPEST = usertz.coerce_zone("Europe/Budapest")
KOLKATA = usertz.coerce_zone("Asia/Kolkata")


# ------------------------------------------------------------- helpers


def _seed():
    p = Project(name="tz-proj")
    db.session.add(p)
    db.session.flush()
    s = Suite(project_id=p.id, name="tz-suite")
    db.session.add(s)
    db.session.flush()
    return p, s


def _ex(p, s, when_utc, outcome=Outcome.PASSED, attempt=1,
        retry_of="", role="", env=None):
    e = Execution(project_id=p.id, suite_id=s.id if s else None,
                  state=ExecutionState.COMPLETED, outcome=outcome,
                  created_by="t", role=role, environment=env)
    e.snapshot_json = json.dumps(
        {"suite_name": s.name if s else "",
         "attempt": attempt, "retry_of": retry_of})
    e.created_at = when_utc - timedelta(seconds=180)
    e.started_at = when_utc - timedelta(seconds=120)
    e.finished_at = when_utc
    db.session.add(e)
    db.session.flush()
    return e


def _result(ex, name="c1", status="passed"):
    r = TestResult(execution_id=ex.id, case_name=name,
                   case_ref=name, status=status, duration_s=1.0)
    db.session.add(r)
    return r


def _admin():
    return User.query.filter_by(username="admin").one()


# ---------------------------------------------------------- usertz core


class TestZoneHelpers:
    def test_iana_identifier_validation(self):
        assert usertz.valid_zone("Europe/Budapest")
        assert usertz.valid_zone("UTC")
        assert usertz.valid_zone("Asia/Kolkata")
        assert not usertz.valid_zone("Budapest")          # not IANA
        assert not usertz.valid_zone("UTC+2")             # fixed offset
        assert not usertz.valid_zone("Nonsense/Nowhere")
        assert not usertz.valid_zone("../../etc/passwd")
        assert not usertz.valid_zone("")

    def test_picker_lists_major_cities_only(self):
        """The suggestion list is a curated major-city set like OS
        pickers (~130 entries) — while the backend still accepts any
        valid IANA name typed in."""
        zones = usertz.picker_zones()
        assert zones[0] == "UTC"
        assert "Europe/Budapest" in zones
        assert "Asia/Kolkata" in zones
        # aliases/links and synthetic zones are filtered out
        assert "US/Eastern" not in zones
        assert not any(z.startswith(("Etc/", "US/", "GMT"))
                       for z in zones)
        # far smaller than the raw IANA db — keeps the dropdown usable
        assert 80 <= len(zones) <= 200
        assert len(zones) < len(usertz.all_zones())
        choices = usertz.tz_choices()
        assert choices[0][0] == "UTC"
        assert len(choices) == len(zones)
        # a zone absent from suggestions is still accepted on save
        assert usertz.valid_zone("Asia/Calcutta")   # legacy link name
        assert usertz.valid_zone("Pacific/Kiritimati")

    def test_picker_groups_by_region(self):
        groups = usertz.tz_choice_groups()
        names = {g for g, _ in groups}
        assert {"UTC", "Europe", "Africa", "Americas", "Asia",
                "Oceania & Pacific"} <= names
        flat = [n for _, opts in groups for n, _ in opts]
        assert flat[0] == "UTC"
        assert "Europe/Budapest" in flat

    def test_invalid_zone_falls_back_to_utc(self):
        dt = datetime(2026, 11, 22, 10, 0)
        bad = usertz.coerce_zone("Mars/Olympus")
        assert usertz.fmt_local(dt, bad).endswith("+00:00")

    def test_numeric_offset_and_no_Z(self):
        dt = datetime(2026, 11, 22, 10, 30)               # naive = UTC
        assert usertz.fmt_local(dt, BUDAPEST) == \
            "2026-11-22 11:30:00 +01:00"
        assert usertz.fmt_local(dt, KOLKATA) == \
            "2026-11-22 16:00:00 +05:30"                  # non-hour zone
        out = usertz.fmt_local(dt, usertz.UTC)
        assert out == "2026-11-22 10:30:00 +00:00"
        assert "Z" not in out

    def test_fall_back_repeated_local_time_distinct(self):
        # 2026-10-25: Budapest repeats 02:00–02:59 once (CEST→CET)
        early = datetime(2026, 10, 25, 0, 30)   # 02:30 CEST
        late = datetime(2026, 10, 25, 1, 30)    # 02:30 CET
        a = usertz.fmt_local(early, BUDAPEST)
        b = usertz.fmt_local(late, BUDAPEST)
        assert a == "2026-10-25 02:30:00 +02:00"
        assert b == "2026-10-25 02:30:00 +01:00"
        assert a != b            # repeated local time, distinct output

    def test_spring_forward_gap(self):
        # 2026-03-29: Budapest skips 02:00–02:59 (CET→CEST)
        before = datetime(2026, 3, 29, 0, 59)   # 01:59 CET
        after = datetime(2026, 3, 29, 1, 0)     # 03:00 CEST
        assert usertz.fmt_local(before, BUDAPEST).endswith("+01:00")
        assert usertz.fmt_local(after, BUDAPEST) == \
            "2026-03-29 03:00:00 +02:00"

    def test_local_day_bounds_dst(self):
        # local 2026-11-22 in Budapest = 23:00 UTC 21st → 23:00 UTC 22nd
        lo, hi = usertz.local_day_bounds("2026-11-22", "2026-11-22",
                                         BUDAPEST)
        assert lo == datetime(2026, 11, 21, 23, 0, tzinfo=timezone.utc)
        assert hi == datetime(2026, 11, 22, 23, 0, tzinfo=timezone.utc)
        # UTC zone — identical to previous behaviour
        ulo, uhi = usertz.local_day_bounds("2026-11-22", "2026-11-22",
                                           usertz.UTC)
        assert ulo == datetime(2026, 11, 22, 0, 0,
                               tzinfo=timezone.utc)
        assert uhi == datetime(2026, 11, 23, 0, 0,
                               tzinfo=timezone.utc)


# ------------------------------------------------------ preference CRUD


class TestPreference:
    def test_existing_users_default_utc(self, app):
        with app.app_context():
            assert _admin().timezone == "UTC"

    def test_admin_create_user_with_zone(self, app, client):
        login(client, "admin")
        r = client.post("/system/users", data={
            "username": "tzuser", "display_name": "",
            "role": "tester", "timezone": "Europe/Budapest",
            "temporary_password": "Temporary-12345",
        }, follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            u = User.query.filter_by(username="tzuser").one()
            assert u.timezone == "Europe/Budapest"

    def test_admin_create_user_invalid_zone_rejected(self, app, client):
        login(client, "admin")
        r = client.post("/system/users", data={
            "username": "badzone", "display_name": "",
            "role": "tester", "timezone": "Nowhere/Fake",
            "temporary_password": "Temporary-12345",
        }, follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            assert User.query.filter_by(username="badzone").first() \
                is None

    def test_admin_edits_other_user_zone(self, app, client):
        login(client, "admin")
        with app.app_context():
            target = User.query.filter_by(username="tester").one()
            uid = target.id
            target.set_assigned_projects(["pA"])
            db.session.commit()
        r = client.post(f"/system/users/{uid}/timezone",
                        data={"timezone": "Asia/Kolkata"},
                        follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            u = db.session.get(User, uid)
            assert u.timezone == "Asia/Kolkata"
            # role + membership untouched
            assert u.role == Role.TESTER
            assert u.assigned_project_ids() == ["pA"]
            ev = AuditEvent.query.filter_by(
                event="user.timezone").order_by(
                AuditEvent.id.desc()).first()
            assert ev and "UTC -> Asia/Kolkata" in (ev.detail or "")

    def test_users_list_inline_save_redirects_back(self, app, client):
        """The per-row selector on the Users list saves and returns
        to the list (next=users), with the saved zone selected."""
        login(client, "admin")
        with app.app_context():
            uid = User.query.filter_by(username="tester").one().id
        r = client.get("/system/users")
        assert f'id="tz-{uid}"'.encode() in r.data   # per-row select
        r = client.post(f"/system/users/{uid}/timezone",
                        data={"timezone": "Asia/Kolkata",
                              "next": "users"})
        assert r.status_code == 302
        assert r.headers["Location"].endswith("/system/users")
        with app.app_context():
            assert db.session.get(User, uid).timezone == "Asia/Kolkata"
        r = client.get("/system/users")
        assert b'value="Asia/Kolkata"\n            selected' in r.data \
            or b'value="Asia/Kolkata" selected' in r.data

    def test_admin_edit_invalid_zone_warns_and_keeps_old(
            self, app, client):
        login(client, "admin")
        with app.app_context():
            uid = User.query.filter_by(username="tester").one().id
        client.post(f"/system/users/{uid}/timezone",
                    data={"timezone": "Bogus/Zone"},
                    follow_redirects=True)
        with app.app_context():
            assert db.session.get(User, uid).timezone == "UTC"

    def test_non_admin_cannot_edit_others(self, app, client):
        login(client, "tester")
        with app.app_context():
            uid = User.query.filter_by(username="po").one().id
        r = client.post(f"/system/users/{uid}/timezone",
                        data={"timezone": "Asia/Kolkata"})
        assert r.status_code in (302, 403)
        with app.app_context():
            assert db.session.get(User, uid).timezone == "UTC"

    def test_self_service_account(self, app, client):
        login(client, "tester")
        r = client.get("/account")
        assert r.status_code == 200
        assert b'<select name="timezone"' in r.data  # grouped picker
        assert b"optgroup" in r.data
        assert b"tz-detected" in r.data         # suggestion script
        r = client.post("/account", data={"timezone": "Europe/Budapest"},
                        follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            u = User.query.filter_by(username="tester").one()
            assert u.timezone == "Europe/Budapest"
            ev = AuditEvent.query.filter_by(event="user.timezone") \
                .order_by(AuditEvent.id.desc()).first()
            assert ev and "self:" in (ev.detail or "")

    def test_self_service_invalid_zone_rejected(self, app, client):
        login(client, "tester")
        client.post("/account", data={"timezone": "Not/AZone"},
                    follow_redirects=True)
        with app.app_context():
            assert User.query.filter_by(
                username="tester").one().timezone == "UTC"


# ------------------------------------------------- display localization


class TestDisplay:
    def test_jinja_filters_use_viewer_zone(self, app, client):
        login(client, "tester")
        with app.app_context():
            u = User.query.filter_by(username="tester").one()
            u.timezone = "Europe/Budapest"
            db.session.commit()
            p, s = _seed()
            u.set_assigned_projects([p.id])
            e = _ex(p, s, datetime(2026, 11, 22, 0, 30))
            e.created_at = datetime(2026, 11, 22, 0, 30)
            db.session.commit()
        r = client.get("/executions")
        assert r.status_code == 200
        # 00:30 UTC = 01:30 CET — the list shows local time + offset
        assert b"01:30 +01:00" in r.data

    def test_two_users_different_zones_same_event(self, app, client):
        with app.app_context():
            p, s = _seed()
            e = _ex(p, s, datetime(2026, 11, 22, 0, 30))
            e.created_at = datetime(2026, 11, 22, 0, 30)
            db.session.commit()
            pid = p.id
        login(client, "tester")
        with app.app_context():
            u = User.query.filter_by(username="tester").one()
            u.timezone = "Europe/Budapest"
            u.set_assigned_projects([pid])
            db.session.commit()
        r = client.get("/executions")
        assert b"01:30 +01:00" in r.data
        login(client, "admin")   # stays UTC (default)
        r = client.get("/executions")
        assert b"00:30 +00:00" in r.data

    def test_audit_page_localizes(self, app, client):
        login(client, "admin")
        with app.app_context():
            ev = AuditEvent(username="admin", event="t.ev",
                            detail="x")
            ev.occurred_at = datetime(2026, 11, 22, 0, 30)
            db.session.add(ev)
            User.query.filter_by(username="admin").one() \
                .timezone = "Asia/Kolkata"
            db.session.commit()
        r = client.get("/system/audit")
        assert b"06:00:00 +05:30" in r.data


# ------------------------------------------------- analytics zone-aware


class TestAnalyticsZones:
    """Group A/B counting policies unchanged — only the calendar the
    buckets are drawn on shifts."""

    def test_day_bucket_follows_viewer_zone(self, app):
        from testorchestrator import analytics
        with app.app_context():
            p, s = _seed()
            # finishes 23:30 UTC — 00:30 next day in Budapest
            _ex(p, s, datetime.now(timezone.utc).replace(
                hour=23, minute=30, second=0, microsecond=0))
            db.session.commit()
            u = _admin()
            utc_data = analytics.main_analytics(u, 30,
                                                tz=usertz.UTC)
            bp_data = analytics.main_analytics(u, 30, tz=BUDAPEST)
            assert utc_data["timezone"] == "UTC"
            assert bp_data["timezone"] == "Europe/Budapest"
            uday = utc_data["queue_wait"][0]["day"] if \
                utc_data["queue_wait"] else None
            bday = bp_data["queue_wait"][0]["day"] if \
                bp_data["queue_wait"] else None
            if uday and bday:
                # the run's enqueue at ~23:25 UTC sits on different
                # local days for the two viewers
                from datetime import date
                assert (date.fromisoformat(bday)
                        - date.fromisoformat(uday)).days == 1
            # first-vs-final assigns the cohort to the first
            # attempt's finish day — also viewer-local
            u_ff = {r["day"] for r in utc_data["first_final"]}
            b_ff = {r["day"] for r in bp_data["first_final"]}
            if u_ff and b_ff:
                from datetime import date
                assert (min(date.fromisoformat(d) for d in b_ff)
                        - min(date.fromisoformat(d)
                              for d in u_ff)).days == 1

    def test_activity_heatmap_local_weekday_hour(self, app):
        from testorchestrator import analytics
        with app.app_context():
            p, s = _seed()
            # 2026-11-22 is a Sunday; 23:30 UTC Sun → 00:30 Mon in
            # Budapest
            e = _ex(p, s, datetime(2026, 11, 22, 23, 30))
            e.created_at = datetime(2026, 11, 22, 23, 25)
            e.started_at = datetime(2026, 11, 22, 23, 28)
            db.session.commit()
            u = _admin()
            sub_u = analytics.main_analytics(
                u, 30, tz=usertz.UTC)["activity_submitted"]
            sub_b = analytics.main_analytics(
                u, 30, tz=BUDAPEST)["activity_submitted"]
            assert sub_u == [{"dow": 6, "hour": 23, "count": 1}]
            assert sub_b == [{"dow": 0, "hour": 0, "count": 1}]

    def test_executions_date_filter_local_day(self, app, client):
        with app.app_context():
            p, s = _seed()
            # created 23:30 UTC on Nov 21 = 00:30 Nov 22 in Budapest
            e = _ex(p, s, datetime(2026, 11, 22, 0, 30))
            e.created_at = datetime(2026, 11, 21, 23, 30)
            db.session.commit()
            eid, pid = e.id, p.id
        login(client, "tester")
        with app.app_context():
            u = User.query.filter_by(username="tester").one()
            u.timezone = "Europe/Budapest"
            # tester needs membership
            u.set_assigned_projects([pid])
            db.session.commit()
        # local Nov 22 in Budapest covers 23:00 UTC Nov 21 onward
        r = client.get("/executions?from_date=2026-11-22"
                       "&to_date=2026-11-22")
        assert eid[:8].encode() in r.data
        r = client.get("/executions?from_date=2026-11-21"
                       "&to_date=2026-11-21")
        assert eid[:8].encode() not in r.data

    def test_activity_drill_matches_local_cell(self, app, client):
        """The dow/hour drill cohort must equal the local-zone cell —
        same conversion as the heatmap, not UTC."""
        with app.app_context():
            p, s = _seed()
            e = _ex(p, s, datetime(2026, 11, 22, 23, 30))
            e.created_at = datetime(2026, 11, 22, 23, 25)
            db.session.commit()
            eid, pid = e.id, p.id
        login(client, "tester")
        with app.app_context():
            u = User.query.filter_by(username="tester").one()
            u.timezone = "Europe/Budapest"
            u.set_assigned_projects([pid])
            db.session.commit()
        # Budapest cell: Monday hour 0
        r = client.get("/executions?activity=submitted&dow=0&hour=0")
        assert eid[:8].encode() in r.data
        # UTC-bucket cell (Sunday 23) must NOT match a Budapest viewer
        r = client.get("/executions?activity=submitted&dow=6&hour=23")
        assert eid[:8].encode() not in r.data

    def test_csv_identifies_zone(self, app, client):
        with app.app_context():
            p, s = _seed()
            _ex(p, s, datetime(2026, 11, 20, 12, 0))
            db.session.commit()
        login(client, "admin")
        r = client.get("/dashboard/analytics?format=csv"
                       "&chart=first_final&days=400")
        assert r.status_code == 200
        assert r.data.decode().splitlines()[0].endswith(",tz")
        with app.app_context():
            User.query.filter_by(username="admin").one() \
                .timezone = "Europe/Budapest"
            db.session.commit()
        r = client.get("/dashboard/analytics?format=csv"
                       "&chart=first_final&days=400")
        assert "Europe/Budapest" in r.data.decode()

    def test_freshness_csv_utc_plus_local(self, app, client):
        with app.app_context():
            p, s = _seed()
            e = _ex(p, s, datetime(2026, 11, 20, 12, 0))
            _result(e)
            db.session.commit()
            pid = p.id
        login(client, "admin")
        r = client.get(f"/projects/{pid}/analytics?format=csv"
                       "&chart=evidence_freshness")
        assert r.status_code == 200
        head = r.data.decode().splitlines()[0]
        assert "last_finished_at_utc" in head
        assert "last_finished_at_local" in head


# ------------------------------------------------------------- schedules


class TestSchedulesUnchanged:
    def test_preference_does_not_move_schedule(self, app, client):
        from testorchestrator.execution import Schedule
        with app.app_context():
            p, s = _seed()
            when = datetime(2030, 1, 1, 12, 0)          # UTC instant
            sch = Schedule(project_id=p.id, name="sch",
                           target_type="suite", suite_id=s.id,
                           kind="once", next_run_at=when,
                           enabled=True)
            db.session.add(sch)
            db.session.commit()
            pid, sid = p.id, sch.id
            stored = db.session.get(Schedule, sid).next_run_at
        login(client, "tester")
        with app.app_context():
            u = User.query.filter_by(username="tester").one()
            u.timezone = "Asia/Kolkata"
            u.set_assigned_projects([pid])
            db.session.commit()
        r = client.get(f"/projects/{pid}")
        assert r.status_code == 200
        # 12:00 UTC = 17:30 IST — displayed localized…
        assert b"17:30 +05:30" in r.data
        with app.app_context():
            # …but the stored fire instant did not move
            assert db.session.get(Schedule, sid).next_run_at == \
                stored

    def test_schedule_form_keeps_utc_semantics(self, app, client):
        with app.app_context():
            p, s = _seed()
            db.session.commit()
            pid = p.id
        login(client, "test_manager")
        with app.app_context():
            u = User.query.filter_by(username="test_manager").one()
            u.timezone = "Europe/Budapest"
            u.set_assigned_projects([pid])
            db.session.commit()
        r = client.get(f"/projects/{pid}")
        # editing form discloses execution zone = UTC, display zone
        # differs
        assert b"fires at the entered UTC instant" in r.data


# ------------------------------------------------------------- CSV export


class TestLogExportZone:
    def test_export_csv_has_local_columns(self, app, client):
        from testorchestrator import logexport
        with app.app_context():
            ev = AuditEvent(username="admin", event="t.x", detail="")
            ev.occurred_at = datetime(2026, 11, 22, 0, 30)
            db.session.add(ev)
            db.session.commit()
            q = logexport.audit_query({})
            rows = "".join(logexport.csv_lines(
                "audit", q, datetime.now(timezone.utc),
                tz_name="Asia/Kolkata"))
            head = rows.splitlines()[0]
            assert "timestamp_utc" in head
            assert "timestamp_local" in head
            assert "timezone" in head
            body = rows.splitlines()[1]
            assert "+05:30" in body
            assert "Asia/Kolkata" in body


# ------------------------------------------------------------ migration


class TestMigration:
    def test_upgrade_populates_utc_default(self, tmp_path):
        """Alembic path: a pre-column DB gains users.timezone='UTC'."""
        import sqlalchemy as sa
        from pathlib import Path
        from tests.conftest import make_app
        mig = str(Path(__file__).resolve().parent.parent
                  / "migrations")

        def _upgrade(app, rev="head"):
            with app.app_context():
                from flask_migrate import upgrade
                upgrade(directory=mig, revision=rev)

        app = make_app(tmp_path, "tz-upg.db")
        # schema comes from migrations only — never create_all
        _upgrade(app, "a9b0c1d2e3f4")          # parent revision
        eng = sa.create_engine(
            f"sqlite:///{tmp_path / 'tz-upg.db'}")
        with eng.begin() as c:
            c.execute(sa.text(
                "INSERT INTO users (username, display_name,"
                " password_hash, role, is_active,"
                " must_change_password, session_version,"
                " allowed_projects, created_at) VALUES"
                " ('pre','', 'x','admin',1,0,1,'[]',"
                " '2026-01-01 00:00:00')"))
        _upgrade(app)                          # → head incl. ours
        with eng.connect() as c:
            val = c.execute(sa.text(
                "SELECT timezone FROM users WHERE"
                " username='pre'")).scalar()
        assert val == "UTC"


# ------------------------------------------------- backup and restore


PASS = "backup-passphrase-12345"


class TestBackupRestore:
    def test_timezone_roundtrips_through_backup(self, app):
        from testorchestrator import backup as bk
        with app.app_context():
            u = User.query.filter_by(username="tester").one()
            u.timezone = "Europe/Budapest"
            db.session.commit()
            payload = bk.decrypt_backup(
                bk.create_backup(app, PASS), PASS)
            tzrow = [r for r in payload["sections"]["users"]
                     if r["username"] == "tester"][0]
            assert tzrow["timezone"] == "Europe/Budapest"

    def test_invalid_restored_zone_warns_and_falls_back(self, app):
        from testorchestrator import backup as bk
        with app.app_context():
            payload = bk.decrypt_backup(
                bk.create_backup(app, PASS), PASS)
            for r in payload["sections"]["users"]:
                if r["username"] == "tester":
                    r["timezone"] = "Bad/Zone"
            report = bk.apply_restore(app, payload, "replace",
                                      "admin")
            u = User.query.filter_by(username="tester").one()
            assert u.timezone == "UTC"
            assert any("invalid time zone" in a
                       for a in report["attention"])

    def test_older_backup_without_zone_defaults_utc(self, app):
        from testorchestrator import backup as bk
        with app.app_context():
            payload = bk.decrypt_backup(
                bk.create_backup(app, PASS), PASS)
            for r in payload["sections"]["users"]:
                r.pop("timezone", None)     # simulate 2.5-era backup
            report = bk.apply_restore(app, payload, "replace",
                                      "admin")
            for u in User.query.all():
                assert u.timezone == "UTC"
            assert not any("time zone" in a
                           for a in report["attention"])
