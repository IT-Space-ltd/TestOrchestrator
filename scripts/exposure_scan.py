#!/usr/bin/env python3
"""Fixed-string exposure scan — pre-sign-off gate.

Scans the final artifacts, docs, manuals and evidence for the exposed
licensed key string. Hit count must be zero.

The key is NEVER embedded in this script or the repo. Provide it via
a file outside version control:

  python3 scripts/exposure_scan.py --key-file /path/outside/repo/key.txt \
      dist/testorchestrator-2.7.0-linux-x86_64.tar.gz \
      docs Manuals-Doc GATE-LEDGER-2.7.0.md

Archives are scanned member by member (text members only, plus a
shallow binary scan for the literal bytes). Output is hit counts per
path — never the key, never surrounding content.
"""
import argparse
import io
import os
import sys
import tarfile

def scan_bytes(name, data, needle, hits):
    if needle in data:
        hits.append(name)

def scan_path(path, needle, hits):
    if os.path.isfile(path):
        if tarfile.is_tarfile(path):
            with tarfile.open(path) as tf:
                for m in tf.getmembers():
                    if not m.isfile() or m.size > 200_000_000:
                        continue
                    f = tf.extractfile(m)
                    if f is None:
                        continue
                    scan_bytes(f"{path}!{m.name}", f.read(), needle, hits)
        else:
            with open(path, "rb") as fh:
                scan_bytes(path, fh.read(), needle, hits)
    elif os.path.isdir(path):
        for root, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
            for fn in files:
                scan_path(os.path.join(root, fn), needle, hits)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key-file", required=True,
                    help="file containing ONLY the exposed key string")
    ap.add_argument("paths", nargs="+")
    args = ap.parse_args()

    needle = open(args.key_file, "rb").read().strip()
    if len(needle) < 8:
        sys.exit("key file looks wrong (too short) — refusing")
    hits = []
    for p in args.paths:
        scan_path(p, needle, hits)
    print(f"scanned {len(args.paths)} path(s); hits: {len(hits)}")
    for h in hits[:20]:
        print(" HIT:", h)
    sys.exit(1 if hits else 0)

if __name__ == "__main__":
    main()
