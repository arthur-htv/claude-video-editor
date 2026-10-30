<#
.SYNOPSIS
  One-time setup for the Claude video editor folder (Windows).

.DESCRIPTION
  Checks for FFmpeg + ffprobe, Node.js 22+, Python 3.12 and HyperFrames.
  Anything missing is downloaded as a portable copy into .\tools (nothing is
  installed system-wide and no admin rights are needed). Then it creates the
  Python environment in .\.venv and installs the libraries in requirements.txt.

  Safe to run again at any time: finished steps are skipped.

.PARAMETER Check
  Only report what is installed. Changes nothing.

.PARAMETER ForcePortable
  Ignore tools already installed on this PC and put portable copies in .\tools.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File setup.ps1
.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File setup.ps1 -Check
#>
[CmdletBinding()]
param(
    [switch]$Check,
    [switch]$ForcePortable
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # Invoke-WebRequest is very slow with the progress bar on
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
} catch { }

# ---------------------------------------------------------------- settings
$Root          = $PSScriptRoot
$Tools         = Join-Path $Root 'tools'
$Downloads     = Join-Path $Tools '_downloads'
$FfmpegDir     = Join-Path $Tools 'ffmpeg\bin'
$NodeDir       = Join-Path $Tools 'node'
$UvDir         = Join-Path $Tools 'uv'
$PythonDir     = Join-Path $Tools 'python'
$Venv          = Join-Path $Root '.venv'
$VenvPython    = Join-Path $Venv 'Scripts\python.exe'
$PythonVersion = '3.12'
$NodeMinMajor  = 22     # HyperFrames needs Node.js 22 or newer
$NodeMajor     = 24     # LTS line downloaded when Node.js is missing
$FfmpegUrl     = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'
$IsArm         = $env:PROCESSOR_ARCHITECTURE -eq 'ARM64'

# ---------------------------------------------------------------- output helpers
function Write-Step([string]$Text) { Write-Host ''; Write-Host "== $Text" -ForegroundColor Cyan }
function Write-Ok([string]$Text)   { Write-Host "   OK       $Text" -ForegroundColor Green }
function Write-Note([string]$Text) { Write-Host "   ..       $Text" }
function Write-Miss([string]$Text) { Write-Host "   MISSING  $Text" -ForegroundColor Yellow }
function Write-Warn2([string]$Text){ Write-Host "   WARNING  $Text" -ForegroundColor Yellow }

# Runs a program, shows its output indented, and stops the setup if it fails.
function Invoke-Native {
    param([string]$Exe, [string[]]$Arguments = @(), [switch]$Silent)
    $old = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $lines = & $Exe @Arguments 2>&1 | ForEach-Object { "$_" }
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $old
    }
    if (-not $Silent -or $code -ne 0) {
        foreach ($l in $lines) { if ($l.Trim()) { Write-Host "            $l" } }
    }
    if ($code -ne 0) { throw "$([IO.Path]::GetFileName($Exe)) failed with exit code $code." }
    return $lines
}

function Find-Program([string]$Name) {
    $cmd = Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cmd) { return $cmd.Source }
    return $null
}

function Get-RemoteText([string]$Url) {
    $curl = Join-Path $env:SystemRoot 'System32\curl.exe'
    if (Test-Path $curl) {
        return ((Invoke-Native $curl @('-L', '--fail', '--silent', '--show-error', '--retry', '3', $Url) -Silent) -join "`n")
    }
    $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing
    if ($resp.Content -is [byte[]]) { return [Text.Encoding]::UTF8.GetString($resp.Content) }
    return [string]$resp.Content
}

