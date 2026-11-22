# setup_dev_windows.ps1
# Priprema razvojnog checkouta AI Influencer Studio na Windowsu (korisnik svenb).
#
# Pokreni jednom, npr. iz PowerShell-a:
#   powershell -ExecutionPolicy Bypass -File tools\setup_dev_windows.ps1
# Ako PowerShell i dalje blokira skriptu (ExecutionPolicy):
#   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
# pa ponovo pokreni, ili ostavi Bypass kao gore.
#
# Skripta:
#   - provjerava git, gh, Python, Node i Git Bash
#   - po tvojoj potvrdi (d/n) predlaze winget instalaciju onoga sto fali
#   - klonira ili azurira checkout u C:\Users\svenb\dev\ai-influencer-studio
#   - pokrece provjeru UI JS-a i testove koji rade na Windowsu
#   - provjerava ovisnosti tools/make_release.sh u Git Bashu, BEZ pokretanja skripte
#   - pise izvjestaj u C:\Users\svenb\dev\setup_report.txt
#
# NE dira instalacijsku mapu %LOCALAPPDATA%\AIInfluencerStudio\app
#   (to nije razvojni checkout).
# Nikad ne trazi, ne sprema i ne ispisuje tokene ni kljuceve.
# Ako gh nije prijavljen, sam pokreni:  gh auth login
#
# Kompatibilno s Windows PowerShell 5.1 i novijim.

#Requires -Version 5.1
$ErrorActionPreference = "Continue"

$RepoUrl = "https://github.com/Spinojpg/ai-influencer-studio.git"
$RepoSlug = "Spinojpg/ai-influencer-studio"
$RepoDir = "C:\Users\svenb\dev\ai-influencer-studio"
$DevRoot = "C:\Users\svenb\dev"
$ReportPath = "C:\Users\svenb\dev\setup_report.txt"
$Branch = "main"

$InstallRoot = Join-Path $env:LOCALAPPDATA "AIInfluencerStudio"

# -----------------------------------------------------------------------------
# Pomocne funkcije
# -----------------------------------------------------------------------------

$script:ReportLines = New-Object System.Collections.Generic.List[string]
$script:FailCount = 0
$script:WarnCount = 0

function Add-Log {
    param(
        [string]$Message,
        [ValidateSet("INFO", "OK", "FAIL", "WARN", "HEAD")]
        [string]$Level = "INFO"
    )
    $prefix = $Level
    if ($Level -eq "HEAD") { $prefix = "" }
    if ($Level -eq "FAIL") { $script:FailCount++ }
    if ($Level -eq "WARN") { $script:WarnCount++ }
    if ($prefix) {
        $line = "[{0}] {1}" -f $prefix, $Message
    } else {
        $line = $Message
    }
    [void]$script:ReportLines.Add($line)
    switch ($Level) {
        "OK"   { Write-Host $line -ForegroundColor Green }
        "FAIL" { Write-Host $line -ForegroundColor Red }
        "WARN" { Write-Host $line -ForegroundColor Yellow }
        "HEAD" { Write-Host $line -ForegroundColor Cyan }
        default { Write-Host $line }
    }
}

function Test-IsUnderPath {
    param([string]$Child, [string]$Parent)
    if ([string]::IsNullOrWhiteSpace($Child) -or [string]::IsNullOrWhiteSpace($Parent)) {
        return $false
    }
    $c = [System.IO.Path]::GetFullPath($Child).TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
    $p = [System.IO.Path]::GetFullPath($Parent).TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
    return $c.StartsWith($p, [System.StringComparison]::OrdinalIgnoreCase)
}

function Test-Interactive {
    try {
        if (-not [Environment]::UserInteractive) { return $false }
        if ($null -eq [Console]::In) { return $false }
        if ([Console]::IsInputRedirected) { return $false }
        return $true
    } catch {
        return $false
    }
}

function Ask-YesNo {
    param([string]$Question)
    if (-not (Test-Interactive)) {
        Add-Log "Nisam u interaktivnom nacinu; preskacem instalaciju. ($Question)" "WARN"
        return $false
    }
    while ($true) {
        $r = Read-Host "$Question [d/n]"
        if ($r -match '^[dDyY]') { return $true }
        if ($r -match '^[nN]') { return $false }
        Write-Host "Odgovori s d (da) ili n (ne)."
    }
}

