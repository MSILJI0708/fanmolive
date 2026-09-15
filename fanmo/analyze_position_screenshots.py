"""9UP 앱 "선수 교체" 화면을 LD플레이어의 스크롤+캡쳐 매크로(Shift+F1)로 찍어둔
스크린샷을 OCR로 읽어서, 포지션별 선수 명단을 뽑아내고 position_db.json의
manual_position에 반영한다. 코스트는 매달 1일/16일에만 바뀌지만 포지션은 9UP이
아무때나 바꾸므로, 이 스크립트를 매일 돌려서 따라잡는 게 목적이다.

전제:
- 스크린샷은 <SCREENSHOT_ROOT>/<포지션폴더>/*.png 형태로 이미 정리돼 있다(폴더명은
  1b,2b,3b,ss,c,cf,lf,rf,dh — LD플레이어 매크로가 이렇게 저장하도록 이미 설정돼 있음).
- Tesseract-OCR 엔진이 설치돼 있고 한국어 언어팩(kor.traineddata)이 있어야 한다.
  안 깔려 있으면 https://github.com/UB-Mannheim/tesseract/wiki 에서 설치 시
  "Korean" 옵션 체크. pip install pytesseract 는 이 스크립트가 필요하면 알려준다.

이름표가 있는 가로 띠(행)만 잘라서 흑백/반전/이진화 후 OCR한다(화면 전체를 그냥 OCR하면
사진들 틈에 낀 글자를 거의 못 찾아서 — 실측으로 확인함). 그래도 이 게임 폰트에서
tesseract가 받침(ㄴ 등)을 종종 빠뜨리는 고질적인 한계가 남아있어("김지찬"->"김지차"
같은 식), position_db.json에 있는 실제 선수명 중 편집거리 1 이내로 유일하게 맞는 게
있으면 자동으로 교정한다(_fuzzy_correct). 그래도 못 맞추거나 동명이인이면
position_override_apply.py가 "매칭 안 됨"/"동명이인"으로 조용히 건너뛰므로, 틀린
포지션이 잘못 적용될 위험은 낮다. 처음 며칠은 적용 결과(적용됨/충돌 목록)를 한번씩
확인해보는 걸 권장한다.

사용법: python analyze_position_screenshots.py [스크린샷_루트_폴더]
  (생략 시 C:\\Users\\HUI\\OneDrive\\문서\\XuanZhi9\\Pictures\\Screenshots 사용)
"""
from __future__ import annotations

import os
import re
import sys

from position_override_apply import apply_positions, print_report

DEFAULT_ROOT = r"C:\Users\HUI\OneDrive\문서\XuanZhi9\Pictures\Screenshots"

FOLDER_TO_POSITION = {
    "1b": "1루수", "2b": "2루수", "3b": "3루수", "ss": "유격수", "c": "포수",
    "cf": "중견수", "lf": "좌익수", "rf": "우익수", "dh": "지명타자",
    # p(선발)/rp(구원)는 투수 role이라 position_db.json(타자 포지션 전용) 대상이 아님 — 건너뜀
}

_NAME_RE = re.compile(r"^[가-힣]{2,5}$")
# 흔한 라벨/숫자 텍스트를 오인식한 경우 걸러내기 위한 최소 블랙리스트
_NOISE = {"교체", "필터", "시너지", "희귀도", "제한", "지난", "경기", "평균", "선수"}

# UB-Mannheim 설치 프로그램이 "Additional Tasks" 화면 없이 그냥 끝나버리는 경우가 있어서
# (실제로 겪음 — 근데 kor.traineddata는 기본으로 같이 깔림) tesseract.exe가 PATH에 안 잡힐 수
# 있다. 기본 설치 경로를 직접 확인해서 pytesseract에 알려준다.
_DEFAULT_TESSERACT_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]


def _check_deps():
    try:
        import pytesseract  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "필요한 패키지가 없습니다: pip install pytesseract pillow\n"
            f"(원본 에러: {exc})"
        )
    import shutil
    if shutil.which("tesseract") is not None:
        return
    for path in _DEFAULT_TESSERACT_PATHS:
        if os.path.exists(path):
            pytesseract.pytesseract.tesseract_cmd = path
            return
    if shutil.which("tesseract") is None:
        raise SystemExit(
            "Tesseract-OCR 엔진을 찾을 수 없습니다. "
            "https://github.com/UB-Mannheim/tesseract/wiki 에서 설치하세요"
            "(설치 시 Additional language data에서 Korean 체크 필수). "
            "설치 후에도 PATH에 안 잡히면 이 스크립트 상단에 "
            "pytesseract.pytesseract.tesseract_cmd 경로를 직접 지정하세요."
        )


