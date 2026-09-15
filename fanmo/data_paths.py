"""data_YYYYMMDD.json(경기별 수집 데이터) 저장 위치를 한 곳에서 관리한다.

예전엔 fanmo/ 폴더 바로 밑에 전부 평평하게 쌓아서(2005~2026년치 1,000개 넘는 파일)
폴더가 지저분했다 — 지금은 fanmo/data/<연도>/data_YYYYMMDD.json 형태로 연도별
하위 폴더에 정리한다. 배포되는 GitHub Pages 사이트(lp_board.html의 클라이언트 JS가
같은 폴더에서 'data_20260915.json'을 그대로 fetch함)에는 영향이 없다 — 배포 스텝에서
이 연도별 폴더 안의 파일들을 전부 _site/ 바로 밑으로 평평하게 복사하기 때문이다
(.github/workflows/fantasy-lp-board.yml 참고). 즉 이 폴더 구조 변경은 저장소 안에서만
보이고, 실제 사이트 동작이나 클라이언트 코드는 하나도 안 바꿔도 된다.

이 모듈을 쓰는 모든 스크립트(daily_pipeline.py, build_board.py, build_stats.py,
detect_errors.py, 각종 backfill/reprocess 스크립트 등)는 fname_for()로 경로를 계산하고,
목록이 필요하면 glob_data_files()를 쓴다 — 절대 os.path.join(HERE, f"data_{...}.json")를
직접 쓰지 않는다.
"""
from __future__ import annotations

import glob
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")


def fname_for(date_str: str) -> str:
    """date_str은 'YYYY-MM-DD' 또는 'YYYYMMDD' 둘 다 받는다. 연도별 하위 폴더를
    필요하면 만들고, 그 안의 data_YYYYMMDD.json 전체 경로를 돌려준다."""
    compact = date_str.replace("-", "")
    year = compact[:4]
    year_dir = os.path.join(DATA_DIR, year)
    os.makedirs(year_dir, exist_ok=True)
    return os.path.join(year_dir, f"data_{compact}.json")


def glob_data_files() -> list[str]:
    """모든 연도 폴더를 통틀어 data_YYYYMMDD.json 전체를 날짜순으로 정렬해 돌려준다."""
    pattern = os.path.join(DATA_DIR, "*", "data_????????.json")
    return sorted(glob.glob(pattern))


_DATE_RE = re.compile(r"data_(\d{8})\.json$")


def date_of(path: str) -> str:
    """파일 경로에서 'YYYY-MM-DD' 날짜 문자열을 뽑아낸다."""
    m = _DATE_RE.search(path)
    if not m:
        raise ValueError(f"data_YYYYMMDD.json 형식이 아닙니다: {path}")
    d = m.group(1)
    return f"{d[0:4]}-{d[4:6]}-{d[6:8]}"