function Find-Exe {
    param(
        [string[]]$Names,
        [string[]]$ExtraPaths
    )
    foreach ($n in $Names) {
        $cmd = Get-Command $n -ErrorAction SilentlyContinue
        if ($cmd -and $cmd.Source) { return [string]$cmd.Source }
        if ($cmd -and $cmd.Path) { return [string]$cmd.Path }
    }
    if ($ExtraPaths) {
        foreach ($p in $ExtraPaths) {
            if ($p -and (Test-Path -LiteralPath $p)) { return $p }
        }
    }
    return $null
}

function Get-ExeVersion {
    param(
        [string]$Exe,
        [string[]]$Args
    )
    if (-not $Exe) { return "" }
    if (-not $Args) { $Args = @("--version") }
    try {
        $out = & $Exe @Args 2>&1 | Out-String
        $text = $out.Trim()
        if ($text.Length -gt 400) { $text = $text.Substring(0, 400) }
        return ($text -replace "\r\n", " " -replace "\n", " ").Trim()
    } catch {
        return "(nije uspjelo procitati verziju: $($_.Exception.Message))"
    }
}

function Refresh-SessionPath {
    try {
        $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
        $user = [Environment]::GetEnvironmentVariable("Path", "User")
        $parts = @()
        if ($machine) { $parts += $machine }
        if ($user) { $parts += $user }
        if ($parts.Count -gt 0) {
            $env:PATH = [string]::Join(";", $parts)
        }
    } catch {
        Add-Log "Nisam mogao osvjeziti PATH iz registra: $($_.Exception.Message)" "WARN"
    }
}

function Add-ToPathIfExists {
    param([string]$Dir)
    if ($Dir -and (Test-Path -LiteralPath $Dir)) {
        $env:PATH = "$Dir;$env:PATH"
    }
}

