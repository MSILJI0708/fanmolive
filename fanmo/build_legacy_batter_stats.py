"""1982~2000년(네이버 API·KBO 공식 사이트 어디에도 경기 단위 데이터가 없는 구간)은
KBO 공식 e-Book "2015 KBO 기록대백과 제5판"(koreabaseball.com에서 로그인 없이 받을 수
있는 PDF, https://6ptotvmi5753.edge.naverncp.com/KBO_FILE/ebook/pdf/2015_deagam.pdf)의
"PART 5 개인 연도별 타자 성적" 섹션을 파싱해서 시즌 통산 기록(경기 단위 아님, 그 해 누적
합계 한 줄)만이라도 확보한다. 투수는 아직 안 함(표 구조가 더 복잡해서 이번엔 타자만).

PDF에서 텍스트를 뽑으면(pypdf) 표가 세로쓰기 헤더 4줄 + "연도 팀 경기 타석 타수 득점 안타
2루타 3루타 홈런 루타 타점 4구 고의4구 사구 삼진 희타 희비 도루 도루실패 병살 실책 타율
장타율 출루율 OPS 도루성공률 (위치별출장수)" 순서의 데이터 행으로 나온다(직접 대조로
확인한 순서 — 특히 AVG 다음이 OBP가 아니라 SLG인 걸 실제 계산으로 검증함: TB/AB가 두
번째 비율값과 일치했음). 선수 블록은 "이름(한자) 생년월일 투타 출신교 (데뷔년.월)" 줄로
시작해서 "데뷔 첫 경기..." 줄, 4줄짜리 헤더, 그 다음 연도별 데이터 행들, "통산" 합계 행
순서로 반복된다("통산" 행은 우리가 직접 합산할 거라 건너뜀).

이적한 해(팀 사이에 "·"가 들어간 표기, 예 "롯·L")나 올스타/동군·서군 같은 팀이 아닌 표기는
정확한 팀 귀속을 못 미더워 그냥 건너뛰고 legacy_batter_unparsed.json에 남긴다 — 틀린 팀으로
집계하느니 그 시즌 하나 빠지는 게 낫다는 판단.

산출물 legacy_batter_seasons.json은 build_stats.py의 aggregate()가 data_*.json과 같은
방식으로 season_batters/career_batters 누적에 그대로 얹어 쓴다(경기별 데이터가 아니라
이미 "그 해 누적"이라 G/AB/스탯을 한 번만 더해주면 된다).

사용법: python build_legacy_batter_stats.py [kbo_daegam_batters.txt 경로]
"""
from __future__ import annotations

import json
import os
import re
import sys

from kbo_official import _load_player_cache, _save_player_cache, resolve_player_code
from naver_fantasy_score import normalize_team_name

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SRC = os.path.join(HERE, "kbo_daegam_batters.txt")
OUT_PATH = os.path.join(HERE, "legacy_batter_seasons.json")
UNPARSED_PATH = os.path.join(HERE, "legacy_batter_unparsed.json")

YEAR_MIN, YEAR_MAX = 1982, 2000

NAME_RE = re.compile(r"^([가-힣]{2,5})\(\s*\)(\S*)\s+(\d{2}\.\d{2}\.\d{2})\s")
# 해당 연도가 부문 1위 등 특이 기록이면 별표가 연도 앞이나 뒤 어느 쪽에도 붙을 수 있다
# (예: "82★ 삼 미"와 "★82 M B C" 둘 다 실제로 나옴 — PDF 추출 순서가 들쭉날쭉해서).
DATA_RE = re.compile(r"^★?(\d{2})★?\s+(.+)$")
HEADER_MARKERS = ("연 소 경", "기 루 루", "도 속 수", "의 루")

# PDF에서 팀 이름이 한글 음절 사이에 공백이 끼어(예: "롯 데") 나오거나 알파벳이
# 한 글자씩 떨어져(예: "S K") 나온다 — 공백을 다 지운 형태를 키로 쓴다.
TEAM_FRAGMENTS = {
    "KIA": "KIA", "LG": "LG", "MBC": "LG", "NC": "NC", "OB": "OB", "SK": "SK",
    "넥센": "넥센", "두산": "두산", "롯데": "롯데", "빙그레": "빙그레", "삼미": "삼미",
    "삼성": "삼성", "쌍방울": "쌍방울", "청보": "청보", "태평양": "태평양", "한화": "한화",
    "해태": "해태", "현대": "현대", "히어로즈": "히어로즈", "우리": "우리",
}


def _parse_team(tokens: list[str]) -> str | None:
    joined = "".join(tokens)
    if "·" in joined:
        return None  # 이적한 해 — 정확한 팀 귀속 불가, 건너뜀
    return TEAM_FRAGMENTS.get(joined)


def parse_file(path: str) -> tuple[list[dict], list[str]]:
    lines = open(path, encoding="utf-8").read().splitlines()
    rows: list[dict] = []
    unparsed: list[str] = []

    current_name: str | None = None
    skip_section = False  # 포스트시즌/올스타 등 "...▸" 구간

    for line in lines:
        line = line.strip()
        if not line or line.startswith("<<<PAGE") or line.startswith("기록대백과KBO"):
            continue
        if any(line.startswith(m) for m in HEADER_MARKERS):
            continue

        m = NAME_RE.match(line)
        if m:
            current_name = m.group(1)
            skip_section = False
            continue
        if line.startswith("데뷔 첫 경기"):
            continue
        if line.endswith("▸"):
            skip_section = True
            continue
        if skip_section or current_name is None:
            continue

        m = DATA_RE.match(line)
        if not m:
            continue
        yy, rest = m.groups()
        yy_i = int(yy)
        year = 1900 + yy_i if yy_i >= 50 else 2000 + yy_i
        if not (YEAR_MIN <= year <= YEAR_MAX):
            continue

        toks = rest.split()
        team_toks = []
        i = 0
        while i < len(toks) and not re.match(r"^-?\d", toks[i]):
            team_toks.append(toks[i])
            i += 1
        nums = toks[i:i + 25]
        team = _parse_team(team_toks)
        if team is None or len(nums) < 25:
            unparsed.append(f"{current_name} {year} {' '.join(team_toks)}")
            continue
        try:
            vals = [int(v) for v in nums[:20]]
        except ValueError:
            unparsed.append(f"{current_name} {year} {' '.join(team_toks)} (숫자 파싱 실패)")
            continue
        (g, pa, ab, r, h, d2, d3, hr, tb, rbi, bb, ibb, hbp, so,
         sacbunt, sacfly, sb, cs, gdp, e) = vals

        rows.append({
            "name": current_name, "year": year,
            "team": normalize_team_name(team),
            "G": g, "AB": ab,
            "stat": {
                "R": r, "H": h, "2B": d2, "3B": d3, "HR": hr, "RBI": rbi, "BB": bb,
                "HBP": hbp, "K": so, "SB": sb, "CS": cs, "GDP": gdp,
                "SACFLY": sacfly, "SACBUNT": sacbunt,
            },
        })
    return rows, unparsed


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
