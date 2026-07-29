"""
오늘(또는 지정한 날짜) 경기를 자동으로 찾아 판타지 LP 데이터를 수집한다.
그날 KBO 일정을 조회 → 아직 시작 전인 경기는 건너뛰고 → 각 경기의 박스스코어+텍스트
중계를 모아 LP를 계산해 data_<date>.json으로 저장한다. build_board.py가 그 파일을 읽어
HTML 보드를 만든다.

사용법:
    python daily_pipeline.py                  # 오늘 날짜
    python daily_pipeline.py --date 2026-07-30
    python daily_pipeline.py --skip-position  # 포지션 재집계 생략(이미 오늘자로 갱신했을 때)
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import date

from naver_fantasy_score import collect_date, load_position_map
from position import build_position_db

HERE = os.path.dirname(os.path.abspath(__file__))


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
    batters, pitchers = run(date_str, days=args.days, refresh_position=not args.skip_position)

    out_path = os.path.join(HERE, f"data_{date_str.replace('-', '')}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"batters": batters, "pitchers": pitchers, "date": date_str}, f, ensure_ascii=False)
    print(f"저장 완료: {out_path}")


if __name__ == "__main__":
    main()