function Invoke-WingetInstall {
    param([string]$PackageId, [string]$Title)
    $winget = Find-Exe -Names @("winget") -ExtraPaths @(
        (Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps\winget.exe")
    )
    if (-not $winget) {
        Add-Log "winget nije dostupan, ne mogu instalirati $Title ($PackageId). Instaliraj rucno ili App Installer iz Microsoft Storea." "FAIL"
        return $false
    }
    Add-Log "Pokrecem: winget install --id $PackageId -e --accept-source-agreements --accept-package-agreements"
    & $winget install --id $PackageId -e --accept-source-agreements --accept-package-agreements
    $code = $LASTEXITCODE
    # 0 = uspjeh, -1978335189 (0x8A15002B) cesto znaci "vec instalirano"
    if ($code -eq 0 -or $code -eq -1978335189) {
        Add-Log "$Title je instaliran ili je vec bio prisutan (winget izlaz $code)." "OK"
        Refresh-SessionPath
        return $true
    }
    Add-Log "winget install $PackageId nije uspio (izlaz $code)." "FAIL"
    return $false
}

function Get-GitBashPath {
    return Find-Exe -Names @("bash") -ExtraPaths @(
        "C:\Program Files\Git\bin\bash.exe",
        "C:\Program Files (x86)\Git\bin\bash.exe",
        (Join-Path $env:LOCALAPPDATA "Programs\Git\bin\bash.exe")
    )
}

function Enable-GitBashOnPath {
    param([string]$BashExe)
    if (-not $BashExe) { return }
    $bin = Split-Path -Parent $BashExe
    $root = Split-Path -Parent $bin
    $usrBin = Join-Path $root "usr\bin"
    $cmdDir = Join-Path $root "cmd"
    Add-ToPathIfExists $bin
    Add-ToPathIfExists $usrBin
    Add-ToPathIfExists $cmdDir
}

# -----------------------------------------------------------------------------
# Provjera okruzenja
# -----------------------------------------------------------------------------

Add-Log "====================================================" "HEAD"
Add-Log "AI Influencer Studio — priprema razvojnog okruzenja" "HEAD"
Add-Log "====================================================" "HEAD"
Add-Log ("Datum: {0} (lokalno vrijeme ovog PC-a)" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
Add-Log ("PowerShell: {0}" -f $PSVersionTable.PSVersion.ToString())
Add-Log ("Korisnik: {0}" -f $env:USERNAME)
Add-Log ("Checkout: {0}" -f $RepoDir)
Add-Log ("Izvjestaj: {0}" -f $ReportPath)

if ($env:OS -ne "Windows_NT") {
    Add-Log "Ova skripta je namijenjena Windowsu. Na ovom sustavu je ne pokreci kao pripremu PC-a." "FAIL"
}

if ($env:USERNAME -and ($env:USERNAME -ne "svenb")) {
    Add-Log "Ocekivani Windows korisnik je svenb, a sada je '$($env:USERNAME)'. I dalje koristim $RepoDir kako je dogovoreno." "WARN"
}

if (Test-IsUnderPath -Child $RepoDir -Parent $InstallRoot) {
    Add-Log "ODBIJENO: putanja checkouta ($RepoDir) je unutar instalacijske mape ($InstallRoot). To ne smije biti razvojni checkout. Ispravi putanju i pokreni ponovo." "FAIL"
    # Jos uvijek cemo pokusati napisati izvjestaj ako je moguce, ali ne nastavljamo s klonom.
    $abortRepo = $true
} else {
    $abortRepo = $false
}

# -----------------------------------------------------------------------------
# 1) Alati
# -----------------------------------------------------------------------------

Add-Log "" "HEAD"
Add-Log "--- Alati ---" "HEAD"

Refresh-SessionPath

$gitExtra = @(
    "C:\Program Files\Git\cmd\git.exe",
    "C:\Program Files\Git\bin\git.exe"
)
$ghExtra = @(
    (Join-Path ${env:ProgramFiles} "GitHub CLI\gh.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "GitHub CLI\gh.exe")
)
$nodeExtra = @(
    (Join-Path ${env:ProgramFiles} "nodejs\node.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "nodejs\node.exe")
)
$pyExtra = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"),
    (Join-Path ${env:ProgramFiles} "Python312\python.exe")
)

$GitExe = Find-Exe -Names @("git") -ExtraPaths $gitExtra
$GhExe = Find-Exe -Names @("gh") -ExtraPaths $ghExtra
$NodeExe = Find-Exe -Names @("node") -ExtraPaths $nodeExtra
$PyLauncher = Find-Exe -Names @("py") -ExtraPaths @()
$PythonExe = Find-Exe -Names @("python", "python3") -ExtraPaths $pyExtra
$BashExe = Get-GitBashPath

# Preferiraj `py -3` za pokretanje testova ako postoji, inace python/python3.
$PythonRun = $null
$PythonRunArgs = @()
$PythonLabel = ""

if ($PyLauncher) {
    $ver = Get-ExeVersion -Exe $PyLauncher -Args @("-3", "--version")
    if ($ver -match "Python") {
        $PythonRun = $PyLauncher
        $PythonRunArgs = @("-3")
        $PythonLabel = "$PyLauncher -3  ($ver)"
        Add-Log "py (launcher): $PyLauncher  — $ver" "OK"
    } else {
        Add-Log "py postoji ($PyLauncher), ali 'py -3 --version' nije uspio: $ver" "WARN"
    }
}

if ($PythonExe) {
    $ver = Get-ExeVersion -Exe $PythonExe -Args @("--version")
    Add-Log "python: $PythonExe  — $ver" "OK"
    if (-not $PythonRun) {
        $PythonRun = $PythonExe
        $PythonRunArgs = @()
        $PythonLabel = "$PythonExe  ($ver)"
    }
}

if (-not $PythonRun) {
    Add-Log "Python nije pronaden (ni py -3, ni python, ni python3)." "FAIL"
} else {
    Add-Log "Za testove koristim: $PythonLabel"
}

if ($GitExe) {
    Add-Log "git: $GitExe  — $(Get-ExeVersion $GitExe @('--version'))" "OK"
} else {
    Add-Log "git nije pronaden." "FAIL"
}

if ($GhExe) {
    Add-Log "gh: $GhExe  — $(Get-ExeVersion $GhExe @('--version'))" "OK"
} else {
    Add-Log "gh (GitHub CLI) nije pronaden." "FAIL"
}

if ($NodeExe) {
    Add-Log "node: $NodeExe  — $(Get-ExeVersion $NodeExe @('--version'))" "OK"
} else {
    Add-Log "node nije pronaden. tools/check_ui_js.py i make_release.sh trebaju Node za provjeru UI JS-a." "FAIL"
}

if ($BashExe) {
    # Ako je "bash" iz WSL-a, to nije Git Bash; preferiraj Gitov bash.exe.
    $isWsl = $false
    try {
        $bashDir = Split-Path -Parent $BashExe
        if ($BashExe -match '\\Windows\\System32\\bash\.exe$' -or $BashExe -match '\\Microsoft\\WindowsApps\\bash\.exe$') {
            $isWsl = $true
        }
    } catch { }
    if ($isWsl -and (Test-Path -LiteralPath "C:\Program Files\Git\bin\bash.exe")) {
        $BashExe = "C:\Program Files\Git\bin\bash.exe"
        Add-Log "Nasao sam System32/WindowsApps bash (vjerojatno WSL). Koristim Git Bash: $BashExe" "WARN"
    }
    Add-Log "Git Bash: $BashExe  — $(Get-ExeVersion $BashExe @('--version'))" "OK"
    Enable-GitBashOnPath $BashExe
} else {
    Add-Log "Git Bash nije pronaden (ocekivano: C:\Program Files\Git\bin\bash.exe). tools/make_release.sh i dio test_updater.py trebaju bash." "FAIL"
}

# Ponudi instalaciju onoga sto fali
$missing = New-Object System.Collections.Generic.List[object]
if (-not $GitExe -or -not $BashExe) {
    [void]$missing.Add(@{ Id = "Git.Git"; Title = "Git za Windows (ukljucuje Git Bash)" })
}
if (-not $GhExe) {
    [void]$missing.Add(@{ Id = "GitHub.cli"; Title = "GitHub CLI (gh)" })
}
if (-not $PythonRun) {
    [void]$missing.Add(@{ Id = "Python.Python.3.12"; Title = "Python 3.12" })
}
if (-not $NodeExe) {
    [void]$missing.Add(@{ Id = "OpenJS.NodeJS.LTS"; Title = "Node.js LTS" })
}

if ($missing.Count -gt 0) {
    Add-Log "" "HEAD"
    Add-Log "Nedostaju alati. Predlozene winget naredbe:" "HEAD"
    foreach ($m in $missing) {
        Add-Log ("  winget install --id {0} -e --accept-source-agreements --accept-package-agreements   # {1}" -f $m.Id, $m.Title)
    }
    if (Ask-YesNo "Zelis li da sada pokusam instalirati nedostajuce alate preko wingeta?") {
        foreach ($m in $missing) {
            if (Ask-YesNo ("Instalirati {0} ({1})?" -f $m.Title, $m.Id)) {
                Invoke-WingetInstall -PackageId $m.Id -Title $m.Title | Out-Null
            } else {
                Add-Log ("Preskocena instalacija: {0}" -f $m.Title) "WARN"
            }
        }
        Refresh-SessionPath
        $GitExe = Find-Exe -Names @("git") -ExtraPaths $gitExtra
        $GhExe = Find-Exe -Names @("gh") -ExtraPaths $ghExtra
        $NodeExe = Find-Exe -Names @("node") -ExtraPaths $nodeExtra
        $PyLauncher = Find-Exe -Names @("py") -ExtraPaths @()
        $PythonExe = Find-Exe -Names @("python", "python3") -ExtraPaths $pyExtra
        $BashExe = Get-GitBashPath
        if ($PyLauncher -and ((Get-ExeVersion -Exe $PyLauncher -Args @("-3", "--version")) -match "Python")) {
            $PythonRun = $PyLauncher
            $PythonRunArgs = @("-3")
            $PythonLabel = "$PyLauncher -3"
        } elseif ($PythonExe) {
            $PythonRun = $PythonExe
            $PythonRunArgs = @()
            $PythonLabel = $PythonExe
        }
        if ($BashExe) { Enable-GitBashOnPath $BashExe }
        Add-Log "Ponovna provjera alata nakon instalacije: git=$(if ($GitExe) {'OK'} else {'NE'}), gh=$(if ($GhExe) {'OK'} else {'NE'}), python=$(if ($PythonRun) {'OK'} else {'NE'}), node=$(if ($NodeExe) {'OK'} else {'NE'}), bash=$(if ($BashExe) {'OK'} else {'NE'})"
    } else {
        Add-Log "Instalacija preskocena. Možeš kasnije sam pokrenuti naredbe iz izvjestaja." "WARN"
    }
}

# -----------------------------------------------------------------------------
# 2) gh prijava (bez tokena)
# -----------------------------------------------------------------------------

Add-Log "" "HEAD"
Add-Log "--- GitHub prijava (gh) ---" "HEAD"

$GhLoggedIn = $false
$GhAccount = ""
if ($GhExe) {
    $authOut = & $GhExe auth status 2>&1 | Out-String
    $authCode = $LASTEXITCODE
    # Ne ispisuj cijeli izlaz ako slucajno sadrzi osjetljivo; uzmi samo statusne linije bez tokena.
    $safeLines = @()
    foreach ($ln in ($authOut -split "`r?`n")) {
        if ($ln -match '(?i)token|secret|password|bearer|gho_|ghp_|github_pat') { continue }
        if ($ln.Trim()) { $safeLines += $ln.Trim() }
    }
    $safe = [string]::Join(" | ", $safeLines)
    if ($authCode -eq 0) {
        $GhLoggedIn = $true
        if ($authOut -match "account\s+(\S+)") { $GhAccount = $Matches[1] }
        Add-Log "gh je prijavljen$(if ($GhAccount) { ' kao ' + $GhAccount } else { '' }). $safe" "OK"
        # Povezi git s postojecom gh prijavom (ne pita za token, ne ispisuje ga).
        & $GhExe auth setup-git 2>&1 | Out-Null
    } else {
        Add-Log "gh nije prijavljen. Repo je privatan, pa klon/pull nece raditi dok se ne prijavis. Pokreni SAM:  gh auth login" "FAIL"
        Add-Log "U gh auth login odaberi GitHub.com, HTTPS i prijavu preko preglednika. Nikad ne lijepi token u chat ni u ovu skriptu." "WARN"
    }
} else {
    Add-Log "Preskacem 'gh auth status' jer gh nije instaliran." "WARN"
}

# -----------------------------------------------------------------------------
# 3) Checkout
# -----------------------------------------------------------------------------

Add-Log "" "HEAD"
Add-Log "--- Checkout ---" "HEAD"

$RepoReady = $false
if ($abortRepo) {
    Add-Log "Checkout je preskocen jer je putanja unutar instalacijske mape." "FAIL"
} elseif (Test-IsUnderPath -Child $RepoDir -Parent $InstallRoot) {
    Add-Log "ODBIJENO: $RepoDir je unutar $InstallRoot." "FAIL"
} elseif (-not $GitExe) {
    Add-Log "Ne mogu klonirati/azurirati repo jer git nije dostupan." "FAIL"
} else {
    if (-not (Test-Path -LiteralPath $DevRoot)) {
        try {
            New-Item -ItemType Directory -Path $DevRoot -Force | Out-Null
            Add-Log "Napravio mapu $DevRoot" "OK"
        } catch {
            Add-Log "Ne mogu napraviti $DevRoot : $($_.Exception.Message)" "FAIL"
        }
    }

    if (Test-Path -LiteralPath (Join-Path $RepoDir ".git")) {
        Add-Log "Checkout vec postoji: $RepoDir — radim git fetch, checkout $Branch, pull --ff-only."
        Push-Location $RepoDir
        try {
            & $GitExe fetch origin 2>&1 | ForEach-Object { $_.ToString() } | Tee-Object -Variable fetchOut | Out-Null
            if ($LASTEXITCODE -ne 0) {
                Add-Log "git fetch nije uspio (izlaz $LASTEXITCODE). Ako je repo privatan, prijavi se sa: gh auth login" "FAIL"
            } else {
                & $GitExe checkout $Branch 2>&1 | Out-Null
                if ($LASTEXITCODE -ne 0) {
                    Add-Log "git checkout $Branch nije uspio (izlaz $LASTEXITCODE)." "FAIL"
                } else {
                    & $GitExe pull --ff-only origin $Branch 2>&1 | ForEach-Object { $_.ToString() } | Tee-Object -Variable pullOut | Out-Null
                    if ($LASTEXITCODE -ne 0) {
                        Add-Log "git pull --ff-only nije uspio (izlaz $LASTEXITCODE). Ne radim force. Provjeri lokalne izmjene." "FAIL"
                    } else {
                        $head = (& $GitExe rev-parse --short HEAD 2>$null)
                        Add-Log "Checkout je azuran, grana $Branch, HEAD $head." "OK"
                        $RepoReady = $true
                    }
                }
            }
        } finally {
            Pop-Location
        }
    } elseif (Test-Path -LiteralPath $RepoDir) {
        $existing = @(Get-ChildItem -LiteralPath $RepoDir -Force -ErrorAction SilentlyContinue)
        if ($existing.Count -gt 0) {
            Add-Log "Putanja $RepoDir postoji, ali nije git repo. Ne diram je. Premjesti/obrisi je ili odaberi drugu mapu." "FAIL"
        } else {
            # prazna mapa — kloniraj u nju
            if (-not $GhLoggedIn -and -not $GhExe) {
                Add-Log "Repo je privatan. Bez gh prijave klon vjerojatno nece uspjeti." "WARN"
            }
            Add-Log "Kloniram $RepoSlug u $RepoDir ..."
            if ($GhExe -and $GhLoggedIn) {
                & $GhExe repo clone $RepoSlug $RepoDir
            } else {
                & $GitExe clone $RepoUrl $RepoDir
            }
            if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath (Join-Path $RepoDir ".git"))) {
                Push-Location $RepoDir
                try { & $GitExe checkout $Branch 2>&1 | Out-Null } finally { Pop-Location }
                $head = ""
                Push-Location $RepoDir
                try { $head = (& $GitExe rev-parse --short HEAD 2>$null) } finally { Pop-Location }
                Add-Log "Klon uspio, HEAD $head." "OK"
                $RepoReady = $true
            } else {
                Add-Log "Kloniranje nije uspjelo (izlaz $LASTEXITCODE). Ako je repo privatan, pokreni: gh auth login  pa ponovo ovu skriptu." "FAIL"
            }
        }
    } else {
        if (-not $GhLoggedIn) {
            Add-Log "Repo je privatan. Bez 'gh auth login' klon vjerojatno nece uspjeti. Ipak pokusavam." "WARN"
        }
        Add-Log "Kloniram $RepoSlug u $RepoDir ..."
        if ($GhExe -and $GhLoggedIn) {
            & $GhExe repo clone $RepoSlug $RepoDir
        } else {
            & $GitExe clone $RepoUrl $RepoDir
        }
        if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath (Join-Path $RepoDir ".git"))) {
            Push-Location $RepoDir
            try { & $GitExe checkout $Branch 2>&1 | Out-Null } finally { Pop-Location }
            $head = ""
            Push-Location $RepoDir
            try { $head = (& $GitExe rev-parse --short HEAD 2>$null) } finally { Pop-Location }
            Add-Log "Klon uspio, HEAD $head." "OK"
            $RepoReady = $true
        } else {
            Add-Log "Kloniranje nije uspjelo (izlaz $LASTEXITCODE). Pokreni SAM: gh auth login   pa ponovo ovu skriptu. Nikad ne lijepi token ovdje." "FAIL"
        }
    }
}

