"""
경기 중계(텍스트 릴레이) 기반 심화 기록 추출기
================================================
naver_fantasy_score.py가 쓰는 박스스코어 API는 팀 단위 합계와 타자 개인 합계만 준다.
그런데 네이버는 그와 별개로 "텍스트 중계"(타석마다 공 하나하나를 중계하는 텍스트) API를
따로 제공하고, 그 안에는 다음이 다 들어있다:

  - 매 타석 시점의 주자 상황(1루/2루/3루에 있는 주자가 "몇 번타자"인지, 0이면 빈 베이스)
  - 투수/포수/각 포지션 교체 이벤트("투수 A : 투수 B (으)로 교체" 등)
  - 아웃 처리 시 관여한 수비수 체인("유격수->2루수->1루수 송구아웃")
  - 도루 성공/실패, 폭투, 실책, 희생번트/희생플라이 여부가 문장으로 명시됨

이걸 이용하면 박스스코어만으로는 특정 선수에게 귀속시킬 수 없었던 다음 항목들을
계산할 수 있다:
  - 투수의 피2루타/피3루타 (그 타석에서 수비 중이던 투수가 누구인지 추적)
  - 포수의 도루 저지/허용 (그 타석에서 포수가 누구인지 추적)
  - 투수의 승계주자 실점 허용/막음 (교체 시점의 주자를 물려받아, 그 이닝이 끝날 때까지
    그 주자가 득점했는지 추적)
  - 야수의 보살(어시스트)/외야수 보살/더블 플레이 가담 (아웃 체인에 이름 대신 포지션이
    적히므로, 포지션별 현재 수비수를 추적해서 이름으로 환원)

한계: 삼중살(트리플 플레이)은 규칙이 명시돼 있지만 실제 경기에서 관측된 예시가 없어
파싱 로직은 있지만 검증되지 않았다. 보살은 "OO->OO 송구아웃"처럼 체인이 텍스트에 명시된
경우만 인정하며, 문장으로 설명되지 않는 애매한 케이스는 세지 않는다.
"""

from __future__ import annotations

import re
from collections import defaultdict

from naver_fantasy_score import BATTER_POINTS, PITCHER_POINTS, fetch_json
from position import FIELDING_CHARS

RELAY_URL = "https://api-gw.sports.naver.com/schedule/games/{game_id}/relay?inning={inning}"

FIELDING_POSITIONS = set(FIELDING_CHARS.values())  # {'1루수','2루수',...,'포수'}
OUTFIELD_POSITIONS = {"좌익수", "중견수", "우익수"}

_SUB_RE = re.compile(r"^(?P<out>.+?) : (?P<in_label>\S+) (?P<in_name>\S+) \(으\)로 교체$")
_PLAY_RE = re.compile(r"^(?P<batter>\S+?) : (?P<desc>.+)$")
_CHAIN_RE = re.compile(r"\(([^)]+)\)$")
_RUN_RE = re.compile(r"^(?P<base>[123])루주자 (?P<name>\S+) : 홈인$")
_SB_RE = re.compile(r"^[123]루주자 (?P<name>\S+) : 도루로 (?:[123]루까지 진루|홈인)$")
_CS_RE = re.compile(r"^[123]루주자 (?P<name>\S+) : 도루실패아웃 \((?P<chain>[^)]+)\)$")
_PICKOFF_RE = re.compile(r"^[123]루주자 (?P<name>\S+) : 견제사아웃 \((?P<who>투수|포수) 견제")
_HOME_RE = re.compile(r"^[123]루주자 \S+ : 홈인$")
# "1루주자 김현수 : 포스아웃 (유격수->2루수 2루 터치아웃)", "3루주자 X : 태그아웃 (좌익수->포수 태그아웃)"
# 처럼 이름에 공백이 없는 주자가 타구 처리 체인으로 베이스에서 아웃되는 경우. _PLAY_RE는
# "이름 : 결과"에서 이름을 공백 없는 한 토큰으로 잡기 때문에 "N루주자 이름"(토큰 2개)인 이 줄은
# 원래 어떤 정규식에도 안 걸려서 그냥 통째로 무시되고 있었다(외야수가 송구로 주자를 잡아내는
# 보살 상황이 여기서 제일 많이 나오는데 그게 전부 누락되고 있었던 것).
_RUNNER_OUT_RE = re.compile(r"^[123]루주자 \S+ : (?:포스아웃|태그아웃) \((?P<chain>[^)]+)\)$")
_PLAIN_ADVANCE_RE = re.compile(r"^[123]루주자 \S+ : (?:[123]루까지 진루|홈인)$")
_ADVANCE_MARKERS = ("폭투", "도루", "실책", "보크", "낫")
_INNING_MARK_RE = re.compile(r"^(\d+)회(초|말) (.+) 공격$")


