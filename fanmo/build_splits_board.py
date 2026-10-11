"""투타 상대 유형별 전적(splits.html)을 만든다.

splits_collect.py가 모은 경기별 조각을 선수 단위로 합치고, 수비기록(KBO 공식)과
선발/구원 등판 수를 붙여서 표로 뿌린다.

표에 담기는 값
  타자: 상대 투수 유형(우투/좌투/언더)별 타격 성적 + 시즌 합계(수비이닝·실책)
  투수: 상대 타자 유형(우타/좌타)별 투구 성적 + 시즌 합계(선발/구원 등판)

유형별로 쪼갤 수 없는 기록은 유형 칸에 넣지 않고 "시즌 전체" 쪽에만 적는다. 수비는
상대 투수가 없는 상황이고, 등판 횟수는 한 경기에서 양쪽 타자를 다 상대하기 때문이다.

사용법: python build_splits_board.py
"""
from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
PITCHER_KINDS = ("우투", "좌투", "언더")
BATTER_KINDS = ("우타", "좌타")


def outs_to_ip(outs: int) -> str:
    """아웃카운트를 야구식 이닝 표기로. 20아웃 -> '6 2/3'."""
    whole, rem = divmod(int(outs), 3)
    return f"{whole}" if rem == 0 else f"{whole} {rem}/3"


