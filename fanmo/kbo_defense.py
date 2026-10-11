"""KBO 공식 기록실에서 선수별 수비 기록(수비이닝·실책)을 가져온다.

왜 공식 기록을 쓰는가
--------------------
수비이닝과 실책은 "상대 투수가 누구였나"로 쪼갤 수 있는 기록이 아니다(수비 중에는
상대 투수가 없다). 그래서 유형별 표가 아니라 시즌 합계 칸에 넣는데, 그럴 거면 중계
텍스트로 근사하지 말고 공식 숫자를 그대로 쓰는 게 맞다.

한 선수가 여러 포지션을 보면 포지션마다 행이 따로 나오므로 선수 단위로 합산한다.
수비이닝은 "1153 1/3"처럼 분수 표기로 오기 때문에 아웃카운트로 바꿔서 더한다.

사용법: python kbo_defense.py [--season 2026] [--out kbo_defense_2026.json]
"""
from __future__ import annotations

import argparse
import html as html_mod
import json
import os
import re
import ssl
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
URL = "https://www.koreabaseball.com/Record/Player/Defense/Basic.aspx"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE

# 포스트백 타겟 이름은 id(밑줄)와 다르게 중첩 마스터페이지 경로(달러)로 써야 한다.
# id만 보고 "cphContents_..."로 보내면 서버가 조용히 1페이지를 다시 돌려준다(실측).
_PREFIX = "ctl00$ctl00$ctl00$cphContents$cphContents$cphContents$"
_TAG_RE = re.compile(r"<[^>]+>")


# ASP.NET은 VIEWSTATE 검증을 세션과 묶어두기 때문에, 첫 GET에서 받은 세션 쿠키를
# 그대로 들고 POST해야 한다. 쿠키 없이 보내면 포스트백이 전부 에러 페이지로 떨어진다.
_OPENER = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(),
    urllib.request.HTTPSHandler(context=_CTX),
)


def _get(url: str, data: bytes | None = None) -> str:
    req = urllib.request.Request(url, data=data, headers={
        "User-Agent": UA,
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": URL,
    })
    return _OPENER.open(req, timeout=30).read().decode("utf-8", "replace")


def _hidden_fields(h: str) -> dict:
    """포스트백에 돌려보내야 하는 폼 상태를 통째로 긁는다.

    __VIEWSTATE류만 보내면 서버가 에러 페이지를 준다(실측). 드롭다운(select)의 현재
    선택값까지 모두 실어야 정상 응답이 온다. 이름은 id(밑줄)가 아니라 name(달러)이다.
    """
    out = {}
    for m in re.finditer(r'<input[^>]*type="hidden"[^>]*>', h, re.I):
        tag = m.group(0)
        nm = re.search(r'name="([^"]+)"', tag)
        val = re.search(r'value="([^"]*)"', tag)
        if nm:
            out[nm.group(1)] = html_mod.unescape(val.group(1) if val else "")
    for m in re.finditer(r'<select[^>]*name="([^"]+)"[^>]*>(.*?)</select>', h, re.S | re.I):
        nm, body = m.group(1), m.group(2)
        sel = re.search(r'<option[^>]*selected[^>]*value="([^"]*)"', body)
        if not sel:
            sel = re.search(r'<option[^>]*value="([^"]*)"', body)
        out[nm] = html_mod.unescape(sel.group(1)) if sel else ""
    return out


def _text(cell: str) -> str:
    return html_mod.unescape(_TAG_RE.sub("", cell)).strip()


def innings_to_outs(txt: str) -> int:
    """'1153 1/3' -> 아웃카운트. 공식 표기가 분수라 정수로 바꿔 둔다."""
    txt = (txt or "").strip()
    if not txt or txt == "-":
        return 0
    outs = 0
    for part in txt.split():
        if "/" in part:
            a, b = part.split("/")
            try:
                outs += round(int(a) / int(b) * 3)
            except (ValueError, ZeroDivisionError):
                pass
        else:
            try:
                outs += int(float(part)) * 3
            except ValueError:
                pass
    return outs


def _parse_rows(h: str) -> list[dict]:
    """표 한 장을 읽는다. 열 순서: 순위 선수명 팀 POS G GS IP E PKO PO A DP ..."""
    rows = []
    for tr in re.findall(r"<tr>(.*?)</tr>", h, re.S):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if len(tds) < 8:
            continue
        cells = [_text(t) for t in tds]
        if not cells[1]:
            continue
        rows.append({
            "name": cells[1], "team": cells[2], "pos": cells[3],
            "games": int(cells[4] or 0), "starts": int(cells[5] or 0),
            "def_outs": innings_to_outs(cells[6]),
            "errors": int(cells[7] or 0),
        })
    return rows