def fetch_full_relay(game_id: str, max_innings: int = 15) -> list[dict]:
    """전체 이닝의 텍스트 릴레이를 시간순으로 펼쳐서 반환한다."""
    events = []
    for inn in range(1, max_innings + 1):
        try:
            data = fetch_json(RELAY_URL.format(game_id=game_id, inning=inn))
        except Exception:  # noqa: BLE001
            break
        groups = (data.get("result") or {}).get("textRelayData", {}).get("textRelays") or []
        if not groups:
            break
        for g in groups:
            no = g.get("no")
            for sub_idx, opt in enumerate(g.get("textOptions") or []):
                cgs = opt.get("currentGameState") or {}
                events.append({
                    "no": no, "sub": sub_idx, "inn": inn,
                    "half": g.get("homeOrAway"),  # '0'=원정 공격(홈 수비), '1'=홈 공격(원정 수비)
                    "out": cgs.get("out"),
                    "base": (cgs.get("base1") or "0", cgs.get("base2") or "0", cgs.get("base3") or "0"),
                    "home_score": int(cgs.get("homeScore") or 0),
                    "away_score": int(cgs.get("awayScore") or 0),
                    "text": opt.get("text", ""),
                })
    events.sort(key=lambda e: (e["no"], e["sub"]))
    return events


_CHAIN_SUFFIX_RE = re.compile(r"\s*(?:[123]루\s*)?(?:송구아웃|터치아웃|포구아웃|태그아웃)$")


def _split_chain(chain_text: str) -> list[str]:
    """'(유격수->2루수->1루수 송구아웃)' → ['유격수','2루수','1루수']. 체인이 없으면 (단일 수비수) [].
    '유격수->2루수 2루 터치아웃'처럼 마지막 키워드 앞에 베이스 번호가 붙는 경우도 있어 그 부분까지
    통째로 떼어낸다(안 떼면 '2루수 2루'가 위치명과 안 맞아 체인이 통째로 날아가 버린다).
    투수도 순서 유지를 위해 남겨둔다 — "1루수->2루수->투수" 체인에서 투수를 걸러내 버리면
    "마지막으로 송구를 보낸 야수"가 2루수가 아니라 1루수로 잘못 계산된다(투수 본인은 보살
    스탯이 없어 defense 딕셔너리에 없으므로, 크레딧 조회 시 자연히 걸러진다)."""
    text = _CHAIN_SUFFIX_RE.sub("", chain_text)
    parts = [p.strip() for p in text.split("->")]
    parts = [p for p in parts if p in FIELDING_POSITIONS or p == "투수"]
    return parts if len(parts) >= 2 else []


def classify_relay_desc(desc: str) -> dict[str, int]:
    """타석 결과 문장 하나에서 타자 스탯 태그를 뽑는다(naver_fantasy_score.classify_pa의 relay
    텍스트 버전). 병살은 GO와 안 겹치게(원본과 동일하게) 배타적으로 잡고, 희생플라이/희생번트는
    원본처럼 FO/GO에도 같이 더해진다."""
    tags = {"H": 0, "2B": 0, "3B": 0, "HR": 0, "BB": 0, "HBP": 0, "K": 0,
            "FO": 0, "GO": 0, "GDP": 0, "SACFLY": 0, "LD": 0}
    if "실책" in desc and "출루" in desc:
        # "유격수 플라이 실책으로 출루"처럼 수비 실책으로 살아나간 경우 — 아웃이 아니므로
        # "플라이"/"땅볼" 같은 하위 키워드가 우연히 걸려 뜬공·땅볼 아웃으로 오분류되면 안 된다.
        # 타자 본인에게는 어차피 점수가 없는 이벤트라 전부 0으로 둔다(실책 자체는 별도 경로로 집계).
        # "출루" 여부로 판단해야 한다 — "중견수 희생플라이 (중견수 실책)"처럼 "아웃" 단어 없이도
        # 실제로는 타자가 아웃된(희생플라이가 성립한) 경우가 있어서(실책은 그 다음 송구 등에서
        # 발생), "아웃" 단어 유무로 판단하면 이런 진짜 희생플라이까지 통째로 0점 처리돼버린다.
        return tags
    if "홈런" in desc:
        tags["H"] = 1
        tags["HR"] = 1
    elif "3루타" in desc:
        tags["H"] = 1
        tags["3B"] = 1
    elif "2루타" in desc:
        tags["H"] = 1
        tags["2B"] = 1
    elif "1루타" in desc or "안타" in desc:
        tags["H"] = 1
    elif "몸에 맞는" in desc:
        tags["HBP"] = 1
    elif "볼넷" in desc or "고의4구" in desc:
        # "자동 고의4구"(고의사구)도 볼넷과 동일하게 채점된다 — box score의 bb 필드에도
        # 고의사구가 포함되는데, 여기서 "볼넷"이라는 단어가 안 들어가 있어 그동안 통째로
        # 미분류(전부 0점)로 빠지면서 팝업에서 "기타 보정"으로만 나타났었다.
        tags["BB"] = 1
    elif "삼진" in desc or "스트라이크 낫 아웃" in desc:
        tags["K"] = 1
    elif "병살" in desc:
        tags["GDP"] = 1
        # 병살타는 기본적으로 땅볼 타구이므로 GO 페널티도 함께 적용된다(box score 쪽
        # process_game에서 GO 스탯에 GDP 개수를 합산하는 것과 동일한 규칙). 여기서도 GO를
        # 같이 세워야 팝업 합계가 실제 LP(-25+-10=-35)와 정확히 맞는다.
        tags["GO"] = 1
    elif "희생플라이" in desc:
        tags["SACFLY"] = 1
        tags["FO"] = 1
    elif "땅볼" in desc or "희생번트" in desc:
        tags["GO"] = 1
    elif "라인드라이브" in desc:
        # 직선타(라인드라이브)로 잡힌 아웃은 뜬공 아웃(FO) 페널티에 포함되지 않는다 —
        # 9up 판타지 점수와 대조해서 확인됨. 중계 텍스트는 "직선타"가 아니라 항상
        # "라인드라이브"로 표기한다(박스스코어 코드 쪽 약자 "직"과 다른 표현이라 따로 확인 필요).
        # 아웃 자체는 발생했으니 LD로 남겨서 투수 쪽 이닝별 아웃카운트 표시에는 반영하되,
        # 타자 점수에는 영향이 없다(BATTER_POINTS에 없음).
        tags["LD"] = 1
    elif "플라이" in desc:
        tags["FO"] = 1
    elif "번트" in desc:
        # 희생번트(위에서 이미 처리)도 번트안타(1루타/안타 체크에서 이미 처리)도 아닌
        # 순수 "번트 아웃"(비희생 번트 시도가 실패해 아웃된 경우) — 일반 스윙 땅볼 아웃과
        # 달리 페널티를 주지 않는다. 아무 태그도 안 세워 이 타석을 0점으로 남긴다.
        pass
    elif "아웃" in desc:
        tags["GO"] = 1  # 분류 못한 아웃은 보수적으로 땅볼 취급
    return tags


