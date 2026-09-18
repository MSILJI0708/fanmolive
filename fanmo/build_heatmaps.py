"""선수별 "스타일" 히트맵 데이터를 만든다(선수 기록실의 히트맵 탭용).

야구는 평균의 스포츠라지만 같은 타율이라도 몰아치기형과 꾸준형이 있고, 같은 평균자책점
이라도 1회에 몰아서 주고 버티는 투수와 난잡하게 흘리는 투수가 있다. 시즌 합계로는
안 보이는 그 "분포"를 보여주기 위한 집계다.

만드는 것(시즌별):
  타자
    hits_per_game   경기당 안타 수의 분포            {안타수: 경기수}
    tb_per_game     경기당 루타 수의 분포            {루타수: 경기수}
    pa_x_hits       경기당 타석수 x 안타 수          {"타석|안타": 경기수}
    pa_x_tb         경기당 타석수 x 루타 수          {"타석|루타": 경기수}
    by_inning       이닝별 타수/안타/루타/볼넷/사구/희비  {이닝: {...}} -> 타율·OPS 계산
  투수
    per_game        경기당 피안타/피출루/피홈런/자책점 분포  {지표: {값: 경기수}}
    by_inning       이닝별 피안타/피출루/자책점         {이닝: {...}}

실점(R)은 데이터에 저장되어 있지 않아 자책점(ER)으로 대신한다.
점수차별·투구수 관련 히트맵은 타석 시점 점수와 투구수가 저장되어 있지 않아 아직 못 만든다.

선수가 수천 명이라 한 파일에 담으면 수 MB가 되어 기록실 페이지가 무거워진다. 선수별로
heatmap/<player_code>.json 에 나눠 쓰고, 페이지는 히트맵 탭을 열 때만 그 선수 것을
불러온다. 매 파이프라인마다 전부 다시 쓰면 커밋이 수천 파일씩 바뀌므로, 내용이 실제로
달라진 파일만 쓴다.

사용법: python build_heatmaps.py
"""
from __future__ import annotations

import json
import os
from collections import Counter, defaultdict

from data_paths import glob_data_files

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "heatmap")
REGULAR_ROUNDS = {"kbo_r"}

# 타석 결과로 치는 태그(수비 기록인 ASSIST, DP_FIELD 등은 같은 play_log에 섞여 있지만
# 그 선수의 타석이 아니므로 세지 않는다)
AB_OUT_TAGS = ("K", "GO", "FO", "LD", "GDP")
MAX_INNING = 10   # 10회 이상 연장은 한 칸으로 묶는다


def _tb(h, d2, d3, hr) -> int:
    # 안타 1개가 이미 1루타로 잡혀 있으므로 장타는 추가 루수만 더한다
    return h + d2 + 2 * d3 + 3 * hr


def _inning_key(inn) -> str:
    try:
        n = int(inn)
    except (TypeError, ValueError):
        return ""
    return str(min(n, MAX_INNING)) if n >= 1 else ""


def _new_batter():
    return {
        "hits_per_game": Counter(), "tb_per_game": Counter(),
        "pa_x_hits": Counter(), "pa_x_tb": Counter(),
        "by_inning": defaultdict(Counter),
    }


def _new_pitcher():
    return {"per_game": defaultdict(Counter), "by_inning": defaultdict(Counter)}


def _season_of_path(fp: str) -> str:
    return os.path.basename(fp)[len("data_"):len("data_") + 4]


