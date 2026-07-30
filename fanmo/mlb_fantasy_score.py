"""
MLB 판타지 라이브 포인트 계산기 (실험용)
==========================================
KBO용 naver_fantasy_score.py와 같은 네이버 스포츠 API를 쓰지만, MLB는 응답 스키마가
꽤 다르다:
  - recordData에 gameInfo/battersBoxscore가 없고, 대신 homeBatter/awayBatter/
    homePitcher/awayPitcher/homeKeyStat/awayKeyStat가 최상위에 바로 있다.
  - 타자 박스에 2루타/3루타/병살/희생플라이 등을 알 수 있는 타석별 코드(inn1~inn25)가
    아예 없다.

mlb_relay.py로 텍스트 중계(형식이 KBO와 달라 별도 파서)를 파싱해서 2루타/3루타/병살타/
희생플라이/진루타/도루실패/견제사(타자)와 피2루타/피3루타/도루허용/도루저지/견제사(투수),
실책(포지션→선발 라인업 정적 매핑, 중간 수비 교체는 못 따라감)까지 채운다.

여전히 못 채우는 항목(UNAVAILABLE) — MLB 중계엔 KBO의 currentGameState(매 이벤트마다
주자상태·스코어 스냅샷) 자체가 없어서 계산이 원천적으로 불가능하다:
  - 승계주자 실점 허용/막음, 세이브 기회 판정: 등판 시점의 점수차/주자 상황을 알아야 하는데
    MLB 중계는 그 스냅샷을 안 준다.
  - 보살/외야수 보살/병살·삼중살 가담: 아웃 처리에 KBO식 "(위치->위치 송구아웃)" 체인이 없다.
  - 포수 도루 저지/허용: 포지션 교체 문구 자체가 안 보여 포수를 동적으로 추적할 수 없다.
"""

from __future__ import annotations

import argparse
import json
from datetime import date

from naver_fantasy_score import BATTER_POINTS, PITCHER_POINTS, fetch_json, score_batter, score_pitcher
from mlb_relay import (
    build_starting_position_map, compute_relay_stats, fetch_full_relay,
)

SCHEDULE_URL = (
    "https://api-gw.sports.naver.com/schedule/games"
    "?fields=basic&upperCategoryId=wbaseball&categoryId=mlb"
    "&fromDate={date}&toDate={date}"
)
RECORD_URL = "https://api-gw.sports.naver.com/schedule/games/{game_id}/record"

UNAVAILABLE = [
    "ASSIST", "OF_ASSIST", "DP_FIELD", "TP_FIELD", "CS_CATCHER", "SB_ALLOWED_CATCHER",
    "INHERITED_SCORED", "INHERITED_STRANDED", "WP", "BK",
]


def fetch_schedule(date_str: str) -> list[dict]:
    return fetch_json(SCHEDULE_URL.format(date=date_str))["result"]["games"]


def fetch_record(game_id: str) -> dict:
    return fetch_json(RECORD_URL.format(game_id=game_id))["result"]["recordData"]


def innings_to_outs(inn: str) -> int:
    """MLB는 '6.2' 형태(소수부가 그 이닝에서의 아웃 수, 0~2)로 준다 — KBO의 ⅓/⅔ 기호와 다름."""
    s = str(inn or "0")
    if "." in s:
        whole, frac = s.split(".", 1)
        return int(whole or 0) * 3 + int(frac or 0)
    return int(s or 0) * 3


def process_game(game_id: str, schedule_entry: dict) -> tuple[list[dict], list[dict]]:
    rd = fetch_record(game_id)
    if not rd or (not rd.get("homeBatter") and not rd.get("homePitcher")):
        return [], []  # 경기 시작 전이라 아직 박스스코어가 없음

    is_final = schedule_entry.get("statusCode") == "RESULT"
    date_disp = schedule_entry["gameDate"]
    team_name = {"home": schedule_entry["homeTeamName"], "away": schedule_entry["awayTeamName"]}
    opp_name = {"home": schedule_entry["awayTeamName"], "away": schedule_entry["homeTeamName"]}

    batter_rows: list[dict] = []
    for side, key in (("home", "homeBatter"), ("away", "awayBatter")):
        for p in rd.get(key) or []:
            stat = {k: 0 for k in BATTER_POINTS}
            stat["CYCLE"] = False
            stat.update({
                "R": int(p.get("run") or 0), "H": int(p.get("hit") or 0),
                "BB": int(p.get("bb") or 0), "HR": int(p.get("hr") or 0),
                "RBI": int(p.get("rbi") or 0), "SB": int(p.get("sb") or 0),
                "HBP": int(p.get("hbp") or 0), "K": int(p.get("so") or 0),
            })
            for k in UNAVAILABLE:
                stat.setdefault(k, 0)
            batter_rows.append({
                "name": p.get("name", ""), "team": team_name[side], "opponent": opp_name[side],
                "date": date_disp, "stadium": "", "position": p.get("posName", ""),
                "position_override": False,
                "ab": int(p.get("ab") or 0), "stat": stat, "lp": score_batter(stat),
            })

    pitcher_rows: list[dict] = []
    team_outs = {
        side: sum(innings_to_outs(p.get("inn")) for p in (rd.get(key) or []))
        for side, key in (("home", "homePitcher"), ("away", "awayPitcher"))
    }
    for side, key in (("home", "homePitcher"), ("away", "awayPitcher")):
        plist = rd.get(key) or []
        for idx, p in enumerate(plist):
            outs = innings_to_outs(p.get("inn"))
            er = int(p.get("er") or 0)
            hit = int(p.get("hit") or 0)
            r = int(p.get("r") or 0)
            is_starter = idx == 0
            cg = bool(is_final and is_starter and outs > 0 and outs == team_outs[side])
            sho = cg and r == 0
            nohit = cg and hit == 0
            perfect = nohit and int(p.get("bb") or 0) == 0
            qsplus = bool(is_starter and outs >= 21 and er <= 3)
            qs = bool(is_starter and outs >= 18 and er <= 3 and not qsplus)
            wls = p.get("wls", "")

            stat = {k: 0 for k in PITCHER_POINTS}
            stat.update({
                "H": hit, "HR": int(p.get("hr") or 0), "ER": er, "BB": int(p.get("bb") or 0),
                "HBP": 0, "K": int(p.get("so") or 0), "OUT": outs,
                "QS": qs, "QSPLUS": qsplus,
                "HOLD": 1 if wls == "홀" else 0, "SAVE": 1 if wls == "세" else 0,
                "BLOWN": 1 if wls == "블" else 0,
                "PERFECT": perfect, "NOHIT": nohit, "SHO": sho, "CG": cg,
            })
            for k in UNAVAILABLE:
                stat.setdefault(k, 0)
            pitcher_rows.append({
                "name": p.get("name", ""), "team": team_name[side], "opponent": opp_name[side],
                "date": date_disp, "stadium": "", "inn": p.get("inn"),
                "role": "선발" if is_starter else "구원",
                "stat": stat, "lp": score_pitcher(stat),
            })

    _merge_relay(game_id, rd, batter_rows, pitcher_rows)
    return batter_rows, pitcher_rows


