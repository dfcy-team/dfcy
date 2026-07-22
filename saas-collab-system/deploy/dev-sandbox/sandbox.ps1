param(
    [ValidateSet('init', 'start', 'verify', 'status', 'stop', 'reset', 'verify-rc', 'start-rc')]
    [string]$Action = 'start',

    [ValidateSet('core', 'sales-inventory-finance-reconciliation', 'creator-management', 'procurement', 'integration')]
    [string]$SandboxProfile = 'core',

    [switch]$ConfirmReset
)

$ErrorActionPreference = 'Stop'
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$EnvFile = Join-Path $ScriptRoot '.env.local'
$EnvExample = Join-Path $ScriptRoot 'env.local.example'
$LocalCompose = Join-Path $ScriptRoot 'docker-compose.local.yml'
$RcCompose = Join-Path $ScriptRoot 'docker-compose.rc.yml'

function New-RandomHex([int]$Bytes) {
    $buffer = New-Object byte[] $Bytes
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($buffer)
    } finally {
        $generator.Dispose()
    }
    return (($buffer | ForEach-Object { $_.ToString('x2') }) -join '')
}

function Initialize-LocalEnvironment {
    if (Test-Path -LiteralPath $EnvFile) {
        Write-Output 'LOCAL_SANDBOX_INIT=SKIP reason=env-exists'
        return
    }
    $content = Get-Content -LiteralPath $EnvExample -Raw -Encoding UTF8
    $content = $content.Replace('__GENERATE_DJANGO_SECRET__', (New-RandomHex 48))
    $content = $content.Replace('__GENERATE_DB_PASSWORD__', (New-RandomHex 24))
    $content = $content.Replace('__GENERATE_MYSQL_ROOT_PASSWORD__', (New-RandomHex 24))
    $content = $content.Replace('__GENERATE_DEMO_PASSWORD__', (New-RandomHex 20))
    [IO.File]::WriteAllText($EnvFile, $content, [Text.UTF8Encoding]::new($false))
    try {
        $acl = Get-Acl -LiteralPath $EnvFile
        $acl.SetAccessRuleProtection($true, $false)
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
        $rule = New-Object Security.AccessControl.FileSystemAccessRule(
            $identity,
            [Security.AccessControl.FileSystemRights]::FullControl,
            [Security.AccessControl.AccessControlType]::Allow
        )
        $acl.SetAccessRule($rule)
        Set-Acl -LiteralPath $EnvFile -AclObject $acl
    } catch {
        Remove-Item -LiteralPath $EnvFile -Force -ErrorAction SilentlyContinue
        throw 'Failed to restrict .env.local permissions.'
    }
    Write-Output 'LOCAL_SANDBOX_INIT=PASS env=.env.local secrets=generated-not-displayed'
}

function Assert-Docker {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw 'Docker CLI is required.'
    }
    & docker compose version | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Docker Compose v2 is required.' }
}

function Invoke-LocalCompose([string[]]$Arguments) {
    & docker compose --env-file $EnvFile -f $LocalCompose @Arguments
    if ($LASTEXITCODE -ne 0) { throw "docker compose failed: $($Arguments -join ' ')" }
}

function Invoke-RcCompose([string[]]$Arguments) {
    & docker compose --env-file $EnvFile -f $RcCompose @Arguments
    if ($LASTEXITCODE -ne 0) { throw "RC docker compose failed: $($Arguments -join ' ')" }
}

function Wait-Backend {
    $port = 8000
    $line = Get-Content -LiteralPath $EnvFile | Where-Object { $_ -match '^LOCAL_SANDBOX_BACKEND_PORT=' } | Select-Object -First 1
    if ($line) { $port = [int]($line.Split('=', 2)[1]) }
    $uri = "http://127.0.0.1:$port/api/internal/health/"
    for ($attempt = 1; $attempt -le 60; $attempt++) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $uri -Headers @{ Host = 'localhost' } -TimeoutSec 3
            if ($response.StatusCode -eq 200) { return }
        } catch {
            Start-Sleep -Seconds 2
        }
    }
    throw "Backend did not become healthy: $uri"
}

function Start-LocalSandbox {
    Initialize-LocalEnvironment
    $env:LOCAL_SANDBOX_MODULE = $SandboxProfile
    try {
        Invoke-LocalCompose @('--profile', $SandboxProfile, 'up', '-d', '--build')
    } catch {
        throw "Local Sandbox build/start failed. Inspect Compose logs; for fetch failures check registry/package mirror access or Docker proxy settings. $($_.Exception.Message)"
    }
    Wait-Backend
    Invoke-LocalCompose @('--profile', $SandboxProfile, '--profile', 'tooling', 'run', '--rm', 'fixture-check')
    Invoke-LocalCompose @('--profile', $SandboxProfile, '--profile', 'tooling', 'run', '--rm', 'seed')
    Write-Output "LOCAL_SANDBOX_START=PASS profile=$SandboxProfile"
}

