"""Catches a big JSON blob POSTed from the app's own page and writes it to a file.

The parcel cache lives in the browser's IndexedDB and is far too big to copy out
through a console return value, so the export goes over HTTP to this instead.
Only ever bound to localhost.

    python3 receive.py              # writes work/store-raw.json, then exits
    python3 receive.py out.json     # ...somewhere else
"""
import http.server, os, socketserver, sys, threading

DEST = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), 'work', 'store-raw.json')
PORT = 8765
done = threading.Event()

class H(http.server.BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', 'content-type')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')

    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()

    def do_POST(self):
        n = int(self.headers.get('content-length') or 0)
        os.makedirs(os.path.dirname(DEST), exist_ok=True)
        got = 0
        with open(DEST, 'wb') as f:
            while got < n:
                chunk = self.rfile.read(min(1 << 20, n - got))
                if not chunk: break
                f.write(chunk); got += len(chunk)
                print(f'\r  {got/1048576:.1f} / {n/1048576:.1f} MB', end='', flush=True)
        print(f'\nwrote {DEST} ({got} bytes)')
        self.send_response(200); self._cors()
        self.send_header('content-type', 'text/plain'); self.end_headers()
        self.wfile.write(b'ok')
        done.set()

    def log_message(self, *a): pass

class Server(socketserver.TCPServer):
    allow_reuse_address = True   # otherwise a re-run within TIME_WAIT can't rebind

with Server(('127.0.0.1', PORT), H) as srv:
    srv.timeout = 1
    print(f'listening on http://127.0.0.1:{PORT}/  -> {DEST}')
    print('in the app\'s console:  await lbParcelsExport()')
    while not done.is_set():
        srv.handle_request()
