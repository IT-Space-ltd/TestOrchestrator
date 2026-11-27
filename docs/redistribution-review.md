# Redistribution review — Buildbot stack in TestOrchestrator 2.7.0

Prepared for the approval gate `TO_BUILDBOT_GPL_APPROVED`. No
customer distribution before this plan is approved; the flag stays
unset until then.

## 1. Code boundary — how TestOrchestrator and Buildbot interact

The products run as **separate processes under separate Python
environments**, communicating only over documented wire protocols:

```
portal process (app venv)                buildbot master (buildbot-venv)
  testorchestrator/                        buildbot 4.3.0
    adapters/buildbot.py ──HTTP/REST──▶ :8010 loopback only
    dispatch.py ───────────┐
                           │ buildrequest + exec_spec (JSON)
buildbot workers (buildbot-venv / remote venv)
  to-local, to-ssh-dispatcher, remote workers ──PB/TCP :9989──▶ master
    worker executes shell steps; for SSH targets it invokes
    to_ssh_exec.py (TO source) as a subprocess
```

Boundary facts:

- The portal **never imports or links** Buildbot code — `adapters/
  buildbot.py` speaks the public REST API (`api/v2`) over loopback;
  Buildbot's own UI/API stay bound to `127.0.0.1`.
- Workers communicate with the master over PB (Perspective Broker,
  TCP 9989) with per-worker passwords — a documented inter-process
  protocol, not in-process API use.
- `paramiko` is used by `to_ssh_exec.py`/`ssh_check.py` — TestOrchestrator
  code invoked **as a subprocess** by the worker. No paramiko code is
  imported into the portal process either (it lives in buildbot-venv).
- No Buildbot source is modified, patched, or vendored-with-changes —
  we ship **verbatim upstream wheels**.

This is an aggregate-of-separate-programs posture: distinct
processes, distinct interpreter environments, wire-protocol IPC —
not a combined/derived work in the GPL sense. The obligations below
still apply to the Buildbot/paramiko packages themselves on
redistribution, which is what this review covers.

## 2. What ships in each artifact

| Artifact | Buildbot/paramiko content | Notes |
|---|---|---|
| `testorchestrator-<version>-linux-x86_64.tar.gz` / `.run` | `3rdparty/buildbot-wheels/` — pinned upstream wheels: `buildbot==4.3.0` (+ `[bundled]` extras), `buildbot-worker==4.3.0`, `buildbot-www==4.3.0`, `paramiko==3.5.1` + resolved dependencies | install.py builds `payload/buildbot-venv` offline from these wheels; master + `to-local` + `to-ssh-dispatcher` run from it |
| `testorchestrator-<version>-windows-amd64-setup-UNSIGNED.exe` | embedded `buildbot-py` runtime with the same Buildbot 4.3.0/paramiko 3.5.1 stack, plus the bundled remote-worker installer and corresponding-source archive | full Windows controller; the Buildbot processes remain separate from the portal process |
| `TestOrchestrator-Buildbot-Worker-Setup-4.3.0-UNSIGNED.exe` (inside the controller packages, served by the portal) | embedded Python runtime + `buildbot-worker==4.3.0` wheel + deps + `setup-worker.py` bootstrap | offline install on the remote Windows host; no controller, no KRE, no credentials inside |
| `TestOrchestrator-Buildbot-Worker-4.3.0-linux-x86_64.tar.gz` / `install_linux_worker.sh` | offline `bb-wheels/` closure for `buildbot-worker==4.3.0` | runs on the remote Linux host; the script itself is TO code |
| App payload/portal virtualenv | **no** Buildbot code — the portal venv contains none of these packages | `paramiko` is absent from the portal process environment; it belongs to the Buildbot runtime |

## 3. Licenses of the bundled packages

Copyleft-covered packages — these drive the corresponding-source and
license-text obligations:

| Package | Version in the final 2.7.0 build | License | Redistribution duties |
|---|---|---|---|
| `buildbot` | 4.3.0 | **GPL-2.0** (COPYING in dist-info) | license text + copyright + corresponding source |
| `buildbot-worker` | 4.3.0 | **GPL-2.0** | same |
| `buildbot-www` | 4.3.0 | **GPL-2.0** (classifier; Buildbot project-wide) | same |
| `paramiko` | 3.5.1 | **LGPL** (upstream metadata/license text shipped) | license text + source offer + no-TPM note (unmodified wheel — replacement/relinking remains possible) |

Resolved dependency inventory in the final Linux controller wheel set
(each wheel is verbatim upstream; its license text is extracted into
`3rdparty/licenses/`):

