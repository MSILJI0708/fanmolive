"""네이버가 투수 박스스코어를 비워서 주는 날짜(2011 정규시즌 전체, 2022-05-22, 2022-09-01)의
투수 기록을 KBO 공식 박스스코어로 채워 다시 수집한다.

네이버 record 응답에 pitchersBoxscore가 빈 배열로 오고 팀 합계(teamPitchingBoxscore)만
있어서, 일반 백필로는 그 날 투수 행이 0개가 된다(타자는 정상). KBO 공식 사이트
(GetBoxScoreScroll)에는 같은 경기의 투수 표가 온전히 있으므로, 그 표를 네이버
pitchersBoxscore 형식으로 바꿔 record 응답에 끼워 넣은 뒤 process_game을 그대로 돌린다.
그러면 QS/완투 판정, 문자중계 기반 심화 기록, LP 계산이 평소 경로와 똑같이 적용된다.

한계: KBO 표는 볼넷과 사구를 "4사구" 하나로 합쳐 준다. 전부 볼넷으로 넣는다(LP 가중치가
같아 점수는 정확하고, 투수 기록실의 볼넷 수만 사구만큼 많아진다).

사용법: python backfill_kbo_pitchers.py [날짜 ...]   (없으면 투수 0명인 정규시즌 날짜 전부)
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import os
import re
import sys
from collections import Counter, defaultdict

import naver_fantasy_score as nfs
from data_paths import fname_for, glob_data_files
from kbo_official import (
    BOXSCORE_URL, _load_player_cache, _post_json, _rows_of, _save_player_cache,
    resolve_player_code,
)

HERE = os.path.dirname(os.path.abspath(__file__))
MAX_WORKERS = 6
_KBO_COLS = ["name", "appear", "result", "W", "L", "SAVE", "IP", "BF", "PITCHES",
             "AB", "H", "HR", "BB_HBP", "K", "R", "ER", "ERA"]
_FRAC = {"1/3": "⅓", "2/3": "⅔"}
# KBO 선수 검색이 같은 이름 여러 명(야수 포함)을 줘서 자동으로 못 고른 투수들 — 검색 결과 중
# 포지션이 "투수"이고 그 해 소속팀 이력이 맞는 쪽으로 확정했다.
_MANUAL_CODE = {("권혁", "삼성"): "72447", ("정현욱", "삼성"): "96462", ("오성민", "SSG"): "75347"}


def _kbo_inn(text: str) -> str:
    """"4 1/3" -> "4⅓", "2/3" -> "⅔" (innings_to_outs가 읽는 네이버 표기)."""
    text = text.replace("&nbsp;", " ").strip()
    m = re.match(r"^(\d+)?\s*(1/3|2/3)?$", text)
    if not m:
        return text
    return (m.group(1) or "") + _FRAC.get(m.group(2) or "", "")


def _int(v) -> int:
    try:
        return int(str(v).replace("&nbsp;", "").strip() or 0)
    except ValueError:
        return 0


def _known_codes() -> dict:
    """(이름, 팀) -> 이미 저장된 데이터에서 본 player_code. 한 코드로만 나온 것만 쓴다."""
    seen: dict = defaultdict(Counter)
    for fp in glob_data_files():
        season = os.path.basename(fp)[5:9]
        if not ("2008" <= season <= "2024"):
            continue
        with open(fp, encoding="utf-8") as f:
            d = json.load(f)
        for r in d.get("pitchers", []):
            if r.get("player_code"):
                seen[(r["name"], r["team"])][r["player_code"]] += 1
    known = {k: next(iter(c)) for k, c in seen.items() if len(c) == 1}
    # 이적한 선수(예: 정현욱 삼성->LG)는 (이름, 팀)으로 못 찾으니, 이름이 코드 하나로만
    # 나오는 경우 이름만으로도 찾게 한다(동명이인이 있으면 쓰지 않는다)
    by_name: dict = defaultdict(set)
    for (name, _team), c in seen.items():
        by_name[name] |= set(c)
    known.update({(n, None): next(iter(c)) for n, c in by_name.items() if len(c) == 1})
    return known


def kbo_pitchers_boxscore(game_id: str, rd: dict, known: dict, cache: dict) -> dict:
    season = int(game_id[:4])
    raw = _post_json(BOXSCORE_URL, {"leId": 1, "srId": 0, "seasonId": season,
                                    "gameId": game_id[:13]})
    if raw.get("code") != "100" or not raw.get("arrPitcher"):
        raise RuntimeError(f"KBO 박스스코어 없음({raw.get('code')})")
    info = rd.get("gameInfo", {})
    team = {"away": nfs.normalize_team_name(info.get("aName", "")),
            "home": nfs.normalize_team_name(info.get("hName", ""))}
    decided = {p.get("name"): p.get("pCode") for p in rd.get("pitchingResult") or []}
    out = {}
    for idx, side in enumerate(("away", "home")):   # KBO 응답은 [원정, 홈] 순서
        rows = []
        for row in _rows_of(raw["arrPitcher"][idx]["table"]):
            vals = dict(zip(_KBO_COLS, row))
            name = (vals.get("name") or "").strip()
            if not name:
                continue
            bbhp = _int(vals.get("BB_HBP"))
            code = (decided.get(name) or _MANUAL_CODE.get((name, team[side])) or known.get((name, team[side]))
                    or known.get((name, None)) or resolve_player_code(name, team[side], cache))
            rows.append({
                "name": name, "pcode": code, "inn": _kbo_inn(vals.get("IP", "")),
                "hit": _int(vals.get("H")), "hr": _int(vals.get("HR")),
                "bb": bbhp, "bbhp": bbhp, "kk": _int(vals.get("K")),
                "r": _int(vals.get("R")), "er": _int(vals.get("ER")),
                "wls": (vals.get("result") or "").replace("&nbsp;", "").strip(),
            })
        out[side] = rows
    return out


def main():
    with open(os.path.join(HERE, "season_calendar.json"), encoding="utf-8") as f:
        cal = json.load(f)
    dates = sys.argv[1:]
    if not dates:
        for ds, v in sorted(cal.items()):
            if (v or {}).get("round") != "kbo_r" or not v.get("game_ids") or ds[:4] < "2008":
                continue
            with open(fname_for(ds), encoding="utf-8") as f:
                d = json.load(f)
            if d.get("batters") and not d.get("pitchers"):
                dates.append(ds)
    print(f"대상 {len(dates)}일: {dates[:3]} ... {dates[-3:]}")

    known = _known_codes()
    cache = _load_player_cache()
    orig_fetch = nfs.fetch_record

    def patched_fetch(game_id):
        rd = orig_fetch(game_id)
        pb = rd.get("pitchersBoxscore") or {}
        if rd.get("battersBoxscore", {}).get("home") and not pb.get("home"):
            rd["pitchersBoxscore"] = kbo_pitchers_boxscore(game_id, rd, known, cache)
        return rd

    nfs.fetch_record = patched_fetch

    for ds in dates:
        gids = cal[ds]["game_ids"]
        pos_map = nfs.load_position_map(ds)
        batters, pitchers, failed = [], [], []
        with cf.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futs = {ex.submit(nfs.process_game, gid, position_map=pos_map): gid for gid in gids}
            for fut in cf.as_completed(futs):
                try:
                    b, p = fut.result()
                except Exception as exc:  # noqa: BLE001
                    failed.append(f"{futs[fut]}: {exc}")
                    continue
                batters.extend(b)
                pitchers.extend(p)
        with open(fname_for(ds), encoding="utf-8") as f:
            old = json.load(f)
        # 한 경기라도 실패하면 기존 파일을 건드리지 않는다(타자 기록을 잃지 않게)
        if failed or len(batters) < len(old.get("batters", [])):
            print(f"!!! {ds} 건너뜀: 실패 {failed} / 타자 {len(batters)} < 기존 {len(old['batters'])}")
            continue
        old["batters"] = sorted(batters, key=lambda r: -r["lp"])
        old["pitchers"] = sorted(pitchers, key=lambda r: -r["lp"])
        with open(fname_for(ds), "w", encoding="utf-8") as f:
            json.dump(old, f, ensure_ascii=False)
        no_code = sum(1 for r in pitchers if not r.get("player_code"))
        print(f"=== {ds} ({len(batters)}타자/{len(pitchers)}투수, 코드없음 {no_code})")

    _save_player_cache(cache)


if __name__ == "__main__":
    main()
