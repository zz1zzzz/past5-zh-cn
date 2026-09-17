"""past5loc.http_api - HTTP/JSON 接口，便于 agent 直接用 curl / requests 调用。

启动：
    python -m past5loc.http_api --port 8765

端点（全部 POST，JSON body，返回 JSON）：
    GET  /health                        健康检查 + 能力清单
    POST /list_resources  {exe, only_forms}
    POST /extract_strings {exe, out_path, min_len}
    POST /check_dictionary{exe, dictionary}
    POST /build           {exe, dictionary, out_path, encoding, allow_list}
    POST /verify          {exe}

所有路径参数都是**服务器本机文件路径**（agent 与服务器在同一台机器时使用）。
"""
from __future__ import annotations

import argparse
import json
import os
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .pe import PEFile, RT
from . import catalog as cat
from . import builder as build_mod
from . import validate as V

ENDPOINTS = {
    '/health': 'GET/POST 健康检查',
    '/list_resources': 'POST {exe, only_forms?} 列出 PE 资源',
    '/extract_strings': 'POST {exe, out_path?, min_len?} 提取可翻译字符串',
    '/check_dictionary': 'POST {exe, dictionary} 检查词典覆盖率',
    '/build': 'POST {exe, dictionary, out_path, encoding?, allow_list?} 生成汉化版',
    '/verify': 'POST {exe} 审计可执行文件的汉化情况',
}


def _load(exe: str) -> PEFile:
    pe = PEFile.open(exe)
    pe.read_resources()
    return pe


def h_health(body):
    return {'ok': True, 'service': 'past5loc', 'endpoints': ENDPOINTS}


def h_list_resources(body):
    exe = body['exe']
    only_forms = body.get('only_forms', True)
    pe = _load(exe)
    rows = []
    for t, n, lang, leaf in pe.iter_resources():
        blob = leaf['__data__']
        is_form = cat.is_tpf0(blob)
        if only_forms and not is_form:
            continue
        rows.append({'type': RT.get(t, t), 'name': n, 'language': lang,
                     'size': len(blob), 'form': is_form})
    return {'ok': True, 'exe': exe, 'count': len(rows), 'resources': rows}


def h_extract_strings(body):
    exe = body['exe']
    pe = _load(exe)
    data = cat.extract(pe, min_len=int(body.get('min_len', 2)))
    out_path = body.get('out_path')
    if out_path:
        with open(out_path, 'w', encoding='utf-8') as fh:
            json.dump({'source': exe, **data}, fh, ensure_ascii=False, indent=1)
    return {'ok': True, 'exe': exe, 'unique': data['unique'],
            'occurrences': data['occurrences'], 'stats': data['stats'],
            'out_path': out_path,
            'strings': data['strings'] if body.get('include_strings') else None}


def h_check_dictionary(body):
    return {'ok': True, **build_mod.translation_delta(body['exe'], body['dictionary'])}


def h_build(body):
    table = json.load(open(body['dictionary'], encoding='utf-8'))
    allow = set()
    ap = body.get('allow_list')
    if ap and os.path.exists(ap):
        allow = set(json.load(open(ap, encoding='utf-8')))
    info = build_mod.build(body['exe'], table, body['out_path'],
                           encoding=body.get('encoding', 'gbk'),
                           allow_unvalidated=allow)
    return {'ok': True, **info}


def h_verify(body):
    exe = body['exe']
    pe = _load(exe)
    forms = cat.forms(pe)
    total = valid = cjk = 0
    for blob in forms.values():
        for t in V.scan(blob):
            total += 1
            valid += 1 if t['ok'] else 0
            cjk += 1 if any('\u4e00' <= c <= '\u9fff' for c in t['text']) else 0
    return {'ok': True, 'exe': exe, 'form_resources': len(forms),
            'string_tokens': total, 'structurally_valid': valid,
            'localized_tokens': cjk}


ROUTES = {
    '/health': h_health,
    '/list_resources': h_list_resources,
    '/extract_strings': h_extract_strings,
    '/check_dictionary': h_check_dictionary,
    '/build': h_build,
    '/verify': h_verify,
}


class Handler(BaseHTTPRequestHandler):
    server_version = 'past5loc/1.0'

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, payload):
        raw = json.dumps(payload, ensure_ascii=False, indent=1).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        fn = ROUTES.get(self.path.split('?')[0])
        if fn is None:
            self._send(404, {'ok': False, 'error': 'unknown path',
                             'endpoints': ENDPOINTS})
            return
        try:
            self._send(200, fn({}))
        except Exception as e:
            self._send(500, {'ok': False, 'error': str(e),
                             'trace': traceback.format_exc()})

    def do_POST(self):
        fn = ROUTES.get(self.path.split('?')[0])
        if fn is None:
            self._send(404, {'ok': False, 'error': 'unknown path',
                             'endpoints': ENDPOINTS})
            return
        try:
            length = int(self.headers.get('Content-Length') or 0)
            body = json.loads(self.rfile.read(length) or b'{}')
        except Exception as e:
            self._send(400, {'ok': False, 'error': f'bad json: {e}'})
            return
        try:
            self._send(200, fn(body))
        except Exception as e:
            self._send(500, {'ok': False, 'error': str(e),
                             'trace': traceback.format_exc()})


def main(argv=None):
    ap = argparse.ArgumentParser(prog='past5loc.http_api')
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=8765)
    args = ap.parse_args(argv)
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f'past5loc HTTP API on http://{args.host}:{args.port}')
    for k, v in ENDPOINTS.items():
        print(f'  {k:20} {v}')
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
