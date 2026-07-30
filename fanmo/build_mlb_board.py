import argparse
import glob
import json
import os
import re
from datetime import datetime, timedelta, timezone

ap = argparse.ArgumentParser(description="수집된 data_mlb_<date>.json 전부를 모아 날짜 선택이 가능한 MLB LP 보드 HTML을 만든다")
ap.add_argument("--date", default=None, help="처음 열었을 때 보여줄 기준일 YYYY-MM-DD (생략 시 가장 최근 수집일)")
args = ap.parse_args()

here = os.path.dirname(os.path.abspath(__file__))

all_data: dict[str, dict] = {}
for path in sorted(glob.glob(os.path.join(here, "data_mlb_*.json"))):
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    m = re.search(r"data_mlb_(\d{8})\.json$", path)
    ds = d.get("date") or f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:8]}"
    all_data[ds] = {"batters": d["batters"], "pitchers": d["pitchers"]}

if not all_data:
    raise SystemExit("data_mlb_*.json 파일이 없습니다. 먼저 mlb_fantasy_score.py로 데이터를 수집하세요.")

date_str = args.date if args.date in all_data else max(all_data.keys())
batters = all_data[date_str]["batters"]
pitchers = all_data[date_str]["pitchers"]

has_data = bool(batters or pitchers)
top_batter = batters[0] if batters else {"lp": 0, "name": "-", "team": "-"}
top_pitcher = pitchers[0] if pitchers else {"lp": 0, "name": "-", "team": "-"}
games_count = len({(r["team"], r["opponent"], r["date"]) for r in batters}) // 2 if batters else 0
last_update = datetime.now(timezone(timedelta(hours=9))).strftime("%m월 %d일 %H:%M")

payload = json.dumps(all_data, ensure_ascii=False)