function Save-RemoteFile([string]$Url, [string]$Dest) {
    Write-Note "Downloading $Url"
    New-Item -ItemType Directory -Force -Path (Split-Path $Dest) | Out-Null
    $curl = Join-Path $env:SystemRoot 'System32\curl.exe'
    if (Test-Path $curl) {
        Invoke-Native $curl @('-L', '--fail', '--silent', '--show-error', '--retry', '3', '-o', $Dest, $Url) -Silent | Out-Null
    } else {
        Invoke-WebRequest -Uri $Url -OutFile $Dest -UseBasicParsing
    }
}

function Assert-Sha256([string]$File, [string]$ChecksumText) {
    $m = [regex]::Match($ChecksumText, '[0-9a-fA-F]{64}')
    if (-not $m.Success) { Write-Warn2 'No checksum published for this download; skipping the check.'; return }
    $actual = (Get-FileHash -Algorithm SHA256 -Path $File).Hash
    if ($actual -ne $m.Value.ToUpper()) {
        throw "Checksum mismatch for $(Split-Path $File -Leaf). The download is damaged or was tampered with. Run the setup again."
    }
    Write-Note 'Checksum verified'
}

function Expand-ZipFile([string]$Zip, [string]$Dest) {
    if (Test-Path $Dest) { Remove-Item $Dest -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $Dest | Out-Null
    $tar = Join-Path $env:SystemRoot 'System32\tar.exe'   # Windows 10+ tar can unpack .zip and is much faster
    if (Test-Path $tar) { Invoke-Native $tar @('-xf', $Zip, '-C', $Dest) -Silent | Out-Null }
    else { Expand-Archive -Path $Zip -DestinationPath $Dest -Force }
}

function Get-NodeMajor([string]$Exe) {
    try {
        $v = Invoke-Native $Exe @('--version') -Silent
        if ("$v" -match 'v(\d+)\.') { return [int]$Matches[1] }
    } catch { }
    return 0
}

# ---------------------------------------------------------------- tool status
function Get-FfmpegStatus {
    $f = Join-Path $FfmpegDir 'ffmpeg.exe'
    $p = Join-Path $FfmpegDir 'ffprobe.exe'
    if ((Test-Path $f) -and (Test-Path $p)) { return @{ Where = 'portable copy in tools\ffmpeg'; Ffmpeg = $f; Ffprobe = $p } }
    if (-not $ForcePortable) {
        $f = Find-Program 'ffmpeg'; $p = Find-Program 'ffprobe'
        if ($f -and $p) { return @{ Where = 'already installed on this PC'; Ffmpeg = $f; Ffprobe = $p } }
    }
    return $null
}

function Get-NodeStatus {
    $local = Join-Path $NodeDir 'node.exe'
    if (Test-Path $local) { return @{ Where = 'portable copy in tools\node'; Node = $local; Dir = $NodeDir } }
    if (-not $ForcePortable) {
        $n = Find-Program 'node'
        if ($n -and ((Get-NodeMajor $n) -ge $NodeMinMajor)) { return @{ Where = 'already installed on this PC'; Node = $n; Dir = (Split-Path $n) } }
    }
    return $null
}

function Get-UvPath {
    $local = Join-Path $UvDir 'uv.exe'
    if (Test-Path $local) { return $local }
    if (-not $ForcePortable) { return (Find-Program 'uv') }
    return $null
}

function Test-Venv {
    if (-not (Test-Path $VenvPython)) { return $false }
    try { Invoke-Native $VenvPython @('-c', 'import sys') -Silent | Out-Null; return $true } catch { return $false }
}

$RequiredImports = 'import numpy, moviepy, faster_whisper'
$OptionalImports = 'import scenedetect, cv2'   # scene detection (optional)

function Test-PythonLibraries {
    if (-not (Test-Venv)) { return $false }
    try {
        Invoke-Native $VenvPython @('-c', $RequiredImports) -Silent | Out-Null
        return $true
    } catch { return $false }
}

function Test-SceneDetection {
    if (-not (Test-Venv)) { return $false }
    try { Invoke-Native $VenvPython @('-c', $OptionalImports) -Silent | Out-Null; return $true } catch { return $false }
}

function Test-Hyperframes {
    return ((Test-Path (Join-Path $Root 'node_modules\hyperframes\package.json')) -and
            (Test-Path (Join-Path $Root 'node_modules\gsap\package.json')))
}

# ---------------------------------------------------------------- installers
function Install-Ffmpeg {
    $zip = Join-Path $Downloads 'ffmpeg.zip'
    Save-RemoteFile $FfmpegUrl $zip
    Assert-Sha256 $zip (Get-RemoteText "$FfmpegUrl.sha256")
    $unpacked = Join-Path $Downloads 'ffmpeg'
    Expand-ZipFile $zip $unpacked
    $exe = Get-ChildItem -Path $unpacked -Recurse -Filter 'ffmpeg.exe' | Select-Object -First 1
    if (-not $exe) { throw 'ffmpeg.exe was not found inside the download.' }
    New-Item -ItemType Directory -Force -Path $FfmpegDir | Out-Null
    foreach ($name in 'ffmpeg.exe', 'ffprobe.exe') {   # ffplay.exe is not needed (saves ~100 MB)
        Copy-Item -Path (Join-Path $exe.DirectoryName $name) -Destination $FfmpegDir -Force
    }
}

function Install-Node {
    $arch = if ($IsArm) { 'arm64' } else { 'x64' }
    $base = "https://nodejs.org/dist/latest-v$NodeMajor.x"
    $sums = Get-RemoteText "$base/SHASUMS256.txt"
    $line = ($sums -split "`r?`n") | ForEach-Object { $_.Trim() } | Where-Object { $_ -match "node-v[\d\.]+-win-$arch\.zip$" } | Select-Object -First 1
    if (-not $line) { throw "Could not find a Node.js $NodeMajor download for win-$arch." }
    $parts = $line -split '\s+'
    $zip = Join-Path $Downloads $parts[1]
    Save-RemoteFile "$base/$($parts[1])" $zip
    Assert-Sha256 $zip $parts[0]
    $unpacked = Join-Path $Downloads 'node'
    Expand-ZipFile $zip $unpacked
    $inner = Get-ChildItem -Path $unpacked -Directory | Select-Object -First 1
    if (Test-Path $NodeDir) { Remove-Item $NodeDir -Recurse -Force }
    Move-Item -Path $inner.FullName -Destination $NodeDir
}

function Install-Uv {
    $arch = if ($IsArm) { 'aarch64' } else { 'x86_64' }
    $name = "uv-$arch-pc-windows-msvc.zip"
    $url = "https://github.com/astral-sh/uv/releases/latest/download/$name"
    $zip = Join-Path $Downloads $name
    Save-RemoteFile $url $zip
    Assert-Sha256 $zip (Get-RemoteText "$url.sha256")
    $unpacked = Join-Path $Downloads 'uv'
    Expand-ZipFile $zip $unpacked
    New-Item -ItemType Directory -Force -Path $UvDir | Out-Null
    Get-ChildItem -Path $unpacked -Recurse -Filter 'uv*.exe' | Copy-Item -Destination $UvDir -Force
}

# ---------------------------------------------------------------- check mode
if ($Check) {
    Write-Host 'Claude video editor - setup check' -ForegroundColor Cyan
    $missing = 0
    $ff = Get-FfmpegStatus
    if ($ff) { Write-Ok "FFmpeg + ffprobe   ($($ff.Where))" } else { Write-Miss 'FFmpeg + ffprobe'; $missing++ }
    $nd = Get-NodeStatus
    if ($nd) { Write-Ok "Node.js $NodeMinMajor+        ($($nd.Where))" } else { Write-Miss "Node.js $NodeMinMajor+"; $missing++ }
    if (Test-Venv) { Write-Ok 'Python environment (.venv)' } else { Write-Miss 'Python environment (.venv)'; $missing++ }
    if (Test-PythonLibraries) { Write-Ok 'Python libraries (requirements.txt)' } else { Write-Miss 'Python libraries (requirements.txt)'; $missing++ }
    if (Test-SceneDetection) { Write-Ok 'Scene detection (optional)' } elseif (Test-Venv) { Write-Warn2 'Scene detection (optional) is unavailable; run the setup again to repair it.' }
    if (Test-Hyperframes) { Write-Ok 'HyperFrames (node_modules)' } else { Write-Miss 'HyperFrames (node_modules)'; $missing++ }
    foreach ($d in 'input', 'output') {
        if (Test-Path (Join-Path $Root $d)) { Write-Ok "$d\ folder" } else { Write-Miss "$d\ folder"; $missing++ }
    }
    Write-Host ''
    if ($missing -eq 0) { Write-Host 'Everything is ready.' -ForegroundColor Green; exit 0 }
    Write-Host "$missing item(s) missing. Run: powershell -NoProfile -ExecutionPolicy Bypass -File setup.ps1" -ForegroundColor Yellow
    exit 1
}

# ---------------------------------------------------------------- setup
$started = Get-Date
Write-Host 'Claude video editor - setup' -ForegroundColor Cyan
Write-Host "Folder: $Root"
Write-Host 'Everything missing is downloaded into this folder only (tools\, .venv\, node_modules\).'

try {
    Write-Step '1/6  Folders'
    foreach ($d in 'input', 'output', 'work', 'tools') {
        New-Item -ItemType Directory -Force -Path (Join-Path $Root $d) | Out-Null
    }
    Write-Ok 'input\ (raw videos), output\ (finished videos), work\ (scratch), tools\ (portable programs)'

    Write-Step '2/6  FFmpeg + ffprobe'
    $ff = Get-FfmpegStatus
    if (-not $ff) {
        Write-Note 'Not found. Installing a portable copy into tools\ffmpeg (about 100 MB)...'
        Install-Ffmpeg
        $ff = Get-FfmpegStatus
    }
    $ffVersion = (Invoke-Native $ff.Ffmpeg @('-version') -Silent | Select-Object -First 1)
    Write-Ok "$ffVersion  [$($ff.Where)]"

    Write-Step "3/6  Node.js $NodeMinMajor+"
    $nd = Get-NodeStatus
    if (-not $nd) {
        Write-Note "Not found (or older than $NodeMinMajor). Installing portable Node.js $NodeMajor LTS into tools\node..."
        Install-Node
        $nd = Get-NodeStatus
    }
    $nodeVersion = (Invoke-Native $nd.Node @('--version') -Silent | Select-Object -First 1)
    Write-Ok "Node.js $nodeVersion  [$($nd.Where)]"

    Write-Step "4/6  Python $PythonVersion environment (.venv)"
    $uv = Get-UvPath
    if (-not $uv) {
        Write-Note 'Installing uv (a small, fast Python installer) into tools\uv...'
        Install-Uv
        $uv = Get-UvPath
    }
    # Keep uv's downloads and cache inside this folder.
    $env:UV_PYTHON_INSTALL_DIR = $PythonDir
    $env:UV_PYTHON_BIN_DIR     = Join-Path $PythonDir 'bin'
    $env:UV_CACHE_DIR          = Join-Path $Tools 'uv-cache'
    $env:UV_PYTHON_PREFERENCE  = if ($ForcePortable) { 'only-managed' } else { 'managed' }
    if (Test-Venv) {
        Write-Ok '.venv already exists'
    } else {
        Write-Note "Creating .venv with Python $PythonVersion (uses an installed Python $PythonVersion if there is one, otherwise downloads a portable one into tools\python)..."
        Invoke-Native $uv @('venv', $Venv, '--python', $PythonVersion, '--seed', '--clear') | Out-Null
    }
    $pyVersion = (Invoke-Native $VenvPython @('--version') -Silent | Select-Object -First 1)
    Write-Ok "$pyVersion in .venv"

    Write-Step '5/6  Python libraries (requirements.txt)'
    Write-Note 'Installing numpy, moviepy, faster-whisper, scenedetect, opencv, auto-editor... (first run takes a few minutes)'
    Invoke-Native $uv @('pip', 'install', '--python', $VenvPython, '-r', (Join-Path $Root 'requirements.txt')) -Silent | Out-Null
    Invoke-Native $VenvPython @('-c', $RequiredImports) -Silent | Out-Null
    Write-Ok 'Python libraries installed and importable'
    if (Test-SceneDetection) { Write-Ok 'Scene detection ready' }
    else { Write-Warn2 'Scene detection (optional) could not load OpenCV. Everything else works; run the setup again later to retry.' }
    $autoEditor = Join-Path $Venv 'Scripts\auto-editor.exe'
    if (Test-Path $autoEditor) {
        try {   # the pip package fetches its program on first use; do it now so later runs work offline
            $env:PYTHONUNBUFFERED = '1'   # keep its download messages before the version line
            $aeVersion = (Invoke-Native $autoEditor @('--version') -Silent | Select-Object -Last 1)
            Write-Ok "auto-editor $aeVersion ready"
        } catch {
            Write-Warn2 'auto-editor could not fetch its program yet (optional; the dead-air cutter does not need it).'
        }
    }

    Write-Step '6/6  HyperFrames (HTML-to-video)'
    $env:Path = "$($nd.Dir);$(Split-Path $ff.Ffmpeg);$env:Path"
    $npm = Join-Path $nd.Dir 'npm.cmd'
    if (-not (Test-Path $npm)) { $npm = Find-Program 'npm' }
    if (-not $npm) { throw 'npm was not found next to Node.js. Re-run with -ForcePortable to get a complete portable Node.js.' }
    Push-Location $Root
    try {
        Invoke-Native $npm @('install', '--no-fund', '--no-audit', '--loglevel=error') -Silent | Out-Null
    } finally { Pop-Location }
    $hfCli = Join-Path $Root 'node_modules\hyperframes\bin\hyperframes.mjs'
    $hfVersion = (Invoke-Native $nd.Node @($hfCli, '--version') -Silent | Select-Object -Last 1)
    Write-Ok "HyperFrames $hfVersion"
    Write-Note 'Downloading the headless Chrome that HyperFrames renders with (once, into your user cache)...'
    $env:HYPERFRAMES_FFMPEG_PATH  = $ff.Ffmpeg
    $env:HYPERFRAMES_FFPROBE_PATH = $ff.Ffprobe
    $env:HYPERFRAMES_NO_TELEMETRY = '1'   # no usage telemetry
    $env:HYPERFRAMES_SKIP_SKILLS  = '1'   # no skill installs into the user profile
    try {
        Invoke-Native $nd.Node @($hfCli, 'browser', 'ensure') -Silent | Out-Null
        Write-Ok 'HyperFrames browser ready'
    } catch {
        Write-Warn2 "HyperFrames could not prepare its browser yet ($($_.Exception.Message)). It will retry on first render. Dead-air cutting does not need it."
    }
}
catch {
    Write-Host ''
    Write-Host "SETUP STOPPED: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'Fix the problem above (often a network hiccup) and run the setup again. Finished steps are skipped.' -ForegroundColor Red
    exit 1
}
finally {
    if (Test-Path $Downloads) { Remove-Item $Downloads -Recurse -Force -ErrorAction SilentlyContinue }
}

$secs = [int]((Get-Date) - $started).TotalSeconds
Write-Host ''
Write-Host "Setup complete in $secs s." -ForegroundColor Green
Write-Host 'Next: put raw videos in input\, open this folder in Claude Code and say "edit my videos".'
Write-Host 'Finished videos appear in output\.'
exit 0
