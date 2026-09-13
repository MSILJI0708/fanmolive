"""2023~2024시즌(386일, season_calendar.json에 경기가 있는 것으로 확인된 날짜)을
처음부터 수집해 data_2023*.json / data_2024*.json을 새로 만든다.

이 두 시즌은 지금까지 한 번도 수집한 적이 없어서(기존 데이터는 2025년부터 시작),
2025년 재수집(backfill_2025_player_code.py)과 달리 기존 파일을 다시 처리하는 게
아니라 완전히 새로 만든다 — 그래서 처음부터 player_code·round가 다 채워져 있다.

reprocess_all_v2.py/backfill_2025_player_code.py와 같은 패턴: 시간 예산 안에서
몇 개씩 나눠 처리하고, 완료한 날짜는 backfill_2023_2024_done.json에 기록해 둬서
여러 번 나눠 실행해도 안전하다.

사용법: python backfill_2023_2024.py
"""
import concurrent.futures as cf
import json
import os
import time

from naver_fantasy_score import load_position_map, process_game

HERE = os.path.dirname(os.path.abspath(__file__))
DONE_PATH = os.path.join(HERE, "backfill_2023_2024_done.json")
CAL_PATH = os.path.join(HERE, "season_calendar.json")
BUDGET_SECONDS = 8 * 60
WAVE_SIZE = 6
MAX_WORKERS = 8


def fname_for(date_str: str) -> str:
    return os.path.join(HERE, f"data_{date_str.replace('-', '')}.json")


def target_dates() -> list:
    with open(CAL_PATH, encoding="utf-8") as f:
        cal = json.load(f)
    dates = [
        ds for ds, info in cal.items()
        if (ds.startswith("2023") or ds.startswith("2024")) and info.get("round") is not None
    ]
    return sorted(dates)


def main():
    done = set()
    if os.path.exists(DONE_PATH):
        with open(DONE_PATH, encoding="utf-8") as f:
            done = set(json.load(f))

    with open(CAL_PATH, encoding="utf-8") as f:
        calendar = json.load(f)

    remaining = [ds for ds in target_dates() if ds not in done]
    print(f"2023-2024 대상 {len(target_dates())}일 중 미완료 {len(remaining)}일", flush=True)

    position_map = load_position_map()
    start = time.time()
    i = 0
    with cf.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        while i < len(remaining):
            if time.time() - start > BUDGET_SECONDS:
                print("시간 예산 소진, 다음 실행에서 이어서 진행", flush=True)
                break
            wave = remaining[i:i + WAVE_SIZE]
            i += WAVE_SIZE

            game_ids_by_date = {ds: calendar[ds]["game_ids"] for ds in wave}
            round_by_date = {ds: calendar[ds]["round"] for ds in wave}

            batters_by_date = {ds: [] for ds in wave}
            pitchers_by_date = {ds: [] for ds in wave}
            futures = {
                ex.submit(process_game, gid, position_map=position_map): (ds, gid)
                for ds in wave for gid in game_ids_by_date[ds]
            }
            for fut in cf.as_completed(futures):
                ds, gid = futures[fut]
                try:
                    b, p = fut.result()
                except Exception as exc:  # noqa: BLE001
                    print(f"  {gid} 처리 실패: {exc}", flush=True)
                    continue
                batters_by_date[ds].extend(b)
                pitchers_by_date[ds].extend(p)

            for ds in wave:
                batters = sorted(batters_by_date[ds], key=lambda r: -r["lp"])
                pitchers = sorted(pitchers_by_date[ds], key=lambda r: -r["lp"])
                with open(fname_for(ds), "w", encoding="utf-8") as f:
                    json.dump(
                        {"batters": batters, "pitchers": pitchers, "date": ds, "round": round_by_date[ds]},
                        f, ensure_ascii=False,
                    )
                done.add(ds)
                missing = sum(1 for r in batters + pitchers if not r.get("player_code"))
                print(f"=== {ds} 완료 ({len(batters)}타자/{len(pitchers)}투수, "
                      f"player_code 없음 {missing}명, round={round_by_date[ds]})", flush=True)

            with open(DONE_PATH, "w", encoding="utf-8") as f:
                json.dump(sorted(done), f, ensure_ascii=False)

    still_left = len(target_dates()) - len(done)
    print(f"이번 실행 후 남은 미완료: {still_left}일", flush=True)


if __name__ == "__main__":
    main()
