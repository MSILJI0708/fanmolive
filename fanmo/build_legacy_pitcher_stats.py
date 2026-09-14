"""1982~2000년 개인 연도별 투수 성적을, "2015 KBO 기록대백과 제5판" PDF의 좌표 정보까지
써서 파싱한다(build_legacy_batter_stats.py의 타자 파서는 pypdf의 일렬 텍스트만으로 됐지만,
투수 표는 4줄짜리 세로쓰기 헤더가 컬럼마다 줄 수가 달라서(예: "자책점"은 3줄, "홀드"는
2줄) 단순히 줄 순서로 읽으면 값이 어느 칸인지 못 맞춘다 — 실제로 첫 시도에서 1.74를
평균자책점으로 잘못 읽었다가, 좌표 기반으로 다시 맞춰보니 1.74는 WHIP이고 6.10이
평균자책점이었다는 걸 계산으로 확인했다(ER*9/IP=7*9/(10+1/3)=6.10 정확히 일치)).

그래서 pdfplumber로 각 단어의 x좌표를 직접 뽑아서(kbo_pitcher_rows.json — 미리
build_pitcher_rows_cache.py 격 스크립트로 뽑아둠), 헤더 각 컬럼의 x좌표와 데이터 행 각
값의 x좌표를 가장 가까운 것끼리 매칭한다. 이렇게 하면 홀드처럼 2000년 이전엔 아예 칸
자체가 비는 컬럼(2000년부터 시상된 스탯이라 그 전엔 값이 없음, INTRODUCTION 페이지에서
확인)도 자동으로 처리된다(그 칸에 해당하는 x좌표에 단어가 없으면 그냥 0으로 둠).

season_stats.json/career_stats.json의 PITCHER_SUM_KEYS와 최대한 맞추되, 이 시대 기록엔
블론세이브/QS/QS+/노히트/퍼펙트가 없어(그런 세분화된 집계 자체가 없음) 전부 0으로 둔다.

사용법: python build_legacy_pitcher_stats.py [kbo_pitcher_rows.json 경로]
"""
from __future__ import annotations

import json
import os
import re
import sys

from kbo_official import _load_player_cache, _save_player_cache, resolve_player_code
from naver_fantasy_score import normalize_team_name

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SRC = os.path.join(HERE, "kbo_pitcher_rows.json")
OUT_PATH = os.path.join(HERE, "legacy_pitcher_seasons.json")
UNPARSED_PATH = os.path.join(HERE, "legacy_pitcher_unparsed.json")

YEAR_MIN, YEAR_MAX = 1982, 2000

# 데이터 행 실측 x좌표(97년 감병훈 행으로 직접 확인)를 기준 컬럼 위치로 쓴다.
COL_REF = [
    (91, "G"), (106, "CG"), (116, "SHO"), (131, "GS"), (145, "FINISH"), (159, "W"),
    (173, "RELIEFW"), (187, "L"), (201, "SV"), (214, "HOLD"), (227, "IP"),
    (257, "BF"), (278, "ABA"), (296, "H"), (314, "HR"),
    (328, "SACBUNT_A"), (342, "SACFLY_A"), (360, "BB"), (373, "IBB"), (388, "HBP"),
    (401, "WP"), (412, "BK"), (431, "K"), (448, "R"), (466, "ER"),
    (477, "WHIP"), (496, "ERA"), (528, "WINPCT"),
]
COL_TOL = 8  # 컬럼 사이 최소 간격(약 13px)보다 작게 잡아 오매칭 방지
# 소속(팀) 토큰은 항상 숫자가 아니다(이적 표시 "·" 포함 한글/영문) — x좌표 경계선이
# 흔들리는 것(예: G값 "41"이 x=88로 찍혀 팀 범위 x<90과 겹침)을 피하려고, "숫자처럼
# 생겼는가"로 팀 토큰과 스탯 토큰을 가른다.
_NUMERIC_RE = re.compile(r"^-?\d+(\.\d+)?[⅓⅔]?$|^-$")

NAME_RE = re.compile(r"^([가-힣]{2,5})\(([^)]*)\)(\d{2}\.\d{2}\.\d{2})")
YEAR_RE = re.compile(r"^★?(\d{2})★?$")
HEADER_SKIP = {
    "연소경완완선종승구패세홀투타타피피희희4고사폭보탈실자W평승수",
    "구의H", "균", "기원이안홈삼책자비", "이4I", "책",
    "PART5개인연도별투수성적", "KBO기록대백과2015",
    "연소경타타득안23홈루타4고사삼희희도도병실타장출O도수비",
    "의", "공", "루", "기루루타살타루P성위치별",
}

