# to-kre-launcher: v2-ps1
# Worker-side KRE credential resolver + output scrubber (Windows).
#
# Staged by TestOrchestrator onto the execution target and invoked by
# the execution spec instead of the raw KRE executable:
#   powershell -NoProfile -ExecutionPolicy Bypass -File
#       .to_kre_cred_exec.ps1 <credential-file> <katalonc> [kre-args...]
#
# Runs under powershell.exe — the same shell the Windows Buildbot
# worker cleanup steps already require; no Python on the target.
#
# Security contract (mirrors the POSIX launcher):
#   - The spec carries script + credential FILE paths, never a value.
#   - The credential file must be a regular non-link file containing a
#     token [A-Za-z0-9_-]{1,128}; confidentiality on Windows is
#     carried by the NTFS ACL on the service-account-owned run dir.
#   - The value is passed to KRE as -apiKey=<value> — same-account-
#     visible argv exposure, documented; never printed here.
#   - Child stdout/stderr are scrubbed at the source before they
#     reach step capture.
#   - The child is placed in a kill-on-close Job Object: terminating
#     this launcher (timeout, cancel, worker kill via
#     TerminateProcess) cannot orphan the KRE process tree.
#   - A pre-supplied -apiKey is rejected. Usage/validation failures
#     exit 3 with a "kre_cred_exec:" marker.
param(
    [Parameter(Position=0)][string]$CredentialFile,
    [Parameter(Position=1)][string]$KreExecutable,
    [Parameter(Position=2, ValueFromRemainingArguments=$true)]
        [string[]]$KreArgs
)

function Fail([string]$m) {
    [Console]::Error.WriteLine("kre_cred_exec: $m")
    if ($script:toDelivered -and $script:CredentialFile) {
        Remove-Item -LiteralPath $script:CredentialFile -Force -ErrorAction SilentlyContinue
    }
    exit 3
}

if (-not $CredentialFile -or -not $KreExecutable) {
    [Console]::Error.WriteLine(
        "usage: kre_cred_exec <credential-file> <katalonc> [kre-args...]")
    exit 3
}

# Delivered-file qualification is computed BEFORE any validation can
# fail so every exit path — validation failure included — can honour
# the removal contract (mirrors the POSIX EXIT trap).
$toDelivered = $false
if ($CredentialFile -like "..\*" -or
        $CredentialFile -eq ".to_kre_cred" -or
        $CredentialFile -like "*\.to_kre_cred" -or
        $CredentialFile -like "*/.to_kre_cred") {
    $toDelivered = $true
}

foreach ($a in @($KreArgs)) {
    if ($a -eq "-apiKey" -or $a -like "-apiKey=*") {
        Fail "conflicting credential source: -apiKey already supplied"
    }
}

if (-not (Test-Path -LiteralPath $CredentialFile -PathType Leaf)) {
    Fail "credential file not found: $CredentialFile"
}
$creItem = Get-Item -LiteralPath $CredentialFile -Force
if ($creItem.LinkType) {
    Fail "credential file must not be a link/junction"
}
try {
    $key = ([IO.File]::ReadAllText($CredentialFile)).Trim()
} catch {
    Fail "credential file unreadable"
}
if (-not $key) { Fail "credential file is empty" }
if ($key -notmatch '^[A-Za-z0-9_-]{1,128}$') {
    Fail "credential file contents are not a valid token shape"
}
if (-not (Test-Path -LiteralPath $KreExecutable -PathType Leaf)) {
    Fail "KRE executable not found at the configured path"
}

# Immediate-delete design (mirrors the POSIX launcher): the key is
# already in memory, so a per-run DELIVERED credential file is deleted
# BEFORE KRE launches — the on-disk window shrinks to this launcher's
# own startup, and even an untrappable hard kill (taskkill /F,
# TerminateProcess) leaves nothing behind. The scrubber key comes
# from the in-memory variable — this process IS the scrubber, so no
# descriptor handoff is needed. NEVER deleted: operator-placed files
# — only the per-run delivered forms qualify: the ..\ drop-dir
# relative form, or a basename of .to_kre_cred (the per-run delivery
# name). The finally-backstop below covers validation-failure exits
# after this point; for a hard kill nothing can run — residue then
# falls to the controller-side kill-path scrub and the prepare-time
# sweep (both implemented controller-side), same as POSIX SIGKILL.
if ($toDelivered) {
    Remove-Item -LiteralPath $CredentialFile -Force -ErrorAction SilentlyContinue
}

