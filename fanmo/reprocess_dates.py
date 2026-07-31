"""주어진 날짜 목록만 골라서 처음부터 다시 수집한다(만루홈런 파싱 버그 등 특정 버그가
영향을 준 날짜만 다시 돌릴 때 쓰는 범용 스크립트). 사용법:
    python reprocess_dates.py 2025-03-23 2025-03-25 ...
날짜 인자가 없으면 이 파일 안의 DATES 리스트를 사용한다."""
import concurrent.futures as cf
import json
import os
import sys

from naver_fantasy_score import fetch_schedule, load_position_map, process_game

HERE = os.path.dirname(os.path.abspath(__file__))
MAX_WORKERS = 8

DATES = [
    "2025-03-23", "2025-03-25", "2025-05-04", "2025-05-07", "2025-05-22",
    "2025-06-01", "2025-06-10", "2025-06-14", "2025-06-19", "2025-06-28",
    "2025-07-05", "2025-07-20", "2025-07-25", "2025-08-10", "2025-08-14",
    "2025-08-16", "2025-08-17", "2025-08-21", "2025-08-23", "2025-08-27",
    "2025-09-04", "2025-09-26", "2026-04-02", "2026-04-05", "2026-05-10",
    "2026-05-14", "2026-05-15", "2026-05-29", "2026-05-30", "2026-06-04",
    "2026-06-06", "2026-06-10", "2026-06-14", "2026-06-16", "2026-06-20",
    "2026-06-23", "2026-06-27", "2026-06-28", "2026-07-17", "2026-07-18",
    "2026-07-31",
]


def fname_for(date_str: str) -> str:
    return os.path.join(HERE, f"data_{date_str.replace('-', '')}.json")


def main():
    dates = sys.argv[1:] or DATES
    calendar = {}
    cal_path = os.path.join(HERE, "season_calendar.json")
    if os.path.exists(cal_path):
        with open(cal_path, encoding="utf-8") as f:
            calendar = json.load(f)

    position_map = load_position_map()
    batters_by_date = {ds: [] for ds in dates}
    pitchers_by_date = {ds: [] for ds in dates}

    with cf.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {}
        for ds in dates:
            game_ids = (calendar.get(ds) or {}).get("game_ids")
            if not game_ids:
                game_ids = [g["gameId"] for g in fetch_schedule(ds) if not g.get("cancel")]
            for gid in game_ids:
                fut = ex.submit(process_game, gid, position_map=position_map)
                futures[fut] = (ds, gid)
        for fut in cf.as_completed(futures):
            ds, gid = futures[fut]
            try:
                b, p = fut.result()
            except Exception as exc:  # noqa: BLE001
                print(f"  {gid} 처리 실패: {exc}")
                continue
            batters_by_date[ds].extend(b)
            pitchers_by_date[ds].extend(p)

    for ds in dates:
        batters = sorted(batters_by_date[ds], key=lambda r: -r["lp"])
        pitchers = sorted(pitchers_by_date[ds], key=lambda r: -r["lp"])
        with open(fname_for(ds), "w", encoding="utf-8") as f:
            json.dump({"batters": batters, "pitchers": pitchers, "date": ds}, f, ensure_ascii=False)
        print(f"=== {ds} 재수집 완료 ({len(batters)}타자/{len(pitchers)}투수)")


if __name__ == "__main__":
    main()
