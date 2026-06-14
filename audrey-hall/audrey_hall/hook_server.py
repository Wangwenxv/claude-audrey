import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .hook_state import ClaudeHookState, DEFAULT_PORT, decode_json_body


class ClaudeHookServer:
    def __init__(self, state: ClaudeHookState, host: str = '127.0.0.1', port: int = DEFAULT_PORT):
        self.state = state
        self.host = host
        self.port = port
        self._thread: threading.Thread | None = None
        self._server: ThreadingHTTPServer | None = None

    def start(self):
        if self._thread is not None:
            return

        state = self.state

        class Handler(BaseHTTPRequestHandler):
            def _write_json(self, payload: dict, status: int = HTTPStatus.OK):
                body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == '/api/current':
                    self._write_json(state.get_state())
                    return
                if self.path == '/api/heartbeat':
                    self._write_json({'ok': True})
                    return
                self._write_json({'ok': False, 'error': 'not_found'}, HTTPStatus.NOT_FOUND)

            def do_POST(self):
                content_length = int(self.headers.get('Content-Length') or 0)
                payload = decode_json_body(self.rfile.read(content_length))
                route = self.path.rstrip('/')
                if route == '/api/hook/thinking':
                    result = state.handle_hook('thinking', payload)
                    self._write_json({'ok': True, 'state': result})
                    return
                if route == '/api/hook/working':
                    result = state.handle_hook('working', payload)
                    self._write_json({'ok': True, 'state': result})
                    return
                if route == '/api/hook/done':
                    result = state.handle_hook('done', payload)
                    self._write_json({'ok': True, 'state': result})
                    return
                if route == '/api/hook/permission':
                    result = state.handle_hook('permission', payload)
                    self._write_json({'ok': True, 'state': result})
                    return
                if route == '/api/hook/idle':
                    result = state.handle_hook('idle', payload)
                    self._write_json({'ok': True, 'state': result})
                    return
                if route == '/api/state':
                    result = state.handle_hook('state', payload)
                    self._write_json({'ok': True, 'state': result})
                    return
                self._write_json({'ok': False, 'error': 'not_found'}, HTTPStatus.NOT_FOUND)

            def log_message(self, format, *args):
                return

        self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        if self._server is None:
            return
        try:
            self._server.shutdown()
            self._server.server_close()
        finally:
            self._server = None
            self._thread = None
