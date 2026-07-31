"""전체 수집된 날짜에서, "홈런" etcRecords 한 줄에 선수가 2명 이상 묶여 나온 경기 중
구버전 _HR_RE(단일 매치)로 파싱했을 때와 신버전 _HR_ITEM_RE(findall)로 파싱했을 때
grand_slam_batters 결과가 달라지는(즉 만루홈런이 누락됐던) 날짜를 찾는다."""
import glob
import json
import os
import re

from naver_fantasy_score import fetch_record, fetch_schedule, _HR_ITEM_RE

HERE = os.path.dirname(os.path.abspath(__file__))
_OLD_HR_RE = re.compile(r"^(.+?)(\d+)호\((\d+)회(\d+)점\s*(.*?)\)$")


def old_parse(result: str) -> set:
    m = _OLD_HR_RE.match(result)
    if m and m.group(4) == "4":
        return {m.group(1).strip()}
    return set()


def new_parse(result: str) -> set:
    return {name for name, _hr_nos, points_blob in _HR_ITEM_RE.findall(result) if "4점" in points_blob}


def main():
    file_dates = []
    for fp in sorted(glob.glob(os.path.join(HERE, "data_????????.json"))):
        dc = os.path.basename(fp)[len("data_"):-len(".json")]
        file_dates.append(f"{dc[0:4]}-{dc[4:6]}-{dc[6:8]}")

    calendar = {}
    cal_path = os.path.join(HERE, "season_calendar.json")
    if os.path.exists(cal_path):
        with open(cal_path, encoding="utf-8") as f:
            calendar = json.load(f)

    affected = []
    checked_games = 0
    for ds in file_dates:
        game_ids = (calendar.get(ds) or {}).get("game_ids")
        if not game_ids:
            try:
                game_ids = [g["gameId"] for g in fetch_schedule(ds) if not g.get("cancel")]
            except Exception as exc:
                print(f"{ds} 일정 조회 실패: {exc}")
                continue
        for gid in game_ids:
            try:
                rd = fetch_record(gid)
            except Exception as exc:
                print(f"  {gid} 조회 실패: {exc}")
                continue
            checked_games += 1
            for e in rd.get("etcRecords", []) or []:
                if e.get("how") != "홈런":
                    continue
                result = (e.get("result") or "").strip()
                old = old_parse(result)
                new = new_parse(result)
                if old != new:
                    print(f"AFFECTED {ds} {gid}: old={old} new={new} raw={result!r}")
                    affected.append((ds, gid, sorted(new)))

    print(f"검사한 경기 수: {checked_games}")
    print(f"영향받은 날짜: {sorted(set(ds for ds, _, _ in affected))}")
    with open(os.path.join(HERE, "grandslam_bug_affected.json"), "w", encoding="utf-8") as f:
        json.dump(affected, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