def _is_productive_out_desc(desc: str) -> bool:
    """희생번트를 포함해 '진루를 시키는 타구'로 아웃된 경우(땅볼/희생번트) 여부.
    병살은 별도 페널티 대상이라 제외하고, 뜬공·희생플라이·삼진은 애초에 이 함수에서 안 걸린다."""
    return ("땅볼" in desc or "희생번트" in desc) and "병살" not in desc


def _detect_productive_outs(events: list[dict]) -> dict[str, int]:
    """같은 타석(no) 안에서, 아웃된 타자의 타구로 다른 주자가 '표시 없이'(폭투/도루/실책/보크가
    아니라) 진루했다면 그 타자에게 진루타(구 희생번트) 크레딧을 준다. 번트든 아니든 판정 방식은
    동일하다 — Naver 박스스코어의 '희' 플래그보다 이게 원래 규정("진루를 시키는 타구 모두 포함")에
    더 가깝다."""
    by_no: dict = {}
    order: list = []
    for ev in events:
        no = ev["no"]
        if no not in by_no:
            by_no[no] = []
            order.append(no)
        by_no[no].append(ev["text"])

    credit: dict[str, int] = defaultdict(int)
    for no in order:
        texts = by_no[no]
        batter = None
        for t in texts:
            m = _PLAY_RE.match(t)
            if m and _is_productive_out_desc(m.group("desc")):
                batter = m.group("batter")
                break
        if not batter:
            continue
        for t in texts:
            if _PLAIN_ADVANCE_RE.match(t) and not any(mk in t for mk in _ADVANCE_MARKERS):
                credit[batter] += 1
                break
    return dict(credit)


