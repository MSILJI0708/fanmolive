"""2001~2007년(네이버 API에 없는 구간) KBO 공식 사이트 박스스코어를 시간 예산 안에서
할 수 있는 만큼 채운다. kbo_official.py를 이 스크립트가 씀. 2008~2022년은
historical_backfill_step.py(네이버 기반)가 이미 담당하므로, 이 스크립트는 그쪽 1단계가
다 끝난 뒤에 이어받아 돌아간다(fantasy-lp-board.yml에서 순서대로 호출).

네이버 쪽은 하루하루 일정을 조회해야 하지만, KBO 공식 사이트는 한 번 호출로 한 달치
일정이 통째로 나와서 1단계(일정 채우기)가 훨씬 빠르다 — 7년×12개월 = 84번 호출이면 끝.
season_calendar.json(네이버용)과 스키마가 달라서(팀명을 같이 저장해야 박스스코어 파싱이
됨) 별도 파일 kbo_official_calendar.json을 쓴다.

data_YYYYMMDD.json은 기존 파이프라인과 완전히 같은 형식(batters/pitchers/date/round)으로
쓰기 때문에 build_stats.py가 별도 수정 없이 그대로 집계한다. round는 항상 "kbo_r"
(정규시즌) — KBO 공식 사이트 일정 조회 자체를 "정규시즌 일정"(srIdList=0,9,6)으로만
하기 때문에 시범경기/포스트시즌은 애초에 안 들어온다.

사용법: python kbo_2001_2007_backfill_step.py
"""
from __future__ import annotations

import json
import os
import time

from kbo_official import (
    _load_player_cache, _save_player_cache, fetch_and_parse_box_score, fetch_schedule_month,
)

HERE = os.path.dirname(os.path.abspath(__file__))
CAL_PATH = os.path.join(HERE, "kbo_official_calendar.json")

START_SEASON = 2001
END_SEASON = 2007
MONTHS = [f"{m:02d}" for m in range(1, 13)]

BUDGET_SECONDS = 90  # 메인 파이프라인 한 회차 안에서 historical_backfill_step.py(2008~2022)와 시간을 나눠 씀


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
    """START_SEASON~END_SEASON의 각 (연도,월)을 한 번에 조회해 날짜별 경기 목록을 채운다.
    한 달 전체가 한 번의 호출로 끝나서 보통 이 함수 하나로 1단계가 통째로 끝난다."""
    cal = load_calendar()
    done_key = "__months_done__"
    done_months = set(cal.get(done_key, []))
    changed = False
    for season in range(START_SEASON, END_SEASON + 1):
        for month in MONTHS:
            key = f"{season}-{month}"
            if key in done_months:
                continue
            if time.time() >= deadline:
                if changed:
                    cal[done_key] = sorted(done_months)
                    save_calendar(cal)
                print(f"[1단계] 시간 예산 소진, {key}까지 진행 중 중단")
                return False
            try:
                games = fetch_schedule_month(season, month)
            except Exception as exc:  # noqa: BLE001
                print(f"  {key} 일정 조회 실패: {exc}")
                continue
            for g in games:
                cal.setdefault(g["date"], []).append(
                    {"game_id": g["game_id"], "away": g["away"], "home": g["home"]}
                )
            done_months.add(key)
            changed = True
            print(f"  {key}: {len(games)}경기")
    cal[done_key] = sorted(done_months)
    if changed:
        save_calendar(cal)
    print("[1단계] 완료 — 2001~2007년 일정 전체 확보")
    return True


def backfill_data(deadline: float) -> None:
    cal = load_calendar()
    dates = sorted(d for d in cal if d != "__months_done__")
    remaining = [d for d in dates if not os.path.exists(fname_for(d))]
    print(f"[2단계] 대상 {len(dates)}일 중 미완료 {len(remaining)}일")
    if not remaining:
        print("[2단계] 완료 — 2001~2007년 전체 수집 끝")
        return

    player_cache = _load_player_cache()
    cache_dirty = False
    unresolved: set[str] = set()
    try:
        for ds in remaining:
            if time.time() >= deadline:
                print(f"[2단계] 시간 예산 소진, {len(remaining)}일 남기고 중단")
                return
            season = int(ds[:4])
            batters, pitchers = [], []
            for g in cal[ds]:
                try:
                    b, p = fetch_and_parse_box_score(
                        season, g["game_id"], g["away"], g["home"], player_cache=player_cache
                    )
                except Exception as exc:  # noqa: BLE001
                    print(f"  {g['game_id']} 처리 실패: {exc}")
                    continue
                batters.extend(b)
                pitchers.extend(p)
                cache_dirty = True
            for row in batters + pitchers:
                if not row.get("player_code"):
                    unresolved.add(f"{row['name']}({row['team']})")
            batters.sort(key=lambda r: -r["lp"])
            pitchers.sort(key=lambda r: -r["lp"])
            with open(fname_for(ds), "w", encoding="utf-8") as f:
                json.dump({"batters": batters, "pitchers": pitchers, "date": ds, "round": "kbo_r"},
                           f, ensure_ascii=False)
            print(f"=== {ds} 완료 ({len(batters)}타자/{len(pitchers)}투수)")
    finally:
        if cache_dirty:
            _save_player_cache(player_cache)
        if unresolved:
            path = os.path.join(HERE, "kbo_2001_2007_unresolved_players.json")
            try:
                with open(path, encoding="utf-8") as f:
                    prev = set(json.load(f))
            except (FileNotFoundError, json.JSONDecodeError):
                prev = set()
            with open(path, "w", encoding="utf-8") as f:
                json.dump(sorted(prev | unresolved), f, ensure_ascii=False, indent=1)
            print(f"  선수코드 못 찾은 이름 {len(unresolved)}건 -> kbo_2001_2007_unresolved_players.json")


def main():
    deadline = time.time() + BUDGET_SECONDS
    calendar_done = fill_calendar(deadline)
    if calendar_done and time.time() < deadline:
        backfill_data(deadline)


if __name__ == "__main__":
    main()