def collect(files):
    batters: dict = defaultdict(lambda: defaultdict(_new_batter))    # code -> season -> acc
    pitchers: dict = defaultdict(lambda: defaultdict(_new_pitcher))
    names: dict = {}

    for fp in files:
        with open(fp, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("round") not in REGULAR_ROUNDS:
            continue
        season = (d.get("date") or os.path.basename(fp)[5:13]).replace("-", "")[:4]

        for row in d.get("batters", []):
            code = row.get("player_code")
            if not code:
                continue
            s = row.get("stat") or {}
            names[code] = row.get("name")
            acc = batters[code][season]
            h = s.get("H", 0)
            tb = _tb(h, s.get("2B", 0), s.get("3B", 0), s.get("HR", 0))
            pa = (row.get("ab", 0) + s.get("BB", 0) + s.get("HBP", 0)
                  + s.get("SACFLY", 0) + s.get("SACBUNT", 0))
            if pa == 0:
                continue   # 대수비·대주자로만 나온 경기는 타격 분포에서 뺀다
            acc["hits_per_game"][h] += 1
            acc["tb_per_game"][tb] += 1
            acc["pa_x_hits"][f"{pa}|{h}"] += 1
            acc["pa_x_tb"][f"{pa}|{tb}"] += 1

            for ev in row.get("play_log") or []:
                inn = _inning_key(ev.get("inn"))
                tags = ev.get("tags") or {}
                if not inn:
                    continue
                bucket = acc["by_inning"][inn]
                if tags.get("H"):
                    bucket["AB"] += 1
                    bucket["H"] += 1
                    bucket["TB"] += _tb(1, tags.get("2B", 0), tags.get("3B", 0), tags.get("HR", 0))
                elif any(tags.get(t) for t in AB_OUT_TAGS):
                    bucket["AB"] += 1
                if tags.get("BB"):
                    bucket["BB"] += 1
                if tags.get("HBP"):
                    bucket["HBP"] += 1
                if tags.get("SACFLY"):
                    bucket["SF"] += 1

        for row in d.get("pitchers", []):
            code = row.get("player_code")
            if not code:
                continue
            s = row.get("stat") or {}
            if not s.get("OUT") and not (s.get("H") or s.get("BB") or s.get("HBP")):
                continue   # 공 하나 안 던지고 교체된 기록 등은 뺀다
            names[code] = row.get("name")
            acc = pitchers[code][season]
            h, bb, hbp = s.get("H", 0), s.get("BB", 0), s.get("HBP", 0)
            acc["per_game"]["H"][h] += 1
            acc["per_game"]["OB"][h + bb + hbp] += 1
            acc["per_game"]["HR"][s.get("HR", 0)] += 1
            acc["per_game"]["ER"][s.get("ER", 0)] += 1

            for ev in row.get("play_log") or []:
                inn = _inning_key(ev.get("inn"))
                tags = ev.get("tags") or {}
                if not inn:
                    continue
                bucket = acc["by_inning"][inn]
                bucket["H"] += tags.get("H", 0)
                bucket["OB"] += tags.get("H", 0) + tags.get("BB", 0) + tags.get("HBP", 0)
                bucket["ER"] += tags.get("ER", 0)
                bucket["OUT"] += tags.get("OUT", 0)
    return batters, pitchers, names


def _plain(obj):
    """Counter/defaultdict를 JSON에 쓸 수 있는 평범한 dict로(키는 문자열로)."""
    if isinstance(obj, dict):
        return {str(k): _plain(v) for k, v in obj.items()}
    return obj


STATE_PATH = os.path.join(OUT_DIR, "_state.json")


def _season_signatures(files) -> dict:
    """시즌 -> "파일수:총바이트". 파일을 열지 않고 크기만 보므로 거의 즉시 끝난다.

    매 파이프라인마다 4,000개 파일을 다 읽으면 60초가 걸려서(실측) 갱신 주기를 크게
    늘린다. 그런데 과거 시즌은 거의 안 바뀐다 — 시즌별로 이 서명을 남겨두고 달라진
    시즌만 다시 읽는다. 수정 시각(mtime)은 CI가 매번 저장소를 새로 체크아웃하면서 전부
    "지금"으로 바뀌어 쓸 수 없으므로, 내용이 바뀌면 같이 바뀌는 크기를 쓴다."""
    sig: dict = defaultdict(lambda: [0, 0])
    for fp in files:
        s = sig[_season_of_path(fp)]
        s[0] += 1
        s[1] += os.path.getsize(fp)
    return {k: f"{v[0]}:{v[1]}" for k, v in sig.items()}


def main():
    import sys

    os.makedirs(OUT_DIR, exist_ok=True)
    all_files = glob_data_files()
    sigs = _season_signatures(all_files)

    old = {}
    if os.path.exists(STATE_PATH) and "--full" not in sys.argv:
        with open(STATE_PATH, encoding="utf-8") as f:
            old = json.load(f)
    changed = sorted(s for s, v in sigs.items() if old.get(s) != v)
    if not changed:
        print("히트맵: 바뀐 시즌 없음 — 건너뜀")
        return

    batters, pitchers, names = collect([fp for fp in all_files if _season_of_path(fp) in changed])

    written = unchanged = 0
    codes = set(batters) | set(pitchers)
    for code in codes:
        path = os.path.join(OUT_DIR, f"{code}.json")
        doc = {"name": None, "batter": {}, "pitcher": {}}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
        # 이번에 다시 읽은 시즌만 갈아 끼우고, 나머지 시즌은 기존 파일 것을 그대로 둔다
        for role, src in (("batter", batters), ("pitcher", pitchers)):
            for season in changed:
                doc[role].pop(season, None)
            doc[role].update(_plain(src.get(code, {})))
        doc["name"] = names.get(code) or doc.get("name")

        text = json.dumps(doc, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                if f.read() == text:
                    unchanged += 1
                    continue
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        written += 1

    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(sigs, f, ensure_ascii=False, sort_keys=True)
    print(f"히트맵: 다시 집계한 시즌 {changed} / 선수 {len(codes)}명 "
          f"(새로 씀 {written}, 변동 없음 {unchanged})")


if __name__ == "__main__":
    main()
