"""지금이 "빠르게 갱신해야 할 활성 구간"인지 판정한다.

cron-job.org는 그냥 항상 같은(짧은) 주기로 워크플로우를 호출하게 해두고, "지금 진짜로
수집·빌드·커밋을 할 시점인지"는 매번 이 스크립트로 판단한다 — 활성 구간이 아니면
워크플로우가 몇 초 안에 조용히 끝나서, Actions 실행 횟수는 잦아도 실질 작업(과 커밋)은
경기가 실제로 임박했을 때만 일어난다.

활성 구간 = (오늘 KBO 경기 중 가장 이른 경기 시작 2시간 전) 부터 (그 경기들이 전부
           RESULT로 끝날 때) 까지 — 이 구간이 "경기 시작 2시간 전~라인업 발표"와
           "첫 경기 시작~마지막 경기 종료"를 합친 것과 같다(그 사이 공백은 따로 안 쉬고
           계속 활성 상태로 둔다 — cron 간격을 하나로만 관리하는 게 실무적으로 훨씬
           간단하고, public 저장소라 그 사이에 몇 번 더 도는 것 자체는 비용이 없다).
MLB은 미국 경기가 한국 시간 기준 거의 하루 내내 걸쳐 있어서(오후~다음날 오전) 이 기준에
넣으면 활성 구간이 사실상 항상 켜져 있게 돼 버린다 — 그래서 판정은 KBO 일정만 보고,
MLB은 이 활성 구간 동안(워크플로우가 실제로 도는 동안) 겸사겸사 같이 수집한다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import naver_fantasy_score as nfs

KST = timezone(timedelta(hours=9))


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
    return any_unfinished  # 다 끝났으면 더 이상 활성 구간 아님


if __name__ == "__main__":
    print("true" if is_active_window() else "false")
