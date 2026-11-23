# Vulture whitelist — generated from `vulture --make-whitelist`, pruned to
# entries that are framework-registered, dynamically dispatched, test-only
# utilities, or deliberately kept API surface. Each group is commented with
# what actually uses the names. Dead entries found by the scan were deleted
# instead of whitelisted (see docs/security-review.md triage table).
#
# Usage (from repo root):
#   vulture testorchestrator/ build-scripts/vulture_whitelist.py \
#     --exclude "static/" --ignore-decorators "@*.route,@*.command,..."

# --- Flask / framework-read attributes -------------------------------------
_.permanent_session_lifetime  # Flask-Login reads this attr on the manager
_.login_view                  # Flask-Login login redirect target (attr, not call)
_.find_spec                   # importlib.abc.MetaPathFinder protocol method
SECRET_KEY                    # config.Config — read by app.config.from_object
SQLALCHEMY_DATABASE_URI       # config.Config — flask-sqlalchemy reads by name
SQLALCHEMY_TRACK_MODIFICATIONS  # config.Config — flask-sqlalchemy
SESSION_COOKIE_HTTPONLY       # config.Config — Flask session cookie flag
SESSION_COOKIE_SAMESITE       # config.Config — Flask session cookie flag
SESSION_COOKIE_SECURE         # config.Config — Flask session cookie flag
PERMANENT_SESSION_LIFETIME_HOURS  # config.Config — app reads via from_object
PREFERRED_URL_SCHEME          # config.Config — Flask URL generation
WAITRESS_LISTEN               # config.Config — waitress serve() binding
TRUSTED_PROXY_IPS             # config.Config — proxy fix allowlist
WTF_CSRF_TIME_LIMIT           # config.Config — Flask-WTF CSRF expiry
CERT_DIR                      # config.Config — TLS asset directory
ADMIN_INITIAL_PASSWORD        # config.Config — first-boot seeding
LOGIN_RATE_LIMIT_ATTEMPTS     # config.Config — login throttle setting

# --- WTForms dynamic dispatch ----------------------------------------------
confirm_password              # WTForms field — form reads attrs by name
_.validate_timezone           # WTForms calls validate_<fieldname>() dynamically

# --- SQLAlchemy event signature --------------------------------------------
connection_record             # event.listens_for(Engine,"connect") callback arg

# --- ORM columns / attributes written via setattr or serialized ------------
# (Vulture counts reads only; these are ORM writes + dict-key serialization —
# verified read in routes, templates, restore payloads or result JSON.)

# --- Buildbot adapter: result-code constants + kept API surface ------------
RESULT_SUCCESS                # Buildbot REST result code — looked up by int
RESULT_WARNINGS               # Buildbot REST result code — looked up by int
RESULT_FAILURE                # Buildbot REST result code — looked up by int
RESULT_SKIPPED                # Buildbot REST result code — looked up by int
RESULT_EXCEPTION              # Buildbot REST result code — looked up by int
RESULT_RETRY                  # Buildbot REST result code — looked up by int
RESULT_CANCELLED              # Buildbot REST result code — looked up by int
_.worker_connected            # DEFERRED: adapter API surface, no in-repo callers
_.reconfig_pidfile            # DEFERRED: adapter API surface (SIGHUP master reconfig)
_.dispatcher_builder_name     # DEFERRED: adapter API surface (SSH builder naming)

# --- Deliberate placeholder seam -------------------------------------------
NotConfiguredError            # adapters/updater.py — 17-line spec-pending stub
Adapter                       # adapters/updater.py — same placeholder seam

# --- Test-exercised utilities (callers live in tests/, scanned separately) ---
run_execution                 # dispatch entry — tests/* dispatch local runs
bundled_available             # tests/* gate bundled-git assertions
list_test_suites              # tests/test_gitsync_remote.py
export_definitions            # tests/test_gitsync_remote.py
push_export                   # tests/test_gitsync_remote.py
reset_config_cache            # tests/test_log_exports.py — test isolation
reset_stats                   # tests/test_log_exports.py — test isolation
probe_write_access            # tests/test_setup_readiness.py
_test_iface                   # tests/test_setup_readiness.py (wrap helper)
resume_from_checkpoint        # tests/test_updater.py
all_zones                     # tests/test_timezone.py — coverage bound check
cleanup_abandoned             # tests/test_authoring.py — stale-draft sweeper
LOGIN_RATE_LIMIT_WINDOW_S     # config.Config — login throttle window
not_before                    # CertInfo dataclass — rendered in network.html
not_after                     # CertInfo dataclass — rendered in network.html
fingerprint_sha256            # CertInfo dataclass — rendered in network.html
expired                       # CertInfo dataclass — rendered in network.html
days_until_expiry             # CertInfo dataclass — rendered in network.html
sans                          # CertInfo dataclass — rendered in network.html
issuer                        # CertInfo dataclass — rendered in network.html

# ORM model column assignments (execution.py/models.py): read via ORM
# queries, json serialization, restore payloads and templates — Vulture
# only counts attribute reads, so Column() declarations report as unused.
# Suppressed by name at report level rather than whitelisting ~60 columns.
_.address                     # AddressCandidate.address — read via .address
producer_tests                # ParsedRun — getattr(run, name) tuple at results.py:97
producer_failures             # ParsedRun — getattr(run, name) tuple at results.py:97
producer_errors               # ParsedRun — getattr(run, name) tuple at results.py:97
producer_skipped              # ParsedRun — getattr(run, name) tuple at results.py:97
_.partial                     # ParsedRun.partial — written + read across parse path
# framework-registered callbacks (decorator names don't match the
# ignore globs — confirmed registered, not dead)
load_user            # flask-login user_loader, __init__.py
_gates               # app.before_request gate chain, bootstrap.py
_sqlite_pragmas      # event.listens_for(Engine,"connect"), extensions.py
inject_about_context # app_context_processor, main/routes.py
