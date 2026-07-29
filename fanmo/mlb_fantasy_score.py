"""
MLB 판타지 라이브 포인트 계산기 (실험용)
==========================================
KBO용 naver_fantasy_score.py와 같은 네이버 스포츠 API를 쓰지만, MLB는 응답 스키마가
꽤 다르다:
  - recordData에 gameInfo/battersBoxscore가 없고, 대신 homeBatter/awayBatter/
    homePitcher/awayPitcher/homeKeyStat/awayKeyStat가 최상위에 바로 있다.
  - 타자 박스에 2루타/3루타/병살/희생플라이 등을 알 수 있는 타석별 코드(inn1~inn25)가
    아예 없다. KBO에서 쓴 relay(텍스트 중계)도 형식이 완전히 달라(문장이 <br/>로 이어
    붙은 하나의 블롭이라 이닝별 주자 상태를 못 읽음) 아직 파싱하지 않았다.
  - 그래서 이 모듈은 박스스코어에서 "확실히 뽑히는" 항목만 채운다: 득점/안타/볼넷/홈런/
    타점/도루/사구/삼진(타자), 피안타/피홈런/자책/볼넷/삼진/아웃카운트/QS/QS+/완투/완봉/
    노히트/퍼펙트/홀드/세이브/블론(투수, wls 표기가 KBO와 동일한 '홀'/'세'/'블'이라 그대로
    재사용). 2루타/3루타/병살/희생플라이/사이클/만루홈런/도루실패/견제사/보살류/포수 도루
    저지·허용/투수 피장타·승계주자는 전부 0으로 비워두고 아래 UNAVAILABLE 목록에 남긴다.

이 실험이 잘 되면 다음 단계는 MLB relay 포맷을 별도로 분석해 KBO relay.py에 준하는
파서를 만드는 것이다.
"""

from __future__ import annotations

import argparse
import json
from datetime import date

from naver_fantasy_score import BATTER_POINTS, PITCHER_POINTS, fetch_json, score_batter, score_pitcher

SCHEDULE_URL = (
    "https://api-gw.sports.naver.com/schedule/games"
    "?fields=basic&upperCategoryId=wbaseball&categoryId=mlb"
    "&fromDate={date}&toDate={date}"
)
RECORD_URL = "https://api-gw.sports.naver.com/schedule/games/{game_id}/record"

UNAVAILABLE = [
    "2B", "3B", "GDP", "SACFLY", "SACBUNT", "CS", "PICKOFF", "CYCLE", "GRANDSLAM", "E",
    "ASSIST", "OF_ASSIST", "DP_FIELD", "TP_FIELD", "CS_CATCHER", "SB_ALLOWED_CATCHER",
    "2B_A", "3B_A", "INHERITED_SCORED", "INHERITED_STRANDED", "CS_A", "SB_ALLOWED", "PICKOFF_A",
    "WP", "BK",
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
            stat = {k: 0 for k in UNAVAILABLE}
            stat.update({
                "R": int(p.get("run") or 0), "H": int(p.get("hit") or 0),
                "BB": int(p.get("bb") or 0), "HR": int(p.get("hr") or 0),
                "RBI": int(p.get("rbi") or 0), "SB": int(p.get("sb") or 0),
                "HBP": int(p.get("hbp") or 0), "K": int(p.get("so") or 0),
                "FO": 0, "GO": 0,
            })
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

            stat = {k: 0 for k in UNAVAILABLE}
            stat.update({
                "H": hit, "HR": int(p.get("hr") or 0), "ER": er, "BB": int(p.get("bb") or 0),
                "HBP": 0, "K": int(p.get("so") or 0), "OUT": outs,
                "QS": qs, "QSPLUS": qsplus,
                "HOLD": 1 if wls == "홀" else 0, "SAVE": 1 if wls == "세" else 0,
                "BLOWN": 1 if wls == "블" else 0,
                "PERFECT": perfect, "NOHIT": nohit, "SHO": sho, "CG": cg,
            })
            pitcher_rows.append({
                "name": p.get("name", ""), "team": team_name[side], "opponent": opp_name[side],
                "date": date_disp, "stadium": "", "inn": p.get("inn"),
                "role": "선발" if is_starter else "구원",
                "stat": stat, "lp": score_pitcher(stat),
            })

    return batter_rows, pitcher_rows


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
