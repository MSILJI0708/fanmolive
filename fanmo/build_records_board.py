"""season_stats.json / career_stats.json(build_stats.py가 만든 정규시즌 누적치)을 읽어
시즌 기록실·통산 기록실을 보여주는 정적 HTML(records.html) 하나로 만든다.
lp_board.html과 같은 팔레트를 그대로 써서 두 페이지가 같은 사이트처럼 보이게 한다.

사용법: python build_records_board.py (build_stats.py를 먼저 돌려서 두 JSON을 만들어둬야 함)
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    with open(os.path.join(HERE, "season_stats.json"), encoding="utf-8") as f:
        season_stats = json.load(f)
    with open(os.path.join(HERE, "career_stats.json"), encoding="utf-8") as f:
        career_stats = json.load(f)

    seasons = sorted(season_stats.keys(), reverse=True)
    season_payload = json.dumps(season_stats, ensure_ascii=False)
    career_payload = json.dumps(career_stats, ensure_ascii=False)
    seasons_payload = json.dumps(seasons, ensure_ascii=False)

    html_doc = r"""<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>KBO 판타지 기록실</title>
<style>
:root {
  --paper-0: #f3f1ea; --paper-1: #ffffff; --ink-0: #1c1a15; --ink-1: #58554a;
  --line: #dcd8cc; --accent: #b9822f; --accent-ink: #6b4e1c; --hot: #b6402f;
  --warm: #c17a1f; --cool: #3a5f9e; --chip-bg: #efe9d8; --row-alt: #ebe8de;
  --shadow: 0 1px 2px rgba(28,26,21,.06), 0 8px 24px -12px rgba(28,26,21,.18);
}
@media (prefers-color-scheme: dark) {
  :root {
    --paper-0: #14120d; --paper-1: #1c1a14; --ink-0: #ede8db; --ink-1: #a9a290;
    --line: #38352a; --accent: #d9a24d; --accent-ink: #f2cf95; --hot: #e2695a;
    --warm: #dda23f; --cool: #7ea3e0; --chip-bg: #262218; --row-alt: #1f1c15;
    --shadow: 0 1px 2px rgba(0,0,0,.4), 0 8px 24px -12px rgba(0,0,0,.6);
  }
}
:root[data-theme="dark"] {
  --paper-0: #14120d; --paper-1: #1c1a14; --ink-0: #ede8db; --ink-1: #a9a290;
  --line: #38352a; --accent: #d9a24d; --accent-ink: #f2cf95; --hot: #e2695a;
  --warm: #dda23f; --cool: #7ea3e0; --chip-bg: #262218; --row-alt: #1f1c15;
  --shadow: 0 1px 2px rgba(0,0,0,.4), 0 8px 24px -12px rgba(0,0,0,.6);
}
:root[data-theme="light"] {
  --paper-0: #f3f1ea; --paper-1: #ffffff; --ink-0: #1c1a15; --ink-1: #58554a;
  --line: #dcd8cc; --accent: #b9822f; --accent-ink: #6b4e1c; --hot: #b6402f;
  --warm: #c17a1f; --cool: #3a5f9e; --chip-bg: #efe9d8; --row-alt: #ebe8de;
  --shadow: 0 1px 2px rgba(28,26,21,.06), 0 8px 24px -12px rgba(28,26,21,.18);
}
* { box-sizing: border-box; }
html, body { margin: 0; background: var(--paper-0); color: var(--ink-0);
  font-family: -apple-system, "Apple SD Gothic Neo", "Malgun Gothic", sans-serif; }
header { padding: 22px 24px 14px; border-bottom: 1px solid var(--line); }
h1 { font-size: 20px; margin: 0 0 4px; }
header p { margin: 0; color: var(--ink-1); font-size: 12.5px; }
.tabs { display: flex; gap: 8px; padding: 14px 24px 0; flex-wrap: wrap; }
.tab, .seg { border: 1px solid var(--line); background: var(--paper-1); color: var(--ink-1);
  border-radius: 999px; padding: 6px 14px; font-size: 13px; cursor: pointer; }
