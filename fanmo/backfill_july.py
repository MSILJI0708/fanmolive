"""2026년 7월 한 달치 KBO 판타지 LP 데이터를 한 번에 채워 넣는 백필 스크립트.
포지션 DB는 이미 있는 걸(position_db.json, 최근 자동화가 계속 갱신해온 스냅샷) 그대로
재사용하고(매일 새로 14일치를 다시 집계하면 너무 느려서), 날짜별로 data_YYYYMMDD.json만
새로 만든다. 이미 있는 날짜(그날 데이터가 이미 존재)는 건드리지 않고 건너뛴다.
"""
import json
import os
from datetime import date, timedelta

from naver_fantasy_score import collect_date, fetch_schedule, load_position_map

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    position_map = load_position_map()
    print(f"포지션 맵 {len(position_map)}명 로드 완료 (기존 position_db.json 재사용)")

    d = date(2026, 7, 1)
    end = date(2026, 7, 27)  # 28은 이미 있고, 29는 별도로 아래서 처리, 30은 실시간 자동화가 관리 중
    dates = [d + timedelta(days=i) for i in range((end - d).days + 1)]
    dates.append(date(2026, 7, 29))

    for d in dates:
        date_str = d.isoformat()
        out_path = os.path.join(HERE, f"data_{date_str.replace('-', '')}.json")
        if os.path.exists(out_path):
            print(f"[skip] {date_str} 이미 존재")
            continue
        try:
            games = fetch_schedule(date_str)
        except Exception as exc:  # noqa: BLE001
            print(f"[{date_str}] 일정 조회 실패: {exc}")
            continue
        if not games:
            print(f"[{date_str}] 경기 없음(휴식일)")
            continue
        print(f"[{date_str}] {len(games)}경기 수집 시작...")
        batters, pitchers = collect_date(date_str, position_map=position_map)
        batters.sort(key=lambda r: -r["lp"])
        pitchers.sort(key=lambda r: -r["lp"])
        if not batters and not pitchers:
            print(f"[{date_str}] 수집된 데이터 없음(전부 처리 실패이거나 취소된 경기)")
            continue
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({"batters": batters, "pitchers": pitchers, "date": date_str}, f, ensure_ascii=False)
        print(f"[{date_str}] 저장 완료: 타자 {len(batters)}명, 투수 {len(pitchers)}명 -> {out_path}")

    print("=== 7월 백필 완료 ===")


if __name__ == "__main__":
    main()
