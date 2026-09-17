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
from collections import Counter, defaultdict

from position_override_apply import _HOMONYM_OVERRIDES
from analyze_position_screenshots import (
    FOLDER_TO_POSITION,
    _CARD_LEFT,
    _CARD_RIGHT,
    _ROW_HEIGHT,
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


# 별 5칸은 카드 안에서 항상 같은 자리에 찍힌다(실측: 카드 왼쪽에서 68px 떨어진 곳부터
# 31.9px 간격). 그래서 칸마다 정해진 좌표의 색만 보면 개수를 셀 수 있다.
_STAR_FIRST_OFFSET = 68.0
_STAR_PITCH = 31.9
_STAR_SAMPLE_HITS = 8   # 한 칸에서 이만큼 금색이 잡히면 별이 있다고 본다


def _has_name_band(img, top: int, col: int) -> bool:
    """그 자리에 진짜 선수 카드가 있는지 — 이름표가 초록 띠인지로 판정한다.

    화면에는 별 모양 금색 아이콘을 쓰는 UI가 여럿 있다(특히 "희귀도 제한 ★ 0/40").
    별만 보고 카드라고 판단하면 이런 UI까지 카드로 잡혀서, 확인해야 할 미확정 카드가
    쓸데없이 두 배로 불어난다. 실제 카드만 이름표가 초록 배경이다(실측: 진짜 카드
    0.45~0.77, UI 0.00)."""
    im = label_image({"path": None, "top": top, "col": col}, img).convert("RGB")
    px = im.load()
    w, h = im.size
    total = green = 0
    for y in range(6, h - 6, 2):
        for x in range(0, w, 3):
            r, g, b = px[x, y]
            total += 1
            if g > 60 and g > r + 25 and g > b + 25:
                green += 1
    return total > 0 and green / total >= 0.20


def stars_at_column(img, top: int, col: int) -> int:
    """카드 한 칸의 별 개수. 별이 없으면(= 그 자리에 카드가 없으면) 0.

    예전에는 금색 픽셀이 연속된 구간의 폭을 31.9로 나눠 셌는데, 별이 선수 사진 위에
    겹쳐 찍히는 카드에서는 금색 검출이 중간에 끊겨 한 카드가 24px짜리 조각 서넛으로
    쪼개졌고, 조각마다 "1개"로 세어 3~4코스트 선수가 1코스트로 떨어졌다(실측: 전상현
    3개→1개, 곽도규 4개→1개). 게다가 사진 속 노란 잡티 1px까지 "별 1개"로 세고 있었다.
    칸마다 정해진 자리의 색만 보면 두 문제가 다 사라진다.

    다만 별의 y 위치는 이름표 기준으로 고정이 아니다 — 스크롤이 멈춘 위치에 따라 카드가
    20px쯤 위아래로 밀린다(로건 카드는 이름표보다 96~70px 위, 다른 카드는 75~45px 위).
    그래서 먼저 이 칸에서 금색이 가장 많이 몰린 y를 찾아 별 띠를 잡고, 거기서 5칸을 샘플한다."""
    px = img.convert("RGB").load()
    x0 = int(_CARD_LEFT + col * _COL_PITCH)
    x1 = int(x0 + _COL_PITCH)

    best_y, best_n = None, 0
    for y in range(top - 120, top - 40):
        n = sum(1 for x in range(x0, x1, 2) if _is_gold(px, x, y))
        if n > best_n:
            best_y, best_n = y, n
    if best_y is None or best_n < 5:
        return 0

    count = 0
    for k in range(5):
        cx = int(x0 + _STAR_FIRST_OFFSET + _STAR_PITCH * k + 14)
        hits = sum(1 for dx in range(-9, 10) for dy in (-4, -2, 0, 2, 4)
                   if _is_gold(px, cx + dx, best_y + dy))
        if hits >= _STAR_SAMPLE_HITS:
            count += 1
    return count


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


# 카드 열 간격(실측: 별 묶음 시작 x가 756, 1036, 1315, 1595, 1874, 2153 — 간격 279.4).
# 카드 왼쪽 끝(_CARD_LEFT=687) 기준으로 나누면 이름도 별도 같은 열 번호로 떨어진다
# (이름 중심은 열의 0.68 지점, 별 묶음 시작은 0.25 지점).
_COL_PITCH = 279.4
_CARD_COLUMNS = 6


def _column_of(x: float) -> int:
    return int((x - _CARD_LEFT) // _COL_PITCH)


def _ocr_row_names_by_column(img, top: int) -> dict[int, str]:
    """이름표 띠를 OCR해서 {카드 열 번호: 이름} 으로 돌려준다.

    예전에는 한 줄을 통으로 읽어 "왼쪽부터 순서대로" 별 묶음과 짝지었는데, tesseract가
    이름 하나를 여러 토막으로 끊는 일이 잦아(예: "블레인" -> "블"/"레"/"인") 개수가 안
    맞으면 그 줄을 통째로 버려야 했다(실측 210줄). 글자마다 x좌표를 받아 같은 열의
    토막을 합치면 개수가 어긋나도 제자리를 찾아갈 수 있다."""
    import pytesseract
    from PIL import ImageOps

    crop = img.crop((_CARD_LEFT, top, _CARD_RIGHT, top + _ROW_HEIGHT)).convert("L")
    crop = crop.resize((crop.width * 2, crop.height * 2))
    crop = ImageOps.invert(crop).point(lambda x: 0 if x < 140 else 255, mode="L")
    data = pytesseract.image_to_data(crop, lang="kor", config="--psm 7",
                                     output_type=pytesseract.Output.DICT)

    pieces: dict[int, list[tuple[float, str]]] = {}
    for i, raw in enumerate(data["text"]):
        token = raw.strip().strip("_|-— ")
        if not token or token in _NOISE:
            continue
        # 위에서 2배로 확대했으므로 좌표를 되돌린다
        x = _CARD_LEFT + data["left"][i] / 2
        w = data["width"][i] / 2
        pieces.setdefault(_column_of(x + w / 2), []).append((x, token))

    names = {}
    for col, parts in pieces.items():
        name = "".join(t for _x, t in sorted(parts))
        if _NAME_RE.match(name):
            names[col] = name
    return names


# 별은 읽혔는데 이름을 확정 못 한 2코스트 이상 카드(사람이 눈으로 확인해야 하는 목록)
_unread_cards: list[dict] = []
# 같은 선수인데 스크린샷마다 별 개수가 다르게 읽힌 건(다수결로 정하되 기록은 남긴다)
_star_conflicts: list[tuple[str, str, dict]] = []


def detect_rows(img) -> list[int]:
    """이 스크린샷에서 카드 행(이름표 초록 띠)이 실제로 시작하는 y 목록.

    처음엔 행 위치를 고정값(590/961/1332)으로 박아뒀는데, 스크롤이 멈추는 위치가
    매번 달라서 어떤 장은 523/894/1266처럼 60px 넘게 밀린다. 이름표 높이가 50px뿐이라
    그만큼 밀리면 띠를 통째로 빗나가 이름이 하나도 안 읽혔다 — 투수 명단 306명 중 60명만
    잡히던 원인이 이것이었다(캡쳐는 정상이었고 읽는 자리가 안 따라간 것). 그래서 장마다
    초록 띠를 직접 찾는다."""
    px = img.convert("RGB").load()
    step = 8
    width = (_CARD_RIGHT - _CARD_LEFT) // step
    runs = []
    start = None
    for y in range(200, 1500):
        n = sum(1 for x in range(_CARD_LEFT, _CARD_RIGHT, step)
                if (lambda c: c[1] > 60 and c[1] > c[0] + 25 and c[1] > c[2] + 25)(px[x, y]))
        if n > width * 0.5:
            if start is None:
                start = y
        else:
            if start is not None:
                runs.append((start, y - start))
            start = None
    if start is not None:
        runs.append((start, 1500 - start))

    # 이름표 띠의 높이는 53~54px로 거의 일정하다. 이 범위를 벗어난 초록 구간은 카드가
    # 아니다 — 잘려서 일부만 보이는 행(22px), 초록 버튼/패널이 이름표에 붙어 한 덩어리가
    # 된 것(102px, 174px), 잡티(1~6px) 같은 것들이다. 이걸 안 거르면 가짜 행이 생기고,
    # 그 행을 기준으로 별을 찾다가 옆 카드의 별을 세어버린다(실측: 원상현 1코스트 카드가
    # 2코스트로 부풀려짐 — 코스트를 부풀리는 쪽이라 특히 위험하다).
    return [y for y, h in runs if _ROW_HEIGHT - 12 <= h <= _ROW_HEIGHT + 20]


def extract_costs(image_path: str) -> list[dict]:
    """카드 하나당 {raw_name, stars, path, top, col} 를 돌려준다.

    이름과 별은 순서가 아니라 카드 열 번호(x좌표)로 짝짓는다 — tesseract가 이름을 여러
    토막으로 끊거나 아예 못 읽어도 나머지 카드는 제자리를 지킨다. 카드 위치를 함께 들고
    다니는 이유는, 이름을 확정 못 한 카드의 이름표 그림을 나중에 다시 꺼내 쓰기 위해서다."""
    from PIL import Image

    img = Image.open(image_path)
    out = []
    for top in detect_rows(img):
        names = _ocr_row_names_by_column(img, top)
        for col in range(_CARD_COLUMNS):
            if not _has_name_band(img, top, col):
                continue   # 그 자리에 카드가 없다
            stars = stars_at_column(img, top, col)
            if stars == 0:
                continue
            out.append({
                "raw_name": names.get(col),
                "stars": stars,
                "path": image_path,
                "top": top,
                "col": col,
            })
    return out


def label_image(card: dict, img=None):
    """카드의 이름표 띠만 잘라낸 그림. 게임 폰트가 고정이라 같은 선수의 이름표는 어느
    스크린샷에서든 사실상 같은 픽셀로 찍힌다 — 이걸 이용해 OCR이 실패한 카드를 성공한
    카드와 그림끼리 맞춰볼 수 있다."""
    from PIL import Image

    if img is None:
        img = Image.open(card["path"])
    x0 = int(_CARD_LEFT + card["col"] * _COL_PITCH)
    y0 = card.get("band_y") or _name_band_y(img, card["top"], card["col"]) or card["top"]
    return img.crop((x0, y0, x0 + int(_COL_PITCH), y0 + _ROW_HEIGHT))


def _name_band_y(img, top: int, col: int):
    """이름표(초록 띠)가 실제로 시작하는 y. 못 찾으면 None.

    카드는 스크롤이 멈춘 위치에 따라 20px쯤 위아래로 밀리기 때문에, 이름표를 고정 y로
    자르면 글자가 잘린다. 잘린 그림은 사람이 읽기도 어렵고 템플릿 대조도 어긋난다."""
    px = img.convert("RGB").load()
    x0 = int(_CARD_LEFT + col * _COL_PITCH)
    x1 = int(x0 + _COL_PITCH)
    rows = []
    for y in range(top - 30, top + _ROW_HEIGHT + 30):
        n = sum(1 for x in range(x0, x1, 4)
                if (lambda c: c[1] > 60 and c[1] > c[0] + 25 and c[1] > c[2] + 25)(px[x, y]))
        rows.append((y, n))
    wide = [y for y, n in rows if n >= (x1 - x0) // 4 // 2]
    return wide[0] if wide else None


def _build_name_code_index() -> dict[str, set[str]]:
    """이름 -> {player_code, ...}. position_db.json(타자) + 최근 데이터 파일(타자+투수)
    스캔 결과를 합친다(투수는 position_db.json에 없어서 보강 필요)."""
    from data_paths import glob_data_files
    from position import load_db

    index: dict[str, set[str]] = defaultdict(set)
    db = load_db()
    for code, rec in db["players"].items():
        index[rec["name"]].add(("batter", code))

    # 투수/타자 동명이인(양현종: KIA 투수 77637 vs 키움 타자 55370, 김민수: KT 65048 vs
    # LG 타자 64793 등)을 제대로 가르려면 두 사람이 다 인덱스에 있어야 한다. 최근 60개
    # 파일만 훑었더니 키움 타자 양현종이 빠져서, 3루수 카드의 양현종이 KIA 투수 코드로
    # 잘못 매칭됐다(2026-09-16). 올 시즌 전체를 훑어 누락을 없앤다.
    for fp in glob_data_files():
        if "/data_2026" not in fp.replace("\\", "/"):
            continue
        try:
            with open(fp, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        for kind, role in (("batters", "batter"), ("pitchers", "pitcher")):
            for rec in d.get(kind, []):
                name = rec.get("name")
                code = rec.get("player_code")
                if name and code:
                    index[name].add((role, code))
    return index


def resolve_codes(costs: list[tuple[str, int]], name_index: dict[str, set[tuple[str, str]]],
                  is_pitcher: bool, kor_position: str | None = None):
    """(이름, 별개수) -> (이름, player_code, 별개수).

    같은 이름이 여러 명이어도, 지금 보고 있는 화면이 투수 명단인지 야수 명단인지로
    후보를 먼저 거른다 — 투수 화면에 뜬 양현종은 KIA 투수, 3루수 화면에 뜬 양현종은
    키움 타자다. 그래도 후보가 둘 이상 남으면(같은 역할의 동명이인) 건너뛴다."""
    want_role = "pitcher" if is_pitcher else "batter"
    resolved = []
    unresolved = []
    for name, stars, precode in costs:
        if precode:
            resolved.append((name, precode, stars))
            continue
        entries = name_index.get(name)
        if not entries:
            unresolved.append((name, stars, "매칭 안 됨"))
            continue
        codes = {code for role, code in entries if role == want_role}
        if not codes:
            unresolved.append((name, stars, f"{'투수' if is_pitcher else '야수'} 기록이 없는 이름"))
            continue
        if len(codes) > 1:
            # 포지션 쪽에서 사진으로 이미 확정해둔 동명이인(박건우/김민석 등)은 그 매핑을
            # 그대로 쓴다 — 같은 사진을 보고 같은 판단을 두 번 할 이유가 없다.
            override = _HOMONYM_OVERRIDES.get((name, kor_position))
            if override in codes:
                resolved.append((name, override, stars))
                continue
            unresolved.append((name, stars, f"동명이인({','.join(sorted(codes))})"))
            continue
        resolved.append((name, next(iter(codes)), stars))
    return resolved, unresolved


def _pick_code(card, name, codes_of, is_pitcher, photos) -> str | None:
    """동명이인이면 사진으로 누구인지 고른다. 동명이인이 아니면 None(뒤에서 이름으로 처리)."""
    cands = codes_of["pitcher" if is_pitcher else "batter"].get(name) or set()
    if len(cands) < 2:
        return None
    return match_homonym_photo(card, cands, photos)


def assign_pitcher_roles(cards: list[dict], folder_pos: str) -> dict[int, str]:
    """투수 카드 하나하나에 선발(SP)/구원(P)을 매긴다.

    9UP의 투수 화면은 선택한 역할군을 코스트 5→1 순으로 쭉 보여준 뒤, 이어서 반대
    역할군을 다시 5부터 보여준다. 그래서 폴더(어느 화면에서 찍었는지)만으로는 역할을
    알 수 없다 — 두 폴더 모두 전체 투수를 담고 있다(실측: p/rp 각 276명, 교집합 275명).
    대신 코스트가 1까지 내려갔다가 갑자기 다시 튀어오르는 지점이 두 역할군의 경계다
    (실측: 선발 화면 133번째 카드에서 1 -> 4로 급상승). 그 앞이 화면에서 선택한 역할,
    뒤가 반대 역할이다."""
    other = "P" if folder_pos == "SP" else "SP"
    boundary = None
    bottomed = False
    prev = None
    for i, card in enumerate(cards):
        s = card["stars"]
        if s <= 1:
            bottomed = True
        elif bottomed and prev is not None and s >= prev + 2:
            boundary = i
            break
        prev = s
    if boundary is None:
        boundary = len(cards)   # 경계를 못 찾으면 전부 선택한 역할로 본다
    return {id(c): (folder_pos if i < boundary else other) for i, c in enumerate(cards)}


def scan_root(root: str, name_index: dict[str, set[tuple[str, str]]]) -> dict[str, list[tuple[str, int]]]:
    """폴더(1b,2b,...) -> [(이름, 별개수), ...]

    이름 보정 후보는 화면에 맞춰 고른다 — 투수 화면이면 투수 명단, 야수 화면이면 타자
    명단. 예전에는 position_db.json(타자 전용 210명)만 후보로 써서 투수 이름은 아예
    보정이 안 됐다."""
    batters = {n for n, entries in name_index.items() if any(r == "batter" for r, _ in entries)}
    pitchers = {n for n, entries in name_index.items() if any(r == "pitcher" for r, _ in entries)}
    library = load_template_library()
    photos = load_homonym_photos()
    # 이름 -> 그 역할(투수/야수)에서 가능한 코드들. 후보가 둘 이상이면 동명이인이라
    # 이름만으로는 못 정하므로, 사진으로 가른다.
    codes_of = {
        role: {n: {c for r, c in e if r == role} for n, e in name_index.items()}
        for role in ("batter", "pitcher")
    }
    learned: dict[str, list] = {}
    results: dict[str, list[tuple[str, int]]] = {}
    # 포지션 OCR과 달리 코스트는 투수(p/rp)도 필요하다 — FOLDER_TO_POSITION은 타자
    # 포지션만 담고 있어서(position_db.json이 타자 전용이라) 그걸 쓰면 투수를 통째로
    # 빠뜨린다.
    for folder, csv_pos in FOLDER_TO_CSV_POS.items():
        dir_path = os.path.join(root, folder)
        if not os.path.isdir(dir_path):
            continue
        known = pitchers if _is_pitcher_pos(csv_pos) else batters
        pairs = []
        cards = []
        # 파일명은 캡쳐 시각순이라, 정렬하면 화면에 나온 명단 순서 그대로가 된다.
        # 투수는 이 순서에서 선발/구원 경계를 찾아내야 하므로 순서가 중요하다.
        for fname in sorted(os.listdir(dir_path)):
            if not fname.lower().endswith((".png", ".jpg", ".jpeg")):
                continue
            path = os.path.join(dir_path, fname)
            try:
                cards.extend(extract_costs(path))
            except Exception as exc:  # noqa: BLE001
                print(f"  {path} 처리 실패: {exc}")

        card_pos = assign_pitcher_roles(cards, csv_pos) if _is_pitcher_pos(csv_pos) else None

        # 1차: OCR 글자로 이름을 확정하고, 확정된 카드의 이름표 그림은 템플릿으로 모은다.
        # 지난 실행에서 쌓아둔 템플릿도 함께 쓴다 — OCR이 매번 똑같이 실패하는 선수는
        # 그때그때 템플릿이 안 생기므로, 누적된 게 없으면 영영 못 읽는다.
        templates: dict[str, list] = {n: list(v) for n, v in library.items() if n in known}
        undecided = []
        for card in cards:
            corrected = (correct_name(card["raw_name"], known)
                         if card["raw_name"] else None)
            if corrected is None:
                undecided.append(card)
                continue
            pairs.append((card_pos[id(card)] if card_pos else csv_pos, corrected, card["stars"],
                          _pick_code(card, corrected, codes_of, _is_pitcher_pos(csv_pos), photos)))
            if len(templates.get(corrected, ())) < 3:
                sig = ink_signature(label_image(card))
                if sig:
                    templates.setdefault(corrected, []).append(sig)
                    learned.setdefault(corrected, []).append(sig)

        # 2차: 못 읽은 카드를 템플릿과 그림끼리 대조해 되살린다. 같은 선수가 여러 장에
        # 겹쳐 찍히므로, 한 장에서 글자가 뭉개져도 다른 장에서 읽혔다면 여기서 살아난다.
        for card in undecided:
            corrected = match_by_image(card, templates)
            if corrected is None:
                # 1코스트는 기본값이라 놓쳐도 손해가 없지만, 2코스트 이상은 그 선수가
                # 1로 잘못 내려가므로 사람이 눈으로 확인하도록 따로 남긴다.
                if card["stars"] >= 2:
                    _unread_cards.append(card)
                continue
            pairs.append((card_pos[id(card)] if card_pos else csv_pos, corrected, card["stars"],
                          _pick_code(card, corrected, codes_of, _is_pitcher_pos(csv_pos), photos)))
        # 같은 선수가 여러 스크린샷에 겹쳐 찍히는데, 별이 사진에 가려 한 장에서만 덜
        # 읽히는 경우가 있다(토다: 어떤 장은 2개, 어떤 장은 1개 — 실제로는 2개). 가장
        # 많이 나온 값으로 정하고, 동률이면 큰 쪽을 택한다(별은 가려져서 덜 세지는 쪽이
        # 흔하지, 없는 별이 생기지는 않는다).
        if pairs:
            votes: dict[tuple, Counter] = defaultdict(Counter)
            for pos, name, stars, code in pairs:
                votes[(pos, name, code)][stars] += 1
            decided = defaultdict(list)
            for (pos, name, code), counter in votes.items():
                top_n = max(counter.values())
                decided[pos].append((name, max(s for s, c in counter.items() if c == top_n), code))
                if len(counter) > 1:
                    _star_conflicts.append((folder, name, dict(counter)))
            for pos, lst in decided.items():
                results.setdefault(pos, []).extend(lst)
            print(f"{folder}: " + ", ".join(f"{p} {len(l)}명" for p, l in sorted(decided.items())))

    # 이번에 확정한 이름표를 다음 실행을 위해 쌓아둔다.
    for name, sigs in learned.items():
        library.setdefault(name, [])
        library[name] = (library[name] + sigs)[:3]
    save_template_library(library)
    print(f"이름표 템플릿 {len(library)}명분 누적 (cost_name_templates.json)")
    return results


def write_draft_csv(resolved: list[tuple[str, str, str, int]], base_csv: str, out_csv: str) -> dict:
    """직전 스냅샷을 바탕으로, 사진에서 읽어낸 코스트만 갱신한 초안 CSV를 만든다.

    스냅샷을 통째로 새로 만들지 않는 이유: 별 세기는 정확한데(실측 정확도 96% — 게다가
    불일치 3건은 전부 수기 CSV 쪽 오기로 확인됨) 이름 OCR이 614행 중 127행만 잡아내서,
    읽어낸 것만으로 CSV를 만들면 나머지 선수들의 코스트가 통째로 사라진다. 그래서 기존
    스냅샷을 복사해두고 확인된 것만 덮어쓴다.

    자동으로 fanmo_cost.py의 SNAPSHOTS에 등록하지는 않는다 — 라이브 점수 계산에 쓰이는
    파일이라, 변경 목록을 사람이 한 번 보고 올리는 게 맞다."""
    import csv

    with open(base_csv, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames
        rows = list(reader)

    by_name: dict[str, list[dict]] = {}
    for row in rows:
        by_name.setdefault((row.get("이름") or "").strip(), []).append(row)

    changed, added, skipped = [], [], []

    # 같은 포지션에 같은 이름인 동명이인은 사진만으로는 끝내 못 가린다 — 유니폼도 같고
    # 이름표도 같아서(예: 삼성 이승현 두 명) 기계가 고를 근거가 없다. 사람이 한 번 확인해
    # 준 값은 여기에 적어두고 그대로 반영한다. player_code로 적으므로 헷갈릴 여지가 없다.
    for code, cost in _MANUAL_COST.items():
        for row in rows:
            if (row.get("동명") or "").strip() == code and (row.get("코스트") or "").strip() != str(cost):
                changed.append(f"{row['이름']}({code}): {row['코스트']} -> {cost} (수동 확인)")
                row["코스트"] = str(cost)
    for pos, name, code, cost in resolved:
        # 투수/타자 동명이인이 실제로 있다(양현종: KIA 투수 vs 키움 타자). 기존 CSV에
        # 투수 행만 있는 이름이라도, 야수 명단에서 읽어낸 코스트는 그 투수 행을 덮어쓸
        # 게 아니라 별개의 타자 행으로 추가해야 한다 — 반대도 마찬가지다. 그래서 같은
        # 이름 중 "같은 쪽(투수/야수)" 행만 후보로 본다.
        candidates = [r for r in by_name.get(name, [])
                      if _is_pitcher_pos((r.get("포지션") or "")) == _is_pitcher_pos(pos)]
        target = None
        if len(candidates) == 1:
            target = candidates[0]
        elif candidates:
            # 동명이인이면 player_code(동명 칸)로 특정하고, 그것도 없으면 포지션이 같은 행
            by_code = [r for r in candidates if (r.get("동명") or "").strip() == code]
            by_pos = [r for r in candidates if (r.get("포지션") or "").strip() == pos]
            if len(by_code) == 1:
                target = by_code[0]
            elif len(by_pos) == 1:
                target = by_pos[0]
            else:
                skipped.append(f"{name}({pos}): 기존 CSV에 같은 이름이 {len(candidates)}행 — 수동 확인")
                continue

        if target is None:
            # 투수는 선발/구원 화면 양쪽에 다 나오므로 같은 선수가 두 번 들어올 수 있다.
            # 이미 추가한 선수면 건너뛴다(실측: 이재학/클레빈저가 두 줄씩 생겼음).
            if any(r.get("이름") == name and (r.get("동명") or "").strip() == code
                   for r in rows):
                continue
            row = {k: "" for k in fields}
            row["동명"], row["포지션"], row["이름"], row["코스트"] = code, pos, name, str(cost)
            rows.append(row)
            by_name.setdefault(name, []).append(row)
            added.append(f"{name}({pos}) = {cost}")
            continue

        old_cost = (target.get("코스트") or "").strip()
        old_pos = (target.get("포지션") or "").strip()

        # 투수는 포지션을 절대 바꾸지 않는다. 9UP의 선발 목록에는 구원투수도 다 나와서
        # (실측: p/rp 폴더가 같은 276명을 담고 있고 교집합이 275명) 어느 폴더에서 읽었는지로
        # 선발/구원을 판단할 수 없다. 그대로 뒀다간 구원투수가 SP로 뒤바뀐다.
        new_pos = old_pos if _is_pitcher_pos(pos) else pos
        if old_cost != str(cost) or old_pos != new_pos:
            changed.append(f"{name}: {old_pos} {old_cost} -> {new_pos} {cost}")
            target["코스트"] = str(cost)
            target["포지션"] = new_pos

    with open(out_csv, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    return {"changed": changed, "added": added, "skipped": skipped, "total_rows": len(rows)}


def _to_jamo(text: str) -> str:
    """한글을 자모로 풀어쓴다(김 -> ㄱㅣㅁ). 종성이 없으면 그 자리는 비운다."""
    out = []
    for ch in text:
        code = ord(ch) - 0xAC00
        if 0 <= code < 11172:
            out.append(chr(0x1100 + code // 588))                  # 초성
            out.append(chr(0x1161 + (code % 588) // 28))            # 중성
            jong = code % 28
            if jong:
                out.append(chr(0x11A7 + jong))                      # 종성
        else:
            out.append(ch)
    return "".join(out)


def _edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def correct_name(name: str, candidates: set[str], max_jamo_distance: int = 2) -> str | None:
    """OCR이 흘린 이름을 실제 선수명으로 되돌린다. 확정 못 하면 None.

    이 게임 폰트에서 tesseract는 받침을 자주 빠뜨리거나 비슷한 자음으로 잘못 읽는다
    ("김현수" -> "기혀수", "고승민" -> "고숲민", "문보경" -> "무보경"). 음절 단위로 비교하면
    세 글자가 통째로 다른 것처럼 보이지만, 자모로 풀어쓰면 받침 한두 개 차이일 뿐이다.
    글자 수가 같고 자모 거리가 가장 가까운 후보가 유일할 때만 고친다 — 후보가 둘 이상
    비슷하면 잘못 고칠 위험이 있으니 손대지 않는다."""
    if name in candidates:
        return name
    target = _to_jamo(name)
    best, best_d = [], max_jamo_distance + 1
    for cand in candidates:
        if len(cand) != len(name):
            continue
        d = _edit_distance(target, _to_jamo(cand))
        if d < best_d:
            best, best_d = [cand], d
        elif d == best_d:
            best.append(cand)
    if best_d <= max_jamo_distance and len(best) == 1:
        return best[0]
    return None


def _is_pitcher_pos(pos: str) -> bool:
    return pos.strip().upper() in ("SP", "P")


def ink_signature(im):
    """이름표에서 흰 글자 픽셀만 뽑아 (좌상단 기준 좌표 집합, 글자영역 크기)로 돌려준다.

    게임 폰트가 고정이라 같은 선수의 이름표는 어느 스크린샷에서든 같은 모양으로 찍힌다.
    다만 카드 열 좌표가 정확히 균등하지 않아 10~20px씩 어긋나므로, 글자 영역(잉크
    바운딩박스) 기준으로 원점을 맞춰야 비교가 된다(이걸 안 맞추고 비교했다가 같은
    이름끼리도 전혀 안 겹쳐서 한참 헤맸다)."""
    im = im.convert("RGB")
    px = im.load()
    w, h = im.size
    pts = [(x, y) for y in range(h) for x in range(w)
           if px[x, y][0] > 200 and px[x, y][1] > 200 and px[x, y][2] > 200]
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    x0, y0 = min(xs), min(ys)
    return (frozenset((x - x0, y - y0) for x, y in pts),
            (max(xs) - x0 + 1, max(ys) - y0 + 1))


def signature_distance(a, b) -> float:
    """두 이름표 그림이 얼마나 다른지(0=완전히 같음, 1=전혀 안 겹침)."""
    (pa, sa), (pb, sb) = a, b
    if abs(sa[0] - sb[0]) > 6 or abs(sa[1] - sb[1]) > 4:
        return 1.0   # 글자 영역 크기부터 다르면 볼 것도 없다(글자 수가 다르거나 다른 이름)
    best = 1.0
    for dx in (-2, -1, 0, 1, 2):
        for dy in (-1, 0, 1):
            shifted = {(x + dx, y + dy) for x, y in pb}
            best = min(best, len(pa ^ shifted) / len(pa | shifted))
    return best


# 실측 분포(2026-09-16): 같은 이름끼리는 대부분 0.33 이하, 다른 이름끼리는 0.455 이상.
# 그 사이에서 넉넉히 보수적으로 잡는다 — 잘못 붙이느니 사람 검수로 넘기는 게 낫다.
_SIGNATURE_MATCH_MAX = 0.40


TEMPLATE_LIBRARY = os.path.join(HERE, "cost_name_templates.json")

# 사진으로도 못 가르는 동명이인의 코스트를 사람이 확인해 직접 적어두는 곳.
# player_code -> 코스트. (2026-09-17 확인: 삼성 이승현 두 명은 팀도 이름표도 같아서
# 왼손 51454 / 오른손 60146 을 사람이 직접 구분해 알려준 값이다.)
_MANUAL_COST = {
    "51454": 2,   # 이승현(삼성, 좌완)
    "60146": 1,   # 이승현(삼성, 우완)
}


HOMONYM_PHOTOS = os.path.join(HERE, "cost_homonym_photos.json")
_PHOTO_MATCH_MAX = 14      # 16x8 dHash(128비트) 기준 이 정도까지는 같은 사진으로 본다
_PHOTO_MATCH_MARGIN = 6    # 1등이 2등보다 이만큼은 가까워야 확신한다


def photo_image(card: dict, img=None):
    """카드에서 선수 사진 부분만 잘라낸다. 동명이인은 이름표 글자가 완전히 똑같아서
    이름표로는 절대 못 가른다 — 얼굴 사진만이 유일한 단서다."""
    from PIL import Image

    if img is None:
        img = Image.open(card["path"])
    x0 = int(_CARD_LEFT + card["col"] * _COL_PITCH)
    return img.crop((x0, card["top"] - 320, x0 + int(_COL_PITCH), card["top"] - 110))


def photo_signature(card: dict, img=None) -> int | None:
    from PIL import Image

    try:
        im = photo_image(card, img).convert("L").resize((17, 8), Image.LANCZOS)
    except Exception:  # noqa: BLE001
        return None
    px = list(im.getdata())
    bits = 0
    for r in range(8):
        for c in range(16):
            bits = (bits << 1) | (1 if px[r * 17 + c] > px[r * 17 + c + 1] else 0)
    return bits


def load_homonym_photos() -> dict[str, list[int]]:
    if not os.path.exists(HOMONYM_PHOTOS):
        return {}
    with open(HOMONYM_PHOTOS, encoding="utf-8") as f:
        return {k: [int(h) for h in v] for k, v in json.load(f).items()}


def save_homonym_photos(lib: dict[str, list[int]]) -> None:
    with open(HOMONYM_PHOTOS, "w", encoding="utf-8") as f:
        json.dump({k: [str(h) for h in v[:4]] for k, v in lib.items()}, f, ensure_ascii=False)


def match_homonym_photo(card: dict, codes: set[str], lib: dict[str, list[int]]) -> str | None:
    """같은 이름의 후보 코드들 중, 카드 사진이 가장 닮은 쪽을 고른다.

    한 번 사람이 확인해준 사진을 쌓아두면 다음 캡쳐(10/1 코스트 개정 등)부터는 이
    비교만으로 자동 구분된다 — 매번 같은 선수를 다시 확인할 이유가 없다."""
    sig = photo_signature(card)
    if sig is None:
        return None
    scored = sorted(
        (min(bin(sig ^ h).count("1") for h in lib[c]), c)
        for c in codes if lib.get(c)
    )
    if not scored or scored[0][0] > _PHOTO_MATCH_MAX:
        return None
    if len(scored) > 1 and scored[1][0] - scored[0][0] < _PHOTO_MATCH_MARGIN:
        return None
    return scored[0][1]


def _sig_to_json(sig) -> dict:
    pts, (w, h) = sig
    bits = bytearray((w * h + 7) // 8)
    for x, y in pts:
        i = y * w + x
        bits[i // 8] |= 1 << (i % 8)
    return {"w": w, "h": h, "bits": bits.hex()}


def _sig_from_json(d) -> tuple:
    w, h = d["w"], d["h"]
    bits = bytes.fromhex(d["bits"])
    pts = {(i % w, i // w) for i in range(w * h) if bits[i // 8] >> (i % 8) & 1}
    return frozenset(pts), (w, h)


def load_template_library() -> dict[str, list]:
    """이름표 그림 템플릿 모음. 실패하는 선수는 매번 똑같이 실패하므로(나승엽은 항상
    "나숫연"으로 읽힌다) 한 번 확인한 이름표를 파일로 쌓아두고 다음부터는 OCR 없이
    그림만으로 알아본다. 게임 폰트가 고정이라 한두 번 검수하면 대부분 자동으로 잡힌다."""
    if not os.path.exists(TEMPLATE_LIBRARY):
        return {}
    with open(TEMPLATE_LIBRARY, encoding="utf-8") as f:
        raw = json.load(f)
    return {name: [_sig_from_json(s) for s in sigs] for name, sigs in raw.items()}


def save_template_library(templates: dict[str, list]) -> None:
    packed = {name: [_sig_to_json(s) for s in sigs[:3]] for name, sigs in templates.items()}
    with open(TEMPLATE_LIBRARY, "w", encoding="utf-8") as f:
        json.dump(packed, f, ensure_ascii=False)


def match_by_image(card: dict, templates: dict[str, list]) -> str | None:
    """OCR로 이름을 확정 못 한 카드를, 이미 확정된 카드의 이름표 그림과 맞춰 알아낸다.

    같은 선수가 여러 스크린샷에 겹쳐 찍히므로, 한 장에서 글자가 뭉개졌어도 다른 장에서
    제대로 읽혔다면 이 방법으로 되살릴 수 있다. 여러 이름이 비슷하게 맞으면 포기한다."""
    sig = ink_signature(label_image(card))
    if sig is None:
        return None
    scored = []
    for name, sigs in templates.items():
        d = min(signature_distance(sig, s) for s in sigs)
        if d <= _SIGNATURE_MATCH_MAX:
            scored.append((d, name))
    if not scored:
        return None
    scored.sort()
    if len(scored) > 1 and scored[1][0] - scored[0][0] < 0.08:
        return None   # 1등과 2등이 엇비슷하면 확신할 수 없다
    return scored[0][1]


def write_review_sheet(cards: list[dict], out_path: str) -> int:
    """이름을 확정 못 한 2코스트 이상 카드들을 잘라 한 장의 검수 시트로 붙인다.

    OCR만으로 100%는 불가능하다 — "박전우"는 박건우와 박정우가 자모 거리 1로 똑같이
    가까워서 기계가 고르면 반드시 절반은 틀리고, 로스터에 없는 이름(용병 등)은 아예
    후보가 없다. 임계값을 낮춰 억지로 맞추면 오히려 엉뚱한 선수 코스트를 오염시킨다.
    1코스트는 기본값이라 놓쳐도 손해가 없지만 2코스트 이상은 그렇지 않으므로, 그 카드만
    모아 사람이 눈으로 확인하게 한다(한 달에 두 번, 몇 분이면 끝난다).

    같은 선수가 여러 스크린샷에 겹쳐 찍히므로, 잘라낸 그림이 사실상 같으면 한 장만 남긴다.
    """
    from PIL import Image, ImageDraw

    if not cards:
        return 0

    from screenshot_dedupe import _hamming

    def card_box(card):
        # 별 띠 위쪽 사진부터 이름표 아래까지 — 사람이 얼굴/등번호/이름을 함께 보고
        # 판단할 수 있어야 하므로 카드 전체를 넉넉히 담는다.
        # 카드 한 장은 이름표 위로 약 330px(행 간격 371px에 가깝다)을 차지한다 — 사진
        # 위쪽부터 이름표까지 통째로 담아야 사람이 얼굴/등번호/이름을 함께 보고 판단한다.
        x0 = int(_CARD_LEFT + card["col"] * _COL_PITCH)
        return (x0, card["top"] - 330, x0 + int(_COL_PITCH), card["top"] + _ROW_HEIGHT)

    def crop_hash(im):
        small = im.convert("L").resize((9, 8), Image.LANCZOS)
        px = list(small.getdata())
        bits = 0
        for r in range(8):
            for c in range(8):
                bits = (bits << 1) | (1 if px[r * 9 + c] > px[r * 9 + c + 1] else 0)
        return bits

    crops, seen = [], []
    for card in sorted(cards, key=lambda c: (-c["stars"], c["path"])):
        try:
            im = Image.open(card["path"]).crop(card_box(card))
        except Exception:  # noqa: BLE001
            continue
        h = crop_hash(im)
        if any(_hamming(h, s) <= 6 for s in seen):
            continue
        seen.append(h)
        crops.append((card, im))

    if not crops:
        return 0

    cols = 8
    cw, ch = crops[0][1].size
    label_h = 30
    gap = 6
    rows = (len(crops) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (cw + gap), rows * (ch + label_h + gap)), (20, 20, 25))
    draw = ImageDraw.Draw(sheet)
    for i, (card, im) in enumerate(crops):
        x = (i % cols) * (cw + gap)
        y = (i // cols) * (ch + label_h + gap)
        sheet.paste(im, (x, y))
        draw.text((x + 6, y + ch + 8), f"#{i + 1}  {card['stars']}코스트", fill=(255, 220, 120))
    sheet.save(out_path)
    return len(crops)


def _today_compact() -> str:
    from datetime import date

    return date.today().strftime("%Y%m%d")


def _latest_dated_screenshot_dir(root: str) -> str | None:
    candidates = [
        d for d in glob.glob(os.path.join(root, "20*-*-*"))
        if os.path.isdir(d)
    ]
    return max(candidates) if candidates else None


def main():
    _check_deps()
    positional = [a for a in sys.argv[1:] if not a.startswith("--")]
    if positional:
        root = positional[0]
    else:
        root = _latest_dated_screenshot_dir(DEFAULT_SCREENSHOT_ROOT)
        if root is None:
            raise SystemExit(
                f"{DEFAULT_SCREENSHOT_ROOT} 아래 날짜 폴더(YYYY-MM-DD)를 찾을 수 없습니다. "
                "스크린샷 폴더 경로를 직접 지정하세요."
            )
        print(f"스크린샷 폴더 자동 선택: {root}")

    name_index = _build_name_code_index()
    scanned = scan_root(root, name_index)
    if not scanned:
        print("인식된 카드가 없습니다 — 스크린샷 폴더/날짜를 확인하세요.")
        return

    all_resolved = []
    all_unresolved = []
    # scan_root는 이제 폴더가 아니라 포지션(1B..DH, SP, P)을 키로 돌려준다 — 투수는
    # 어느 폴더에서 찍혔는지가 아니라 명단 안의 경계로 선발/구원이 갈리기 때문이다.
    kor_of = {v: k for k, v in FOLDER_TO_CSV_POS.items()}
    for csv_pos, pairs in scanned.items():
        resolved, unresolved = resolve_codes(pairs, name_index, _is_pitcher_pos(csv_pos),
                                             FOLDER_TO_POSITION.get(kor_of.get(csv_pos)))
        for name, code, stars in resolved:
            all_resolved.append((csv_pos, name, code, stars))
        for name, stars, reason in unresolved:
            all_unresolved.append((csv_pos, name, stars, reason))

    print(f"\n=== 매칭 성공 {len(all_resolved)}건 ===")
    for csv_pos, name, code, stars in sorted(all_resolved):
        print(f"  {csv_pos}\t{name}\t{code}\t{stars}코스트")

    # 2코스트 이상은 놓치면 그 선수가 1코스트로 잘못 내려간다. 이름을 못 읽었거나
    # 동명이인이라 못 가른 건을 전부 모아 따로 보여준다 — 이 목록이 비어야 안심할 수 있다.
    critical = [u for u in all_unresolved if u[2] >= 2]
    print(f"\n=== [중요] 2코스트 이상인데 확정 못 한 카드: "
          f"{len(critical) + len(_unread_cards)}건 ===")
    for csv_pos, name, stars, reason in sorted(critical):
        print(f"  {csv_pos}\t{name}\t{stars}코스트\t({reason})")
    for card in sorted(_unread_cards, key=lambda c: (-c["stars"], c["path"], c["col"])):
        label = (f"'{card['raw_name']}'로 읽혀 보정 실패" if card["raw_name"]
                 else "이름 글자를 못 찾음")
        print(f"  {label}\t{card['stars']}코스트\t"
              f"{os.path.basename(card['path'])} ({card['col'] + 1}번째 카드)")
    if not critical and not _unread_cards:
        print("  없음 — 2코스트 이상은 전부 확정됨")
    elif _unread_cards:
        sheet = os.path.join(HERE, "cost_review_%s.png" % _today_compact()[2:])
        n = write_review_sheet(_unread_cards, sheet)
        print(f"\n  이름을 확정 못 한 카드 {n}장을 검수 시트로 모았습니다: {sheet}")
        print("  이 그림을 열어서 각 카드의 선수 이름을 알려주면 코스트에 반영합니다.")

    if all_unresolved:
        print(f"\n=== 매칭 실패/보류 {len(all_unresolved)}건(수동 확인 필요) ===")
        for csv_pos, name, stars, reason in sorted(all_unresolved):
            print(f"  {csv_pos}\t{name}\t{stars}코스트\t({reason})")

    # 코스트 갱신일에는 직전 스냅샷 기반 초안 CSV까지 만들어 둔다(등록은 사람이).
    if "--draft" in sys.argv:
        from fanmo_cost import SNAPSHOTS

        base_csv = os.path.join(HERE, SNAPSHOTS[-1][2])
        out_csv = os.path.join(HERE, "fanmo%s_draft.csv" % _today_compact()[2:])
        report = write_draft_csv(all_resolved, base_csv, out_csv)
        print(f"\n=== 초안 CSV 작성: {out_csv} ===")
        print(f"  기준 스냅샷: {SNAPSHOTS[-1][2]} / 전체 {report['total_rows']}행")
        print(f"  코스트(또는 포지션) 바뀐 선수: {len(report['changed'])}명")
        for c in report["changed"]:
            print("   ", c)
        print(f"  새로 추가된 선수: {len(report['added'])}명")
        for a in report["added"]:
            print("   ", a)
        if report["skipped"]:
            print(f"  동명이인이라 건너뜀: {len(report['skipped'])}명")
            for s in report["skipped"]:
                print("   ", s)
        print("  * 이 파일은 아직 쓰이지 않습니다. 내용을 확인한 뒤 fanmo<YYMMDD>.csv 로"
              " 이름을 바꾸고 fanmo_cost.py의 SNAPSHOTS에 등록하세요.")

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
            # 이름을 확정 못 한 2코스트 이상 카드의 위치 — 나중에 다시 OCR을 돌리지 않고
            # 그 카드만 잘라 보거나, 사람이 알려준 이름을 템플릿으로 학습시킬 때 쓴다.
            "unread_cards": _unread_cards,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n결과 저장: {out_path}")
    print("(주의: 아직 fanmo_cost.py CSV에는 반영하지 않았습니다 — 결과를 확인한 뒤 "
          "직접 새 스냅샷 CSV로 반영하세요.)")


if __name__ == "__main__":
    main()
