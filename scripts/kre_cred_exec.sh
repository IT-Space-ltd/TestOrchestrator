#!/bin/sh
# to-kre-launcher: v2-sh
# Worker-side KRE credential resolver + output scrubber (POSIX).
#
# Staged by TestOrchestrator onto the execution target and invoked by
# the execution spec instead of the raw KRE executable:
#     sh .to_kre_cred_exec.sh <credential-file> <katalonc> [kre-args...]
#
# Runs under plain POSIX sh — no python/python3 requirement on the
# target (sh is the same shell the SSH run wrapper and the Buildbot
# pidfile wrapper already require).
#
# Security contract:
#   - The spec carries this script's path and the credential FILE
#     PATH — never the secret value.
#   - The file must be a regular non-symlink file owned by the
#     invoking account with no group/other permission bits, and must
#     contain a narrowly-shaped token ([A-Za-z0-9_-]{1,128}).
#   - The credential is passed to KRE as -apiKey=<value> — it appears
#     in KRE's argv on the target (documented, same-account-visible
#     only), never printed by this launcher.
#   - KRE's merged stdout/stderr is scrubbed through awk — which
#     reads the key from the credential file itself, so the value is
#     in no process argv, env, or temp file — before output reaches
#     step capture; redaction happens at the source, not on collect.
#   - KRE runs in THIS launcher's process group. Both kill paths —
#     Buildbot's step killpg (TERM-then-KILL) and the SSH driver's
#     group kill — target the launcher's group; a setsid'ed KRE would
#     escape both and strand a licensed run as an orphan.
#   - A pre-supplied -apiKey is rejected: exactly one credential
#     source. Usage/validation failures exit 3 with a
#     "kre_cred_exec:" marker for controller-side classification.

fail() { echo "kre_cred_exec: $*" >&2; exit 3; }

if [ "$#" -lt 2 ]; then
    echo "usage: kre_cred_exec <credential-file> <katalonc> [kre-args...]" >&2
    exit 3
fi
cred=$1; shift
exe=$1; shift

for a in "$@"; do
    case "$a" in
        -apiKey|-apiKey=*)
            fail "conflicting credential source: -apiKey already supplied";;
    esac
done

# Path contract: an absolute path (operator-placed target file), or
# the per-run delivered form ../<relpath> — the FileDownload artifact
# lands in the prep-created restricted drop dir .to_cred/ at the
# builddir root (exec workdir is build/src). After stripping the
# leading ../ the remainder must be a clean relative path: no bare
# name rejection needed, but no interior .., no leading /.
case "$cred" in
    /*) ;;
    ../*)
        rest=$cred
        while :; do
            case "$rest" in ../*) rest=${rest#../};; *) break;; esac
        done
        case "$rest" in
            ""|.|..|/*|../*|*/../*|*/..)
                fail "credential file path must be absolute";;
        esac;;
    *) fail "credential file path must be absolute";;
esac

