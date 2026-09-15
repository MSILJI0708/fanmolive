"""보살(ASSIST/OF_ASSIST) 규칙이 바뀌어서 기존에 수집해둔 날짜 전부를 다시 계산한다.
이미 있는 data_YYYYMMDD.json 파일들을 전부 찾아 collect_date로 재수집 후 덮어쓴다.
포지션 DB는 기존 스냅샷을 그대로 재사용(백필 때와 동일한 방침)."""
import json
import os

from data_paths import glob_data_files
from naver_fantasy_score import collect_date, load_position_map

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    files = glob_data_files()
    for fp in files:
        date_compact = os.path.basename(fp)[len("data_"):-len(".json")]
        date_str = f"{date_compact[0:4]}-{date_compact[4:6]}-{date_compact[6:8]}"
        # 날짜별로 그때그때 맞는 포지션 맵을 쓴다(9/13 이전은 9/1 스냅샷) — 그냥 한 번만
        # 로드해서 전체 날짜에 재사용하면, 최근 갱신된 "지금" 포지션이 옛날 데이터에도
        # 잘못 덮어씌워진다(naver_fantasy_score.load_position_map 참고).
        position_map = load_position_map(date_str)
        print(f"[{date_str}] 재수집 시작...")
        batters, pitchers = collect_date(date_str, position_map=position_map)
        batters.sort(key=lambda r: -r["lp"])
        pitchers.sort(key=lambda r: -r["lp"])
        with open(fp, "w", encoding="utf-8") as f:
            json.dump({"batters": batters, "pitchers": pitchers, "date": date_str}, f, ensure_ascii=False)
        print(f"[{date_str}] 저장 완료: 타자 {len(batters)}명, 투수 {len(pitchers)}명")

    print("=== 전체 재수집 완료 ===")


if __name__ == "__main__":
    main()
