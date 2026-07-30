"""
타자 포지션(수비 기록 기반) 추적기
====================================
9UP 판타지 모드는 "최근 2주간 수비 기록"으로 타자의 기본 포지션(및 코스트)을 책정하고,
이후 유저가 임의로 포지션을 재지정할 수 있다고 한다. 이 모듈은:

  1. 지정한 종료일 기준 최근 N일(기본 14일)의 KBO 경기 박스스코어를 모아
     선수별로 "포지션별 수비 이닝"을 추정 집계한다 (auto_position).
  2. position_db.json에 저장하고, 이미 저장된 manual_position(수동 재지정)은
     재집계 시에도 덮어쓰지 않고 보존한다.
  3. effective_position = manual_position이 있으면 그것, 없으면 auto_position.

데이터 한계
----------
네이버 박스스코어는 "그 경기에서 뛴 포지션 문자열"만 준다(예: '유'=유격수 단독출전,
'좌중'=좌익수로 시작해 중견수로 수비 위치 변경). 포지션별 정확한 "이닝 시각"은 내려주지
않으므로, 한 경기에 포지션이 여러 개면 그 경기의 수비 이닝(=자기 팀 투수 이닝)을 해당
포지션 개수로 균등 분배해 근사한다. 지(지명타자)/타(대타)/주(대주자)는 수비 포지션이
아니므로 이닝 집계에서 제외한다(둘 다 없이 경기를 마쳤다면 지명타자로 분류).
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import date, datetime, timedelta

from naver_fantasy_score import fetch_schedule, fetch_record, innings_to_outs

DB_PATH = os.path.join(os.path.dirname(__file__), "position_db.json")

FIELDING_CHARS = {
    "一": "1루수", "二": "2루수", "三": "3루수", "유": "유격수",
    "좌": "좌익수", "중": "중견수", "우": "우익수", "포": "포수",
}
FIELDING_POSITIONS = list(FIELDING_CHARS.values())
NON_FIELDING = {"지": "지명타자", "타": "대타", "주": "대주자"}
ALL_POSITIONS = FIELDING_POSITIONS + ["지명타자"]

POSITION_GROUPS = {
    "포수": ["포수"],
    "1루수": ["1루수"],
    "2루수": ["2루수"],
    "3루수": ["3루수"],
    "유격수": ["유격수"],
    "좌익수": ["좌익수"],
    "중견수": ["중견수"],
    "우익수": ["우익수"],
    "지명타자": ["지명타자"],
}


def _fielding_chars(pos_str: str) -> list[str]:
    return [c for c in (pos_str or "") if c in FIELDING_CHARS]


def collect_position_window(end_date_str: str, days: int = 14) -> dict:
    """playerCode -> {name, team, innings: {position: float}, dh_games, games}"""
    end = datetime.strptime(end_date_str, "%Y-%m-%d").date()
    players: dict = {}

    for i in range(days):
        d = (end - timedelta(days=i)).isoformat()
        try:
            games = fetch_schedule(d)
        except Exception as exc:  # noqa: BLE001
            print(f"  {d} 일정 조회 실패: {exc}")
            continue
        for g in games:
            if g.get("statusCode") != "RESULT":
                continue  # 종료된 경기만 집계 (진행 중/예정 경기는 표본 불안정)
            gid = g["gameId"]
            try:
                rd = fetch_record(gid)
            except Exception as exc:  # noqa: BLE001
                print(f"  {gid} 기록 조회 실패: {exc}")
                continue

            info = rd.get("gameInfo", {})
            team_name = {"home": info.get("hName", ""), "away": info.get("aName", "")}
            team_pb = rd.get("teamPitchingBoxscore", {})
            bb = rd.get("battersBoxscore", {})

            for side in ("home", "away"):
                def_innings = innings_to_outs((team_pb.get(side) or {}).get("inn")) / 3
                for p in bb.get(side, []):
                    code = p.get("playerCode")
                    if not code:
                        continue
                    rec = players.setdefault(code, {
                        "name": p.get("name", ""), "team": team_name[side],
                        "innings": defaultdict(float), "dh_games": 0, "games": 0,
                    })
                    rec["team"] = team_name[side]
                    rec["games"] += 1
                    fchars = _fielding_chars(p.get("pos", ""))
                    if fchars:
                        share = (def_innings / len(fchars)) if def_innings else 0.0
                        for c in fchars:
                            rec["innings"][FIELDING_CHARS[c]] += share
                    else:
                        rec["dh_games"] += 1
    return players


def auto_position(rec: dict) -> str:
    innings = rec.get("innings") or {}
    if innings:
        return max(innings.items(), key=lambda kv: kv[1])[0]
    if rec.get("dh_games", 0) > 0:
        return "지명타자"
    return "미상"


def load_db() -> dict:
    if os.path.exists(DB_PATH):
        with open(DB_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"as_of": None, "window_days": 14, "players": {}}


def save_db(db: dict) -> None:
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


def build_position_db(end_date_str: str, days: int = 14) -> dict:
    """최근 N일 수비 기록으로 auto_position을 재계산하되, 기존 manual_position은 보존."""
    existing = load_db()
    existing_players = existing.get("players", {})

    window = collect_position_window(end_date_str, days=days)

    players_out = {}
    for code, rec in window.items():
        prev = existing_players.get(code, {})
        auto_pos = auto_position(rec)
        manual = prev.get("manual_position")
        players_out[code] = {
            "name": rec["name"],
            "team": rec["team"],
            "innings_by_position": {k: round(v, 1) for k, v in rec["innings"].items()},
            "games": rec["games"],
            "auto_position": auto_pos,
            "manual_position": manual,
            "effective_position": manual or auto_pos,
        }

    # 이번 윈도우에 출전 기록이 없던(부상/이적/트레이드 등) 기존 선수도 manual override는 유지
    for code, prev in existing_players.items():
        if code not in players_out and prev.get("manual_position"):
            players_out[code] = prev

    db = {"as_of": end_date_str, "window_days": days, "players": players_out}
    save_db(db)
    return db


def set_manual_position(player_code: str, new_position: str | None) -> dict:
    """new_position=None 이면 수동 지정 해제(자동 산정값으로 복귀)."""
    db = load_db()
    rec = db["players"].get(player_code)
    if rec is None:
        raise KeyError(f"알 수 없는 playerCode: {player_code}")
    rec["manual_position"] = new_position
    rec["effective_position"] = new_position or rec["auto_position"]
    save_db(db)
    return rec


def find_players_by_name(name: str) -> list[tuple[str, dict]]:
    db = load_db()
    return [(code, rec) for code, rec in db["players"].items() if name in rec["name"]]


def _cli():
    import argparse

    ap = argparse.ArgumentParser(description="타자 포지션(2주 수비 기록) 집계기")
    ap.add_argument("--end-date", required=True, help="YYYY-MM-DD (이 날짜까지 최근 N일 집계)")
    ap.add_argument("--days", type=int, default=14)
    args = ap.parse_args()

    print(f"{args.end_date} 기준 최근 {args.days}일 수비 기록 수집 중...")
    db = build_position_db(args.end_date, days=args.days)
    print(f"선수 {len(db['players'])}명 집계 완료 → {DB_PATH}")


if __name__ == "__main__":
    _cli()
