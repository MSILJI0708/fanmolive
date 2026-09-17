# daily_position_capture.ps1 을 숨김 창으로 한 번만 띄우는 런처.
# 경로에 공백("바탕 화면")이 있어서 Start-Process 인자에 그대로 넘기면 쪼개진다
# (실제로 "C:\Users\HUI\OneDrive\바탕 는 .ps1 확장자가 아니다"로 거부당했다).
# 그래서 경로를 따옴표로 감싼 하나의 인자로 넘긴다.
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$ps1 = Join-Path $here 'daily_position_capture.ps1'
Start-Process -FilePath 'powershell.exe' -ArgumentList @(
    '-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden',
    '-File', ('"{0}"' -f $ps1)
)
Start-Sleep -Seconds 10
Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
    Where-Object { $_.CommandLine -match 'daily_position_capture\.ps1' } |
    ForEach-Object { "실행중 PID $($_.ProcessId) (시작 $($_.CreationDate.ToString('HH:mm:ss')))" }
Get-ChildItem (Join-Path $here 'logs') -Filter 'daily_position_capture_*.log' |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1 |
    ForEach-Object { "최신 로그: $($_.Name) (수정 $($_.LastWriteTime.ToString('HH:mm:ss')))" }