if ($RepoReady) {
    Push-Location $RepoDir
    try {
        $fullHead = (& $GitExe rev-parse HEAD 2>$null)
        $shortHead = (& $GitExe rev-parse --short HEAD 2>$null)
        $branchNow = (& $GitExe rev-parse --abbrev-ref HEAD 2>$null)
        Add-Log "Trenutno stanje: $branchNow @ $fullHead (kratko $shortHead)"
    } finally { Pop-Location }
}

# -----------------------------------------------------------------------------
# 4) Provjera UI JS-a i testovi (Windows)
# -----------------------------------------------------------------------------

Add-Log "" "HEAD"
Add-Log "--- Testovi (Windows) ---" "HEAD"
Add-Log "Playwright dijelovi (test_v110, test_v117, test_v119) nisu obavezni na ovom PC-u; ti testovi sami preskacu UI korak ako playwright nije instaliran. Ne postavljam PW_PYTHON=/tmp/pwenv (to je putanja s Grokova racunala / Linux boxa)."
Add-Log "Napomene o rizicima na Windowsu:"
Add-Log "  - test_updater.py u jednom koraku zove 'bash tools/make_release.sh' u kopiji stabla; zato Git Bash mora biti na PATH-u (skripta ga dodaje ako je naden)."
Add-Log "  - make_release.sh zove 'python3' (ne 'python'). Ako u Git Bashu nema python3, taj korak testa moze pasti."
Add-Log "  - test_v105.py koristi hardkodirane putanje /tmp/fake-brave/... samo kao lazni objekt u mocku, ne stvara te mape."
Add-Log "  - test_v115.py radi symlink_to; na Windowsu to cesto treba Developer Mode ili administratorska prava i moze pasti."

