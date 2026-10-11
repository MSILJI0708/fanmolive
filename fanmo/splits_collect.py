"""2026시즌 투타 상대 유형별 상대 전적 수집기.

타자는 "상대한 투수가 어떤 유형이었나"(우투/좌투/언더), 투수는 "상대한 타자가 어떤
유형이었나"(우타/좌타)로 나눠서 성적을 쌓는다.

왜 중계(relay)를 다시 긁는가
---------------------------
박스스코어는 경기 단위 합계라 "이 안타를 누구한테 쳤는지"가 없다. 반면 네이버 중계는
이벤트마다 currentGameState.pitcher/batter를 player_code로 박아주기 때문에, 추정 없이
타석 단위로 투수-타자를 정확히 짝지을 수 있다. 그래서 유형별 분해는 중계로만 가능하다.

이벤트 타입 (실측으로 확인함)
  1  투구          8  타석 시작        2  교체
  13 타석 결과(득점 없음)              23 타석 결과(그 타석에서 득점 발생)
  14 주자 이동/아웃(도루·견제사 등)    24 주자 홈인
  홈런과 적시타는 전부 23으로 오므로 13만 보면 통째로 누락된다.

유형 판정
  엔트리의 hittype이 "우투우타"처럼 [던지는 손][치는 손] 두 쌍으로 온다.
  투수: 우투 / 좌투 / 우언·좌언 -> 언더
  타자: 우타 / 좌타 / 양타 -> 투수가 던진 손의 반대쪽(사용자 지정 전제)

득점과 실점의 귀속
  공식 규칙대로 "그 주자를 내보낸 투수"에게 실점을 매긴다. 주자가 출루한 타석을
  기억해 뒀다가(runner_origin) 홈인할 때 그 타석의 투수/타자 유형으로 귀속하므로,
  타자의 득점과 투수의 실점이 같은 기준으로 떨어진다.

사용법: python splits_collect.py [--year 2026] [--out splits_2026.json]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from naver_fantasy_score import fetch_json, fetch_record, fetch_schedule, innings_to_outs

HERE = os.path.dirname(os.path.abspath(__file__))
RELAY_URL = "https://api-gw.sports.naver.com/schedule/games/{game_id}/relay?inning={inning}"
RECORD_URL = "https://api-gw.sports.naver.com/schedule/games/{game_id}/record"

PITCHER_KINDS = ("우투", "좌투", "언더")
BATTER_KINDS = ("우타", "좌타")

# ── 결과 문구 판정 ────────────────────────────────────────────────────────
# 실제 중계 문구를 2026시즌 표본에서 전수로 뽑아 만든 규칙이다(추측 아님).
_HIT_1B = ("1루타", "내야안타", "번트안타")


def pitcher_kind(hittype: str) -> str | None:
    """'우투우타' -> '우투'. 언더는 좌우를 묶어 '언더' 하나로 본다(사용자 지정)."""
    if not hittype or len(hittype) < 2:
        return None
    head = hittype[:2]
    if head in ("우언", "좌언"):
        return "언더"
    return head if head in ("우투", "좌투") else None


def throws_right(hittype: str) -> bool | None:
    """투수가 오른손으로 던지는가. 양타 타자의 타석 방향을 정하는 데 쓴다."""
    if not hittype:
        return None
    return hittype[0] == "우" if hittype[0] in ("우", "좌") else None


def batter_kind(bat_hittype: str, pit_hittype: str) -> str | None:
    """타자 유형. 양타는 '항상 투수가 던진 손의 반대쪽 타석'이라는 전제로 환산한다."""
    if not bat_hittype or len(bat_hittype) < 4:
        return None
    tail = bat_hittype[2:4]
    if tail == "양타":
        r = throws_right(pit_hittype)
        if r is None:
            return None
        return "좌타" if r else "우타"
    return tail if tail in ("우타", "좌타") else None


def classify_pa(desc: str) -> dict:
    """타석 결과 한 줄을 타격 기록으로 환산한다. 반환 키는 집계 항목 이름 그대로."""
    r = {k: 0 for k in ("h", "d", "t", "hr", "tb", "bb", "ibb", "hbp", "so", "sh", "sf", "ab")}
    if "고의4구" in desc:
        r["bb"] = r["ibb"] = 1
        return r
    if "볼넷" in desc:
        r["bb"] = 1
        return r
    if "몸에 맞는 볼" in desc:
        r["hbp"] = 1
        return r
    if "희생번트" in desc:
        r["sh"] = 1
        return r
    if "희생플라이" in desc:
        r["sf"] = 1
        return r
    # 낫아웃은 삼진이면서 출루할 수 있지만, 타자 기록상 삼진·타수로 잡는 건 같다.
    # 쓰리번트 실패도 공식 기록은 삼진이다("박승욱 : 포수 쓰리번트 아웃").
    if "삼진" in desc or "낫 아웃" in desc or "낫아웃" in desc or "쓰리번트" in desc:
        r["so"] = r["ab"] = 1
        return r

    r["ab"] = 1
    if "홈런" in desc:
        r.update(h=1, hr=1, tb=4)
    elif "3루타" in desc:
        r.update(h=1, t=1, tb=3)
    elif "2루타" in desc:
        r.update(h=1, d=1, tb=2)
    elif any(k in desc for k in _HIT_1B):
        r.update(h=1, tb=1)
    return r


_BAT_RE = re.compile(r"^(?P<name>\S+) : (?P<desc>.+)$")
_RUNNER_RE = re.compile(r"^(?P<base>[123])루주자 (?P<name>\S+) : (?P<desc>.+)$")
# 타석 도중에 투수가 바뀌었을 때, 교체 시점 카운트가 아래 다섯 가지이고 그 타석이
# 볼넷으로 끝나면 그 볼넷(과 그 주자의 실점 책임)은 전임 투수 몫이다(공식야구규칙
# 10.16(i)). 안타·아웃·삼진 등 다른 결과는 카운트와 무관하게 구원투수 몫이다(실측:
# 2볼0스트라이크에서 교체된 뒤의 삼진이 공식 기록에서 구원투수 몫이었다).
def reached_base(desc: str, st: dict) -> bool:
    """타자가 살아 나갔는지. 문구에 "아웃"이 들어가도 출루인 결과가 있다.

    낫아웃 폭투·포일이 그렇다("윤도현 : 스트라이크 낫아웃 폭투"). 이걸 아웃으로 보면
    그 주자의 책임 투수가 기록되지 않아, 나중에 들어온 점수가 아무에게도 안 붙는다.
    """
    if st["h"] or st["bb"] or st["hbp"] or "출루" in desc:
        return True
    # "한지윤 : 좌익수 희생플라이 (좌익수 실책)"처럼 실책으로 살아 나간 희생타.
    if "실책" in desc and "아웃" not in desc:
        return True
    if "낫아웃" in desc or "낫 아웃" in desc:
        # "포수 스트라이크 낫 아웃 (…1루 터치아웃)"처럼 실제로 잡힌 경우와 가른다.
        return "아웃" not in desc.replace("낫아웃", "").replace("낫 아웃", "")
    return False


_PREV_PITCHER_COUNTS = {(2, 0), (2, 1), (3, 0), (3, 1), (3, 2)}
# 투수 교체는 "투수 A : 투수 B (으)로 교체"뿐 아니라 "좌익수 김민혁 : 투수 주권 (으)로
# 교체"처럼 수비 이동을 함께 적은 형태로도 온다. 왼쪽만 보고 거르면 그 교체를 놓친다.
_PITCHER_SWAP_RE = re.compile(r" : 투수 \S+ \(으\)로 교체$")

# 2스트라이크에서 타자가 교체되고 대타가 삼진으로 물러나면, 삼진과 타수는 먼저
# 타석에 섰던 타자 몫이다(공식야구규칙 10.15(b)). 그 밖의 결과는 대타 몫이다.
_PINCH_BAT_RE = re.compile(r"^\d번타자 \S+ : 대타 \S+ \(으\)로 교체$")

_PINCH_RUN_RE = re.compile(r"^[123]루주자 (?P<out>\S+) : 대주자 (?P<in>\S+) \(으\)로 교체$")


def fetch_relay_groups(game_id: str, max_innings: int = 15) -> list[dict]:
    """이닝별로 나뉜 중계를 한 줄로 펼치고, 선수 유형표를 함께 만든다.

    주의: entry와 lineup은 서로 겹치지 않는 별개 명단이다(실측 확인). entry는 그 경기에
    출전하지 않은 벤치 대기 선수, lineup이 실제로 뛴 선수다. 게다가 유형 필드 이름이
    entry는 hittype, lineup은 hitType으로 대소문자가 다르다. 둘 다 긁지 않으면 정작
    경기에 나온 선수의 유형을 하나도 못 구한다.
    """
    groups, entry = [], {}
    for inn in range(1, max_innings + 1):
        try:
            data = fetch_json(RELAY_URL.format(game_id=game_id, inning=inn))
        except Exception:  # noqa: BLE001
            break
        d = (data.get("result") or {}).get("textRelayData") or {}
        for side, field in (("homeEntry", "hittype"), ("awayEntry", "hittype"),
                            ("homeLineup", "hitType"), ("awayLineup", "hitType")):
            played = side.endswith("Lineup")
            for kind in ("batter", "pitcher"):
                for p in (d.get(side) or {}).get(kind) or []:
                    code, ht = p.get("pcode"), p.get(field)
                    if not code:
                        continue
                    prev = entry.get(code) or {}
                    # 교체로 나중 이닝에만 나오는 선수가 있어 이닝마다 누적한다.
                    entry[code] = {"name": p.get("name") or prev.get("name"),
                                   "hittype": ht or prev.get("hittype"),
                                   "played": played or prev.get("played", False),
                                   # 두 팀에 같은 이름이 있을 때 주자를 가리는 데 쓴다.
                                   "side": "home" if side.startswith("home") else "away",
                                   "kind": kind if played else prev.get("kind", kind)}
        grs = d.get("textRelays") or []
        if not grs:
            break
        groups.extend(grs)

    # 중계는 한 이닝 안에서 "최신 타석이 맨 앞"인 역순으로 내려온다(실측). 그대로 읽으면
    # 주자의 홈인을 그 주자가 출루하기도 전에 처리하게 되어 실점 책임을 영영 못 찾는다.
    # 타석 순번(no)으로 오름차순 정렬해 실제 경기 진행 순서로 되돌린다.
    groups.sort(key=lambda g: (g.get("inn") or 0, g.get("no") or 0))
    return [{"entry": entry, "groups": _drop_replayed_halves(groups)}]


_ORDER_RE = re.compile(r"^(\d)번타자 ")


def _drop_replayed_halves(groups: list[dict]) -> list[dict]:
    """같은 타석이 두 번 실려 오는 경기를 한 벌로 줄인다.

    실측(20260513NCLT02026): 9회초가 통째로, 8회말은 5번타자부터 끝까지 다시 실려 왔다.
    앞 벌은 타석 결과가 비어 있거나 뒤 벌과 같은 내용이어서, 그대로 읽으면 그 구간의
    볼넷·삼진이 두 번 잡힌다. 한 반이닝에서 타순이 되감기고 그 타석의 결과가 앞 벌과
    같으면(또는 앞 벌이 결과 없이 끊겼으면) 재전송으로 보고 앞 벌을 버린다.
    """
    halves: dict[tuple, list[int]] = {}
    for i, g in enumerate(groups):
        halves.setdefault((g.get("inn"), g.get("homeOrAway")), []).append(i)

    drop: set[int] = set()
    for idxs in halves.values():
        seen: dict[int, tuple[int, int, tuple]] = {}
        nth = 0
        for pos, i in enumerate(idxs):
            opts = groups[i].get("textOptions") or []
            bats = [o.get("text") or "" for o in opts if o.get("type") == 8]
            res = tuple(o.get("text") or "" for o in opts if o.get("type") in (13, 23))
            nums = [int(m.group(1)) for m in map(_ORDER_RE.match, bats) if m]
            if not nums:
                continue
            nth += 1
            prev = seen.get(nums[0])
            # 타순이 한 바퀴(9타자)를 돌기 전에 되돌아왔고 그 타석 내용까지 겹치면
            # 재전송이다. 한 바퀴를 제대로 돈 경우는 간격이 9라서 걸리지 않는다.
            if prev and nth - prev[1] < 9 and (not prev[2] or not res or prev[2] == res):
                drop.update(idxs[prev[0]:pos])
                seen = {}
            seen[nums[0]] = (pos, nth, res)
    return [g for i, g in enumerate(groups) if i not in drop] if drop else groups


def parse_game(game_id: str) -> dict | None:
    """경기 하나를 타석 단위로 쪼개 유형별 집계 조각을 만든다."""
    packed = fetch_relay_groups(game_id)
    if not packed or not packed[0]["groups"]:
        return None
    entry, groups = packed[0]["entry"], packed[0]["groups"]
    if not entry:
        return None

    # 주자는 중계에 이름으로만 나오므로 이름->코드 표가 필요하다. 동명이인이 있을 때
    # 벤치에만 앉아 있던 선수까지 후보에 넣으면 "누구인지 못 가림"으로 기록이 통째로
    # 버려진다. 실제로 뛴 선수(lineup)가 있으면 그쪽만 후보로 본다.
    by_name: dict[str, list[str]] = defaultdict(list)
    for code, info in entry.items():
        if info.get("name"):
            by_name[info["name"]].append(code)
    name_to_code: dict[str, list[str]] = {}
    for nm, codes in by_name.items():
        played = [c for c in codes if (entry.get(c) or {}).get("played")]
        name_to_code[nm] = played or codes

    def ht(code):
        return (entry.get(code) or {}).get("hittype") or ""

    bat_rows: dict[tuple[str, str], dict] = {}
    pit_rows: dict[tuple[str, str], dict] = {}
    # 주자가 출루한 타석을 기억해 둔다 — 홈인할 때 "누가 내보낸 주자인가"로 실점을 매긴다.
    runner_origin: dict[str, tuple[str, str]] = {}
    pit_game_runs: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    def bat_cell(bcode, pkind):
        return bat_rows.setdefault((bcode, pkind), defaultdict(int))

    def pit_cell(pcode, bkind):
        return pit_rows.setdefault((pcode, bkind), defaultdict(int))

    half_key = None
    prev_out = 0
    cur_pa: dict | None = None   # 진행 중인 타석(타점을 누구에게 줄지 판단하는 데 쓴다)
    # 투수 실점 책임은 "누가 득점했나"가 아니라 "각 투수가 몇 명을 내보냈나"로 매긴다
    # (공식야구규칙 9.16(h) 코멘트: charge each pitcher with the number of runners he put
    # on base, rather than with the specific runners who scored). 그래서 주자 개인 추적과
    # 별도로, 출루 순서대로 쌓는 책임 큐를 반이닝마다 둔다.
    resp: list[tuple[str, str]] = []
    pa_resp: str | None = None  # 이 타석에 지금 던지고 있는 투수
    pa_walk_owner: str | None = None  # 볼넷으로 끝나면 떠안을 전임 투수(10.16(i))
    pa_reached = False          # 이 타석에서 타자가 살아 나갔는지
    pa_runner: str | None = None  # 이 타석에서 살아 나간 타자 이름
    pa_resulted = False         # 이 타석의 타구 처리(결과 이후 주자 이벤트) 중인지
    pa_error = False            # 그 처리 과정에 실책이 끼었는지
    pa_bat_owner: str | None = None  # 2스트라이크에서 물러난 타자(삼진을 떠안는다)
    for g in groups:
        # 반이닝이 바뀌면 누상의 주자는 모두 사라진다. 이걸 안 비우면 1회에 출루했던
        # 주자의 "출루시킨 투수"가 그대로 남아, 몇 이닝 뒤 동명의 주자가 득점할 때
        # 엉뚱한 투수에게 실점이 붙는다(실측: 김성윤 1·3회 출루가 7회 득점에 귀속됨).
        hk = (g.get("inn"), g.get("homeOrAway"))
        if hk != half_key:
            runner_origin.clear()
            resp.clear()
            prev_out, cur_pa, pa_resp, pa_reached = 0, None, None, False
            pa_bat_owner = pa_walk_owner = None
            half_key = hk

        for opt in g.get("textOptions") or []:
            ty = opt.get("type")
            cgs = opt.get("currentGameState") or {}
            pcode, bcode = cgs.get("pitcher"), cgs.get("batter")
            text = opt.get("text") or ""

            # 아웃카운트가 늘어난 만큼을 그 시점 투수의 "이 타자 유형 상대 아웃"으로 쌓는다.
            # 타자가 직접 아웃된 것뿐 아니라 주자가 잡힌 것도 투수의 이닝으로 들어간다.
            try:
                cur_out = int(cgs.get("out"))
            except (TypeError, ValueError):
                cur_out = prev_out
            if cur_out > prev_out and pcode and bcode:
                bk_o = batter_kind(ht(bcode), ht(pcode))
                if bk_o:
                    pit_cell(pcode, bk_o)["outs"] += cur_out - prev_out
                prev_out = cur_out

            if ty == 8 and pcode and bcode:
                # 타점은 "지금 타석에 선 타자"에게 붙는다. 타석 결과(13/23)에서 잡으면
                # 그 타석이 끝난 뒤라, 다음 타자 타석 도중 들어온 점수가 직전 타자에게
                # 잘못 붙는다(실측: 폭투 득점이 한 타석 앞 타자의 타점이 됐다).
                pk8 = pitcher_kind(ht(pcode))
                cur_pa = {"b": bcode, "pk": pk8} if pk8 else None
                pa_resp, pa_reached = pcode, False
                pa_runner, pa_resulted, pa_error = None, False, False
                # 대타가 들어오면 같은 타석이 "대타 오태곤"으로 한 번 더 열린다. 그때
                # 떠안을 타자를 지워버리면 10.15(b)를 적용할 수 없다.
                if not text.startswith("대타"):
                    pa_bat_owner = pa_walk_owner = None

            elif ty in (13, 23) and pcode and bcode:
                m = _BAT_RE.match(text)
                if not m:
                    continue
                desc = m.group("desc")
                st = classify_pa(desc)
                pa_resulted, pa_error = True, "실책" in desc
                # 타석 결과는 실제로 던진 투수 몫이되, 10.16(i)에 걸린 볼넷만 전임
                # 투수(rc)에게 간다. 투구이닝은 언제나 아웃을 잡은 투수에게 간다.
                rc = pa_walk_owner if (st["bb"] and pa_walk_owner) else pcode
                pk, bk = pitcher_kind(ht(rc)), batter_kind(ht(bcode), ht(rc))
                rbk = bk
                if not pk or not bk:
                    continue

                b = bat_cell(pa_bat_owner if (st["so"] and pa_bat_owner) else bcode, pk)
                b["pa"] += 1
                for k in ("h", "d", "t", "hr", "tb", "bb", "ibb", "hbp", "so", "sh", "sf", "ab"):
                    b[k] += st[k]

                p = pit_cell(rc, bk)
                p["tbf"] += 1
                p["h"] += st["h"]; p["d"] += st["d"]; p["t"] += st["t"]; p["hr"] += st["hr"]
                p["bb"] += st["bb"]; p["ibb"] += st["ibb"]; p["hbp"] += st["hbp"]; p["so"] += st["so"]

                # 홈런은 타자 본인이 곧바로 득점한다(주자 홈인 이벤트로 따로 오지 않음).
                if st["hr"] and rbk:
                    b["r"] += 1
                    b["rbi"] += 1
                    pit_cell(rc, rbk)["r"] += 1
                    pit_game_runs[rc][rbk] += 1
                    # 홈런 타자는 루상에 남지 않으므로 책임 큐에 넣지 않는다.

                # 병살타로 들어온 점수는 타점이 아니다. 반면 타자의 타구가 실책이 되어
                # 출루한 경우는 그 타구로 들어온 주자에게 타점이 인정된다(실측 확인) —
                # 타점에서 빼야 하는 "실책"은 타구가 아니라 득점 장면 쪽이다.
                if "병살" in desc:
                    cur_pa = None
                # 타자가 살아 나가면 그 주자의 출신 타석을 기록해 둔다.
                if reached_base(desc, st):
                    nm = m.group("name")
                    if not st["hr"] and rbk:
                        # 타자 쪽 득점은 실제 상대 투수 유형으로, 투수 쪽 실점은 책임
                        # 투수 토큰으로 갈라 들고 다닌다.
                        runner_origin[nm] = ((pcode, bk), (rc, rbk))
                        resp.append((rc, rbk))
                        pa_reached, pa_runner = True, nm

            elif ty in (14, 24) and pcode:
                # 14와 24는 "주자에게 일어난 일"로 성격이 같다. 24가 홈인 전용이 아니라는
                # 점이 중요하다 — 득점이 난 플레이에 딸린 주자 이벤트면 진루도 포스아웃도
                # 전부 24로 온다(실측: 한 선수의 "3루까지 진루"·"홈인"·"포스아웃"이 모두
                # 24였다). 타입이 아니라 문구로 갈라야 득점이 부풀지 않는다.
                m = _RUNNER_RE.match(text)
                if not m:
                    continue
                nm, desc = m.group("name"), m.group("desc")
                if pa_resulted and "실책" in desc:
                    pa_error = True
                codes = name_to_code.get(nm) or []
                if len(codes) > 1:
                    # 주자는 언제나 공격팀 타자다. 두 팀에 같은 이름이 함께 뛴 경기에서
                    # 이걸로 가리지 않으면 그 주자의 득점·도루가 통째로 버려진다(실측:
                    # 박건우 NC·KT, 김민석, 이재원 등 6건).
                    bat_side = "home" if str(g.get("homeOrAway")) == "1" else "away"
                    narrowed = [c for c in codes
                                if (entry.get(c) or {}).get("side") == bat_side
                                and (entry.get(c) or {}).get("kind") != "pitcher"]
                    codes = narrowed or codes
                pk = pitcher_kind(ht(pcode))

                if "홈인" in desc:
                    # 타자의 득점은 "그 주자가 실제로 누구를 상대로 출루했나"로 가른다
                    # (타자 쪽 표는 상대 투수 유형별 성적이므로 개인 추적이 맞다).
                    origin = runner_origin.pop(nm, None)
                    opk = pitcher_kind(ht(origin[0][0])) if origin else pk
                    if len(codes) == 1 and opk:
                        bat_cell(codes[0], opk)["r"] += 1
                    # 투수의 실투(폭투·보크)나 수비 실책으로 굴러들어온 점수는 타자가
                    # 만든 게 아니라 타점으로 치지 않는다.
                    # 홈스틸, 주자 스스로 판단해 뛰어든 득점("주자의 재치로 홈인"), 수비가
                    # 다른 주자를 잡는 사이 들어온 득점도 타자가 만든 게 아니다(실측: 셋
                    # 모두 공식 기록에서 타점 0).
                    if cur_pa and not any(x in desc for x in (
                            "실책", "폭투", "보크", "포일", "도루", "재치", "다른주자수비")):
                        bat_cell(cur_pa["b"], cur_pa["pk"])["rbi"] += 1
                    # 홈까지 훔친 것도 도루다("3루주자 … : 이중도루로 홈인"). 단 "이중도루
                    # 실패시 홈인"은 다른 주자가 잡히는 사이 들어온 것이라 도루가 아니다.
                    if (len(codes) == 1 and pk and "도루" in desc
                            and "무관심" not in desc and "실패" not in desc):
                        bat_cell(codes[0], pk)["sb"] += 1
                    # 투수 실점은 책임 큐의 맨 앞(가장 먼저 내보낸 주자 몫)에서 꺼낸다.
                    charged = resp.pop(0) if resp else (origin[1] if origin else None)
                    if charged:
                        opc, obk = charged
                        pit_cell(opc, obk)["r"] += 1
                        pit_game_runs[opc][obk] += 1
                    continue

                if len(codes) == 1 and pk:
                    # 무관심도루(수비가 잡을 생각이 없을 때의 진루)는 공식 기록상 도루가
                    # 아니다(실측: 김지찬 20260429 공식 0 / 중계 문구는 "무관심도루").
                    if "도루로" in desc and "무관심" not in desc:
                        bat_cell(codes[0], pk)["sb"] += 1
                    elif "도루실패" in desc:
                        bat_cell(codes[0], pk)["cs"] += 1
                # 아웃된 주자는 더 이상 득점할 수 없으므로 책임 추적에서 지운다.
                if "아웃" in desc:
                    org = runner_origin.pop(nm, None)
                    on_batted_ball = (pa_resulted and not pa_error and nm != pa_runner
                                      and "도루실패" not in desc and "견제사" not in desc)
                    if on_batted_ball and resp:
                        # 타구를 처리하는 과정에서 앞 주자가 잡힌 경우다(야수선택·포스
                        # 아웃·병살 모두). 잡힌 주자를 내보낸 투수의 책임은 그대로 남고
                        # 뒤 주자들이 자리를 메우므로(9.16(h)), 큐 맨 뒤를 버린다. 실책이
                        # 낀 플레이는 타자가 실책으로 살아 나간 것으로 기록되어 승계가
                        # 일어나지 않는다(실측 20260918LGKT02026).
                        resp.pop()
                    elif org and org[1] in resp:
                        # 견제사·도루실패처럼 그냥 잡힌 주자는 자기 몫만 사라진다.
                        resp.remove(org[1])
                    elif resp:
                        resp.pop()

            elif ty == 2:
                # 2스트라이크에서의 대타 교체: 삼진으로 끝나면 먼저 섰던 타자 몫이다.
                if bcode and _PINCH_BAT_RE.match(text) and cgs.get("strike") == "2":
                    pa_bat_owner = cur_pa["b"] if cur_pa else None

                # 타석 도중 투수 교체: 볼카운트로 이 타석의 책임 투수를 다시 가린다.
                if pcode and pa_resp and pcode != pa_resp and _PITCHER_SWAP_RE.search(text):
                    try:
                        cnt = (int(cgs.get("ball")), int(cgs.get("strike")))
                    except (TypeError, ValueError):
                        cnt = (0, 0)
                    if cnt in _PREV_PITCHER_COUNTS and pa_walk_owner is None:
                        pa_walk_owner = pa_resp
                    pa_resp = pcode

                # 대주자 교체: 나간 주자의 책임 투수를 들어온 주자가 그대로 물려받는다.
                m = _PINCH_RUN_RE.match(text)
                if m:
                    origin = runner_origin.pop(m.group("out"), None)
                    if origin:
                        runner_origin[m.group("in")] = origin
                    # 책임 큐는 사람이 아니라 머릿수라 대주자 교체로 바뀔 게 없다.

    # 자책점은 "실책이 없었다면" 가정이 들어간 기록원 판단이라 중계 문구만으로는 재현할
    # 수 없다. 그래서 경기별 공식 자책점(박스스코어)을 가져와, 그 경기에서 그 투수가
    # 유형별로 내준 실점 비율대로 나눈다. 시즌 합계는 공식과 정확히 맞고, 유형별 쪼개기만
    # 근사치다. 선수별 팀/이름도 이때 같이 챙긴다.
    meta: dict[str, dict] = {}
    pitcher_er: dict[str, int] = {}
    try:
        rd = fetch_record(game_id)
        info = rd.get("gameInfo") or {}
        team_of = {"home": info.get("hName", ""), "away": info.get("aName", "")}
        for side in ("home", "away"):
            for b in (rd.get("battersBoxscore") or {}).get(side) or []:
                if b.get("playerCode"):
                    meta[b["playerCode"]] = {"name": b.get("name"), "team": team_of[side]}
            for p in (rd.get("pitchersBoxscore") or {}).get(side) or []:
                if p.get("pcode"):
                    meta[p["pcode"]] = {"name": p.get("name"), "team": team_of[side]}
                    pitcher_er[p["pcode"]] = int(p.get("er") or 0)
                    starters = (rd.get("pitchersBoxscore") or {}).get(side) or []
                    meta[p["pcode"]]["role"] = "선발" if starters and starters[0] is p else "구원"
    except Exception as exc:  # noqa: BLE001
        print(f"  {game_id} 박스스코어 조회 실패(자책점 생략): {exc}")

    return {
        "game_id": game_id,
        "batters": {f"{c}|{k}": dict(v) for (c, k), v in bat_rows.items()},
        "pitchers": {f"{c}|{k}": dict(v) for (c, k), v in pit_rows.items()},
        "pitcher_runs": {c: dict(v) for c, v in pit_game_runs.items()},
        "pitcher_er": pitcher_er,
        "meta": meta,
    }


def collect_season(year: int, workers: int = 8, limit: int | None = None) -> list[dict]:
    """그 해 정규시즌 전 경기를 모은다.

    날짜 목록을 "우리가 이미 수집한 data_*.json"에서 뽑으면 안 된다. 그 목록은 LP 보드를
    돌린 날만 들어 있어서 시즌 전체를 덮지 못하고, 실제로 715경기 중 685경기만 잡혀
    선수마다 기록이 조금씩 비었다(실측). 시즌 전 기간을 날짜로 훑어야 빠짐이 없다.
    """
    import datetime

    start = datetime.date(year, 3, 1)
    end = min(datetime.date(year, 11, 30), datetime.date.today())
    dates = [(start + datetime.timedelta(days=i)).isoformat()
             for i in range((end - start).days + 1)]

    # 시범경기(kbo_e)와 올스타전(kbo_as)은 시즌 기록이 아니므로 뺀다. season_calendar.json이
    # 날짜별 라운드를 들고 있는데 만들어진 시점까지만 채워져 있어서, 거기 없는 최근 날짜는
    # 정규시즌으로 본다(시범경기는 3월 하순에 끝나므로 뒤쪽에서 섞일 일이 없다).
    skip: set[str] = set()
    cal_path = os.path.join(HERE, "season_calendar.json")
    if os.path.exists(cal_path):
        try:
            with open(cal_path, encoding="utf-8") as f:
                cal = json.load(f)
            skip = {d for d, v in cal.items()
                    if d.startswith(str(year)) and (v or {}).get("round") in ("kbo_e", "kbo_as")}
        except (OSError, ValueError):
            pass
    if skip:
        print(f"  시범경기·올스타 {len(skip)}일 제외")
    dates = [d for d in dates if d not in skip]

    game_ids: list[str] = []

    def _sched(d):
        try:
            return [g["gameId"] for g in fetch_schedule(d)
                    if g.get("statusCode") == "RESULT" and not g.get("cancel")]
        except Exception:  # noqa: BLE001
            return []

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for ids in ex.map(_sched, dates):
            game_ids.extend(ids)
    game_ids = sorted(set(game_ids))
    if limit:
        game_ids = game_ids[:limit]
    print(f"{year}시즌 경기 {len(game_ids)}건 수집 시작 (병렬 {workers})")

    out, done = [], 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for res in ex.map(_safe_parse, game_ids):
            done += 1
            if res:
                out.append(res)
            if done % 50 == 0:
                print(f"  {done}/{len(game_ids)}  ({round(time.time()-t0)}초)")
    print(f"완료: {len(out)}경기 / {round(time.time()-t0)}초")
    return out


def _safe_parse(gid: str):
    try:
        return parse_game(gid)
    except Exception as exc:  # noqa: BLE001
        print(f"  {gid} 처리 실패: {exc}")
        return None


def main():
    ap = argparse.ArgumentParser(description="투타 상대 유형별 전적 수집")
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--limit", type=int, default=None, help="앞에서 N경기만(테스트용)")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    games = collect_season(args.year, workers=args.workers, limit=args.limit)
    out = args.out or os.path.join(HERE, f"splits_raw_{args.year}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(games, f, ensure_ascii=False)
    print(f"저장: {out} ({len(games)}경기)")


if __name__ == "__main__":
    main()
