# 9UP 포지션(+투수 역할) 자동 캡쳐
# ---------------------------------------------------------------------------
# 코스트는 매달 1일/16일에만 바뀌지만 포지션은 9UP이 아무때나 바꿔서, 매일 이 스크립트를
# 돌려 따라잡는다. 투수(선발/구원) 화면은 코스트와 같은 주기(1일/16일)에만 찍는다 —
# 지금은 캡쳐해서 폴더별로 정리해 두는 것까지만 하고(사용자 요청: "구현만 해놔"),
# 그 사진을 어떻게 쓸지(코스트 자동 추출 등)는 나중에 별도로 정한다.
#
# LD플레이어에 녹화해둔 매크로와 단축키 매핑(실제 테스트로 확정 — CTRL/ALT+숫자 조합은
# SendKeys로 안정적으로 안 먹혀서(특히 ALT는 윈도우 메뉴 활성화로 새는 경우가 있음)
# 전부 SHIFT 계열로 통일했다):
#   SHIFT+F2        : 9UP 앱 실행(홈 화면에서 아이콘 탭)
#   SHIFT+F3        : 판타지 모드 진입(앱 메인 -> 메뉴 -> 판타지 모드)
#   SHIFT+F4 ~ F12  : 포지션 선택(1루수/2루수/유격수/3루수/포수/좌익수/중견수/우익수/
#                     지명타자 순 — 녹화하신 순서 그대로, 알파벳/포지션 순서가 아님)
#   SHIFT+0         : 투수(선발/구원) 화면 선택
#   SHIFT+F1        : 스크롤+캡쳐(포지션/투수 선택 후 실행 — 선택된 화면 안의 선수
#                     명단을 드래그하면서 스크린샷을 계속 찍음). 스크린샷은 전부 같은
#                     폴더(SCREENSHOT_ROOT)에 쌓이고 포지션 구분이 안 되므로, 이
#                     스크립트가 "이 매크로를 돌리기 직전까지 있던 파일" 대비 새로
#                     생긴 파일만 골라 <오늘 날짜>\<포지션> 하위 폴더로 옮긴다
#                     (예: Screenshots\2026-09-15\1b\). 날짜별로 나눠야 다음날 다시
#                     돌릴 때 어제 사진이 안 섞인다 — 예전에 며칠 지난 스크린샷이 최신
#                     폴더에 그대로 남아있어서 OCR 결과가 꼬였던 적이 있었음.
#
# 사용법: daily_position_capture.bat
#
# 전체 실행이 15분쯤 걸리는데 LD플레이어가 중간에 뻗는 일이 실제로 있어서(2026-09-16
# 구원투수 캡쳐 도중 다운), 그냥 다시 실행하면 못 찍은 포지션부터 이어서 진행된다.
# 모든 포지션을 순서대로 "방문"은 하되(각 포지션 매크로가 ESC로 현재 명단에서 빠져나온
# 뒤 탭을 누르는 구조라, 건너뛰면 다음 포지션의 이동이 깨진다), 방문 직후 이미 명단
# 끝까지 찍혀 있으면 캡쳐(포지션당 50초 이상)만 건너뛰고 바로 다음으로 넘어간다.

$ErrorActionPreference = "Stop"

