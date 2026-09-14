"""career_stats.json에 나온 선수 전원에 대해 player/<이름>/index.html을 만든다.

목적은 URL만으로 선수 기록에 바로 갈 수 있게 하는 것 — 예:
    https://msilji0708.github.io/fanmolive/player/강백호/

실제 렌더링 로직은 전부 player.html(query string으로 player_code를 받아
season_stats.json/career_stats.json을 fetch해서 보여줌)에 그대로 있고, 여기서
만드는 파일들은 그 앞단의 얇은 진입점일 뿐이다:
  - 이름이 유일한 선수(939명 중 899명): player.html?code=...로 즉시 리다이렉트.
  - 동명이인(같은 이름, 다른 player_code — 실제로 40명: 박건우·김태훈·이재원 등)은
    리다이렉트 대신 팀/역할이 적힌 선택 화면을 보여주고, 고르면 그제서야
    player.html로 넘어간다.

매번 전체를 깨끗이 다시 만든다(이름이 바뀌거나 사라지는 선수는 거의 없지만,
혹시 있어도 낡은 폴더가 안 남게).

사용법: python build_player_pages.py (build_stats.py를 먼저 돌려서
career_stats.json을 만들어둬야 함)
"""
from __future__ import annotations

import json
import os
import shutil
import urllib.parse
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "player")

REDIRECT_TMPL = """<!doctype html>
<meta charset="utf-8">
<title>{name} 기록실로 이동</title>
<meta http-equiv="refresh" content="0; url=../../player.html?{qs}">
<script>location.replace("../../player.html?{qs}");</script>
<p>선수 기록실로 이동 중입니다. 자동으로 안 넘어가면 <a href="../../player.html?{qs}">여기</a>를 눌러주세요.</p>
"""

PICKER_TMPL = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name} - 동명이인 선택</title>
<style>
:root {{ color-scheme: light dark; }}
body {{ margin:0; padding:24px; font-family:-apple-system,"Apple SD Gothic Neo","Malgun Gothic",sans-serif; }}
h1 {{ font-size:18px; }}
p {{ color:#777; font-size:13px; }}
ul {{ list-style:none; padding:0; max-width:420px; }}
li a {{ display:flex; justify-content:space-between; gap:12px; padding:12px 14px; margin-bottom:8px;
  border:1px solid #ccc8; border-radius:8px; text-decoration:none; color:inherit; }}
li a:hover {{ background:#8882; }}
.role {{ color:#888; font-size:12px; }}
</style>
<h1>"{name}" 동명이인 {count}명</h1>
<p>같은 이름의 선수가 여러 명 있습니다. 소속 팀으로 찾는 선수를 골라주세요.</p>
<ul>
{items}
</ul>
"""


def _slugify(name: str) -> str:
    # 파일시스템/URL 양쪽에서 문제 될 만한 문자만 살짝 걸러낸다(선수 이름엔 거의 없음).
    return "".join(c for c in name if c not in '\\/:*?"<>|').strip() or "unknown"


def main():
    with open(os.path.join(HERE, "career_stats.json"), encoding="utf-8") as f:
        career = json.load(f)

    # name -> list of {code, role, team, games}
    by_name: dict[str, list[dict]] = defaultdict(list)
    for role in ("batters", "pitchers"):
        for r in career.get(role, []):
            code = r.get("player_code")
            name = r.get("name")
            if not code or not name:
                continue
            by_name[name].append({"code": code, "role": role, "team": r.get("team") or "", "games": r.get("G") or 0})

    if os.path.exists(OUT_DIR):
        shutil.rmtree(OUT_DIR)
    os.makedirs(OUT_DIR, exist_ok=True)

    redirects = pickers = 0
    for name, candidates in by_name.items():
        # 같은 player_code가 타자·투수 양쪽에 다 있는 선수(연장전에 비상 등판한 투수 등,
        # 실제로 KT 박건우 코드 55046이 투수 6경기/타자 2경기로 둘 다 기록에 있음)는
        # 코드 기준으로 합쳐서 한 사람으로 세되, 경기 수가 더 많은 쪽 role을 그 선수의
        # 대표 역할로 삼는다(단순히 타자를 우선하면 부업으로 2경기 나온 쪽이 주 종목인
        # 투수 6경기 기록을 가려버린다).
        by_code: dict[str, dict] = {}
        for c in candidates:
            existing = by_code.get(c["code"])
            if existing is None or c["games"] > existing["games"]:
                by_code[c["code"]] = c
        uniq = list(by_code.values())

        slug = _slugify(name)
        dir_path = os.path.join(OUT_DIR, slug)
        os.makedirs(dir_path, exist_ok=True)

        if len(uniq) == 1:
            c = uniq[0]
            qs = urllib.parse.urlencode({"code": c["code"], "role": c["role"], "name": name})
            html = REDIRECT_TMPL.format(name=name, qs=qs)
            redirects += 1
        else:
            items = []
            for c in sorted(uniq, key=lambda c: c["team"]):
                qs = urllib.parse.urlencode({"code": c["code"], "role": c["role"], "name": name})
                role_label = "투수" if c["role"] == "pitchers" else "타자"
                items.append(
                    f'<li><a href="../../player.html?{qs}"><span>{c["team"]}</span>'
                    f'<span class="role">{role_label}</span></a></li>'
                )
            html = PICKER_TMPL.format(name=name, count=len(uniq), items="\n".join(items))
            pickers += 1

        with open(os.path.join(dir_path, "index.html"), "w", encoding="utf-8") as f:
            f.write(html)

    print(f"player/ 아래 {redirects + pickers}개 폴더 생성 "
          f"(단일 선수 리다이렉트 {redirects}개, 동명이인 선택 화면 {pickers}개)")


if __name__ == "__main__":
    main()
