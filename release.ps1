<#
.SYNOPSIS
    Build a clean firmware image and publish it as a GitHub release.

.DESCRIPTION
    Requires the GitHub CLI (gh) to be installed and authenticated:
        winget install --id GitHub.cli
        gh auth login

.EXAMPLE
    .\release.ps1 -Version v0.1.0
    .\release.ps1 -Version v0.1.0 -Board pico_w -Draft
#>
param(
    [Parameter(Mandatory)][string]$Version,
    [string[]]$Board = @("pico"),
    [switch]$Draft,
    [switch]$NoPush,
    [string]$Notes
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command gh -EA SilentlyContinue)) {
    throw "gh not found. Install with: winget install --id GitHub.cli"
}
gh auth status 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Not logged in. Run: gh auth login" }

# The submodule working tree is permanently modified by the FIFO patch, so
# ignore changes inside it; a changed submodule *pointer* is still reported.
if (git -C $PSScriptRoot status --porcelain --ignore-submodules=dirty) {
    throw "Working tree is dirty. Commit or stash first so the tag matches the source."
}

# gh creates the tag on the remote, so the branch must be pushed first or the
# tag would point at a stale commit.
if (git ls-remote --tags origin "refs/tags/$Version") {
    throw "Tag $Version already exists on origin. Pick a new version, or delete it with: gh release delete $Version --cleanup-tag"
}

if (-not $NoPush) {
    Write-Host "==> Pushing main"
    git -C $PSScriptRoot push origin HEAD
    if ($LASTEXITCODE -ne 0) { throw "git push failed" }
}

$local = (git -C $PSScriptRoot rev-parse HEAD).Trim()
$remote = (git -C $PSScriptRoot rev-parse '@{u}' 2>$null).Trim()
if ($local -ne $remote) {
    throw "HEAD ($($local.Substring(0,7))) is not pushed. The tag would point at the wrong commit."
}

$Dist = Join-Path $PSScriptRoot "dist"
Remove-Item -Recurse -Force $Dist -EA SilentlyContinue
New-Item -ItemType Directory -Force -Path $Dist | Out-Null

$assets = @()
foreach ($b in $Board) {
    Write-Host "==> Building $b"
    & (Join-Path $PSScriptRoot "deploy.ps1") -Board $b -Clean -BuildOnly

    # deploy.ps1 applies patches/ before building; confirm it took effect so a
    # release can never ship unpatched firmware.
    $bridge = Join-Path $PSScriptRoot "external\pico-uart-bridge\uart-bridge.c"
    if (-not (Select-String -Path $bridge -Pattern 'uart_set_fifo_enabled\(ui->inst, true\)' -Quiet)) {
        throw "FIFO patch is not applied - refusing to publish unpatched firmware."
    }

    $src = Join-Path $PSScriptRoot "external\pico-uart-bridge\build\$b\uart_bridge.uf2"
    $dst = Join-Path $Dist "picouart-$Version-$b.uf2"
    Copy-Item $src $dst
    $assets += $dst
}

# Checksums so users can verify what they flash.
$sums = Join-Path $Dist "SHA256SUMS.txt"
Get-FileHash $assets -Algorithm SHA256 |
    ForEach-Object { "{0}  {1}" -f $_.Hash.ToLower(), (Split-Path $_.Path -Leaf) } |
    Set-Content $sums -Encoding ascii
$assets += $sums

if (-not $Notes) {
    $Notes = @'
UART bridge firmware with the hardware FIFOs enabled.

Flash: hold BOOTSEL while plugging in the Pico, then copy the `.uf2` to the
`RPI-RP2` drive. The board then exposes two serial ports (UART0 on GP16/GP17,
UART1 on GP4/GP5).

Verify the download against `SHA256SUMS.txt`.
'@
}

# Note: $args is an automatic variable, so use a distinct name.
$ghArgs = @(
    "release", "create", $Version,
    "--title", "picouart $Version",
    "--notes", $Notes,
    "--target", $local
)
if ($Draft) { $ghArgs += "--draft" }

Write-Host "==> Creating release $Version"
gh @ghArgs @assets
if ($LASTEXITCODE -ne 0) { throw "gh release create failed" }

Write-Host "==> Published:"
$assets | ForEach-Object { Write-Host "    $(Split-Path $_ -Leaf)" }
gh release view $Version --json url --jq .url