def fetch_defense(season: int = 2026, series: str = "0", team: str = "") -> dict:
    """선수(이름+팀) 단위로 합산한 수비 기록. 키는 '이름|팀'.

    team을 주면 그 팀만 조회한다. 전체 조회는 페이저가 중간에 끊겨 적게 뛴 선수가
    통째로 빠지는 일이 있어(실측: 실책 합계가 공식 팀합계의 68%에 그침), 팀별로
    나눠 받아 합치는 쪽이 빠짐이 없다.
    """
    h = _get(URL)
    fields = _hidden_fields(h)

    if team:
        payload = dict(fields)
        payload["__EVENTTARGET"] = _PREFIX + "ddlTeam$ddlTeam"
        payload["__EVENTARGUMENT"] = ""
        payload[_PREFIX + "ddlSeason$ddlSeason"] = str(season)
        payload[_PREFIX + "ddlSeries$ddlSeries"] = series
        payload[_PREFIX + "ddlTeam$ddlTeam"] = team
        h = _get(URL, urllib.parse.urlencode(payload, encoding="utf-8").encode())
        fields = _hidden_fields(h)

    # 시즌이 기본값과 다르면 먼저 드롭다운을 바꾼다(기본은 최신 시즌).
    cur = re.search(r'ddlSeason_ddlSeason"[^>]*>(.*?)</select>', h, re.S)
    cur_sel = re.findall(r'<option[^>]*selected[^>]*value="([^"]+)"', cur.group(1)) if cur else []
    if str(season) not in cur_sel:
        payload = dict(fields)
        payload["__EVENTTARGET"] = _PREFIX + "ddlSeason$ddlSeason"
        payload["__EVENTARGUMENT"] = ""
        payload[_PREFIX + "ddlSeason$ddlSeason"] = str(season)
        payload[_PREFIX + "ddlSeries$ddlSeries"] = series
        h = _get(URL, urllib.parse.urlencode(payload, encoding="utf-8").encode())
        fields = _hidden_fields(h)

    merged: dict[str, dict] = {}
    page = 1
    while True:
        for r in _parse_rows(h):
            key = f"{r['name']}|{r['team']}"
            m = merged.setdefault(key, {"name": r["name"], "team": r["team"],
                                        "def_outs": 0, "errors": 0, "positions": []})
            m["def_outs"] += r["def_outs"]
            m["errors"] += r["errors"]
            m["positions"].append(r["pos"])

        # 페이저는 번호를 5개씩만 보여주고 그 너머는 btnNext로 넘긴다. 번호 버튼만
        # 보고 끊으면 6페이지 이후 선수가 통째로 빠진다.
        nxt = page + 1
        if f"btnNo{nxt}" in h:
            target = _PREFIX + f"ucPager$btnNo{nxt}"
        elif "btnNext" in h:
            target = _PREFIX + "ucPager$btnNext"
        else:
            break
        payload = dict(fields)
        payload["__EVENTTARGET"] = target
        payload["__EVENTARGUMENT"] = ""
        payload[_PREFIX + "ddlSeason$ddlSeason"] = str(season)
        payload[_PREFIX + "ddlSeries$ddlSeries"] = series
        if team:
            payload[_PREFIX + "ddlTeam$ddlTeam"] = team
        h = _get(URL, urllib.parse.urlencode(payload, encoding="utf-8").encode())
        fields = _hidden_fields(h)
        page = nxt
        if page > 30:  # 안전장치
            break
    return merged


def main():
    ap = argparse.ArgumentParser(description="KBO 공식 선수 수비기록 수집")
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    teams = ["KT", "SS", "HT", "LG", "OB", "SK", "HH", "NC", "LT", "WO"]
    data = {}
    for t in teams:
        part = fetch_defense(args.season, team=t)
        for k, v in part.items():
            m = data.setdefault(k, {"name": v["name"], "team": v["team"],
                                    "def_outs": 0, "errors": 0, "positions": []})
            m["def_outs"] += v["def_outs"]
            m["errors"] += v["errors"]
            m["positions"] += v["positions"]
        print(f"  {t}: {len(part)}명")
    out = args.out or os.path.join(HERE, f"kbo_defense_{args.season}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    tot = sum(v["def_outs"] for v in data.values())
    print(f"{args.season} 수비기록 {len(data)}명 저장 -> {out} (총 수비이닝 {tot//3}.{tot%3})")


if __name__ == "__main__":
    main()
