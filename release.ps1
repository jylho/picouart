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

# Warn if the patch is not applied, so a release cannot silently ship without it.
$bridge = Join-Path $PSScriptRoot "external\pico-uart-bridge\uart-bridge.c"
if (-not (Select-String -Path $bridge -Pattern 'uart_set_fifo_enabled\(ui->inst, true\)' -Quiet)) {
    throw "FIFO patch is not applied. Run: git -C external/pico-uart-bridge apply ../../patches/0001-enable-uart-fifo.patch"
}

$Dist = Join-Path $PSScriptRoot "dist"
Remove-Item -Recurse -Force $Dist -EA SilentlyContinue
New-Item -ItemType Directory -Force -Path $Dist | Out-Null

$assets = @()
foreach ($b in $Board) {
    Write-Host "==> Building $b"
    & (Join-Path $PSScriptRoot "deploy.ps1") -Board $b -Clean -BuildOnly
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
    $Notes = @"
UART bridge firmware with the hardware FIFOs enabled.

Flash: hold BOOTSEL while plugging in the Pico, then copy the ``.uf2`` to the
``RPI-RP2`` drive. The board then exposes two serial ports (UART0 on GP16/GP17,
UART1 on GP4/GP5).

Verify the download against ``SHA256SUMS.txt``.
"@
}

$args = @("release", "create", $Version, "--title", "picouart $Version", "--notes", $Notes)
if ($Draft) { $args += "--draft" }

Write-Host "==> Creating release $Version"
gh @args @assets
if ($LASTEXITCODE -ne 0) { throw "gh release create failed" }

Write-Host "==> Published:"
$assets | ForEach-Object { Write-Host "    $(Split-Path $_ -Leaf)" }
