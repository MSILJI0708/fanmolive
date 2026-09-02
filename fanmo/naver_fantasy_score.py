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
from collections import Counter, defaultdict

from fanmo_cost import lookup_batter_cost, lookup_pitcher_cost

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
    "&fromDate={date}&toDate={date}&size=20"
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
# 예: '우안'=우익수 앞 안타(1루타), '2안'/'3안'=("2루타"/"3루타"가 아니라) 2루수·3루수
#     쪽으로 향한 내야안타(1루타) — 포지션 번호와 루타 수가 우연히 같은 숫자를 써서 헷갈리기
#     쉬운데, 여러 건을 중계 텍스트로 교차검증해서 "N안"은 숫자와 무관하게 항상 1루타임을
#     확인했다(김호령 '2안'이 중계에서 "2루수 오른쪽 내야안타"로, 힐리어드 '2안'이
#     "2루수 앞 내야안타"로, 오재원 '3안'이 "3루수 앞 내야안타"로 나옴 — 전부 단타).
#     실제 2루타/3루타는 '좌중2'=좌중간 2루타처럼 위치 문구 뒤에 숫자가 오되 '안'이 안 붙는
#     형태로 표기된다. '좌중홈'=홈런(hr 필드로 재확인), '유병'=병살타, '중희비'=희생플라이,
#     '4구'=볼넷(bb 필드), '사구'=몸에 맞는 공, '삼진'=삼진(kk 필드), '*실'=상대 실책 출루.
def _hit_bases(code: str) -> int:
    if code.endswith("안"):
        return 1
    last = code[-1] if code else ""
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
    if code.endswith("번"):
        # '투희번'/'포희번'/'1희번'처럼 "희"가 붙으면 희생번트(땅볼과 동일하게 처리),
        # '투번'/'1번'/'2번'처럼 "희" 없이 그냥 "번"으로만 끝나면 희생도 안타도 아닌
        # "번트 아웃"(비희생 번트 시도 실패)이라 페널티가 없다 — BATTER_POINTS에 없는
        # 값을 반환해서 GO/SACBUNT 어느 쪽도 건드리지 않게 한다(REACH_ERROR와 동일한 패턴).
        return "SACBUNT" if "희" in code else "BUNT_OUT"
    if code.endswith(("비", "파")):
        return "SACFLY" if "희" in code else "FO"
    if code.endswith("직"):
        # 직선타(라인드라이브)로 잡힌 아웃은 뜬공 아웃(FO) 페널티에 포함되지 않는다 —
        # 9up 판타지 점수와 대조해서 확인됨(뜬공 아웃 개수가 실제로는 1개 적게 잡혀야 했음).
        return "LD"
    if "실" in code:
        return "REACH_ERROR"
    if code.endswith("홈"):
        return "HR"
    return {1: "1B", 2: "2B", 3: "3B"}[_hit_bases(code)]


def parse_batter_pa(row: dict) -> dict:
    tags = defaultdict(int)
    for i in range(1, 26):
        code = row.get(f"inn{i}")
        if not code:
            continue
        # 아주 가끔 한 타석 슬롯에 "4구/4구", "좌파/유땅"처럼 슬래시로 결과 두 개가 묶여서
        # 온다(왜 그런 슬롯이 생기는지는 불명이나, 실제로 그 타자의 ab가 그만큼 더 많은 걸로
        # 봐서 정말 타석을 두 번 가졌는데 어떤 이유로 한 슬롯에 합쳐 기록된 것으로 보인다).
        # 그동안은 이 합쳐진 문자열 전체를 그대로 classify_pa에 넘겨서, 접미사만 보고
        # 뒷부분 결과 하나로만 분류하고 앞부분 결과가 통째로 사라지고 있었다.
        for part in code.split("/"):
            if part:
                tags[classify_pa(part)] += 1
    return tags


# ───────────────────────── etcRecords(특이기록) 파서 ─────────────────────────
_NAME_INN_RE = re.compile(r"([^\s()]+)\((\d+)회\)")
# 한 경기에 홈런이 여럿이면 "김도영33호(1회1점 토다) 권희동4호(2회4점 양현종) ..."처럼
# 모든 선수의 기록이 공백으로 이어붙은 문자열 하나로 온다. 예전엔 이 문자열 전체를 ^...$로
# 통째로 매칭하는 정규식을 썼는데, 그러면 첫 번째 선수만 제대로 잡히고 그 뒤 선수들의
# "(N회N점 상대)" 부분이 첫 번째 매치의 마지막 그룹에 통째로 빨려들어가 버려서, 두 번째
# 이후 선수(권희동 등)의 만루홈런이 조용히 누락됐다. finditer로 각 선수 기록을 따로 뽑아야 한다.
# 한 선수가 그 경기에서 홈런을 2개 이상 쳤으면 "위즈덤25호26호(6회4점 8회1점 원태인 육선엽)"
# 처럼 "N호"가 여러 번 붙고 괄호 안에도 "회N점"이 여러 쌍 들어온다 — 이름 그룹을 숫자가
# 아닌 문자로만 한정해서, 뒤에 붙는 "N호"들이 이름에 섞여 들어가지 않게 한다(이름에 숫자가
# 섞이면 grand_slam_batters에 엉뚱한 문자열이 들어가 정작 그 선수 이름과 안 맞아 조회가
# 실패한다). 괄호 안은 "회N점"이 몇 쌍이든 통째로 캡처해서, 그 안에 "4점"이 있는지만 본다
# (몇 번째 홈런이 만루였는지는 안 가려도 되고, 그 경기에 만루홈런이 있었는지만 알면 된다).
_HR_ITEM_RE = re.compile(r"([^\d\s()]+)((?:\d+호)+)\(([^()]*)\)")