# Testovi koje pokrecemo (bez iskljucivo Playwright/Linux okruzenja).
$WindowsTests = @(
    "tools\check_ui_js.py",
    "tools\test_pythonw_stdio.py",
    "tools\test_updater.py",
    "tools\test_v102.py",
    "tools\test_v105.py",
    "tools\test_v107.py",
    "tools\test_v108.py",
    "tools\test_v109.py",
    "tools\test_v110.py",
    "tools\test_v111.py",
    "tools\test_v112.py",
    "tools\test_v113.py",
    "tools\test_v114.py",
    "tools\test_v115.py",
    "tools\test_v116.py",
    "tools\test_v117.py",
    "tools\test_v118.py",
    "tools\test_v119.py",
    "tools\test_v120.py"
)

if (-not $RepoReady) {
    Add-Log "Preskacem testove jer checkout nije spreman." "WARN"
} elseif (-not $PythonRun) {
    Add-Log "Preskacem testove jer Python nije dostupan." "FAIL"
} else {
    if ($BashExe) { Enable-GitBashOnPath $BashExe }
    if ($NodeExe) { Add-ToPathIfExists (Split-Path -Parent $NodeExe) }

    Push-Location $RepoDir
    try {
        foreach ($rel in $WindowsTests) {
            $full = Join-Path $RepoDir $rel
            if (-not (Test-Path -LiteralPath $full)) {
                Add-Log "$rel ne postoji u checkoutu — preskacem." "WARN"
                continue
            }
            Add-Log "Pokrecem: $PythonLabel $rel"
            $args = @()
            foreach ($a in $PythonRunArgs) { $args += $a }
            $args += $rel
            $output = & $PythonRun @args 2>&1 | Out-String
            $code = $LASTEXITCODE
            if ($null -eq $code) { $code = 0 }
            $trimmed = $output.Trim()
            if ($trimmed.Length -gt 2500) {
                $snippet = $trimmed.Substring($trimmed.Length - 2500)
            } else {
                $snippet = $trimmed
            }
            if ($code -eq 0) {
                Add-Log "$rel — PROSAO (izlaz 0)" "OK"
            } else {
                Add-Log "$rel — PAO (izlaz $code)" "FAIL"
            }
            if ($snippet) {
                foreach ($ln in ($snippet -split "`r?`n")) {
                    if ($ln.Trim()) { [void]$script:ReportLines.Add("        $ln") }
                }
                # Na konzolu samo zadnjih par linija da ne bude predugacko
                $tail = ($snippet -split "`r?`n" | Where-Object { $_.Trim() } | Select-Object -Last 8)
                foreach ($t in $tail) { Write-Host "        $t" }
            }
        }
    } finally {
        Pop-Location
    }
}

