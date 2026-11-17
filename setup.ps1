# One-time setup for YT Downloader (Windows).
# Installs Python, FFmpeg and Deno if they're missing (via winget), creates a
# virtual environment with the Python packages, and adds Desktop + Start Menu shortcuts.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

function Have($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'User') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'Machine')
}

function Winget-Install($id, $name) {
    if (-not (Have 'winget')) {
        Write-Host "  winget isn't available. Please install $name manually, then run setup again." -ForegroundColor Yellow
        return
    }
    Write-Host "  Installing $name..." -ForegroundColor Cyan
    winget install --id $id -e --silent --accept-package-agreements --accept-source-agreements --disable-interactivity | Out-Host
    Refresh-Path
}

function Get-PythonExe {
    $tries = @(@{ cmd = 'py'; args = @('-3') }, @{ cmd = 'python'; args = @() })
    foreach ($t in $tries) {
        if (-not (Have $t.cmd)) { continue }
        try {
            $code = 'import sys; print(sys.executable if sys.version_info >= (3, 10) else "")'
            $exe = & $t.cmd @($t.args + @('-c', $code)) 2>$null
        } catch { $exe = $null }
        if ($exe -and (Test-Path $exe.Trim())) { return $exe.Trim() }
    }
    return $null
}

Write-Host "`n== YT Downloader setup ==`n" -ForegroundColor White

# 1. Python
Write-Host "[1/4] Python"
$py = Get-PythonExe
if (-not $py) {
    Winget-Install 'Python.Python.3.13' 'Python 3.13'
    $py = Get-PythonExe
    if (-not $py) {
        $guess = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'
        if (Test-Path $guess) { $py = $guess }
    }
}
if (-not $py) { throw "Python 3.10+ is required. Install it from https://www.python.org and run setup again." }
Write-Host "  Using $py" -ForegroundColor DarkGray

# 2. FFmpeg (merging video+audio, MP3 conversion) and Deno (needed by yt-dlp for YouTube)
Write-Host "[2/4] FFmpeg and Deno"
if (-not (Have 'ffmpeg')) { Winget-Install 'Gyan.FFmpeg' 'FFmpeg' } else { Write-Host "  FFmpeg found" -ForegroundColor DarkGray }
if (-not (Have 'deno'))   { Winget-Install 'DenoLand.Deno' 'Deno' } else { Write-Host "  Deno found" -ForegroundColor DarkGray }

# 3. Virtual environment + packages
Write-Host "[3/4] Python packages"
if (-not (Test-Path '.venv\Scripts\python.exe')) { & $py -m venv .venv }
& .venv\Scripts\python.exe -m pip install --upgrade --quiet --disable-pip-version-check pip
& .venv\Scripts\python.exe -m pip install --upgrade --quiet --disable-pip-version-check -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

# 4. Shortcuts
Write-Host "[4/4] Shortcuts"
$shell = New-Object -ComObject WScript.Shell
$targets = @(
    (Join-Path ([Environment]::GetFolderPath('Desktop')) 'YT Downloader.lnk'),
    (Join-Path ([Environment]::GetFolderPath('Programs')) 'YT Downloader.lnk')
)
foreach ($lnkPath in $targets) {
    $lnk = $shell.CreateShortcut($lnkPath)
    $lnk.TargetPath = Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'
    $lnk.Arguments = '"' + (Join-Path $PSScriptRoot 'run.pyw') + '"'
    $lnk.WorkingDirectory = $PSScriptRoot
    $lnk.IconLocation = Join-Path $PSScriptRoot 'assets\icon.ico'
    $lnk.Description = 'Download YouTube videos as MP4 or MP3'
    $lnk.Save()
}
Write-Host "  Added 'YT Downloader' to your Desktop and Start Menu" -ForegroundColor DarkGray

Write-Host "`nAll set! Launching YT Downloader...`n" -ForegroundColor Green
Start-Process (Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe') -ArgumentList ('"' + (Join-Path $PSScriptRoot 'run.pyw') + '"') -WorkingDirectory $PSScriptRoot
