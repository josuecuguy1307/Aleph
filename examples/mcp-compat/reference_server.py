"""Tiny deterministic MCP reference fixture; no filesystem/network tools."""
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def response(message):
    rid = message.get('id')
    if rid is None:
        return None
    method = message.get('method')
    if method == 'initialize':
        result = {'protocolVersion': message['params']['protocolVersion'],
                  'capabilities': {'tools': {}},
                  'serverInfo': {'name': 'aleph-reference', 'version': '1.0.0'}}
    elif method == 'tools/list':
        result = {'tools': [{'name': 'echo', 'description': 'Echo public synthetic text',
                            'inputSchema': {'type': 'object', 'properties': {'text': {'type': 'string'}},
                                            'required': ['text']}}]}
    elif method == 'tools/call':
        params = message['params']
        if params['name'] == 'slow':
            time.sleep(2)
        denied = params['name'] not in ('echo', 'slow')
        result = {'content': [{'type': 'text', 'text': 'denied' if denied else params['arguments'].get('text', '')}],
                  'isError': denied}
    else:
        return {'jsonrpc': '2.0', 'id': rid, 'error': {'code': -32601, 'message': 'Method not found'}}
    return {'jsonrpc': '2.0', 'id': rid, 'result': result}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_POST(self):
        message = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        result = response(message)
        body = json.dumps(result).encode() if result is not None else b''
        self.send_response(200 if result is not None else 202)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        self.send_error(405)  # This stateless fixture does not offer a standalone SSE stream.

    def do_DELETE(self):
        self.send_response(200)
        self.send_header('Content-Length', '0')
        self.end_headers()


if __name__ == '__main__':
    for line in sys.stdin:
        result = response(json.loads(line))
        if result is not None:
            print(json.dumps(result), flush=True)