# -----------------------------------------------------------------------------
# 5) Ovisnosti make_release.sh (BEZ pokretanja)
# -----------------------------------------------------------------------------

Add-Log "" "HEAD"
Add-Log "--- Ovisnosti tools/make_release.sh (samo provjera, NE pokrecem skriptu) ---" "HEAD"
Add-Log "make_release.sh bumpa verziju i pakira zip — zato je ovdje samo 'command -v', nikad sam release."
Add-Log "Stvarno potrebno u skripti: bash, python3, cat. node je pozeljan (inace se preskace check_ui_js.py uz upozorenje)."
Add-Log "zip i sha256sum NISU potrebni: paket i hash rade se u Pythonu (zipfile + hashlib)."

if (-not $BashExe) {
    Add-Log "Ne mogu provjeriti ovisnosti u Git Bashu jer bash nije naden." "FAIL"
} else {
    Enable-GitBashOnPath $BashExe
    $cmds = @("python3", "python", "node", "zip", "sha256sum", "cat", "bash")
    $needed = @{
        "python3"   = "obavezno (make_release.sh zove python3)"
        "python"    = "nije dovoljno samo po sebi; skripta zove python3"
        "node"      = "pozeljno (provjera UI JS-a); bez njega skripta upozori i nastavi"
        "zip"       = "nije potrebno (koristi se Python zipfile)"
        "sha256sum" = "nije potrebno (koristi se Python hashlib)"
        "cat"       = "koristi se za zavrsnu poruku"
        "bash"      = "obavezno (sama skripta)"
    }
    foreach ($c in $cmds) {
        $probe = & $BashExe --noprofile --norc -c "command -v $c 2>/dev/null || true"
        $probe = ([string]$probe).Trim()
        $note = $needed[$c]
        if ($probe) {
            Add-Log ("Git Bash command -v {0} = {1}  ({2})" -f $c, $probe, $note) "OK"
            if ($c -eq "python3") { $needed["seen_python3"] = $true }
        } else {
            if ($c -eq "python3" -or $c -eq "bash" -or $c -eq "cat") {
                Add-Log ("Git Bash nema '{0}' ({1})" -f $c, $note) "FAIL"
            } elseif ($c -eq "node") {
                Add-Log ("Git Bash nema '{0}' ({1})" -f $c, $note) "WARN"
            } else {
                Add-Log ("Git Bash nema '{0}' ({1})" -f $c, $note) "WARN"
            }
        }
    }
    if (-not $needed["seen_python3"]) {
        Add-Log "VAZNO: bez naredbe python3 u Git Bashu, 'bash tools/make_release.sh' nece raditi na ovom PC-u, cak i ako 'python' postoji. Treba shim ili instalacija tako da 'python3' postoji na PATH-u u Bashu." "WARN"
    }
}

