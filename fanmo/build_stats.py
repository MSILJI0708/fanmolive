"""data_YYYYMMDD.json(정규시즌, round=='kbo_r'만) 전체를 선수별로 합산해
시즌 기록실(season_stats.json)과 통산 기록실(career_stats.json)을 만든다.

- 동명이인 구분을 위해 player_code로 묶는다(코드가 없는 행은 스킵).
- 비율 스탯(타율/출루율/장타율/OPS, 평균자책점/WHIP 등)은 카운팅 스탯을 전부 합산한
  뒤 마지막에 한 번만 계산한다(경기별 비율의 평균을 내면 안 된다).
- 올스타전(kbo_as)·시범경기(kbo_e)는 round 필드로 걸러 제외한다. 포스트시즌(kbo_ps_*)도
  일단 "정규시즌 기록실"이라는 성격에 맞춰 제외해 둔다(추후 별도 페이지로 다룰 수 있음).

사용법: python build_stats.py
"""
from __future__ import annotations

import glob
import json
import os
from collections import defaultdict

from naver_fantasy_score import outs_to_innings_str

HERE = os.path.dirname(os.path.abspath(__file__))
REGULAR_ROUNDS = {"kbo_r"}

BATTER_SUM_KEYS = ["R", "H", "2B", "3B", "HR", "RBI", "BB", "HBP", "K",
                   "SB", "CS", "GDP", "SACFLY", "SACBUNT"]
PITCHER_SUM_KEYS = ["ER", "H", "HR", "BB", "HBP", "K", "WP", "BK",
                    "WIN", "LOSS", "SAVE", "HOLD", "BLOWN",
                    "QS", "QSPLUS", "SHO", "CG", "NOHIT", "PERFECT"]


def _round3(x: float) -> float:
    return round(x, 3)


def _new_batter_acc() -> dict:
    d = {k: 0 for k in BATTER_SUM_KEYS}
    d.update({"name": None, "team": None, "player_code": None, "G": 0, "AB": 0})
    return d


def _new_pitcher_acc() -> dict:
    d = {k: 0 for k in PITCHER_SUM_KEYS}
    d.update({"name": None, "team": None, "player_code": None, "G": 0, "GS": 0, "OUT": 0})
    return d


def _finalize_batter(acc: dict) -> dict:
    ab = acc["AB"]
    h, d2, d3, hr = acc["H"], acc["2B"], acc["3B"], acc["HR"]
    singles = max(h - d2 - d3 - hr, 0)
    tb = singles + d2 * 2 + d3 * 3 + hr * 4
    pa = ab + acc["BB"] + acc["HBP"] + acc["SACFLY"] + acc["SACBUNT"]
    avg = _round3(h / ab) if ab else 0.0
    obp_den = ab + acc["BB"] + acc["HBP"] + acc["SACFLY"]
    obp = _round3((h + acc["BB"] + acc["HBP"]) / obp_den) if obp_den else 0.0
    slg = _round3(tb / ab) if ab else 0.0
    ops = _round3(obp + slg)
    out = dict(acc)
    out.update({"PA": pa, "TB": tb, "AVG": avg, "OBP": obp, "SLG": slg, "OPS": ops})
    return out


def _finalize_pitcher(acc: dict) -> dict:
    outs = acc["OUT"]
    innings = outs / 3
    era = _round3(acc["ER"] * 9 / innings) if innings else 0.0
    whip = _round3((acc["H"] + acc["BB"]) / innings) if innings else 0.0
    k9 = _round3(acc["K"] * 9 / innings) if innings else 0.0
    bb9 = _round3(acc["BB"] * 9 / innings) if innings else 0.0
    out = dict(acc)
    out["IP"] = outs_to_innings_str(outs)
    out.update({"ERA": era, "WHIP": whip, "K9": k9, "BB9": bb9})
    return out


def _season_of(date_str: str) -> str:
    return date_str[:4]


def aggregate():
    files = sorted(glob.glob(os.path.join(HERE, "data_????????.json")))

    # season -> player_code -> acc
    season_batters: dict[str, dict[str, dict]] = defaultdict(dict)
    season_pitchers: dict[str, dict[str, dict]] = defaultdict(dict)
    career_batters: dict[str, dict] = {}
    career_pitchers: dict[str, dict] = {}

    used_files = 0
    for fp in files:
        with open(fp, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("round") not in REGULAR_ROUNDS:
            continue
        date_str = d.get("date") or os.path.basename(fp)[len("data_"):-len(".json")]
        season = _season_of(date_str.replace("-", ""))
        used_files += 1

        for row in d.get("batters", []):
            pc = row.get("player_code")
            if not pc:
                continue
            s = row["stat"]
            for bucket, table in ((season_batters[season], "season"), (career_batters, "career")):
                acc = bucket.setdefault(pc, _new_batter_acc())
                acc["name"] = row["name"]
                acc["team"] = row["team"]
                acc["player_code"] = pc
                acc["G"] += 1
                acc["AB"] += row.get("ab", 0)
                for k in BATTER_SUM_KEYS:
                    acc[k] += s.get(k, 0)

        for row in d.get("pitchers", []):
            pc = row.get("player_code")
            if not pc:
                continue
            s = row["stat"]
            for bucket, table in ((season_pitchers[season], "season"), (career_pitchers, "career")):
                acc = bucket.setdefault(pc, _new_pitcher_acc())
                acc["name"] = row["name"]
                acc["team"] = row["team"]
                acc["player_code"] = pc
                acc["G"] += 1
                if row.get("role") == "선발":
                    acc["GS"] += 1
                acc["OUT"] += s.get("OUT", 0)
                for k in PITCHER_SUM_KEYS:
                    acc[k] += s.get(k, 0)

    season_out = {}
    for season, table in season_batters.items():
        season_out.setdefault(season, {})["batters"] = [_finalize_batter(a) for a in table.values()]
    for season, table in season_pitchers.items():
        season_out.setdefault(season, {})["pitchers"] = [_finalize_pitcher(a) for a in table.values()]

    career_out = {
        "batters": [_finalize_batter(a) for a in career_batters.values()],
        "pitchers": [_finalize_pitcher(a) for a in career_pitchers.values()],
    }

    return season_out, career_out, used_files


def main():
    season_out, career_out, used_files = aggregate()

    with open(os.path.join(HERE, "season_stats.json"), "w", encoding="utf-8") as f:
        json.dump(season_out, f, ensure_ascii=False)
    with open(os.path.join(HERE, "career_stats.json"), "w", encoding="utf-8") as f:
        json.dump(career_out, f, ensure_ascii=False)

    seasons = sorted(season_out.keys())
    print(f"정규시즌 파일 {used_files}개 집계 완료. 시즌: {seasons}")
    print(f"통산 타자 {len(career_out['batters'])}명, 통산 투수 {len(career_out['pitchers'])}명")


if __name__ == "__main__":
    main()
