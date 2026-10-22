# 헤르메스 캘린더 설치 (윈도우)
# install.cmd 를 더블클릭하면 이 파일이 실행돼요.
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = "1"

function Fail($msg) { Write-Host "`n⛔ $msg" -ForegroundColor Red; exit 1 }
function Step($msg) { Write-Host "`n▶ $msg" -ForegroundColor Cyan }

$Here = $PSScriptRoot
if ($env:HCAL_HOME) { $HcalHome = $env:HCAL_HOME }
elseif ($env:HERMES_HOME) { $HcalHome = Join-Path $env:HERMES_HOME "hcal" }
else { $HcalHome = Join-Path $env:LOCALAPPDATA "hermes\hcal" }
$Venv = Join-Path $HcalHome "venv"
$Py = Join-Path $Venv "Scripts\python.exe"
$Check = "import sys; print(sys.version_info >= (3, 11))"

function Find-Python {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        if ((& py -3 -c $Check 2>$null) -eq "True") { return ,@("py", "-3") }
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        if ((& python -c $Check 2>$null) -eq "True") { return ,@("python") }
    }
    return $null
}

Step "1/4 파이썬 확인"
$PyCmd = Find-Python
if (-not $PyCmd) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Fail "파이썬 3.11 이상이 필요해요. https://www.python.org/downloads/ 에서 설치한 뒤 다시 실행하세요."
    }
    Write-Host "파이썬이 없어서 설치할게요 (winget)..."
    winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
    $PyCmd = Find-Python
    if (-not $PyCmd) { Fail "파이썬을 설치했지만 찾지 못했어요. 창을 닫고 install.cmd 를 다시 실행하세요." }
}
$PyExe = $PyCmd[0]
$PyArgs = @($PyCmd | Select-Object -Skip 1)
Write-Host "OK: $(& $PyExe @PyArgs --version)"

Step "2/4 프로그램 설치 ($HcalHome)"
New-Item -ItemType Directory -Force $HcalHome | Out-Null
if (-not (Test-Path $Py)) {
    & $PyExe @PyArgs -m venv $Venv
    if ($LASTEXITCODE -ne 0) { Fail "가상환경을 만들지 못했어요." }
}
& $Py -m pip install -q --disable-pip-version-check $Here
if ($LASTEXITCODE -ne 0) { Fail "설치에 실패했어요. 인터넷 연결을 확인하고 다시 실행하세요." }
$env:HCAL_HOME = $HcalHome

Step "3/4 구글 연결 (브라우저가 열려요)"
& $Py -m hermes_calendar.cli setup
if ($LASTEXITCODE -ne 0) { Fail "구글 연결을 끝내지 못했어요. install.cmd 를 다시 실행하면 이어서 할 수 있어요." }

Step "4/4 헤르메스에 연결"
& $Py -m hermes_calendar.cli install-hermes --apply
if ($LASTEXITCODE -ne 0) { Fail "헤르메스 연결에 실패했어요. 위 메시지를 확인하세요." }

Write-Host "`n🎉 설치 끝. 텔레그램에서 헤르메스에게 '오늘 일정 알려줘'라고 보내 보세요." -ForegroundColor Green
