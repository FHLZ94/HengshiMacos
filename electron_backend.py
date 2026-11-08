"""Loopback bridge for the sandboxed Electron renderer."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import secrets
import sys

from desktop import DesktopAPI

METHOD_ARGS = {
    'get_state': 0, 'refresh': 0, 'search_global_news': 1,
    'save_watchlist': 1, 'add_tracking': 1, 'remove_tracking': 1, 'save_position': 3, 'delete_position': 1,
    'set_holding_status': 2, 'save_neutral_pe': 2, 'save_guidance': 4,
    'save_public_posts': 1, 'save_network': 2, 'set_local_model': 1, 'open_url': 1,
    'analyze_event': 1, 'translate_event': 1,
    'event_market_context': 1, 'get_event_intelligence': 1,
}


def serve(api=None, token=None):
    api = api or DesktopAPI()
    token = token or os.environ.get('HENGSHI_IPC_TOKEN') or secrets.token_hex(32)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != '/invoke' or self.headers.get('X-Hengshi-Token') != token:
                self.send_error(403)
                return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 128_000:
                    raise ValueError('请求大小无效')
                payload = json.loads(self.rfile.read(size))
                method = payload.get('method')
                args = payload.get('args')
                if method not in METHOD_ARGS or not isinstance(args, list) or len(args) != METHOD_ARGS[method]:
                    raise ValueError('操作参数无效')
                result = getattr(api, method)(*args)
                encoded = json.dumps({'ok': True, 'value': result}, ensure_ascii=False).encode('utf-8')
                code = 200
            except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                encoded = json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False).encode('utf-8')
                code = 400
            except Exception:
                encoded = b'{"ok":false,"error":"operation failed"}'
                code = 500
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(encoded)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    print(json.dumps({'port': server.server_port}), flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()


if __name__ == '__main__':
    serve()