def parse_etc_records(etc_records: list[dict]) -> dict:
    errors, wild_pitches = defaultdict(int), defaultdict(int)
    caught_stealing, balks = defaultdict(int), defaultdict(int)
    picked_off = defaultdict(int)
    error_innings: dict = defaultdict(list)
    grand_slam_batters: set[str] = set()

    for e in etc_records or []:
        how = e.get("how", "")
        result = (e.get("result") or "").strip()
        if how == "실책":
            for name, inn in _NAME_INN_RE.findall(result):
                errors[name] += 1
                error_innings[name].append(int(inn))
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
            for name, _hr_nos, points_blob in _HR_ITEM_RE.findall(result):
                if "4점" in points_blob:
                    grand_slam_batters.add(name)

    return {
        "errors": errors,
        "error_innings": error_innings,
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
        if key in ("CYCLE", "GRANDSLAM", "DP_FIELD", "TP_FIELD"):
            continue
        pts += stat.get(key, 0) * weight
    if stat.get("CYCLE"):
        pts += BATTER_POINTS["CYCLE"]
    pts += stat.get("GRANDSLAM", 0) * BATTER_POINTS["GRANDSLAM"]
    # 더블/트리플 플레이 가담은 원래 규정상 "1경기에 1번만 인정" — 병살 하나에 여러 야수가
    # 가담해도 각 야수 본인 기준으로는 그 경기에서 몇 번을 가담했든 1회분만 받는다(9up 판타지
    # 점수의 이재현 사례로 확인함: 가담 횟수는 2로 표시돼도 포인트는 10점 그대로였음).
    if stat.get("DP_FIELD"):
        pts += BATTER_POINTS["DP_FIELD"]
    if stat.get("TP_FIELD"):
        pts += BATTER_POINTS["TP_FIELD"]
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


def _batter_appeared(p: dict) -> bool:
    """battersBoxscore에 이름은 올라와 있지만 실제로는 전혀 출전하지 않은 선수를 걸러낸다.
    네이버 박스스코어는 보통 실제로 나온 선수만 주고(교체 주자·수비 교체로 들어온 선수도
    substituteIn=True로 표시되며, 타석에 못 서고 그친 경우에도 pos는 채워져 있음), 리스트만
    되고 실제 출전 기록이 전무한 행은 관측된 적이 없지만, 혹시 모를 경우를 대비해 방어적으로
    제외한다(경기 종료 후 실제로 뛰지 않은 선수가 명단에 남지 않도록)."""
    if int(p.get("ab") or 0) or int(p.get("hit") or 0) or int(p.get("bb") or 0):
        return True
    if int(p.get("run") or 0) or int(p.get("rbi") or 0) or int(p.get("hr") or 0) or int(p.get("sb") or 0):
        return True
    if int(p.get("kk") or 0):
        return True
    if p.get("substituteIn"):
        return True
    return bool((p.get("pos") or "").strip())


def _pitcher_appeared(p: dict) -> bool:
    """pitchersBoxscore 쪽의 동일한 방어적 필터 — 실제 등판 기록(아웃카운트나 피안타/사사구/
    자책/탈삼진 중 하나라도)이 전혀 없는 행은 제외한다."""
    if innings_to_outs(p.get("inn")):
        return True
    for key in ("hit", "er", "hr", "bb", "bbhp", "kk"):
        if int(p.get(key) or 0):
            return True
    return bool((p.get("wls") or "").strip())


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
            if not _batter_appeared(p):
                continue
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
                "GO": tags["GO"] + tags["SACBUNT"] + tags["GDP"],
                "LD": tags["LD"],
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
                "ADVANCE_OUT": 0,
            }
            pos_info = (position_map or {}).get(p.get("playerCode"), {})
            row_position = pos_info.get("position", "")
            batter_rows.append({
                "name": name, "player_code": p.get("playerCode") or p.get("pcode"),
                "team": team_name[side], "opponent": opp_name[side],
                "date": date_disp, "stadium": stadium, "pos": p.get("pos", ""),
                "position": row_position,
                "position_override": pos_info.get("is_override", False),
                "ab": int(p.get("ab") or 0), "stat": stat,
                "lp": score_batter(stat),
                "fanmo_cost": lookup_batter_cost(name, team_name[side], row_position, game_id[:8]),
                "_error_innings": list(etc["error_innings"].get(name, [])),
            })

    pitcher_rows: list[dict] = []
    pb_box = rd.get("pitchersBoxscore", {})
    team_pb = rd.get("teamPitchingBoxscore", {})
    for side in ("home", "away"):
        plist = pb_box.get(side, [])
        team_outs = innings_to_outs((team_pb.get(side) or {}).get("inn"))
        for idx, p in enumerate(plist):
            if not _pitcher_appeared(p):
                continue
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
            qsplus = bool(is_starter and outs >= 21 and er <= 2)
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
                "CS_A": 0, "SB_ALLOWED": 0, "PICKOFF_A": 0, "SAVE_OPP": False,
            }
            pitcher_rows.append({
                "name": name, "player_code": p.get("playerCode") or p.get("pcode"),
                "team": team_name[side], "opponent": opp_name[side],
                "date": date_disp, "stadium": stadium, "inn": p.get("inn"),
                "role": "선발" if is_starter else "구원",
                "stat": stat, "lp": score_pitcher(stat),
                "fanmo_cost": lookup_pitcher_cost(name, team_name[side], game_id[:8]),
            })

    # player_code 는 동명이인(이승현 삼성26/57, 김현수 KIA 등)을 사후에 구분하는 유일한 키다.
    # 키 이름이 다르다: battersBoxscore 는 playerCode, pitchersBoxscore 는 pcode.
    # 비면 조용히 넘어가지 않고 한 번 알린다.
    for label, rows in (("타자", batter_rows), ("투수", pitcher_rows)):
        missing = sum(1 for r in rows if not r.get("player_code"))
        if missing:
            print(f"  [주의] {game_id} {label} {missing}/{len(rows)}명 playerCode 없음 "
                  f"— 동명이인 구분 불가")

    _merge_relay_stats(game_id, rd, batter_rows, pitcher_rows)
    return batter_rows, pitcher_rows