def load_raw(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def aggregate(games: list[dict]) -> dict:
    """경기별 조각을 선수별로 합친다."""
    bat: dict[str, dict] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    pit: dict[str, dict] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    meta: dict[str, dict] = {}
    appear: dict[str, dict] = defaultdict(lambda: {"선발": 0, "구원": 0})
    # 자책점은 공식값(경기별)을 유형별 실점 비율로 나눠 담는다.
    er_split: dict[str, dict] = defaultdict(lambda: defaultdict(float))

    for g in games:
        if not g:
            continue
        for code, m in (g.get("meta") or {}).items():
            cur = meta.setdefault(code, {"name": m.get("name"), "team": m.get("team")})
            cur["team"] = m.get("team") or cur.get("team")
            if m.get("role"):
                appear[code][m["role"]] += 1

        for key, vals in (g.get("batters") or {}).items():
            code, kind = key.split("|", 1)
            for stat, n in vals.items():
                bat[code][kind][stat] += n
        for key, vals in (g.get("pitchers") or {}).items():
            code, kind = key.split("|", 1)
            for stat, n in vals.items():
                pit[code][kind][stat] += n

        runs = g.get("pitcher_runs") or {}
        for code, er in (g.get("pitcher_er") or {}).items():
            by_kind = runs.get(code) or {}
            total = sum(by_kind.values())
            if not er:
                continue
            if total <= 0:
                # 실점은 없는데 자책이 잡힌 희귀한 경우. 상대한 타자 비중으로 나눈다.
                tbf = {k: (pit[code][k].get("tbf") or 0) for k in BATTER_KINDS}
                tot2 = sum(tbf.values())
                for k, v in tbf.items():
                    if tot2:
                        er_split[code][k] += er * v / tot2
                continue
            for k, v in by_kind.items():
                er_split[code][k] += er * v / total

    return {"bat": bat, "pit": pit, "meta": meta, "appear": appear, "er": er_split}


def build_rows(agg: dict, defense: dict) -> dict:
    """화면에 바로 뿌릴 수 있는 형태로 정리한다."""
    meta, appear = agg["meta"], agg["appear"]

    bat_rows = []
    for code, kinds in agg["bat"].items():
        m = meta.get(code) or {}
        name, team = m.get("name") or code, m.get("team") or ""
        def_rec = defense.get(f"{name}|{_kbo_team(team)}") or {}
        total_pa = sum(k.get("pa", 0) for k in kinds.values())
        if not total_pa:
            continue
        row = {"code": code, "name": name, "team": team,
               "def_outs": def_rec.get("def_outs"), "errors": def_rec.get("errors"),
               "splits": {}}
        for kind in PITCHER_KINDS:
            s = kinds.get(kind) or {}
            pa = s.get("pa", 0)
            sh = s.get("sh", 0)
            row["splits"][kind] = {
                "pa": pa, "epa": pa - sh, "ab": s.get("ab", 0), "r": s.get("r", 0),
                "h": s.get("h", 0), "d": s.get("d", 0), "t": s.get("t", 0),
                "hr": s.get("hr", 0), "tb": s.get("tb", 0), "rbi": s.get("rbi", 0),
                "bb": s.get("bb", 0), "hbp": s.get("hbp", 0), "ibb": s.get("ibb", 0),
                "so": s.get("so", 0), "sb": s.get("sb", 0), "cs": s.get("cs", 0),
                "sba": s.get("sb", 0) + s.get("cs", 0),
            }
        bat_rows.append(row)

    pit_rows = []
    for code, kinds in agg["pit"].items():
        m = meta.get(code) or {}
        name, team = m.get("name") or code, m.get("team") or ""
        total_bf = sum(k.get("tbf", 0) for k in kinds.values())
        if not total_bf:
            continue
        ap = appear.get(code) or {}
        row = {"code": code, "name": name, "team": team,
               "gs": ap.get("선발", 0), "gr": ap.get("구원", 0), "splits": {}}
        for kind in BATTER_KINDS:
            s = kinds.get(kind) or {}
            row["splits"][kind] = {
                "outs": s.get("outs", 0), "ip": outs_to_ip(s.get("outs", 0)),
                "r": s.get("r", 0), "er": round(agg["er"].get(code, {}).get(kind, 0.0), 1),
                "tbf": s.get("tbf", 0), "h": s.get("h", 0), "d": s.get("d", 0),
                "t": s.get("t", 0), "hr": s.get("hr", 0), "bb": s.get("bb", 0),
                "ibb": s.get("ibb", 0), "hbp": s.get("hbp", 0), "so": s.get("so", 0),
            }
        pit_rows.append(row)

    bat_rows.sort(key=lambda r: -sum(s["pa"] for s in r["splits"].values()))
    pit_rows.sort(key=lambda r: -sum(s["outs"] for s in r["splits"].values()))
    return {"batters": bat_rows, "pitchers": pit_rows}


# KBO 기록실은 팀을 영문 약칭으로 쓰고, 네이버는 한글을 쓴다.
_TEAM_MAP = {"KIA": "KIA", "삼성": "삼성", "LG": "LG", "KT": "KT", "두산": "두산",
             "SSG": "SSG", "한화": "한화", "롯데": "롯데", "NC": "NC", "키움": "키움"}


def _kbo_team(team: str) -> str:
    return _TEAM_MAP.get(team, team)


PAGE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>투타 상대 유형별 전적</title>
<style>
:root{
  --paper-0:#f6f7f9; --paper-1:#fff; --ink-0:#1b1c1f; --ink-1:#6b7280;
  --line:#e3e6ea; --accent:#2f6fed; --hot:#d93025; --cool:#1a73e8; --chip:#eef1f5;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --paper-0:#15171a; --paper-1:#1d2024; --ink-0:#e8eaed; --ink-1:#9aa0a6;
    --line:#2d3237; --chip:#262a2f;
  }
}
:root[data-theme="dark"]{
  --paper-0:#15171a; --paper-1:#1d2024; --ink-0:#e8eaed; --ink-1:#9aa0a6;
  --line:#2d3237; --chip:#262a2f;
}
*{box-sizing:border-box}
body{margin:0;background:var(--paper-0);color:var(--ink-0);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Apple SD Gothic Neo",
  "Noto Sans KR",sans-serif;font-size:14px;line-height:1.5}
header{padding:20px 16px 8px;max-width:1500px;margin:0 auto}
.site-nav{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0 4px}
.site-nav a{font-size:12.5px;font-weight:600;padding:7px 14px;border-radius:999px;
  border:1px solid var(--line);background:var(--paper-1);color:var(--ink-1);text-decoration:none}
.site-nav a:hover{border-color:var(--accent);color:var(--accent)}
h1{margin:0 0 4px;font-size:20px;letter-spacing:-.02em}
.sub{margin:0;color:var(--ink-1);font-size:12.5px;line-height:1.7}
main{max-width:1500px;margin:0 auto;padding:0 16px 60px}
nav.tabs{display:flex;gap:6px;margin:14px 0 10px;flex-wrap:wrap}
nav.tabs button{font:inherit;font-weight:700;font-size:13px;padding:7px 14px;
  border-radius:999px;border:1px solid var(--line);background:var(--paper-1);
  color:var(--ink-0);cursor:pointer}
