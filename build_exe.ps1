# Builds a standalone "dist\YT Downloader\YT Downloader.exe" (no Python needed to run it).
# FFmpeg and Deno are copied into dist\YT Downloader\bin so the folder works on any PC.
# Run setup.bat first.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$py = '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { throw 'Run setup.bat first.' }

& $py -m pip install --upgrade --quiet --disable-pip-version-check pyinstaller
& $py -m PyInstaller --noconfirm --clean --windowed `
    --name 'YT Downloader' `
    --icon 'assets\icon.ico' `
    --add-data 'assets;assets' `
    --collect-data customtkinter `
    --collect-all yt_dlp_ejs `
    run.pyw
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }

$bin = 'dist\YT Downloader\bin'
New-Item -ItemType Directory -Force $bin | Out-Null
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + [Environment]::GetEnvironmentVariable('Path', 'Machine')
foreach ($tool in 'ffmpeg', 'ffprobe', 'deno') {
    $cmd = Get-Command $tool -ErrorAction SilentlyContinue
    if ($cmd) {
        $src = (Get-Item $cmd.Source)
        if ($src.LinkType -eq 'SymbolicLink' -and $src.Target) {  # winget installs aliases as symlinks
            $t = @($src.Target)[0]
            if (-not [IO.Path]::IsPathRooted($t)) { $t = Join-Path $src.DirectoryName $t }
            $src = Get-Item $t
        }
        Copy-Item $src.FullName $bin -Force
        Write-Host "Bundled $tool"
        if ($tool -eq 'ffmpeg') {  # FFmpeg is GPL: ship its licence alongside it
            $lic = Join-Path $src.Directory.Parent.FullName 'LICENSE'
            if (Test-Path $lic) { Copy-Item $lic (Join-Path $bin 'FFMPEG-LICENSE.txt') -Force }
            else { Write-Warning 'FFmpeg LICENSE file not found; add it to bin\FFMPEG-LICENSE.txt before sharing.' }
        }
    } else {
        Write-Warning "$tool not found; the .exe will need it installed separately."
    }
}
Copy-Item 'THIRD-PARTY-NOTICES.txt', 'README.md' 'dist\YT Downloader' -Force
Write-Host "`nDone: dist\YT Downloader\YT Downloader.exe" -ForegroundColor Green