# 등록 포지션과 실제 수비 포지션이 다를 때 그 수비 기록을 인정할지 정하는 3단계 규칙.
# 서버 쪽 기본값이며, 페이지에서는 드롭다운/토글로 유저가 즉석에서 바꿔볼 수 있다(js에 동일 로직 복제).
FIELD_GROUP = {
    "포수": "포수", "1루수": "내야", "2루수": "내야", "3루수": "내야", "유격수": "내야",
    "좌익수": "외야", "중견수": "외야", "우익수": "외야",
}
DEFAULT_POSITION_MODE = 3  # 1=그 포지션에서만, 2=내야/외야끼리만, 3=제약 없음
DEFAULT_DH_DEFENSE_ON = True  # 지명타자 등록 선수의 수비 기록 인정 여부(카드 각주 기본값=인정, 토글로 불인정 전환 가능)


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
    timeline = stats["timeline"]
    entry_margin = stats["pitcher_entry_margin"]
    final_score = stats["final_score"]
    earned_run_events = stats.get("earned_run_events", {})
    bunt_out = stats.get("bunt_out", {})
    info = rd.get("gameInfo", {})
    home_team_name = info.get("hName", "")

    # 릴레이 텍스트는 선수를 이름으로만 가리켜서, 같은 팀에 이름이 완전히 같은 선수가
    # 둘 있으면(흔치 않지만 실제로 있음 — 예: 삼성 계투진에 "이승현"이 둘) 어느 쪽이 그
    # 플레이를 했는지 텍스트만으로는 원천적으로 구분할 수 없다. 그런 경우 두 선수 모두
    # 릴레이 기반 심화 기록(보살/병살가담/피2루타/자책점 세부 등) 합산을 건너뛰고 박스스코어
    # 집계값만 쓴다 — 잘못된 값을 억지로 나누는 것보다 "세부 내역 없음"이 낫다.
    ambiguous_batters = {name for name, c in Counter(r["name"] for r in batter_rows).items() if c > 1}
    ambiguous_pitchers = {name for name, c in Counter(r["name"] for r in pitcher_rows).items() if c > 1}

    for row in batter_rows:
        if row["name"] in ambiguous_batters:
            continue
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
            # "진루타"(번트가 아닌 일반 타구로 주자를 진루시킨 아웃)는 더 이상 채점하지 않는다
            # (희생번트 칸은 박스스코어 자체의 공식 기록만 쓴다 — "희"+"땅" 플래그는 KBO
            # 공식 스코어러가 번트 시도와 주자 진루 성공을 이미 전제로 매기는 값이라 그대로 둬도
            # 정확하다). 그래도 나중에 다시 볼 수 있게 참고용으로 ADVANCE_OUT에 남겨둔다
            # (BATTER_POINTS에 없는 키라 LP에는 전혀 영향을 주지 않는다).
            row["stat"]["ADVANCE_OUT"] = advance
        bunts = bunt_out.get(row["name"])
        if bunts:
            # 희생번트도 번트안타도 아닌 "번트 아웃"(비희생 번트 실패)은 페널티가 없다.
            # 박스스코어 코드로는 일반 스윙 땅볼 아웃과 구분이 안 돼 GO에 이미 포함돼있으니
            # 중계에서 확인된 만큼 빼준다.
            row["stat"]["GO"] = max(0, row["stat"]["GO"] - bunts)
        if events_for_player or bunts:
            row["lp"] = score_batter(row["stat"])

    for row in pitcher_rows:
        if row["name"] in ambiguous_pitchers:
            continue
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

        margin = entry_margin.get(row["name"])
        if margin is not None and final_score is not None:
            side = "home" if row["team"] == home_team_name else "away"
            opp_side = "away" if side == "home" else "home"
            team_won = final_score[side] > final_score[opp_side]
            outs = row["stat"]["OUT"]
            # 조건1: 3점 이내 리드로 등판해 1이닝 이상 / 조건3: 이닝 무관 3이닝 이상
            # ("동점주자가 누상/타석/다음타자"인 조건2는 미구현 — 주자 신원까지 필요해 생략)
            row["stat"]["SAVE_OPP"] = bool(
                team_won and ((1 <= margin <= 3 and outs >= 3) or outs >= 9)
            )

    for row in batter_rows + pitcher_rows:
        is_pitcher_row = "OUT" in row["stat"]
        ambiguous = row["name"] in (ambiguous_pitchers if is_pitcher_row else ambiguous_batters)
        _attach_play_log(row, timeline, earned_run_events.get(row["name"], []), ambiguous_name=ambiguous)
        row["categories"] = (
            _pitcher_categories(row) if is_pitcher_row else _batter_categories(row)
        )


