"""
KBO 판타지 모드 라이브 포인트(LP) 계산기
=========================================
네이버 스포츠 내부 API(api-gw.sports.naver.com)에서 경기 박스스코어(및 특이기록)를
직접 호출해 받아온 뒤, "[판타지 모드] 타자/투수 선수 카드 라이브 포인트" 규정에 따라
선수별 포인트(LP)를 계산하고 HTML 표로 출력한다.

Selenium 없이 requests/urllib만으로 동작한다 (네이버 스포츠는 화면에 쓰이는 데이터를
공개 JSON API로 그대로 내려주기 때문에 브라우저 자동화가 필요 없다).

사용법
------
    python naver_fantasy_score.py --date 2026-05-05
    python naver_fantasy_score.py --date 2026-05-05 --out result.html
    python naver_fantasy_score.py --game-id 20260505NCSK02026

데이터 한계 (박스스코어 API에 값 자체가 없어 계산에서 제외한 항목)
------------------------------------------------------------
  타자: 견제사, 보살, 더블/트리플 플레이 가담, 외야수 보살, 도루 저지(포수), 도루 허용(포수)
  투수: 피2루타, 피3루타(투수별 귀속 불가), 승계주자 실점 허용/막음,
        도루 저지(투수), 도루 허용(투수), 견제사
이 항목들은 네이버가 "누가/몇 회에" 했는지를 별도로 내려주는 필드가 없어(수비 보조기록,
주자 승계 정보, 도루 시도 시점의 포수/투수 매핑 등) 신뢰성 있게 크롤링할 수 없다.
나머지 항목(안타/홈런/타점/볼넷/삼진/도루/도루실패/병살/실책/폭투/보크/홀드/세이브/
블론세이브/QS/QS+/완투/완봉/노히트/퍼펙트/사이클히트/만루홈런 등)은 실제 API 응답을
근거로 파싱 로직을 검증했다.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import ssl
import urllib.request
from collections import defaultdict

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://m.sports.naver.com/",
    "Accept": "application/json",
}

SCHEDULE_URL = (
    "https://api-gw.sports.naver.com/schedule/games"
    "?fields=basic&upperCategoryId=kbaseball&categoryId=kbo"
    "&fromDate={date}&toDate={date}"
)
GAME_URL = "https://api-gw.sports.naver.com/schedule/games/{game_id}"
RECORD_URL = "https://api-gw.sports.naver.com/schedule/games/{game_id}/record"


def fetch_json(url: str) -> dict:
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
        return json.loads(resp.read())


def fetch_schedule(date_str: str) -> list[dict]:
    return fetch_json(SCHEDULE_URL.format(date=date_str))["result"]["games"]


def fetch_record(game_id: str) -> dict:
    return fetch_json(RECORD_URL.format(game_id=game_id))["result"]["recordData"]


def fetch_game_status(game_id: str) -> str:
    """'BEFORE' | 'LIVE' | 'RESULT' | ... (recordData의 gameInfo.statusCode는 숫자코드라
    신뢰할 수 없어, 별도로 이 정제된 문자열 상태를 쓴다)."""
    return fetch_json(GAME_URL.format(game_id=game_id))["result"]["game"]["statusCode"]


# ───────────────────────── 이닝 문자열 → 아웃카운트 ─────────────────────────
_FRACTIONS = {"⅓": 1, "⅔": 2}


def innings_to_outs(s) -> int:
    s = str(s or "").strip()
    if not s:
        return 0
    m = re.match(r"^(\d+)?\s*([⅓⅔])?$", s)
    if m:
        whole = int(m.group(1)) if m.group(1) else 0
        frac = _FRACTIONS.get(m.group(2), 0)
        return whole * 3 + frac
    try:
        return int(round(float(s) * 3))
    except ValueError:
        return 0


# ───────────────────────── 타자 타석 결과 코드 분류 ─────────────────────────
# 네이버 박스스코어의 inn1..inn25 필드는 "몇 회"가 아니라 그 타자의 N번째 타석 결과다.
# 예: '우안'=우익수 앞 안타(1루타), '좌중2'=좌중간 2루타, '우3'/'3안'=3루타,
#     '좌중홈'=홈런(hr 필드로 재확인), '유병'=병살타, '중희비'=희생플라이,
#     '4구'=볼넷(bb 필드), '사구'=몸에 맞는 공, '삼진'=삼진(kk 필드), '*실'=상대 실책 출루.
def _hit_bases(code: str) -> int:
    body = code[:-1] if code.endswith("안") else code
    last = body[-1] if body else ""
    if last == "2":
        return 2
    if last == "3":
        return 3
    return 1


def classify_pa(code: str) -> str:
    if code == "삼진":
        return "K"
    if code == "4구":
        return "BB"
    if code == "사구":
        return "HBP"
    if "병" in code:
        return "GDP"
    if code.endswith("땅"):
        return "SACBUNT" if "희" in code else "GO"
    if code.endswith(("비", "파", "직")):
        return "SACFLY" if "희" in code else "FO"
    if "실" in code:
        return "REACH_ERROR"
    if code.endswith("홈"):
        return "HR"
    return {1: "1B", 2: "2B", 3: "3B"}[_hit_bases(code)]


def parse_batter_pa(row: dict) -> dict:
    tags = defaultdict(int)
    for i in range(1, 26):
        code = row.get(f"inn{i}")
        if code:
            tags[classify_pa(code)] += 1
    return tags


# ───────────────────────── etcRecords(특이기록) 파서 ─────────────────────────
_NAME_INN_RE = re.compile(r"([^\s()]+)\((\d+)회\)")
_HR_RE = re.compile(r"^(.+?)(\d+)호\((\d+)회(\d+)점\s*(.*?)\)$")


def parse_etc_records(etc_records: list[dict]) -> dict:
    errors, wild_pitches = defaultdict(int), defaultdict(int)
    caught_stealing, balks = defaultdict(int), defaultdict(int)
    picked_off = defaultdict(int)
    grand_slam_batters: set[str] = set()

    for e in etc_records or []:
        how = e.get("how", "")
        result = (e.get("result") or "").strip()
        if how == "실책":
            for name, _ in _NAME_INN_RE.findall(result):
                errors[name] += 1
        elif how == "폭투":
            for name, _ in _NAME_INN_RE.findall(result):
                wild_pitches[name] += 1
        elif how == "도루자":
            for name, _ in _NAME_INN_RE.findall(result):
                caught_stealing[name] += 1
        elif how == "보크":
            for name, _ in _NAME_INN_RE.findall(result):
                balks[name] += 1
        elif how == "견제사":
            for name, _ in _NAME_INN_RE.findall(result):
                picked_off[name] += 1
        elif how == "홈런":
            m = _HR_RE.match(result)
            if m and m.group(4) == "4":
                grand_slam_batters.add(m.group(1).strip())

    return {
        "errors": errors,
        "wild_pitches": wild_pitches,
        "caught_stealing": caught_stealing,
        "balks": balks,
        "picked_off": picked_off,
        "grand_slam_batters": grand_slam_batters,
    }


# ───────────────────────── 포인트 규정 ─────────────────────────
BATTER_POINTS = {
    "R": 15, "H": 10, "BB": 10, "2B": 15, "3B": 30, "HR": 80, "RBI": 25,
    "FO": -10, "GO": -10, "GDP": -25, "SACFLY": 10, "SACBUNT": 10, "SB": 30, "CS": -15,
    "HBP": 5, "K": -15, "PICKOFF": -10, "CYCLE": 50, "GRANDSLAM": 10, "E": -10,
    "ASSIST": 1, "DP_FIELD": 10, "TP_FIELD": 50, "OF_ASSIST": 30,
    "CS_CATCHER": 40, "SB_ALLOWED_CATCHER": -10,
}
PITCHER_POINTS = {
    "H": -10, "2B_A": -10, "3B_A": -15, "HR": -40, "ER": -10, "BB": -10, "HBP": -10, "WP": -20,
    "OUT": 10, "K": 15, "BK": -50, "QS": 20, "QSPLUS": 30,
    "INHERITED_SCORED": -5, "INHERITED_STRANDED": 5,
    "CS_A": 10, "SB_ALLOWED": -10, "PICKOFF_A": 10,
    "HOLD": 20, "SAVE": 30, "BLOWN": -10, "PERFECT": 100, "NOHIT": 70,
    "SHO": 30, "CG": 15,
}


def score_batter(stat: dict) -> int:
    pts = 0
    for key, weight in BATTER_POINTS.items():
        if key in ("CYCLE", "GRANDSLAM"):
            continue
        pts += stat.get(key, 0) * weight
    if stat.get("CYCLE"):
        pts += BATTER_POINTS["CYCLE"]
    pts += stat.get("GRANDSLAM", 0) * BATTER_POINTS["GRANDSLAM"]
    return pts


def score_pitcher(stat: dict) -> int:
    pts = 0
    for key in ("H", "2B_A", "3B_A", "HR", "ER", "BB", "HBP", "WP", "K", "BK",
                "INHERITED_SCORED", "INHERITED_STRANDED", "CS_A", "SB_ALLOWED", "PICKOFF_A"):
        pts += stat.get(key, 0) * PITCHER_POINTS[key]
    pts += stat.get("OUT", 0) * PITCHER_POINTS["OUT"]
    if stat.get("QSPLUS"):
        pts += PITCHER_POINTS["QSPLUS"]
    elif stat.get("QS"):
        pts += PITCHER_POINTS["QS"]
    pts += stat.get("HOLD", 0) * PITCHER_POINTS["HOLD"]
    pts += stat.get("SAVE", 0) * PITCHER_POINTS["SAVE"]
    pts += stat.get("BLOWN", 0) * PITCHER_POINTS["BLOWN"]
    if stat.get("PERFECT"):
        pts += PITCHER_POINTS["PERFECT"]
    elif stat.get("NOHIT"):
        pts += PITCHER_POINTS["NOHIT"]
    if stat.get("SHO"):
        pts += PITCHER_POINTS["SHO"]
    elif stat.get("CG"):
        pts += PITCHER_POINTS["CG"]
    return pts


def load_position_map() -> dict:
    """playerCode -> {"position": 적용 포지션, "is_override": 수동 재지정 여부}.
    position.py는 이 모듈의 fetch 함수를 가져다 쓰므로, 순환 임포트를 피하려고
    여기서만 지연 임포트한다."""
    try:
        from position import load_db
    except ImportError:
        return {}
    db = load_db()
    return {
        code: {
            "position": rec["effective_position"],
            "is_override": bool(rec.get("manual_position")),
        }
        for code, rec in db.get("players", {}).items()
    }


# ───────────────────────── 경기 1건 처리 ─────────────────────────
def process_game(
    game_id: str, position_map: dict | None = None, game_status: str | None = None,
) -> tuple[list[dict], list[dict]]:
    rd = fetch_record(game_id)
    if not rd or not rd.get("gameInfo"):
        return [], []  # 경기 시작 전이라 아직 박스스코어가 없음

    if game_status is None:
        try:
            game_status = fetch_game_status(game_id)
        except Exception:  # noqa: BLE001
            game_status = None
    is_final = game_status == "RESULT"

    info = rd.get("gameInfo", {})
    date_disp = f"{str(info.get('gdate'))[4:6]}월 {str(info.get('gdate'))[6:8]}일"
    stadium = info.get("stadium", "")
    team_name = {"home": info.get("hName", ""), "away": info.get("aName", "")}
    opp_name = {"home": info.get("aName", ""), "away": info.get("hName", "")}

    etc = parse_etc_records(rd.get("etcRecords", []))

    batter_rows: list[dict] = []
    bb_box = rd.get("battersBoxscore", {})
    for side in ("home", "away"):
        for p in bb_box.get(side, []):
            tags = parse_batter_pa(p)
            hr = int(p.get("hr") or 0)
            cycle = bool(tags["1B"] and tags["2B"] and tags["3B"] and hr)
            name = p.get("name", "")
            stat = {
                "R": int(p.get("run") or 0),
                "H": int(p.get("hit") or 0),
                "BB": int(p.get("bb") or 0),
                "2B": tags["2B"],
                "3B": tags["3B"],
                "HR": hr,
                "RBI": int(p.get("rbi") or 0),
                "FO": tags["FO"] + tags["SACFLY"],
                "GO": tags["GO"] + tags["SACBUNT"],
                "GDP": tags["GDP"],
                "SACFLY": tags["SACFLY"],
                "SACBUNT": tags["SACBUNT"],
                "SB": int(p.get("sb") or 0),
                "CS": etc["caught_stealing"].get(name, 0),
                "HBP": tags["HBP"],
                "K": int(p.get("kk") or 0),
                "PICKOFF": etc["picked_off"].get(name, 0),
                "CYCLE": cycle,
                "GRANDSLAM": 1 if name in etc["grand_slam_batters"] else 0,
                "E": etc["errors"].get(name, 0),
                "ASSIST": 0, "OF_ASSIST": 0, "DP_FIELD": 0, "TP_FIELD": 0,
                "CS_CATCHER": 0, "SB_ALLOWED_CATCHER": 0,
            }
            pos_info = (position_map or {}).get(p.get("playerCode"), {})
            batter_rows.append({
                "name": name, "team": team_name[side], "opponent": opp_name[side],
                "date": date_disp, "stadium": stadium, "pos": p.get("pos", ""),
                "position": pos_info.get("position", ""),
                "position_override": pos_info.get("is_override", False),
                "ab": int(p.get("ab") or 0), "stat": stat,
                "lp": score_batter(stat),
            })

    pitcher_rows: list[dict] = []
    pb_box = rd.get("pitchersBoxscore", {})
    team_pb = rd.get("teamPitchingBoxscore", {})
    for side in ("home", "away"):
        plist = pb_box.get(side, [])
        team_outs = innings_to_outs((team_pb.get(side) or {}).get("inn"))
        for idx, p in enumerate(plist):
            name = p.get("name", "")
            outs = innings_to_outs(p.get("inn"))
            bb = int(p.get("bb") or 0)
            bbhp = int(p.get("bbhp") or 0)
            hbp = max(bbhp - bb, 0)
            er = int(p.get("er") or 0)
            hit = int(p.get("hit") or 0)
            r = int(p.get("r") or 0)
            is_starter = idx == 0

            # 완투/완봉/노히트/퍼펙트는 "경기가 끝났다"는 사실 자체가 성립 조건이라
            # 진행 중인 경기에서는 선발이 아직 안 내려갔을 뿐인데도 outs==team_outs가
            # 우연히 성립해버려 오탐이 난다. 경기 종료(RESULT) 확정 전에는 절대 지급하지 않는다.
            cg = bool(is_final and is_starter and outs > 0 and outs == team_outs)
            sho = cg and r == 0
            nohit = cg and hit == 0
            perfect = nohit and bbhp == 0
            qsplus = bool(is_starter and outs >= 21 and er <= 3)
            qs = bool(is_starter and outs >= 18 and er <= 3 and not qsplus)
            wls = p.get("wls", "")

            stat = {
                "H": hit, "HR": int(p.get("hr") or 0), "ER": er, "BB": bb,
                "HBP": hbp, "K": int(p.get("kk") or 0), "OUT": outs,
                "WP": etc["wild_pitches"].get(name, 0),
                "BK": etc["balks"].get(name, 0),
                "QS": qs, "QSPLUS": qsplus,
                "HOLD": 1 if wls == "홀" else 0,
                "SAVE": 1 if wls == "세" else 0,
                "BLOWN": 1 if wls == "블" else 0,
                "PERFECT": perfect, "NOHIT": nohit, "SHO": sho, "CG": cg,
                "2B_A": 0, "3B_A": 0, "INHERITED_SCORED": 0, "INHERITED_STRANDED": 0,
                "CS_A": 0, "SB_ALLOWED": 0, "PICKOFF_A": 0,
            }
            pitcher_rows.append({
                "name": name, "team": team_name[side], "opponent": opp_name[side],
                "date": date_disp, "stadium": stadium, "inn": p.get("inn"),
                "role": "선발" if is_starter else "구원",
                "stat": stat, "lp": score_pitcher(stat),
            })

    _merge_relay_stats(game_id, rd, batter_rows, pitcher_rows)
    return batter_rows, pitcher_rows


# 등록 포지션과 실제 수비 포지션이 다를 때 그 수비 기록을 인정할지 정하는 3단계 규칙.
# 서버 쪽 기본값이며, 페이지에서는 드롭다운/토글로 유저가 즉석에서 바꿔볼 수 있다(js에 동일 로직 복제).
FIELD_GROUP = {
    "포수": "포수", "1루수": "내야", "2루수": "내야", "3루수": "내야", "유격수": "내야",
    "좌익수": "외야", "중견수": "외야", "우익수": "외야",
}
DEFAULT_POSITION_MODE = 3  # 1=그 포지션에서만, 2=내야/외야끼리만, 3=제약 없음
DEFAULT_DH_DEFENSE_ON = False  # 지명타자 등록 선수의 수비 기록 인정 여부(카드 각주 기본값=미인정)


def _position_allowed(event_pos: str, registered_pos: str, mode: int, dh_defense_on: bool) -> bool:
    if registered_pos == "지명타자":
        return dh_defense_on
    if not registered_pos:
        return True  # 등록 포지션을 모르면 제한할 근거가 없으니 전부 인정
    if mode == 1:
        return event_pos == registered_pos
    if mode == 2:
        return FIELD_GROUP.get(event_pos) == FIELD_GROUP.get(registered_pos)
    return True  # mode == 3


def _aggregate_field_events(events: list[dict], registered_pos: str, mode: int, dh_defense_on: bool) -> dict:
    counts = {"ASSIST": 0, "OF_ASSIST": 0, "CS_CATCHER": 0, "SB_ALLOWED_CATCHER": 0}
    dp = tp = False
    for ev in events:
        if not _position_allowed(ev["pos"], registered_pos, mode, dh_defense_on):
            continue
        t = ev["type"]
        if t == "DP":
            dp = True
        elif t == "TP":
            tp = True
        else:
            counts[t] = counts.get(t, 0) + 1
    counts["DP_FIELD"] = 1 if dp else 0
    counts["TP_FIELD"] = 1 if tp else 0
    return counts


def _merge_relay_stats(game_id: str, rd: dict, batter_rows: list[dict], pitcher_rows: list[dict]) -> None:
    """텍스트 릴레이(relay.py)에서 뽑은 심화 기록을 이름 기준으로 합쳐 LP를 재계산한다.
    릴레이 조회가 실패해도(비인기 이닝 데이터 누락 등) 기본 박스스코어 기반 점수는 그대로 유지된다."""
    try:
        from relay import (
            build_starting_defense, collect_substituted_in_names,
            compute_relay_stats, fetch_full_relay,
        )

        bb_box = rd.get("battersBoxscore", {})
        pb_box = rd.get("pitchersBoxscore", {})
        if not bb_box.get("home") or not pb_box.get("home"):
            return

        events = fetch_full_relay(game_id)
        subbed = collect_substituted_in_names(events)
        home_def = build_starting_defense(bb_box["home"], subbed)
        away_def = build_starting_defense(bb_box["away"], subbed)
        home_sp = pb_box["home"][0]["name"] if pb_box.get("home") else None
        away_sp = pb_box["away"][0]["name"] if pb_box.get("away") else None

        stats = compute_relay_stats(events, home_def, away_def, home_sp, away_sp)
    except Exception as exc:  # noqa: BLE001
        print(f"  {game_id} 릴레이 기반 심화 기록 조회 실패(기본 점수만 적용): {exc}")
        return

    fielding_events = stats["fielding_events"]
    catcher_events = stats["catcher_events"]
    pitcher_extra = stats["pitcher_extra"]
    batter_extra = stats["batter_extra"]

    for row in batter_rows:
        events_for_player = fielding_events.get(row["name"], []) + catcher_events.get(row["name"], [])
        if events_for_player:
            row["position_events"] = events_for_player
            agg = _aggregate_field_events(
                events_for_player, row.get("position", ""),
                DEFAULT_POSITION_MODE, DEFAULT_DH_DEFENSE_ON,
            )
            row["stat"]["ASSIST"] += agg["ASSIST"]
            row["stat"]["OF_ASSIST"] += agg["OF_ASSIST"]
            row["stat"]["DP_FIELD"] += agg["DP_FIELD"]
            row["stat"]["TP_FIELD"] += agg["TP_FIELD"]
            row["stat"]["CS_CATCHER"] += agg["CS_CATCHER"]
            row["stat"]["SB_ALLOWED_CATCHER"] += agg["SB_ALLOWED_CATCHER"]
        advance = batter_extra.get(row["name"])
        if advance:
            # 릴레이 기반 진루타(구 희생번트) 판정이 박스코드 기반보다 더 넓은 정의라
            # 그 값으로 대체한다(같은 사건을 중복 집계하지 않도록 덮어쓰기)
            row["stat"]["SACBUNT"] = advance
        if events_for_player or advance:
            row["lp"] = score_batter(row["stat"])

    for row in pitcher_rows:
        pe = pitcher_extra.get(row["name"])
        if pe:
            row["stat"]["2B_A"] += pe.get("2B_A", 0)
            row["stat"]["3B_A"] += pe.get("3B_A", 0)
            row["stat"]["INHERITED_SCORED"] += pe.get("INHERITED_SCORED", 0)
            row["stat"]["INHERITED_STRANDED"] += pe.get("INHERITED_STRANDED", 0)
            row["stat"]["CS_A"] += pe.get("CS_A", 0)
            row["stat"]["SB_ALLOWED"] += pe.get("SB_A", 0)
            row["stat"]["PICKOFF_A"] += pe.get("PICKOFF_A", 0)
            row["lp"] = score_pitcher(row["stat"])


def collect_date(date_str: str, position_map: dict | None = None) -> tuple[list[dict], list[dict]]:
    all_batters, all_pitchers = [], []
    for g in fetch_schedule(date_str):
        gid = g["gameId"]
        if g.get("statusCode") == "BEFORE":
            continue  # 아직 시작 전 → 박스스코어 없음
        try:
            b, p = process_game(gid, position_map=position_map, game_status=g.get("statusCode"))
        except Exception as exc:  # noqa: BLE001
            print(f"  {gid} 처리 실패: {exc}")
            continue
        all_batters.extend(b)
        all_pitchers.extend(p)
    return all_batters, all_pitchers


# ───────────────────────── HTML 출력 ─────────────────────────
def _lp_color(lp: int) -> str:
    if lp >= 150:
        return "#d92b2b"
    if lp >= 80:
        return "#e07b13"
    if lp < 0:
        return "#4472c4"
    return "#1d1d1d"


def _esc(v) -> str:
    return html.escape(str(v))


def build_batter_table(rows: list[dict]) -> str:
    rows = sorted(rows, key=lambda r: r["lp"], reverse=True)
    cols = [
        ("순위", None), ("이름", "name"), ("포지션", "position"), ("소속", "team"),
        ("상대", "opponent"), ("구장", "stadium"), ("날짜", "date"), ("LP", "lp"), ("타수", "ab"),
        ("안타", "H"), ("2루타", "2B"), ("3루타", "3B"), ("홈런", "HR"),
        ("타점", "RBI"), ("득점", "R"), ("볼넷", "BB"), ("사구", "HBP"),
        ("삼진", "K"), ("도루", "SB"), ("도루실패", "CS"), ("병살", "GDP"),
        ("희생번트", "SACBUNT"), ("실책", "E"), ("싸이클", "CYCLE"), ("만루홈런", "GRANDSLAM"),
    ]
    head = "".join(f"<th>{h}</th>" for h, _ in cols)
    body_rows = []
    for i, r in enumerate(rows, 1):
        s = r["stat"]
        cells = []
        for h, key in cols:
            if key is None:
                cells.append(f"<td>{i}</td>")
            elif key == "name":
                cells.append(f"<td class='name'>{_esc(r['name'])}</td>")
            elif key in ("team", "opponent", "stadium", "date", "ab"):
                cells.append(f"<td>{_esc(r[key])}</td>")
            elif key == "position":
                mark = "*" if r.get("position_override") else ""
                cells.append(f"<td>{_esc(r.get('position', ''))}{mark}</td>")
            elif key == "lp":
                cells.append(f"<td class='lp' style='color:{_lp_color(r['lp'])}'>{r['lp']}</td>")
            elif key == "CYCLE":
                cells.append(f"<td>{'✅' if s.get('CYCLE') else ''}</td>")
            else:
                cells.append(f"<td>{s.get(key, 0)}</td>")
        body_rows.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


def build_pitcher_table(rows: list[dict]) -> str:
    rows = sorted(rows, key=lambda r: r["lp"], reverse=True)
    cols = [
        ("순위", None), ("이름", "name"), ("구분", "role"), ("소속", "team"),
        ("상대", "opponent"), ("구장", "stadium"), ("날짜", "date"), ("LP", "lp"), ("이닝", "inn"),
        ("피안타", "H"), ("자책", "ER"), ("볼넷", "BB"), ("사구", "HBP"),
        ("탈삼진", "K"), ("폭투", "WP"), ("보크", "BK"), ("홀드", "HOLD"),
        ("세이브", "SAVE"), ("블론", "BLOWN"), ("QS+", "QSPLUS"), ("QS", "QS"),
        ("완투", "CG"), ("완봉", "SHO"), ("노히트", "NOHIT"), ("퍼펙트", "PERFECT"),
    ]
    head = "".join(f"<th>{h}</th>" for h, _ in cols)
    body_rows = []
    for i, r in enumerate(rows, 1):
        s = r["stat"]
        cells = []
        for h, key in cols:
            if key is None:
                cells.append(f"<td>{i}</td>")
            elif key == "name":
                cells.append(f"<td class='name'>{_esc(r['name'])}</td>")
            elif key in ("team", "opponent", "stadium", "date", "role"):
                cells.append(f"<td>{_esc(r[key])}</td>")
            elif key == "inn":
                cells.append(f"<td>{_esc(r['inn'])}</td>")
            elif key == "lp":
                cells.append(f"<td class='lp' style='color:{_lp_color(r['lp'])}'>{r['lp']}</td>")
            elif key in ("QS", "QSPLUS", "CG", "SHO", "NOHIT", "PERFECT"):
                cells.append(f"<td>{'✅' if s.get(key) else ''}</td>")
            else:
                cells.append(f"<td>{s.get(key, 0)}</td>")
        body_rows.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


PAGE_TEMPLATE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>KBO 판타지 라이브 포인트 - {date}</title>
<style>
  body {{ font-family: "Malgun Gothic", "Apple SD Gothic Neo", sans-serif; background:#f4f5f7; margin:0; padding:24px; color:#1d1d1d; }}
  h1 {{ font-size:20px; margin:0 0 4px; }}
  h2 {{ font-size:16px; margin:28px 0 8px; padding-left:8px; border-left:4px solid #1d467d; }}
  .note {{ color:#666; font-size:12px; margin-bottom:16px; }}
  table {{ border-collapse: collapse; width:100%; background:#fff; font-size:12px; box-shadow:0 1px 3px rgba(0,0,0,.08); }}
  th, td {{ border:1px solid #e2e5ea; padding:6px 8px; text-align:center; white-space:nowrap; }}
  thead th {{ background:#1d467d; color:#fff; position:sticky; top:0; }}
  td.name {{ text-align:left; font-weight:600; }}
  td.lp {{ font-weight:700; font-size:13px; }}
  tbody tr:nth-child(even) {{ background:#f7f8fa; }}
  .wrap {{ overflow-x:auto; }}
  footer {{ margin-top:20px; font-size:11px; color:#888; line-height:1.6; }}
</style>
</head>
<body>
  <h1>KBO 판타지 모드 라이브 포인트(LP)</h1>
  <div class="note">데이터 출처: 네이버 스포츠(api-gw.sports.naver.com) · 기준일: {date}</div>

  <h2>타자 LP 순위</h2>
  <div class="wrap">{batter_table}</div>

  <h2>투수 LP 순위</h2>
  <div class="wrap">{pitcher_table}</div>

  <footer>
    * 데이터 한계로 다음 항목은 LP 계산에서 제외됨: (타자) 견제사, 보살, 더블/트리플 플레이 가담,
    외야수 보살, 도루 저지(포수), 도루 허용(포수) / (투수) 피2루타·피3루타(투수 귀속),
    승계주자 실점 허용·막음, 도루 저지(투수), 도루 허용(투수), 견제사.<br>
    * 희생번트는 진루타(희생플라이 제외)로 근사 판정, 사이클히트/만루홈런은 박스스코어·특이기록에서
    자동 판별.
  </footer>
</body>
</html>
"""