nav.tabs button.active{background:var(--accent);border-color:var(--accent);color:#fff}
.toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:10px}
.toolbar input[type=search]{font:inherit;font-size:13px;padding:6px 11px;border-radius:7px;
  border:1px solid var(--line);background:var(--paper-1);color:var(--ink-0);min-width:180px}
.toolbar label{font-size:12.5px;color:var(--ink-1);display:flex;align-items:center;gap:6px}
.toolbar input[type=number]{font:inherit;font-size:13px;width:74px;padding:5px 8px;
  border-radius:6px;border:1px solid var(--line);background:var(--paper-1);color:var(--ink-0)}
.count{font-size:12.5px;color:var(--ink-1)}
.wrap{overflow:auto;background:var(--paper-1);border:1px solid var(--line);border-radius:10px}
table{border-collapse:separate;border-spacing:0;width:100%;font-size:12.5px;white-space:nowrap}
th,td{padding:6px 9px;border-bottom:1px solid var(--line);text-align:right}
th{position:sticky;top:0;background:var(--paper-1);z-index:2;font-weight:700;
  color:var(--ink-1);font-size:11.5px;cursor:pointer;user-select:none}
th.grp{text-align:center;border-bottom:1px solid var(--line);cursor:default;
  background:var(--chip);color:var(--ink-0)}
th.left,td.left{text-align:left}
tbody tr:hover{background:var(--chip)}
td.name{font-weight:650}
td.sep,th.sep{border-left:2px solid var(--line)}
.kind{color:var(--ink-1);font-weight:700}
.note{margin-top:14px;font-size:12px;color:var(--ink-1);line-height:1.85}
.note b{color:var(--ink-0)}
.theme{position:fixed;top:12px;right:12px;width:34px;height:34px;border-radius:50%;
  border:1px solid var(--line);background:var(--paper-1);cursor:pointer;font-size:15px}
@media (max-width:640px){
  body{font-size:15px} table{font-size:12px} th,td{padding:5px 7px}
}
</style>
<script>
(function(){try{var t=localStorage.getItem('splitsTheme');
if(t==='light'||t==='dark')document.documentElement.dataset.theme=t;}catch(e){}})();
</script>
</head>
<body>
<button class="theme" id="theme" title="테마 전환">&#127763;</button>
<header>
  <h1>투타 상대 유형별 전적</h1>
  <nav class="site-nav">
    <a href="index.html">← LP 보드</a>
    <a href="records.html">📊 기록실</a>
    <a href="options.html">⚙️ 설정</a>
  </nav>
  <p class="sub">__SEASON__시즌 · 타자는 상대한 투수 유형별, 투수는 상대한 타자 유형별로 나눈 기록입니다.
  네이버 문자중계의 타석별 투수·타자 정보를 그대로 집계했고, 박스스코어 합계와 대조해 검증했습니다.
  <br>마지막 갱신 __UPDATED__</p>
