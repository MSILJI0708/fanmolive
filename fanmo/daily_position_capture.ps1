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
# 사용법: powershell -File daily_position_capture.ps1
#         (daily_position_capture.bat가 이 스크립트를 호출한다)

$ErrorActionPreference = "Stop"

$RepoDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ScreenshotRoot = "C:\Users\HUI\OneDrive\문서\XuanZhi9\Pictures\Screenshots"
$LDPlayerTitle = "LDPlayer"

$LaunchAppHotkey = "+{F2}"      # SHIFT+F2 (9UP 앱 실행)
$FantasyModeHotkey = "+{F3}"    # SHIFT+F3 (판타지 모드 진입)
$CaptureHotkey = "+{F1}"        # SHIFT+F1 (기존 매크로, 포지션/투수 선택 후 실행)

# 폴더명 -> (선택 단축키, 표시용 이름). 녹화하신 실제 순서 그대로(SHIFT+F4~F12).
$Targets = [ordered]@{
    "1b" = @{ Key = "+{F4}";  Label = "1루수" }
    "2b" = @{ Key = "+{F5}";  Label = "2루수" }
    "ss" = @{ Key = "+{F6}";  Label = "유격수" }
    "3b" = @{ Key = "+{F7}";  Label = "3루수" }
    "c"  = @{ Key = "+{F8}";  Label = "포수" }
    "lf" = @{ Key = "+{F9}";  Label = "좌익수" }
    "cf" = @{ Key = "+{F10}"; Label = "중견수" }
    "rf" = @{ Key = "+{F11}"; Label = "우익수" }
    "dh" = @{ Key = "+{F12}"; Label = "지명타자" }
    "p"  = @{ Key = "+0";     Label = "투수(선발)"; MonthlyOnly = $true }
    "rp" = @{ Key = "+-";    Label = "투수(구원)"; MonthlyOnly = $true }
    # 구원투수도 선발 목록(p)에 뜨긴 하지만 스크롤 12번 안에 안 나올 수 있어서 따로 캡쳐.
}

$WaitAfterSelectSeconds = 3     # 포지션 선택 후 화면 전환 대기
$WaitAfterCaptureSeconds = 60   # 스크롤+캡쳐 매크로가 다 돌 때까지 대기(실제 소요시간 보고 조절)

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
}
"@

function Find-LDPlayerWindow([string]$title) {
    # wscript.shell의 AppActivate/FindWindow(ANSI)는 이 환경에서 LDPlayer 창을 못 찾는
    # 현상이 있어서(EnumWindows로는 정상적으로 잡힘 — 원인 불명, 유니코드/ANSI 마샬링
    # 차이로 추정), EnumWindows 기반으로 직접 핸들을 찾는다.
    $found = [IntPtr]::Zero
    $callback = {
        param($hWnd, $lParam)
        if ([LDWin]::IsWindowVisible($hWnd)) {
            $sb = New-Object System.Text.StringBuilder 256
            [LDWin]::GetWindowText($hWnd, $sb, 256) | Out-Null
            if ($sb.ToString() -eq $title) { $script:found = $hWnd; return $false }
        }
        return $true
    }
    [LDWin]::EnumWindows($callback, [IntPtr]::Zero) | Out-Null
    return $found
}

function Send-ToLDPlayer([string]$keys) {
    $hwnd = Find-LDPlayerWindow $LDPlayerTitle
    if ($hwnd -eq [IntPtr]::Zero) {
        throw "LD플레이어 창을 찾을 수 없습니다 ('$LDPlayerTitle') — 창이 켜져 있는지 확인하세요."
    }
    [LDWin]::ShowWindow($hwnd, 9) | Out-Null  # SW_RESTORE(최소화돼 있으면 복원)
    if (-not [LDWin]::SetForegroundWindow($hwnd)) {
        throw "LD플레이어 창을 활성화하지 못했습니다."
    }
    Start-Sleep -Milliseconds 500
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

Write-Host "[1/4] 9UP 앱 실행..."
Send-ToLDPlayer $LaunchAppHotkey
Start-Sleep -Seconds 15   # 앱 로딩 대기 — 실제 소요 시간 보고 조절

Write-Host "[1/4] 판타지 모드 진입..."
Send-ToLDPlayer $FantasyModeHotkey
Start-Sleep -Seconds 5

$todayDay = (Get-Date).Day
$isCostDay = ($todayDay -eq 1) -or ($todayDay -eq 16)
$dateFolder = Get-Date -Format "yyyy-MM-dd"  # 캡쳐한 날짜별로 폴더를 나눠서, 다음날 다시
                                              # 돌릴 때 어제 사진이랑 안 섞이게 한다(예전에
                                              # 묵은 스크린샷이 최신 것과 섞여서 OCR 결과가
                                              # 꼬였던 적이 있었음 — 9/13 예전 사진이 9/15
                                              # 폴더에 남아있던 문제 참고).

foreach ($folder in $Targets.Keys) {
    $info = $Targets[$folder]
    if ($info.MonthlyOnly -and -not $isCostDay) {
        continue  # 투수 화면은 1일/16일에만
    }
    Write-Host "[2/4] $($info.Label) 선택 + 캡쳐..."
    $before = Get-Date
    Send-ToLDPlayer $info.Key
    Start-Sleep -Seconds $WaitAfterSelectSeconds
    Send-ToLDPlayer $CaptureHotkey
    Start-Sleep -Seconds $WaitAfterCaptureSeconds

    $destFolder = Join-Path $ScreenshotRoot "$dateFolder\$folder"
    $moved = Move-NewScreenshots -destFolder $destFolder -since $before
    Write-Host "  -> $moved 장을 $destFolder 로 이동"
}

Write-Host "[3/4] 스크린샷 OCR 분석 + position_db.json 반영..."
Push-Location $RepoDir
try {
    $screenshotDateDir = Join-Path $ScreenshotRoot $dateFolder

    # daily_pipeline.py도 매 주기 position_db.json을 다시 쓰기 때문에(GitHub 서버 쪽에서
    # 몇 분 간격으로 계속 커밋), 여기서 그냥 git pull --rebase로 합치려고 하면 JSON
    # 줄단위 충돌이 나기 쉽다(다른 생성 파일(lp_board.html 등)처럼 "그냥 다시 만들기"가
    # 안 통함 — 원격이 방금 갱신한 auto_position까지 같이 들고 있어야 하므로). 그래서
    # 매 시도마다 원격의 최신 position_db.json으로 맞춘 다음 그 위에 OCR 결과를 다시
    # 얹는 방식으로 몇 번 재시도한다 — 이러면 애초에 git 차원의 충돌이 안 생긴다.
    $maxAttempts = 3
    $pushed = $false
    for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
        git fetch origin
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
        exit 1
    }
} finally {
    Pop-Location
}

Write-Host "완료."
