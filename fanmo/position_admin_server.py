"""
포지션 수동 재지정 관리자 (로컬 전용)
====================================
9UP은 2주 수비 기록으로 산정한 기본 포지션을 유저가 임의로 바꿀 수 있다고 했다.
이 서버는 position_db.json을 웹 폼으로 편집할 수 있게 해주는 아주 작은 로컬 도구다.
외부 라이브러리 없이 표준 라이브러리(http.server)만 사용한다.

사용법
------
    python position_admin_server.py
    → http://127.0.0.1:8765 접속

주의: 로컬 전용이다. 127.0.0.1에만 바인드하며(외부 접근 불가), 디스크에
position_db.json을 직접 덮어쓰므로 신뢰할 수 없는 네트워크에 노출하지 말 것.
"""

from __future__ import annotations

import html
import json
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

from position import ALL_POSITIONS, load_db, set_manual_position

HOST, PORT = "127.0.0.1", 8765


def render_page(message: str = "") -> str:
    db = load_db()
    players = sorted(db["players"].items(), key=lambda kv: kv[1]["name"])

    options = []
    for code, rec in players:
        label = f"{rec['name']} ({rec['team']} · #{code}) — 자동:{rec['auto_position']}"
        if rec.get("manual_position"):
            label += f" / 수동:{rec['manual_position']}"
        options.append(f'<option value="{html.escape(code)}">{html.escape(label)}</option>')

    pos_options = "".join(
        f'<option value="{html.escape(p)}">{html.escape(p)}</option>' for p in ALL_POSITIONS
    )

    rows = []
    for code, rec in players:
        override = rec.get("manual_position")
        rows.append(
            "<tr>"
            f"<td>{html.escape(rec['name'])}</td>"
            f"<td>{html.escape(rec['team'])}</td>"
            f"<td>{html.escape(rec['auto_position'])}</td>"
            f"<td class='{'override' if override else ''}'>{html.escape(override or '-')}</td>"
            f"<td><b>{html.escape(rec['effective_position'])}</b></td>"
            f"<td>{code}</td>"
            "</tr>"
        )

    msg_html = f"<p class='msg'>{html.escape(message)}</p>" if message else ""

    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<title>포지션 수동 재지정</title>
<style>
  body {{ font-family: "Malgun Gothic", sans-serif; max-width: 900px; margin: 32px auto; color:#1c1a15; }}
  h1 {{ font-size: 18px; }}
  form {{ display:flex; gap:10px; align-items:center; flex-wrap:wrap; background:#f3f1ea; padding:14px; border-radius:8px; }}
  select, button {{ padding:7px 10px; font-size:13px; }}
  .msg {{ color:#1a7d3a; font-weight:600; }}
  table {{ border-collapse:collapse; width:100%; margin-top:20px; font-size:12.5px; }}
  th, td {{ border:1px solid #dcd8cc; padding:5px 8px; text-align:left; }}
  th {{ background:#efe9d8; }}
  td.override {{ color:#b6402f; font-weight:700; }}
  .reset {{ color:#888; }}
</style></head>
<body>
  <h1>타자 포지션 수동 재지정</h1>
  {msg_html}
  <form method="post" action="/set-position">
    <label>선수
      <select name="player_code" required>
        <option value="" disabled selected>선수 선택 (동명이인은 소속·코드로 구분)</option>
        {''.join(options)}
      </select>
    </label>
    <label>옮길 포지션
      <select name="new_position" required>
        <option value="__AUTO__" class="reset">자동 산정값으로 복귀</option>
        {pos_options}
      </select>
    </label>
    <button type="submit">반영</button>
  </form>
  <table>
    <thead><tr><th>이름</th><th>소속</th><th>자동</th><th>수동</th><th>적용값</th><th>코드</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # noqa: A003
        pass  # 조용히 (기본 stderr 액세스 로그 생략)

    def _send_html(self, body: str, status: int = 200):
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        if self.path.startswith("/"):
            self._send_html(render_page())
        else:
            self._send_html("Not found", 404)

    def do_POST(self):
        if self.path != "/set-position":
            self._send_html("Not found", 404)
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        form = urllib.parse.parse_qs(body)
        player_code = (form.get("player_code") or [""])[0]
        new_position = (form.get("new_position") or [""])[0]

        try:
            rec = set_manual_position(player_code, None if new_position == "__AUTO__" else new_position)
            msg = f"{rec['name']} → {rec['effective_position']} 반영 완료"
        except KeyError as exc:
            msg = str(exc)

        self._send_html(render_page(msg))


def main():
    server = HTTPServer((HOST, PORT), Handler)
    print(f"포지션 관리자 서버 실행 중: http://{HOST}:{PORT}  (종료: Ctrl+C)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
