"""
기존 data_YYYYMMDD.json 전부에 fanmo_cost 필드를 추가한다(재수집 없이, 이미 저장된
행에 코스트만 덧붙임). LP 점수 계산 로직은 전혀 건드리지 않으므로 재조정(reconcile)
검증이 필요 없다 — 순수 추가 필드다.

사용법: python backfill_fanmo_cost.py
"""
import glob
import json
import re

from fanmo_cost import lookup_batter_cost, lookup_pitcher_cost


def backfill_file(path: str, date_str: str | None) -> tuple[int, int]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    matched = 0
    total = 0
    for row in data.get("batters", []):
        total += 1
        cost = lookup_batter_cost(row.get("name", ""), row.get("team", ""), row.get("position", ""), date_str)
        row["fanmo_cost"] = cost
        if cost is not None:
            matched += 1
    for row in data.get("pitchers", []):
        total += 1
        cost = lookup_pitcher_cost(row.get("name", ""), row.get("team", ""), date_str)
        row["fanmo_cost"] = cost
        if cost is not None:
            matched += 1

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return matched, total


def main():
    files = sorted(glob.glob("data_[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].json"))
    grand_matched = grand_total = 0
    for path in files:
        m = re.search(r"data_(\d{8})\.json$", path)
        date_str = m.group(1) if m else None
        matched, total = backfill_file(path, date_str)
        grand_matched += matched
        grand_total += total
    print(f"{len(files)}개 파일 처리 완료, 총 {grand_matched}/{grand_total}행 코스트 매칭")


if __name__ == "__main__":
    main()
