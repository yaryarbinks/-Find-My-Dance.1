$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python environment creation failed.' }
}
& ./.venv/Scripts/python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
New-Item -ItemType Directory -Path (Join-Path $PSScriptRoot 'data') -Force | Out-Null
$appUrl = $null
$projectPath = $PSScriptRoot.TrimEnd('\')
$processes = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like "*$projectPath*" -and $_.CommandLine -match '-m streamlit run app\.py'
}
foreach ($process in $processes) {
    $port = 8501
    if ($process.CommandLine -match '--server\.port\s+(\d+)') {
        $port = [int]$Matches[1]
    }
    $listeners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $_.OwningProcess -eq $process.ProcessId }
    foreach ($listener in $listeners) {
        $hostName = if ($listener.LocalAddress -in @('::', '::1')) { '[::1]' } else { '127.0.0.1' }
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri "http://${hostName}:$port/_stcore/health" -TimeoutSec 1
            if ($response.StatusCode -eq 200) {
                $appUrl = "http://${hostName}:$port/"
                break
            }
        } catch {
            continue
        }
    }
    if ($appUrl) { break }
}
if (-not $appUrl) {
    $port = $null
    foreach ($candidate in 8501..8510) {
        if (-not (Get-NetTCPConnection -LocalPort $candidate -State Listen -ErrorAction SilentlyContinue)) {
            $port = $candidate
            break
        }
    }
    if (-not $port) { throw 'No available app port found between 8501 and 8510.' }

    $danceInterpreter = Join-Path $PSScriptRoot '.venv/Scripts/pythonw.exe'
    if (-not (Test-Path -LiteralPath $danceInterpreter)) {
        $danceInterpreter = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
    }
    Start-Process -FilePath $danceInterpreter `
        -ArgumentList "-m streamlit run app.py --server.address 127.0.0.1 --server.port $port --server.headless true --browser.gatherUsageStats false" `
        -WorkingDirectory $PSScriptRoot -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $PSScriptRoot 'data/server.log') `
        -RedirectStandardError (Join-Path $PSScriptRoot 'data/server-error.log')

    $appUrl = "http://127.0.0.1:$port/"
    $ready = $false
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri "${appUrl}_stcore/health" -TimeoutSec 1
            if ($response.StatusCode -eq 200) {
                $ready = $true
                break
            }
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    if (-not $ready) { throw "Find My Dance did not start successfully. Check data/server-error.log." }
}
Write-Output "Find My Dance is ready at $appUrl"
