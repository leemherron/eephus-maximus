#!/usr/bin/env python3
"""
Local server for the clip timing editor.
Serves static files + handles POST /api/save-pause and /api/save-fields to write back to data.json.

Usage:  python scripts/editor_server.py
        then open  http://localhost:8080/anticipation/editor.html
"""
import json
import os
from http.server import HTTPServer, SimpleHTTPRequestHandler

HERE   = os.path.dirname(os.path.abspath(__file__))
ROOT   = os.path.normpath(os.path.join(HERE, '..'))
DATA   = os.path.join(ROOT, 'anticipation', 'data.json')
PORT   = 8080
EDITABLE = {'pause_time', 'contact_time', 'exclude', 'exclude_reason'}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def do_POST(self):
        if self.path == '/api/save-pause':
            n = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(n))

            with open(DATA) as f:
                plays = json.load(f)

            idx = int(body['index'])
            plays[idx]['pause_time'] = round(float(body['pause_time']), 3)

            with open(DATA, 'w') as f:
                json.dump(plays, f, indent=2, ensure_ascii=False)

            self._json(200, {'ok': True, 'index': idx,
                             'pause_time': plays[idx]['pause_time']})
        elif self.path == '/api/save-fields':
            # body: {"updates": [{"index": i, "fields": {...}}, ...]}
            n = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(n))
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
            self._json(200, {'ok': True, 'count': len(body['updates'])})
        else:
            self.send_error(404)

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
    server = HTTPServer(('', PORT), Handler)
    print(f"Editor →  http://localhost:{PORT}/anticipation/editor.html")
    print("Ctrl-C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