.tab.active, .seg.active { background: var(--accent); color: #fff; border-color: var(--accent); font-weight: 600; }
.toolbar { display: flex; gap: 8px; align-items: center; padding: 10px 24px; flex-wrap: wrap; }
.toolbar input[type=text] { border: 1px solid var(--line); background: var(--paper-1); color: var(--ink-0);
  border-radius: 8px; padding: 7px 10px; font-size: 13px; min-width: 160px; }
.toolbar select { border: 1px solid var(--line); background: var(--paper-1); color: var(--ink-0);
  border-radius: 8px; padding: 7px 10px; font-size: 13px; }
main { padding: 4px 24px 40px; overflow-x: auto; }
table { border-collapse: collapse; width: 100%; min-width: 900px; font-size: 12.5px; }
thead th { position: sticky; top: 0; background: var(--paper-0); text-align: right; padding: 8px 10px;
  border-bottom: 2px solid var(--line); color: var(--ink-1); cursor: pointer; white-space: nowrap; user-select: none; }
thead th.left, td.left { text-align: left; }
thead th:hover { color: var(--accent-ink); }
thead th.sorted { color: var(--accent-ink); font-weight: 700; }
tbody td { padding: 6px 10px; text-align: right; border-bottom: 1px solid var(--line); white-space: nowrap; }
tbody tr:nth-child(even) { background: var(--row-alt); }
tbody tr:hover { background: var(--chip-bg); }
.rank { color: var(--ink-1); width: 30px; }
.name { font-weight: 600; }
.team { color: var(--ink-1); font-size: 11px; margin-left: 4px; }
footer { padding: 16px 24px 40px; color: var(--ink-1); font-size: 11px; }
a.back { color: var(--accent-ink); text-decoration: none; font-size: 12.5px; }
</style>
<body>
<header>
  <a class="back" href="lp_board.html">← LP 보드로</a>
  <h1>KBO 판타지 기록실</h1>
  <p>정규시즌(올스타·포스트시즌 제외) 누적 기록 · 자동 집계</p>
</header>
<div class="tabs" id="scopeTabs"></div>
<div class="tabs" id="roleTabs">
  <button class="tab active" data-role="batters">타자</button>
  <button class="tab" data-role="pitchers">투수</button>
</div>
<div class="toolbar">
  <select id="seasonSelect"></select>
  <input id="search" type="text" placeholder="선수 이름 검색">
  <span id="rowCount" style="color:var(--ink-1);font-size:12px;"></span>
</div>
<main><table id="tbl"><thead></thead><tbody></tbody></table></main>
<footer>데이터 출처: 네이버 스포츠 · 기준: 정규시즌만(올스타전 kbo_as, 포스트시즌 kbo_ps_* 제외)</footer>
<script>
const SEASON_STATS = __SEASON_STATS__;
const CAREER_STATS = __CAREER_STATS__;
const SEASONS = __SEASONS__;

const BATTER_COLS = [
  {h:'', key:'rank', num:true},
  {h:'이름', key:'name', left:true},
  {h:'G', key:'G', num:true}, {h:'AB', key:'AB', num:true}, {h:'PA', key:'PA', num:true},
  {h:'R', key:'R', num:true}, {h:'H', key:'H', num:true}, {h:'2B', key:'2B', num:true},
  {h:'3B', key:'3B', num:true}, {h:'HR', key:'HR', num:true}, {h:'RBI', key:'RBI', num:true},
  {h:'BB', key:'BB', num:true}, {h:'K', key:'K', num:true}, {h:'SB', key:'SB', num:true},
  {h:'CS', key:'CS', num:true}, {h:'AVG', key:'AVG', num:true, dec:3},
  {h:'OBP', key:'OBP', num:true, dec:3}, {h:'SLG', key:'SLG', num:true, dec:3},
  {h:'OPS', key:'OPS', num:true, dec:3},
];
const PITCHER_COLS = [
  {h:'', key:'rank', num:true},
  {h:'이름', key:'name', left:true},
  {h:'G', key:'G', num:true}, {h:'GS', key:'GS', num:true}, {h:'IP', key:'IP', num:true, isIP:true},
  {h:'W', key:'WIN', num:true}, {h:'L', key:'LOSS', num:true}, {h:'SV', key:'SAVE', num:true},
  {h:'HLD', key:'HOLD', num:true}, {h:'BS', key:'BLOWN', num:true},
  {h:'ERA', key:'ERA', num:true, dec:2}, {h:'WHIP', key:'WHIP', num:true, dec:2},
  {h:'H', key:'H', num:true}, {h:'HR', key:'HR', num:true}, {h:'BB', key:'BB', num:true},
  {h:'K', key:'K', num:true}, {h:'QS', key:'QS', num:true},
];

let state = { scope: 'season', role: 'batters', season: SEASONS[0] || '', sortKey: null, sortDir: -1, q: '' };

function scopeTabsInit() {
  const el = document.getElementById('scopeTabs');
  el.innerHTML = '';
  [['season','시즌 기록실'], ['career','통산 기록실']].forEach(([key,label]) => {
    const b = document.createElement('button');
    b.className = 'tab' + (state.scope === key ? ' active' : '');
    b.textContent = label;
    b.onclick = () => { state.scope = key; state.sortKey = null; render(); };
    el.appendChild(b);
  });
}

document.querySelectorAll('#roleTabs .tab').forEach(b => {
  b.onclick = () => {
    document.querySelectorAll('#roleTabs .tab').forEach(x => x.classList.remove('active'));
    b.classList.add('active');
    state.role = b.dataset.role;
    state.sortKey = null;
    render();
  };
});

const seasonSelect = document.getElementById('seasonSelect');
seasonSelect.innerHTML = SEASONS.map(s => `<option value="${s}">${s}시즌</option>`).join('');
seasonSelect.onchange = () => { state.season = seasonSelect.value; render(); };
document.getElementById('search').oninput = (e) => { state.q = e.target.value.trim(); render(); };

function currentRows() {
  const src = state.scope === 'season' ? (SEASON_STATS[state.season] || {}) : CAREER_STATS;
  return src[state.role] || [];
}

function ipToOuts(ipStr) {
  const [w, r] = String(ipStr).split('.').map(Number);
  return (w || 0) * 3 + (r || 0);
}

function render() {
  scopeTabsInit();
  seasonSelect.style.display = state.scope === 'season' ? '' : 'none';
  const cols = state.role === 'batters' ? BATTER_COLS : PITCHER_COLS;
  let rows = currentRows().slice();
  if (state.q) {
    const q = state.q.toLowerCase();
    rows = rows.filter(r => (r.name || '').toLowerCase().includes(q));
  }
  const defaultKey = state.role === 'batters' ? 'OPS' : 'ERA';
  const sortKey = state.sortKey || defaultKey;
  const dir = state.sortKey ? state.sortDir : (sortKey === 'ERA' ? 1 : -1);
  rows.sort((a, b) => {
    let av = sortKey === 'IP' ? ipToOuts(a.IP) : a[sortKey];
    let bv = sortKey === 'IP' ? ipToOuts(b.IP) : b[sortKey];
    if (typeof av === 'string') return dir * av.localeCompare(bv);
    return dir * ((av || 0) - (bv || 0));
  });

  const thead = document.querySelector('#tbl thead');
  thead.innerHTML = '<tr>' + cols.map(c => {
    const cls = (c.left ? 'left ' : '') + (c.key === sortKey ? 'sorted' : '');
    return `<th class="${cls}" data-key="${c.key}">${c.h}${c.key===sortKey ? (dir>0?' ▲':' ▼') : ''}</th>`;
  }).join('') + '</tr>';
  thead.querySelectorAll('th').forEach(th => {
    th.onclick = () => {
      const key = th.dataset.key;
      if (key === 'rank') return;
      if (state.sortKey === key) state.sortDir *= -1;
      else { state.sortKey = key; state.sortDir = -1; }
      render();
    };
  });

  const tbody = document.querySelector('#tbl tbody');
  tbody.innerHTML = rows.map((r, i) => '<tr>' + cols.map(c => {
    if (c.key === 'rank') return `<td class="rank">${i + 1}</td>`;
    if (c.key === 'name') return `<td class="left"><span class="name">${r.name || ''}</span><span class="team">${r.team || ''}</span></td>`;
    let v = r[c.key];
    if (v == null) v = 0;
    if (c.dec != null) v = Number(v).toFixed(c.dec);
    return `<td>${v}</td>`;
  }).join('') + '</tr>').join('');
  document.getElementById('rowCount').textContent = rows.length + '명';
}

render();
</script>
"""
    html_doc = (html_doc
                .replace("__SEASON_STATS__", season_payload)
                .replace("__CAREER_STATS__", career_payload)
                .replace("__SEASONS__", seasons_payload))

    out_path = os.path.join(HERE, "records.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_doc)
    print(f"wrote {len(html_doc)} bytes -> {out_path}")


if __name__ == "__main__":
    main()
