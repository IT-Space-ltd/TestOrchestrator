# UI acceptance suite (Playwright) — test tooling, not product code

Runs the browser flows against an **installed** package. Isolated venv
only — never inside the product runtime.

## Setup (in the test VM or any host that can reach the portal)

    python3.12 -m venv /tmp/pw-venv
    /tmp/pw-venv/bin/pip install -r requirements.txt
    /tmp/pw-venv/bin/playwright install --with-deps chromium firefox

## Run

    cd tests/e2e-ui
    /tmp/pw-venv/bin/python -m pytest . -v \
        --browser chromium --browser firefox \
        --screenshot only-on-failure --tracing retain-on-failure \
        --output /tmp/to-ui-artifacts

## Point at another install (e.g. the Windows controller)

    TO_UI_BASE_URL=https://win-host.example:8443 \
    TO_UI_ADMIN_USER=Admin TO_UI_BOOTSTRAP_PW='Admin' \
    TO_UI_ADMIN_PW='Throwaway-Only-1!' \
    /tmp/pw-venv/bin/python -m pytest tests/e2e-ui -v

- `TO_UI_BASE_URL` — portal HTTPS URL (default https://localhost).
- `TO_UI_BOOTSTRAP_PW` — bootstrap credential on a fresh install.
- `TO_UI_ADMIN_PW` — throwaway replacement; never a real password.
- `TO_UI_ADMIN_USER` — admin username (default `Admin`).
- `TO_UI_STATE_DIR` — saved-login-state dir (default `/tmp/to-ui-state`).
- Traces/screenshots capture page content: keep artifacts out of git,
  use throwaway credentials only, delete artifacts after triage.
- infra seeding (runner/runtime/item) is test DATA via app internals;
  all *user actions* go through the browser only.
- Known deferred defect (not a failure): the invisible keyboard-focus
  indicator (accessibility) is tracked separately.
