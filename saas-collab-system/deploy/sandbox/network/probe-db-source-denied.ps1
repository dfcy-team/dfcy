# Run on the independent Windows host only. This host is a probe, never an
# application or database member, and must receive a reviewed policy copy.
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$PolicyFile = ".\sandbox-network.env",
    [Parameter(Position = 1)]
    [string]$EvidenceFile = ".\unapproved-db-source-evidence.json"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Fail([string]$Message) {
    [Console]::Error.WriteLine("Sandbox Windows database source probe failed: $Message")
    exit 1
}

if (-not (Test-Path -LiteralPath $PolicyFile -PathType Leaf)) {
    Fail "Policy file is missing: $PolicyFile"
}

$policy = @{}
foreach ($line in Get-Content -LiteralPath $PolicyFile) {
    if ($line -match '^\s*([^#=\s]+)\s*=\s*(.*?)\s*$') {
        $policy[$Matches[1]] = $Matches[2]
    }
}

if ($policy['SANDBOX_UNAPPROVED_SOURCE_PROBE'] -ne 'YES') {
    Fail "Explicit SANDBOX_UNAPPROVED_SOURCE_PROBE=YES approval is required."
}
$dbIp = $policy['SANDBOX_DB_HOST_IP']
$dbPortText = $policy['SANDBOX_DB_PORT']
$approvedAppIp = $policy['SANDBOX_APP_HOST_IP']
$dbPort = 0
if ([string]::IsNullOrWhiteSpace($dbIp) -or [string]::IsNullOrWhiteSpace($approvedAppIp)) {
    Fail "SANDBOX_DB_HOST_IP and SANDBOX_APP_HOST_IP are required."
}
if (-not [int]::TryParse($dbPortText, [ref]$dbPort)) {
    Fail "SANDBOX_DB_PORT is invalid."
}
if ($dbPort -ne 3307) {
    Fail "The Sandbox single-host probe must target TCP 3307."
}

$result = Test-NetConnection -ComputerName $dbIp -Port $dbPort -InformationLevel Detailed -WarningAction SilentlyContinue
$sourceIp = [string]$result.SourceAddress
if ([string]::IsNullOrWhiteSpace($sourceIp)) {
    Fail "Windows could not determine the probe source address."
}
if ($sourceIp -eq $approvedAppIp) {
    Fail "This host is the approved application source; use an independent Windows host."
}
if ($result.TcpTestSucceeded) {
    Fail "Database connection unexpectedly succeeded from unapproved source $sourceIp."
}

$parent = Split-Path -Parent $EvidenceFile
if ([string]::IsNullOrWhiteSpace($parent)) {
    $parent = (Get-Location).Path
}
if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
    Fail "Evidence directory is missing: $parent"
}
$tmp = "$EvidenceFile.tmp.$PID"
$evidence = [ordered]@{
    schema_version = 1
    environment = 'sandbox'
    probe = 'unapproved_database_source'
    verification_status = 'pass'
    verified_at = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    source_ip = $sourceIp
    approved_application_ip = $approvedAppIp
    database_ip = $dbIp
    database_port = $dbPort
    connection_result = 'rejected'
    probe_platform = 'windows'
}
$evidence | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $tmp -Encoding utf8NoBOM
Move-Item -LiteralPath $tmp -Destination $EvidenceFile -Force
Write-Output "SANDBOX_UNAPPROVED_DB_SOURCE=PASS source=$sourceIp file=$EvidenceFile"
Write-Output "Copy the evidence to SANDBOX_UNAPPROVED_DB_SOURCE_EVIDENCE_FILE on Linux and chmod 400 before generating Sandbox PASS evidence."