# bat을 실수로 여러 번 실행하면 인스턴스 여러 개가 동시에 LD플레이어 창 포커스를
# 서로 뺏고 뺏으면서 키 입력이 엉뚱하게 들어가 캡쳐가 하나도 안 되는 문제가 실제로
# 있었다(2026-09-16 확인). 그래서 시작하자마자 이 스크립트를 실행 중인 다른
# powershell 프로세스가 있으면(내 자신 제외) 먼저 강제 종료한다.
$myPid = $PID
Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.ProcessId -ne $myPid -and $_.CommandLine -match "daily_position_capture\.ps1" } |
    ForEach-Object {
        Write-Host "기존에 돌고 있던 인스턴스 종료: PID $($_.ProcessId)"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
Start-Sleep -Milliseconds 500

$RepoDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ScreenshotRoot = "C:\Users\HUI\OneDrive\문서\XuanZhi9\Pictures\Screenshots"
$LDPlayerTitle = "LDPlayer"

# bat이 -WindowStyle Hidden으로 콘솔 창 없이 돌아가서 Write-Host가 어디에도 안 남는다
# (실행 중 어디서 멈췄는지/왜 죽었는지 알 방법이 없었음 — 2026-09-16에 실제로 중간에
# 죽었는데 원인을 못 찾아 헤맴). logs 폴더에 실행마다 타임스탬프 로그 파일을 남기고,
# 스크립트 전체를 try/catch로 감싸서 어떤 예외로 죽었는지도 로그에 그대로 찍히게 한다.
$LogDir = Join-Path $RepoDir "logs"
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
$LogPath = Join-Path $LogDir "daily_position_capture_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"
Start-Transcript -Path $LogPath -Append | Out-Null

try {

$LaunchAppHotkey = "+{F2}"      # SHIFT+F2 (9UP 앱 실행)
$FantasyModeHotkey = "+{F3}"    # SHIFT+F3 (판타지 모드 진입)
$CaptureHotkey = "+{F1}"        # SHIFT+F1 (기존 매크로, 포지션/투수 선택 후 실행)

# 폴더명 -> (선택 단축키, 표시용 이름, LD플레이어 매크로 녹화 파일명).
# 녹화하신 실제 순서 그대로(SHIFT+F4~F12).
$Targets = [ordered]@{
    "1b" = @{ Key = "+{F4}";  Label = "1루수";       Record = "1루수" }
    "2b" = @{ Key = "+{F5}";  Label = "2루수";       Record = "2루수" }
    "ss" = @{ Key = "+{F6}";  Label = "유격수";      Record = "유격수" }
    "3b" = @{ Key = "+{F7}";  Label = "3루수";       Record = "3루수" }
    "c"  = @{ Key = "+{F8}";  Label = "포수";        Record = "포수" }
    "lf" = @{ Key = "+{F9}";  Label = "좌익수";      Record = "좌익수" }
    "cf" = @{ Key = "+{F10}"; Label = "중견수";      Record = "중견수" }
    "rf" = @{ Key = "+{F11}"; Label = "우익수";      Record = "우익수" }
    "dh" = @{ Key = "+{F12}"; Label = "지명타자";    Record = "지명타자" }
    "p"  = @{ Key = "+0";     Label = "투수(선발)";  Record = "선발"; MonthlyOnly = $true; MaxCaptureRuns = 5 }
    "rp" = @{ Key = "+-";     Label = "투수(구원)";  Record = "구원"; MonthlyOnly = $true; MaxCaptureRuns = 5 }
    # 구원투수도 선발 목록(p)에 뜨긴 하지만 스크롤 12번 안에 안 나올 수 있어서 따로 캡쳐.
}

# 캡쳐 매크로(SHIFT+F1)는 "스크린샷 1장 + 아래로 스크롤"을 6번 반복하고 끝난다(매크로
# 파일의 loopTimes=6). 스크롤을 위로 되돌리는 동작이 없어서, 단축키를 한 번 더 보내면
# 멈춘 자리에서 이어서 6장을 더 찍는다. 투수는 명단이 야수보다 훨씬 길어서 6장으로는
# 끝까지 못 간다(실측: 투수 폴더 사진들은 서로 전혀 안 겹침 = 아직 끝에 도달 못 함).
# 그래서 포지션마다 최대 반복 횟수를 두되, 매번 "마지막 2장이 사실상 같은 화면인지"를
# screenshot_dedupe.py로 확인해서 명단 끝에 닿았으면 바로 멈춘다(야수는 보통 1회로 끝).
$DefaultMaxCaptureRuns = 2

# LD플레이어는 매크로가 재생되는 도중에 들어온 단축키를 그냥 무시한다. 그래서 다음
# 단축키를 보내기 전에 "직전 매크로가 다 끝날 때까지" 기다려야 하는데, 이걸 고정값으로
# 어림잡았다가 크게 헤맸다(2026-09-16):
#   - 판모진입 매크로가 18.7초짜리인데 5초만 기다리고 1루수(SHIFT+F4)를 눌러서, 1루수만
#     항상 씹혔다. 그 뒤 포지션 매크로들은 맨 앞에 ESC(AndroidBack)가 있어서, 명단
#     화면이 안 열린 상태로 ESC만 계속 먹으며 메인 화면 쪽으로 밀려났다.
#   - 포지션 선택 매크로가 5.5~11.4초인데 3초만 기다리고 캡쳐(SHIFT+F1)를 눌러서, 캡쳐가
#     될 때도 있고 안 될 때도 있었다.
# 매크로 재생 시간은 녹화 파일(.record)의 circleDuration(1회 재생 ms) x loopTimes(반복
# 횟수)에 그대로 적혀 있으므로, 그 값을 읽어서 + 여유시간만큼 기다린다. 이러면 매크로를
# 다시 녹화해서 길이가 바뀌어도 자동으로 맞춰진다.
$MacroRecordDir = "C:\LDPllayer\LDPlayer9\vms\operationRecords"
$MacroMarginSeconds = 5   # 매크로 재생 시간 + 이만큼 여유를 두고 다음 키를 보낸다

function Get-MacroSeconds([string]$recordName, [int]$fallbackSeconds) {
    $path = Join-Path $MacroRecordDir "$recordName.record"
    if (-not (Test-Path $path)) {
        Write-Host "  (매크로 파일을 못 찾음: $path — 기본 대기 $fallbackSeconds 초 사용)"
        return $fallbackSeconds
    }
    try {
        $info = (Get-Content $path -Raw -Encoding UTF8 | ConvertFrom-Json).recordInfo
        $loops = if ($info.loopTimes -gt 0) { $info.loopTimes } else { 1 }
        return [math]::Ceiling($info.circleDuration * $loops / 1000.0)
    } catch {
        Write-Host "  (매크로 파일 읽기 실패: $recordName — 기본 대기 $fallbackSeconds 초 사용)"
        return $fallbackSeconds
    }
}

Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public class LDWin {
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);
    [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);
    [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
    [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint idAttach, uint idAttachTo, bool fAttach);
    [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr hWnd);
}
"@

function Find-LDPlayerWindow([string]$title) {
    # wscript.shell의 AppActivate/FindWindow(ANSI)는 이 환경에서 LDPlayer 창을 못 찾는
    # 현상이 있어서(EnumWindows로는 정상적으로 잡힘 — 원인 불명, 유니코드/ANSI 마샬링
    # 차이로 추정), EnumWindows 기반으로 직접 핸들을 찾는다.
    # 주의: 콜백 스크립트블록 안에서는 함수의 지역 스코프가 아니라 "script" 스코프에
    # 값을 써야 밖으로 전달된다(지역 변수에 그냥 대입하면 클로저 밖 함수 return에
    # 반영이 안 돼서 항상 못 찾은 것으로 나옴 — 실제로 이 버그 때문에 매크로가 전혀
    # 안 돌아가고 있었다). 그래서 함수 이름을 포함한 고유 키로 $script: 변수를 쓴다.
    $script:_ldFoundHwnd = [IntPtr]::Zero
    $callback = {
        param($hWnd, $lParam)
        if ([LDWin]::IsWindowVisible($hWnd)) {
            $sb = New-Object System.Text.StringBuilder 256
            [LDWin]::GetWindowText($hWnd, $sb, 256) | Out-Null
            if ($sb.ToString() -eq $title) { $script:_ldFoundHwnd = $hWnd; return $false }
        }
        return $true
    }
    [LDWin]::EnumWindows($callback, [IntPtr]::Zero) | Out-Null
    return $script:_ldFoundHwnd
}

function Set-ForegroundWindowForced([IntPtr]$hwnd) {
    # 방금 사용자 입력이 없었던 프로세스(작업 스케줄러로 무인 실행되는 경우 등)에서
    # SetForegroundWindow를 부르면 Windows의 포그라운드 탈취 방지 정책 때문에 거부될
    # 수 있다(직접 double-click으로 실행할 땐 "방금 입력한 프로세스" 취급이라 되던
    # 것도, 스케줄러/원격 실행에서는 그냥 실패함 — 실측 확인). 현재 포그라운드 창을
    # 가진 스레드에 내 입력 스레드를 잠깐 붙였다가(AttachThreadInput) 다시 시도하면
    # 이 제한을 우회할 수 있다(잘 알려진 workaround).
    if ([LDWin]::SetForegroundWindow($hwnd)) { return $true }

    $curThread = [LDWin]::GetCurrentThreadId()
    $fgWindow = [LDWin]::GetForegroundWindow()
    $fgProcId = 0
    $fgThread = [LDWin]::GetWindowThreadProcessId($fgWindow, [ref]$fgProcId)

    [LDWin]::AttachThreadInput($curThread, $fgThread, $true) | Out-Null
    try {
        [LDWin]::BringWindowToTop($hwnd) | Out-Null
        $ok = [LDWin]::SetForegroundWindow($hwnd)
    } finally {
        [LDWin]::AttachThreadInput($curThread, $fgThread, $false) | Out-Null
    }
    return $ok
}

function Send-ToLDPlayer([string]$keys) {
    $hwnd = Find-LDPlayerWindow $LDPlayerTitle
    if ($hwnd -eq [IntPtr]::Zero) {
        throw "LD플레이어 창을 찾을 수 없습니다 ('$LDPlayerTitle') — 창이 켜져 있는지 확인하세요."
    }
    # 다른 창이 잠깐 포커스를 붙잡고 있으면 SetForegroundWindow가 실패하는데, 이건
    # 대부분 일시적이다(실측: 8개 포지션을 정상 처리한 뒤 지명타자 차례에 한 번 실패해서
    # 그 뒤 전부를 날림, 2026-09-16). 그래서 한 번 실패했다고 바로 포기하지 않고,
    # 실제로 LD플레이어가 포그라운드가 됐는지 확인하면서 몇 초간 끈질기게 재시도한다.
    $confirmed = $false
    for ($i = 0; $i -lt 30; $i++) {
        [LDWin]::ShowWindow($hwnd, 9) | Out-Null  # SW_RESTORE(최소화돼 있으면 복원)
        Set-ForegroundWindowForced $hwnd | Out-Null
        Start-Sleep -Milliseconds 300
        if ([LDWin]::GetForegroundWindow() -eq $hwnd) { $confirmed = $true; break }
    }
    if (-not $confirmed) {
        throw "LD플레이어에 포커스를 유지할 수 없습니다(다른 창이 계속 가로챔) — 키 입력을 보내지 않고 중단합니다."
    }

    Start-Sleep -Milliseconds 300
    $wshell = New-Object -ComObject wscript.shell
    $wshell.SendKeys($keys)
}

function Move-NewScreenshots([string]$destFolder, [datetime]$since) {
    New-Item -ItemType Directory -Path $destFolder -Force | Out-Null
    $newFiles = Get-ChildItem -Path $ScreenshotRoot -File -Filter "*.png" |
        Where-Object { $_.CreationTime -gt $since }
    foreach ($f in $newFiles) {
        Move-Item -Path $f.FullName -Destination $destFolder -Force
    }
    return $newFiles.Count
}

$launchWait = (Get-MacroSeconds "9up실행" 5) + 30   # 매크로 자체는 짧고, 게임 로딩이 오래 걸린다
Write-Host "[1/5] 9UP 앱 실행... (${launchWait}초 대기)"
Send-ToLDPlayer $LaunchAppHotkey
Start-Sleep -Seconds $launchWait

$fantasyWait = (Get-MacroSeconds "판모진입" 20) + $MacroMarginSeconds
Write-Host "[1/5] 판타지 모드 진입... (${fantasyWait}초 대기)"
Send-ToLDPlayer $FantasyModeHotkey
Start-Sleep -Seconds $fantasyWait

$todayDay = (Get-Date).Day
$isCostDay = ($todayDay -eq 1) -or ($todayDay -eq 16)
$dateFolder = Get-Date -Format "yyyy-MM-dd"  # 캡쳐한 날짜별로 폴더를 나눠서, 다음날 다시
                                              # 돌릴 때 어제 사진이랑 안 섞이게 한다(예전에
                                              # 묵은 스크린샷이 최신 것과 섞여서 OCR 결과가
                                              # 꼬였던 적이 있었음 — 9/13 예전 사진이 9/15
                                              # 폴더에 남아있던 문제 참고).

# 코스트는 1일/16일에만 바뀌므로 투수 화면도 그날만 찍으면 되지만, 그날 캡쳐가 끝까지
# 못 갔으면(LD플레이어가 뻗거나 명단이 길어 반복 횟수가 모자랐거나) 다음 갱신일까지
# 보름 내내 메울 방법이 없다 — 실제로 9/16 투수 캡쳐가 명단 끝에 도달하지 못한 채
# 끝났는데 17일에는 투수를 아예 안 찍어서 손쓸 수가 없었다. 그래서 "갱신일인가"가 아니라
# "이번 주기 캡쳐가 끝났는가"로 판단한다. 다 찍혔으면 저절로 안 찍으니 매일 10분씩
# 낭비되지도 않는다.
$periodStart = if ($todayDay -ge 16) { (Get-Date -Day 16).Date } else { (Get-Date -Day 1).Date }

function Test-PitcherCaptureDone([string]$folder) {
    $dirs = Get-ChildItem $ScreenshotRoot -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^\d{4}-\d{2}-\d{2}$' -and [datetime]$_.Name -ge $periodStart }
    foreach ($d in $dirs) {
        $sub = Join-Path $d.FullName $folder
        if (-not (Test-Path $sub)) { continue }
        python (Join-Path $RepoDir "screenshot_dedupe.py") --at-bottom $sub | Out-Null
        if ($LASTEXITCODE -eq 0) { return $true }
    }
    return $false
}

foreach ($folder in $Targets.Keys) {
    $info = $Targets[$folder]
    if ($info.MonthlyOnly) {
        if (Test-PitcherCaptureDone $folder) {
            Write-Host "[2/5] $($info.Label) 건너뜀 — 이번 주기($($periodStart.ToString('MM/dd')) 이후)에 이미 명단 끝까지 찍음"
            continue
        }
        Write-Host "[2/5] $($info.Label): 이번 주기 캡쳐가 아직 안 끝나서 이어서 찍습니다"
    }

    $destFolder = Join-Path $ScreenshotRoot "$dateFolder\$folder"
    $selectWait = (Get-MacroSeconds $info.Record 12) + $MacroMarginSeconds
    $captureWait = (Get-MacroSeconds "판모스샷" 50) + $MacroMarginSeconds
    Write-Host "[2/5] $($info.Label) 선택(${selectWait}초 대기) + 캡쳐(${captureWait}초 대기)..."
    # 한 포지션에서 실패해도 나머지는 계속 진행한다 — 예전엔 마지막 포지션 하나가
    # 포커스 문제로 실패하면서 스크립트 전체가 죽어 뒤 단계(OCR/커밋)까지 날아갔다.
    try {
        $maxRuns = if ($info.MaxCaptureRuns) { $info.MaxCaptureRuns } else { $DefaultMaxCaptureRuns }

        $before = Get-Date
        Send-ToLDPlayer $info.Key
        Start-Sleep -Seconds $selectWait

        # 오늘 이미 "끝까지" 찍어둔 포지션이면 캡쳐(포지션당 50초 이상)를 건너뛴다 —
        # 중간에 실패해서 다시 돌릴 때 앞부분을 처음부터 반복하지 않기 위해서다. 단
        # 포지션 이동 자체(위의 선택 키)는 건너뛰지 않는다: 각 포지션 매크로가 "ESC로
        # 지금 명단에서 나온 뒤 해당 탭을 누르는" 구조라, 앞 포지션을 통째로 건너뛰면
        # 다음 포지션이 엉뚱한 화면에서 시작해 이동이 깨진다.
        # 완료 판정을 "사진이 있으면"으로 하면 안 된다 — LD플레이어가 뻗어서 7장만 찍히고
        # 끊긴 구원투수 폴더까지 완료로 보고 건너뛰어서, 정작 다시 찍어야 할 포지션을
        # 영영 안 찍게 된다(2026-09-16 실제 상황). 그래서 캡쳐 중 쓰는 것과 같은
        # 판정("마지막 2장이 같은 화면 = 명단 끝 도달")을 쓴다.
        $already = (Get-ChildItem -Path $destFolder -File -Filter "*.png" -ErrorAction SilentlyContinue).Count
        if ($already -gt 0) {
            python (Join-Path $RepoDir "screenshot_dedupe.py") --at-bottom $destFolder | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Host "  캡쳐 건너뜀 — 오늘 이미 $already 장(명단 끝까지) 찍혀 있음"
                continue
            }
            Write-Host "  오늘 $already 장 있지만 명단 끝까지 못 갔음 — 이어서 찍습니다"
        }

        $moved = 0
        for ($run = 1; $run -le $maxRuns; $run++) {
            Send-ToLDPlayer $CaptureHotkey
            Start-Sleep -Seconds $captureWait
            $moved += Move-NewScreenshots -destFolder $destFolder -since $before
            $before = Get-Date

            # 마지막 2장이 사실상 같은 화면이면 명단 끝에 닿은 것 — 더 찍어봐야 같은
            # 사진만 쌓이므로 멈춘다(python 실행 실패 시엔 그냥 계속 진행).
            python (Join-Path $RepoDir "screenshot_dedupe.py") --at-bottom $destFolder | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Host "  ($run 회차에서 명단 끝 도달)"
                break
            }
            if ($run -eq $maxRuns) {
                Write-Host "  [주의] $maxRuns 회를 다 돌았는데도 명단 끝에 도달하지 못했습니다 — MaxCaptureRuns를 늘려야 할 수 있습니다."
            }
        }

        # 중복 사진 삭제는 여기서 하지 않는다 — OCR이 끝난 뒤에 한다(아래 [5/5]).
        # 거의 같아 보이는 사진이라도 OCR은 장마다 읽어내는 이름이 조금씩 다르다.
        # 실측(2026-09-16): 유격수 9장에서 36명 읽던 걸 유사중복 제거 후 3장으로 줄이면
        # 22명까지 떨어지면서 오지환/이재현 같은 실제 선수가 유실됐다. 즉 중복처럼 보이는
        # 사진이 "같은 선수를 여러 번 읽을 기회"를 주고 있다.
        $kept = (Get-ChildItem -Path $destFolder -File -Filter "*.png" -ErrorAction SilentlyContinue).Count
        Write-Host "  -> $moved 장 이동, 현재 $kept 장 ($destFolder)"
        if ($kept -eq 0) {
            Write-Host "  [경고] $($info.Label): 캡쳐된 사진이 없습니다 — 화면이 예상과 달랐을 수 있습니다."
        }
    } catch {
        Write-Host "  [실패] $($info.Label) 건너뜀: $_"
    }
}