def _cat_item(label: str, key: str, stat: dict, points_table: dict, weight_key: str | None = None,
              flag: bool = False) -> dict:
    w = points_table.get(weight_key or key, 0)
    v = stat.get(key, 0)
    pts = (w if v else 0) if flag else v * w
    return {"label": label, "count": v, "points": pts, "flag": flag}


def _batter_categories(row: dict) -> list[dict]:
    """카드게임에서 요청한 5개 그룹(+아웃)으로 타자 스탯을 묶는다. 항목은 항상 전부 계산해서
    넣고, 값이 0/false인 항목을 숨길지는 화면(JS) 쪽에서 정한다.
    "아웃" 그룹은 견제사/도루실패를 "주루" 그룹과 중복으로 보여준다("아웃당한 방식"을 한눈에
    모아보기 위함)라서, 그룹 총합을 전부 더하면 LP보다 그만큼 더 나올 수 있다(그룹별 합계는
    각각 정확하고, 전체 LP는 팝업 상단에 별도로 표시되니 문제는 없다)."""
    s = row["stat"]

    def item(label, key, **kw):
        return _cat_item(label, key, s, BATTER_POINTS, **kw)

    groups = [
        {"name": "출루", "items": [item("안타", "H"), item("볼넷", "BB"), item("사구", "HBP")]},
        {"name": "장타", "items": [
            item("2루타", "2B"), item("3루타", "3B"), item("홈런", "HR"),
            item("만루홈런", "GRANDSLAM"), item("사이클히트", "CYCLE", flag=True),
        ]},
        {"name": "팀배팅", "items": [
            item("타점", "RBI"), item("희생번트", "SACBUNT"), item("희생플라이", "SACFLY"),
        ]},
        {"name": "주루", "items": [
            item("도루", "SB"), item("도루실패", "CS"), item("견제사", "PICKOFF"), item("득점", "R"),
        ]},
        {"name": "수비", "items": [
            item("보살", "ASSIST"), item("외야수 보살", "OF_ASSIST"),
            item("병살 가담", "DP_FIELD"), item("삼중살 가담", "TP_FIELD"),
            item("도루 저지(포수)", "CS_CATCHER"), item("도루 허용(포수)", "SB_ALLOWED_CATCHER"),
            item("실책", "E"),
        ]},
        {"name": "아웃", "items": [
            item("삼진", "K"), item("땅볼 아웃", "GO"), item("뜬공 아웃(파울플라이 포함)", "FO"),
            item("직선타", "LD"), _pickoff_cs_item(s), item("병살타", "GDP"),
        ]},
    ]
    for g in groups:
        g["total"] = sum(i["points"] for i in g["items"])
    return groups


