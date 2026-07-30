"""
MLB 텍스트 중계 파서 (실험)
=============================
KBO용 relay.py와 목적은 같지만(박스스코어에 없는 항목을 타석별 문장에서 직접 뽑아내기),
MLB 중계는 응답 형식 자체가 다르고 정보량도 더 적다:

  - 한 타석의 공/결과가 개별 객체 배열이 아니라 문자열 하나에 <br/>로 이어붙어 있다.
  - 매 이벤트마다 있었던 KBO의 currentGameState(주자 상태, 스코어 스냅샷)가 아예 없다.
    → 승계주자 추적, 세이브 기회(등판 시점 점수차 필요)는 원천적으로 계산 불가.
  - 투수 교체 문구가 "투수 A : B (으)로 교체"라, KBO처럼 들어오는 쪽에 "투수"가 안 붙는다.
  - 수비 위치 교체(포수 등) 문구 자체가 안 보인다 → 포지션은 "선발 그대로 경기 끝까지"라고
    가정하는 정적 근사치를 쓴다. 경기 중 그 자리 선수가 바뀌면 그 이후 귀속은 부정확해진다.
  - 아웃 처리에 "(위치->위치 송구아웃)" 같은 수비 체인이 아예 없다 → 보살/병살 가담/
    삼중살 가담은 계산 불가.

그래서 이 모듈이 실제로 뽑는 건: 타자의 2루타/3루타/병살타/희생플라이/진루타(번트 포함)/
도루실패/견제사, 투수의 피2루타/피3루타/도루허용/도루저지/견제사(전부 "현재 등판 중인
투수" 추적만으로 가능한 것들), 그리고 실책(포지션→선발 라인업 매핑으로 근사, 중간 교체는
못 따라감).
"""

from __future__ import annotations

import re
from collections import defaultdict

from naver_fantasy_score import fetch_json
from relay import classify_relay_desc

RELAY_URL = "https://api-gw.sports.naver.com/schedule/games/{game_id}/relay?inning={inning}"

_SUB_RE = re.compile(r"^투수 (?P<out>\S+) : (?P<in>\S+) \(으\)로 교체$")
_PLAY_RE = re.compile(r"^(?P<batter>\S+?) : (?P<desc>.+)$")
_SB_RE = re.compile(r"^[123]루주자 (?P<name>\S+) : 도루로 (?:[123]루까지 진루|홈인)$")
_CS_RE = re.compile(r"^[123]루주자 (?P<name>\S+) : 도루실패\s?아웃")
_PICKOFF_RE = re.compile(r"^[123]루주자 (?P<name>\S+) : 견제사\s?아웃")
_HOME_RE = re.compile(r"^[123]루주자 \S+ : 홈인$")
_PLAIN_ADVANCE_RE = re.compile(r"^[123]루주자 \S+ : (?:[123]루까지 진루|홈인)$")
_ADVANCE_MARKERS = ("폭투", "도루", "실책", "보크")
_ERROR_RE = re.compile(r"(?P<pos>\S+수) 실책")


def fetch_full_relay(game_id: str, max_innings: int = 13) -> list[dict]:
    """<br/>로 이어붙은 문자열을 KBO relay.py와 같은 모양의 평평한 이벤트 목록으로 편다."""
    events = []
    for inn in range(1, max_innings + 1):
        try:
            data = fetch_json(RELAY_URL.format(game_id=game_id, inning=inn))
        except Exception:  # noqa: BLE001
            break
        groups = (data.get("result") or {}).get("textRelayData", {}).get("textRelays") or []
        if not groups:
            break
        for g in groups:
            lines = (g.get("text") or "").split("<br/>")
            for sub_idx, line in enumerate(lines):
                line = line.strip()
                if not line:
                    continue
                events.append({
                    "no": g.get("no"), "sub": sub_idx, "inn": g.get("inn"),
                    "half": g.get("homeOrAway"),  # '0'=원정 공격(홈 수비), '1'=홈 공격(원정 수비)
                    "text": line,
                })
    events.sort(key=lambda e: (e["no"], e["sub"]))
    return events


def build_starting_position_map(batter_box_side: list[dict]) -> dict[str, str]:
    """MLB 타자 박스의 posName으로 '선발 포지션 -> 이름' 정적 지도를 만든다.
    경기 중 수비 교체는 못 따라가는 근사치다."""
    m: dict[str, str] = {}
    for p in batter_box_side or []:
        pos = p.get("posName", "")
        if pos and pos not in ("대타", "대주자", "지명타자"):
            m[pos] = p.get("name", "")
    return m


