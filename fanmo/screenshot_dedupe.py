"""9UP 스크롤+캡쳐 매크로가 남긴 스크린샷에서 의미 없는 중복을 걸러낸다.

캡쳐 매크로(SHIFT+F1)는 "스크린샷 1장 + 아래로 스크롤" 을 6번 반복하는데, 선수 명단이
6페이지보다 짧으면 끝에 닿은 뒤에도 계속 찍어서 같은 화면이 여러 장 쌓인다. 실패해서
bat을 다시 돌린 경우에도 이전 실행 사진과 거의 같은 게 또 쌓인다.

바이트가 완전히 같은 파일만 지우는 걸로는 부족하다 — 스크롤이 멈춘 뒤에도 애니메이션이나
스크롤바 때문에 픽셀 몇 개가 달라서 "눈으로는 같은데 파일은 다른" 사진이 남는다. 그래서
카드 그리드 영역만 잘라 dHash(64비트)로 비교한다.

임계값 10은 실측으로 정했다(2026-09-16 오늘 찍힌 사진 전부의 쌍별 거리 분포):
    같은 화면이 반복된 쌍 : 0, 3, 4, 6, 8
    실제로 다른 페이지인 쌍: 13 이상 (대부분 20~35)
경계가 넓게 벌어져 있어서 10으로 자르면 실제 페이지를 지울 위험은 거의 없다.

사용법:
    python screenshot_dedupe.py <폴더>          중복 삭제(하위 포지션 폴더까지 전부)
    python screenshot_dedupe.py --at-bottom <폴더>
        가장 최근에 찍힌 사진 2장이 사실상 같은지 판정한다(= 스크롤이 명단 끝에 닿아서
        더 찍어봐야 소용 없는 상태인지). 끝이면 "BOTTOM"을 찍고 0, 아직 남았으면 "MORE"를
        찍고 1로 끝난다 — daily_position_capture.ps1이 캡쳐를 한 번 더 돌릴지 판단할 때 쓴다.
"""
from __future__ import annotations

import hashlib
import os
import sys

# 카드 그리드 영역만 본다 — 왼쪽 사이드바/상단 탭 같은 고정 UI가 비교를 지배하면
# 서로 다른 페이지도 비슷해 보인다(analyze_position_screenshots.py의 좌표와 같은 기준).
CROP = (687, 480, 2469, 1400)
HASH_SIZE = 8          # dHash 8x8 -> 64비트
DISTANCE_THRESHOLD = 10


def _dhash(path: str) -> int:
    from PIL import Image

    img = Image.open(path).convert("L").crop(CROP)
    img = img.resize((HASH_SIZE + 1, HASH_SIZE), Image.LANCZOS)
    px = list(img.getdata())
    bits = 0
    for row in range(HASH_SIZE):
        for col in range(HASH_SIZE):
            left = px[row * (HASH_SIZE + 1) + col]
            right = px[row * (HASH_SIZE + 1) + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return bits


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _image_files(folder: str) -> list[str]:
    return sorted(
        (os.path.join(folder, f) for f in os.listdir(folder)
         if f.lower().endswith((".png", ".jpg", ".jpeg"))),
        key=lambda p: os.path.getmtime(p),
    )


def dedupe_folder(folder: str) -> int:
    """오래된 파일을 원본으로 남기고, 그와 사실상 같은 뒤 파일들을 지운다."""
    files = _image_files(folder)
    if len(files) < 2:
        return 0

    kept: list[tuple[int, str]] = []   # (dhash, 바이트해시)
    removed = 0
    for path in files:
        with open(path, "rb") as f:
            byte_hash = hashlib.sha256(f.read()).hexdigest()
        try:
            h = _dhash(path)
        except Exception as exc:  # noqa: BLE001
            print(f"  {os.path.basename(path)} 읽기 실패, 건너뜀: {exc}")
            continue

        is_dupe = any(
            bh == byte_hash or _hamming(h, kh) <= DISTANCE_THRESHOLD
            for kh, bh in kept
        )
        if is_dupe:
            os.remove(path)
            removed += 1
        else:
            kept.append((h, byte_hash))
    return removed


def at_bottom(folder: str) -> bool:
    """가장 최근 사진 2장이 사실상 같으면 True(스크롤이 명단 끝에 닿았다는 뜻)."""
    files = _image_files(folder)
    if len(files) < 2:
        return False
    last, prev = files[-1], files[-2]
    try:
        return _hamming(_dhash(last), _dhash(prev)) <= DISTANCE_THRESHOLD
    except Exception:  # noqa: BLE001
        return False


def main():
    args = sys.argv[1:]
    if args and args[0] == "--at-bottom":
        folder = args[1]
        done = at_bottom(folder)
        print("BOTTOM" if done else "MORE")
        raise SystemExit(0 if done else 1)

    if not args:
        raise SystemExit("사용법: python screenshot_dedupe.py <폴더> [또는 --at-bottom <폴더>]")

    root = args[0]
    if not os.path.isdir(root):
        raise SystemExit(f"폴더를 찾을 수 없습니다: {root}")

    # 폴더 자체에 이미지가 있으면 그것만, 아니면 하위 포지션 폴더들을 훑는다.
    targets = [root] if any(
        f.lower().endswith(".png") for f in os.listdir(root)
    ) else [
        os.path.join(root, d) for d in sorted(os.listdir(root))
        if os.path.isdir(os.path.join(root, d))
    ]

    total = 0
    for folder in targets:
        before = len(_image_files(folder))
        removed = dedupe_folder(folder)
        total += removed
        if before:
            print(f"{os.path.basename(folder):<4} {before}장 -> {before - removed}장 (중복 {removed}장 삭제)")
    print(f"총 {total}장 삭제")


if __name__ == "__main__":
    main()
