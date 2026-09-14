"""KBO 공식 홈페이지(koreabaseball.com)의 "구단별 등록 현황" 페이지에서 등번호를 긁어와
jersey_numbers.json(player_code -> {number, name, team})을 만든다.

이 페이지의 선수 링크(playerId=...)가 우리가 naver_fantasy_score.py에서 쓰는
player_code와 완전히 같은 값이다(실제 확인: 삼성 투수 김태훈 playerId=62360, 우리
쪽 player_code도 62360과 정확히 일치) — 그래서 별도 이름 매칭 없이 바로 연결된다.

records.html·lp_board.html·player.html이 이 파일을 fetch해서, 같은 팀 안에 이름이
같은 선수가 둘 이상이면(동명이인) 이름 옆에 등번호를 작게 붙여 구분한다.

pregame.py의 fetch_active_roster()와 같은 페이지·같은 POST 방식을 쓰지만, 그쪽은
"이 선수가 투수인지 아닌지"만 필요해서 등번호를 버리고 이름만 남긴다 — 여기서는
반대로 등번호(+playerId)가 핵심이라 별도 함수로 뺐다.

사용법: python build_jersey_numbers.py
"""
from __future__ import annotations

import http.cookiejar
import json
import os
import re
import ssl
import time
import urllib.parse
import urllib.request
from datetime import date

from naver_fantasy_score import HEADERS
from pregame import ENTRY_CATEGORIES, REGISTER_URL, _POSTBACK_PREFIX, _extract_hidden_fields

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_PATH = os.path.join(HERE, "jersey_numbers.json")
LAST_REFRESH_PATH = os.path.join(HERE, "jersey_last_refresh.txt")
# 등번호는 트레이드·방출 때만 바뀌는 값이라 자주 다시 긁을 필요가 없다 — 10개 구단(각
# GET+POST 2번씩)을 매 활성 구간 주기마다 다시 부르면 낭비라 하루 한 번으로 제한한다
# (position_last_refresh.txt와 같은 패턴).
REFRESH_INTERVAL_SECONDS = 24 * 60 * 60


def _refresh_due() -> bool:
    try:
        with open(LAST_REFRESH_PATH, encoding="utf-8") as f:
            last = float(f.read().strip())
    except (FileNotFoundError, ValueError):
        return True
    return (time.time() - last) >= REFRESH_INTERVAL_SECONDS

# koreabaseball.com 팀 코드 -> 우리 데이터의 팀 표기(naver_fantasy_score가 쓰는 것과 동일).
TEAM_CODE_TO_NAME = {
    "SS": "삼성", "HT": "KIA", "LG": "LG", "KT": "KT", "OB": "두산",
    "SK": "SSG", "HH": "한화", "LT": "롯데", "NC": "NC", "WO": "키움",
}

_ROW_RE = re.compile(
    r'<tr>\s*<td>(\d+)</td>\s*<td><a href="[^"]*playerId=(\d+)"[^>]*>([^<]+)</a>', re.S,
)


def fetch_team_numbers(team_code: str, date_str: str) -> list[dict]:
    """team_code(SS/KT/LG/HT/OB/HH/NC/LT/SK/WO)의 그날 기준 1군 등록 선수 전원을
    [{"number": "18", "player_code": "69446", "name": "원태인"}, ...]로 돌려준다.
    감독/코치 표는 건너뛴다(pregame.py와 동일한 ENTRY_CATEGORIES 기준)."""
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

    players = []
    for table in re.findall(r'<table class="tNData".*?</table>', section, re.S):
        m_head = re.search(r"<th[^>]*>(.*?)</th>\s*<th[^>]*>(.*?)</th>", table, re.S)
        role = m_head.group(2).strip() if m_head else ""
        if role not in ENTRY_CATEGORIES:
            continue  # 감독/코치 표는 건너뜀
        for number, code, name in _ROW_RE.findall(table):
            players.append({"number": number, "player_code": code, "name": name})
    return players


def main(force: bool = False):
    if not force and not _refresh_due():
        print("최근에 갱신함, 건너뜀(하루 한 번만 갱신 — --force로 강제 가능)")
        return

    today = date.today().isoformat()
    result: dict[str, dict] = {}
    for team_code, team_name in TEAM_CODE_TO_NAME.items():
        try:
            players = fetch_team_numbers(team_code, today)
        except Exception as exc:  # noqa: BLE001
            print(f"  {team_name}({team_code}) 조회 실패: {exc}")
            continue
        for p in players:
            result[p["player_code"]] = {"number": p["number"], "name": p["name"], "team": team_name}
        print(f"{team_name}({team_code}) {len(players)}명")

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    with open(LAST_REFRESH_PATH, "w", encoding="utf-8") as f:
        f.write(str(time.time()))
    print(f"완료: {len(result)}명 -> {OUT_PATH}")


if __name__ == "__main__":
    import sys
    main(force="--force" in sys.argv)
