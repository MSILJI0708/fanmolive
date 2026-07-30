"""경기 시작 전(BEFORE) 상태에서도 보드에 뭔가 보여주기 위한 모듈.

두 가지를 합쳐서 "선발 라인업이 발표되기 전에는 1군 엔트리 전원을, 발표된 뒤에는 그중
선발 라인업에 든 선수를 초록 마커로" 보여준다.

1. KBO 공식 홈페이지(koreabaseball.com)의 "구단별 등록 현황"(1군 엔트리) 페이지를 그대로
   가져온다. ASP.NET WebForms 페이지라 팀을 바꾸는 게 실제로는 __doPostBack이라, 첫 GET에서
   __VIEWSTATE 등을 읽어와 그대로 얹어 POST하는 방식으로 흉내낸다(Selenium 불필요).
2. 네이버 스포츠의 "/preview" 엔드포인트가 경기 시작 전에도 선발 라인업이 발표되면
   fullLineUp(타순 포함) / 선발투수 이름을 그대로 내려준다 — 인스타그램 등을 따로 볼 필요 없이
   이걸로 "선발 여부"를 판정한다(아직 발표 전이면 fullLineUp에 선발투수 한 명만 들어있다).

koreabaseball.com 팀 코드(SS/KT/LG/HT/OB/HH/NC/LT/SK/WO)는 네이버가 스케줄에서 주는
homeTeamCode/awayTeamCode와 그대로 같아서 별도 매핑표가 필요 없다.
"""

from __future__ import annotations

import http.cookiejar
import re
import ssl
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from naver_fantasy_score import HEADERS, fetch_json

KST = timezone(timedelta(hours=9))

REGISTER_URL = "https://www.koreabaseball.com/Player/Register.aspx"
PREVIEW_URL = "https://api-gw.sports.naver.com/schedule/games/{game_id}/preview"

_POSTBACK_PREFIX = "ctl00$ctl00$ctl00$cphContents$cphContents$cphContents$"

# koreabaseball.com 등록명단의 포지션 그룹 헤더 -> 우리 쪽 표기(포수/내야수/외야수는 그대로 두고,
# 세부 포지션은 나중에 position_db.json의 실제 수비 포지션으로 덮어쓴다. 여기선 "이 선수가
# 투수인지 아닌지"만 구분되면 충분하다).
ENTRY_CATEGORIES = ("투수", "포수", "내야수", "외야수")

_roster_cache: dict[tuple[str, str], dict[str, str]] = {}


def _extract_hidden_fields(html: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for tag in re.findall(r"<input\b[^>]*>", html, re.I):
        m_name = re.search(r'name="([^"]+)"', tag)
        if not m_name:
            continue
        m_val = re.search(r'value="([^"]*)"', tag)
        fields[m_name.group(1)] = m_val.group(1) if m_val else ""
    return fields


def fetch_active_roster(team_code: str, date_str: str) -> dict[str, str]:
    """team_code(SS/KT/LG/HT/OB/HH/NC/LT/SK/WO)와 date_str(YYYY-MM-DD)를 받아
    그 날짜 기준 1군 등록 선수 {이름: '투수'|'포수'|'내야수'|'외야수'} 딕셔너리를 돌려준다.
    감독/코치는 제외한다. 같은 (팀, 날짜)는 세션 내에서 캐시한다."""
    cache_key = (team_code, date_str)
    if cache_key in _roster_cache:
        return _roster_cache[cache_key]

    date_compact = date_str.replace("-", "")
    ctx = ssl.create_default_context()
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cj), urllib.request.HTTPSHandler(context=ctx)
    )

    req = urllib.request.Request(REGISTER_URL, headers=HEADERS)
    html = opener.open(req, timeout=15).read().decode("utf-8", errors="replace")
    fields = _extract_hidden_fields(html)
    fields[_POSTBACK_PREFIX + "hfSearchTeam"] = team_code
    fields[_POSTBACK_PREFIX + "hfSearchDate"] = date_compact
    fields["__EVENTTARGET"] = _POSTBACK_PREFIX + "btnCalendarSelect"
    fields["__EVENTARGUMENT"] = ""

    data = urllib.parse.urlencode(fields).encode("utf-8")
    req2 = urllib.request.Request(
        REGISTER_URL, data=data,
        headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded", "Referer": REGISTER_URL},
    )
    html2 = opener.open(req2, timeout=15).read().decode("utf-8", errors="replace")

    start = html2.find("선수등록명단")
    end = html2.find("등/말소 현황", start)
    section = html2[start:end] if start != -1 else ""

    roster: dict[str, str] = {}
    for table in re.findall(r'<table class="tNData".*?</table>', section, re.S):
        m_head = re.search(r"<th[^>]*>(.*?)</th>\s*<th[^>]*>(.*?)</th>", table, re.S)
        role = m_head.group(2).strip() if m_head else ""
        if role not in ENTRY_CATEGORIES:
            continue  # 감독/코치 표는 건너뜀
        for name in re.findall(r'<a href="[^"]*playerId=\d+">([^<]+)</a>', table):
            roster[name] = role

    _roster_cache[cache_key] = roster
    return roster


def fetch_preview(game_id: str) -> dict | None:
    """네이버 /preview에서 이 경기의 선발 라인업 발표 상태를 가져온다.
    반환: {'home': {...}, 'away': {...}, 'stadium': str} 또는 조회 실패 시 None.
    각 side 딕셔너리: {'starting_pitcher': str|None, 'starters': {이름: batorder}}"""
    try:
        rd = fetch_json(PREVIEW_URL.format(game_id=game_id))
    except Exception:  # noqa: BLE001
        return None
    pd = (rd.get("result") or {}).get("previewData")
    if not pd:
        return None

    def _side(lineup: dict) -> dict:
        starting_pitcher = None
        starters: dict[str, int] = {}
        for entry in (lineup or {}).get("fullLineUp") or []:
            name = entry.get("playerName")
            if not name:
                continue
            if entry.get("positionName") == "선발투수":
                starting_pitcher = name
            elif entry.get("batorder"):
                starters[name] = int(entry["batorder"])
        return {"starting_pitcher": starting_pitcher, "starters": starters}

    gi = pd.get("gameInfo") or {}
    return {
        "home": _side(pd.get("homeTeamLineUp")),
        "away": _side(pd.get("awayTeamLineUp")),
        "stadium": gi.get("stadium", ""),
    }


def is_within_pregame_window(game_datetime_str: str, hours_before: float = 2.0) -> bool:
    """gameDateTime("2026-07-30T18:30:00", KST 기준)이 지금부터 hours_before시간 이내로
    다가왔는지(그리고 아직 지나지 않았는지) 여부."""
    try:
        game_dt = datetime.fromisoformat(game_datetime_str).replace(tzinfo=KST)
    except ValueError:
        return False
    now = datetime.now(KST)
    return now >= game_dt - timedelta(hours=hours_before)