def compute_relay_stats(
    events: list[dict],
    home_starting_defense: dict,
    away_starting_defense: dict,
    home_starting_pitcher: str | None,
    away_starting_pitcher: str | None,
) -> dict:
    """
    events: fetch_full_relay()가 반환한, 이미 가져온 이벤트 목록(중복 호출 방지를 위해
    호출자가 한 번만 fetch해서 넘긴다).
    home_starting_defense / away_starting_defense: {'포수': '조형우', '유격수': '이재현', ...}
    (경기 시작 시점의 포지션별 선발 수비수, 투수 제외 — build_starting_defense로 생성.
    투수는 DH 룰 때문에 타자 박스스코어에 없으므로 pitchersBoxscore[0]['name']을 따로 넘긴다)

    half 표기: '0'=원정팀 공격(홈팀이 수비 중), '1'=홈팀 공격(원정팀이 수비 중)

    반환: {
      'pitcher_extra': {name: {'2B_A':n,'3B_A':n,'INHERITED_SCORED':n,'INHERITED_STRANDED':n,
                                'CS_A':n,'SB_A':n,'PICKOFF_A':n}},
      'catcher_events': {name: [{'type':'CS_CATCHER'|'SB_ALLOWED_CATCHER', 'pos':'포수'}, ...]},
      'fielding_events': {name: [{'type':'ASSIST'|'OF_ASSIST'|'DP'|'TP', 'pos':실제 수비 위치}, ...]},
      'batter_extra': {name: {'ADVANCE':n}},
      'timeline': {name: [{'inn':int, 'text':str, 'points':int, 'tags':{stat:count}}, ...]},
      'pitcher_entry_margin': {name: int},  # 구원투수가 등판한 순간의 (자팀-상대) 점수차. 세이브
                                             # 기회 판정용(조건1: 0<margin<=3 and 1이닝 이상 / 조건3:
                                             # 3이닝 이상 무관. "동점주자가 누상/타석"인 조건2는 미구현)
      'final_score': {'home': int, 'away': int} | None,  # 승/패 판정용 최종 스코어
    }
    catcher_events/fielding_events는 "그 순간 실제로 뛴 포지션"을 이벤트마다 태그해 원본 그대로
    반환한다 — 판타지 카드 등록 포지션과 다른 포지션에서 난 수비 기록을 어떻게 인정할지는
    naver_fantasy_score.py의 필터링 단계(및 프론트엔드의 사용자 선택)에서 결정한다. 그래서 더블
    플레이/트리플 플레이도 "게임당 1회"로 미리 접지 않고 매 발생 건을 그대로 내보낸다(필터링 후
    남는 이벤트 중 하나라도 있으면 1회 인정하는 계산은 호출자 몫).

    timeline은 "선수를 클릭하면 타석/수비별로 무슨 일이 있었고 몇 점을 얻었는지" 팝업용 원장이다.
    시간순 그대로 담아서 게임당 1회 상한(DP/TP 등) 같은 후처리는 하지 않으므로, 화면에서 보여줄 때
    실제 LP와 차이가 나면 그 차액을 "기타 보정" 한 줄로 reconcile해야 한다(naver_fantasy_score.py
    쪽에서 처리).
    """
    batter_extra = _detect_productive_outs(events)
    group_texts: dict = defaultdict(list)
    for ev in events:
        group_texts[ev["no"]].append(ev["text"])

    pitcher_extra: dict = defaultdict(lambda: defaultdict(int))
    catcher_events: dict = defaultdict(list)
    fielding_events: dict = defaultdict(list)
    # timeline은 (이름, 역할) 튜플로 키를 잡는다 — 이름만으로 키를 잡으면 두 팀에 동명이인
    # 투수/타자가 있을 때(예: 한쪽 팀 투수와 다른 쪽 팀 타자가 우연히 이름이 같은 경우) 서로
    # 무관한 두 선수의 기록이 한 timeline 리스트에 섞여 들어가 버린다(실제로 SSG-KIA전에서
    # 양 팀에 동명이인 "김민준" 투수/타자가 있어 이 문제가 발생한 걸 확인함). "bat"은 타자
    # 본인의 타석/주루/수비(보살 등) 기록, "pitch"는 투수 본인의 피안타/사사구/아웃카운트 등
    # 기록이라 역할이 겹칠 일이 없다.
    timeline: dict = defaultdict(list)

    def tl(name: str, role: str) -> list:
        return timeline[(name, role)]
    # 희생번트도 번트안타도 아닌 "번트 아웃"(비희생 번트 시도가 실패해 아웃된 경우) 횟수.
    # 박스스코어 코드만으로는 이걸 일반 스윙 땅볼 아웃과 구분할 수 없어서(둘 다 그냥
    # "N땅"으로만 나옴) 중계 텍스트로 잡아낸 만큼을 나중에 GO 집계에서 빼준다.
    bunt_out: dict = defaultdict(int)
    # 세이브 기회 판정용: 구원투수가 등판한 "순간"의 (자기 팀 점수 - 상대 팀 점수) 마진.
    # 선발은 여기 안 걸리는 게 맞다(등판 자체가 '교체'로 안 잡히니까).
    pitcher_entry_margin: dict = {}
    # 자책점을 "이닝별"로 보여주기 위한 추적: 주자 이름 -> 그 주자를 출루시킨 투수.
    # 이후 그 주자가 득점하면 이 투수에게 "자책점 후보"를 그 득점이 일어난 이닝에 매긴다.
    # (진짜 자책/비자책 판정은 박스스코어에만 있어서, 상한은 naver_fantasy_score.py에서
    # 박스스코어의 er 합계로 다시 자른다 — 여기서는 후보만 시간순으로 모아둔다)
    run_origin: dict[str, str] = {}
    earned_run_events: dict = defaultdict(list)

    defense = {"0": dict(home_starting_defense), "1": dict(away_starting_defense)}
    current_pitcher = {"0": home_starting_pitcher, "1": away_starting_pitcher}
    # half -> {slot(타순번호): 그 주자를 물려받은 투수 이름} — 투수 등판 시점 주자만 등록되고,
    # 해당 투수 본인이 내보낸 주자는 여기 들어가지 않는다(그건 그냥 자책점으로 잡힘)
    pending_inherited: dict[str, dict[str, str]] = {"0": {}, "1": {}}
    prev_base = {"0": ("0", "0", "0"), "1": ("0", "0", "0")}

    for ev in events:
        half = ev["half"]
        text = ev["text"]
        base = ev["base"]

        if _INNING_MARK_RE.match(text):
            # 새 하프이닝 시작 → 지난 하프이닝에 남아있던 승계주자는 실점 없이 막은 것으로 확정
            for half_key in ("0", "1"):
                for pitcher in pending_inherited[half_key].values():
                    pitcher_extra[pitcher]["INHERITED_STRANDED"] += 1
                    tl(pitcher, "pitch").append({
                        "inn": ev["inn"], "text": "승계주자 실점 막음",
                        "points": PITCHER_POINTS["INHERITED_STRANDED"], "tags": {"INHERITED_STRANDED": 1},
                    })
                pending_inherited[half_key] = {}
            prev_base = {"0": ("0", "0", "0"), "1": ("0", "0", "0")}
            continue

        m_sub = _SUB_RE.match(text)
        if m_sub:
            in_label, in_name = m_sub.group("in_label"), m_sub.group("in_name")
            if in_label == "투수":
                # 새로 등판하는 투수가 이 순간 이미 나가 있던 주자를 승계주자로 물려받는다
                # (이미 다른 투수 소속으로 등록된 slot은 원래 투수 귀속을 그대로 유지)
                for slot in base:
                    if slot != "0" and slot not in pending_inherited[half]:
                        pending_inherited[half][slot] = in_name
                current_pitcher[half] = in_name
                if in_name not in pitcher_entry_margin:
                    # half='0'이면 수비팀=홈, half='1'이면 수비팀=원정
                    margin = (ev["home_score"] - ev["away_score"]) if half == "0" else (ev["away_score"] - ev["home_score"])
                    pitcher_entry_margin[in_name] = margin
            elif in_label in FIELDING_POSITIONS:
                defense[half][in_label] = in_name
            prev_base[half] = base
            continue

        m_run = _RUN_RE.match(text)
        if m_run:
            runner = m_run.group("name")
            slot = prev_base[half][int(m_run.group("base")) - 1]
            pitcher = pending_inherited[half].pop(slot, None)
            if pitcher:
                pitcher_extra[pitcher]["INHERITED_SCORED"] += 1
                tl(pitcher, "pitch").append({
                    "inn": ev["inn"], "text": f"승계주자 {runner} 실점 허용",
                    "points": PITCHER_POINTS["INHERITED_SCORED"], "tags": {"INHERITED_SCORED": 1},
                })
            tl(runner, "bat").append({
                "inn": ev["inn"], "text": "득점", "points": BATTER_POINTS["R"], "tags": {"R": 1},
            })
            origin = run_origin.pop(runner, None)
            if origin:
                earned_run_events[origin].append({"inn": ev["inn"], "runner": runner})
            prev_base[half] = base
            continue

        m_sb = _SB_RE.match(text)
        if m_sb:
            runner = m_sb.group("name")
            tl(runner, "bat").append({
                "inn": ev["inn"], "text": "도루 성공", "points": BATTER_POINTS["SB"], "tags": {"SB": 1},
            })
            catcher = defense[half].get("포수")
            if catcher:
                catcher_events[catcher].append({"type": "SB_ALLOWED_CATCHER", "pos": "포수"})
                tl(catcher, "bat").append({
                    "inn": ev["inn"], "text": f"도루 허용 ({runner})",
                    "points": BATTER_POINTS["SB_ALLOWED_CATCHER"], "tags": {"SB_ALLOWED_CATCHER": 1},
                })
            pitcher = current_pitcher[half]
            if pitcher:
                pitcher_extra[pitcher]["SB_A"] += 1
                tl(pitcher, "pitch").append({
                    "inn": ev["inn"], "text": f"도루 허용 ({runner})",
                    "points": PITCHER_POINTS["SB_ALLOWED"], "tags": {"SB_ALLOWED": 1},
                })
            prev_base[half] = base
            continue

        m_cs = _CS_RE.match(text)
        if m_cs:
            runner = m_cs.group("name")
            tl(runner, "bat").append({
                "inn": ev["inn"], "text": "도루 실패(아웃)", "points": BATTER_POINTS["CS"], "tags": {"CS": 1},
            })
            catcher = defense[half].get("포수")
            if catcher:
                catcher_events[catcher].append({"type": "CS_CATCHER", "pos": "포수"})
                tl(catcher, "bat").append({
                    "inn": ev["inn"], "text": f"도루 저지 ({runner})",
                    "points": BATTER_POINTS["CS_CATCHER"], "tags": {"CS_CATCHER": 1},
                })
            pitcher = current_pitcher[half]
            if pitcher:
                pitcher_extra[pitcher]["CS_A"] += 1
                tl(pitcher, "pitch").append({
                    "inn": ev["inn"], "text": f"도루 저지 ({runner})",
                    "points": PITCHER_POINTS["CS_A"], "tags": {"CS_A": 1},
                })
            prev_base[half] = base
            continue

        m_pickoff = _PICKOFF_RE.match(text)
        if m_pickoff:
            runner = m_pickoff.group("name")
            tl(runner, "bat").append({
                "inn": ev["inn"], "text": "견제사(아웃)", "points": BATTER_POINTS["PICKOFF"], "tags": {"PICKOFF": 1},
            })
            # "포수 견제"(포수가 던진 견제)는 투수의 견제사로 치지 않고, "투수 견제"만 인정
            if m_pickoff.group("who") == "투수":
                pitcher = current_pitcher[half]
                if pitcher:
                    tl(pitcher, "pitch").append({
                        "inn": ev["inn"], "text": f"견제사 ({runner})",
                        "points": PITCHER_POINTS["PICKOFF_A"], "tags": {"PICKOFF_A": 1},
                    })
                    pitcher_extra[pitcher]["PICKOFF_A"] += 1
            prev_base[half] = base
            continue

        m_runner_out = _RUNNER_OUT_RE.match(text)
        if m_runner_out:
            # 여기는 _split_chain을 그대로 쓰지 않는다 — 타자 자신의 뜬공/땅볼과 달리, 주자를
            # 베이스에서 잡아내는 플레이는 "유격수 2루 터치아웃"처럼 야수 혼자(포스아웃) 처리해도
            # 보살로 인정해야 해서, _split_chain의 "체인 길이 2 이상만" 제약을 적용하면 안 된다.
            raw = _CHAIN_SUFFIX_RE.sub("", m_runner_out.group("chain"))
            parts = [p.strip() for p in raw.split("->")]
            parts = [p for p in parts if p in FIELDING_POSITIONS or p == "투수"]
            # 이 포스아웃 자체의 문구엔 "병살"/"삼중살"이 안 붙지만(타자 쪽 줄에만 붙음),
            # 같은 타석(no) 안에 병살/삼중살 문구가 있으면 이 주자 포스아웃도 그 병살/삼중살의
            # 일부다 — 그럴 땐 보살 대신, 관여한 야수 전원에게 병살/삼중살 가담을 준다
            # (다른 야수들과 동일하게 배타적 처리; 1경기 1회 상한은 score_batter에서 적용).
            group = group_texts[ev["no"]]
            is_dp_group = any("병살" in t for t in group)
            is_tp_group = any("삼중살" in t for t in group)
            if parts and (is_dp_group or is_tp_group):
                for pos in parts:
                    fielder = defense[half].get(pos)
                    if not fielder:
                        continue
                    if is_dp_group:
                        fielding_events[fielder].append({"type": "DP", "pos": pos})
                        tl(fielder, "bat").append({
                            "inn": ev["inn"], "text": f"병살 가담 ({pos}, 주자 아웃)",
                            "points": BATTER_POINTS["DP_FIELD"], "tags": {"DP_FIELD": 1},
                        })
                    if is_tp_group:
                        fielding_events[fielder].append({"type": "TP", "pos": pos})
                        tl(fielder, "bat").append({
                            "inn": ev["inn"], "text": f"삼중살 가담 ({pos}, 주자 아웃)",
                            "points": BATTER_POINTS["TP_FIELD"], "tags": {"TP_FIELD": 1},
                        })
            elif parts:
                assist_pos = parts[-2] if len(parts) >= 2 else parts[0]
                fielder = defense[half].get(assist_pos)
                if fielder:
                    etype = "OF_ASSIST" if assist_pos in OUTFIELD_POSITIONS else "ASSIST"
                    fielding_events[fielder].append({"type": etype, "pos": assist_pos})
                    tl(fielder, "bat").append({
                        "inn": ev["inn"], "text": f"보살 ({assist_pos}, 주자 아웃)",
                        "points": BATTER_POINTS[etype], "tags": {etype: 1},
                    })
            prev_base[half] = base
            continue

        m_play = _PLAY_RE.match(text)
        if m_play:
            desc = m_play.group("desc")
            batter = m_play.group("batter")
            if "2루타" in desc:
                p = current_pitcher[half]
                if p:
                    pitcher_extra[p]["2B_A"] += 1
                    tl(p, "pitch").append({
                        "inn": ev["inn"], "text": f"피2루타 ({batter})",
                        "points": PITCHER_POINTS["2B_A"], "tags": {"2B_A": 1},
                    })
            elif "3루타" in desc:
                p = current_pitcher[half]
                if p:
                    pitcher_extra[p]["3B_A"] += 1
                    tl(p, "pitch").append({
                        "inn": ev["inn"], "text": f"피3루타 ({batter})",
                        "points": PITCHER_POINTS["3B_A"], "tags": {"3B_A": 1},
                    })

            bat_tags = classify_relay_desc(desc)
            # 희생번트도 번트안타도 아닌 "번트 아웃"(비희생 번트 시도 실패) — 박스스코어 코드로는
            # 일반 스윙 땅볼 아웃과 구분이 안 돼서, 여기서 잡은 만큼 나중에 GO 집계에서 빼준다.
            is_bunt_out = "번트" in desc and "희생번트" not in desc and "안타" not in desc and "아웃" in desc
            if is_bunt_out:
                bunt_out[batter] += 1
                tl(batter, "bat").append({
                    "inn": ev["inn"], "text": desc, "points": 0, "tags": {},
                })
                # 스퀴즈 번트처럼 타자는 아웃당해도 그 사이 주자가 홈에 들어오는 드문 경우 대비
                rbi = sum(1 for t in group_texts[ev["no"]] if _HOME_RE.match(t))
                if rbi:
                    tl(batter, "bat").append({
                        "inn": ev["inn"], "text": f"타점 {rbi}개", "points": rbi * BATTER_POINTS.get("RBI", 0),
                        "tags": {"RBI": rbi},
                    })
            elif any(bat_tags.values()):
                pts = sum(bat_tags[k] * BATTER_POINTS.get(k, 0) for k in bat_tags)
                tl(batter, "bat").append({
                    "inn": ev["inn"], "text": desc, "points": pts,
                    "tags": {k: v for k, v in bat_tags.items() if v},
                })
                rbi = sum(1 for t in group_texts[ev["no"]] if _HOME_RE.match(t))
                if bat_tags["HR"]:
                    tl(batter, "bat").append({
                        "inn": ev["inn"], "text": "득점 (홈런)", "points": BATTER_POINTS["R"], "tags": {"R": 1},
                    })
                    rbi += 1  # 홈런은 다른 주자뿐 아니라 타자 자신의 득점도 타점으로 잡힌다
                if rbi:
                    tl(batter, "bat").append({
                        "inn": ev["inn"], "text": f"타점 {rbi}개", "points": rbi * BATTER_POINTS.get("RBI", 0),
                        "tags": {"RBI": rbi},
                    })

                # 투수 쪽도 타자와 같은 타석을 "상대 성적"으로 이닝별 타임라인에 남긴다
                # (아웃카운트는 병살이면 2개, 그 외 아웃성 결과는 1개, 안타/볼넷/사구는 0개)
                p = current_pitcher[half]
                if p:
                    if bat_tags["HR"]:
                        # 홈런은 타자 본인이 그 자리에서 득점까지 확정되므로 별도 조회 없이 바로 기록
                        earned_run_events[p].append({"inn": ev["inn"], "runner": batter})
                    elif bat_tags["H"] or bat_tags["BB"] or bat_tags["HBP"]:
                        run_origin[batter] = p
                    if bat_tags["H"]:
                        tl(p, "pitch").append({
                            "inn": ev["inn"], "text": f"피안타 ({batter})",
                            "points": PITCHER_POINTS["H"], "tags": {"H": 1},
                        })
                    if bat_tags["HR"]:
                        tl(p, "pitch").append({
                            "inn": ev["inn"], "text": f"피홈런 ({batter})",
                            "points": PITCHER_POINTS["HR"], "tags": {"HR": 1},
                        })
                    if bat_tags["BB"]:
                        tl(p, "pitch").append({
                            "inn": ev["inn"], "text": f"볼넷 허용 ({batter})",
                            "points": PITCHER_POINTS["BB"], "tags": {"BB": 1},
                        })
                    if bat_tags["HBP"]:
                        tl(p, "pitch").append({
                            "inn": ev["inn"], "text": f"사구 허용 ({batter})",
                            "points": PITCHER_POINTS["HBP"], "tags": {"HBP": 1},
                        })
                    if bat_tags["K"]:
                        tl(p, "pitch").append({
                            "inn": ev["inn"], "text": f"탈삼진 ({batter})",
                            "points": PITCHER_POINTS["K"], "tags": {"K": 1},
                        })
                    outs_this_play = 2 if bat_tags["GDP"] else (1 if (bat_tags["K"] or bat_tags["FO"] or bat_tags["GO"] or bat_tags["LD"]) else 0)
                    if outs_this_play:
                        tl(p, "pitch").append({
                            "inn": ev["inn"], "text": f"아웃카운트 {outs_this_play}개 ({batter})",
                            "points": outs_this_play * PITCHER_POINTS["OUT"], "tags": {"OUT": outs_this_play},
                        })

            m_chain = _CHAIN_RE.search(desc)
            chain = _split_chain(m_chain.group(1)) if m_chain else []
            is_dp = "병살" in desc
            is_tp = "삼중살" in desc

            # 보살: 병살/삼중살은 별도 스탯(DP_FIELD/TP_FIELD)으로 채점하므로 여기서는 제외하고,
            # 타구를 처리해 아웃을 만든 플레이에서 "마지막으로 송구를 보낸 야수" 한 명에게만 준다.
            # 체인이 없는 단독 처리(뜬공을 그냥 잡거나, 1루수가 직접 베이스를 밟는 무보살 땅볼
            # 아웃 등)는 내야/외야 구분 없이 보살로 안 친다 — "무보살"이라는 말 그대로 송구 자체가
            # 없으면 보살이 아니다(9up 판타지 점수와 대조해서 실제로 확인됨: 무보살 처리를
            # 보살로 잘못 쳐주고 있던 게 여러 선수에게서 1~2점씩 차이를 만들고 있었음).
            if (bat_tags["FO"] or bat_tags["GO"]) and not is_dp and not is_tp:
                seq = chain if len(chain) >= 2 else []
                if seq:
                    assist_pos = seq[max(0, len(seq) - 2)]
                    fielder = defense[half].get(assist_pos)
                    if fielder:
                        etype = "OF_ASSIST" if assist_pos in OUTFIELD_POSITIONS else "ASSIST"
                        fielding_events[fielder].append({"type": etype, "pos": assist_pos})
                        tl(fielder, "bat").append({
                            "inn": ev["inn"], "text": f"보살 ({assist_pos}, {batter} 타석)",
                            "points": BATTER_POINTS[etype], "tags": {etype: 1},
                        })

            if chain and (is_dp or is_tp):
                for pos in chain:
                    fielder = defense[half].get(pos)
                    if not fielder:
                        continue
                    if is_dp:
                        fielding_events[fielder].append({"type": "DP", "pos": pos})
                        tl(fielder, "bat").append({
                            "inn": ev["inn"], "text": f"병살 가담 ({pos}, {batter} 타석)",
                            "points": BATTER_POINTS["DP_FIELD"], "tags": {"DP_FIELD": 1},
                        })
                    if is_tp:
                        fielding_events[fielder].append({"type": "TP", "pos": pos})
                        tl(fielder, "bat").append({
                            "inn": ev["inn"], "text": f"삼중살 가담 ({pos}, {batter} 타석)",
                            "points": BATTER_POINTS["TP_FIELD"], "tags": {"TP_FIELD": 1},
                        })

        prev_base[half] = base

    # 경기 마지막 하프이닝은 다음 "N회 공격" 표시줄이 없어서 루프 안에서 못 걸러진다 —
    # 남아있는 승계주자는 경기가 그렇게 끝난 것 자체가 실점 없이 막았다는 뜻이라 여기서 마저 정산한다.
    last_inn = events[-1]["inn"] if events else None
    for half_key in ("0", "1"):
        for pitcher in pending_inherited[half_key].values():
            pitcher_extra[pitcher]["INHERITED_STRANDED"] += 1
            tl(pitcher, "pitch").append({
                "inn": last_inn, "text": "승계주자 실점 막음(경기 종료)",
                "points": PITCHER_POINTS["INHERITED_STRANDED"], "tags": {"INHERITED_STRANDED": 1},
            })

    final_score = (
        {"home": events[-1]["home_score"], "away": events[-1]["away_score"]}
        if events else None
    )

    return {
        "pitcher_extra": {k: dict(v) for k, v in pitcher_extra.items()},
        "catcher_events": dict(catcher_events),
        "fielding_events": dict(fielding_events),
        "batter_extra": batter_extra,
        "timeline": {k: v for k, v in timeline.items()},
        "pitcher_entry_margin": pitcher_entry_margin,
        "final_score": final_score,
        "earned_run_events": {k: v for k, v in earned_run_events.items()},
        "bunt_out": dict(bunt_out),
    }


def build_starting_defense(batters_box_side: list[dict], substituted_in_names: set[str]) -> dict:
    """battersBoxscore의 한 팀 리스트에서, 교체로 들어온 선수가 아닌(=선발) 선수들의
    pos 문자열 첫 글자로 선발 수비 배치를 만든다."""
    defense = {}
    for p in batters_box_side:
        name = p.get("name", "")
        if name in substituted_in_names:
            continue
        pos = p.get("pos", "")
        if pos and pos[0] in FIELDING_CHARS:
            defense[FIELDING_CHARS[pos[0]]] = name
    return defense


def collect_substituted_in_names(events: list[dict]) -> set[str]:
    names = set()
    for ev in events:
        m = _SUB_RE.match(ev["text"])
        if m:
            names.add(m.group("in_name"))
    return names