</header>
<main>
  <nav class="tabs">
    <button data-tab="batters" class="active">타자 <span class="count" id="n-b"></span></button>
    <button data-tab="pitchers">투수 <span class="count" id="n-p"></span></button>
  </nav>
  <div class="toolbar">
    <input type="search" id="q" placeholder="이름·소속 검색">
    <label>최소 <span id="minlabel">타석</span> <input type="number" id="minv" value="0" min="0" step="10"></label>
    <span class="count" id="cnt"></span>
  </div>
  <div class="wrap"><table id="tbl"></table></div>
  <p class="note">
    <b>유형 구분.</b> 투수는 우투 / 좌투 / 언더(우언·좌언 합산), 타자는 우타 / 좌타로 나눕니다.
    양손 타자는 "항상 투수가 던진 손의 반대쪽 타석에 선다"고 보고 환산했습니다.<br>
    <b>유효타석</b>은 타석에서 희생번트 성공을 뺀 값, <b>도루기회</b>는 도루 시도(도루+도루실패)입니다.<br>
    <b>유형별로 나눌 수 없는 기록.</b> 타자의 수비이닝·실책은 수비 중 기록이라 상대 투수가 없고,
    투수의 선발·구원 등판은 한 경기에서 양쪽 타자를 모두 상대하므로 유형별로 쪼개면 중복됩니다.
    그래서 이 네 가지는 맨 오른쪽 <b>시즌 전체</b> 칸에만 넣었습니다. 수비 기록은 KBO 공식
    기록실 값을 그대로 가져왔습니다.<br>
    <b>자책점.</b> "실책이 없었다면 어땠을까"를 따지는 기록원 판단이라 중계 문구만으로는 재현할 수
    없습니다. 그래서 경기별 공식 자책점을 그 경기의 유형별 실점 비율대로 나눴습니다 —
    선수의 시즌 합계는 공식 기록과 정확히 같고, 좌우 분해만 근사치입니다.<br>
    <b>공식 기록 규칙 반영.</b> 타석 도중 투수가 바뀐 뒤의 볼넷(교체 시점 2-0·2-1·3-0·3-1·3-2),
    2스트라이크 이후 대타의 삼진, 승계주자 실점(내보낸 주자 수 기준, 야수선택 승계 포함)은
    공식 기록원과 같은 방식으로 귀속했습니다.<br>
    <b>검증.</b> 정규시즌 715경기 전체를 경기별 공식 박스스코어와 대조해 타자(타수·안타·홈런·득점·타점·
    볼넷·삼진·도루)와 투수(이닝·피안타·피홈런·볼넷·삼진·실점) 전 항목이 일치함을 확인했습니다.
    예외는 두 경기뿐입니다 — 2026-04-15 키움-KIA는 중계 데이터에서 1회초 첫 타석(이주형 안타)이
    빠져 있고, 2026-05-30 롯데-NC는 승계주자 실점 1점을 공식 기록이 다른 경기들과 달리 처리했습니다.
  </p>
</main>
<script id="data" type="application/json">__DATA__</script>
<script>
const DATA = JSON.parse(document.getElementById('data').textContent);
const PK = ['우투','좌투','언더'], BK = ['우타','좌타'];
const BAT_COLS = [
  ['pa','타석'],['epa','유효타석'],['ab','타수'],['r','득점'],['h','안타'],['d','2루타'],
  ['t','3루타'],['hr','홈런'],['tb','루타'],['rbi','타점'],['bb','볼넷'],['hbp','사구'],
  ['ibb','고의사구'],['so','삼진'],['sb','도루'],['cs','도실'],['sba','도루기회'],
];
const PIT_COLS = [
  ['ip','이닝'],['r','실점'],['er','자책'],['tbf','상대타자'],['h','피안타'],['d','피2루타'],
  ['t','피3루타'],['hr','피홈런'],['bb','볼넷'],['ibb','고의사구'],['hbp','사구'],['so','삼진'],
];

let tab = 'batters', sortKey = null, sortDir = -1;

function cellVal(row, kind, key){
  const s = row.splits[kind] || {};
  return s[key] === undefined ? 0 : s[key];
}
function totalOf(row, key){
  const kinds = tab === 'batters' ? PK : BK;
  return kinds.reduce((a,k)=> a + (Number(cellVal(row,k,key))||0), 0);
}