def _pickoff_cs_item(stat: dict) -> dict:
    """견제사+도루실패를 "아웃" 카테고리에서 한 줄로 합쳐 보여준다(각자 주루 카테고리에도
    따로 나오지만, 여기서는 "타자가 아웃당한 방식"을 한눈에 모아 보는 게 목적이라 중복 표시)."""
    count = stat.get("PICKOFF", 0) + stat.get("CS", 0)
    pts = stat.get("PICKOFF", 0) * BATTER_POINTS["PICKOFF"] + stat.get("CS", 0) * BATTER_POINTS["CS"]
    return {"label": "견제사+도루실패", "count": count, "points": pts, "flag": False}


def _pitcher_categories(row: dict) -> list[dict]:
    """선발/구원은 애초에 서로 절대 낼 수 없는 스탯이 있어서(선발은 홀드/세이브 불가, 구원은
    QS/완투 불가) 역할별로 다른 그룹 구성을 쓴다. 상대쪽 전용 스탯은 구조상 항상 0이라 빼도
    총합에서 LP가 안 맞는 문제는 안 생긴다."""
    s = row["stat"]
    role = row.get("role")

    def item(label, key, **kw):
        return _cat_item(label, key, s, PITCHER_POINTS, **kw)

    groups = [
        {"name": "기본", "items": [
            {"label": "아웃카운트", "count": s["OUT"], "points": s["OUT"] * PITCHER_POINTS["OUT"], "flag": False},
            item("자책점", "ER"), item("탈삼진", "K"),
        ]},
        {"name": "출루허용", "items": [item("피안타", "H"), item("볼넷", "BB"), item("사구", "HBP")]},
        {"name": "장타허용", "items": [item("피2루타", "2B_A"), item("피3루타", "3B_A"), item("피홈런", "HR")]},
    ]

    if role == "선발":
        groups.append({"name": "주자억제", "items": [
            item("도루 허용", "SB_ALLOWED"), item("도루 저지", "CS_A"), item("견제사", "PICKOFF_A"),
            item("폭투", "WP"), item("보크", "BK"),
        ]})
        groups.append({"name": "선발 특별", "items": [
            item("퀄리티스타트+", "QSPLUS", flag=True), item("퀄리티스타트", "QS", flag=True),
            item("완투", "CG", flag=True), item("완봉", "SHO", flag=True),
            item("노히트", "NOHIT", flag=True), item("퍼펙트게임", "PERFECT", flag=True),
        ]})
    else:  # 구원
        groups.append({"name": "주자억제", "items": [
            item("도루 허용", "SB_ALLOWED"), item("도루 저지", "CS_A"), item("견제사", "PICKOFF_A"),
            item("폭투", "WP"), item("보크", "BK"),
            {"label": "승계주자 수", "count": s["INHERITED_SCORED"] + s["INHERITED_STRANDED"],
             "points": 0, "flag": False, "info": True},
            item("승계주자 실점 허용", "INHERITED_SCORED"),
            item("승계주자 실점 막음", "INHERITED_STRANDED"),
        ]})
        groups.append({"name": "구원 특별", "items": [
            {"label": "세이브 기회", "count": 1 if s["SAVE_OPP"] else 0, "points": 0, "flag": True, "info": True},
            item("홀드", "HOLD", flag=True), item("세이브", "SAVE", flag=True),
            item("블론 세이브", "BLOWN", flag=True),
        ]})

    for g in groups:
        g["total"] = sum(i["points"] for i in g["items"])
    return groups


