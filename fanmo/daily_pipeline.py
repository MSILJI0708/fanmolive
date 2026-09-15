"""
오늘(또는 지정한 날짜) 경기를 자동으로 찾아 판타지 LP 데이터를 수집한다.
그날 KBO 일정을 조회 → 아직 시작 전인 경기는 건너뛰고 → 각 경기의 박스스코어+텍스트
중계를 모아 LP를 계산해 data_<date>.json으로 저장한다. build_board.py가 그 파일을 읽어
HTML 보드를 만든다.

사용법:
    python daily_pipeline.py                  # 오늘 날짜
    python daily_pipeline.py --date 2026-07-30
    python daily_pipeline.py --skip-position  # 포지션 재집계 생략(이미 오늘자로 갱신했을 때)

포지션 재집계(build_position_db)는 최근 14일치 일정+박스스코어를 전부 다시 조회해서
(최대 14 + 14*5 ≈ 84번의 API 호출) 자동화가 매번(활성 구간 중 몇 분 간격) 호출하기엔
너무 무겁다 — 포지션은 어차피 하루이틀 안에 잘 안 바뀌는 값이라, POSITION_REFRESH_INTERVAL
이상 지났을 때만 실제로 재집계하고 그 사이엔 건너뛴다(마지막 재집계 시각은
position_last_refresh.txt에 저장). 라이브 경기 중 네이버 API가 느려질 때 이 재집계까지
겹쳐서 파이프라인 전체가 오래 걸리는(심하면 몇 분씩 멈추는) 문제의 주된 원인이었다.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import date

from data_paths import fname_for
from naver_fantasy_score import collect_date, fetch_round, fetch_schedule, load_position_map
from position import build_position_db

HERE = os.path.dirname(os.path.abspath(__file__))
POSITION_REFRESH_INTERVAL = 60 * 60  # 1시간
POSITION_LAST_REFRESH_PATH = os.path.join(HERE, "position_last_refresh.txt")


def _position_refresh_due() -> bool:
    try:
        with open(POSITION_LAST_REFRESH_PATH, encoding="utf-8") as f:
            last = float(f.read().strip())
    except (FileNotFoundError, ValueError):
        return True
    return (time.time() - last) >= POSITION_REFRESH_INTERVAL


def _mark_position_refreshed() -> None:
    with open(POSITION_LAST_REFRESH_PATH, "w", encoding="utf-8") as f:
        f.write(str(time.time()))


def _richness(batters: list[dict], pitchers: list[dict]) -> int:
    """이 수집 결과가 얼마나 "실제 경기가 진행된" 내용을 담고 있는지 보는 대략적인 지표
    (타자 타수 합 + 투수 아웃카운트 합). 경기가 실제로 진행되는 동안엔 이 값이 절대
    줄어들 수 없다 — 그래서 새로 수집한 값이 이미 저장된 파일보다 작으면(특히 0이면)
    "경기가 아직 시작 안 함(BEFORE) → 라인업만 있는 0점 placeholder"로 잘못 되돌아간
    것이지, 정상적인 진행이 아니다(2026-09-13 실제 사례: 네이버 일정 API가 경기 종료
    후에도 일시적으로 옛 상태를 돌려줘서, 이미 다 모은 실제 기록이 placeholder로
    통째로 덮어써진 적이 있다)."""
    return (sum(b.get("ab", 0) for b in batters)
            + sum(p.get("stat", {}).get("OUT", 0) for p in pitchers))


def run(date_str: str, days: int = 14, refresh_position: bool = True) -> tuple[list[dict], list[dict]]:
    if refresh_position:
        print(f"[1/2] {date_str} 기준 최근 {days}일 수비 기록으로 포지션 갱신 중...")
        build_position_db(date_str, days=days)
    else:
        print("[1/2] 포지션 갱신 생략(--skip-position)")

    position_map = load_position_map()

    print(f"[2/2] {date_str} 경기 데이터 수집 중...")
    batters, pitchers = collect_date(date_str, position_map=position_map)
    batters.sort(key=lambda r: -r["lp"])
    pitchers.sort(key=lambda r: -r["lp"])

    if not batters and not pitchers:
        print("      아직 시작한 경기가 없습니다(전부 BEFORE 상태). 경기 시작 후 다시 실행하세요.")
    else:
        print(f"      타자 {len(batters)}명, 투수 {len(pitchers)}명 처리 완료")

    return batters, pitchers


def main():
    ap = argparse.ArgumentParser(description="오늘(또는 지정 날짜) KBO 경기를 자동으로 찾아 LP 데이터 수집")
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (생략 시 오늘 날짜)")
    ap.add_argument("--days", type=int, default=14, help="포지션 집계 기간(일)")
    ap.add_argument("--skip-position", action="store_true", help="포지션 재집계 생략")
    args = ap.parse_args()

    date_str = args.date or date.today().isoformat()
    refresh_position = not args.skip_position and _position_refresh_due()
    batters, pitchers = run(date_str, days=args.days, refresh_position=refresh_position)
    if refresh_position:
        _mark_position_refreshed()

    # round: 올스타전(kbo_as) 등 이벤트성 경기를 실제 시즌 성적(세이브/홀드 누적 등) 집계에서
    # 가려낼 수 있게 표시만 해 둔다 — 데이터 자체는 지우지 않고 계속 그대로 수집·저장한다.
    round_code = None
    any_canceled = False
    try:
        all_games = fetch_schedule(date_str)
        any_canceled = any(g.get("cancel") for g in all_games)
        games = [g for g in all_games if not g.get("cancel")]
        if games:
            round_code = fetch_round(games[0]["gameId"])
    except Exception as exc:  # noqa: BLE001
        print(f"  라운드 조회 실패(무시하고 계속): {exc}")

    out_path = fname_for(date_str)

    # 이미 저장된 파일보다 이번에 수집한 내용이 더 부실하면(특히 완전히 0이면) 저장을
    # 건너뛴다 — 네이버 일정 API가 경기 종료 후에도 일시적으로 낡은 상태(BEFORE/READY)를
    # 돌려주는 경우가 실제로 있어서, 그걸 그대로 믿고 덮어쓰면 이미 모아둔 실제 기록이
    # 라인업만 있는 0점 placeholder로 되돌아간다(2026-09-13 실제 발생).
    #
    # 다만 "경기 도중 노게임 처리"(진행되던 경기가 취소돼 그날까지의 개인 기록이 공식적으로
    # 전부 무효가 되는 경우)도 richness가 정상적으로 줄어드는 정당한 사례라 이 가드에 걸리면
    # 안 된다 — 그 순간 일정 API에 cancel=true가 실제로 붙어 있는지를 같이 확인해서, 취소가
    # 확인되면(any_canceled) 줄어든 값도 그대로 믿고 저장한다.
    new_richness = _richness(batters, pitchers)
    if os.path.exists(out_path) and not any_canceled:
        try:
            with open(out_path, encoding="utf-8") as f:
                old = json.load(f)
            old_richness = _richness(old.get("batters", []), old.get("pitchers", []))
        except (json.JSONDecodeError, OSError):
            old_richness = 0
        if new_richness < old_richness:
            print(f"[경고] 새로 수집한 데이터가 기존 파일보다 부실합니다"
                  f"(신규={new_richness} < 기존={old_richness}) — 취소된 경기도 없는데"
                  f" 줄어들어서, 네이버 API가 일시적으로 낡은 상태를 돌려준 것으로 보여"
                  f" 저장을 건너뛰고 기존 파일을 그대로 둡니다.")
            return

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(
            {"batters": batters, "pitchers": pitchers, "date": date_str, "round": round_code},
            f, ensure_ascii=False,
        )
    print(f"저장 완료: {out_path} (round={round_code})")


if __name__ == "__main__":
    main()
