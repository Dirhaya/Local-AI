# Per-user setup. No admin privileges, password collection or account connections.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$appRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $appRoot

function Run-Checked {
    param([string]$Program, [string[]]$Arguments)
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $Program @Arguments
        $resultCode = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previousPreference }
    if ($resultCode -ne 0) { throw "A setup command failed (exit $resultCode). Read the error above." }
}
function Find-Python312 {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'SultanLocalAI\Python312\python.exe')
    )
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        $previousPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            $found = & $launcher.Source -3.12 -c 'import sys; print(sys.executable)' 2>$null
            $resultCode = $LASTEXITCODE
        } finally { $ErrorActionPreference = $previousPreference }
        if ($resultCode -eq 0 -and $found) { $candidates += [string]($found | Select-Object -Last 1) }
    }
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            & $candidate -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3,12) else 1)' 2>$null
            if ($LASTEXITCODE -eq 0) { return $candidate }
        }
    }
    return $null
}
function Find-Ollama {
    $command = Get-Command ollama -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $candidate = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
    if (Test-Path -LiteralPath $candidate) { return $candidate }
    return $null
}

try {
    Write-Host 'SULTAN LOCAL AI - AUTOMATIC SETUP' -ForegroundColor Cyan
    Write-Host 'This installs Python if needed, app packages, local chat and speech models.'
    Write-Host 'Keep this window open. First setup needs internet and several GB of free space.'
    Write-Host 'It does not connect your email or calendar accounts.'
    Write-Host ''

    Write-Host '[1/6] Finding Python 3.12...' -ForegroundColor Cyan
    $python = Find-Python312
    if (-not $python) {
        if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64' -or -not [Environment]::Is64BitOperatingSystem) {
            throw 'This automatic installer targets 64-bit Intel/AMD Windows. Share this message so we can adapt it.'
        }
        $temporary = Join-Path ([IO.Path]::GetTempPath()) ('sultan-setup-' + [guid]::NewGuid())
        New-Item -ItemType Directory -Path $temporary | Out-Null
        try {
            $installer = Join-Path $temporary 'python-3.12.10-amd64.exe'
            Write-Host 'Downloading Python from python.org...'
            Invoke-WebRequest -UseBasicParsing -Uri 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' -OutFile $installer
            $signature = Get-AuthenticodeSignature -FilePath $installer
            if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Python Software Foundation') {
                throw 'The Python installer signature could not be verified. Nothing was installed.'
            }
            $target = Join-Path $env:LOCALAPPDATA 'SultanLocalAI\Python312'
            $installArgs = '/quiet InstallAllUsers=0 Include_launcher=0 Include_test=0 Include_doc=0 Include_pip=1 PrependPath=0 TargetDir="' + $target + '"'
            Write-Host 'Installing Python for your Windows user. This may take a few minutes...'
            $installed = Start-Process -FilePath $installer -ArgumentList $installArgs -Wait -PassThru
            if ($installed.ExitCode -notin @(0,3010)) { throw "Python installation failed (exit $($installed.ExitCode))." }
        } finally {
            Remove-Item -LiteralPath $temporary -Recurse -Force -ErrorAction SilentlyContinue
        }
        $python = Find-Python312
        if (-not $python) { throw 'Python installed but could not be found. Restart Windows and run this setup again.' }
    }
    Write-Host 'Python 3.12 is ready.'

    Write-Host '[2/6] Preparing the app...' -ForegroundColor Cyan
    # Keep the installed code in a stable folder, separate from the encrypted vault.
    $installedRoot = Join-Path $env:LOCALAPPDATA 'SultanLocalAI\Application'
    try {
        $null = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/status' -TimeoutSec 2
        throw 'Close the running Sultan Local AI window before installing or repairing it.'
    } catch {
        if ($_.Exception.Message -like 'Close the running*') { throw }
    }
    if ([IO.Path]::GetFullPath($appRoot).TrimEnd('\') -ne [IO.Path]::GetFullPath($installedRoot).TrimEnd('\')) {
        New-Item -ItemType Directory -Path $installedRoot -Force | Out-Null
        $database = Join-Path $env:LOCALAPPDATA 'SultanLocalAI\vault.sqlite3'
        if (Test-Path -LiteralPath $database) {
            $backupDir = Join-Path $env:LOCALAPPDATA 'SultanLocalAI\backups'
            New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
            Copy-Item -LiteralPath $database -Destination (Join-Path $backupDir ('before-setup-' + (Get-Date -Format 'yyyyMMddHHmmss') + '.sqlite3'))
        }
        foreach ($item in Get-ChildItem -LiteralPath $appRoot -Force) {
            if ($item.Name -in @('.venv','.git','__pycache__','.pytest_cache','models','setup-defaults.json')) { continue }
            Copy-Item -LiteralPath $item.FullName -Destination $installedRoot -Recurse -Force
        }
        $appRoot = $installedRoot
        Set-Location -LiteralPath $appRoot
    }
    $venv = Join-Path $appRoot '.venv'
    $venvPython = Join-Path $venv 'Scripts\python.exe'
    if (Test-Path -LiteralPath $venvPython) {
        & $venvPython -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3,12) else 1)' 2>$null
        if ($LASTEXITCODE -ne 0) {
            Move-Item -LiteralPath $venv -Destination ($venv + '-previous-' + [guid]::NewGuid().ToString('N'))
        }
    }
    if (-not (Test-Path -LiteralPath $venvPython)) { Run-Checked $python @('-m','venv',$venv) }
    Run-Checked $venvPython @('-m','pip','install','-r','requirements-speech.txt')

    Write-Host '[3/6] Connecting to your installed Ollama...' -ForegroundColor Cyan
    $ollama = Find-Ollama
    if (-not $ollama) { throw 'Ollama was not found. Install it from https://ollama.com/download/windows, then rerun this setup.' }
    $env:OLLAMA_NO_CLOUD = '1'
    # Applies to future Ollama launches; existing local models are additionally verified by the app.
    [Environment]::SetEnvironmentVariable('OLLAMA_NO_CLOUD','1','User')
    try {
        $null = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 4
    } catch {
        Start-Process -FilePath $ollama -ArgumentList 'serve' -WindowStyle Minimized | Out-Null
        $ready = $false
        for ($attempt=0; $attempt -lt 30; $attempt++) {
            Start-Sleep -Seconds 1
            try { $null = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2; $ready=$true; break } catch {}
        }
        if (-not $ready) { throw 'Ollama could not start. Open the Ollama app and run this setup again.' }
    }

    Write-Host '[4/6] Downloading a local chat model...' -ForegroundColor Cyan
    $ram = 0
    try { $ram = [double](Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB } catch {}
    $model = if ($ram -gt 0 -and $ram -lt 12) { 'qwen3.5:2b' } else { 'qwen3.5:4b' }
    Write-Host "Selected $model. The download may take a while; its progress is shown below."
    Run-Checked $ollama @('pull',$model)

    Write-Host '[5/6] Downloading offline speech recognition...' -ForegroundColor Cyan
    Run-Checked $venvPython @('scripts\download_speech.py','--model','base')
    $speech = Join-Path $env:LOCALAPPDATA 'SultanLocalAI\models\whisper-base'
    @{model=$model; speech_model_path=$speech} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $appRoot 'setup-defaults.json') -Encoding UTF8

    Write-Host '[6/6] Opening your AI app...' -ForegroundColor Cyan
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'Sultan Local AI.lnk'))
    $shortcut.TargetPath = Join-Path $appRoot 'Start-Windows.cmd'
    $shortcut.WorkingDirectory = $appRoot
    $shortcut.Description = 'Your local study workspace and personal AI'
    $shortcut.Save()
    Write-Host 'When the browser opens, create your private vault passphrase. You choose it; setup does not know it.'
    Write-Host 'Chat and speech settings are prefilled for a new vault. Keep this window open while using the app.'
    Run-Checked $venvPython @('run.py')
} catch {
    Write-Host ''
    Write-Host ('SETUP STOPPED: ' + $_.Exception.Message) -ForegroundColor Red
    Write-Host 'You can run SETUP-EVERYTHING.cmd again. Completed downloads can be reused.'
    exit 1
}