def _is_productive_out_desc(desc: str) -> bool:
    return ("땅볼" in desc or "희생번트" in desc) and "병살" not in desc


def compute_relay_stats(
    events: list[dict],
    home_starting_pitcher: str | None,
    away_starting_pitcher: str | None,
    home_position_map: dict[str, str],
    away_position_map: dict[str, str],
) -> dict:
    """
    반환: {
      'batter_extra': {name: {'2B':n,'3B':n,'GDP':n,'SACFLY':n,'ADVANCE':n,'CS':n,'PICKOFF':n}},
      'pitcher_extra': {name: {'2B_A':n,'3B_A':n,'CS_A':n,'SB_A':n,'PICKOFF_A':n}},
      'error_credit': {name: n},
    }
    """
    group_texts: dict = defaultdict(list)
    for ev in events:
        group_texts[ev["no"]].append(ev["text"])

    batter_extra: dict = defaultdict(lambda: defaultdict(int))
    pitcher_extra: dict = defaultdict(lambda: defaultdict(int))
    error_credit: dict = defaultdict(int)

    current_pitcher = {"0": home_starting_pitcher, "1": away_starting_pitcher}
    position_map = {"0": home_position_map, "1": away_position_map}

    for ev in events:
        half = ev["half"]
        text = ev["text"]

        m_sub = _SUB_RE.match(text)
        if m_sub:
            current_pitcher[half] = m_sub.group("in")
            continue

        m_sb = _SB_RE.match(text)
        if m_sb:
            p = current_pitcher[half]
            if p:
                pitcher_extra[p]["SB_A"] += 1
            continue

        m_cs = _CS_RE.match(text)
        if m_cs:
            batter_extra[m_cs.group("name")]["CS"] += 1
            p = current_pitcher[half]
            if p:
                pitcher_extra[p]["CS_A"] += 1
            continue

        m_pickoff = _PICKOFF_RE.match(text)
        if m_pickoff:
            batter_extra[m_pickoff.group("name")]["PICKOFF"] += 1
            p = current_pitcher[half]
            if p:
                pitcher_extra[p]["PICKOFF_A"] += 1
            continue

        m_err = _ERROR_RE.search(text)
        if m_err and "견제실책" not in text:
            fielder = position_map[half].get(m_err.group("pos"))
            if fielder:
                error_credit[fielder] += 1
            # continue 하지 않는다 — 같은 줄에 타자 결과가 같이 오는 경우는 없지만,
            # 혹시 몰라 아래 타자 판정도 계속 시도한다.

        m_play = _PLAY_RE.match(text)
        if m_play:
            desc = m_play.group("desc")
            batter = m_play.group("batter")

            if "2루타" in desc:
                p = current_pitcher[half]
                if p:
                    pitcher_extra[p]["2B_A"] += 1
            elif "3루타" in desc:
                p = current_pitcher[half]
                if p:
                    pitcher_extra[p]["3B_A"] += 1

            tags = classify_relay_desc(desc)
            if tags["2B"]:
                batter_extra[batter]["2B"] += 1
            if tags["3B"]:
                batter_extra[batter]["3B"] += 1
            if tags["GDP"]:
                batter_extra[batter]["GDP"] += 1
            if tags["SACFLY"]:
                batter_extra[batter]["SACFLY"] += 1
            if tags["HR"]:
                # 같은 타석 그룹 안의 "홈인" 줄 수 = 만루면 본인 포함 3명(볼넷/안타로 채워진 주자 3명)
                runners_scored = sum(1 for t in group_texts[ev["no"]] if _HOME_RE.match(t))
                if runners_scored >= 3:
                    batter_extra[batter]["GRANDSLAM"] += 1

            if _is_productive_out_desc(desc):
                for t in group_texts[ev["no"]]:
                    if _PLAIN_ADVANCE_RE.match(t) and not any(mk in t for mk in _ADVANCE_MARKERS):
                        batter_extra[batter]["ADVANCE"] += 1
                        break

    return {
        "batter_extra": {k: dict(v) for k, v in batter_extra.items()},
        "pitcher_extra": {k: dict(v) for k, v in pitcher_extra.items()},
        "error_credit": dict(error_credit),
    }
