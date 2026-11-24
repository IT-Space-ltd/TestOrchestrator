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

# --- Post-2.5.x ORM columns / serialized attrs (added after the    ---
# --- original whitelist; verified read via routes, queries or      ---
# --- serializers — same FP class as FP-*. verified_capabilities    ---
# --- deliberately NOT whitelisted: dead column, see DEFER-3.       ---
_.rerun  # unused attribute (testorchestrator/adapters/reporting_labs.py:119)
_.end  # unused attribute (testorchestrator/adapters/reporting_labs.py:134)
_.end  # unused attribute (testorchestrator/adapters/reporting_labs.py:168)
_.end  # unused attribute (testorchestrator/adapters/reporting_labs.py:198)
_.last_used_at  # unused attribute (testorchestrator/api/routes.py:75)
_.published_sha  # unused attribute (testorchestrator/authoring.py:297)
_.check_status  # unused attribute (testorchestrator/backup.py:504)
_.check_error  # unused attribute (testorchestrator/backup.py:505)
_.check_at  # unused attribute (testorchestrator/backup.py:506)
_.git_state  # unused attribute (testorchestrator/dispatch.py:1641)
_.git_state  # unused attribute (testorchestrator/dispatch.py:1643)
_.git_state  # unused attribute (testorchestrator/dispatch.py:1645)
_.processed_at  # unused attribute (testorchestrator/dispatch.py:1669)
_.last_error  # unused attribute (testorchestrator/dispatch.py:1672)
_.last_run_at  # unused attribute (testorchestrator/dispatch.py:2442)
discovery_status  # unused variable (testorchestrator/execution.py:60)
discovery_at  # unused variable (testorchestrator/execution.py:62)
discovery_error  # unused variable (testorchestrator/execution.py:63)
project_root  # unused variable (testorchestrator/execution.py:65)
last_error  # unused variable (testorchestrator/execution.py:68)
imported  # unused variable (testorchestrator/execution.py:83)
parallelism  # unused variable (testorchestrator/execution.py:111)
sync_binding_id  # unused variable (testorchestrator/execution.py:146)
synced_sha  # unused variable (testorchestrator/execution.py:148)
sync_dirty  # unused variable (testorchestrator/execution.py:149)
last_run_at  # unused variable (testorchestrator/execution.py:201)
tags  # unused variable (testorchestrator/execution.py:232)
capabilities  # unused variable (testorchestrator/execution.py:233)
agent_token_hash  # unused variable (testorchestrator/execution.py:255)
agent_version  # unused variable (testorchestrator/execution.py:256)
agent_capabilities  # unused variable (testorchestrator/execution.py:257)
check_status  # unused variable (testorchestrator/execution.py:286)
check_error  # unused variable (testorchestrator/execution.py:287)
check_at  # unused variable (testorchestrator/execution.py:288)
last_check_at  # unused variable (testorchestrator/execution.py:311)
PENDING  # unused variable (testorchestrator/execution.py:365)
AMBIGUOUS  # unused variable (testorchestrator/execution.py:368)
git_state  # unused variable (testorchestrator/execution.py:416)
report_pub_repo  # unused variable (testorchestrator/execution.py:486)
report_pub_sha  # unused variable (testorchestrator/execution.py:489)
report_pub_error  # unused variable (testorchestrator/execution.py:491)
deletion_error  # unused variable (testorchestrator/execution.py:496)
result_format  # unused variable (testorchestrator/execution.py:508)
imported_at  # unused variable (testorchestrator/execution.py:510)
imported_by  # unused variable (testorchestrator/execution.py:511)
source_repo  # unused variable (testorchestrator/execution.py:522)
source_commit  # unused variable (testorchestrator/execution.py:523)
source_path  # unused variable (testorchestrator/execution.py:524)
schedule  # unused variable (testorchestrator/execution.py:529)
resource_kind  # unused variable (testorchestrator/execution.py:562)
slot_index  # unused variable (testorchestrator/execution.py:563)
quantity  # unused variable (testorchestrator/execution.py:564)
acquired_at  # unused variable (testorchestrator/execution.py:565)
ERROR  # unused variable (testorchestrator/execution.py:575)
SKIPPED  # unused variable (testorchestrator/execution.py:576)
suite_entry_order  # unused variable (testorchestrator/execution.py:587)
collected_at  # unused variable (testorchestrator/execution.py:621)
last_error  # unused variable (testorchestrator/execution.py:636)
processed_at  # unused variable (testorchestrator/execution.py:639)
token_hash  # unused variable (testorchestrator/execution.py:687)
last_used_at  # unused variable (testorchestrator/execution.py:696)
order_idx  # unused variable (testorchestrator/execution.py:749)
seq  # unused variable (testorchestrator/execution.py:798)
imported_execution_id  # unused variable (testorchestrator/execution.py:815)
claimed_by  # unused variable (testorchestrator/execution.py:840)
published_sha  # unused variable (testorchestrator/execution.py:867)
updated_at  # unused variable (testorchestrator/execution.py:870)
_.context  # unused attribute (testorchestrator/frontend.py:181)
_.context  # unused attribute (testorchestrator/frontend.py:221)
_.last_error  # unused attribute (testorchestrator/gitsync.py:98)
_.last_error  # unused attribute (testorchestrator/gitsync.py:104)
_.discovery_status  # unused attribute (testorchestrator/gitsync.py:488)
_.discovery_status  # unused attribute (testorchestrator/gitsync.py:495)
_.discovery_error  # unused attribute (testorchestrator/gitsync.py:496)
_.discovery_at  # unused attribute (testorchestrator/gitsync.py:497)
_.project_root  # unused attribute (testorchestrator/gitsync.py:498)
_.discovery_status  # unused attribute (testorchestrator/gitsync.py:504)
_.discovery_error  # unused attribute (testorchestrator/gitsync.py:505)
_.report_pub_error  # unused attribute (testorchestrator/gitsync.py:586)
_.report_pub_error  # unused attribute (testorchestrator/gitsync.py:599)
_.report_pub_error  # unused attribute (testorchestrator/gitsync.py:606)
_.report_pub_error  # unused attribute (testorchestrator/gitsync.py:652)
_.report_pub_repo  # unused attribute (testorchestrator/gitsync.py:656)
_.report_pub_sha  # unused attribute (testorchestrator/gitsync.py:659)
_.report_pub_error  # unused attribute (testorchestrator/gitsync.py:661)
_.report_pub_error  # unused attribute (testorchestrator/gitsync.py:666)
_.deletion_error  # unused attribute (testorchestrator/gitsync.py:692)
_.deletion_error  # unused attribute (testorchestrator/gitsync.py:701)
_.deletion_error  # unused attribute (testorchestrator/gitsync.py:725)
_.deletion_error  # unused attribute (testorchestrator/gitsync.py:736)
_.imported_execution_id  # unused attribute (testorchestrator/importer.py:923)
_.imported_execution_id  # unused attribute (testorchestrator/importer.py:929)
_.imported_execution_id  # unused attribute (testorchestrator/importer.py:936)
_.imported_execution_id  # unused attribute (testorchestrator/importer.py:956)
forbidden  # unused function (testorchestrator/main/routes.py:432)
not_found  # unused function (testorchestrator/main/routes.py:438)
_.sync_binding_id  # unused attribute (testorchestrator/portal/routes.py:1950)
_.synced_sha  # unused attribute (testorchestrator/portal/routes.py:1952)
_.sync_dirty  # unused attribute (testorchestrator/portal/routes.py:1954)
_.sync_dirty  # unused attribute (testorchestrator/portal/routes.py:1978)
_.sync_dirty  # unused attribute (testorchestrator/portal/routes.py:1996)
_.sync_dirty  # unused attribute (testorchestrator/portal/routes.py:2036)
_.sync_dirty  # unused attribute (testorchestrator/portal/routes.py:2113)
_.last_check_at  # unused attribute (testorchestrator/runner_readiness.py:109)
_.last_check_at  # unused attribute (testorchestrator/runner_readiness.py:222)
_.check_at  # unused attribute (testorchestrator/system/routes.py:1699)
_.check_error  # unused attribute (testorchestrator/system/routes.py:1701)
_.check_status  # unused attribute (testorchestrator/system/routes.py:1701)
_.check_error  # unused attribute (testorchestrator/system/routes.py:1710)
_.check_status  # unused attribute (testorchestrator/system/routes.py:1710)
_.check_error  # unused attribute (testorchestrator/system/routes.py:1715)
_.check_status  # unused attribute (testorchestrator/system/routes.py:1715)
_.check_status  # unused attribute (testorchestrator/system/routes.py:1720)
_.check_error  # unused attribute (testorchestrator/system/routes.py:1721)
_.check_error  # unused attribute (testorchestrator/system/routes.py:1735)
_.check_status  # unused attribute (testorchestrator/system/routes.py:1735)
_.check_status  # unused attribute (testorchestrator/system/routes.py:1739)
_.check_error  # unused attribute (testorchestrator/system/routes.py:1740)
_.check_error  # unused attribute (testorchestrator/system/routes.py:1750)
_.check_error  # unused attribute (testorchestrator/system/routes.py:1790)
_.check_status  # unused attribute (testorchestrator/system/routes.py:1790)
_.check_at  # unused attribute (testorchestrator/system/routes.py:1791)
_.last_check_at  # unused attribute (testorchestrator/system/routes.py:1932)
_.last_check_at  # unused attribute (testorchestrator/system/routes.py:1938)
_.check_status  # unused attribute (testorchestrator/system/routes.py:2041)
_.check_error  # unused attribute (testorchestrator/system/routes.py:2042)
_.last_check_at  # unused attribute (testorchestrator/system/routes.py:2052)
_.last_check_at  # unused attribute (testorchestrator/system/routes.py:2098)
