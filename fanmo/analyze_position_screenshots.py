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

한계: 게임 UI 폰트에 대한 OCR이라 오탈자가 날 수 있다. position_override_apply.py가
어차피 position_db.json에 없는 이름이나 동명이인은 자동으로 건너뛰므로, 오탈자로 잘못
읽은 이름은 대부분 "매칭 안 됨"으로 조용히 무시된다(틀린 포지션이 적용될 위험은 낮음).
다만 완벽하지 않으므로 처음 며칠은 적용 결과(적용됨/안 됨 목록)를 한번씩 확인해보는 걸
권장한다.

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
    if shutil.which("tesseract") is None:
        raise SystemExit(
            "Tesseract-OCR 엔진을 찾을 수 없습니다. "
            "https://github.com/UB-Mannheim/tesseract/wiki 에서 설치하세요"
            "(설치 시 Additional language data에서 Korean 체크 필수). "
            "설치 후에도 PATH에 안 잡히면 이 스크립트 상단에 "
            "pytesseract.pytesseract.tesseract_cmd 경로를 직접 지정하세요."
        )


def extract_names(image_path: str) -> list[str]:
    import pytesseract
    from PIL import Image

    img = Image.open(image_path)
    data = pytesseract.image_to_data(img, lang="kor", output_type=pytesseract.Output.DICT)
    names = []
    for text, conf in zip(data["text"], data["conf"]):
        text = text.strip()
        if not text or text in _NOISE:
            continue
        try:
            if float(conf) < 40:
                continue
        except ValueError:
            continue
        if _NAME_RE.match(text):
            names.append(text)
    return names


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
            print(f"{folder}({pos}): {len(names)}명 인식")
    return positions


def main():
    _check_deps()
    root = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ROOT
    if not os.path.isdir(root):
        raise SystemExit(f"스크린샷 폴더를 찾을 수 없습니다: {root}")

    positions = scan_root(root)
    if not positions:
        print("인식된 선수 이름이 없습니다 — 스크린샷이 최신인지, 폴더 구조가 맞는지 확인하세요.")
        return

    print_report(apply_positions(positions))


if __name__ == "__main__":
    main()
