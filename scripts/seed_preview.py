#!/usr/bin/env python3
"""Seed the disposable preview instance (127.0.0.1:39995) used by the
live-browser tests. Wipes and re-creates TO_INSTANCE_DIR content —
NEVER point this at a real instance.

Usage:
  TO_INSTANCE_DIR=/tmp/to-preview-data python scripts/seed_preview.py
  TO_INSTANCE_DIR=/tmp/to-preview-data python -m waitress --listen=127.0.0.1:39995 wsgi:app
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def main():
    inst = os.environ.get("TO_INSTANCE_DIR", "")
    if not inst or "preview" not in inst:
        sys.exit("refusing: TO_INSTANCE_DIR must be a disposable preview dir")
    dbpath = os.path.join(inst, "testorchestrator.db")
    if os.path.exists(dbpath):
        os.remove(dbpath)
    os.makedirs(inst, exist_ok=True)

    from testorchestrator import create_app
    from testorchestrator.extensions import db
    app = create_app()
    with app.app_context():
        from flask_migrate import upgrade
        upgrade()
        from testorchestrator.execution import Runner
        from testorchestrator.models import User, Role
        if not User.query.filter_by(username="Admin").first():
            u = User(username="Admin", display_name="Preview Admin",
                     role=Role.ADMIN)
            u.set_password("Review-Preview-#2026!")
            db.session.add(u)
        # Fixed-id project the modal browser tests navigate to —
        # without it they skip or fail on missing modal triggers.
        from testorchestrator.execution import Project
        PROJ = "62d2f3e1b4654e5680fd187795c454f7"
        if not db.session.get(Project, PROJ):
            db.session.add(Project(
                id=PROJ, name="Preview-Project",
                description="seeded project for the live browser tests"))
        # authoring-enabled binding — the suite/collection modal triggers
        # render only when can_author (an authoring_writable binding exists)
        from testorchestrator.execution import GitBinding
        if not GitBinding.query.filter_by(project_id=PROJ).first():
            db.session.add(GitBinding(
                project_id=PROJ, name="preview-binding",
                url="https://example.invalid/preview/repo.git",
                ref="main", authoring_writable=True,
                report_writable=True))
        for rid in ("rem-1", "rem-2"):
            if not db.session.get(Runner, rid):
                db.session.add(Runner(
                    id=rid, name=rid,
                    description="seeded remote runner for browser tests",
                    connection_mode="remote",
                    os_arch="linux-x86_64",
                    workspace_root="/tmp",
                    max_slots=2))
        db.session.commit()
        print("seeded: Admin user + rem-1/rem-2 runners")

if __name__ == "__main__":
    main()