def _pitcher_box_summary_lines(stat: dict, log: list[dict], er_events: list[dict]) -> list[dict]:
    """박스스코어 전용 보너스/패널티를, 팝업 타임라인에서 "실제로 그 일이 일어난 이닝"에
    붙여서 보여주기 위한 줄들.

    - 자책점: relay.py가 "누가 출루시킨 주자가 언제 득점했는지"(er_events)를 이닝별로 모아준다.
      진짜 자책/비자책 판정은 박스스코어에만 있어서, 시간순으로 앞의 er_events부터 최대
      stat['ER']개까지만 "자책점"으로 확정하고 나머지(있다면 비자책 실점)는 버린다 — 어차피
      비자책 실점은 포인트에 영향이 없다. er_events가 stat['ER']보다 적게 잡혔으면(릴레이
      파싱 누락) 모자란 만큼은 _attach_play_log의 "기타 보정"이 자동으로 흡수한다.
    - QS/QS+: "6회를 3자책 이하로, 7회를 2자책 이하로 마쳤을 때"라는 조건 자체가 6회/7회
      시점의 판정이라 각각 6회, 7회에 고정으로 붙인다.
    - 완투/완봉/노히트/퍼펙트/세이브/홀드/블론세이브: "경기(또는 등판)의 마지막 투수"라는
      조건이라 이 투수가 실제로 던진 마지막 이닝(log에 남은 마지막 이닝)에 붙인다 — 홀드의
      경우 그 이닝을 마치고 강판된 시점에 해당한다.
    - 폭투/보크는 박스스코어 합계로만 잡히고 relay 쪽에 개별 이닝 태깅이 없어 그대로 경기
      전체 단위로 남긴다."""
    last_inn = None
    for e in log:
        if e["inn"] is not None:
            last_inn = e["inn"]

    lines = []
    er_total = stat["ER"]
    if er_total:
        for c in sorted(er_events, key=lambda c: c["inn"])[:er_total]:
            lines.append({"inn": c["inn"], "text": f"자책점 허용 ({c['runner']} 득점)",
                           "points": PITCHER_POINTS["ER"], "tags": {"ER": 1}})
    if stat["WP"]:
        lines.append({"inn": None, "text": f"폭투 {stat['WP']}개",
                       "points": stat["WP"] * PITCHER_POINTS["WP"], "tags": {"WP": stat["WP"]}})
    if stat["BK"]:
        lines.append({"inn": None, "text": f"보크 {stat['BK']}개",
                       "points": stat["BK"] * PITCHER_POINTS["BK"], "tags": {"BK": stat["BK"]}})
    if stat["QSPLUS"]:
        lines.append({"inn": 7, "text": "퀄리티스타트+", "points": PITCHER_POINTS["QSPLUS"], "tags": {"QSPLUS": 1}})
    elif stat["QS"]:
        lines.append({"inn": 6, "text": "퀄리티스타트", "points": PITCHER_POINTS["QS"], "tags": {"QS": 1}})
    if stat["HOLD"]:
        lines.append({"inn": last_inn, "text": "홀드", "points": PITCHER_POINTS["HOLD"], "tags": {"HOLD": 1}})
    if stat["SAVE"]:
        lines.append({"inn": last_inn, "text": "세이브", "points": PITCHER_POINTS["SAVE"], "tags": {"SAVE": 1}})
    if stat["BLOWN"]:
        lines.append({"inn": last_inn, "text": "블론 세이브", "points": PITCHER_POINTS["BLOWN"], "tags": {"BLOWN": 1}})
    if stat["PERFECT"]:
        lines.append({"inn": last_inn, "text": "퍼펙트게임", "points": PITCHER_POINTS["PERFECT"], "tags": {"PERFECT": 1}})
    elif stat["NOHIT"]:
        lines.append({"inn": last_inn, "text": "노히트", "points": PITCHER_POINTS["NOHIT"], "tags": {"NOHIT": 1}})
    if stat["SHO"]:
        lines.append({"inn": last_inn, "text": "완봉", "points": PITCHER_POINTS["SHO"], "tags": {"SHO": 1}})
    elif stat["CG"]:
        lines.append({"inn": last_inn, "text": "완투", "points": PITCHER_POINTS["CG"], "tags": {"CG": 1}})
    return lines


def _batter_box_summary_lines(row: dict, log: list[dict]) -> list[dict]:
    """타자 쪽 박스스코어 전용 항목(투수의 _pitcher_box_summary_lines에 대응) — 중계 텍스트
    만으로는 절대 못 만드는 항목들이라 여기서 박스스코어(etcRecords) 값으로 직접 합성한다.
    - 실책: 실책은 "그 순간 수비 중이던 야수"가 아니라 etcRecords의 "실책" 특이기록에 이름이
      그대로 박혀 나와서, 중계 텍스트 패턴 매칭 없이도 이닝까지 정확히 알 수 있다.
    - 만루홈런/사이클히트 보너스: 홈런/안타 자체는 이미 중계 타임라인에 있지만, 그 위에 얹는
      보너스 점수(+10/+50)는 "이 경기에서 만루/사이클을 달성했다"는 게임 전체 단위 판정이라
      개별 타석 문장에는 나타나지 않는다."""
    lines = []
    for inn in row.pop("_error_innings", []):
        lines.append({"inn": inn, "text": "실책", "points": BATTER_POINTS["E"], "tags": {"E": 1}})
    stat = row["stat"]
    if stat.get("GRANDSLAM"):
        hr_inn = next((e["inn"] for e in log if e.get("tags", {}).get("HR")), None)
        lines.append({
            "inn": hr_inn, "text": "만루홈런 보너스",
            "points": stat["GRANDSLAM"] * BATTER_POINTS["GRANDSLAM"], "tags": {"GRANDSLAM": stat["GRANDSLAM"]},
        })
    if stat.get("CYCLE"):
        last_inn = None
        for e in log:
            if e.get("inn") is not None:
                last_inn = e["inn"]
        lines.append({
            "inn": last_inn, "text": "사이클히트 보너스",
            "points": BATTER_POINTS["CYCLE"], "tags": {"CYCLE": 1},
        })
    return lines