| Package | Version | License family |
|---|---|---|
| alembic | 1.20.1 | MIT |
| attrs | 26.1.0 | MIT |
| autobahn | 26.11.2 | MIT |
| Automat | 25.4.16 | MIT |
| bcrypt | 5.0.0 | Apache-2.0 |
| cbor2 | 6.3.0 | MIT |
| cffi | 2.1.1 | MIT-0 |
| constantly | 23.10.4 | MIT |
| croniter | 7.0.0 | MIT |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause |
| hyperlink | 21.0.0 | MIT |
| idna | 3.20 | BSD-3-Clause |
| Incremental | 24.11.0 | MIT |
| Jinja2 | 3.1.6 | BSD |
| Mako | 1.4.3 | MIT |
| MarkupSafe | 3.0.4 | BSD-3-Clause |
| msgpack | 1.2.4 | Apache-2.0 |
| multipart | 2.0.1 | MIT |
| packaging | 26.4 | Apache-2.0 OR BSD-2-Clause |
| pycparser | 3.12 | BSD-3-Clause |
| PyJWT | 2.15.1 | MIT |
| PyNaCl | 1.6.2 | Apache-2.0 |
| pyOpenSSL | 26.4.0 | Apache-2.0 |
| python-dateutil | 4.0.0 | BSD-3-Clause |
| PyYAML | 6.0.4 | MIT |
| service-identity | 26.1.0 | MIT |
| setuptools | 84.2.1 | MIT |
| SQLAlchemy | 2.1.9 | MIT |
| treq | 26.7.0 | MIT |
| Twisted | 26.10.0 | MIT |
| txaio | 26.6.1 | MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |
| tzdata | 2026.6 | Apache-2.0 |
| ujson | 6.1.0 | BSD-3-Clause AND TCL |
| unidiff | 1.0.1 | MIT |
| zope.interface | 8.7 | ZPL-2.1 |

## 4. Notices and corresponding-source delivery — as implemented

**Primary route: GPLv2 §3(a) — source accompanies the binaries.**

- `build_corresponding_sources()` (build-scripts/_common.py) emits
  `TestOrchestrator-Buildbot-Sources-<ver>.tar.gz`: sdists of the
  GPL/LGPL-covered packages (`buildbot`, `buildbot-worker`,
  `buildbot-www`, `paramiko` — `--no-binary` source distributions,
  no-deps) + `build-and-install/` (provision_buildbot.py, master.cfg,
  install_linux_worker.sh, setup-worker.py, the NSIS script) +
  `CORRESPONDING-SOURCES.txt`. It is published **beside the
  controller package** and copied into `packaging/windows/` where
  the Admin UI serves it **next to the worker .exe download**
  (`system.buildbot_sources_download` + a Source link on the
  download card).
- License texts are extracted from every staged wheel into
  `3rdparty/licenses/` (controller bundle) and into
  `bb-worker-payload/licenses/` (inside the .exe) — notices travel
  with both artifacts.

**Residual route: GPLv2 §3(b) written offer** — retained only for
copies distributed *without* the archive (e.g., a customer shares
the .exe onward, or an ad-hoc transfer). `CORRESPONDING-SOURCES.txt`
carries the offer; **fulfillment owner: IT-Space Kft. — the support
contact published with the product (About page / Admin Manual)**.
Terms per GPLv2: valid ≥3 years, to any third party, at no more
than the physical cost of source distribution. The offer names the
published support channel — the release must not ship without that
contact present.

**Boundary remains as §1** — no linking, no modified sources; the
§3(a) archive makes verification direct (no upstream-link reliance).

**Inventory verification** (`validate_package.py`): asserts the
worker .exe, the controller wheels dir incl. `buildbot-www`, and —
added with this change — the sources archive + license files.
The .exe payload additionally carries embed-Python + pywin32 +
the resolved win_amd64 wheels; the review of the actual staged
artifacts happens at RC-build time per docs/acceptance-2.5.0.md.

## 5. Approval checklist

Owner approval recorded in the 2.7.0 release session on 2026-11-27, and explicitly reconfirmed after this inventory was corrected to the final Buildbot 4.3.0 / paramiko 3.5.1 package set.

- [x] Confirm the separate-process/wire-protocol boundary is the
      intended posture (it is — no linking, no modified sources)
- [x] Accept the GPLv2 §3(a) accompanying-source route (archive ships
      beside every binary offer) with the §3(b) written offer retained
      only as residual for onward copies
- [x] Approve notice files above
- [x] Then: `TO_BUILDBOT_GPL_APPROVED=1` for the final clean build only