# CommandLineToArgvW-compatible quoting for ProcessStartInfo.Arguments
# (PS 5.1 has no ArgumentList) — argument boundaries preserved for
# paths with spaces; no shell is ever in the chain.
function Quote-Arg([string]$s) {
    if ($s.Length -gt 0 -and $s -notmatch '[ \t"\\]') { return $s }
    $b = New-Object System.Text.StringBuilder
    [void]$b.Append('"')
    $bs = 0
    foreach ($c in $s.ToCharArray()) {
        if ($c -eq '\') { $bs++; continue }
        if ($c -eq '"') {
            [void]$b.Append('\' * ($bs * 2 + 1)).Append('"')
        } else {
            [void]$b.Append('\' * $bs).Append($c)
        }
        $bs = 0
    }
    [void]$b.Append('\' * ($bs * 2)).Append('"')
    return $b.ToString()
}

$argv = @()
foreach ($a in @($KreArgs)) { $argv += (Quote-Arg $a) }
$argv += (Quote-Arg "-apiKey=$key")

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $KreExecutable
$psi.Arguments = ($argv -join ' ')
$psi.UseShellExecute = $false
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.CreateNoWindow = $true

# Kill-on-close Job Object — same contract as the python helper.
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class ToJob {
    [DllImport("kernel32.dll")]
    public static extern IntPtr CreateJobObject(IntPtr attr, string name);
    [DllImport("kernel32.dll", SetLastError=true)]
    public static extern bool SetInformationJobObject(IntPtr job,
        int infoClass, ref JOBOBJECT_EXTENDED_LIMIT_INFORMATION info,
        int len);
    [DllImport("kernel32.dll", SetLastError=true)]
    public static extern bool AssignProcessToJobObject(IntPtr job,
        IntPtr process);
    [StructLayout(LayoutKind.Sequential)]
    public struct JOBOBJECT_BASIC_LIMIT_INFORMATION {
        public long PerProcessUserTimeLimit;
        public long PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize;
        public UIntPtr MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass;
        public uint SchedulingClass;
    }
    [StructLayout(LayoutKind.Sequential)]
    public struct IO_COUNTERS {
        public ulong ReadOperationCount, WriteOperationCount,
            OtherOperationCount, ReadTransferCount, WriteTransferCount,
            OtherTransferCount;
    }
    [StructLayout(LayoutKind.Sequential)]
    public struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION {
        public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
        public IO_COUNTERS IoInfo;
        public UIntPtr ProcessMemoryLimit;
        public UIntPtr JobMemoryLimit;
        public UIntPtr PeakProcessMemoryUsed;
        public UIntPtr PeakJobMemoryUsed;
    }
}
'@

try {
    $proc = [System.Diagnostics.Process]::Start($psi)
} catch {
    Fail "KRE executable failed to start: $($_.Exception.Message)"
}
$job = [ToJob]::CreateJobObject([IntPtr]::Zero, $null)
if ($job -ne [IntPtr]::Zero) {
    $info = New-Object 'ToJob+JOBOBJECT_EXTENDED_LIMIT_INFORMATION'
    $info.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
    $len = [Runtime.InteropServices.Marshal]::SizeOf(
        [type]'ToJob+JOBOBJECT_EXTENDED_LIMIT_INFORMATION')
    if ([ToJob]::SetInformationJobObject($job, 9, [ref]$info, $len)) {
        [void][ToJob]::AssignProcessToJobObject($job, $proc.Handle)
    }
}

# Drain stderr asynchronously while stdout is scrubbed line-wise —
# a full stderr pipe cannot deadlock the child.
$errTask = $proc.StandardError.ReadToEndAsync()
while (-not $proc.StandardOutput.EndOfStream) {
    $line = $proc.StandardOutput.ReadLine()
    if ($null -ne $line) {
        [Console]::Out.WriteLine($line.Replace($key, "***REDACTED***"))
    }
}
$proc.WaitForExit()
$err = $errTask.Result
if ($err) {
    [Console]::Error.Write($err.Replace($key, "***REDACTED***"))
}
# Backstop only — the delivered file was already deleted pre-launch;
# this covers the edge where the pre-launch delete itself failed.
if ($toDelivered) {
    Remove-Item -LiteralPath $CredentialFile -Force -ErrorAction SilentlyContinue
}
exit $proc.ExitCode
