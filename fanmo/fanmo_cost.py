"""
9UP 판타지 모드 "코스트"(선수 영입 비용) 조회
====================================
지인이 수기로 정리해 준 fanmo260715_copy.csv(2026-07-15 기준 스냅샷)를 파싱해
(포지션, 이름) -> 코스트 조회 인덱스를 만든다.

CSV 컬럼: 동명, 포지션, 이름, 코스트
  - 포지션은 1B/2B/3B/SS/C/LF/CF/RF/DH(타자) 또는 SP/P(투수, P=구원) 표기.
  - 동명은 "같은 포지션에 동명이인이 있을 때만" 팀명(+등번호)을 적어 구분한 것이고,
    나머지 절대다수 행은 비어 있다(그 포지션에서 이름이 유일하다는 뜻).
  - 이 프로젝트의 실제 데이터는 팀명을 "KIA/삼성/LG/KT/두산/SSG/한화/롯데/NC/키움"로
    쓰므로 동명 문자열이 이 팀명으로 시작하는지만 보면 구분된다.

이 스냅샷은 특정 시점(2026-07-15) 기준이라 시간이 지나며 선수 이동/코스트 변동과
어긋날 수 있다 — 그래도 이름 기준 매칭이라 웬만한 기간에는 그대로 들어맞는다.
"""
from __future__ import annotations

import csv
import os
from functools import lru_cache

_HERE = os.path.dirname(__file__)

# 코스트 스냅샷은 게임 갱신 주기(매월 1일 / 16일)마다 갈린다.
# (시작일, 종료일, 파일) — 둘 다 포함(inclusive). 날짜는 'YYYYMMDD' 문자열로 비교한다.
SNAPSHOTS = [
    ("20260816", "20260831", "fanmo260816.csv"),
    ("20260901", "20260915", "fanmo260901.csv"),
]
# 스냅샷이 정해지기 전(2026-08-15 이하) 구간에 쓰던 기존 파일.
LEGACY_CSV = "fanmo260715_copy.csv"
CSV_PATH = os.path.join(_HERE, LEGACY_CSV)   # 하위 호환용(날짜 미지정 시)


def snapshot_for(date_str: str | None) -> str | None:
    """경기 날짜에 해당하는 코스트 스냅샷 파일명. 없으면 None.

    date_str 은 'YYYYMMDD' 또는 'YYYY-MM-DD'. None 이면 기존 동작(LEGACY_CSV)을 유지한다.
    등록된 어느 구간에도 안 들어가는 미래 날짜는 None 을 돌려준다 —
    지난 스냅샷을 그대로 갖다 쓰면 조용히 틀린 코스트가 박히기 때문이다.
    """
    if not date_str:
        return LEGACY_CSV
    d = date_str.replace("-", "")
    if d < SNAPSHOTS[0][0]:
        return LEGACY_CSV
    for lo, hi, fname in SNAPSHOTS:
        if lo <= d <= hi:
            return fname
    return None

# CSV 포지션 코드 -> naver_fantasy_score/position.py가 쓰는 한글 포지션명
BATTER_POS_TRANSLATE = {
    "1B": "1루수", "2B": "2루수", "3B": "3루수", "SS": "유격수", "C": "포수",
    "LF": "좌익수", "CF": "중견수", "RF": "우익수", "DH": "지명타자",
}
PITCHER_POS_CODES = {"SP", "P"}

TEAM_NAMES = ["KIA", "삼성", "LG", "KT", "두산", "SSG", "한화", "롯데", "NC", "키움"]


def _team_hint_matches(hint: str, team: str) -> bool:
    if not hint or not team:
        return False
    for t in TEAM_NAMES:
        if hint.startswith(t):
            return t == team
    return False


class CostIndex:
    def __init__(self, rows: list[dict]):
        # (한글포지션, 이름) -> [(동명힌트, 코스트), ...]  (타자, 포지션 정확 일치 tier)
        self.batter_by_pos_name: dict[tuple[str, str], list[tuple[str, int]]] = {}
        # 이름 -> [(한글포지션, 동명힌트, 코스트), ...]  (타자, 포지션 무관 폴백 tier)
        self.batter_by_name: dict[str, list[tuple[str, str, int]]] = {}
        # 이름 -> [(CSV포지션(SP/P), 동명힌트, 코스트), ...]  (투수)
        self.pitcher_by_name: dict[str, list[tuple[str, str, int]]] = {}

        for r in rows:
            pos = (r.get("포지션") or "").strip()
            name = (r.get("이름") or "").strip()
            hint = (r.get("동명") or "").strip()
            cost_raw = (r.get("코스트") or "").strip()
            if not pos or not name or not cost_raw:
                continue
            try:
                cost = int(cost_raw)
            except ValueError:
                continue

            if pos in PITCHER_POS_CODES:
                self.pitcher_by_name.setdefault(name, []).append((pos, hint, cost))
                continue

            kor = BATTER_POS_TRANSLATE.get(pos)
            if kor is None:
                continue
            self.batter_by_pos_name.setdefault((kor, name), []).append((hint, cost))
            self.batter_by_name.setdefault(name, []).append((kor, hint, cost))

    def lookup_batter(self, name: str, team: str, position: str) -> int | None:
        exact = self.batter_by_pos_name.get((position, name))
        if exact:
            if len(exact) == 1:
                return exact[0][1]
            matched = [c for hint, c in exact if _team_hint_matches(hint, team)]
            return matched[0] if len(matched) == 1 else None

        fallback = self.batter_by_name.get(name)
        if not fallback:
            return None
        if len(fallback) == 1:
            return fallback[0][2]
        matched = [c for _pos, hint, c in fallback if _team_hint_matches(hint, team)]
        return matched[0] if len(matched) == 1 else None

    def lookup_pitcher(self, name: str, team: str) -> int | None:
        candidates = self.pitcher_by_name.get(name)
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0][2]
        matched = [c for _pos, hint, c in candidates if _team_hint_matches(hint, team)]
        return matched[0] if len(matched) == 1 else None


@lru_cache(maxsize=8)
def _load_index(fname: str | None) -> CostIndex | None:
    if not fname:
        return None
    path = os.path.join(_HERE, fname)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    return CostIndex(rows)


def lookup_batter_cost(name: str, team: str, position: str,
                       date_str: str | None = None) -> int | None:
    idx = _load_index(snapshot_for(date_str))
    return idx.lookup_batter(name, team, position) if idx else None


def lookup_pitcher_cost(name: str, team: str,
                        date_str: str | None = None) -> int | None:
    idx = _load_index(snapshot_for(date_str))
    return idx.lookup_pitcher(name, team) if idx else None