# Confinement (KRE_CRED_DIR): the resolved real parent directory must
# live under the permitted directory — same realpath contract as the
# original resolver, via pwd -P (no realpath dependency).
if [ -n "${KRE_CRED_DIR:-}" ]; then
    conf=$(cd -P -- "$KRE_CRED_DIR" 2>/dev/null && pwd -P) \
        || conf=$KRE_CRED_DIR
    rp=$(cd -P -- "$(dirname -- "$cred")" 2>/dev/null && pwd -P) \
        || fail "credential file unreadable"
    real=$rp/$(basename -- "$cred")
    case "$real" in
        "$conf"/*) ;;
        *) fail "credential file outside permitted directory";;
    esac
fi

[ -L "$cred" ] && fail "credential file unreadable"
[ -f "$cred" ] || fail "credential file unreadable"
[ -r "$cred" ] || fail "credential file unreadable"
mode=$(stat -c '%a' "$cred" 2>/dev/null || stat -f '%Lp' "$cred" 2>/dev/null)
uid=$(stat -c '%u' "$cred" 2>/dev/null || stat -f '%u' "$cred" 2>/dev/null)
[ -n "$mode" ] && [ -n "$uid" ] || fail "cannot stat credential file"
[ "$uid" = "$(id -u)" ] \
    || fail "credential file not owned by the invoking account"
case "$mode" in
    *[!0-9]*) fail "cannot determine credential file mode";;
    *00) : ;;  # last two octal digits == group/other bits
    *) fail "credential file has group/other permission bits";;
esac

key=$(tr -d '[:space:]' < "$cred") || fail "cannot read credential"
[ -n "$key" ] || fail "credential file is empty"
case "$key" in
    *[!A-Za-z0-9_-]*)
        fail "credential file contents are not a valid token shape";;
esac
[ "${#key}" -le 128 ] || fail "credential token too long"

[ -f "$exe" ] || fail "KRE executable not found at the configured path"

# Per-run delivered credentials are removed by THIS wrapper at the end
# of every run — normal exit, validation failure, TERM/INT/HUP kill
# (timeout/cancel), and controller death alike (the detached wrapper
# outlives the controller and still exits). The controller-side
# collect/kill removal and the prepare-sweep scrub are backstops only.
# NEVER removed: operator-placed files — only the per-run delivered
# forms qualify: the ../ drop-dir relative form, or a basename of
# .to_kre_cred (the per-run ssh delivery name).
case "$cred" in
    ../*|.to_kre_cred|*/.to_kre_cred) _to_delivered=1;;
    *) _to_delivered=0;;
esac
on_exit() {
    [ "$_to_delivered" = 1 ] && rm -f "$cred" 2>/dev/null
    rm -rf "$d" 2>/dev/null
}
d=
trap on_exit EXIT

# Run KRE in this launcher's process group (NO setsid — see header)
# and scrub its merged output through awk — the awk program reads
# the key from the credential file itself, so the value exists in
# no argv, env, or extra file.
d=$(mktemp -d "${TMPDIR:-/tmp}/to_kre.XXXXXX") \
    || fail "cannot create private run dir"
fifo=$d/out
mkfifo "$fifo" 2>/dev/null || { rm -rf "$d"; fail "cannot create output fifo"; }

"$exe" "$@" "-apiKey=$key" > "$fifo" 2>&1 &
pid=$!
awk -v cred="$cred" '
    BEGIN {
        k = ""
        while ((getline line < cred) > 0) {
            gsub(/[[:space:]]/, "", line); k = k line
        }
        close(cred)
    }
    {
        if (k != "") gsub(k, "***REDACTED***")
        print; fflush()
    }' < "$fifo" &
awkpid=$!

_kids() {
    # Children of $1 — pgrep when available, else a POSIX ps scan.
    if command -v pgrep >/dev/null 2>&1; then
        pgrep -P "$1" 2>/dev/null
    else
        ps -eo pid=,ppid= 2>/dev/null | awk -v p="$1" '$2==p {print $1}'
    fi
}
_killtree() {
    # Depth-first: signal leaves before parents so reparented
    # grandchildren cannot escape the sweep.
    for _k in $(_kids "$1"); do _killtree "$_k" "$2"; done
    kill -"$2" "$1" 2>/dev/null
}
on_term() {
    # A pid-directed signal reaches only this launcher — take the
    # whole child TREE (katalonc's java/sleep grandchildren), not
    # just the direct child. Group-directed kills already reached
    # the tree; the redundant signal is harmless. No `--` separator:
    # dash's kill builtin rejects it ("Illegal number").
    _killtree "$pid" TERM
    sleep 1
    _killtree "$pid" KILL
    # Bounded drain of the scrubber: a surviving writer that
    # inherited the fifo fd must not hang the trap.
    i=0
    while kill -0 "$awkpid" 2>/dev/null && [ "$i" -lt 5 ]; do
        i=$((i + 1)); sleep 1
    done
    kill -KILL "$awkpid" 2>/dev/null
    wait "$awkpid" 2>/dev/null
    rm -rf "$d"
    exit 143
}
trap on_term TERM INT HUP

wait "$pid"; rc=$?
trap - TERM INT HUP
wait "$awkpid" 2>/dev/null
rm -rf "$d"
exit "$rc"