def _attach_play_log(
    row: dict, timeline: dict, er_events: list[dict] | None = None, ambiguous_name: bool = False,
) -> None:
    """선수 클릭 팝업용 "타석/수비별 결과 - 포인트" 내역. 릴레이 텍스트를 직접 분류해서 만든
    거라, 박스스코어 기반 최종 LP(row['lp'])와 합계가 다를 수 있다(예: 병살 가담이 이미 그
    경기에서 2번 이상 잡혔지만 실제 점수는 1회로 상한). 그 차이는 마지막 줄에 "기타 보정"으로
    투명하게 남겨서, 팝업에 나온 항목을 전부 더하면 항상 실제 LP와 정확히 맞도록 한다.
    투수는 이닝/자책/QS 등 박스스코어 전용 항목을 실제로 그 일이 일어난 이닝 뒤에 이어붙여서
    "기타 보정"이 원칙적으로 0에 가깝게 만든다.

    timeline은 (이름, 역할) 튜플로 키가 잡혀 있다 — 두 팀에 동명이인 투수/타자가 있을 때
    이름만으로는 서로 다른 두 선수의 기록이 섞여버리기 때문(relay.py 쪽 compute_relay_stats
    참고). 여기서는 이 행이 투수 행인지 타자 행인지(row['stat']에 'OUT' 키가 있는지)로
    역할을 판정해서 그 역할의 기록만 가져온다.

    ambiguous_name=True면 같은 팀·같은 역할(타자/투수)에 이름이 완전히 같은 선수가 더 있다는
    뜻이다(예: 같은 팀 계투진에 동명이인 "이승현"이 둘) — 이럴 땐 릴레이 텍스트만으로 둘 중
    누구의 플레이인지 원천적으로 구분이 안 되니, 잘못된 세부 내역을 보여주는 대신 그 사실을
    그대로 알린다."""
    if ambiguous_name:
        row["play_log"] = [{
            "inn": None,
            "text": "동명이인 선수가 있어 세부 내역을 표시할 수 없습니다 (박스스코어 합계 기준 LP)",
            "points": row["lp"], "tags": {},
        }]
        return
    role = "pitch" if "OUT" in row["stat"] else "bat"
    log = list(timeline.get((row["name"], role), []))
    # 병살/삼중살 가담은 규정상 "1경기에 1번만 인정"이라, 같은 경기에서 여러 번 잡혀도 실제
    # 점수는 처음 1번만 반영된다. 화면에 전부 +10/+50으로 찍히면 헷갈리니, 두 번째부터는
    # 점수를 0으로 표시하고 문구에 상한 적용 사실을 남긴다(합계는 그대로 LP와 정확히 맞음).
    seen_dp_tp = set()
    for e in log:
        for key in ("DP_FIELD", "TP_FIELD"):
            if e.get("tags", {}).get(key):
                if key in seen_dp_tp:
                    e["text"] += " (1경기 1회 상한, 추가 반영 없음)"
                    e["points"] = 0
                else:
                    seen_dp_tp.add(key)
    if "OUT" in row["stat"]:  # 투수 행
        log = log + _pitcher_box_summary_lines(row["stat"], log, er_events or [])
    else:  # 타자 행
        log = log + _batter_box_summary_lines(row, log)
    log_sum = sum(e["points"] for e in log)
    diff = row["lp"] - log_sum
    if diff:
        log.append({
            "inn": None, "text": "기타 보정 (박스스코어 기준 상한 등)",
            "points": diff, "tags": {},
        })
    row["play_log"] = log


def _zero_batter_stat() -> dict:
    return {
        "R": 0, "H": 0, "BB": 0, "2B": 0, "3B": 0, "HR": 0, "RBI": 0,
        "FO": 0, "GO": 0, "LD": 0, "GDP": 0, "SACFLY": 0, "SACBUNT": 0,
        "SB": 0, "CS": 0, "HBP": 0, "K": 0, "PICKOFF": 0,
        "CYCLE": 0, "GRANDSLAM": 0, "E": 0,
        "ASSIST": 0, "OF_ASSIST": 0, "DP_FIELD": 0, "TP_FIELD": 0,
        "CS_CATCHER": 0, "SB_ALLOWED_CATCHER": 0, "ADVANCE_OUT": 0,
    }


def _zero_pitcher_stat() -> dict:
    return {
        "H": 0, "HR": 0, "ER": 0, "BB": 0, "HBP": 0, "K": 0, "OUT": 0,
        "WP": 0, "BK": 0, "QS": False, "QSPLUS": False,
        "HOLD": 0, "SAVE": 0, "BLOWN": 0,
        "PERFECT": False, "NOHIT": False, "SHO": False, "CG": False,
        "2B_A": 0, "3B_A": 0, "INHERITED_SCORED": 0, "INHERITED_STRANDED": 0,
        "CS_A": 0, "SB_ALLOWED": 0, "PICKOFF_A": 0, "SAVE_OPP": False,
    }


