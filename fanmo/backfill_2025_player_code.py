"""2025시즌 data_2025*.json(180일)을 전부 다시 수집해 player_code를 채워 넣는다.

2025년 데이터는 naver_fantasy_score.py가 아직 player_code를 저장하지 않던 시기에
모은 것이라, 통산 기록실 집계(build_stats.py, player_code로 선수를 묶음)에서
전부 빠져 있다(detect_errors.py의 MISSING_PLAYER_CODE 2만6천여 건이 전부 이거다).
지금 코드로 다시 수집하면 player_code·round·소수 이닝 표기 등 그 사이 고쳐진 것도
전부 같이 적용된다.

reprocess_all_v2.py와 같은 패턴(시간 예산 안에서 몇 개씩 나눠 처리, 완료한 날짜는
backfill_2025_done.json에 기록해 두고 다음 실행에서 이어감)이되, round 필드까지
같이 채운다는 점이 다르다.

사용법: python backfill_2025_player_code.py  (여러 번 나눠 실행해도 안전)
"""
import concurrent.futures as cf
import glob
import json
import os
import time

from naver_fantasy_score import fetch_round, fetch_schedule, load_position_map, process_game

HERE = os.path.dirname(os.path.abspath(__file__))
DONE_PATH = os.path.join(HERE, "backfill_2025_done.json")
BUDGET_SECONDS = 8 * 60
WAVE_SIZE = 6
MAX_WORKERS = 8


def fname_for(date_str: str) -> str:
    return os.path.join(HERE, f"data_{date_str.replace('-', '')}.json")


def all_2025_dates() -> list:
    dates = []
    for fp in sorted(glob.glob(os.path.join(HERE, "data_2025????.json"))):
        dc = os.path.basename(fp)[len("data_"):-len(".json")]
        dates.append(f"{dc[0:4]}-{dc[4:6]}-{dc[6:8]}")
    return dates


def main():
    done = set()
    if os.path.exists(DONE_PATH):
        with open(DONE_PATH, encoding="utf-8") as f:
            done = set(json.load(f))

    calendar = {}
    cal_path = os.path.join(HERE, "season_calendar.json")
    if os.path.exists(cal_path):
        with open(cal_path, encoding="utf-8") as f:
            calendar = json.load(f)

    remaining = [ds for ds in all_2025_dates() if ds not in done]
    print(f"2025시즌 전체 {len(all_2025_dates())}일 중 미완료 {len(remaining)}일", flush=True)

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

            game_ids_by_date = {}
            round_by_date = {}
            for ds in wave:
                gids = (calendar.get(ds) or {}).get("game_ids")
                if not gids:
                    try:
                        games = [g for g in fetch_schedule(ds) if not g.get("cancel")]
                    except Exception as exc:  # noqa: BLE001
                        print(f"  {ds} 일정 조회 실패: {exc}", flush=True)
                        games = []
                    gids = [g["gameId"] for g in games]
                game_ids_by_date[ds] = gids
                round_by_date[ds] = None
                if gids:
                    try:
                        round_by_date[ds] = fetch_round(gids[0])
                    except Exception as exc:  # noqa: BLE001
                        print(f"  {ds} 라운드 조회 실패(무시): {exc}", flush=True)

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

    still_left = len(all_2025_dates()) - len(done)
    print(f"이번 실행 후 남은 미완료: {still_left}일", flush=True)


if __name__ == "__main__":
    main()
