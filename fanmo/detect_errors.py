"""수집된 KBO 데이터 전반의 정합성을 점검해 이상 징후를 한 곳에 모아 보여준다.

두 가지를 같이 본다.
  1) 자체판정(SAVE/HOLD/WIN/LOSS) 정확도 — naver_fantasy_score.py가 공식 wls가 붙는
     순간마다 "wls가 없었다면 우리 로직이 뭐라고 판정했을지"를 항상 계산해 정답과
     비교하고, 틀린 경우만 self_pred_mismatches.json에 남겨둔다. 여기서는 그 파일을
     그대로 읽어 같이 보여준다(오늘 다룬 세이브/홀드/승/패 규칙이 새 경기에서도 계속
     맞는지 상시 감시하는 부분).
  2) 그 외 데이터 구조/값 자체의 일반적인 정합성 — round 필드 누락·이상값, player_code
     누락, 이닝 표기 형식, 통계값 범위 이상(음수, 안타>타수 등), 같은 선수 중복 행,
     동시에 성립할 수 없는 승/패/세이브/홀드 조합 등. 오늘 있었던 이닝 표기 혼용·올스타전
     오염·playerCode 누락 같은 사례들이 전부 이 범주라, 특정 사례에 묶이지 않고 늘 같은
     기준으로 전체 파일을 훑는다.

사용법:
    python detect_errors.py              # data_????????.json 전체
    python detect_errors.py --date 20260912   # 특정 날짜만
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))

# roundCode 값 중 지금까지 실제로 관측된 것들 + None(구버전 데이터라 필드 자체가 없던 경우).
# 새로운 값이 나타나면(네이버가 포스트시즌 라운드를 세분화하는 등) 조용히 넘기지 않고
# 걸러내기 위해 화이트리스트 방식으로 둔다. kbo_ps_wd=와일드카드, kbo_ps_sp=준플레이오프,
# kbo_ps_po=플레이오프, kbo_ps_ks=한국시리즈(2025 시즌 실제 데이터에서 확인됨).
VALID_ROUNDS = {"kbo_r", "kbo_as", "kbo_e",
                "kbo_ps_wd", "kbo_ps_sp", "kbo_ps_po", "kbo_ps_ks", "kbo_ps_f", None}
INNING_RE = re.compile(r"^\d+\.[012]$")
# 한 투수에게 동시에 성립할 수 없는 조합(세이브+홀드는 한 경기 안에서 같은 투수가 둘 다
# 받을 수 없고, 승리와 패전·세이브도 마찬가지).
EXCLUSIVE_PITCHER_FLAGS = [("WIN", "LOSS"), ("SAVE", "HOLD"), ("WIN", "SAVE"), ("WIN", "HOLD")]


def _issue(date: str, kind: str, detail: str) -> dict:
    return {"date": date, "kind": kind, "detail": detail}


def check_file(fp: str) -> list[dict]:
    date = os.path.basename(fp)[len("data_"):-len(".json")]
    try:
        with open(fp, encoding="utf-8") as f:
            d = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        return [_issue(date, "JSON_PARSE_FAIL", str(exc))]

    issues = []
    if d.get("round") not in VALID_ROUNDS:
        issues.append(_issue(date, "UNKNOWN_ROUND", f"round={d.get('round')!r}"))

    # player_code가 같은 행이 하루에 여럿 있는 건 그 자체로는 이상하지 않다 — 더블헤더로
    # 같은 상대와 하루 두 경기를 뛰거나(실제 확인됨: 2025-05-10 LG 타자들), 한 팀에
    # 동명이인이 있는 경우(2025-03-26 삼성 이승현 둘)가 정상적으로 존재한다. 두 경기의
    # 스탯이 다르면 그런 정상적인 경우고, stat 딕셔너리가 완전히 똑같은 행이 두 번
    # 들어있을 때만 "같은 경기 결과를 실수로 두 번 저장한" 진짜 버그로 본다.
    seen: dict[tuple, dict] = {}
    for row in d.get("batters", []):
        name, team = row.get("name"), row.get("team")
        pc = row.get("player_code")
        if not pc:
            issues.append(_issue(date, "MISSING_PLAYER_CODE", f"타자 {name}({team})"))
        else:
            key = (team, pc)
            prev = seen.get(key)
            if prev is not None and prev.get("stat") == row.get("stat") and prev.get("ab") == row.get("ab"):
                issues.append(_issue(date, "DUPLICATE_ROW", f"타자 {name}({team}) player_code={pc} 완전 동일 행 중복"))
            seen[key] = row
        s = row.get("stat", {})
        ab = row.get("ab", 0)
        if s.get("H", 0) > ab:
            issues.append(_issue(date, "STAT_RANGE", f"타자 {name}({team}) H={s.get('H')} > AB={ab}"))
        for k, v in s.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v < 0:
                issues.append(_issue(date, "NEGATIVE_STAT", f"타자 {name}({team}) {k}={v}"))

    seen = {}
    for row in d.get("pitchers", []):
        name, team = row.get("name"), row.get("team")
        pc = row.get("player_code")
        if not pc:
            issues.append(_issue(date, "MISSING_PLAYER_CODE", f"투수 {name}({team})"))
        else:
            key = (team, pc)
            prev = seen.get(key)
            if prev is not None and prev.get("stat") == row.get("stat"):
                issues.append(_issue(date, "DUPLICATE_ROW", f"투수 {name}({team}) player_code={pc} 완전 동일 행 중복"))
            seen[key] = row
        inn = row.get("inn", "")
        if not INNING_RE.match(str(inn)):
            issues.append(_issue(date, "INNING_FORMAT", f"투수 {name}({team}) inn={inn!r}"))
        s = row.get("stat", {})
        for k, v in s.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v < 0:
                issues.append(_issue(date, "NEGATIVE_STAT", f"투수 {name}({team}) {k}={v}"))
        for a, b in EXCLUSIVE_PITCHER_FLAGS:
            if s.get(a) and s.get(b):
                issues.append(_issue(date, "CONFLICTING_FLAGS", f"투수 {name}({team}) {a}·{b} 동시 성립"))

    return issues


def load_self_pred_mismatches() -> list[dict]:
    fp = os.path.join(HERE, "self_pred_mismatches.json")
    try:
        with open(fp, encoding="utf-8") as f:
            return list(json.load(f).values())
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", help="YYYYMMDD, 지정하면 그 날짜 파일만 점검")
    args = ap.parse_args()

    if args.date:
        files = [os.path.join(HERE, f"data_{args.date}.json")]
        files = [fp for fp in files if os.path.exists(fp)]
    else:
        files = sorted(glob.glob(os.path.join(HERE, "data_????????.json")))

    all_issues = []
    for fp in files:
        all_issues.extend(check_file(fp))

    mismatches = load_self_pred_mismatches()

    # MISSING_PLAYER_CODE는 2025년 구버전 데이터의 이미 알려진 한계라 건수만 알면 되고,
    # 개별 사례를 전부 저장소에 커밋하면 파일이 수 MB로 불어난다(실제로 2.6만 건).
    # 그 외 유형은 새로 생긴 진짜 이슈일 수 있어 유형별로 최대 30건까지만 상세를 남긴다.
    by_kind = Counter(it["kind"] for it in all_issues)
    KNOWN_NOISY_KINDS = {"MISSING_PLAYER_CODE"}
    SAMPLE_CAP = 30
    saved_issues = []
    for kind in by_kind:
        matching = [it for it in all_issues if it["kind"] == kind]
        if kind in KNOWN_NOISY_KINDS:
            continue
        saved_issues.extend(matching[:SAMPLE_CAP])

    report = {
        "files_checked": len(files),
        "issue_counts_by_kind": dict(by_kind),
        "issues": saved_issues,
        "self_pred_mismatches": mismatches,
    }
    out_path = os.path.join(HERE, "error_report.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)

    print(f"{len(files)}개 파일 점검 완료 — 데이터 정합성 이슈 {len(all_issues)}건, "
          f"자체판정 불일치 {len(mismatches)}건 (상세: error_report.json, 유형별 최대 {SAMPLE_CAP}건까지 저장)")
    print("  유형별 건수: " + ", ".join(f"{k}={v}" for k, v in by_kind.most_common()))
    for kind in by_kind:
        if kind in KNOWN_NOISY_KINDS:
            continue
        sample = [it for it in saved_issues if it["kind"] == kind][:15]
        for it in sample:
            print(f"  [{it['kind']}] {it['date']} {it['detail']}")
        if by_kind[kind] > len(sample):
            print(f"  ... {kind} 외 {by_kind[kind] - len(sample)}건")

    for m in mismatches[:20]:
        print(f"  [SELF_PRED_MISMATCH] {m['game_id']} {m['name']}({m['team']}) "
              f"wls={m['official_wls']!r} 예측={m['predicted']} 정답={m['official']}")
    if len(mismatches) > 20:
        print(f"  ... 외 {len(mismatches) - 20}건")


if __name__ == "__main__":
    main()
