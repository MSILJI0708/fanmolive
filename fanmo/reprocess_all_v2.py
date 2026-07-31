"""전체 수집된 날짜(283일)를 새 코드로 전부 다시 처리한다 — 병살타 타점 이중계산,
폭투/보크/실책/홈스틸로 득점하는 경우의 득점(R) 누락, 박스스코어 슬래시 복합코드
("4구/4구") 파싱 누락을 한꺼번에 고치고 난 뒤 전체를 다시 돌리는 용도.

이미 이 스크립트로 다시 처리된 날짜는 reprocess_v2_done.json에 기록해 두고 건너뛰므로,
여러 번 나눠 실행해도 안전하다(시간 예산을 넘기면 그 시점까지 완료한 날짜만 남기고
깔끔하게 끝난다 — 다음 실행이 이어서 진행)."""
import concurrent.futures as cf
import glob
import json
import os
import time

from naver_fantasy_score import fetch_schedule, load_position_map, process_game

HERE = os.path.dirname(os.path.abspath(__file__))
DONE_PATH = os.path.join(HERE, "reprocess_v2_done.json")
BUDGET_SECONDS = 8 * 60
WAVE_SIZE = 6
MAX_WORKERS = 8


def fname_for(date_str: str) -> str:
    return os.path.join(HERE, f"data_{date_str.replace('-', '')}.json")


def all_dates() -> list:
    dates = []
    for fp in sorted(glob.glob(os.path.join(HERE, "data_????????.json"))):
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

    remaining = [ds for ds in all_dates() if ds not in done]
    print(f"전체 대상 중 미완료 {len(remaining)}일", flush=True)

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
            for ds in wave:
                gids = (calendar.get(ds) or {}).get("game_ids")
                if not gids:
                    gids = [g["gameId"] for g in fetch_schedule(ds) if not g.get("cancel")]
                game_ids_by_date[ds] = gids

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
                    json.dump({"batters": batters, "pitchers": pitchers, "date": ds}, f, ensure_ascii=False)
                done.add(ds)
                print(f"=== {ds} 재처리 완료 ({len(batters)}타자/{len(pitchers)}투수)", flush=True)

            with open(DONE_PATH, "w", encoding="utf-8") as f:
                json.dump(sorted(done), f, ensure_ascii=False)

    still_left = len(all_dates()) - len(done)
    print(f"이번 실행 후 남은 미완료: {still_left}일", flush=True)


if __name__ == "__main__":
    main()
