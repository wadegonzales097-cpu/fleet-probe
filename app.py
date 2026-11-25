#!/usr/bin/env python3
"""Probe: periodically checks reachability/latency of our own public
endpoints and serves a small status page. Pure Python 3 stdlib, no deps.
Listens on $PORT (default 8080), binds 0.0.0.0.
Start: python3 app.py
"""
import html
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TARGETS = [
    "https://beszel.bigking.eu.cc",
    "https://office.bigking.eu.cc",
    "https://japan.bigking.eu.cc",
    "https://box.bigking.eu.cc",
    "https://box2.bigking.eu.cc",
    "https://box3.bigking.eu.cc",
    "https://louislamuptime-kuma-production-055cd893.up.railway.app",
]
INTERVAL = 300  # seconds between probe rounds
TIMEOUT = 10  # seconds per HTTP GET
MAX_REDIRECTS = 3
BJ = timezone(timedelta(hours=8))  # Beijing time

_lock = threading.Lock()
_results = {}  # url -> (status, ms, datetime in UTC)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def probe(url):
    """One HTTP GET (following at most MAX_REDIRECTS redirects manually).
    Returns (status_code_or_error, elapsed_ms)."""
    start = time.monotonic()
    current = url
    status = "ERR"
    for attempt in range(MAX_REDIRECTS + 1):
        req = urllib.request.Request(
            current, headers={"User-Agent": "abasthan-probe/1.0"}
        )
        try:
            with _opener.open(req, timeout=TIMEOUT) as resp:
                resp.read(2048)
                status = resp.getcode()
            break
        except urllib.error.HTTPError as e:
            loc = e.headers.get("Location") if e.headers else None
            if e.code in (301, 302, 303, 307, 308) and loc and attempt < MAX_REDIRECTS:
                current = urllib.parse.urljoin(current, loc)
                continue
            status = e.code
            break
        except Exception as e:  # DNS failure, timeout, TLS error, ...
            status = "ERR " + type(e).__name__
            break
    ms = int((time.monotonic() - start) * 1000)
    return status, ms


def probe_loop():
    while True:
        for url in TARGETS:
            status, ms = probe(url)
            with _lock:
                _results[url] = (status, ms, datetime.now(timezone.utc))
        time.sleep(INTERVAL)


def render_page():
    with _lock:
        snapshot = dict(_results)
    rows = []
    for url in TARGETS:
        if url in snapshot:
            status, ms, when = snapshot[url]
            utc_s = when.strftime("%Y-%m-%d %H:%M:%S")
            bj_s = when.astimezone(BJ).strftime("%Y-%m-%d %H:%M:%S")
            rows.append(
                "<tr><td>{}</td><td>{}</td><td>{} ms</td>"
                "<td>{} UTC / {} 北京</td></tr>".format(
                    html.escape(url), html.escape(str(status)), ms, utc_s, bj_s
                )
            )
        else:
            rows.append(
                "<tr><td>{}</td><td>-</td><td>-</td><td>首轮探测中</td></tr>".format(
                    html.escape(url)
                )
            )
    page = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<meta http-equiv='refresh' content='60'>"
        "<title>Endpoint Probe</title></head><body>"
        "<h1>自家节点入口探针</h1>"
        "<table border='1' cellspacing='0' cellpadding='6'>"
        "<tr><th>目标</th><th>状态码</th><th>延迟</th><th>最后探测时间</th></tr>"
        + "".join(rows)
        + "</table><p>每 5 分钟一轮，页面每 60 秒自刷新。</p></body></html>"
    )
    return page.encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            data, ctype = b"ok", "text/plain; charset=utf-8"
        elif self.path == "/":
            data, ctype = render_page(), "text/html; charset=utf-8"
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        pass


def main():
    port = int(os.environ.get("PORT", "8080"))
    threading.Thread(target=probe_loop, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
