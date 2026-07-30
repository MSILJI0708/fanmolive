import argparse
import glob
import json
import os
import re

ap = argparse.ArgumentParser(description="수집된 data_<date>.json 전부를 모아 날짜 선택이 가능한 LP 보드 HTML을 만든다")
ap.add_argument("--date", default=None, help="처음 열었을 때 보여줄 기준일 YYYY-MM-DD (생략 시 가장 최근 수집일)")
args = ap.parse_args()

here = os.path.dirname(os.path.abspath(__file__))

all_data: dict[str, dict] = {}
# data_????????.json 만 (KBO). data_mlb_*.json은 별도 리그라 build_mlb_board.py가 처리한다.
for path in sorted(glob.glob(os.path.join(here, "data_????????.json"))):
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    m = re.search(r"data_(\d{8})\.json$", path)
    ds = d.get("date") or f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:8]}"
    all_data[ds] = {"batters": d["batters"], "pitchers": d["pitchers"]}

if not all_data:
    raise SystemExit("data_*.json 파일이 없습니다. 먼저 daily_pipeline.py로 데이터를 수집하세요.")

date_str = args.date if args.date in all_data else max(all_data.keys())
batters = all_data[date_str]["batters"]
pitchers = all_data[date_str]["pitchers"]

has_data = bool(batters or pitchers)
top_batter = batters[0] if batters else {"lp": 0, "name": "-", "team": "-"}
top_pitcher = pitchers[0] if pitchers else {"lp": 0, "name": "-", "team": "-"}
games_count = len({(r["team"], r["opponent"], r["date"]) for r in batters}) // 2 if batters else 0

payload = json.dumps(all_data, ensure_ascii=False)

