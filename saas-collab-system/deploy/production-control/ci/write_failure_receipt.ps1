param(
  [Parameter(Mandatory=$true)][string]$Path,
  [Parameter(Mandatory=$true)][ValidateSet('cache','deploy','reuse')][string]$Stage,
  [Parameter(Mandatory=$true)][ValidateSet('ssh_exit_nonzero','process_start_failed','invalid_receipt','validation_failed','unknown')][string]$Reason,
  [int]$ExitCode = -1,
  [string]$RunId = '',
  [string]$Attempt = '',
  [string]$ReleaseSha = '',
  [string]$ControllerSha = ''
)
$shaPattern = '^[0-9a-f]{40}$'
$receipt = [ordered]@{
  status = 'failure'
  stage = $Stage
  exit_code = $ExitCode
  run_id = if ($RunId -match '^[0-9]{1,20}$') { $RunId } else { 'unknown' }
  attempt = if ($Attempt -match '^[0-9]{1,3}$') { $Attempt } else { 'unknown' }
  release_sha = if ($ReleaseSha -match $shaPattern) { $ReleaseSha } else { 'unknown' }
  controller_sha = if ($ControllerSha -match $shaPattern) { $ControllerSha } else { 'unknown' }
  reason = $Reason
}
[IO.File]::WriteAllText($Path, ($receipt | ConvertTo-Json -Compress), [Text.UTF8Encoding]::new($false))
