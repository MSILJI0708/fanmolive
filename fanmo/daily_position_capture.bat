@echo off
setlocal

REM ============================================================================
REM  9UP 포지션 일일 갱신 자동화
REM  ---------------------------------------------------------------------------
REM  코스트는 매달 1일/16일에만 바뀌지만 포지션은 9UP이 아무때나 바꾸기 때문에,
REM  이 스크립트를 (Windows 작업 스케줄러 등으로) 매일 한 번 돌려서 따라잡는다.
REM
REM  순서: 1) LD플레이어에 미리 녹화해둔 "포지션 스크롤+캡쳐" 스크립트를
REM           단축키(SHIFT+F1)로 실행 -> 스크린샷이
REM           C:\Users\HUI\OneDrive\문서\XuanZhi9\Pictures\Screenshots\<포지션>\ 에 쌓임
REM        2) 매크로가 다 돌 때까지 대기(WAIT_SECONDS — 실제 소요 시간 보고 조절)
REM        3) analyze_position_screenshots.py가 그 스크린샷들을 OCR로 읽어서
REM           position_db.json의 manual_position에 반영
REM        4) 바뀐 게 있으면 git commit & push
REM           (봇이 몇 분 간격으로 계속 커밋하므로, 먼저 최신 상태로 pull --rebase
REM           한 다음에 이 변경을 얹어야 충돌이 덜 난다)
REM
REM  ** LD플레이어 창이 이미 켜져 있고 9UP 앱의 "선수 교체" 화면이 열려 있어야 한다.
REM     매크로 자체가 포지션 필터까지 전환해주는지는 확인 안 됐으니, 여러 포지션을
REM     한 번에 다 돌리는 매크로가 아니라면 이 배치를 포지션별로 여러 번 실행하거나
REM     매크로 쪽에서 9개 포지션을 다 순회하도록 만들어 둬야 한다.
REM ============================================================================

set REPO_DIR=%~dp0
set LDPLAYER_TITLE=LDPlayer
set HOTKEY={SHIFT}{F1}
set WAIT_SECONDS=90

cd /d "%REPO_DIR%"

echo [1/4] LD플레이어 창 활성화 후 캡쳐 매크로 실행 (%HOTKEY%)...
powershell -NoProfile -Command ^
  "$wshell = New-Object -ComObject wscript.shell;" ^
  "if ($wshell.AppActivate('%LDPLAYER_TITLE%')) {" ^
  "  Start-Sleep -Milliseconds 500;" ^
  "  $wshell.SendKeys('%HOTKEY%');" ^
  "} else {" ^
  "  Write-Host '  LD플레이어 창을 못 찾았습니다 — 창이 켜져 있는지 확인하세요.';" ^
  "  exit 1" ^
  "}"
if errorlevel 1 goto :error

echo [2/4] 매크로가 다 돌 때까지 %WAIT_SECONDS%초 대기...
timeout /t %WAIT_SECONDS% /nobreak >nul

echo [3/4] 스크린샷 OCR 분석 + position_db.json 반영...
python analyze_position_screenshots.py
if errorlevel 1 goto :error

echo [4/4] git commit ^& push...
git fetch origin
git add fanmo\position_db.json 2>nul
git add position_db.json 2>nul
git diff --cached --quiet
if not errorlevel 1 (
    echo   변경 사항 없음, 커밋 생략
    goto :done
)
git commit -m "9UP 포지션 일일 갱신 (%date% %time%)"
git pull --rebase origin main
if errorlevel 1 (
    echo   충돌 발생 — 수동으로 확인하세요: git status
    goto :error
)
git push origin main

:done
echo 완료.
exit /b 0

:error
echo 오류로 중단됨.
exit /b 1