def _merge_relay(game_id: str, rd: dict, batter_rows: list[dict], pitcher_rows: list[dict]) -> None:
    """mlb_relay.py에서 뽑은 2루타/3루타/병살/희생플라이/진루타/도루실패/견제사(타자)와
    피2루타/피3루타/도루허용/도루저지/견제사(투수), 실책을 합쳐 LP를 재계산한다."""
    try:
        home_batters = rd.get("homeBatter") or []
        away_batters = rd.get("awayBatter") or []
        home_pitchers = rd.get("homePitcher") or []
        away_pitchers = rd.get("awayPitcher") or []
        if not home_batters and not home_pitchers:
            return

        events = fetch_full_relay(game_id)
        home_pos = build_starting_position_map(home_batters)
        away_pos = build_starting_position_map(away_batters)
        home_sp = home_pitchers[0]["name"] if home_pitchers else None
        away_sp = away_pitchers[0]["name"] if away_pitchers else None
        stats = compute_relay_stats(events, home_sp, away_sp, home_pos, away_pos)
    except Exception as exc:  # noqa: BLE001
        print(f"  {game_id} MLB 릴레이 조회 실패(기본 점수만 적용): {exc}")
        return

    batter_extra = stats["batter_extra"]
    pitcher_extra = stats["pitcher_extra"]
    error_credit = stats["error_credit"]

    for row in batter_rows:
        be = batter_extra.get(row["name"])
        changed = False
        if be:
            for key in ("2B", "3B", "GDP", "SACFLY", "CS", "PICKOFF", "GRANDSLAM"):
                if be.get(key):
                    row["stat"][key] += be[key]
                    changed = True
            if be.get("ADVANCE"):
                row["stat"]["SACBUNT"] = be["ADVANCE"]
                changed = True
        err = error_credit.get(row["name"])
        if err:
            row["stat"]["E"] += err
            changed = True
        if changed:
            hr = row["stat"]["HR"]
            row["stat"]["CYCLE"] = bool(
                row["stat"]["H"] - row["stat"]["2B"] - row["stat"]["3B"] - hr > 0
                and row["stat"]["2B"] > 0 and row["stat"]["3B"] > 0 and hr > 0
            )
            row["lp"] = score_batter(row["stat"])

    for row in pitcher_rows:
        pe = pitcher_extra.get(row["name"])
        if pe:
            for key in ("2B_A", "3B_A", "CS_A", "SB_A", "PICKOFF_A"):
                v = pe.get(key, 0)
                if not v:
                    continue
                stat_key = "SB_ALLOWED" if key == "SB_A" else key
                row["stat"][stat_key] += v
            row["lp"] = score_pitcher(row["stat"])


def collect_date(date_str: str) -> tuple[list[dict], list[dict]]:
    all_batters, all_pitchers = [], []
    for g in fetch_schedule(date_str):
        if g.get("statusCode") in ("READY", "BEFORE"):
            continue  # 경기 시작 전 (READY=곧 시작, BEFORE=아직 한참 남음)
        gid = g["gameId"]
        try:
            b, p = process_game(gid, g)
        except Exception as exc:  # noqa: BLE001
            print(f"  {gid} 처리 실패: {exc}")
            continue
        all_batters.extend(b)
        all_pitchers.extend(p)
    return all_batters, all_pitchers


def main():
    ap = argparse.ArgumentParser(description="MLB 판타지 라이브 포인트 계산기(실험용)")
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (생략 시 오늘)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    date_str = args.date or date.today().isoformat()
    print(f"{date_str} MLB 경기 목록 조회 중...")
    batters, pitchers = collect_date(date_str)
    batters.sort(key=lambda r: -r["lp"])
    pitchers.sort(key=lambda r: -r["lp"])

    if not batters and not pitchers:
        print("  아직 시작한 경기가 없습니다(전부 READY 상태).")
    else:
        print(f"  타자 {len(batters)}명, 투수 {len(pitchers)}명 처리 완료")

    out_path = args.out or f"data_mlb_{date_str.replace('-', '')}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"batters": batters, "pitchers": pitchers, "date": date_str, "league": "mlb"}, f, ensure_ascii=False)
    print(f"저장 완료: {out_path}")


if __name__ == "__main__":
    main()