html_doc = """<!doctype html>
<title>KBO 판타지 LP 보드 · __DATE__</title>
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
.chip.group-chip { display: inline-flex; align-items: center; gap: 5px; }
.chip.group-chip .sign {
  display: inline-flex; align-items: center; justify-content: center;
  width: 13px; height: 13px; border-radius: 4px;
  background: var(--paper-0); color: var(--ink-1); font-size: 10px; font-weight: 700;
}
.chip.group-chip.expanded .sign { background: var(--accent); color: #fff; }

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
  max-width: 660px;
  max-height: 85vh;
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
.modal-head { margin-bottom: 14px; padding-right: 30px; }
.modal-name { font-size: 19px; font-weight: 700; }
.modal-meta { font-size: 12.5px; color: var(--ink-1); margin-top: 3px; }
.modal-lp { font-size: 26px; font-weight: 700; margin-top: 8px; }

.modal-view-toggle {
  display: flex;
  gap: 4px;
  margin-bottom: 14px;
  border-bottom: 1px solid var(--line);
}
.modal-view-toggle button {
  font: inherit;
  font-size: 12.5px;
  font-weight: 700;
  padding: 7px 14px;
  background: none;
  border: none;
  color: var(--ink-1);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
}
.modal-view-toggle button.active { color: var(--ink-0); border-bottom-color: var(--accent); }

/* 타임라인 보기 */
.modal-body table { width: 100%; border-collapse: collapse; font-size: 12px; table-layout: fixed; }
.modal-body th {
  text-align: left;
  font-size: 10.5px;
  color: var(--ink-1);
  text-transform: uppercase;
  letter-spacing: .03em;
  padding: 5px 6px;
  border-bottom: 1px solid var(--line);
}
.modal-body td { padding: 5px 6px; border-bottom: 1px solid var(--line); vertical-align: top; overflow-wrap: anywhere; text-align: left; }
.modal-body tr:last-child td { border-bottom: none; }
.modal-body td.inn { color: var(--ink-1); white-space: nowrap; width: 34px; }
/* result 컬럼은 width:0으로 줘야 fixed 레이아웃에서 내용 길이로 컬럼이 안 늘어나고
   남은 공간 안에서만 줄바꿈된다(고정폭 테이블의 "가변 컬럼" 트릭) */
.modal-body td.result { width: 0; }
.modal-body td.pts { text-align: right; font-weight: 700; white-space: nowrap; width: 52px; }
.modal-body td.pts.pos { color: var(--hot); }
.modal-body td.pts.neg { color: var(--cool); }
.modal-empty { color: var(--ink-1); font-size: 13px; padding: 10px 0; }

/* 카테고리 보기 (아코디언) */
.cat-group {
  border: 1px solid var(--line);
  border-radius: 8px;
  margin-bottom: 8px;
  overflow: hidden;
}
.cat-group-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  cursor: pointer;
  background: var(--chip-bg);
  user-select: none;
}
.cat-group-head .cat-name { font-weight: 700; font-size: 13.5px; display: flex; align-items: center; gap: 8px; }
.cat-group-head .cat-toggle-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px; height: 18px;
  border-radius: 5px;
  background: var(--paper-1);
  border: 1px solid var(--line);
  font-size: 12px;
  font-weight: 700;
  flex-shrink: 0;
}
.cat-group-head .cat-total { font-weight: 700; font-size: 14px; }
.cat-group-body { display: none; padding: 4px 14px 8px; }
.cat-group.expanded .cat-group-body { display: block; }
.cat-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 0;
  font-size: 12.5px;
  border-bottom: 1px dashed var(--line);
}
.cat-item:last-child { border-bottom: none; }
.cat-item .cat-item-label { color: var(--ink-0); }
.cat-item .cat-item-count { color: var(--ink-1); font-size: 11.5px; margin-left: 6px; }
.cat-item .cat-item-pts { font-weight: 700; white-space: nowrap; }
.cat-item .cat-item-flag {
  display: inline-block;
  width: 9px; height: 9px;
  border-radius: 50%;
  background: var(--line);
  margin-right: 7px;
}
.cat-item .cat-item-flag.on { background: var(--hot); }

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
  <p class="eyebrow">KBO 판타지 모드 · 라이브 포인트</p>
  <h1>선수 카드 LP 보드</h1>
  <p class="sub">
    기준일
    <select id="date-select" class="date-select"></select>
    · 데이터 출처 <code>api-gw.sports.naver.com</code> (Selenium 불필요, 공개 JSON 응답 직접 호출)
    · <a href="mlb.html">MLB 실험판 보기 →</a>
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
    <div class="rule-bar">
      <label>타 포지션 수비기록 인정
        <select id="pos-mode">
          <option value="1">그 포지션에서만</option>
          <option value="2">내야는 내야끼리, 외야는 외야끼리 허용</option>
          <option value="3" selected>제약 없음</option>
        </select>
      </label>
      <label class="toggle">
        <input type="checkbox" id="dh-defense-toggle" />
        지명타자 등록 선수의 수비기록도 인정
      </label>
      <span class="rule-note">보살·외야보살·병살가담·삼중살가담·도루저지(포)·도루허용(포)에만 적용됨</span>
    </div>
    <div class="chips" id="batter-mode-chips"></div>
    <div class="chips" id="batter-group-chips"></div>
    <div class="tablewrap"><table id="tbl-b"></table></div>
  </section>

  <section class="board" id="chapter-pitchers">
    <div class="board-head">
      <input class="search" id="search-p" placeholder="이름·소속 검색" />
      <span class="count" id="count-p"></span>
    </div>
    <div class="chips" id="role-chips"></div>
    <div class="chips" id="pitcher-mode-chips"></div>
    <div class="chips" id="pitcher-group-chips"></div>
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
    <div class="modal-view-toggle">
      <button id="modal-view-category" class="active">카테고리 보기</button>
      <button id="modal-view-timeline">타임라인 보기</button>
    </div>
    <div class="modal-body" id="modal-body"></div>
  </div>
</div>

<footer class="notes">
  <b>포지션 판정.</b> 기준일 이전 최근 14일간 수비 출전 기록(포지션별 수비 이닝 추정)에서
  가장 많이 뛴 포지션을 자동 배정하며(9UP 방식과 동일한 로직), 유저가
  <code>position_admin_server.py</code>의 폼을 통해 직접 재지정하면 <span class="posbadge">
  <span class="override">●</span></span> 표시와 함께 그 값이 우선 적용된다(로컬
  <code>position_db.json</code>에 저장·보존).<br>
  <b>텍스트 중계(relay) 기반 심화 기록.</b> 박스스코어에는 없지만 네이버의 타석별 텍스트 중계(주자
  상황·포지션 교체·수비 체인이 문장으로 기록됨)를 별도로 파싱해 다음을 채운다 — 보살/외야수 보살/
  병살·삼중살 가담(아웃 처리에 관여한 수비수를 "OO→OO 송구아웃" 체인에서 추출), 포수·투수 양쪽의
  도루 저지·허용(그 시점의 포수·투수를 각각 추적), 투수의 견제사(투수가 직접 던진 견제만 인정,
  포수의 견제 송구는 제외), 투수의 피2루타·피3루타(그 시점의 투수를 추적), 승계주자 실점 허용·막음
  (교체 시점의 주자를 물려받아 그 하프이닝이 끝날 때까지 득점 여부 추적), 타자의 진루타(번트든
  아니든 그 타구로 아웃되면서 다른 주자를 진루시켰는지를 판정 — 원래 규정이 "번트를 포함해 진루를
  시키는 타구 모두 포함"이라 명시하고 있어, 박스스코어의 '번트' 표기 여부보다 이 판정이 규정에 더
  가깝다). 위치 추적은 중계 텍스트의 교체 이벤트만으로 재구성한 근사치라, 아주 드물게 동명이인
  겹침이나 누락된 중계 이벤트가 있으면 오차가 날 수 있다.<br>
  <b>표시 병합(집계는 그대로).</b> 사사구(볼넷+사구), 주루사(도루실패+견제사, 타자), 도루저지+견제
  (투수)는 화면에서만 합쳐 보여주고, 실제 LP 계산과 저장 데이터는 원래 항목별 가중치(예: 도루실패
  -15 / 견제사 -10)를 그대로 각각 적용한다 — 합친 숫자에 마우스를 올리면 항목별 내역이 뜬다.<br>
  <b>타 포지션 수비기록 규칙.</b> 등록 포지션과 다른 자리에서 난 보살·외야보살·병살/삼중살 가담·
  도루 저지·허용(포수)은 타자 탭 상단 드롭다운으로 즉시 바꿔볼 수 있다 — ① 그 포지션에서만 인정
  ② 내야는 내야끼리·외야는 외야끼리만 인정 ③ 제약 없음(기본값). 지명타자로 등록된 선수의 수비
  기록은 이 드롭다운과 별개로 옆 토글로 켜고 끌 수 있으며, 기본값은 카드 각주("지명타자 슬롯에
  들어간 선수의 수비 기록은 인정하지 않는다")를 따라 꺼져 있다.<br>
  <b>여전히 못 채우는 항목.</b> 삼중살 가담은 로직은 있지만 실제 경기에서 발생 예시를 못 봐 검증되지
  않았고(사실상 발생 극히 드묾), 일반 아웃에서 포구만 하고 어시스트 없이 끝나는 단독 수비(보살 없음)는
  정확히 구분해 0으로 처리한다. 중계 텍스트 자체가 없거나 형식이 다른 경기(우천 콜드, 예년 이전 경기 등)는
  이 심화 기록 없이 기본 박스스코어 점수만 반영된다.<br>
  사이클히트·만루홈런·병살·실책·폭투·보크·홀드·세이브·블론세이브·QS·QS+·완투·완봉·노히트·퍼펙트는
  박스스코어와 경기 특이기록(etcRecords)에서 자동 판별함.
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

// 등록 포지션과 실제 수비 위치 비교용 (naver_fantasy_score.py의 FIELD_GROUP과 동일하게 유지)
const FIELD_GROUP = {
  '포수': '포수', '1루수': '내야', '2루수': '내야', '3루수': '내야', '유격수': '내야',
  '좌익수': '외야', '중견수': '외야', '우익수': '외야',
};
// 이 6개 항목의 가중치(naver_fantasy_score.py BATTER_POINTS와 동일하게 유지)
const FIELD_WEIGHTS = { ASSIST: 1, OF_ASSIST: 30, DP_FIELD: 10, TP_FIELD: 50, CS_CATCHER: 40, SB_ALLOWED_CATCHER: -10 };

function positionAllowed(eventPos, registeredPos, mode, dhDefenseOn) {
  if (registeredPos === '지명타자') return dhDefenseOn;
  if (!registeredPos) return true;
  if (mode === '1') return eventPos === registeredPos;
  if (mode === '2') return FIELD_GROUP[eventPos] === FIELD_GROUP[registeredPos];
  return true; // mode === '3'
}

function aggregateFieldEvents(events, registeredPos, mode, dhDefenseOn) {
  const counts = { ASSIST: 0, OF_ASSIST: 0, CS_CATCHER: 0, SB_ALLOWED_CATCHER: 0 };
  let dp = false, tp = false;
  (events || []).forEach(ev => {
    if (!positionAllowed(ev.pos, registeredPos, mode, dhDefenseOn)) return;
    if (ev.type === 'DP') dp = true;
    else if (ev.type === 'TP') tp = true;
    else counts[ev.type] = (counts[ev.type] || 0) + 1;
  });
  counts.DP_FIELD = dp ? 1 : 0;
  counts.TP_FIELD = tp ? 1 : 0;
  return counts;
}

function applyFieldRule(mode, dhDefenseOn) {
  data.batters.forEach(row => {
    if (!row.position_events) return;
    const fresh = aggregateFieldEvents(row.position_events, row.position, mode, dhDefenseOn);
    let delta = 0;
    Object.keys(FIELD_WEIGHTS).forEach(key => {
      delta += (fresh[key] - row.stat[key]) * FIELD_WEIGHTS[key];
      row.stat[key] = fresh[key];
    });
    row.lp += delta;
  });
}

function lpClass(v) {
  if (v >= 150) return 'hot';
  if (v >= 60) return 'warm';
  if (v < 0) return 'cool';
  return '';
}

// 표 상단 "카테고리 방식" 보기용 가중치(naver_fantasy_score.py BATTER_POINTS/PITCHER_POINTS와 동일)
const BATTER_POINTS_JS = {
  R: 15, H: 10, BB: 10, '2B': 15, '3B': 30, HR: 80, RBI: 25,
  FO: -10, GO: -10, GDP: -25, SACFLY: 10, SACBUNT: 10, SB: 30, CS: -15,
  HBP: 5, K: -15, PICKOFF: -10, CYCLE: 50, GRANDSLAM: 10, E: -10,
  ASSIST: 1, DP_FIELD: 10, TP_FIELD: 50, OF_ASSIST: 30,
  CS_CATCHER: 40, SB_ALLOWED_CATCHER: -10,
};
const PITCHER_POINTS_JS = {
  H: -10, '2B_A': -10, '3B_A': -15, HR: -40, ER: -10, BB: -10, HBP: -10, WP: -20,
  OUT: 10, K: 15, BK: -50, QS: 20, QSPLUS: 30,
  INHERITED_SCORED: -5, INHERITED_STRANDED: 5,
  CS_A: 10, SB_ALLOWED: -10, PICKOFF_A: 10,
  HOLD: 20, SAVE: 30, BLOWN: -10, PERFECT: 100, NOHIT: 70, SHO: 30, CG: 15,
};

// 표에서 "카테고리 방식"으로 볼 때 쓰는 그룹 정의(팝업의 categories와 라벨은 맞추되,
// 투수는 선발/구원 구분 없이 통합 - 표는 두 역할이 섞여 있어 항목을 안 나눌 수 없음).
const BATTER_GROUP_DEFS = {
  '출루': [{ label: '안타', key: 'H' }, { label: '볼넷', key: 'BB' }, { label: '사구', key: 'HBP' }],
  '장타': [
    { label: '2루타', key: '2B' }, { label: '3루타', key: '3B' }, { label: '홈런', key: 'HR' },
    { label: '만루홈런', key: 'GRANDSLAM' }, { label: '사이클히트', key: 'CYCLE', flag: true },
  ],
  '팀배팅': [{ label: '타점', key: 'RBI' }, { label: '진루타', key: 'SACBUNT' }, { label: '희생플라이', key: 'SACFLY' }],
  '주루': [{ label: '도루', key: 'SB' }, { label: '도루실패', key: 'CS' }, { label: '견제사', key: 'PICKOFF' }, { label: '득점', key: 'R' }],
  '수비': [
    { label: '보살', key: 'ASSIST' }, { label: '외야수 보살', key: 'OF_ASSIST' },
    { label: '병살 가담', key: 'DP_FIELD' }, { label: '삼중살 가담', key: 'TP_FIELD' },
    { label: '도루 저지(포)', key: 'CS_CATCHER' }, { label: '도루 허용(포)', key: 'SB_ALLOWED_CATCHER' },
    { label: '실책', key: 'E' },
  ],
  '아웃': [{ label: '뜬공 아웃', key: 'FO' }, { label: '땅볼 아웃', key: 'GO' }, { label: '병살타', key: 'GDP' }, { label: '삼진', key: 'K' }],
};
const PITCHER_GROUP_DEFS = {
  '기본': [{ label: '아웃카운트', key: 'OUT' }, { label: '자책점', key: 'ER' }, { label: '탈삼진', key: 'K' }],
  '출루허용': [{ label: '피안타', key: 'H' }, { label: '볼넷', key: 'BB' }, { label: '사구', key: 'HBP' }],
  '장타허용': [{ label: '피2루타', key: '2B_A' }, { label: '피3루타', key: '3B_A' }, { label: '피홈런', key: 'HR' }],
  '주자억제': [
    { label: '도루 허용', key: 'SB_ALLOWED' }, { label: '도루 저지', key: 'CS_A' }, { label: '견제사', key: 'PICKOFF_A' },
    { label: '폭투', key: 'WP' }, { label: '보크', key: 'BK' },
    { label: '승계주자 실점 허용', key: 'INHERITED_SCORED' }, { label: '승계주자 실점 막음', key: 'INHERITED_STRANDED' },
  ],
  '특별': [
    { label: 'QS+', key: 'QSPLUS', flag: true }, { label: 'QS', key: 'QS', flag: true },
    { label: '완투', key: 'CG', flag: true }, { label: '완봉', key: 'SHO', flag: true },
    { label: '노히트', key: 'NOHIT', flag: true }, { label: '퍼펙트', key: 'PERFECT', flag: true },
    { label: '홀드', key: 'HOLD', flag: true }, { label: '세이브', key: 'SAVE', flag: true }, { label: '블론세이브', key: 'BLOWN', flag: true },
  ],
};

function groupTotal(row, items, weights) {
  return items.reduce((sum, it) => {
    const v = row.stat ? (row.stat[it.key] || 0) : 0;
    const w = weights[it.key] || 0;
    return sum + (it.flag ? (v ? w : 0) : v * w);
  }, 0);
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

const batterColsFlat = [
  {h:'#', key:null, cls:'rank'},
  {h:'이름', key:'name', cls:'name left'},
  {h:'포지션', key:'position', cls:'left'},
  {h:'소속', key:'team', cls:'left'},
  {h:'상대', key:'opponent', cls:'left'},
  {h:'구장', key:'stadium', cls:'left'},
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
  {h:'보살', key:'ASSIST', num:true},
  {h:'외야보살', key:'OF_ASSIST', num:true},
  {h:'병살가담', key:'DP_FIELD', num:true},
  {h:'삼중살가담', key:'TP_FIELD', num:true},
  {h:'도루저지(포)', key:'CS_CATCHER', num:true},
  {h:'도루허용(포)', key:'SB_ALLOWED_CATCHER', num:true},
  {h:'사이클', key:'CYCLE', tag:true},
  {h:'만루HR', key:'GRANDSLAM', num:true},
];

const pitcherColsFlat = [
  {h:'#', key:null, cls:'rank'},
  {h:'이름', key:'name', cls:'name left'},
  {h:'구분', key:'role', cls:'left'},
  {h:'소속', key:'team', cls:'left'},
  {h:'상대', key:'opponent', cls:'left'},
  {h:'구장', key:'stadium', cls:'left'},
  {h:'LP', key:'lp', num:true},
  {h:'IP', key:'inn', cls:'left'},
  {h:'피안타', key:'H', num:true},
  {h:'자책', key:'ER', num:true},
  {h:'사사구', merge:['BB','HBP'], labels:['볼넷','사구'], num:true},
  {h:'탈삼진', key:'K', num:true},
  {h:'피2루타', key:'2B_A', num:true},
  {h:'피3루타', key:'3B_A', num:true},
  {h:'폭투', key:'WP', num:true},
  {h:'보크', key:'BK', num:true},
  {h:'승계실점허용', key:'INHERITED_SCORED', num:true},
  {h:'승계실점막음', key:'INHERITED_STRANDED', num:true},
  {h:'도루저지+견제', merge:['CS_A','PICKOFF_A'], labels:['도루 저지(투수)','견제사(투수)'], num:true},
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
  if (col.compute) {
    return col.compute(row);
  }
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
    } else if (col.groupTotal) {
      const v = cellValue(row, col);
      const span = document.createElement('span');
      span.className = 'lp num ' + lpClass(v);
      span.textContent = (v > 0 ? '+' : '') + v;
      td.appendChild(span);
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
      tr.title = '클릭하면 타석/수비별 포인트 내역을 볼 수 있어요';
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

const BATTER_LEADING_COLS = [
  {h:'#', key:null, cls:'rank'},
  {h:'이름', key:'name', cls:'name left'},
  {h:'포지션', key:'position', cls:'left'},
  {h:'소속', key:'team', cls:'left'},
  {h:'상대', key:'opponent', cls:'left'},
  {h:'구장', key:'stadium', cls:'left'},
  {h:'LP', key:'lp', num:true},
  {h:'타수', key:'ab', num:true},
];
const PITCHER_LEADING_COLS = [
  {h:'#', key:null, cls:'rank'},
  {h:'이름', key:'name', cls:'name left'},
  {h:'구분', key:'role', cls:'left'},
  {h:'소속', key:'team', cls:'left'},
  {h:'상대', key:'opponent', cls:'left'},
  {h:'구장', key:'stadium', cls:'left'},
  {h:'LP', key:'lp', num:true},
  {h:'IP', key:'inn', cls:'left'},
];

function buildGroupedCols(leadingCols, groupDefs, expandState, weights) {
  const cols = [...leadingCols];
  Object.keys(groupDefs).forEach(gname => {
    const items = groupDefs[gname];
    if (expandState[gname]) {
      items.forEach(it => {
        cols.push({
          h: it.label, tag: !!it.flag, num: !it.flag,
          compute: row => {
            const v = row.stat ? (row.stat[it.key] || 0) : 0;
            return it.flag ? (v ? 1 : 0) : v;
          },
        });
      });
    } else {
      cols.push({ h: gname, groupTotal: true, compute: row => groupTotal(row, items, weights) });
    }
  });
  return cols;
}

let batterTableMode = 'flat'; // 'flat' | 'grouped'
const batterGroupExpand = { '출루': false, '장타': false, '팀배팅': false, '주루': false, '수비': false, '아웃': false };
let pitcherTableMode = 'flat';
const pitcherGroupExpand = { '기본': false, '출루허용': false, '장타허용': false, '주자억제': false, '특별': false };

function getBatterCols() {
  return batterTableMode === 'grouped'
    ? buildGroupedCols(BATTER_LEADING_COLS, BATTER_GROUP_DEFS, batterGroupExpand, BATTER_POINTS_JS)
    : batterColsFlat;
}
function getPitcherCols() {
  return pitcherTableMode === 'grouped'
    ? buildGroupedCols(PITCHER_LEADING_COLS, PITCHER_GROUP_DEFS, pitcherGroupExpand, PITCHER_POINTS_JS)
    : pitcherColsFlat;
}

let bCtl = render('tbl-b', getBatterCols(), data.batters);
let pCtl = render('tbl-p', getPitcherCols(), data.pitchers);
document.getElementById('count-b').textContent = data.batters.length + '명';
document.getElementById('count-p').textContent = data.pitchers.length + '명';

function rebuildBatterTable() {
  bCtl = render('tbl-b', getBatterCols(), data.batters);
  applyBatterFilters();
}
function rebuildPitcherTable() {
  pCtl = render('tbl-p', getPitcherCols(), data.pitchers);
  applyPitcherFilters();
}

function renderModeChips(wrapId, onFlat, onGrouped) {
  const wrap = document.getElementById(wrapId);
  const flatBtn = document.createElement('button');
  flatBtn.className = 'chip active';
  flatBtn.textContent = '기존 방식 (전체 컬럼)';
  const groupBtn = document.createElement('button');
  groupBtn.className = 'chip';
  groupBtn.textContent = '카테고리 방식 (그룹 접기/펼치기)';
  flatBtn.addEventListener('click', () => {
    flatBtn.classList.add('active');
    groupBtn.classList.remove('active');
    onFlat();
  });
  groupBtn.addEventListener('click', () => {
    groupBtn.classList.add('active');
    flatBtn.classList.remove('active');
    onGrouped();
  });
  wrap.append(flatBtn, groupBtn);
}

function renderGroupChips(wrapId, groupDefs, expandState, rebuildFn) {
  const wrap = document.getElementById(wrapId);
  wrap.innerHTML = '';
  Object.keys(groupDefs).forEach(gname => {
    const btn = document.createElement('button');
    btn.className = 'chip group-chip' + (expandState[gname] ? ' expanded' : '');
    const sign = document.createElement('span');
    sign.className = 'sign';
    sign.textContent = expandState[gname] ? '−' : '+';
    btn.append(sign, document.createTextNode(gname));
    btn.addEventListener('click', () => {
      expandState[gname] = !expandState[gname];
      renderGroupChips(wrapId, groupDefs, expandState, rebuildFn);
      rebuildFn();
    });
    wrap.appendChild(btn);
  });
}

renderModeChips('batter-mode-chips',
  () => { batterTableMode = 'flat'; document.getElementById('batter-group-chips').style.display = 'none'; rebuildBatterTable(); },
  () => { batterTableMode = 'grouped'; document.getElementById('batter-group-chips').style.display = ''; renderGroupChips('batter-group-chips', BATTER_GROUP_DEFS, batterGroupExpand, rebuildBatterTable); rebuildBatterTable(); },
);
document.getElementById('batter-group-chips').style.display = 'none';

renderModeChips('pitcher-mode-chips',
  () => { pitcherTableMode = 'flat'; document.getElementById('pitcher-group-chips').style.display = 'none'; rebuildPitcherTable(); },
  () => { pitcherTableMode = 'grouped'; document.getElementById('pitcher-group-chips').style.display = ''; renderGroupChips('pitcher-group-chips', PITCHER_GROUP_DEFS, pitcherGroupExpand, rebuildPitcherTable); rebuildPitcherTable(); },
);
document.getElementById('pitcher-group-chips').style.display = 'none';

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

// --- 타 포지션 수비기록 인정 규칙 (드롭다운 + 지명타자 토글) ---
const posModeSelect = document.getElementById('pos-mode');
const dhToggle = document.getElementById('dh-defense-toggle');
function onFieldRuleChange() {
  applyFieldRule(posModeSelect.value, dhToggle.checked);
  applyBatterFilters();
}
posModeSelect.addEventListener('change', onFieldRuleChange);
dhToggle.addEventListener('change', onFieldRuleChange);

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
  posModeSelect.value = '3';
  dhToggle.checked = false;

  renderTiles(dateStr);
  applyBatterFilters();
  applyPitcherFilters();
}

dateSelect.addEventListener('change', () => switchDate(dateSelect.value));

renderTiles(activeDate);

// --- 선수 클릭 → 타석/수비별 포인트 내역 팝업 ---
const modalOverlay = document.getElementById('player-modal-overlay');
const modalName = document.getElementById('modal-name');
const modalMeta = document.getElementById('modal-meta');
const modalLp = document.getElementById('modal-lp');
const modalBody = document.getElementById('modal-body');
const modalViewCategoryBtn = document.getElementById('modal-view-category');
const modalViewTimelineBtn = document.getElementById('modal-view-timeline');

let currentModalRow = null;
let currentModalView = 'category'; // 'category' | 'timeline'

function renderTimelineView(row) {
  modalBody.innerHTML = '';
  const log = row.play_log;
  if (log === undefined) {
    const p = document.createElement('div');
    p.className = 'modal-empty';
    p.textContent = '이 경기는 텍스트 중계 조회에 실패했거나 지원되지 않는 리그라 상세 내역이 없어요. 표의 합산 점수만 유효합니다.';
    modalBody.appendChild(p);
    return;
  }
  if (log.length === 0) {
    const p = document.createElement('div');
    p.className = 'modal-empty';
    p.textContent = '이 선수는 이번 경기에서 득점으로 이어진 개별 이벤트가 없어요 (LP 0).';
    modalBody.appendChild(p);
    return;
  }
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
    tdText.className = 'result';
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

function renderCategoryView(row) {
  modalBody.innerHTML = '';
  const cats = row.categories;
  if (!cats) {
    const p = document.createElement('div');
    p.className = 'modal-empty';
    p.textContent = '이 리그는 아직 카테고리별 세부 내역을 지원하지 않아요. 표의 합산 점수만 유효합니다.';
    modalBody.appendChild(p);
    return;
  }
  cats.forEach((group, gi) => {
    const wrap = document.createElement('div');
    wrap.className = 'cat-group';

    const head = document.createElement('div');
    head.className = 'cat-group-head';
    const nameSpan = document.createElement('span');
    nameSpan.className = 'cat-name';
    const icon = document.createElement('span');
    icon.className = 'cat-toggle-icon';
    icon.textContent = '+';
    nameSpan.append(icon, document.createTextNode(group.name));
    const totalSpan = document.createElement('span');
    totalSpan.className = 'cat-total';
    totalSpan.textContent = (group.total > 0 ? '+' : '') + group.total;
    totalSpan.style.color = group.total > 0 ? 'var(--hot)' : (group.total < 0 ? 'var(--cool)' : 'var(--ink-1)');
    head.append(nameSpan, totalSpan);

    const body = document.createElement('div');
    body.className = 'cat-group-body';
    const visibleItems = group.items.filter(it => it.flag ? true : it.count);
    if (visibleItems.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'cat-item';
      empty.innerHTML = '<span class="cat-item-label" style="color:var(--ink-1)">해당 없음</span>';
      body.appendChild(empty);
    }
    visibleItems.forEach(it => {
      const row2 = document.createElement('div');
      row2.className = 'cat-item';
      const left = document.createElement('span');
      if (it.flag) {
        const dot = document.createElement('span');
        dot.className = 'cat-item-flag' + (it.count ? ' on' : '');
        left.appendChild(dot);
        left.appendChild(document.createTextNode(it.label));
      } else {
        left.className = 'cat-item-label';
        left.textContent = it.label;
        const cnt = document.createElement('span');
        cnt.className = 'cat-item-count';
        cnt.textContent = it.count + '개';
        left.appendChild(cnt);
      }
      const right = document.createElement('span');
      right.className = 'cat-item-pts';
      if (it.info) {
        right.style.color = 'var(--ink-1)';
        right.textContent = it.flag ? (it.count ? '조건 만족' : '') : '';
      } else {
        right.style.color = it.points > 0 ? 'var(--hot)' : (it.points < 0 ? 'var(--cool)' : 'var(--ink-1)');
        right.textContent = (it.points > 0 ? '+' : '') + it.points;
      }
      row2.append(left, right);
      body.appendChild(row2);
    });

    head.addEventListener('click', () => wrap.classList.toggle('expanded'));
    if (gi === 0) wrap.classList.add('expanded'); // 첫 그룹은 기본으로 펼쳐서 보여줌
    wrap.append(head, body);
    modalBody.appendChild(wrap);
  });
}

function renderModalBody() {
  if (!currentModalRow) return;
  if (currentModalView === 'timeline') renderTimelineView(currentModalRow);
  else renderCategoryView(currentModalRow);
}

modalViewCategoryBtn.addEventListener('click', () => {
  currentModalView = 'category';
  modalViewCategoryBtn.classList.add('active');
  modalViewTimelineBtn.classList.remove('active');
  renderModalBody();
});
modalViewTimelineBtn.addEventListener('click', () => {
  currentModalView = 'timeline';
  modalViewTimelineBtn.classList.add('active');
  modalViewCategoryBtn.classList.remove('active');
  renderModalBody();
});

function openPlayerModal(row) {
  currentModalRow = row;
  modalName.textContent = row.name;
  const posOrRole = row.position ? row.position : (row.role || '');
  const vsOpponent = row.opponent ? ('vs ' + row.opponent) : '';
  modalMeta.textContent = [posOrRole, row.team, vsOpponent, row.date].filter(Boolean).join(' · ');
  modalLp.textContent = row.lp + ' LP';
  modalLp.style.color = row.lp > 0 ? 'var(--hot)' : (row.lp < 0 ? 'var(--cool)' : 'var(--ink-0)');

  renderModalBody();
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
)

out_path = os.path.join(here, "lp_board.html")
with open(out_path, "w", encoding="utf-8") as f:
    f.write(html_doc)
print(f"wrote {len(html_doc)} bytes -> {out_path}")