# 스크린샷은 항상 2560x1600(카드 6열x최대3행)로 고정돼 있다(실측). 화면 전체를 한 번에
# OCR하면 선수 사진들 사이에 낀 작은 이름표 글자를 tesseract가 거의 못 찾는다(실측:
# 카드 그리드 안 이름 0개 인식, 왼쪽 사이드바 글자만 건짐) — 그래서 이름표가 있는 가로
# 띠(행)만 크게 잘라서 흑백/반전/이진화한 뒤 그 줄만 OCR한다. 이렇게만 해도 이름표를
# 아예 못 찾던 것에서 대부분 찾는 수준으로 좋아진다(다만 이 폰트에서 받침(ㄴ 등)을
# 종종 빠뜨리는 tesseract 자체 한계는 남아있어 fuzzy 보정으로 뒤에서 따로 처리).
_CARD_LEFT, _CARD_RIGHT = 687, 2469
_ROW_TOPS = [590, 961, 1332]   # 1~3행 이름표 띠의 위쪽 y좌표(실측)
_ROW_HEIGHT = 50


def _ocr_row(img, top: int) -> str:
    import pytesseract
    from PIL import ImageOps

    crop = img.crop((_CARD_LEFT, top, _CARD_RIGHT, top + _ROW_HEIGHT)).convert("L")
    crop = crop.resize((crop.width * 2, crop.height * 2))
    crop = ImageOps.invert(crop).point(lambda x: 0 if x < 140 else 255, mode="L")
    return pytesseract.image_to_string(crop, lang="kor", config="--psm 7")


def extract_names(image_path: str) -> list[str]:
    from PIL import Image

    img = Image.open(image_path)
    names = []
    for top in _ROW_TOPS:
        text = _ocr_row(img, top)
        for token in text.split():
            token = token.strip("_|-— ")
            if token and token not in _NOISE and _NAME_RE.match(token):
                names.append(token)
    return names


def _build_known_names() -> set[str]:
    from position import load_db
    return {rec["name"] for rec in load_db()["players"].values()}


def _fuzzy_correct(names: list[str], known: set[str]) -> list[str]:
    """OCR이 받침을 빠뜨리는 등 1글자 정도 오탈자를 낸 경우, position_db.json에 있는
    실제 선수명 중 편집거리 1 이내로 유일하게 맞는 게 있으면 그걸로 교정한다. 후보가
    여러 명이면(동명이인처럼 애매하면) 손 안 대고 원래 OCR 결과 그대로 둔다 — 그러면
    apply_positions()가 어차피 "매칭 안 됨"으로 조용히 걸러준다."""
    import difflib

    corrected = []
    for name in names:
        if name in known:
            corrected.append(name)
            continue
        matches = difflib.get_close_matches(name, known, n=2, cutoff=0.7)
        # 길이가 같은 것끼리만(받침 유무로 아예 음절 수가 달라지진 않음) + 유일할 때만 교정
        matches = [m for m in matches if len(m) == len(name)]
        if len(matches) == 1:
            corrected.append(matches[0])
        else:
            corrected.append(name)
    return corrected


def scan_root(root: str) -> dict[str, list[str]]:
    positions: dict[str, list[str]] = {}
    for folder, pos in FOLDER_TO_POSITION.items():
        dir_path = os.path.join(root, folder)
        if not os.path.isdir(dir_path):
            continue
        names: set[str] = set()
        for fname in os.listdir(dir_path):
            if not fname.lower().endswith((".png", ".jpg", ".jpeg")):
                continue
            path = os.path.join(dir_path, fname)
            try:
                found = extract_names(path)
            except Exception as exc:  # noqa: BLE001
                print(f"  {path} OCR 실패: {exc}")
                continue
            names.update(found)
        if names:
            positions[pos] = sorted(names)
            print(f"{folder}({pos}): {len(names)}명 인식(교정 전)")
    return positions


def main():
    _check_deps()
    root = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ROOT
    if not os.path.isdir(root):
        raise SystemExit(f"스크린샷 폴더를 찾을 수 없습니다: {root}")

    positions = scan_root(root)
    known = _build_known_names()
    positions = {pos: sorted(set(_fuzzy_correct(names, known))) for pos, names in positions.items()}
    if not positions:
        print("인식된 선수 이름이 없습니다 — 스크린샷이 최신인지, 폴더 구조가 맞는지 확인하세요.")
        return

    print_report(apply_positions(positions))


if __name__ == "__main__":
    main()
