"""동명이인 확인용 조회 스크립트.

9UP 앱 스크린샷에서 이름이 같은 선수가 여럿 나오면, 코스트 CSV에 player_code로
구분해서 적어 넣어야 한다(README: fanmo_cost.py 상단 설명 참고). 그때마다 매번
data_*.json을 손으로 뒤지지 않도록, 이름 하나를 던지면 그 이름으로 실제 경기에
등장한 모든 player_code 후보와 구분에 쓸 만한 단서(팀, 포지션/등판 역할, 등장
횟수·기간)를 한 번에 뽑아준다.

사용법:
    python identify_player.py 이승현
    python identify_player.py 이승현 김태훈 박준영   # 여러 명 한 번에
"""
from __future__ import annotations

import argparse
import glob
import json
from collections import Counter, defaultdict

HERE_GLOB = "data_????????.json"


def collect(names: set[str]) -> dict:
    # name -> player_code -> {"teams": Counter, "batter_pos": Counter, "pitcher_role": Counter,
    #                          "is_batter": bool, "is_pitcher": bool, "dates": [str, ...]}
    info: dict = defaultdict(lambda: defaultdict(lambda: {
        "teams": Counter(), "batter_pos": Counter(), "pitcher_role": Counter(),
        "is_batter": False, "is_pitcher": False, "dates": [],
    }))

    files = sorted(glob.glob(HERE_GLOB))
    for fp in files:
        with open(fp, encoding="utf-8") as f:
            d = json.load(f)
        date = d.get("date") or fp
        for row in d.get("batters", []):
            if row["name"] not in names:
                continue
            pc = row.get("player_code") or "(없음)"
            rec = info[row["name"]][pc]
            rec["is_batter"] = True
            rec["teams"][row["team"]] += 1
            rec["batter_pos"][row.get("position") or row.get("pos") or "?"] += 1
            rec["dates"].append(date)
        for row in d.get("pitchers", []):
            if row["name"] not in names:
                continue
            pc = row.get("player_code") or "(없음)"
            rec = info[row["name"]][pc]
            rec["is_pitcher"] = True
            rec["teams"][row["team"]] += 1
            rec["pitcher_role"][row.get("role") or "?"] += 1
            rec["dates"].append(date)

    return info


def report(info: dict) -> None:
    for name, by_code in info.items():
        print(f"\n=== {name} ===")
        if not by_code:
            print("  실제 경기 데이터에 등장한 적 없음")
            continue
        for pc, rec in sorted(by_code.items(), key=lambda kv: -len(kv[1]["dates"])):
            dates = sorted(rec["dates"])
            kind = "타자" if rec["is_batter"] and not rec["is_pitcher"] else \
                   "투수" if rec["is_pitcher"] and not rec["is_batter"] else "타자+투수(!)"
            teams = ", ".join(f"{t}({c})" for t, c in rec["teams"].most_common())
            print(f"  player_code={pc:8s} [{kind}] 팀={teams} 경기수={len(dates)} "
                  f"최초={dates[0]} 최근={dates[-1]}")
            if rec["batter_pos"]:
                pos = ", ".join(f"{p}={c}" for p, c in rec["batter_pos"].most_common())
                print(f"    수비 위치: {pos}")
            if rec["pitcher_role"]:
                role = ", ".join(f"{r}={c}" for r, c in rec["pitcher_role"].most_common())
                print(f"    등판 역할: {role}")
        if len(by_code) > 1:
            print("  -> player_code가 여럿이면 동명이인. 팀/포지션/등판 역할/등장 기간으로")
            print("     실제 어느 스크린샷 속 사람인지 판단해서 fanmo260901.csv의 '동명'에 적어 넣는다.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("names", nargs="+", help="조회할 선수 이름(여러 개 가능)")
    args = ap.parse_args()

    info = collect(set(args.names))
    report(info)


if __name__ == "__main__":
    main()
