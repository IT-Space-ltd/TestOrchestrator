#!/usr/bin/env python3
"""Merge installer env wiring and install-unique secrets (installer step).

systemd/NSIS write the deterministic TO_* wiring; the values that must be
unique per installation — TO_SECRET_KEY (session signing) and
TO_INSTALL_ID — are generated here with the embedded interpreter because
neither service manager can produce secrets itself. Idempotent: existing
keys are preserved so reruns/upgrades never invalidate live sessions or
the install identity.

Usage: init_env.py --env-file <path> [--merge-file <path>]
"""

import argparse
import secrets
from pathlib import Path

GENERATED = (
    ("TO_SECRET_KEY", lambda: secrets.token_hex(24)),
    ("TO_INSTALL_ID", lambda: secrets.token_hex(12)),
)


def _parse(text):
    rows = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, _, val = stripped.partition("=")
            rows.append((key.strip(), val.strip(), True))
        else:
            rows.append((line, "", False))
    return rows


def _render(rows):
    return "\n".join(
        f"{key}={val}" if is_kv else key for key, val, is_kv in rows
    ) + "\n"


def merge_env(env_path: Path, merge_path: Path) -> None:
    existing = _parse(env_path.read_text(encoding="utf-8")) \
        if env_path.exists() else []
    incoming = _parse(merge_path.read_text(encoding="utf-8"))
    rows = list(existing)
    positions = {key: i for i, (key, _val, is_kv) in enumerate(rows)
                 if is_kv}
    for key, val, is_kv in incoming:
        if not is_kv:
            continue
        if key in positions:
            rows[positions[key]] = (key, val, True)
        else:
            positions[key] = len(rows)
            rows.append((key, val, True))
    env_path.write_text(_render(rows), encoding="utf-8")


def ensure(env_path: Path) -> list:
    text = env_path.read_text(encoding="utf-8") \
        if env_path.exists() else ""
    added = []
    for key, gen in GENERATED:
        if f"{key}=" in text:
            continue
        if text and not text.endswith("\n"):
            text += "\n"
        text += f"{key}={gen()}\n"
        added.append(key)
    env_path.write_text(text, encoding="utf-8")
    return added


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", required=True)
    ap.add_argument("--merge-file")
    a = ap.parse_args(argv)
    env_path = Path(a.env_file)
    if a.merge_file:
        merge_env(env_path, Path(a.merge_file))
    added = ensure(env_path)
    print(f"[init_env] {env_path}: "
          + (", ".join(added) if added else "secrets preserved"))


if __name__ == "__main__":
    main()
