[CmdletBinding()]
param(
    [string]$EnvPath,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"

$scriptRoot = if (-not [string]::IsNullOrWhiteSpace($PSScriptRoot)) {
    $PSScriptRoot
}
else {
    Split-Path -Parent $MyInvocation.MyCommand.Path
}

$repoRoot = Split-Path -Parent $scriptRoot

if ([string]::IsNullOrWhiteSpace($EnvPath)) {
    $EnvPath = Join-Path $repoRoot ".env"
}

function Get-DotEnvValue {
    param(
        [string]$FilePath,
        [string]$Key
    )

    $pattern = "^\s*" + [regex]::Escape($Key) + "\s*=\s*(.*)\s*$"
    foreach ($line in Get-Content -Path $FilePath) {
        if ($line -match "^\s*#") {
            continue
        }

        if ($line -match $pattern) {
            $value = $matches[1].Trim()
            if (
                ($value.StartsWith('"') -and $value.EndsWith('"')) -or
                ($value.StartsWith("'") -and $value.EndsWith("'"))
            ) {
                $value = $value.Substring(1, $value.Length - 2)
            }
            return $value
        }
    }

    return $null
}

if ($env:OS -ne "Windows_NT") {
    throw "This script is for Windows only."
}

if (-not (Test-Path $EnvPath)) {
    throw ".env file not found: $EnvPath"
}

$clientId = Get-DotEnvValue -FilePath $EnvPath -Key "GOOGLE_ADS_CLIENT_ID"
$clientSecret = Get-DotEnvValue -FilePath $EnvPath -Key "GOOGLE_ADS_CLIENT_SECRET"

if ([string]::IsNullOrWhiteSpace($clientId)) {
    throw "GOOGLE_ADS_CLIENT_ID is missing in .env"
}

if ([string]::IsNullOrWhiteSpace($clientSecret)) {
    throw "GOOGLE_ADS_CLIENT_SECRET is missing in .env"
}

$uvCommand = Get-Command "uv" -ErrorAction SilentlyContinue
if ($null -eq $uvCommand) {
    throw "uv is not installed or not available in this terminal."
}

$tempSecretsPath = Join-Path $env:TEMP "google-ads-client-secret.generated.json"
$clientJson = @{
    web = @{
        client_id = $clientId
        client_secret = $clientSecret
        auth_uri = "https://accounts.google.com/o/oauth2/auth"
        token_uri = "https://oauth2.googleapis.com/token"
        redirect_uris = @("http://127.0.0.1:8080")
    }
} | ConvertTo-Json -Depth 5

[System.IO.File]::WriteAllText($tempSecretsPath, $clientJson)

Write-Host ""
Write-Host "Temporary OAuth client file created: $tempSecretsPath" -ForegroundColor Cyan
Write-Host "A browser login URL will be printed next." -ForegroundColor Cyan
Write-Host ""

Push-Location $repoRoot
try {
    $pyArgs = @("run", "auth/generate_refresh_token.py", "-c", $tempSecretsPath, "--env-file", $EnvPath)
    if ($NoBrowser) {
        $pyArgs += "--no-browser"
    }
    & $uvCommand.Source @pyArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Refresh token generation failed."
    }
}
finally {
    Pop-Location
    if (Test-Path $tempSecretsPath) {
        Remove-Item $tempSecretsPath -Force -ErrorAction SilentlyContinue
    }
}
