"""KBO 공식 홈페이지(koreabaseball.com)에서 2001~2007년(네이버 스포츠 API에 없는 구간)
경기 일정·박스스코어를 가져와, naver_fantasy_score.py와 같은 형식의 배터/피처 기록으로
바꿔준다. 2008년 이후는 네이버 API(naver_fantasy_score.py)를 그대로 쓰므로 이 모듈은
2001~2007년 전용이다.

데이터 출처 (전부 로그인 없이 되는 것만 확인함 — 2001~2007년 선에서는 로그인이 필요 없었다.
1982~2000년은 KBO 사이트 자체가 로그인해야만 "선수 기록실"의 시즌 통산 기록을 보여주고,
그마저도 경기 단위 데이터는 없어서 이 모듈로는 다룰 수 없다):
  - 일정: POST /ws/Schedule.asmx/GetScheduleList (leId=1, srIdList, seasonId, gameMonth)
  - 박스스코어: POST /ws/Schedule.asmx/GetBoxScoreScroll (leId=1, srId=0, seasonId, gameId)

박스스코어 응답 구조(실제 호출로 확인함, 2005-06-01 현대vs두산 경기 기준):
  - arrHitter: [원정팀, 홈팀] 순서로 2개. 각각 table1(타순/수비위치/이름),
    table2(회별 타석 결과를 한글 기록 부호로— 예: "중안"=중전안타, "삼진", "4구"=볼넷,
    "一땅"=1루수 땅볼아웃, "二유병"=2루수-유격수 병살 — 표시), table3(타수/안타/타점/득점/타율)
  - arrPitcher: [원정팀, 홈팀] 순서로 2개. table 하나에 승패세/이닝/타자/투구수/타수/피안타/
    홈런/4사구/삼진/실점/자책/평균자책점까지 이미 집계된 형태로 다 들어있어 별도 파싱이
    필요 없다 — 다만 "4사구"가 볼넷+사구 합산이라 둘을 따로 못 뗀다. 다행히 두 항목 모두
    PITCHER_POINTS 가중치가 -10으로 같아서(score_pitcher 참고), 전부 BB로 몰아넣어도
    투수 LP 점수 자체는 정확하다(표시상 BB/HBP 구분만 부정확해짐 — naver_fantasy_score.py의
    문서 주석에 있는 기존 "크롤링 불가 항목" 리스트에 이 한계를 추가하는 셈).
  - 타자 쪽은 견제사/보살/포수 도루저지 같은 세부 수비 기록이 아예 없다(naver_fantasy_score.py
    문서 주석의 기존 한계와 동일 선상) — E(실책), ASSIST, DP_FIELD/TP_FIELD, CS_CATCHER 등은
    항상 0으로 둔다.

홈/원정 순서는 KBO 일정 응답의 "play" 텍스트(예: "현대 2 vs 4 두산")와 경기장(스타디움)이
항상 뒤에 적힌 팀 쪽과 일치하는 걸로 확인해서 "첫 팀=원정, 두 번째 팀=홈"으로 정했다.
"""
from __future__ import annotations

import json
import os
import re
import ssl
import urllib.parse
import urllib.request

from naver_fantasy_score import HEADERS, normalize_team_name, score_batter, score_pitcher

SCHEDULE_URL = "https://www.koreabaseball.com/ws/Schedule.asmx/GetScheduleList"
BOXSCORE_URL = "https://www.koreabaseball.com/ws/Schedule.asmx/GetBoxScoreScroll"
REFERER = "https://www.koreabaseball.com/Schedule/Schedule.aspx"

# 2001~2007년 사이에 존재했던 팀만 있으면 된다(NC/KT/키움은 이 구간에 아직 없었음).
TEAM_CODE_TO_NAME = {
    "HD": "현대", "OB": "두산", "LG": "LG", "SS": "삼성", "HT": "KIA",
    "HH": "한화", "LT": "롯데", "SK": "SSG",  # normalize_team_name이 SK->SSG로 더 정규화함
}


def _post_json(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
                 "Referer": REFERER, "X-Requested-With": "XMLHttpRequest"},
    )
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


_GAME_LINK_RE = re.compile(r"gameId=([0-9A-Z]+)")
_PLAY_TEAMS_RE = re.compile(r"<span>([^<]+)</span>.*?<span>([^<]+)</span>\s*$")


def fetch_schedule_month(season: int, month: str) -> list[dict]:
    """그 달의 경기를 [{"date": "YYYY-MM-DD", "game_id": ..., "away": ..., "home": ...}, ...]로.
    srIdList "0,9,6"은 KBO 사이트가 정규시즌+시범경기+포스트시즌을 한 번에 묶어 부를 때 쓰는
    값이다(Schedule.aspx 페이지 JS에서 그대로 가져옴)."""
    result = _post_json(SCHEDULE_URL, {
        "leId": 1, "srIdList": "0,9,6", "seasonId": season, "gameMonth": month, "teamId": "",
    })
    games = []
    current_date = None
    for row in result.get("rows", []):
        cells = row.get("row", [])
        texts = {c.get("Class"): c for c in cells}
        day_cell = texts.get("day")
        if day_cell and day_cell.get("Text"):
            m = re.match(r"(\d{2})\.(\d{2})", day_cell["Text"])
            if m:
                current_date = f"{season}-{m.group(1)}-{m.group(2)}"
        relay = texts.get("relay")
        play = texts.get("play")
        if not relay or not current_date:
            continue
        m = _GAME_LINK_RE.search(relay.get("Text", ""))
        if not m:
            continue
        away = home = None
        if play:
            teams = re.findall(r"<span>([^<]*)</span>", play.get("Text", ""))
            if len(teams) >= 2:
                away, home = teams[0], teams[-1]
        games.append({"date": current_date, "game_id": m.group(1), "away": away, "home": home})
    return games