html_doc = """<!doctype html>
<title>MLB 판타지 LP 보드(실험) · __DATE__</title>
<style>
:root {
  --paper-0: #f3f1ea;
  --paper-1: #ffffff;
  --ink-0: #1c1a15;
  --ink-1: #58554a;
  --line: #dcd8cc;
  --accent: #b9822f;
  --accent-ink: #6b4e1c;
  --hot: #b6402f;
  --warm: #c17a1f;
  --cool: #3a5f9e;
  --chip-bg: #efe9d8;
  --row-alt: #ebe8de;
  --shadow: 0 1px 2px rgba(28,26,21,.06), 0 8px 24px -12px rgba(28,26,21,.18);
}
@media (prefers-color-scheme: dark) {
  :root {
    --paper-0: #14120d;
    --paper-1: #1c1a14;
    --ink-0: #ede8db;
    --ink-1: #a9a290;
    --line: #38352a;
    --accent: #d9a24d;
    --accent-ink: #f2cf95;
    --hot: #e2695a;
    --warm: #dda23f;
    --cool: #7ea3e0;
    --chip-bg: #262218;
    --row-alt: #1f1c15;
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
html, body { margin: 0; }
body {
  background: var(--paper-0);
  color: var(--ink-0);
  font-family: "Malgun Gothic", "Apple SD Gothic Neo", "Noto Sans KR", system-ui, sans-serif;
  padding: 0 0 64px;
}
.num { font-variant-numeric: tabular-nums; font-feature-settings: "tnum" 1; }

header.top {
  padding: 32px 24px 20px;
  max-width: 1180px;
  margin: 0 auto;
}
.eyebrow {
  font-size: 11px;
  letter-spacing: .14em;
  text-transform: uppercase;
  color: var(--accent-ink);
  font-weight: 700;
  margin: 0 0 8px;
}
h1 {
  font-size: clamp(22px, 3vw, 30px);
  margin: 0 0 6px;
  text-wrap: balance;
  letter-spacing: -.01em;
}
.sub {
  color: var(--ink-1);
  font-size: 13px;
  margin: 0;
}
.sub code {
  background: var(--chip-bg);
  border: 1px solid var(--line);
  border-radius: 4px;
  padding: 1px 5px;
  font-size: 12px;
}
.sub a { color: var(--accent-ink); font-weight: 600; text-decoration: none; }
.sub a:hover { text-decoration: underline; }
.date-select {
  font: inherit;
  font-weight: 700;
  font-size: 13px;
  padding: 3px 8px;
  border-radius: 6px;
  border: 1px solid var(--line);
  background: var(--paper-1);
  color: var(--ink-0);
  cursor: pointer;
}

.tiles {
  max-width: 1180px;
  margin: 20px auto 0;
  padding: 0 24px;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 12px;
}
.tile {
  background: var(--paper-1);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 14px 16px;
  box-shadow: var(--shadow);
}
.tile .label { font-size: 11px; color: var(--ink-1); letter-spacing: .04em; text-transform: uppercase; }
.tile .value { font-size: 22px; font-weight: 700; margin-top: 4px; }
.tile .value.hot { color: var(--hot); }
.tile .meta { font-size: 12px; color: var(--ink-1); margin-top: 2px; }

main {
  max-width: 1180px;
  margin: 0 auto;
  padding: 0 24px;
}

nav.chapters {
  display: flex;
  gap: 4px;
  margin-top: 30px;
  border-bottom: 2px solid var(--ink-0);
}
nav.chapters button {
  font: inherit;
  font-weight: 700;
  font-size: 15px;
  padding: 10px 20px 12px;
  background: none;
  border: none;
  color: var(--ink-1);
  cursor: pointer;
  border-bottom: 3px solid transparent;
  margin-bottom: -2px;
}
nav.chapters button.active {
  color: var(--ink-0);
  border-bottom-color: var(--accent);
}
nav.chapters button .n {
  color: var(--ink-1);
  font-weight: 500;
  font-size: 12px;
}

section.board { display: none; margin-top: 18px; }
section.board.active { display: block; }

.board-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.board-head .count { font-size: 12px; color: var(--ink-1); }
.search {
  padding: 7px 10px;
  border-radius: 7px;
  border: 1px solid var(--line);
  background: var(--paper-1);
  color: var(--ink-0);
  font-size: 13px;
  outline: none;
  min-width: 180px;
}
.search:focus { border-color: var(--accent); }

.chips {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}
.chip {
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  padding: 5px 12px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: var(--paper-1);
  color: var(--ink-1);
  cursor: pointer;
}
.chip.active {
  background: var(--ink-0);
  color: var(--paper-1);
  border-color: var(--ink-0);
}

.info-tip {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 13px;
  height: 13px;
  margin-left: 5px;
  border-radius: 50%;
  background: var(--line);
  color: var(--paper-1);
  font-size: 9px;
  font-weight: 700;
  font-style: normal;
  text-transform: none;
  letter-spacing: 0;
  cursor: help;
  vertical-align: middle;
}
.info-tip .bubble {
  display: none;
  position: absolute;
  bottom: 130%;
  left: 50%;
  transform: translateX(-50%);
  width: 250px;
  background: var(--ink-0);
  color: var(--paper-0);
  font-size: 11px;
  font-weight: 500;
  line-height: 1.65;
  padding: 10px 12px;
  border-radius: 8px;
  text-align: left;
  white-space: normal;
  z-index: 30;
  box-shadow: var(--shadow);
  pointer-events: none;
}
.info-tip .bubble b { color: var(--accent); }
.info-tip:hover .bubble, .info-tip:focus .bubble { display: block; }

.rule-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 14px;
  margin-bottom: 12px;
  padding: 10px 14px;
  background: var(--chip-bg);
  border: 1px solid var(--line);
  border-radius: 8px;
  font-size: 12.5px;
}
.rule-bar label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
}
.rule-bar select {
  font: inherit;
  font-size: 12.5px;
  padding: 4px 8px;
  border-radius: 6px;
  border: 1px solid var(--line);
  background: var(--paper-1);
  color: var(--ink-0);
}
.rule-bar label.toggle { font-weight: 500; cursor: pointer; }
.rule-bar input[type="checkbox"] { width: 15px; height: 15px; accent-color: var(--accent); cursor: pointer; }
.rule-bar .rule-note { color: var(--ink-1); font-size: 11px; margin-left: auto; }

tbody tr.clickable { cursor: pointer; }
tbody tr.clickable:hover { background: var(--chip-bg); }

.modal-overlay {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,.45);
  z-index: 100;
  align-items: center;
  justify-content: center;
  padding: 20px;
}
.modal-overlay.open { display: flex; }
.modal-card {
  position: relative;
  width: 100%;
  max-width: 620px;
  max-height: 82vh;
  overflow-y: auto;
  background: var(--paper-1);
  border: 1px solid var(--line);
  border-radius: 12px;
  box-shadow: var(--shadow);
  padding: 22px 24px;
}
.modal-close {
  position: absolute;
  top: 14px;
  right: 14px;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  border: 1px solid var(--line);
  background: var(--paper-0);
  color: var(--ink-1);
  font-size: 13px;
  cursor: pointer;
}
.modal-head { margin-bottom: 16px; padding-right: 30px; }
.modal-name { font-size: 19px; font-weight: 700; }
.modal-meta { font-size: 12.5px; color: var(--ink-1); margin-top: 3px; }
.modal-lp { font-size: 26px; font-weight: 700; margin-top: 8px; }
.modal-body table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.modal-body th {
  text-align: left;
  font-size: 11px;
  color: var(--ink-1);
  text-transform: uppercase;
  letter-spacing: .03em;
  padding: 6px 8px;
  border-bottom: 1px solid var(--line);
}
.modal-body td { padding: 7px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
.modal-body tr:last-child td { border-bottom: none; }
.modal-body td.inn { color: var(--ink-1); white-space: nowrap; }
.modal-body td.pts { text-align: right; font-weight: 700; white-space: nowrap; }
.modal-body td.pts.pos { color: var(--hot); }
.modal-body td.pts.neg { color: var(--cool); }
.modal-empty { color: var(--ink-1); font-size: 13px; padding: 10px 0; }

.tablewrap {
  overflow-x: auto;
  border: 1px solid var(--line);
  border-radius: 10px;
  box-shadow: var(--shadow);
  background: var(--paper-1);
}
table {
  border-collapse: collapse;
  width: 100%;
  font-size: 12.5px;
  min-width: 920px;
}
thead th {
  position: sticky;
  top: 0;
  background: var(--paper-1);
  border-bottom: 1px solid var(--line);
  color: var(--ink-1);
  font-weight: 600;
  font-size: 11px;
  letter-spacing: .03em;
  text-transform: uppercase;
  padding: 9px 10px;
  text-align: right;
  white-space: nowrap;
  cursor: pointer;
  user-select: none;
}
thead th.left, td.left { text-align: left; }
thead th:hover { color: var(--ink-0); }
thead th.sorted { color: var(--accent-ink); }
tbody td {
  padding: 7px 10px;
  text-align: right;
  white-space: nowrap;
  border-bottom: 1px solid var(--line);
}
tbody tr:nth-child(even) { background: var(--row-alt); }
tbody tr:hover { background: var(--chip-bg); }
td.name { text-align: left; font-weight: 600; }
td.rank { text-align: left; color: var(--ink-1); width: 28px; }
.lp {
  display: inline-block;
  min-width: 44px;
  padding: 2px 8px;
  border-radius: 999px;
  font-weight: 700;
  background: var(--chip-bg);
}
.lp.hot { color: #fff; background: var(--hot); }
.lp.warm { color: #fff; background: var(--warm); }
.lp.cool { color: #fff; background: var(--cool); }
.tag { display: inline-block; color: var(--accent-ink); font-weight: 700; }
.posbadge { font-size: 11px; }
.posbadge .override { color: var(--accent-ink); font-weight: 700; margin-left: 2px; }
.role { font-size: 11px; font-weight: 700; padding: 2px 7px; border-radius: 5px; }
.role.starter { background: var(--chip-bg); color: var(--accent-ink); }
.role.reliever { color: var(--ink-1); }

footer.notes {
  max-width: 1180px;
  margin: 28px auto 0;
  padding: 14px 24px 0;
  border-top: 1px solid var(--line);
  font-size: 11.5px;
  color: var(--ink-1);
  line-height: 1.7;
}
footer.notes b { color: var(--ink-0); }

@media (prefers-reduced-motion: no-preference) {
  tbody tr { transition: background .1s ease; }
}
</style>

<header class="top">
  <p class="eyebrow">MLB · 라이브 포인트 (실험용, KBO 카드 규칙 그대로 적용)</p>
  <h1>MLB 선수 LP 보드</h1>
  <p class="sub">
    기준일
    <select id="date-select" class="date-select"></select>
    · 데이터 출처 <code>api-gw.sports.naver.com</code> (Selenium 불필요, 공개 JSON 응답 직접 호출)
    · <a href="index.html">← KBO 보드로</a>
    · 마지막 업데이트 __LAST_UPDATE__ (KST)
  </p>
</header>

<div class="tiles" id="no-data-banner" style="display:none">
  <div class="tile" style="grid-column:1/-1; border-color:var(--accent);">
    <div class="label">알림</div>
    <div class="value" style="font-size:15px">아직 이 날짜의 경기 데이터가 없습니다</div>
    <div class="meta">경기 시작 전이거나, 아직 이 날짜를 수집하지 않은 경우입니다. <code>python daily_pipeline.py --date &lt;날짜&gt;</code> 실행 후 보드를 다시 생성해 주세요.</div>
  </div>
</div>

<div class="tiles" id="tiles-main">
  <div class="tile">
    <div class="label">경기 수</div>
    <div class="value num" id="tile-games">__GAMES__</div>
    <div class="meta" id="tile-games-meta">__DATE__ KBO 전 경기</div>
  </div>
  <div class="tile">
    <div class="label">타자 최고 LP</div>
    <div class="value hot num" id="tile-topb-lp">__TOP_B_LP__</div>
    <div class="meta" id="tile-topb-meta">__TOP_B_NAME__ · __TOP_B_TEAM__</div>
  </div>
  <div class="tile">
    <div class="label">투수 최고 LP</div>
    <div class="value hot num" id="tile-topp-lp">__TOP_P_LP__</div>
    <div class="meta" id="tile-topp-meta">__TOP_P_NAME__ · __TOP_P_TEAM__</div>
  </div>
  <div class="tile">
    <div class="label">집계 선수</div>
    <div class="value num" id="tile-total">__TOTAL_PLAYERS__</div>
    <div class="meta" id="tile-total-meta">타자 __NB__ · 투수 __NP__</div>
  </div>
</div>

<main>
  <nav class="chapters">
    <button class="chip-tab active" data-chapter="batters">타자 <span class="n" id="tab-nb">__NB__명</span></button>
    <button class="chip-tab" data-chapter="pitchers">투수 <span class="n" id="tab-np">__NP__명</span></button>
  </nav>

  <section class="board active" id="chapter-batters">
    <div class="board-head">
      <input class="search" id="search-b" placeholder="이름·소속 검색" />
      <span class="count" id="count-b"></span>
    </div>
    <div class="chips" id="pos-chips"></div>
    <div class="tablewrap"><table id="tbl-b"></table></div>
  </section>

  <section class="board" id="chapter-pitchers">
    <div class="board-head">
      <input class="search" id="search-p" placeholder="이름·소속 검색" />
      <span class="count" id="count-p"></span>
    </div>
    <div class="chips" id="role-chips"></div>
    <div class="tablewrap"><table id="tbl-p"></table></div>
  </section>
</main>

<div class="modal-overlay" id="player-modal-overlay">
  <div class="modal-card" role="dialog" aria-modal="true">
    <button class="modal-close" id="player-modal-close" aria-label="닫기">✕</button>
    <div class="modal-head">
      <div class="modal-name" id="modal-name"></div>
      <div class="modal-meta" id="modal-meta"></div>
      <div class="modal-lp" id="modal-lp"></div>
    </div>
    <div class="modal-body" id="modal-body"></div>
  </div>
</div>

<footer class="notes">
  <b>이 보드는 실험용입니다.</b> MLB 텍스트 중계는 KBO와 응답 형식이 달라서(한 타석의 공/결과가
  개별 이벤트가 아니라 문자열 하나에 <code>&lt;br/&gt;</code>로 이어붙어 있고, 매 이벤트마다
  있던 KBO의 주자상태·스코어 스냅샷이 아예 없음) <code>mlb_relay.py</code>를 새로 만들어 파싱했다.
  덕분에 박스스코어엔 없는 2루타·3루타·병살타·희생플라이·진루타(번트 포함)·도루실패·견제사(타자),
  피2루타·피3루타·도루허용·도루저지·견제사(투수)까지 채웠고, 실책은 "그 포지션의 선발 라인업"으로
  근사해서 귀속시켰다(경기 중 그 자리 선수가 교체되면 그 이후 실책 귀속은 부정확할 수 있음).<br>
  <b>구조적으로 못 채우는 항목.</b> 승계주자 실점 허용/막음, 세이브 기회 판정은 등판 시점의
  점수차·주자 상황을 알아야 하는데 MLB 중계엔 그 스냅샷 자체가 없어 계산이 불가능하다. 보살·
  외야수 보살·병살/삼중살 가담은 아웃 처리에 KBO식 "(위치→위치 송구아웃)" 체인이 없어서, 포수
  도루 저지/허용은 포지션 교체 문구 자체가 안 보여 포수를 동적으로 추적할 수 없어서 못 채운다.
  선수 클릭 시 나오는 카테고리/타임라인 팝업도 아직 MLB엔 없다(KBO만 지원) — 표의 합산 점수는
  유효하지만 세부 내역은 못 본다.
</footer>

<script id="lp-data" type="application/json">__DATA_JSON__</script>
<script>
const ALL_DATA = JSON.parse(document.getElementById('lp-data').textContent);
const AVAILABLE_DATES = Object.keys(ALL_DATA).sort().reverse();
let activeDate = '__DATE__';
let data = ALL_DATA[activeDate] || { batters: [], pitchers: [] };

const POSITION_GROUPS = {
  '전체': null,
  '포수': ['포수'],
  '1루수': ['1루수'],
  '2루수': ['2루수'],
  '3루수': ['3루수'],
  '유격수': ['유격수'],
  '외야수': ['좌익수', '중견수', '우익수'],
  '지명타자': ['지명타자'],
};

function lpClass(v) {
  if (v >= 150) return 'hot';
  if (v >= 60) return 'warm';
  if (v < 0) return 'cool';
  return '';
}

const SAVE_TIP = `<b>세이브 요건 (공식 야구규칙 기준)</b><br>
승리 팀의 마지막 투수로 등판해 경기를 끝냈고, 그 경기의 선발투수가 아니며,
다음 중 하나를 만족해야 함:<br>
① 3점 이내 리드로 등판해 최소 1이닝 이상 투구<br>
② 동점 주자가 누상·타석·다음 타자 중 하나로 존재하는
"잠재적 동점 상황"에 등판(점수차 무관)<br>
③ 최소 3이닝을 투구<br>
+ 팀이 승리로 경기를 마쳐야 인정됨`;

const HOLD_TIP = `<b>홀드 요건 (공식 야구규칙 기준)</b><br>
선발투수도, 세이브 요건을 만족한 마무리투수도 아닌 구원투수가
리드를 지킨 상태로 등판해 최소 1아웃 이상을 잡고,<br>
동점이나 역전을 허용하지 않은 채 다음 투수에게
리드를 그대로 넘기고 물러났을 경우 부여됨`;

const batterCols = [
  {h:'#', key:null, cls:'rank'},
  {h:'이름', key:'name', cls:'name left'},
  {h:'포지션', key:'position', cls:'left'},
  {h:'소속', key:'team', cls:'left'},
  {h:'상대', key:'opponent', cls:'left'},
  {h:'LP', key:'lp', num:true},
  {h:'타수', key:'ab', num:true},
  {h:'안타', key:'H', num:true},
  {h:'2B', key:'2B', num:true},
  {h:'3B', key:'3B', num:true},
  {h:'홈런', key:'HR', num:true},
  {h:'타점', key:'RBI', num:true},
  {h:'득점', key:'R', num:true},
  {h:'사사구', merge:['BB','HBP'], labels:['볼넷','사구'], num:true},
  {h:'삼진', key:'K', num:true},
  {h:'도루', key:'SB', num:true},
  {h:'주루사', merge:['CS','PICKOFF'], labels:['도루실패','견제사'], num:true},
  {h:'병살', key:'GDP', num:true},
  {h:'희비', key:'SACFLY', num:true},
  {h:'진루타', key:'SACBUNT', num:true},
  {h:'실책', key:'E', num:true},
  {h:'사이클', key:'CYCLE', tag:true},
  {h:'만루HR', key:'GRANDSLAM', num:true},
];

const pitcherCols = [
  {h:'#', key:null, cls:'rank'},
  {h:'이름', key:'name', cls:'name left'},
  {h:'구분', key:'role', cls:'left'},
  {h:'소속', key:'team', cls:'left'},
  {h:'상대', key:'opponent', cls:'left'},
  {h:'LP', key:'lp', num:true},
  {h:'IP', key:'inn', cls:'left'},
  {h:'피안타', key:'H', num:true},
  {h:'자책', key:'ER', num:true},
  {h:'볼넷', key:'BB', num:true},
  {h:'탈삼진', key:'K', num:true},
  {h:'피2루타', key:'2B_A', num:true},
  {h:'피3루타', key:'3B_A', num:true},
  {h:'도루저지+견제', merge:['CS_A','PICKOFF_A'], labels:['도루 저지','견제사'], num:true},
  {h:'도루허용', key:'SB_ALLOWED', num:true},
  {h:'홀드', key:'HOLD', num:true, tip: HOLD_TIP},
  {h:'세이브', key:'SAVE', num:true, tip: SAVE_TIP},
  {h:'블론', key:'BLOWN', num:true},
  {h:'QS+', key:'QSPLUS', tag:true},
  {h:'QS', key:'QS', tag:true},
  {h:'완투', key:'CG', tag:true},
  {h:'완봉', key:'SHO', tag:true},
  {h:'노히트', key:'NOHIT', tag:true},
  {h:'퍼펙트', key:'PERFECT', tag:true},
];

function cellValue(row, col) {
  if (col.merge) {
    return col.merge.reduce((sum, k) => sum + (row.stat ? (row.stat[k] || 0) : 0), 0);
  }
  if (col.key === null) return null;
  if (col.key === 'name' || col.key === 'team' || col.key === 'opponent' ||
      col.key === 'stadium' || col.key === 'date' || col.key === 'ab' ||
      col.key === 'inn' || col.key === 'lp' || col.key === 'position' || col.key === 'role') {
    return row[col.key];
  }
  return row.stat ? row.stat[col.key] : undefined;
}

function makeRowCells(row, cols, i) {
  return cols.map(col => {
    const td = document.createElement('td');
    if (col.key === null) {
      td.textContent = i + 1;
      td.className = 'rank';
    } else if (col.key === 'lp') {
      const span = document.createElement('span');
      span.className = 'lp num ' + lpClass(row.lp);
      span.textContent = row.lp;
      td.appendChild(span);
    } else if (col.key === 'position') {
      td.className = 'left posbadge';
      td.textContent = row.position || '-';
      if (row.position_override) {
        const s = document.createElement('span');
        s.className = 'override';
        s.textContent = '●';
        s.title = '유저 수동 재지정';
        td.appendChild(s);
      }
    } else if (col.key === 'role') {
      const span = document.createElement('span');
      span.className = 'role ' + (row.role === '선발' ? 'starter' : 'reliever');
      span.textContent = row.role || '';
      td.appendChild(span);
      td.className = 'left';
    } else if (col.tag) {
      const v = cellValue(row, col);
      if (v) { const s = document.createElement('span'); s.className = 'tag'; s.textContent = '●'; td.appendChild(s); }
      td.className = 'num';
    } else if (col.merge) {
      const v = cellValue(row, col);
      td.textContent = v || 0;
      td.className = 'num';
      const breakdown = col.merge
        .map((k, i) => `${col.labels[i]} ${(row.stat && row.stat[k]) || 0}`)
        .join(' · ');
      td.title = breakdown;
    } else {
      const v = cellValue(row, col);
      td.textContent = (v === undefined || v === null) ? '' : v;
      if (col.cls) td.className = col.cls;
      else if (col.num) td.className = 'num';
    }
    return td;
  });
}

function render(tableId, cols, rows) {
  const table = document.getElementById(tableId);
  const thead = document.createElement('thead');
  const trh = document.createElement('tr');
  cols.forEach((c, i) => {
    const th = document.createElement('th');
    th.appendChild(document.createTextNode(c.h));
    if (c.tip) {
      const tip = document.createElement('span');
      tip.className = 'info-tip';
      tip.textContent = 'i';
      tip.tabIndex = 0;
      tip.addEventListener('click', e => e.stopPropagation());
      const bubble = document.createElement('span');
      bubble.className = 'bubble';
      bubble.innerHTML = c.tip;
      tip.appendChild(bubble);
      th.appendChild(tip);
    }
    if (c.cls) th.className = c.cls;
    th.dataset.idx = i;
    trh.appendChild(th);
  });
  thead.appendChild(trh);

  const tbody = document.createElement('tbody');
  table.innerHTML = '';
  table.appendChild(thead);
  table.appendChild(tbody);

  function renderBody(sorted) {
    tbody.innerHTML = '';
    sorted.forEach((row, i) => {
      const tr = document.createElement('tr');
      tr.className = 'clickable';
      tr.title = '클릭하면 상세 내역을 볼 수 있어요';
      tr.addEventListener('click', () => openPlayerModal(row));
      makeRowCells(row, cols, i).forEach(td => tr.appendChild(td));
      tbody.appendChild(tr);
    });
  }
  renderBody(rows);

  let sortState = { idx: cols.findIndex(c => c.key === 'lp'), dir: -1 };
  function applySort(rowsToSort) {
    const col = cols[sortState.idx];
    const sorted = [...rowsToSort].sort((a, b) => {
      const av = cellValue(a, col), bv = cellValue(b, col);
      if (typeof av === 'string' || typeof bv === 'string') {
        return sortState.dir * String(av).localeCompare(String(bv), 'ko');
      }
      return sortState.dir * ((bv||0) - (av||0)) * -1;
    });
    renderBody(sorted);
    [...trh.children].forEach(th => th.classList.toggle('sorted', +th.dataset.idx === sortState.idx));
    return sorted;
  }

  let currentRows = rows;
  trh.querySelectorAll('th').forEach(th => {
    th.addEventListener('click', () => {
      const idx = +th.dataset.idx;
      if (cols[idx].key === null) return;
      if (sortState.idx === idx) sortState.dir *= -1; else { sortState.idx = idx; sortState.dir = -1; }
      currentRows = applySort(currentRows);
    });
  });

  return {
    rows,
    setRows(newRows) { currentRows = newRows; applySort(newRows); },
  };
}

const bCtl = render('tbl-b', batterCols, data.batters);
const pCtl = render('tbl-p', pitcherCols, data.pitchers);
document.getElementById('count-b').textContent = data.batters.length + '명';
document.getElementById('count-p').textContent = data.pitchers.length + '명';

// --- 검색 + 포지션 필터 (타자) ---
let posFilter = '전체';
const posChipsWrap = document.getElementById('pos-chips');
Object.keys(POSITION_GROUPS).forEach(label => {
  const btn = document.createElement('button');
  btn.className = 'chip' + (label === '전체' ? ' active' : '');
  btn.textContent = label;
  btn.addEventListener('click', () => {
    posFilter = label;
    [...posChipsWrap.children].forEach(c => c.classList.toggle('active', c === btn));
    applyBatterFilters();
  });
  posChipsWrap.appendChild(btn);
});

function applyBatterFilters() {
  const q = document.getElementById('search-b').value.trim().toLowerCase();
  const groups = POSITION_GROUPS[posFilter];
  const filtered = data.batters.filter(r => {
    const matchesText = (r.name + r.team).toLowerCase().includes(q);
    const matchesPos = !groups || groups.includes(r.position);
    return matchesText && matchesPos;
  });
  bCtl.setRows(filtered);
  document.getElementById('count-b').textContent = filtered.length + '명';
}
document.getElementById('search-b').addEventListener('input', applyBatterFilters);

// --- 검색 + 역할 필터 (투수) ---
let roleFilter = '전체';
const roleChipsWrap = document.getElementById('role-chips');
['전체', '선발', '구원'].forEach(label => {
  const btn = document.createElement('button');
  btn.className = 'chip' + (label === '전체' ? ' active' : '');
  btn.textContent = label;
  btn.addEventListener('click', () => {
    roleFilter = label;
    [...roleChipsWrap.children].forEach(c => c.classList.toggle('active', c === btn));
    applyPitcherFilters();
  });
  roleChipsWrap.appendChild(btn);
});

function applyPitcherFilters() {
  const q = document.getElementById('search-p').value.trim().toLowerCase();
  const filtered = data.pitchers.filter(r => {
    const matchesText = (r.name + r.team).toLowerCase().includes(q);
    const matchesRole = roleFilter === '전체' || r.role === roleFilter;
    return matchesText && matchesRole;
  });
  pCtl.setRows(filtered);
  document.getElementById('count-p').textContent = filtered.length + '명';
}
document.getElementById('search-p').addEventListener('input', applyPitcherFilters);

// --- 챕터(타자/투수) 탭 전환 ---
document.querySelectorAll('.chip-tab').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.chip-tab').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const target = btn.dataset.chapter;
    document.getElementById('chapter-batters').classList.toggle('active', target === 'batters');
    document.getElementById('chapter-pitchers').classList.toggle('active', target === 'pitchers');
  });
});

// --- 기준일 선택 ---
const dateSelect = document.getElementById('date-select');
AVAILABLE_DATES.forEach(d => {
  const opt = document.createElement('option');
  opt.value = d;
  opt.textContent = d;
  dateSelect.appendChild(opt);
});
dateSelect.value = activeDate;

function computeTiles(d) {
  const hasData = (d.batters.length > 0) || (d.pitchers.length > 0);
  const topB = d.batters[0] || { lp: 0, name: '-', team: '-' };
  const topP = d.pitchers[0] || { lp: 0, name: '-', team: '-' };
  const games = d.batters.length
    ? new Set(d.batters.map(r => [r.team, r.opponent, r.date].join('|'))).size / 2
    : 0;
  return { hasData, topB, topP, games };
}

function renderTiles(dateStr) {
  const t = computeTiles(data);
  document.getElementById('no-data-banner').style.display = t.hasData ? 'none' : '';
  document.getElementById('tiles-main').style.display = t.hasData ? '' : 'none';
  document.getElementById('tile-games').textContent = t.games;
  document.getElementById('tile-games-meta').textContent = dateStr + ' KBO 전 경기';
  document.getElementById('tile-topb-lp').textContent = t.topB.lp;
  document.getElementById('tile-topb-meta').textContent = t.topB.name + ' · ' + t.topB.team;
  document.getElementById('tile-topp-lp').textContent = t.topP.lp;
  document.getElementById('tile-topp-meta').textContent = t.topP.name + ' · ' + t.topP.team;
  document.getElementById('tile-total').textContent = data.batters.length + data.pitchers.length;
  document.getElementById('tile-total-meta').textContent = '타자 ' + data.batters.length + ' · 투수 ' + data.pitchers.length;
  document.getElementById('tab-nb').textContent = data.batters.length + '명';
  document.getElementById('tab-np').textContent = data.pitchers.length + '명';
}

function switchDate(dateStr) {
  activeDate = dateStr;
  data = ALL_DATA[dateStr] || { batters: [], pitchers: [] };

  // 필터 상태 초기화(다른 날짜의 필터가 새 데이터에 그대로 적용돼 혼란스러운 것 방지)
  document.getElementById('search-b').value = '';
  document.getElementById('search-p').value = '';
  posFilter = '전체';
  [...posChipsWrap.children].forEach(c => c.classList.toggle('active', c.textContent === '전체'));
  roleFilter = '전체';
  [...roleChipsWrap.children].forEach(c => c.classList.toggle('active', c.textContent === '전체'));

  renderTiles(dateStr);
  applyBatterFilters();
  applyPitcherFilters();
}

dateSelect.addEventListener('change', () => switchDate(dateSelect.value));

renderTiles(activeDate);

// --- 선수 클릭 → 상세 내역 팝업 (MLB는 텍스트 중계 파서가 없어 항상 "정보 없음") ---
const modalOverlay = document.getElementById('player-modal-overlay');
const modalName = document.getElementById('modal-name');
const modalMeta = document.getElementById('modal-meta');
const modalLp = document.getElementById('modal-lp');
const modalBody = document.getElementById('modal-body');

function openPlayerModal(row) {
  modalName.textContent = row.name;
  const posOrRole = row.position ? row.position : (row.role || '');
  modalMeta.textContent = [posOrRole, row.team, row.opponent, row.date].filter(Boolean).join(' · ');
  modalLp.textContent = row.lp + ' LP';
  modalLp.style.color = row.lp > 0 ? 'var(--hot)' : (row.lp < 0 ? 'var(--cool)' : 'var(--ink-0)');

  modalBody.innerHTML = '';
  const log = row.play_log;
  if (log === undefined) {
    const p = document.createElement('div');
    p.className = 'modal-empty';
    p.textContent = 'MLB 실험판은 아직 텍스트 중계 파서가 없어서(박스스코어 스키마가 달라 KBO용 파서를 그대로 못 씀) 타석별 상세 내역은 제공하지 않아요. 표의 합산 점수만 유효합니다.';
    modalBody.appendChild(p);
  } else if (log.length === 0) {
    const p = document.createElement('div');
    p.className = 'modal-empty';
    p.textContent = '이 선수는 이번 경기에서 득점으로 이어진 개별 이벤트가 없어요 (LP 0).';
    modalBody.appendChild(p);
  } else {
    const table = document.createElement('table');
    const thead = document.createElement('thead');
    thead.innerHTML = '<tr><th>이닝</th><th>결과</th><th style="text-align:right">포인트</th></tr>';
    const tbody = document.createElement('tbody');
    log.forEach(e => {
      const tr = document.createElement('tr');
      const tdInn = document.createElement('td');
      tdInn.className = 'inn';
      tdInn.textContent = e.inn ? e.inn + '회' : '-';
      const tdText = document.createElement('td');
      tdText.textContent = e.text;
      const tdPts = document.createElement('td');
      tdPts.className = 'pts ' + (e.points > 0 ? 'pos' : (e.points < 0 ? 'neg' : ''));
      tdPts.textContent = (e.points > 0 ? '+' : '') + e.points;
      tr.append(tdInn, tdText, tdPts);
      tbody.appendChild(tr);
    });
    table.append(thead, tbody);
    modalBody.appendChild(table);
  }

  modalOverlay.classList.add('open');
}

function closePlayerModal() {
  modalOverlay.classList.remove('open');
}

document.getElementById('player-modal-close').addEventListener('click', closePlayerModal);
modalOverlay.addEventListener('click', e => {
  if (e.target === modalOverlay) closePlayerModal();
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closePlayerModal();
});
</script>
"""

html_doc = (html_doc
    .replace("__DATE__", date_str)
    .replace("__GAMES__", str(games_count))
    .replace("__TOP_B_LP__", str(top_batter["lp"]))
    .replace("__TOP_B_NAME__", top_batter["name"])
    .replace("__TOP_B_TEAM__", top_batter["team"])
    .replace("__TOP_P_LP__", str(top_pitcher["lp"]))
    .replace("__TOP_P_NAME__", top_pitcher["name"])
    .replace("__TOP_P_TEAM__", top_pitcher["team"])
    .replace("__TOTAL_PLAYERS__", str(len(batters) + len(pitchers)))
    .replace("__NB__", str(len(batters)))
    .replace("__NP__", str(len(pitchers)))
    .replace("__DATA_JSON__", payload)
    .replace("__LAST_UPDATE__", last_update)
)

out_path = os.path.join(here, "lp_board_mlb.html")
with open(out_path, "w", encoding="utf-8") as f:
    f.write(html_doc)
print(f"wrote {len(html_doc)} bytes -> {out_path}")
