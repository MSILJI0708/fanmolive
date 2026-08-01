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

from naver_fantasy_score import collect_date, load_position_map
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

    out_path = os.path.join(HERE, f"data_{date_str.replace('-', '')}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"batters": batters, "pitchers": pitchers, "date": date_str}, f, ensure_ascii=False)
    print(f"저장 완료: {out_path}")


if __name__ == "__main__":
    main()
