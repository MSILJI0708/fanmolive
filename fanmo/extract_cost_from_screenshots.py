"""9UP 앱 "선수 교체" 화면 스크린샷에서 코스트(카드 아래 금색 별 1~5개)를 뽑아낸다.

배경: 코스트는 카드 아래 큰 초록 숫자가 아니라 별 개수다(실측 확인 완료 — 오스틴/디아즈
=5별, 김태연=4별, 문정빈/블레인=3별, 세베리노/오태곤=2별, fanmo260901.csv와 정확히 일치).
포지션 자동 캡쳐(daily_position_capture.ps1/analyze_position_screenshots.py)가 이미 매일
같은 스크린샷을 찍어두므로, 새로 캡쳐할 필요 없이 그 사진을 재사용한다.

별 세는 방법: 이름표 띠 바로 위(코스트 UI 위치는 화면 레이아웃상 고정)에서 금색 픽셀이
연속으로 붙어 있는 구간(run)을 찾는다 — 별 사이 간격이 좁아서 픽셀 임계값으로는 별 하나
하나가 분리되지 않고 카드당 하나의 연속 run으로 뭉친다(실측: 5별 run 폭 158~159px,
4별 128px, 3별 97px → 별 1개당 약 32px). 그래서 "별 개수"가 아니라 "run 폭 / 32를
반올림"으로 센다. 카드별 컬럼 경계를 미리 고정하지 않고 run 자체를 카드 단위로 삼는
이유: 실측해보니 카드 폭이 정확히 균등(전체폭/6)하지 않아서(약 297px로 가정했더니 옆
카드 별이 섞여 들어옴) 고정 컬럼 나누기보다 훨씬 안정적이다.

이름은 기존 analyze_position_screenshots.py와 같은 방식(행 전체를 한 줄로 psm7 OCR)으로
뽑고, 그 왼쪽->오른쪽 토큰 순서를 별 run의 왼쪽->오른쪽 순서와 그대로 짝짓는다. 토큰
개수와 run 개수가 다르면(OCR이 이름 하나를 놓쳤거나 노이즈를 하나 더 만든 경우) 그 행은
안전하게 건너뛴다 — 잘못 짝지어서 엉뚱한 선수에게 코스트를 매기는 것보다는 낫다.

선수명 -> player_code 매칭은 position_db.json(타자) + 최근 수집된 data_*.json 몇 개를
스캔해서 만든 이름-코드 인덱스(타자+투수 전부 커버)를 합쳐서 쓴다. 이름이 겹치는
동명이인이면(같은 포지션 폴더 안에 코드가 여러 개) 스스로 못 정하니 건너뛴다 — 그러면
나중에 fanmo_cost.py CSV의 '동명' 칸에 수동으로 player_code를 채워야 한다(기존 방식과
동일).

이 스크립트는 아직 fanmo_cost.py의 CSV/SNAPSHOTS를 직접 건드리지 않는다 — 추출 결과만
출력(및 JSON 저장)한다. 실제 코스트 갱신일(매달 1일/16일)에 이 스크립트로 뽑은 결과를
사람이 한 번 확인한 뒤 새 스냅샷 CSV로 반영하는 것을 권장한다(라이브 판타지 스코어링에
쓰이는 파일이라 자동 반영은 신중해야 함).

사용법: python extract_cost_from_screenshots.py [스크린샷_날짜_폴더]
  (생략 시 daily_position_capture.ps1이 오늘 만든 폴더를 자동으로 찾는다)
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys
from collections import defaultdict

from analyze_position_screenshots import (
    FOLDER_TO_POSITION,
    _CARD_LEFT,
    _CARD_RIGHT,
    _ROW_TOPS,
    _check_deps,
    _fuzzy_correct,
    _ocr_row,
)

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SCREENSHOT_ROOT = r"C:\Users\HUI\OneDrive\문서\XuanZhi9\Pictures\Screenshots"

# 코스트 UI(별)는 이름표 띠보다 위에 있고, 실측으로 확인한 상대 오프셋은 고정이다
# (이름표 top - 75 = 별 띠 top, 별 띠 높이 30px).
_STAR_OFFSET_Y = 75
_STAR_HEIGHT = 30
_PX_PER_STAR = 32  # 실측: 5별 run≈159px, 4별≈128px, 3별≈97px → 약 32px/별

# CSV(fanmo_cost.py)에서 쓰는 포지션 표기로 변환
FOLDER_TO_CSV_POS = {
    "1b": "1B", "2b": "2B", "3b": "3B", "ss": "SS", "c": "C",
    "lf": "LF", "cf": "CF", "rf": "RF", "dh": "DH",
    "p": "SP", "rp": "P",
}


def _is_gold(px, x, y) -> bool:
    r, g, b = px[x, y][:3]
    return r > 150 and g > 100 and b < 100 and r > b + 60


def _find_star_runs(img, top: int) -> list[tuple[int, int]]:
    """이름표 띠 top을 기준으로 그 위 별 띠에서 금색 픽셀이 연속인 x구간(run)들을 찾는다."""
    px = img.convert("RGB").load()
    star_top = top - _STAR_OFFSET_Y
    star_bottom = star_top + _STAR_HEIGHT
    col_has_gold = []
    for x in range(_CARD_LEFT, _CARD_RIGHT):
        has = any(_is_gold(px, x, y) for y in range(star_top, star_bottom))
        col_has_gold.append(has)

    runs = []
    start = None
    for i, v in enumerate(col_has_gold):
        if v and start is None:
            start = i
        if not v and start is not None:
            runs.append((start + _CARD_LEFT, i + _CARD_LEFT))
            start = None
    if start is not None:
        runs.append((start + _CARD_LEFT, len(col_has_gold) + _CARD_LEFT))
    return runs


def _stars_from_run(run: tuple[int, int]) -> int:
    width = run[1] - run[0]
    n = round(width / _PX_PER_STAR)
    return max(1, min(5, n))


_NAME_RE = re.compile(r"^[가-힣]{2,5}$")
_NOISE = {"교체", "필터", "시너지", "희귀도", "제한", "지난", "경기", "평균", "선수"}


def _ocr_row_names(img, top: int) -> list[str]:
    text = _ocr_row(img, top)
    names = []
    for token in text.split():
        token = token.strip("_|-— ")
        if token and token not in _NOISE and _NAME_RE.match(token):
            names.append(token)
    return names


def extract_costs(image_path: str) -> list[tuple[str, int]]:
    """(이름, 별개수) 리스트. 한 줄(행) 안에서 이름 토큰 수와 별 run 수가 다르면
    그 행은 안전하게 건너뛴다(짝을 잘못 맞추는 것보다 낫다)."""
    from PIL import Image

    img = Image.open(image_path)
    out = []
    for top in _ROW_TOPS:
        names = _ocr_row_names(img, top)
        runs = _find_star_runs(img, top)
        if len(names) != len(runs):
            print(f"    [skip] {os.path.basename(image_path)} row(top={top}): "
                  f"이름 {len(names)}개 vs 별묶음 {len(runs)}개 — 개수 불일치, 건너뜀")
            continue
        for name, run in zip(names, runs):
            out.append((name, _stars_from_run(run)))
    return out


def _build_name_code_index() -> dict[str, set[str]]:
    """이름 -> {player_code, ...}. position_db.json(타자) + 최근 데이터 파일(타자+투수)
    스캔 결과를 합친다(투수는 position_db.json에 없어서 보강 필요)."""
    from data_paths import glob_data_files
    from position import load_db

    index: dict[str, set[str]] = defaultdict(set)
    db = load_db()
    for code, rec in db["players"].items():
        index[rec["name"]].add(code)

    files = glob_data_files()
    for fp in files[-60:]:  # 최근 60개 파일이면 현재 등록 선수 대부분 커버
        try:
            with open(fp, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        for rec in d.get("batters", []) + d.get("pitchers", []):
            name = rec.get("name")
            code = rec.get("player_code")
            if name and code:
                index[name].add(code)
    return index


def resolve_codes(costs: list[tuple[str, int]], name_index: dict[str, set[str]]):
    """(이름, 별개수) -> (player_code, 별개수). 동명이인(코드 2개 이상)이거나 아예
    매칭 안 되면 unresolved에 넣고 건너뛴다."""
    resolved = []
    unresolved = []
    for name, stars in costs:
        codes = name_index.get(name)
        if not codes:
            unresolved.append((name, stars, "매칭 안 됨"))
            continue
        if len(codes) > 1:
            unresolved.append((name, stars, f"동명이인({','.join(sorted(codes))})"))
            continue
        resolved.append((name, next(iter(codes)), stars))
    return resolved, unresolved


def scan_root(root: str) -> dict[str, list[tuple[str, int]]]:
    """폴더(1b,2b,...) -> [(이름, 별개수), ...]"""
    from position import load_db

    known = {rec["name"] for rec in load_db()["players"].values()}
    results: dict[str, list[tuple[str, int]]] = {}
    for folder in FOLDER_TO_POSITION:
        dir_path = os.path.join(root, folder)
        if not os.path.isdir(dir_path):
            continue
        pairs = []
        for fname in os.listdir(dir_path):
            if not fname.lower().endswith((".png", ".jpg", ".jpeg")):
                continue
            path = os.path.join(dir_path, fname)
            try:
                found = extract_costs(path)
            except Exception as exc:  # noqa: BLE001
                print(f"  {path} 처리 실패: {exc}")
                continue
            names_only = _fuzzy_correct([n for n, _ in found], known)
            for (orig, stars), corrected in zip(found, names_only):
                pairs.append((corrected, stars))
        if pairs:
            results[folder] = pairs
            print(f"{folder}: {len(pairs)}장 인식")
    return results


def _latest_dated_screenshot_dir(root: str) -> str | None:
    candidates = [
        d for d in glob.glob(os.path.join(root, "20*-*-*"))
        if os.path.isdir(d)
    ]
    return max(candidates) if candidates else None


def main():
    _check_deps()
    if len(sys.argv) > 1:
        root = sys.argv[1]
    else:
        root = _latest_dated_screenshot_dir(DEFAULT_SCREENSHOT_ROOT)
        if root is None:
            raise SystemExit(
                f"{DEFAULT_SCREENSHOT_ROOT} 아래 날짜 폴더(YYYY-MM-DD)를 찾을 수 없습니다. "
                "스크린샷 폴더 경로를 직접 지정하세요."
            )
        print(f"스크린샷 폴더 자동 선택: {root}")

    scanned = scan_root(root)
    if not scanned:
        print("인식된 카드가 없습니다 — 스크린샷 폴더/날짜를 확인하세요.")
        return

    name_index = _build_name_code_index()

    all_resolved = []
    all_unresolved = []
    for folder, pairs in scanned.items():
        csv_pos = FOLDER_TO_CSV_POS.get(folder, folder.upper())
        resolved, unresolved = resolve_codes(pairs, name_index)
        for name, code, stars in resolved:
            all_resolved.append((csv_pos, name, code, stars))
        for name, stars, reason in unresolved:
            all_unresolved.append((csv_pos, name, stars, reason))

    print(f"\n=== 매칭 성공 {len(all_resolved)}건 ===")
    for csv_pos, name, code, stars in sorted(all_resolved):
        print(f"  {csv_pos}\t{name}\t{code}\t{stars}코스트")

    if all_unresolved:
        print(f"\n=== 매칭 실패/보류 {len(all_unresolved)}건(수동 확인 필요) ===")
        for csv_pos, name, stars, reason in sorted(all_unresolved):
            print(f"  {csv_pos}\t{name}\t{stars}코스트\t({reason})")

    out_path = os.path.join(HERE, "extracted_cost_result.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "resolved": [
                {"position": p, "name": n, "player_code": c, "cost": s}
                for p, n, c, s in all_resolved
            ],
            "unresolved": [
                {"position": p, "name": n, "cost": s, "reason": r}
                for p, n, s, r in all_unresolved
            ],
        }, f, ensure_ascii=False, indent=2)
    print(f"\n결과 저장: {out_path}")
    print("(주의: 아직 fanmo_cost.py CSV에는 반영하지 않았습니다 — 결과를 확인한 뒤 "
          "직접 새 스냅샷 CSV로 반영하세요.)")


if __name__ == "__main__":
    main()
