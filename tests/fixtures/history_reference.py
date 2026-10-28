"""Independent test-only server; never copied to an SDLC candidate."""
import argparse
from contextlib import closing
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import sqlite3


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status, value):
        raw = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def error(self, status):
        self.send_json(status, {'error': 'invalid request'})

    def do_GET(self):
        if self.path == '/health':
            return self.send_json(200, {'status': 'ok'})
        if self.path in ('/analyze', '/analyses'):
            return self.error(405)
        suffix = self.path.removeprefix('/analyses/')
        if not self.path.startswith('/analyses/') or not suffix.isascii() or not suffix.isdecimal() or not 0 < int(suffix) <= 2**63-1:
            return self.error(404)
        with closing(sqlite3.connect(self.server.database)) as db:
            row = db.execute('SELECT text, result FROM analyses WHERE id = ?', (int(suffix),)).fetchone()
        if row is None:
            return self.error(404)
        return self.send_json(200, {'id': int(suffix), 'text': row[0], 'analysis': json.loads(row[1])})

    def do_POST(self):
        if self.path.startswith('/analyses/'):
            return self.error(405)
        if self.path not in ('/analyses', '/analyze'):
            return self.error(404)
        try:
            data = json.loads(self.rfile.read(int(self.headers.get('Content-Length', '0'))).decode())
            if not isinstance(data, dict) or not isinstance(data.get('text'), str):
                raise ValueError()
            text = data['text']
            for flag in ('include_word_frequencies', 'include_utf8_bytes'):
                if not isinstance(data.get(flag, False), bool):
                    raise ValueError()
            if self.path == '/analyses':
                text.encode('utf-8')
            result = {'characters': len(text), 'words': len(text.split()), 'lines': len(text.splitlines())}
            if data.get('include_word_frequencies'):
                result['word_frequencies'] = {token: text.split().count(token) for token in text.split()}
            if data.get('include_utf8_bytes'):
                result['utf8_bytes'] = len(text.encode('utf-8'))
        except (ValueError, UnicodeError):
            return self.error(400)
        if self.path == '/analyze':
            return self.send_json(200, result)
        with closing(sqlite3.connect(self.server.database)) as db:
            cursor = db.execute('INSERT INTO analyses(text, result) VALUES (?, ?)', (text, json.dumps(result)))
            identifier = cursor.lastrowid
            db.commit()
        self.send_json(201, {'id': identifier, 'text': text, 'analysis': result})

    def unsupported(self):
        self.error(405 if self.path in ('/analyze', '/analyses') or self.path.startswith('/analyses/') else 404)

    do_PUT = do_PATCH = do_DELETE = do_OPTIONS = unsupported

    def log_message(self, *args):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--database', default='httpstats.sqlite3')
    args = parser.parse_args()
    with closing(sqlite3.connect(args.database)) as db:
        db.execute('CREATE TABLE IF NOT EXISTS analyses (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL, result TEXT NOT NULL)')
        db.commit()
    server = HTTPServer(('127.0.0.1', args.port), Handler)
    server.database = args.database
    print(f'PORT={server.server_port}', flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