# --- 타석 결과 한글 기록 부호 해독 ---------------------------------------------------
# 접두(수비 위치: 一二三=1/2/3루수, 유=유격수, 좌/중/우=외야수, 포=포수, 투=투수)는 무시하고
# 접미(결과)만 본다. table3가 타수/안타/타점/득점은 이미 정확히 주므로, 여기서는 안타의
# 루타 종류(2루타/3루타/홈런, 나머지는 단타)와 삼진/볼넷/사구/희생타만 뽑아내면 된다.
def _classify_code(code: str) -> str | None:
    code = code.replace("&nbsp;", "").strip()
    if not code:
        return None
    if code == "삼진":
        return "SO"
    if code == "4구":
        return "BB"
    if code == "사구":
        return "HBP"
    if "희번" in code or code == "희" or "희생번트" in code:
        return "SACBUNT"
    if "희비" in code:
        return "SACFLY"
    if "홈" in code:
        return "HR"
    if code.endswith("안"):
        # "안" 앞에 아라비아 숫자 2/3가 붙으면 2루타/3루타, 아니면 단타.
        if code[:-1].endswith("2"):
            return "2B"
        if code[:-1].endswith("3"):
            return "3B"
        return "1B"
    if "병" in code:
        return "GDP"
    if code.endswith("땅"):
        return "GO"
    if code.endswith("비") or code.endswith("파") or code.endswith("직"):
        return "FO"
    return None  # 야선/실책출루 등 드문 코드 — 굳이 못 맞춰도 LP에 영향 없어 그냥 무시


def _rows_of(table_json: str) -> list[list[str]]:
    parsed = json.loads(table_json)
    return [[c.get("Text", "") for c in r["row"]] for r in parsed.get("rows", [])]


def _parse_hitters(side: dict) -> list[dict]:
    names_rows = _rows_of(side["table1"])
    events_rows = _rows_of(side["table2"])
    totals_rows = _rows_of(side["table3"])
    out = []
    for name_row, events, totals in zip(names_rows, events_rows, totals_rows):
        if len(name_row) < 3 or not name_row[2].strip():
            continue
        name = name_row[2].strip()
        position = name_row[1].strip()
        ab, hit, rbi, run, _avg = (totals + ["0"] * 5)[:5]
        counts = {"SO": 0, "BB": 0, "HBP": 0, "SACBUNT": 0, "SACFLY": 0,
                  "2B": 0, "3B": 0, "HR": 0, "GDP": 0, "GO": 0, "FO": 0}
        for code in events:
            kind = _classify_code(code)
            if kind and kind in counts:
                counts[kind] += 1
        hit_n = int(hit or 0)
        extra_base = counts["2B"] + counts["3B"] + counts["HR"]
        stat = {
            "R": int(run or 0), "H": hit_n, "BB": counts["BB"],
            "2B": counts["2B"], "3B": counts["3B"], "HR": counts["HR"],
            "RBI": int(rbi or 0), "FO": counts["FO"], "GO": counts["GO"],
            "GDP": counts["GDP"], "SACFLY": counts["SACFLY"], "SACBUNT": counts["SACBUNT"],
            "SB": 0, "CS": 0, "HBP": counts["HBP"], "K": counts["SO"], "PICKOFF": 0, "E": 0,
            "ASSIST": 0, "DP_FIELD": 0, "TP_FIELD": 0, "OF_ASSIST": 0,
            "CS_CATCHER": 0, "SB_ALLOWED_CATCHER": 0,
        }
        # (단타 개수는 stat에 별도 필드가 없다 — score_batter는 2B/3B/HR/H만 보고
        # 단타분은 H안에 암묵적으로 포함돼 있다고 가정하는 구조라 그대로 둔다.)
        out.append({
            "name": name, "player_code": None, "position": position,
            "ab": int(ab or 0), "stat": stat, "lp": score_batter(stat),
            "extra_base_hits_detected": extra_base,
        })
    return out


_PITCHER_COLS = ["name", "appear", "result", "W", "L", "SAVE", "IP", "BF", "PITCHES",
                  "AB", "H", "HR", "BB_HBP", "K", "R", "ER", "ERA"]