TEAM_FRAGMENTS = {
    "KIA": "KIA", "LG": "LG", "MBC": "LG", "NC": "NC", "OB": "OB", "SK": "SK",
    "넥센": "넥센", "두산": "두산", "롯데": "롯데", "빙그레": "빙그레", "삼미": "삼미",
    "삼성": "삼성", "쌍방울": "쌍방울", "청보": "청보", "태평양": "태평양", "한화": "한화",
    "해태": "해태", "현대": "현대", "히어로즈": "히어로즈", "우리": "우리",
}

_INNING_FRAC = {"⅓": 1, "⅔": 2}


def _parse_ip_to_outs(text: str) -> int:
    m = re.match(r"(\d+)([⅓⅔]?)", text)
    if not m:
        return 0
    whole, frac = m.groups()
    return int(whole) * 3 + _INNING_FRAC.get(frac, 0)


def _assign_columns(items: list[tuple[int, str]]) -> dict:
    """items[0]=연도. 그 뒤로 숫자처럼 안 생긴 토큰이 이어지는 동안은 팀 이름, 숫자처럼
    생긴 첫 토큰부터는 그 뒤로 전부 스탯 값 — 각 값을 x좌표로 COL_REF의 가장 가까운
    컬럼에 매칭한다."""
    team_toks = []
    values: dict[str, str] = {}
    in_team = True
    for x, text in items[1:]:
        if in_team and not _NUMERIC_RE.match(text):
            team_toks.append(text)
            continue
        in_team = False
        best = min(COL_REF, key=lambda c: abs(c[0] - x))
        if abs(best[0] - x) <= COL_TOL:
            values[best[1]] = text
    return {"team": "".join(team_toks), "values": values}


def parse_file(path: str) -> tuple[list[dict], list[str]]:
    with open(path, encoding="utf-8") as f:
        rows = json.load(f)

    out: list[dict] = []
    unparsed: list[str] = []
    current_name: str | None = None
    skip_section = False

    for items in rows:
        text = "".join(t for _, t in items)
        if not text:
            continue
        if text in HEADER_SKIP or text.isdigit() and len(text) <= 3:
            continue

        m = NAME_RE.match(text)
        if m:
            current_name = m.group(1)
            skip_section = False
            continue
        if text.startswith("데뷔첫경기") or text.startswith("통산"):
            continue
        if "▸" in text:
            skip_section = True
            continue
        if skip_section or current_name is None:
            continue

        ym = YEAR_RE.match(items[0][1])
        if not ym:
            continue
        yy = int(ym.group(1))
        year = 1900 + yy if yy >= 50 else 2000 + yy
        if not (YEAR_MIN <= year <= YEAR_MAX):
            continue

        parsed = _assign_columns(items)
        team_raw = parsed["team"]
        if "·" in team_raw:
            unparsed.append(f"{current_name} {year} {team_raw} (이적)")
            continue
        team = TEAM_FRAGMENTS.get(team_raw)
        if team is None:
            unparsed.append(f"{current_name} {year} {team_raw} (팀 인식 실패)")
            continue

        v = parsed["values"]
        try:
            g = int(v.get("G", 0))
            gs = int(v.get("GS", 0))
            w = int(v.get("W", 0))
            loss = int(v.get("L", 0))
            sv = int(v.get("SV", 0))
            hold = int(v.get("HOLD", 0))
            bf = int(v.get("BF", 0))
            h = int(v.get("H", 0))
            hr = int(v.get("HR", 0))
            bb = int(v.get("BB", 0))
            hbp = int(v.get("HBP", 0))
            wp = int(v.get("WP", 0))
            bk = int(v.get("BK", 0))
            k = int(v.get("K", 0))
            er = int(v.get("ER", 0))
            cg = int(v.get("CG", 0))
            sho = int(v.get("SHO", 0))
        except ValueError:
            unparsed.append(f"{current_name} {year} {team_raw} (숫자 파싱 실패)")
            continue
        outs = _parse_ip_to_outs(v.get("IP", "0"))

        out.append({
            "name": current_name, "year": year, "team": normalize_team_name(team),
            "G": g, "GS": gs, "OUT": outs,
            "stat": {
                "ER": er, "H": h, "HR": hr, "BB": bb, "HBP": hbp, "K": k, "WP": wp, "BK": bk,
                "WIN": w, "LOSS": loss, "SAVE": sv, "HOLD": hold, "BLOWN": 0,
                "QS": 0, "QSPLUS": 0, "SHO": sho, "CG": cg, "NOHIT": 0, "PERFECT": 0,
            },
        })
    return out, unparsed


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SRC
    rows, unparsed = parse_file(src)
    print(f"파싱된 행 {len(rows)}개, 건너뛴 행 {len(unparsed)}개")

    cache = _load_player_cache()
    resolved = 0
    for row in rows:
        code = resolve_player_code(row["name"], row["team"], cache)
        row["player_code"] = code
        if code:
            resolved += 1
    _save_player_cache(cache)
    print(f"선수코드 매칭 {resolved}/{len(rows)}")

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    with open(UNPARSED_PATH, "w", encoding="utf-8") as f:
        json.dump(unparsed, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
