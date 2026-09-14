"""
9UP 판타지 모드 "코스트"(선수 영입 비용) 조회
====================================
지인이 수기로 정리해 준 fanmo260715_copy.csv(2026-07-15 기준 스냅샷)를 파싱해
(포지션, 이름) -> 코스트 조회 인덱스를 만든다.

CSV 컬럼: 동명, 포지션, 이름, 코스트
  - 포지션은 1B/2B/3B/SS/C/LF/CF/RF/DH(타자) 또는 SP/P(투수, P=구원) 표기.
  - 동명은 "같은 포지션에 동명이인이 있을 때만" 채우는 구분자다. fanmo260901.csv부터는
    네이버가 주는 고유 식별자 player_code(숫자 문자열)를 적는다 — 팀명 텍스트는 트레이드가
    나면 못 쓰게 되고, 9UP 앱 화면을 다시 캡쳐할 때마다 사진으로 사람을 재확인해야 하는
    번거로움이 있어서, 한 번 data_*.json에서 실제 player_code를 찾아 박아두면 그 뒤로는
    앱 화면을 다시 볼 필요 없이 이름+player_code만으로 영구히 구분된다. 예전 스냅샷
    (fanmo260816.csv, fanmo260715_copy.csv)은 여전히 팀명(+등번호) 텍스트 방식이라
    두 형식을 함께 지원한다(동명 값이 숫자면 player_code, 아니면 팀명 힌트로 취급).

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


EARLIEST_INVESTIGATED = "20260101"  # 이보다 이전(2023~2025시즌 등)은 코스트를 조사한 적이 없다.


def snapshot_for(date_str: str | None) -> str | None:
    """경기 날짜에 해당하는 코스트 스냅샷 파일명. 없으면 None(코스트 공란 처리).

    date_str 은 'YYYYMMDD' 또는 'YYYY-MM-DD'. 코스트는 매달 1일/16일 두 번 갱신되는
    9UP 앱 화면을 실제로 캡쳐해서 조사한 값이라, 우리가 그 시점을 조사한 적이 없으면
    (2026년 이전 시즌 전체, 또는 등록된 스냅샷 구간에 안 들어가는 미래 날짜) 지난
    스냅샷을 그대로 갖다 쓰지 않고 None을 돌려준다 — 조용히 틀린 코스트가 박히는 것보다
    "코스트 데이터 없음"으로 공란 표시되는 게 낫다(2023~2024시즌을 재수집한 뒤, 전혀
    다른 시즌 경기에 2026-07-15 스냅샷 코스트가 그대로 붙어있던 걸 이렇게 고쳤다).
    """
    if not date_str:
        return None
    d = date_str.replace("-", "")
    if d < EARLIEST_INVESTIGATED:
        return None
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


def _hint_matches(hint: str, team: str, player_code: str | None) -> bool:
    """동명 힌트 하나가 지금 조회 중인 선수와 같은 사람을 가리키는지 판정한다.

    힌트가 숫자로만 이루어져 있으면 player_code로 취급해 정확히 일치하는지만 본다
    (신규 방식 — fanmo260901.csv부터). 그렇지 않으면 예전 방식대로 팀명(+등번호)
    텍스트가 team으로 시작하는지로 판정한다(구 스냅샷 하위 호환)."""
    if not hint:
        return False
    if hint.isdigit():
        return player_code is not None and hint == player_code
    if not team:
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

    def lookup_batter(self, name: str, team: str, position: str,
                      player_code: str | None = None) -> int | None:
        exact = self.batter_by_pos_name.get((position, name))
        if exact:
            if len(exact) == 1:
                return exact[0][1]
            matched = [c for hint, c in exact if _hint_matches(hint, team, player_code)]
            return matched[0] if len(matched) == 1 else None

        fallback = self.batter_by_name.get(name)
        if not fallback:
            return None
        if len(fallback) == 1:
            return fallback[0][2]
        matched = [c for _pos, hint, c in fallback if _hint_matches(hint, team, player_code)]
        return matched[0] if len(matched) == 1 else None

    def lookup_pitcher(self, name: str, team: str, player_code: str | None = None) -> int | None:
        candidates = self.pitcher_by_name.get(name)
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0][2]
        matched = [c for _pos, hint, c in candidates if _hint_matches(hint, team, player_code)]
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
                       date_str: str | None = None, player_code: str | None = None) -> int | None:
    idx = _load_index(snapshot_for(date_str))
    return idx.lookup_batter(name, team, position, player_code) if idx else None


def lookup_pitcher_cost(name: str, team: str,
                        date_str: str | None = None, player_code: str | None = None) -> int | None:
    idx = _load_index(snapshot_for(date_str))
    return idx.lookup_pitcher(name, team, player_code) if idx else None
