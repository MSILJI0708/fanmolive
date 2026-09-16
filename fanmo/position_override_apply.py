"""{포지션(한글): [선수명, ...]} 형태의 딕셔너리를 position_db.json의 manual_position으로
반영하는 공통 로직. apply_playerdb_positions.py(수작업으로 옮겨 적은 최초 스크린샷)와
analyze_position_screenshots.py(OCR 자동화) 둘 다 이 함수를 쓴다.

이름만으로 매칭하되, position_db.json 안에 이미 동명이인이 있는 이름은 스크린샷/OCR
결과만으로 어느 쪽인지 구분이 안 되므로 건너뛴다 — 틀리게 넣느니 그대로 두는 게 낫다.
"""
from __future__ import annotations

from position import load_db, save_db

# 동명이인은 이름만으로 구분이 안 돼서 기본적으로 건너뛰지만, 사람이 한 번 확인해서
# 확정한 건은 여기에 적어두면 그 뒤로는 자동 반영된다. 9UP은 선수 한 명에게 포지션을
# 하나만 주므로 (이름, 포지션) 조합이면 사람을 특정할 수 있다.
#   (이름, 9UP 포지션) -> player_code
_HOMONYM_OVERRIDES = {
    # 박건우: NC 79215(실제 우익수)와 롯데 55509(실제 포수). 9UP에서 한 명은 포수,
    # 다른 한 명은 지명타자로 나온다. 포수 명단에 외야수가 올라올 리는 없고, 지명타자
    # 카드 사진은 두산 시절 박건우(= 두산->NC로 옮긴 그 선수)로 확인됨.
    ("박건우", "포수"): "55509",
    ("박건우", "지명타자"): "79215",
    # 김민석: 두산 53554(실제 좌익수)와 KT 54097(실제 포수). 좌익수 카드 사진에서
    # 두산 유니폼(헬멧의 "두산 베어스")이 확인됨.
    ("김민석", "좌익수"): "53554",
}


def apply_positions(positions: dict[str, list[str]]) -> dict:
    db = load_db()
    players = db["players"]

    by_name: dict[str, list[str]] = {}
    for code, rec in players.items():
        by_name.setdefault(rec["name"], []).append(code)

    applied, ambiguous, not_found, conflicts = [], [], [], []
    seen_code_to_pos: dict[str, str] = {}

    for pos, names in positions.items():
        for name in names:
            codes = by_name.get(name)
            if not codes:
                not_found.append(f"{name}({pos})")
                continue
            if len(codes) > 1:
                override = _HOMONYM_OVERRIDES.get((name, pos))
                if override not in codes:
                    ambiguous.append(f"{name}({pos}) -> {codes}")
                    continue
                code = override
            else:
                code = codes[0]
            if code in seen_code_to_pos and seen_code_to_pos[code] != pos:
                conflicts.append(f"{name}: {seen_code_to_pos[code]} vs {pos} (같은 선수코드 {code})")
                continue
            seen_code_to_pos[code] = pos
            rec = players[code]
            if rec.get("manual_position") != pos:
                rec["manual_position"] = pos
                rec["effective_position"] = pos
                applied.append(f"{name}({rec['team']}): {rec.get('auto_position')} -> {pos}")

    save_db(db)
    return {"applied": applied, "ambiguous": ambiguous, "not_found": not_found, "conflicts": conflicts}


def print_report(result: dict) -> None:
    print(f"적용됨: {len(result['applied'])}건")
    for a in result["applied"]:
        print("  ", a)
    print(f"\nDB에 동명이인이 있어 건너뜀: {len(result['ambiguous'])}건")
    for a in result["ambiguous"]:
        print("  ", a)
    print(f"\n같은 선수가 서로 다른 포지션에 나와 충돌: {len(result['conflicts'])}건")
    for c in result["conflicts"]:
        print("  ", c)
    print(f"\nposition_db.json에 없는 이름(최근 14일 무출전 등): {len(result['not_found'])}건")
