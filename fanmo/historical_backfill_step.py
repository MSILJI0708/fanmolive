"""2008~2022년(현재 season_calendar.json 시작점인 2023-01-01 이전) KBO 데이터를
백그라운드로 조금씩 채운다. 사람이 컴퓨터를 켜 두지 않아도 계속 진행되도록
GitHub Actions의 자체 schedule 트리거로 이 스크립트를 몇 분~십수 분 간격으로
계속 호출하는 방식을 쓴다(.github/workflows/historical-backfill.yml) — 그래서
이 스크립트 자체는 "한 번 불릴 때 정해진 시간 예산 안에서 할 수 있는 만큼만 하고
끝난다"는 게 핵심이다. 시간 예산을 넘기고도 안 끝나면 GitHub Actions가 강제로
죽여버려서, 그 직후의 "커밋 & 푸시" 단계가 아예 못 돌고 그 회차 진행분을 통째로
잃어버리기 때문이다.

두 단계로 나뉜다(먼저 것부터 순서대로 끝내고 다음으로 넘어간다):
  1단계: season_calendar.json에 START~END 범위가 다 채워질 때까지, 없는 날짜만
         가볍게(일정 조회 1번, 경기 있으면 라운드 조회 1번 추가) 채운다.
  2단계: 1단계가 끝나면, 그 범위 안에서 실제 경기가 있었는데 아직
         data_YYYYMMDD.json이 없는 날짜를 골라 실제로 수집한다
         (backfill_2023_2024.py와 같은 패턴 — 병렬로 여러 경기씩).

사용법: python historical_backfill_step.py
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import os
import time
from datetime import date, timedelta

from naver_fantasy_score import fetch_json, fetch_schedule, load_position_map, process_game, GAME_URL

HERE = os.path.dirname(os.path.abspath(__file__))
CAL_PATH = os.path.join(HERE, "season_calendar.json")

START = date(2008, 1, 1)
END = date(2022, 12, 31)

BUDGET_SECONDS = 150  # 메인 파이프라인(fantasy-lp-board.yml)의 한 회차 안에 얹혀서 도니까 짧게 잡음
WAVE_SIZE = 6
MAX_WORKERS = 8


def fname_for(date_str: str) -> str:
    return os.path.join(HERE, f"data_{date_str.replace('-', '')}.json")


def load_calendar() -> dict:
    if os.path.exists(CAL_PATH):
        with open(CAL_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_calendar(cal: dict) -> None:
    with open(CAL_PATH, "w", encoding="utf-8") as f:
        json.dump(cal, f, ensure_ascii=False, indent=1)


def fill_calendar(deadline: float) -> bool:
    """START~END 범위에서 아직 season_calendar.json에 없는 날짜를 채운다.
    시간 예산을 다 쓰면 중간에 멈추고 False를 돌려준다(아직 남은 게 있다는 뜻).
    다 채우면 True."""
    cal = load_calendar()
    d = START
    changed = False
    while d <= END:
        if time.time() >= deadline:
            if changed:
                save_calendar(cal)
            print(f"[1단계] 시간 예산 소진, {d.isoformat()}까지 진행 중 중단")
            return False
        ds = d.isoformat()
        if ds not in cal:
            try:
                games = [g for g in fetch_schedule(ds) if not g.get("cancel")]
            except Exception as exc:  # noqa: BLE001
                print(f"  {ds} 일정 조회 실패: {exc}")
                d += timedelta(days=1)
                continue
            if not games:
                cal[ds] = {"round": None, "game_ids": []}
            else:
                gid0 = games[0]["gameId"]
                try:
                    round_code = fetch_json(GAME_URL.format(game_id=gid0))["result"]["game"].get("roundCode")
                except Exception:  # noqa: BLE001
                    round_code = None
                cal[ds] = {"round": round_code, "game_ids": [g["gameId"] for g in games]}
            changed = True
        d += timedelta(days=1)
    if changed:
        save_calendar(cal)
    print("[1단계] 완료 — season_calendar.json이 전체 범위를 다 커버함")
    return True


def target_dates(cal: dict) -> list[str]:
    return sorted(
        ds for ds, info in cal.items()
        if START.isoformat() <= ds <= END.isoformat() and info.get("round") is not None
    )


def backfill_data(deadline: float) -> None:
    """1단계가 끝난 뒤, 아직 안 모은 날짜의 실제 경기 데이터를 시간 예산 안에서 모은다."""
    cal = load_calendar()
    remaining = [ds for ds in target_dates(cal) if not os.path.exists(fname_for(ds))]
    print(f"[2단계] 대상 {len(target_dates(cal))}일 중 미완료 {len(remaining)}일")
    if not remaining:
        print("[2단계] 완료 — 2008~2022년 전체 수집 끝")
        return

    position_map = load_position_map()
    i = 0
    with cf.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        while i < len(remaining) and time.time() < deadline:
            wave = remaining[i:i + WAVE_SIZE]
            i += WAVE_SIZE

            batters_by_date = {ds: [] for ds in wave}
            pitchers_by_date = {ds: [] for ds in wave}
            futures = {
                ex.submit(process_game, gid, position_map=position_map): (ds, gid)
                for ds in wave for gid in cal[ds]["game_ids"]
            }
            for fut in cf.as_completed(futures):
                ds, gid = futures[fut]
                try:
                    b, p = fut.result()
                except Exception as exc:  # noqa: BLE001
                    print(f"  {gid} 처리 실패: {exc}")
                    continue
                batters_by_date[ds].extend(b)
                pitchers_by_date[ds].extend(p)

            for ds in wave:
                batters = sorted(batters_by_date[ds], key=lambda r: -r["lp"])
                pitchers = sorted(pitchers_by_date[ds], key=lambda r: -r["lp"])
                with open(fname_for(ds), "w", encoding="utf-8") as f:
                    json.dump(
                        {"batters": batters, "pitchers": pitchers, "date": ds, "round": cal[ds]["round"]},
                        f, ensure_ascii=False,
                    )
                print(f"=== {ds} 완료 ({len(batters)}타자/{len(pitchers)}투수, round={cal[ds]['round']})")

    still_left = len([ds for ds in target_dates(load_calendar()) if not os.path.exists(fname_for(ds))])
    if time.time() >= deadline and still_left:
        print(f"[2단계] 시간 예산 소진, 남은 미완료 {still_left}일 — 다음 실행에서 이어서 진행")


def main():
    deadline = time.time() + BUDGET_SECONDS
    calendar_done = fill_calendar(deadline)
    if calendar_done and time.time() < deadline:
        backfill_data(deadline)


if __name__ == "__main__":
    main()
