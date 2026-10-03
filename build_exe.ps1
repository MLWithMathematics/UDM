# Builds dist\UDM.exe — a single-file, windowed build with the same features as
# `python run.py` (video downloads incl. merging, browser extension bridge,
# clipboard monitor, scheduler, tray, themes).
#
# Usage: double-click build_exe.bat   (or run this script in PowerShell)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Run($exe, $argList) {
    & $exe @argList
    if ($LASTEXITCODE -ne 0) { throw "Command failed: $exe $($argList -join ' ')" }
}

function Get-FromZip($url, $names, $destDir) {
    $tmp = Join-Path $env:TEMP ("udm_dl_" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force $tmp | Out-Null
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $zip = Join-Path $tmp "pkg.zip"
        Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
        Expand-Archive -Path $zip -DestinationPath $tmp -Force
        foreach ($n in $names) {
            $f = Get-ChildItem $tmp -Recurse -Filter $n | Select-Object -First 1
            if ($f) { Copy-Item $f.FullName (Join-Path $destDir $n) -Force }
        }
    } finally {
        Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
    }
}

# 1. Virtual environment + dependencies (same packages the terminal version uses)
$py = Join-Path $PSScriptRoot "venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "==> Creating virtual environment"
    Run "python" @("-m", "venv", "venv")
}
Write-Host "==> Installing dependencies"
Run $py @("-m", "pip", "install", "--upgrade", "pip")
Run $py @("-m", "pip", "install", "-r", "requirements.txt")
Run $py @("-m", "pip", "install", "--upgrade", "pyinstaller")

# 2. Helper tools bundled into the exe (cached in vendor\ after first run)
$vendor = Join-Path $PSScriptRoot "vendor"
New-Item -ItemType Directory -Force $vendor | Out-Null

# ffmpeg/ffprobe: required for merging separate video+audio streams (YouTube etc.)
if (-not (Test-Path "$vendor\ffmpeg.exe")) {
    Write-Host "==> Downloading ffmpeg"
    Get-FromZip "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-lgpl.zip" @("ffmpeg.exe", "ffprobe.exe") $vendor
}
if (-not (Test-Path "$vendor\ffmpeg.exe")) { throw "ffmpeg.exe could not be downloaded. Put ffmpeg.exe and ffprobe.exe in the vendor folder and re-run." }

# deno: JS runtime recent yt-dlp versions use to solve YouTube challenges (non-fatal if it fails)
if (-not (Test-Path "$vendor\deno.exe")) {
    try {
        Write-Host "==> Downloading deno"
        Get-FromZip "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip" @("deno.exe") $vendor
    } catch {
        Write-Warning "Could not download deno ($($_.Exception.Message)). YouTube may need it; place deno.exe in vendor\ and re-run."
    }
}

# 3. Icon: use the project's logo (udm.ico). It is never overwritten here;
#    only if it is missing do we generate a plain fallback icon.
if (Test-Path "udm.ico") {
    Write-Host "==> Using logo icon: udm.ico"
} else {
    Write-Warning "udm.ico not found - generating a plain fallback icon. Put your logo icon at $PSScriptRoot\udm.ico to use it."
    try { Run $py @("tools\make_icon.py") } catch { Write-Warning "Icon generation skipped: $($_.Exception.Message)" }
}

# 4. Build
Write-Host "==> Building UDM.exe"
Remove-Item build, dist -Recurse -Force -ErrorAction SilentlyContinue
Run $py @("-m", "PyInstaller", "--noconfirm", "--clean", "UDM.spec")

if (Test-Path "dist\UDM.exe") {
    $mb = [math]::Round((Get-Item "dist\UDM.exe").Length / 1MB, 1)
    Write-Host ""
    Write-Host "Done: $PSScriptRoot\dist\UDM.exe ($mb MB)" -ForegroundColor Green
} else {
    throw "Build finished but dist\UDM.exe was not produced."
}
