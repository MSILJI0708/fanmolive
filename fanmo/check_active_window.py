"""지금이 "빠르게 갱신해야 할 활성 구간"인지 판정한다.

cron-job.org는 그냥 항상 같은(짧은) 주기로 워크플로우를 호출하게 해두고, "지금 진짜로
수집·빌드·커밋을 할 시점인지"는 매번 이 스크립트로 판단한다 — 활성 구간이 아니면
워크플로우가 몇 초 안에 조용히 끝나서, Actions 실행 횟수는 잦아도 실질 작업(과 커밋)은
경기가 실제로 임박했을 때만 일어난다.

활성 구간 = (오늘 KBO 경기 중 가장 이른 경기 시작 2시간 전) 부터 (그 경기들이 전부
           RESULT로 끝난 뒤 GRACE_MINUTES 유예시간이 지날 때)까지 — 이 구간이
           "경기 시작 2시간 전~라인업 발표"와 "첫 경기 시작~마지막 경기 종료+유예"를
           합친 것과 같다(그 사이 공백은 따로 안 쉬고 계속 활성 상태로 둔다 — cron
           간격을 하나로만 관리하는 게 실무적으로 훨씬 간단하고, public 저장소라 그
           사이에 몇 번 더 도는 것 자체는 비용이 없다).

유예시간이 필요한 이유: 경기가 RESULT로 바뀐 바로 그 순간엔 네이버 공식 승/패/세이브/
홀드 결정(wls)이 아직 안 붙어있는 경우가 흔하다(실제로 몇 분 뒤 뒤바뀌는 것도 관찰됨 —
공식 기록원이 검토하며 계속 수정하는 것으로 보인다). RESULT 즉시 활성 구간을 닫아버리면
그 최종 결정을 다시는 못 받아온다. all_result_since 상태 파일에 "오늘 경기가 전부
RESULT가 된 시각"을 처음 관측한 시점으로 기록해 두고, 그로부터 GRACE_MINUTES가 지날
때까지는 계속 활성 구간으로 본다(그 사이 naver_fantasy_score.py 쪽은 relay.py의 스코어
흐름 기반 자체 판정으로 wls 공백을 임시로 메워두고, 실제 wls가 붙으면 재수집 때마다
그쪽이 항상 우선한다 — 이 유예시간은 그 "실제 wls로 수렴할 기회"를 몇 번 더 주는 것).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import naver_fantasy_score as nfs

KST = timezone(timedelta(hours=9))
GRACE_MINUTES = 20
STATE_PATH = Path(__file__).with_name("active_window_state.json")


def _load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def _save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def is_active_window(now: datetime | None = None) -> bool:
    now = now or datetime.now(KST)
    today = now.date().isoformat()

    try:
        games = nfs.fetch_schedule(today)
    except Exception:  # noqa: BLE001
        return True  # 조회 실패 시엔 안전하게 활성으로 취급(놓치는 것보다 낫다)

    times = []
    any_unfinished = False
    for g in games:
        dt = g.get("gameDateTime")
        if dt:
            times.append(datetime.fromisoformat(dt).replace(tzinfo=KST))
        if g.get("statusCode") != "RESULT":
            any_unfinished = True

    if not times:
        return False  # 오늘 KBO 경기 자체가 없음(휴식일)
    first_game = min(times)
    if now < first_game - timedelta(hours=2):
        return False  # 아직 한참 남음

    state = _load_state()
    if any_unfinished:
        # 아직 안 끝난 경기가 있으면 "전부 끝난 시각" 기록은 의미가 없으니 지워둔다
        # (연장/서스펜디드 등으로 RESULT가 잠깐 됐다가 다시 진행되는 경우 대비).
        if state.get("date") == today:
            _save_state({})
        return True

    # 여기 도달 = 오늘 경기가 전부 RESULT. 처음 관측한 시각을 기준으로 유예시간을 준다.
    if state.get("date") != today:
        state = {"date": today, "since": now.isoformat()}
        _save_state(state)
        return True

    since = datetime.fromisoformat(state["since"])
    elapsed_min = (now - since).total_seconds() / 60
    return elapsed_min < GRACE_MINUTES


if __name__ == "__main__":
    print("true" if is_active_window() else "false")