def build_pregame_rows(g: dict) -> tuple[list[dict], list[dict]]:
    """경기 시작 2시간 전부터, 아직 시작 안 한(BEFORE) 경기라도 1군 엔트리 전원을 LP 0짜리
    "출전 예정" 행으로 미리 보여준다. 코리아베이스볼(koreabaseball.com) 등록 현황에서 그날
    기준 1군 엔트리를, 네이버 스포츠 /preview에서 선발 라인업 발표 여부를 가져와 합친다.
    라인업이 아직 발표 전이면 선발투수만(fullLineUp에 그 한 명만 들어있음) 표시되고,
    나머지는 발표되는 대로 자동으로 초록 마커가 붙는다."""
    import pregame

    # 경기가 취소되면(우천취소 등) statusCode는 "RESULT"로 안 넘어가고 "BEFORE"에 계속
    # 머무른 채 cancel=true만 붙는다. is_within_pregame_window는 "경기 시작 몇 시간 전부터"라는
    # 하한선만 있고 상한선이 없어서, 이 체크가 없으면 취소된 경기의 예정 명단이 영영 안
    # 사라지고 계속 표시된다.
    if g.get("cancel"):
        return [], []

    # "BEFORE"(경기 한참 전)뿐 아니라 "READY"(곧 시작, 이 시점에 라인업이 뜨는 경우가 많음)도
    # 경기 시작 전 상태라 여기서 같이 처리해야 한다 — READY로 바뀌는 순간 이 체크에서 빠지면
    # process_game 쪽은 아직 박스스코어가 없어 빈 값을 돌려주고, 결과적으로 막 발표된 선발
    # 라인업이 통째로 안 보이는 공백 구간이 생긴다.
    if g.get("statusCode") not in ("BEFORE", "READY") or not pregame.is_within_pregame_window(g.get("gameDateTime", "")):
        return [], []

    home_code, away_code = g.get("homeTeamCode"), g.get("awayTeamCode")
    home_name, away_name = g.get("homeTeamName", ""), g.get("awayTeamName", "")
    date_str = g.get("gameDate", "")
    date_disp = f"{date_str[5:7]}월 {date_str[8:10]}일" if len(date_str) == 10 else ""

    try:
        home_roster = pregame.fetch_active_roster(home_code, date_str)
        away_roster = pregame.fetch_active_roster(away_code, date_str)
    except Exception as exc:  # noqa: BLE001
        print(f"  {g.get('gameId')} 1군 엔트리 조회 실패: {exc}")
        return [], []

    preview = pregame.fetch_preview(g["gameId"]) or {}
    stadium = preview.get("stadium", "")

    from position import load_db  # naver_fantasy_score <-> position 순환 임포트 방지(지연 임포트)
    name_pos_by_team: dict[tuple, str] = {}
    for rec in load_db().get("players", {}).values():
        name_pos_by_team[(rec["name"], rec.get("team", ""))] = rec["effective_position"]

    batter_rows, pitcher_rows = [], []
    for side, code, team, opp, roster in (
        ("home", home_code, home_name, away_name, home_roster),
        ("away", away_code, away_name, home_name, away_roster),
    ):
        side_preview = preview.get(side, {})
        starters = side_preview.get("starters", {})
        starting_pitcher = side_preview.get("starting_pitcher")

        pitcher_names = [n for n, c in roster.items() if c == "투수"]
        pitcher_names.sort(key=lambda n: 0 if n == starting_pitcher else 1)
        for name in pitcher_names:
            pitcher_rows.append({
                "name": name, "team": team, "opponent": opp,
                "date": date_disp, "stadium": stadium, "inn": "",
                "role": "선발" if name == starting_pitcher else "구원",
                "stat": _zero_pitcher_stat(), "lp": 0,
                "is_starter": name == starting_pitcher,
                "status": "pregame",
            })

        batter_names = [n for n, c in roster.items() if c != "투수"]
        batter_names.sort(key=lambda n: starters.get(n, 99))
        for name in batter_names:
            category = roster[name]
            position = name_pos_by_team.get((name, team), category)
            batter_rows.append({
                "name": name, "team": team, "opponent": opp,
                "date": date_disp, "stadium": stadium, "pos": "",
                "position": position, "position_override": False,
                "ab": 0, "stat": _zero_batter_stat(), "lp": 0,
                "is_starter": name in starters,
                "bat_order": starters.get(name),
                "status": "pregame",
            })

    return batter_rows, pitcher_rows


def collect_date(date_str: str, position_map: dict | None = None) -> tuple[list[dict], list[dict]]:
    all_batters, all_pitchers = [], []
    for g in fetch_schedule(date_str):
        gid = g["gameId"]
        if g.get("statusCode") in ("BEFORE", "READY"):
            try:
                b, p = build_pregame_rows(g)
            except Exception as exc:  # noqa: BLE001
                print(f"  {gid} 출전 예정 명단 처리 실패: {exc}")
                b, p = [], []
            all_batters.extend(b)
            all_pitchers.extend(p)
            continue  # 아직 시작 전 → 박스스코어는 없음
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