Write-Host "[3/5] 스크린샷 OCR 분석 + position_db.json 반영..."
Push-Location $RepoDir
try {
    $screenshotDateDir = Join-Path $ScreenshotRoot $dateFolder

    # daily_pipeline.py도 매 주기 position_db.json을 다시 쓰기 때문에(GitHub 서버 쪽에서
    # 몇 분 간격으로 계속 커밋), 여기서 그냥 git pull --rebase로 합치려고 하면 JSON
    # 줄단위 충돌이 나기 쉽다(다른 생성 파일(lp_board.html 등)처럼 "그냥 다시 만들기"가
    # 안 통함 — 원격이 방금 갱신한 auto_position까지 같이 들고 있어야 하므로). 그래서
    # 매 시도마다 원격의 최신 position_db.json으로 맞춘 다음 그 위에 OCR 결과를 다시
    # 얹는 방식으로 몇 번 재시도한다 — 이러면 애초에 git 차원의 충돌이 안 생긴다.
    # git 쪽이 실패해도(원격 충돌 등) 코스트 추출/사진 정리는 그대로 진행해야 한다 —
    # 특히 코스트는 한 달에 두 번뿐이라 이날 못 뽑으면 반달치를 통째로 놓친다. 그래서
    # git 단계만 따로 감싸고, 실패는 기억해뒀다가 맨 뒤에서 알린다.
    $gitError = $null
    try {
    $maxAttempts = 3
    $pushed = $false
    for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
        git fetch origin
        # 로컬 브랜치를 원격 최신으로 당겨두지 않으면, 커밋을 해도 non-fast-forward라
        # push가 100% 거부된다(라이브 파이프라인이 몇 분마다 커밋하기 때문에 로컬은
        # 금방 수백 커밋씩 뒤처진다 — 실제로 155커밋 뒤처진 채 push가 3번 다 실패했음,
        # 2026-09-16). 로컬에 자체 커밋이 없는 게 정상이라 ff-only면 충분하고, ff가 안
        # 되면(로컬에 커밋이 생겼거나 작업 트리가 충돌하면) 사람이 봐야 하는 상황이다.
        git merge --ff-only origin/main
        if ($LASTEXITCODE -ne 0) {
            throw "로컬 브랜치를 원격(origin/main)으로 fast-forward 하지 못했습니다 — 'git status'로 직접 확인하세요."
        }
        git checkout origin/main -- position_db.json

        python analyze_position_screenshots.py $screenshotDateDir
        if ($LASTEXITCODE -ne 0) { throw "analyze_position_screenshots.py 실패" }

        git add position_db.json
        git diff --cached --quiet
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  변경 사항 없음, 커밋 생략"
            $pushed = $true
            break
        }

        git commit -m "9UP 포지션 일일 갱신 ($(Get-Date -Format 'yyyy-MM-dd HH:mm'))"
        git push origin main
        if ($LASTEXITCODE -eq 0) {
            $pushed = $true
            break
        }
        Write-Host "  push 실패($attempt/$maxAttempts) — 그 사이 원격이 또 바뀐 것 같음, 다시 시도"
        git reset --soft HEAD~1  # 커밋만 풀고 변경 내용은 유지 — 다음 시도에서 최신 기준으로 재적용
    }
    if (-not $pushed) {
        Write-Host "  $maxAttempts 번 시도해도 push 실패 — 수동으로 확인하세요: git status"
        throw "push 실패"
    }
    } catch {
        $gitError = $_
        Write-Host "  [실패] position_db.json 반영/푸시 실패: $_"
        Write-Host "  (코스트 추출과 사진 정리는 계속 진행합니다)"
    }

    # 코스트는 매달 1일/16일에만 갱신되므로 그날만 추출한다. 카드 아래 금색 별 개수가
    # 곧 코스트라, 포지션용으로 찍어둔 같은 사진을 그대로 재사용한다(별 세기 정확도는
    # 실측 96%이고, 불일치 3건도 전부 수기 CSV 쪽 오기로 확인됐다).
    # 다만 이름 OCR이 전체의 20% 정도만 잡아내서 스냅샷을 새로 만들 수는 없다. 그래서
    # 직전 스냅샷을 복사해두고 읽어낸 것만 덮어쓴 "초안"을 만들고, 실제 등록(파일명 변경
    # + SNAPSHOTS 추가)은 사람이 변경 목록을 보고 판단한다 — 라이브 점수에 쓰이는
    # 데이터라 자동으로 갈아끼우지 않는다.
    # 투수 사진이 오늘 찍혔으면(= 갱신일이거나, 갱신일 캡쳐가 모자라서 오늘 이어 찍었으면)
    # 코스트도 다시 뽑는다. 타자는 매일 찍으므로 오늘 폴더 하나로 전체가 커버된다.
    $pitcherShotToday = Test-Path (Join-Path $screenshotDateDir "p")
    if ($isCostDay -or $pitcherShotToday) {
        Write-Host "[4/5] 코스트(별 개수) 추출 + 초안 CSV 작성..."
        python extract_cost_from_screenshots.py $screenshotDateDir --draft
    }

    # 중복 사진 삭제는 OCR이 다 끝난 뒤에 한다 — 거의 같아 보이는 사진이라도 장마다
    # 읽어내는 이름이 달라서, 먼저 지우면 실제 선수가 유실된다(실측: 유격수 36명 -> 22명).
    Write-Host "[5/5] 중복 스크린샷 정리..."
    python screenshot_dedupe.py $screenshotDateDir

    if ($gitError) { throw $gitError }
} finally {
    Pop-Location
}

Write-Host "완료."
} catch {
    Write-Host "에러로 중단됨: $_"
    Write-Host $_.ScriptStackTrace
} finally {
    Stop-Transcript | Out-Null
}
