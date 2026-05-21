#!/usr/bin/env python3
"""
Local preview for e-paper tag renders. Edit renderer.py, then refresh to see changes.

Usage:
    python preview.py               # render once, open result in browser
    python preview.py --serve       # live server; refresh browser after each edit
    python preview.py --size 296x128  # override tag dimensions
"""

from __future__ import annotations

import argparse
import base64
import http.server
import importlib
import os
import sys
import webbrowser
from io import BytesIO
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(".env")
load_dotenv(".env.example")

# Tuples: (issue_num, title, status, assignee, sub_issues)
_SAMPLES = [
    (42, "Implement NFC scanning loop and background status service", "Needs Triage", "kyle",  ()),
    (17, "Design e-paper card layout for sprint view",                "In Progress",  "alice", (18, 19, 20)),
    (8,  "Set up Raspberry Pi service with systemd unit file",        "Done",         "bob",   ()),
    (55, "Wire up GitHub Projects v2 GraphQL mutation for status",    "In Review",    "kyle",  (56, 57)),
    (3,  "Add NFC tag registration workflow to CLI",                  "Blocked",      "kyle",  ()),
    (12, "Migrate auth service to new token format",                  "Aborted",      "alice", (13, 14, 15, 16)),
    (7,  "Investigate display flicker on cold boot",                  "Ready",        "",      ()),
]


def _img_to_b64(img) -> str:
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _load_db_cards(db_path: str, default_w: int, default_h: int, repo_name: str = "") -> list[dict]:
    if not Path(db_path).exists():
        return []
    try:
        from store import Store
        store = Store(db_path)
        cards = []
        for tag, assignment in store.get_all_assignments():
            cards.append({
                "label": tag.alias or tag.mac[-8:],
                "width":  tag.width  or default_w,
                "height": tag.height or default_h,
                "issue_number": assignment.issue_number,
                "title":        assignment.issue_title,
                "status":       assignment.status,
                "assignee":     assignment.assignee,
                "repo_name":    repo_name,
                "source": "db",
            })
        return cards
    except Exception as exc:
        print(f"[preview] DB read failed: {exc}", file=sys.stderr)
        return []


def _build_card_list(
    db_path: str, size_override: tuple[int, int] | None, repo_name: str = ""
) -> list[dict]:
    default_w, default_h = size_override or (296, 128)
    cards = _load_db_cards(db_path, default_w, default_h, repo_name)
    for issue_num, title, status, assignee, sub_issues in _SAMPLES:
        w = size_override[0] if size_override else default_w
        h = size_override[1] if size_override else default_h
        cards.append({
            "label": f"sample-{issue_num}",
            "width": w, "height": h,
            "issue_number": issue_num,
            "title": title, "status": status, "assignee": assignee,
            "repo_name": repo_name,
            "sub_issues": sub_issues,
            "source": "sample",
        })
    return cards


def render_html(db_path: str, size_override: tuple[int, int] | None, repo_name: str = "") -> str:
    """Render all cards to an HTML string. Re-imports renderer each call."""
    import renderer as _r
    importlib.reload(_r)

    cards = _build_card_list(db_path, size_override, repo_name)
    max_w = max(c["width"] * 2 for c in cards)

    card_blocks = []
    for c in cards:
        img = _r.render_card(
            width=c["width"], height=c["height"],
            issue_number=c["issue_number"], title=c["title"],
            status=c["status"], assignee=c["assignee"],
            repo_name=c.get("repo_name", ""),
            sub_issues=c.get("sub_issues", ()),
        )
        b64 = _img_to_b64(img)
        badge = (
            '<span class="badge db">DB</span>'
            if c["source"] == "db"
            else '<span class="badge sample">SAMPLE</span>'
        )
        card_blocks.append(f"""
  <div class="card">
    <div class="meta">{badge} {c['label']}  {c['width']}×{c['height']}</div>
    <img src="data:image/png;base64,{b64}"
         width="{c['width'] * 2}" height="{c['height'] * 2}"
         style="image-rendering:pixelated">
    <div class="info">#{c['issue_number']} · {c['status']} · {c['title'][:60]}</div>
  </div>""")

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Tag Preview</title>
<style>
  body  {{ background:#1e1e1e; color:#ccc; font-family:monospace; padding:20px; margin:0; }}
  h1   {{ color:#fff; margin:0 0 4px; }}
  .sub  {{ color:#666; margin-bottom:20px; font-size:12px; }}
  .grid {{ display:flex; flex-wrap:wrap; gap:16px; }}
  .card {{ background:#2a2a2a; border-radius:6px; padding:10px; }}
  .meta {{ font-size:11px; color:#888; margin-bottom:6px; }}
  .info {{ font-size:11px; color:#666; margin-top:6px; max-width:{max_w}px;
           white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
  img  {{ display:block; border:1px solid #444; }}
  .badge {{ padding:1px 5px; border-radius:3px; font-size:10px; font-weight:bold; }}
  .badge.db     {{ background:#1a7a4a; color:#fff; }}
  .badge.sample {{ background:#555;    color:#bbb; }}
</style>
</head>
<body>
<h1>Tag Preview</h1>
<p class="sub">Edit renderer.py and refresh — no push to hardware needed.</p>
<div class="grid">
{''.join(card_blocks)}
</div>
</body>
</html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Local e-paper tag preview")
    parser.add_argument(
        "--serve", action="store_true",
        help="Start a live-reload HTTP server (refresh browser after each edit)",
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--size", default="",
        help="Override tag dimensions, e.g. 296x128",
    )
    parser.add_argument(
        "--repo", default="tactile-kanban",
        help="Repo name shown in card header (default: tactile-kanban)",
    )
    parser.add_argument(
        "--db", default=os.environ.get("DB_PATH", "kanban.db"),
        help="SQLite DB path (default: kanban.db)",
    )
    args = parser.parse_args()

    size_override: tuple[int, int] | None = None
    if args.size:
        w_str, h_str = args.size.lower().split("x")
        size_override = (int(w_str), int(h_str))

    if args.serve:
        db_path = args.db
        so = size_override
        repo = args.repo

        class _Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                html = render_html(db_path, so, repo).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html)))
                self.end_headers()
                self.wfile.write(html)

            def log_message(self, fmt, *args):  # suppress per-request noise
                pass

        url = f"http://localhost:{args.port}"
        print(f"Preview server at {url}")
        print("Edit renderer.py and refresh your browser to see changes.")
        webbrowser.open(url)
        http.server.HTTPServer(("", args.port), _Handler).serve_forever()
    else:
        html = render_html(args.db, size_override, args.repo)
        out = Path("preview.html")
        out.write_text(html)
        print(f"Saved {out}")
        webbrowser.open(str(out.resolve()))


if __name__ == "__main__":
    main()