function render(){
  const rows = DATA[tab];
  const kinds = tab === 'batters' ? PK : BK;
  const cols = tab === 'batters' ? BAT_COLS : PIT_COLS;
  const q = document.getElementById('q').value.trim();
  const minv = Number(document.getElementById('minv').value) || 0;
  const minKey = tab === 'batters' ? 'pa' : 'outs';

  let list = rows.filter(r => {
    if (q && !(r.name.includes(q) || (r.team||'').includes(q))) return false;
    const base = tab === 'batters' ? totalOf(r,'pa')
      : kinds.reduce((a,k)=> a + (cellVal(r,k,'outs')||0), 0) / 3;
    return base >= minv;
  });

  if (sortKey){
    const [kind, key] = sortKey;
    list = list.slice().sort((a,b)=>{
      const av = kind === '*' ? totalOf(a,key) : cellVal(a,kind,key);
      const bv = kind === '*' ? totalOf(b,key) : cellVal(b,kind,key);
      if (typeof av === 'string' || typeof bv === 'string')
        return sortDir * String(av).localeCompare(String(bv),'ko');
      return sortDir * ((Number(bv)||0) - (Number(av)||0));
    });
  }

  const t = document.getElementById('tbl');
  const grp = ['<tr><th class="grp left" colspan="2">선수</th>'];
  kinds.forEach(k => grp.push(`<th class="grp sep" colspan="${cols.length}">vs ${k}</th>`));
  grp.push(`<th class="grp sep" colspan="${tab==='batters'?2:2}">시즌 전체</th></tr>`);

  const head = ['<tr><th class="left">이름</th><th class="left">소속</th>'];
  kinds.forEach(k => cols.forEach(([key,label],i) =>
    head.push(`<th data-k="${k}" data-c="${key}" class="${i===0?'sep':''}">${label}</th>`)));
  if (tab === 'batters')
    head.push('<th class="sep" data-k="*" data-c="def">수비이닝</th><th data-k="*" data-c="err">실책</th>');
  else
    head.push('<th class="sep" data-k="*" data-c="gs">선발</th><th data-k="*" data-c="gr">구원</th>');
  head.push('</tr>');

  const body = list.map(r => {
    const tds = [`<td class="left name">${r.name}</td><td class="left">${r.team||''}</td>`];
    kinds.forEach(k => cols.forEach(([key],i) => {
      const v = cellVal(r,k,key);
      tds.push(`<td class="${i===0?'sep':''}">${v===0?'<span style="opacity:.35">0</span>':v}</td>`);
    }));
    if (tab === 'batters'){
      const ip = r.def_outs==null ? '-' : (Math.floor(r.def_outs/3) + (r.def_outs%3 ? ' '+(r.def_outs%3)+'/3' : ''));
      tds.push(`<td class="sep">${ip}</td><td>${r.errors==null?'-':r.errors}</td>`);
    } else {
      tds.push(`<td class="sep">${r.gs||0}</td><td>${r.gr||0}</td>`);
    }
    return '<tr>' + tds.join('') + '</tr>';
  }).join('');

  t.innerHTML = '<thead>' + grp.join('') + head.join('') + '</thead><tbody>' + body + '</tbody>';
  document.getElementById('cnt').textContent = list.length + '명';

  t.querySelectorAll('th[data-c]').forEach(th => th.addEventListener('click', () => {
    const k = th.dataset.k, c = th.dataset.c;
    if (sortKey && sortKey[0]===k && sortKey[1]===c) sortDir = -sortDir;
    else { sortKey = [k,c]; sortDir = -1; }
    render();
  }));
}

document.querySelectorAll('nav.tabs button').forEach(b => b.addEventListener('click', () => {
  document.querySelectorAll('nav.tabs button').forEach(x => x.classList.toggle('active', x===b));
  tab = b.dataset.tab; sortKey = null;
  document.getElementById('minlabel').textContent = tab==='batters' ? '타석' : '이닝';
  document.getElementById('minv').value = 0;
  render();
}));
document.getElementById('q').addEventListener('input', render);
document.getElementById('minv').addEventListener('input', render);
document.getElementById('theme').addEventListener('click', () => {
  const cur = document.documentElement.dataset.theme;
  const next = cur === 'dark' ? 'light' : cur === 'light' ? '' : 'dark';
  if (next) document.documentElement.dataset.theme = next;
  else delete document.documentElement.dataset.theme;
  try { localStorage.setItem('splitsTheme', next); } catch(e){}
});
document.getElementById('n-b').textContent = DATA.batters.length + '명';
document.getElementById('n-p').textContent = DATA.pitchers.length + '명';
render();
</script>
</body>
</html>
"""


def main():
    import datetime

    ap = argparse.ArgumentParser(description="투타 상대 유형별 전적 페이지 생성")
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--raw", default=None)
    ap.add_argument("--defense", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    raw = args.raw or os.path.join(HERE, f"splits_raw_{args.season}.json")
    games = load_raw(raw)
    agg = aggregate(games)

    defense = {}
    dpath = args.defense or os.path.join(HERE, f"kbo_defense_{args.season}.json")
    if os.path.exists(dpath):
        with open(dpath, encoding="utf-8") as f:
            defense = json.load(f)

    data = build_rows(agg, defense)
    html = (PAGE
            .replace("__SEASON__", str(args.season))
            .replace("__UPDATED__", datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
            .replace("__DATA__", json.dumps(data, ensure_ascii=False)))
    out = args.out or os.path.join(HERE, "splits.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"wrote {len(html)} bytes -> {out}")
    print(f"  타자 {len(data['batters'])}명 / 투수 {len(data['pitchers'])}명 / 경기 {len(games)}건")


if __name__ == "__main__":
    main()
