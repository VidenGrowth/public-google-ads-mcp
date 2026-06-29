[CmdletBinding()]
param(
    [switch]$SkipToolInstall,
    [switch]$SkipSync,
    [switch]$SkipEnvPrompt,
    [string]$RepoUrl = "https://github.com/VidenGrowth/public-google-ads-mcp"
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Test-CommandInstalled {
    param([string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Refresh-Path {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $combined = @($machinePath, $userPath, $env:Path) -join ";"
    $env:Path = $combined
}

function Try-InstallWithWinget {
    param(
        [string]$PackageId,
        [string]$DisplayName
    )

    if (-not (Test-CommandInstalled "winget")) {
        return $false
    }

    Write-Host "Installing $DisplayName with winget..."
    # --source winget skips the msstore source, which can fail with SSL cert
    # errors on some networks and cause a non-zero exit even when the package
    # is available.
    & winget install --id $PackageId -e --source winget --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "winget failed while installing $DisplayName. Trying fallback installer."
        return $false
    }

    return $true
}

function Install-GitWithDirectDownload {
    Write-Host "Installing Git with direct download fallback..."
    $ProgressPreference = "SilentlyContinue"
    $apiUrl = "https://api.github.com/repos/git-for-windows/git/releases/latest"
    $release = Invoke-RestMethod -Uri $apiUrl
    $asset = $release.assets | Where-Object { $_.name -match '64-bit\.exe$' } | Select-Object -First 1
    if ($null -eq $asset) {
        throw "Failed to find the latest Git for Windows 64-bit installer."
    }
    $installerPath = Join-Path $env:TEMP "GitInstall.exe"
    Invoke-RestMethod -Uri $asset.browser_download_url -OutFile $installerPath
    try {
        $process = Start-Process -FilePath $installerPath -ArgumentList "/VERYSILENT", "/NORESTART", "/NOCANCEL" -Wait -PassThru
        if ($process.ExitCode -ne 0) {
            throw "Git installer exited with code $($process.ExitCode)."
        }
    }
    finally {
        Remove-Item $installerPath -Force -ErrorAction SilentlyContinue
    }
}

function Install-UvWithOfficialScript {
    Write-Host "Installing uv with the official installer..."
    & powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    if ($LASTEXITCODE -ne 0) {
        throw "uv installer failed."
    }
}

function Ensure-Command {
    param(
        [string]$Name,
        [string]$DisplayName,
        [scriptblock]$InstallAction
    )

    if (Test-CommandInstalled $Name) {
        Write-Host "$DisplayName is already installed."
        return
    }

    if ($SkipToolInstall) {
        throw "$DisplayName is not installed. Re-run without -SkipToolInstall or install it manually."
    }

    & $InstallAction
    Refresh-Path

    if (-not (Test-CommandInstalled $Name)) {
        throw "$DisplayName was installed, but the command is still not available in this terminal. Close PowerShell, reopen it, and run the script again."
    }
}

function Convert-ToClaudePath {
    param([string]$PathValue)
    return ($PathValue -replace "\\", "/")
}

if ($env:OS -ne "Windows_NT") {
    throw "This script is for Windows only."
}

$ClaudeDir = Join-Path $env:APPDATA "Claude"
$ClaudeConfigPath = Join-Path $ClaudeDir "claude_desktop_config.json"

# Step 1: Install Git
Write-Step "Step 1 - Checking Git"
Ensure-Command -Name "git" -DisplayName "Git" -InstallAction {
    if (-not (Try-InstallWithWinget -PackageId "Git.Git" -DisplayName "Git")) {
        Install-GitWithDirectDownload
    }
}
& git --version

# Step 2: Install uv
Write-Step "Step 2 - Checking uv"
Ensure-Command -Name "uv" -DisplayName "uv" -InstallAction {
    try {
        Install-UvWithOfficialScript
    }
    catch {
        Write-Warning "Official uv installer failed. Trying winget fallback."
        if (-not (Try-InstallWithWinget -PackageId "astral-sh.uv" -DisplayName "uv")) {
            throw "Could not install uv with the official installer or winget."
        }
    }
}
& uv --version

# Step 3: Clone repo (if needed)
Write-Step "Step 3 - Locating repository"

$RepoRoot = $null

# If the script lives inside the repo, use that location.
if ($null -ne $PSScriptRoot -and (Test-Path (Join-Path (Split-Path -Parent $PSScriptRoot) "pyproject.toml"))) {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
    Write-Host "Using existing repo at: $RepoRoot"
}
else {
    # Otherwise clone to $HOME\google-ads-mcp
    $defaultClonePath = Join-Path $HOME "google-ads-mcp"
    if (Test-Path (Join-Path $defaultClonePath "pyproject.toml")) {
        $RepoRoot = $defaultClonePath
        Write-Host "Found existing clone at: $RepoRoot"
    }
    else {
        Write-Host "Cloning repository to $defaultClonePath ..."
        & git clone $RepoUrl $defaultClonePath
        if ($LASTEXITCODE -ne 0) {
            throw "git clone failed."
        }
        $RepoRoot = $defaultClonePath
    }
}

$EnvExamplePath = Join-Path $RepoRoot ".env.example"
$EnvPath = Join-Path $RepoRoot ".env"

# Step 4: Find uv path
Write-Step "Step 4 - Resolving uv path"
$uvCommand = Get-Command "uv" -ErrorAction Stop
$uvPath = $uvCommand.Source
Write-Host "uv path: $uvPath"

# Step 5: Prepare .env
Write-Step "Step 5 - Preparing .env"
if (-not (Test-Path $EnvPath)) {
    Copy-Item $EnvExamplePath $EnvPath
    Write-Host "Created .env from .env.example"
}
else {
    Write-Host ".env already exists."
}

$envContents = Get-Content -Path $EnvPath -Raw
$needsEnvEdit = $envContents -match "your-developer-token|your-client-id|your-client-secret|your-refresh-token"

if (-not $SkipEnvPrompt -and $needsEnvEdit) {
    Write-Host "Your .env still contains placeholder values. Notepad will open now."
    Write-Host "Fill in: GOOGLE_ADS_DEVELOPER_TOKEN, GOOGLE_ADS_CLIENT_ID, GOOGLE_ADS_CLIENT_SECRET" -ForegroundColor Yellow
    Write-Host "Leave GOOGLE_ADS_REFRESH_TOKEN empty - the next step will generate it." -ForegroundColor Yellow
    Start-Process notepad.exe $EnvPath
    Read-Host "Fill in your Google Ads credentials, save the file, then press Enter here"
}

# Step 6: Generate refresh token
Write-Step "Step 6 - Generating GOOGLE_ADS_REFRESH_TOKEN"
$refreshTokenScript = Join-Path $RepoRoot "scripts\generate-refresh-token-windows.ps1"
if (Test-Path $refreshTokenScript) {
    $envContents = Get-Content -Path $EnvPath -Raw
    $refreshTokenMatch = [regex]::Match($envContents, 'GOOGLE_ADS_REFRESH_TOKEN\s*=\s*(.+)')
    $refreshTokenValue = $null
    if ($refreshTokenMatch.Success) {
        $refreshTokenValue = $refreshTokenMatch.Groups[1].Value.Trim()
        if (
            ($refreshTokenValue.StartsWith('"') -and $refreshTokenValue.EndsWith('"')) -or
            ($refreshTokenValue.StartsWith("'") -and $refreshTokenValue.EndsWith("'"))
        ) {
            $refreshTokenValue = $refreshTokenValue.Substring(1, $refreshTokenValue.Length - 2)
        }
    }

    $hasUsableRefreshToken = -not [string]::IsNullOrWhiteSpace($refreshTokenValue) -and $refreshTokenValue -ne "your-refresh-token"

    if (-not $hasUsableRefreshToken) {
        Write-Host "Running refresh token generation script..."
        & powershell -ExecutionPolicy Bypass -File $refreshTokenScript -EnvPath $EnvPath
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Refresh token generation failed. You can run it manually later:"
            Write-Host "  powershell -ExecutionPolicy Bypass -File .\scripts\generate-refresh-token-windows.ps1" -ForegroundColor Yellow
        }
        else {
            Write-Host "Refresh token saved to .env" -ForegroundColor Green
        }
    }
    else {
        Write-Host "GOOGLE_ADS_REFRESH_TOKEN already set in .env - skipping."
    }
}
else {
    Write-Warning "Refresh token script not found at: $refreshTokenScript"
    Write-Host "You will need to generate your refresh token manually later."
}

# Step 7: Install project dependencies
Write-Step "Step 7 - Installing project dependencies"
Push-Location $RepoRoot
try {
    if (-not $SkipSync) {
        & $uvPath sync
        if ($LASTEXITCODE -ne 0) {
            throw "uv sync failed."
        }
    }
    else {
        Write-Host "Skipped uv sync."
    }
}
finally {
    Pop-Location
}

# Step 8: Update Claude Desktop config
Write-Step "Step 8 - Updating Claude Desktop config"
if (-not (Test-Path $ClaudeDir)) {
    New-Item -ItemType Directory -Path $ClaudeDir | Out-Null
}

$configObject = [pscustomobject]@{}
if (Test-Path $ClaudeConfigPath) {
    $rawConfig = Get-Content -Path $ClaudeConfigPath -Raw
    if (-not [string]::IsNullOrWhiteSpace($rawConfig)) {
        try {
            $configObject = $rawConfig | ConvertFrom-Json
        }
        catch {
            throw "Existing Claude config is not valid JSON: $ClaudeConfigPath"
        }
    }

    $backupPath = "$ClaudeConfigPath.bak"
    Copy-Item $ClaudeConfigPath $backupPath -Force
    Write-Host "Backup created: $backupPath"
}

if ($null -eq $configObject) {
    $configObject = [pscustomobject]@{}
}

if (-not (Get-Member -InputObject $configObject -Name "mcpServers" -MemberType NoteProperty -ErrorAction SilentlyContinue)) {
    $configObject | Add-Member -NotePropertyName "mcpServers" -NotePropertyValue ([pscustomobject]@{})
}
elseif ($null -eq $configObject.mcpServers) {
    $configObject.mcpServers = [pscustomobject]@{}
}

$serverConfig = [pscustomobject]@{
    command = (Convert-ToClaudePath $uvPath)
    args = @(
        "--directory",
        (Convert-ToClaudePath $RepoRoot),
        "run",
        "google-ads-mcp"
    )
}

$configObject.mcpServers | Add-Member -NotePropertyName "google-ads" -NotePropertyValue $serverConfig -Force

$json = $configObject | ConvertTo-Json -Depth 10
Set-Content -Path $ClaudeConfigPath -Value $json -Encoding UTF8

Write-Step "Done"
Write-Host "Claude Desktop config updated: $ClaudeConfigPath" -ForegroundColor Green
Write-Host "Repo path: $RepoRoot"
Write-Host "uv path: $uvPath"
Write-Host ""
Write-Host "Next steps:"
Write-Host "1. If you have not filled in .env yet, open it and add your Google Ads credentials."
Write-Host "2. Fully quit Claude Desktop and open it again."
Write-Host "3. In Claude Desktop, look for the tools icon and test: Show me all campaigns for customer 1234567890"