def build_html(batter_rows: list[dict], pitcher_rows: list[dict], date_str: str) -> str:
    return PAGE_TEMPLATE.format(
        date=date_str,
        batter_table=build_batter_table(batter_rows),
        pitcher_table=build_pitcher_table(pitcher_rows),
    )


def main():
    ap = argparse.ArgumentParser(description="KBO 판타지 라이브 포인트 계산기")
    ap.add_argument("--date", help="YYYY-MM-DD (해당 날짜 전 경기)")
    ap.add_argument("--game-id", help="특정 경기 gameId 하나만 처리")
    ap.add_argument("--out", help="출력 HTML 파일 경로")
    ap.add_argument("--no-position", action="store_true",
                     help="position_db.json을 무시하고 포지션 열 없이 출력")
    args = ap.parse_args()

    position_map = None if args.no_position else load_position_map()

    if args.game_id:
        date_str = args.game_id[:4] + "-" + args.game_id[4:6] + "-" + args.game_id[6:8]
        batters, pitchers = process_game(args.game_id, position_map=position_map)
    elif args.date:
        date_str = args.date
        print(f"{date_str} 경기 목록 조회 중...")
        batters, pitchers = collect_date(date_str, position_map=position_map)
    else:
        ap.error("--date 또는 --game-id 중 하나는 필요합니다.")
        return

    print(f"타자 {len(batters)}명, 투수 {len(pitchers)}명 처리 완료")
    out_path = args.out or f"fantasy_score_{date_str.replace('-', '')}.html"
    html_doc = build_html(batters, pitchers, date_str)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_doc)
    print(f"저장 완료: {out_path}")


if __name__ == "__main__":
    main()
