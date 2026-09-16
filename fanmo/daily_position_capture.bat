@echo off
REM 9UP 포지션 일일 자동 갱신 — 실제 로직은 daily_position_capture.ps1에 있음
REM (여러 포지션을 순회하는 반복/파일 정리 로직이라 배치보다 PowerShell이 다루기 쉬움).
REM Windows 작업 스케줄러에 이 .bat를 매일 한 번 등록해서 쓰면 된다.
REM ** LD플레이어가 켜져 있어야 하고, 9UP 앱이 최소한 실행은 되어 있어야 한다
REM    (SHIFT+F2가 "앱 시작 화면 -> 메뉴 -> 판타지 모드"까지 가는 매크로라는 전제).
REM
REM -WindowStyle Hidden: bat을 그냥 더블클릭하면 powershell 콘솔 창이 화면에 보이는
REM 채로 떠서, 그 창 자체가 LD플레이어와 포커스를 다퉈 키 입력이 엉뚱하게 들어가는
REM 문제가 실제로 있었다(수동으로 매크로 누르면 되는데 bat으로 돌리면 포지션 선택에서
REM 안 넘어가고 뒤로 가버림, 2026-09-16 확인). 콘솔 창 자체를 안 띄우면 이 경합이
REM 사라진다.
powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0daily_position_capture.ps1"
exit /b %ERRORLEVEL%
