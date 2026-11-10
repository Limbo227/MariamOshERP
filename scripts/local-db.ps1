param([ValidateSet('init','start','stop','status')][string]$Action = 'start')
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$local = Join-Path $root '.local'
$bin = Join-Path $local 'postgres/pgsql/bin'
$data = Join-Path $local 'pgdata'
if (-not (Test-Path (Join-Path $bin 'pg_ctl.exe'))) { throw 'Download/extract PostgreSQL as described in docs/development.md.' }
function Check-Exit { if ($LASTEXITCODE -ne 0) { throw "PostgreSQL command failed ($LASTEXITCODE)." } }
function Random-Secret {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes)
    $rng.Dispose()
    return ([BitConverter]::ToString($bytes)).Replace('-','').ToLowerInvariant()
}
if ($Action -eq 'init') {
    if (Test-Path (Join-Path $data 'PG_VERSION')) { throw 'Database already initialised. Use -Action start.' }
    if ((Test-Path (Join-Path $root '.env')) -and -not (Test-Path (Join-Path $local 'pg-admin.password'))) { throw '.env already exists. Configure the database manually; do not overwrite credentials.' }
    New-Item -ItemType Directory -Force $local | Out-Null
    if (Test-Path (Join-Path $root '.env')) {
        $adminSecret = [IO.File]::ReadAllText((Join-Path $local 'pg-admin.password'))
        $config = Get-Content (Join-Path $root '.env') | ConvertFrom-StringData
        if ($config.POSTGRES_USER -ne 'ebb_app' -or $config.POSTGRES_DB -ne 'ebb_erp' -or $config.POSTGRES_PORT -ne '55432') { throw 'Existing .env is not the local bootstrap configuration.' }
        $appSecret = $config.POSTGRES_PASSWORD
        if ($appSecret -notmatch '^[a-f0-9]{64}$') { throw 'Unexpected bootstrap password format.' }
    } else {
    $adminSecret = Random-Secret
    $appSecret = Random-Secret
    $djangoSecret = Random-Secret
    [IO.File]::WriteAllText((Join-Path $local 'pg-admin.password'), $adminSecret)
    $envText = "DJANGO_SECRET_KEY=$djangoSecret`nDJANGO_DEBUG=true`nDJANGO_ALLOWED_HOSTS=127.0.0.1,localhost,testserver`nPOSTGRES_DB=ebb_erp`nPOSTGRES_USER=ebb_app`nPOSTGRES_PASSWORD=$appSecret`nPOSTGRES_HOST=127.0.0.1`nPOSTGRES_PORT=55432`n"
    [IO.File]::WriteAllText((Join-Path $root '.env'), $envText)
    }
    & (Join-Path $bin 'initdb.exe') -D $data -U ebb_admin --auth=scram-sha-256 --encoding=UTF8 --locale=C ('--pwfile=' + (Join-Path $local 'pg-admin.password'))
    Check-Exit
}
if ($Action -in @('init','start')) {
    & (Join-Path $bin 'pg_ctl.exe') -D $data status *> $null
    if ($LASTEXITCODE -ne 0) {
        & (Join-Path $bin 'pg_ctl.exe') -D $data -l (Join-Path $local 'postgres.log') -o '-h 127.0.0.1 -p 55432' -w start
        Check-Exit
    }
}
if ($Action -eq 'init') {
    $sqlPath = Join-Path $local 'bootstrap.sql'
    [IO.File]::WriteAllText($sqlPath, "CREATE ROLE ebb_app LOGIN CREATEDB NOSUPERUSER PASSWORD '$appSecret';`nCREATE DATABASE ebb_erp OWNER ebb_app;")
    $env:PGPASSWORD = $adminSecret
    try {
        & (Join-Path $bin 'psql.exe') -h 127.0.0.1 -p 55432 -U ebb_admin -d postgres -v ON_ERROR_STOP=1 -f $sqlPath
        Check-Exit
    } finally {
        Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $sqlPath
    }
}
if ($Action -eq 'stop') { & (Join-Path $bin 'pg_ctl.exe') -D $data -m fast -w stop; Check-Exit }
if ($Action -eq 'status') { & (Join-Path $bin 'pg_ctl.exe') -D $data status; Check-Exit }