def _parse_pitchers(side: dict) -> list[dict]:
    rows = _rows_of(side["table"])
    out = []
    for row in rows:
        if not row or not row[0].strip():
            continue
        vals = dict(zip(_PITCHER_COLS, row))
        name = vals["name"].strip()
        if not name:
            continue

        def _i(key):
            try:
                return int(vals.get(key, "0").replace("&nbsp;", "") or 0)
            except ValueError:
                return 0

        # "이닝" 표시가 "5" 같은 정수만 오는 경우와 "5 1/3" 처럼 분수가 섞인 경우가 있어,
        # OUT(아웃카운트) 계산 시 소수부는 무시하고 정수 이닝*3만 쓴다(약간의 오차는 감수).
        ip_text = vals.get("IP", "0").replace("&nbsp;", "").strip()
        ip_whole = int(re.match(r"\d+", ip_text).group()) if re.match(r"\d+", ip_text) else 0
        stat = {
            "OUT": ip_whole * 3, "H": _i("H"), "2B_A": 0, "3B_A": 0, "HR": _i("HR"),
            "ER": _i("ER"), "BB": _i("BB_HBP"), "HBP": 0, "WP": 0, "K": _i("K"), "BK": 0,
            "INHERITED_SCORED": 0, "INHERITED_STRANDED": 0, "CS_A": 0, "SB_ALLOWED": 0,
            "PICKOFF_A": 0, "QS": False, "QSPLUS": False, "HOLD": 0, "SAVE": 0, "BLOWN": 0,
            "PERFECT": False, "NOHIT": False, "SHO": False, "CG": False,
        }
        if ip_whole >= 6 and stat["ER"] <= 3:
            stat["QS"] = True
        out.append({
            "name": name, "player_code": None,
            "role": "선발" if vals.get("appear", "").strip() == "선발" else "구원",
            "stat": stat, "lp": score_pitcher(stat),
        })
    return out


SEARCH_PLAYER_URL = "https://www.koreabaseball.com/ws/Controls.asmx/GetSearchPlayer"
_PLAYER_CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kbo_player_code_cache.json")


def _load_player_cache() -> dict:
    try:
        with open(_PLAYER_CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_player_cache(cache: dict) -> None:
    with open(_PLAYER_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)


def resolve_player_code(name: str, team: str, cache: dict) -> str | None:
    """이름+팀으로 koreabaseball.com의 playerId(=우리 player_code)를 찾는다. build_stats.py는
    player_code 없는 행을 통째로 집계에서 뺴버리므로, 이게 없으면 2001~2007년 기록이 전부
    시즌·통산 기록실에서 누락된다. GetSearchPlayer는 이름 하나로 동명이인을 다 주기 때문에
    팀명으로 한 명만 골라야 하는데, 팀명도 옛날 이름(해태/현대 등)일 수 있어
    normalize_team_name으로 양쪽 다 맞춰서 비교한다. 애매하거나 못 찾으면 None — 호출부에서
    unresolved 목록에 남겨 나중에 검토한다. cache는 {name: [{"team":정규화된팀명,"code":...}]}
    형태로 디스크에 저장해 같은 이름을 매 경기마다 다시 조회하지 않게 한다."""
    norm_team = normalize_team_name(team)
    if name in cache:
        for cand in cache[name]:
            if cand["team"] == norm_team:
                return cand["code"]
            if cand["team"] is None:  # 이름이 유일해서 팀 비교가 필요 없었던 경우
                return cand["code"]
        return None

    try:
        result = _post_json(SEARCH_PLAYER_URL, {"name": name})
    except Exception:  # noqa: BLE001
        return None
    candidates = (result.get("now") or []) + (result.get("retire") or [])
    entries = [{"team": normalize_team_name(c.get("T_NM", "")), "code": str(c.get("P_ID"))}
               for c in candidates if c.get("P_ID")]
    if len(entries) == 1:
        entries[0]["team"] = None  # 유일한 선수라 팀 비교 없이 항상 매치
    cache[name] = entries
    for cand in entries:
        if cand["team"] == norm_team or cand["team"] is None:
            return cand["code"]
    return None


def fetch_and_parse_box_score(season: int, game_id: str, away_team: str, home_team: str,
                               player_cache: dict | None = None) -> tuple[list[dict], list[dict]]:
    raw = _post_json(BOXSCORE_URL, {"leId": 1, "srId": 0, "seasonId": season, "gameId": game_id})
    if raw.get("code") != "100" or not raw.get("arrHitter"):
        return [], []

    away_team = normalize_team_name(away_team or "")
    home_team = normalize_team_name(home_team or "")
    if player_cache is None:
        player_cache = {}
    batters: list[dict] = []
    pitchers: list[dict] = []
    for side_idx, (team, opp) in enumerate([(away_team, home_team), (home_team, away_team)]):
        for b in _parse_hitters(raw["arrHitter"][side_idx]):
            b["team"], b["opponent"] = team, opp
            b["player_code"] = resolve_player_code(b["name"], team, player_cache)
            del b["extra_base_hits_detected"]
            batters.append(b)
        for p in _parse_pitchers(raw["arrPitcher"][side_idx]):
            p["team"], p["opponent"] = team, opp
            p["player_code"] = resolve_player_code(p["name"], team, player_cache)
            pitchers.append(p)
    return batters, pitchers
