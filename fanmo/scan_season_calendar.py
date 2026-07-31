"""2025-03-01 ~ 2026-06-30 범위의 모든 날짜를 스캔해서, 그날 경기가 있었는지 및
roundCode(kbo_e=시범경기, kbo_r=정규시즌, kbo_as=올스타, 그 외=포스트시즌 등)를
확인해 season_calendar.json에 저장한다. 하루에 여러 경기가 있어도 그 날의 라운드는
전부 동일하므로(같은 날 시범경기와 정규시즌이 섞이지 않음), 첫 경기 하나만 상세조회해서
그 날짜 전체의 roundCode로 취급한다."""
import json
import os
import time
from datetime import date, timedelta

from naver_fantasy_score import fetch_schedule, fetch_json, GAME_URL

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_PATH = os.path.join(HERE, "season_calendar.json")

START = date(2025, 3, 1)
END = date(2026, 6, 30)


def main():
    result = {}
    if os.path.exists(OUT_PATH):
        with open(OUT_PATH, encoding="utf-8") as f:
            result = json.load(f)

    d = START
    n = 0
    while d <= END:
        ds = d.isoformat()
        if ds in result:
            d += timedelta(days=1)
            continue
        try:
            games = fetch_schedule(ds)
        except Exception as exc:
            print(f"{ds} 일정 조회 실패: {exc}")
            d += timedelta(days=1)
            continue
        games = [g for g in games if not g.get("cancel")]
        if not games:
            result[ds] = {"round": None, "game_ids": []}
        else:
            gid0 = games[0]["gameId"]
            try:
                detail = fetch_json(GAME_URL.format(game_id=gid0))["result"]["game"]
                round_code = detail.get("roundCode")
            except Exception as exc:
                print(f"{ds} 라운드 조회 실패({gid0}): {exc}")
                round_code = None
            result[ds] = {
                "round": round_code,
                "game_ids": [g["gameId"] for g in games],
            }
        n += 1
        if n % 20 == 0:
            print(f"...{ds}까지 처리, 저장 중")
            with open(OUT_PATH, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=1)
        d += timedelta(days=1)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print("완료:", OUT_PATH)

    rounds = {}
    for ds, info in sorted(result.items()):
        rc = info["round"]
        rounds.setdefault(rc, []).append(ds)
    for rc, dates in rounds.items():
        print(rc, len(dates), dates[0], "~", dates[-1])


if __name__ == "__main__":
    main()
