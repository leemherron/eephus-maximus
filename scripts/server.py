#!/usr/bin/env python3
"""
Local server for Read the Swing: serves the site, collects trial results, and
backs the clip review editor.

  GET  /api/trials        all logged trials (data/trials.jsonl) as a JSON list
  POST /api/trials        {"trials": [...]} — append trials from the game
  POST /api/save-fields   {"updates": [{"index": i, "fields": {...}}]} — editor writes to data.json

Static files support HTTP Range requests so video seeking works like on a real host.

Usage:  python scripts/server.py
        game     http://localhost:8080/anticipation/
        results  http://localhost:8080/anticipation/results.html
        review   http://localhost:8080/anticipation/editor.html
"""
import json
import os
import re
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..'))
DATA = os.path.join(ROOT, 'anticipation', 'data.json')
TRIALS = os.path.join(ROOT, 'data', 'trials.jsonl')
PORT = 8080
EDITABLE = {'contact_time', 'contact_raw', 'contact_verified', 'contact_frame_checked', 'exclude', 'exclude_reason'}
TRIAL_FIELDS = {'player_id', 'session_id', 'trial', 'play_id', 'lead', 'lead_s', 'guess', 'direction',
                'correct', 'rt_ms', 'frozen_at', 'contact_time', 'repeat', 'experience', 'ts'}

lock = threading.Lock()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    # ── API ────────────────────────────────────────────────────────────────
    def do_GET(self):
        if self.path == '/api/trials':
            rows = []
            if os.path.exists(TRIALS):
                with open(TRIALS) as f:
                    rows = [json.loads(line) for line in f if line.strip()]
            return self._json(200, rows)
        return self._serve_with_range()

    def do_POST(self):
        body = self._body()
        if body is None:
            return self._json(400, {'error': 'bad json'})

        if self.path == '/api/trials':
            rows = [{k: t.get(k) for k in TRIAL_FIELDS} for t in body.get('trials', [])]
            with lock:
                os.makedirs(os.path.dirname(TRIALS), exist_ok=True)
                seen = set()
                if os.path.exists(TRIALS):    # ignore re-sent trials from the client's retry queue
                    with open(TRIALS) as f:
                        seen = {(r['session_id'], r['trial']) for r in map(json.loads, filter(str.strip, f))}
                with open(TRIALS, 'a') as f:
                    for r in rows:
                        if (r['session_id'], r['trial']) not in seen:
                            f.write(json.dumps(r) + '\n')
            return self._json(200, {'ok': True, 'count': len(rows)})

        if self.path == '/api/save-fields':
            with lock:
                with open(DATA) as f:
                    plays = json.load(f)
                for u in body['updates']:
                    for k, v in u['fields'].items():
                        if k not in EDITABLE:
                            continue
                        if v is None:
                            plays[int(u['index'])].pop(k, None)
                        else:
                            plays[int(u['index'])][k] = v
                with open(DATA, 'w') as f:
                    json.dump(plays, f, indent=2, ensure_ascii=False)
            return self._json(200, {'ok': True, 'count': len(body['updates'])})

        self.send_error(404)

    # ── static files with Range support ────────────────────────────────────
    def _serve_with_range(self):
        rng = self.headers.get('Range')
        path = self.translate_path(self.path)
        if not rng or not os.path.isfile(path):
            return super().do_GET()
        m = re.match(r'bytes=(\d*)-(\d*)', rng)
        size = os.path.getsize(path)
        if not m:
            return super().do_GET()
        start = int(m.group(1)) if m.group(1) else max(0, size - int(m.group(2)))
        end = int(m.group(2)) if m.group(1) and m.group(2) else size - 1
        end = min(end, size - 1)
        if start > end:
            self.send_response(416)
            self.send_header('Content-Range', f'bytes */{size}')
            self.end_headers()
            return
        self.send_response(206)
        self.send_header('Content-Type', self.guess_type(path))
        self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.send_header('Content-Length', str(end - start + 1))
        self.send_header('Accept-Ranges', 'bytes')
        self.end_headers()
        with open(path, 'rb') as f:
            f.seek(start)
            remaining = end - start + 1
            try:
                while remaining:
                    chunk = f.read(min(65536, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass   # browser cancelled the request (normal while seeking)

    def end_headers(self):
        if not self.headers.get('Range'):
            self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Cache-Control', 'no-cache')
        super().end_headers()

    # ── helpers ────────────────────────────────────────────────────────────
    def _body(self):
        try:
            n = int(self.headers.get('Content-Length', 0))
            return json.loads(self.rfile.read(n))
        except (ValueError, json.JSONDecodeError):
            return None

    def _json(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass  # quiet


if __name__ == '__main__':
    server = ThreadingHTTPServer(('', PORT), Handler)
    print(f"Game     →  http://localhost:{PORT}/anticipation/")
    print(f"Results  →  http://localhost:{PORT}/anticipation/results.html")
    print(f"Review   →  http://localhost:{PORT}/anticipation/editor.html")
    print("Ctrl-C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
