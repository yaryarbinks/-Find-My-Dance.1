$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python environment creation failed.' }
}
& ./.venv/Scripts/python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
if (-not (Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue)) {
    New-Item -ItemType Directory -Path (Join-Path $PSScriptRoot 'data') -Force | Out-Null
    $danceInterpreter = Join-Path $PSScriptRoot '.venv/Scripts/pythonw.exe'
    if (-not (Test-Path -LiteralPath $danceInterpreter)) {
        $danceInterpreter = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
    }
    Start-Process -FilePath $danceInterpreter -ArgumentList '-m streamlit run app.py --server.address 127.0.0.1 --server.headless true --browser.gatherUsageStats false' -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot 'data/server.log') -RedirectStandardError (Join-Path $PSScriptRoot 'data/server-error.log')
}
Write-Output 'Find My Dance is running in the background at http://127.0.0.1:8501/'
