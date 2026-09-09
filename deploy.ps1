<#
.SYNOPSIS
    Build and flash the pico-uart-bridge firmware (Windows).

.DESCRIPTION
    Uses the toolchain installed by the Raspberry Pi Pico VS Code extension
    (~/.pico-sdk). No separate SDK install is required.

.EXAMPLE
    .\deploy.ps1
    .\deploy.ps1 -BuildOnly
    .\deploy.ps1 -Board pico_w -Clean
#>
param(
    [string]$Board = "pico",
    [switch]$Clean,
    [switch]$BuildOnly
)

$ErrorActionPreference = "Stop"

$PicoSdk = Join-Path $HOME ".pico-sdk"
if (-not (Test-Path $PicoSdk)) {
    throw "~/.pico-sdk not found. Install the 'Raspberry Pi Pico' VS Code extension (raspberry-pi.raspberry-pi-pico) and let it download its toolchain."
}

function Resolve-PicoTool([string]$Category, [string]$Exe) {
    $root = Join-Path $PicoSdk $Category
    if (-not (Test-Path $root)) { throw "Missing $root - update the Raspberry Pi Pico VS Code extension." }
    # Pick the newest installed version directory.
    $dir = Get-ChildItem $root -Directory | Sort-Object Name -Descending | Select-Object -First 1
    if (-not $dir) { throw "No versions installed under $root" }
    $hit = Get-ChildItem $dir.FullName -Recurse -Filter $Exe -EA SilentlyContinue | Select-Object -First 1
    if (-not $hit) { throw "$Exe not found under $($dir.FullName)" }
    return $hit.Directory.FullName
}

$ToolchainBin = Resolve-PicoTool "toolchain" "arm-none-eabi-gcc.exe"
$CMakeBin     = Resolve-PicoTool "cmake"     "cmake.exe"
$NinjaBin     = Resolve-PicoTool "ninja"     "ninja.exe"

$env:PICO_TOOLCHAIN_PATH = (Split-Path $ToolchainBin -Parent)
$env:Path = "$CMakeBin;$NinjaBin;$ToolchainBin;$env:Path"

$Src = Join-Path $PSScriptRoot "external\pico-uart-bridge"
$Build = Join-Path $Src "build\$Board"

if (-not (Test-Path (Join-Path $Src "pico-sdk\.git"))) {
    Write-Host "==> Initializing vendored pico-sdk submodule (this takes a while)"
    git -C $Src submodule update --init --recursive
    if ($LASTEXITCODE -ne 0) { throw "submodule init failed" }
}

# Apply our patches to the submodule. Submodule working-tree edits are not
# tracked by this repository, so this has to happen on every build; each patch
# is skipped if it is already applied.
foreach ($patch in (Get-ChildItem (Join-Path $PSScriptRoot "patches") -Filter *.patch | Sort-Object Name)) {
    git -C $Src apply --reverse --check $patch.FullName 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "==> Patch already applied: $($patch.Name)"
        continue
    }
    Write-Host "==> Applying $($patch.Name)"
    git -C $Src apply $patch.FullName
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to apply $($patch.Name). Reset the submodule with: git -C `"$Src`" checkout -- ."
    }
}

if ($Clean -and (Test-Path $Build)) {
    Remove-Item -Recurse -Force $Build
}

Write-Host "==> Configuring ($Board)"
cmake -G Ninja -B $Build -S $Src "-DPICO_BOARD=$Board" "-DCMAKE_BUILD_TYPE=Release"
if ($LASTEXITCODE -ne 0) { throw "cmake configure failed" }

Write-Host "==> Building"
cmake --build $Build
if ($LASTEXITCODE -ne 0) { throw "build failed" }

$Uf2 = Join-Path $Build "uart_bridge.uf2"
Write-Host "==> Firmware: $Uf2"

if ($BuildOnly) { return }

# Prefer picotool: it can reboot a running board into BOOTSEL automatically.
$picotool = @(
    (Get-Command picotool.exe -EA SilentlyContinue).Source,
    "C:\raspberry\picotool\picotool.exe"
) + (Get-ChildItem (Join-Path $PicoSdk "picotool") -Directory -EA SilentlyContinue |
        Sort-Object Name -Descending |
        ForEach-Object { Join-Path $_.FullName "picotool\picotool.exe" }) |
    Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1

if ($picotool) {
    Write-Host "==> Flashing with picotool"
    & $picotool load -x $Uf2 -f
    if ($LASTEXITCODE -eq 0) {
        Write-Host "==> Done. The board re-enumerates as two new COM ports."
        return
    }
    Write-Warning "picotool failed; falling back to mass-storage copy"
}

Write-Host "==> Waiting for a Pico in BOOTSEL mode (hold BOOTSEL and replug)..."
$drive = $null
for ($i = 0; $i -lt 60; $i++) {
    $drive = Get-Volume -EA SilentlyContinue |
        Where-Object { $_.FileSystemLabel -eq "RPI-RP2" -and $_.DriveLetter } |
        Select-Object -First 1
    if ($drive) { break }
    Start-Sleep -Seconds 1
}

if (-not $drive) {
    throw "No RPI-RP2 drive found. Hold BOOTSEL while plugging in the board, then copy manually: $Uf2"
}

$dest = "$($drive.DriveLetter):\"
Write-Host "==> Copying to $dest"
Copy-Item $Uf2 $dest
Write-Host "==> Done. The board re-enumerates as two new COM ports."
