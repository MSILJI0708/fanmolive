"""경기 중인 KBO 경기의 "수집 시점 상황"을 뽑아 둔다.

보드에 찍히는 LP는 파이프라인이 마지막으로 수집한 시점의 값이라, 지금 TV로 보고 있는
실시간 상황과는 몇 분 차이가 난다. 그 차이 때문에 "왜 방금 안타를 쳤는데 LP가 그대로냐"는
혼란이 생기므로, LP를 계산한 바로 그 시점의 이닝·점수·주자·투타를 함께 저장해 보드
사이드바에 같이 보여준다. 브라우저가 네이버를 직접 부르면 LP와 시점이 어긋나므로
반드시 수집할 때 같이 저장해야 한다.

경기가 끝나면(statusCode=RESULT) 더 이상 의미가 없으므로 저장하지 않는다.
"""
from __future__ import annotations

from naver_fantasy_score import fetch_json

GAME_URL = "https://api-gw.sports.naver.com/schedule/games/{game_id}"
RELAY_URL = "https://api-gw.sports.naver.com/schedule/games/{game_id}/relay?inning={inning}"


def _player_names(relay: dict) -> dict:
    """선수코드 -> 이름. 교체로 나온 선수까지 잡으려면 라인업과 엔트리를 모두 훑어야 한다."""
    names = {}
    for side in ("home", "away"):
        for block in (relay.get(f"{side}Lineup") or {}, relay.get(f"{side}Entry") or {}):
            for role in ("batter", "pitcher"):
                for p in block.get(role) or []:
                    code = str(p.get("pcode") or "")
                    if code:
                        names[code] = p.get("name")
    return names


def fetch_live_state(game_id: str) -> dict | None:
    """진행 중인 경기의 현재 상황. 아직 시작 안 했거나 이미 끝났으면 None."""
    try:
        game = fetch_json(GAME_URL.format(game_id=game_id))["result"]["game"]
    except Exception:  # noqa: BLE001
        return None
    if game.get("statusCode") != "STARTED" or game.get("cancel"):
        return None

    inning_text = game.get("currentInning") or game.get("statusInfo") or ""
    # "5회말" 에서 이닝 숫자만 뽑아 릴레이를 요청한다(릴레이는 이닝별로 나뉘어 있다).
    digits = "".join(ch for ch in inning_text if ch.isdigit())
    inning_no = int(digits) if digits else 1

    try:
        relay = fetch_json(RELAY_URL.format(game_id=game_id, inning=inning_no))["result"]["textRelayData"]
        state = relay.get("currentGameState") or {}
        names = _player_names(relay)
    except Exception:  # noqa: BLE001
        state, names = {}, {}

    return {
        "game_id": game_id,
        "inning": inning_text,
        "away_team": game.get("awayTeamName"),
        "home_team": game.get("homeTeamName"),
        "away_score": int(game.get("awayTeamScore") or 0),
        "home_score": int(game.get("homeTeamScore") or 0),
        "out": int(state.get("out") or 0),
        "ball": int(state.get("ball") or 0),
        "strike": int(state.get("strike") or 0),
        # 주자는 각 루의 0/1 플래그로 온다
        "bases": [bool(int(state.get(f"base{i}") or 0)) for i in (1, 2, 3)],
        "pitcher": names.get(str(state.get("pitcher") or "")),
        "batter": names.get(str(state.get("batter") or "")),
        "stadium": game.get("stadium"),
    }


def collect_live_states(game_ids) -> list[dict]:
    out = []
    for gid in game_ids:
        try:
            st = fetch_live_state(gid)
        except Exception:  # noqa: BLE001
            continue
        if st:
            out.append(st)
    return out