function Test-LocalSandbox {
    Start-LocalSandbox
    Invoke-LocalCompose @('--profile', $SandboxProfile, 'config', '--quiet')
    Invoke-LocalCompose @('--profile', $SandboxProfile, 'exec', '-T', 'backend', 'python', 'manage.py', 'check')
    Invoke-LocalCompose @('--profile', $SandboxProfile, 'exec', '-T', 'backend', 'python', 'manage.py', 'makemigrations', '--check', '--dry-run')
    Invoke-LocalCompose @('--profile', $SandboxProfile, 'exec', '-T', 'backend', 'python', 'manage.py', 'sync_permissions', '--check')
    Invoke-LocalCompose @('--profile', $SandboxProfile, '--profile', 'tooling', 'run', '--rm', 'test-db-prepare')

    $tests = switch ($SandboxProfile) {
        'core' { @('tests/test_auth_api.py', 'tests/test_common_responses.py', 'tests/test_permission_catalog.py', 'tests/test_local_sandbox_seed.py') }
        'sales-inventory-finance-reconciliation' { @('tests/test_phase2_finance_reconciliation.py', 'tests/test_phase3_bi_metrics.py', 'tests/test_phase3_inventory_alerts.py', 'tests/test_phase3_replenishment.py', 'tests/test_local_sandbox_seed.py') }
        'creator-management' { @('tests/test_auth_api.py', 'tests/test_local_sandbox_seed.py') }
        'procurement' { @('tests/test_purchasing_suppliers_api.py', 'tests/test_phase2_supplier_performance.py', 'tests/test_local_sandbox_seed.py') }
        'integration' { @() }
    }
    $pytestArgs = @('--profile', $SandboxProfile, 'exec', '-T', 'backend', 'pytest', '-q') + $tests
    Invoke-LocalCompose $pytestArgs
    if ($SandboxProfile -in @('sales-inventory-finance-reconciliation', 'integration')) {
        Invoke-LocalCompose @('--profile', $SandboxProfile, 'exec', '-T', 'backend', 'python', 'manage.py', 'check_phase3_data_quality')
    }
    Invoke-LocalCompose @('--profile', $SandboxProfile, 'exec', '-T', '-e', 'VITE_USE_MOCK=true', 'frontend', 'npm', 'test')
    Invoke-LocalCompose @('--profile', $SandboxProfile, 'exec', '-T', 'frontend', 'npm', 'run', 'build')

    $frontendPort = 5173
    $line = Get-Content -LiteralPath $EnvFile | Where-Object { $_ -match '^LOCAL_SANDBOX_FRONTEND_PORT=' } | Select-Object -First 1
    if ($line) { $frontendPort = [int]($line.Split('=', 2)[1]) }
    $frontend = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$frontendPort/" -TimeoutSec 5
    if ($frontend.StatusCode -ne 200) { throw 'Frontend smoke test failed.' }

    if ($SandboxProfile -in @('creator-management', 'integration')) {
        $mockPort = 8091
        $line = Get-Content -LiteralPath $EnvFile | Where-Object { $_ -match '^LOCAL_SANDBOX_CREATOR_MOCK_PORT=' } | Select-Object -First 1
        if ($line) { $mockPort = [int]($line.Split('=', 2)[1]) }
        $mock = Invoke-RestMethod -Uri "http://127.0.0.1:$mockPort/mock/creator-management/creators/" -TimeoutSec 5
        if (-not $mock.success -or $mock.data.count -ne 2) { throw 'Creator management mock contract failed.' }
        try {
            Invoke-WebRequest -UseBasicParsing -Method Post -Uri "http://127.0.0.1:$mockPort/mock/creator-management/creators/" -TimeoutSec 5 | Out-Null
            throw 'Creator mock accepted a write request.'
        } catch {
            $statusCode = [int]$_.Exception.Response.StatusCode
            if ($statusCode -ne 405) { throw }
        }
    }
    Write-Output "LOCAL_SANDBOX_VERIFY=PASS profile=$SandboxProfile"
}

function Test-ReleaseCandidateContract {
    Initialize-LocalEnvironment
    $mount = "${ScriptRoot}:/sandbox:ro"
    & docker run --rm -v $mount python:3.12-alpine python /sandbox/validate_rc_manifest.py --env-file /sandbox/.env.local
    if ($LASTEXITCODE -ne 0) { throw 'Release-candidate manifest validation failed.' }
    Invoke-RcCompose @('--profile', 'release-candidate', 'config', '--quiet')
    if (Select-String -LiteralPath $RcCompose -Pattern '^\s*build\s*:') {
        throw 'Release-candidate Compose must not contain build.'
    }
    Write-Output 'LOCAL_SANDBOX_RC_VERIFY=PASS'
}

Assert-Docker
switch ($Action) {
    'init' { Initialize-LocalEnvironment }
    'start' { Start-LocalSandbox }
    'verify' { Test-LocalSandbox }
    'status' { Initialize-LocalEnvironment; Invoke-LocalCompose @('--profile', $SandboxProfile, 'ps') }
    'stop' { Initialize-LocalEnvironment; Invoke-LocalCompose @('--profile', $SandboxProfile, 'down', '--remove-orphans') }
    'reset' {
        if (-not $ConfirmReset) { throw 'reset requires -ConfirmReset because it deletes Local Sandbox volumes.' }
        Initialize-LocalEnvironment
        Invoke-LocalCompose @('--profile', $SandboxProfile, 'down', '--volumes', '--remove-orphans')
        Start-LocalSandbox
    }
    'verify-rc' { Test-ReleaseCandidateContract }
    'start-rc' {
        Test-ReleaseCandidateContract
        Invoke-RcCompose @('--profile', 'release-candidate', 'up', '-d')
        Write-Output 'LOCAL_SANDBOX_RC_START=PASS'
    }
}
