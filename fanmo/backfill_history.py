"""season_calendar.json(scan_season_calendar.py로 만든, 날짜별 roundCode/game_ids 색인)을
기준으로, 정규시즌(kbo_r)과 포스트시즌(kbo_ps_*)에 해당하는 모든 날짜의 data_YYYYMMDD.json을
새로 만든다(시범경기 kbo_e, 올스타 kbo_as는 제외).

이미 data_YYYYMMDD.json이 있는 날짜는 건너뛰므로 몇 번이고 다시 실행해도 안전하고, 중간에
끊겨도 이어서 진행할 수 있다. 경기 하나하나가 네트워크 I/O로 대부분의 시간을 쓰기 때문에,
날짜를 몇 개씩 묶어("웨이브") 그 안의 경기 전체를 스레드풀로 동시에 처리한다 — 순차 처리 대비
훨씬 빠르다. 한 웨이브가 끝날 때마다 시간 예산을 확인해서, 넘겼으면 그 시점까지 완성된 날짜만
남기고 깔끔하게 끝낸다(다음 실행이 자동으로 이어서 진행)."""
import concurrent.futures as cf
import json
import os
import time

from naver_fantasy_score import load_position_map, process_game

HERE = os.path.dirname(os.path.abspath(__file__))
CALENDAR_PATH = os.path.join(HERE, "season_calendar.json")
INCLUDE_ROUNDS = {"kbo_r", "kbo_ps_wd", "kbo_ps_sp", "kbo_ps_po", "kbo_ps_ks"}
BUDGET_SECONDS = 8 * 60
WAVE_SIZE = 6  # 한 번에 동시 처리할 날짜 수
MAX_WORKERS = 8  # 경기 단위 동시 요청 수(네이버 서버에 과도한 부담을 주지 않는 선)


def fname_for(date_str: str) -> str:
    return os.path.join(HERE, f"data_{date_str.replace('-', '')}.json")


def main():
    with open(CALENDAR_PATH, encoding="utf-8") as f:
        calendar = json.load(f)

    targets = sorted(
        ds for ds, info in calendar.items()
        if info.get("round") in INCLUDE_ROUNDS and info.get("game_ids")
    )
    remaining = [ds for ds in targets if not os.path.exists(fname_for(ds))]
    print(f"대상 {len(targets)}일 중 미수집 {len(remaining)}일", flush=True)

    position_map = load_position_map()
    start = time.time()
    done_dates = 0
    i = 0
    with cf.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        while i < len(remaining):
            if time.time() - start > BUDGET_SECONDS:
                print("시간 예산 소진, 다음 실행에서 이어서 진행", flush=True)
                break
            wave = remaining[i:i + WAVE_SIZE]
            i += WAVE_SIZE
            batters_by_date = {ds: [] for ds in wave}
            pitchers_by_date = {ds: [] for ds in wave}
            futures = {
                ex.submit(process_game, gid, position_map=position_map): (ds, gid)
                for ds in wave for gid in calendar[ds]["game_ids"]
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
                done_dates += 1
                print(f"=== {ds} 완료 ({len(batters)}타자/{len(pitchers)}투수)", flush=True)

    still_left = sum(1 for ds in targets if not os.path.exists(fname_for(ds)))
    print(f"이번 실행 {done_dates}일 수집. 전체 대상 중 남은 미수집: {still_left}일", flush=True)


if __name__ == "__main__":
    main()