# -----------------------------------------------------------------------------
# 6) Izvjestaj
# -----------------------------------------------------------------------------

Add-Log "" "HEAD"
Add-Log "--- Sažetak ---" "HEAD"
Add-Log ("Neuspjelih provjera: {0}; upozorenja: {1}" -f $script:FailCount, $script:WarnCount)
if ($script:FailCount -eq 0) {
    Add-Log "Sve obavezne provjere koje su se mogle pokrenuti su prošle (upozorenja gore, ako ih ima)." "OK"
} else {
    Add-Log "Ima neuspjelih provjera — pogledaj izvjestaj i poruke iznad." "FAIL"
}
Add-Log "Izvjestaj je spremljen u: $ReportPath"
Add-Log "Sljedeci korak ako gh nije prijavljen: pokreni 'gh auth login' SAM, zatim ponovo ovu skriptu."
Add-Log "Instalacijsku mapu (%LOCALAPPDATA%\AIInfluencerStudio) nismo dirali."

# Zapisi izvjestaj (UTF-8). U PS 5.1 Out-File -Encoding utf8 pise BOM, sto je u redu na Windowsu.
try {
    if (-not (Test-Path -LiteralPath $DevRoot)) {
        New-Item -ItemType Directory -Path $DevRoot -Force | Out-Null
    }
    $text = [string]::Join("`r`n", $script:ReportLines.ToArray()) + "`r`n"
    $utf8Bom = New-Object System.Text.UTF8Encoding $true
    [System.IO.File]::WriteAllText($ReportPath, $text, $utf8Bom)
    Add-Log "Izvjestaj zapisan." "OK"
} catch {
    Write-Host "NISAM mogao zapisati $ReportPath : $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host ""
Write-Host "======= sadrzaj izvjestaja =======" -ForegroundColor Cyan
if (Test-Path -LiteralPath $ReportPath) {
    Get-Content -LiteralPath $ReportPath -Encoding UTF8 | Write-Host
}

if ($script:FailCount -gt 0) { exit 1 } else { exit 0 }
