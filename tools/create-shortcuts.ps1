# Creates Desktop and Start Menu shortcuts named "AI Influencer Studio".
param(
    [Parameter(Mandatory = $true)]
    [string]$AppDir,
    [string]$IconPath = ""
)

$ErrorActionPreference = "Stop"
$AppDir = [System.IO.Path]::GetFullPath($AppDir)
$launcher = Join-Path $AppDir "launcher.py"
$vbs = Join-Path $AppDir "pokreni.vbs"
if (-not $IconPath) { $IconPath = Join-Path $AppDir "app.ico" }

function Get-LaunchTarget {
    $pyw = "C:\ComfyUI-Zluda\venv\Scripts\pythonw.exe"
    $py = "C:\ComfyUI-Zluda\venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $pyw) {
        return @{ Target = $pyw; Arguments = "`"$launcher`""; WindowStyle = 7 }
    }
    if (Test-Path -LiteralPath $py) {
        return @{ Target = $py; Arguments = "`"$launcher`""; WindowStyle = 7 }
    }
    if (Test-Path -LiteralPath $vbs) {
        $wscript = Join-Path $env:SystemRoot "System32\wscript.exe"
        return @{ Target = $wscript; Arguments = "`"$vbs`""; WindowStyle = 7 }
    }
    $pyCmd = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCmd) {
        return @{ Target = $pyCmd.Source; Arguments = "-3.11 `"$launcher`""; WindowStyle = 7 }
    }
    throw "Nisam nasao Python za precac (C:\ComfyUI-Zluda\venv ili py -3.11)."
}

$launch = Get-LaunchTarget
$Wsh = New-Object -ComObject WScript.Shell
$name = "AI Influencer Studio.lnk"

$destinations = @()
$desktop = [Environment]::GetFolderPath("Desktop")
if ($desktop) { $destinations += (Join-Path $desktop $name) }
$start = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
if (-not (Test-Path -LiteralPath $start)) { New-Item -ItemType Directory -Path $start -Force | Out-Null }
$destinations += (Join-Path $start $name)

foreach ($lnk in $destinations) {
    $s = $Wsh.CreateShortcut($lnk)
    $s.TargetPath = $launch.Target
    $s.Arguments = $launch.Arguments
    $s.WorkingDirectory = $AppDir
    $s.WindowStyle = 7
    $s.Description = "AI Influencer Studio"
    if (Test-Path -LiteralPath $IconPath) {
        # ",0" bira prvu ikonu u ICO-u; novi zapis tjera Explorer da ne drzi stari cache.
        $s.IconLocation = "$IconPath,0"
    }
    $s.Save()
    Write-Host "Napravljen precac: $lnk"
}

# Osvjezi Windowsev cache ikona (inace prečac često ostane na staroj ikoni).
$notifyPaths = @()
if (Test-Path -LiteralPath $IconPath) { $notifyPaths += $IconPath }
$notifyPaths += $destinations
try {
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class StudioShellNotify {
    [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
    public static extern void SHChangeNotify(int eventId, uint flags, string item1, string item2);
    [DllImport("shell32.dll")]
    public static extern void SHChangeNotify(int eventId, uint flags, IntPtr item1, IntPtr item2);
}
"@
    foreach ($p in $notifyPaths) {
        try { [StudioShellNotify]::SHChangeNotify(0x00002000, 0x1005, [string]$p, $null) } catch {}
    }
    [StudioShellNotify]::SHChangeNotify(0x08000000, 0x1000, [IntPtr]::Zero, [IntPtr]::Zero)
    Write-Host "SHChangeNotify poslan"
} catch {
    Write-Host "SHChangeNotify nije uspio: $_"
}
$ie4 = Join-Path $env:SystemRoot "System32\ie4uinit.exe"
if (Test-Path -LiteralPath $ie4) {
    try {
        & $ie4 -show | Out-Null
        Write-Host "ie4uinit -show"
    } catch {
        Write-Host "ie4uinit: $_"
    }
}
