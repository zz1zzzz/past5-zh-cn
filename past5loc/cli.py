"""past5loc.cli - command line interface.

    python -m past5loc list    Past5.exe
    python -m past5loc extract Past5.exe -o catalog.json
    python -m past5loc check   Past5.exe translations_zh.json
    python -m past5loc build   Past5.exe translations_zh.json -o Past5_zh-CN.exe
    python -m past5loc verify  Past5_zh-CN.exe
    python -m past5loc run     Past5.exe -- python -m past5loc build ...

JSON goes to stdout for the machine-readable commands so an agent can pipe it.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from .pe import PEFile, RT
from . import catalog as cat
from . import builder as build_mod


def cmd_list(args):
    pe = PEFile.open(args.exe)
    pe.read_resources()
    rows = []
    for t, n, lang, leaf in pe.iter_resources():
        rows.append({'type': RT.get(t, t), 'name': n, 'lang': lang,
                     'size': len(leaf['__data__']),
                     'kind': ('form' if cat.is_tpf0(leaf['__data__']) else 'data')})
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0
    forms = [r for r in rows if r['kind'] == 'form']
    print(f'{args.exe}: {len(rows)} resources, {len(forms)} embedded forms')
    for r in rows[:args.limit]:
        print(f"  {r['type']:<12} {r['name']:<34} lang={r['lang']:<6} "
              f"size={r['size']:<10} {r['kind']}")
    return 0


def cmd_extract(args):
    pe = PEFile.open(args.exe)
    pe.read_resources()
    data = cat.extract(pe)
    out = {'source': args.exe, **data}
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as fh:
            json.dump(out, fh, ensure_ascii=False, indent=1)
        print(f'{data["unique"]} unique strings '
              f'({data["occurrences"]} occurrences) -> {args.out}')
    else:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


def cmd_check(args):
    info = build_mod.translation_delta(args.exe, args.table)
    print(json.dumps(info, ensure_ascii=False, indent=1))
    return 0


def cmd_build(args):
    table = json.load(open(args.table, encoding='utf-8'))
    allow = set()
    if args.allow and os.path.exists(args.allow):
        allow = set(json.load(open(args.allow, encoding='utf-8')))
    info = build_mod.build(args.exe, table, args.out, encoding=args.encoding,
                           allow_unvalidated=allow, pad=args.pad)
    print(json.dumps(info, ensure_ascii=False, indent=1))
    return 0


def cmd_verify(args):
    pe = PEFile.open(args.exe)
    pe.read_resources()
    forms_found = cat.forms(pe)
    total = valid = cjk = 0
    for blob in forms_found.values():
        toks = list(V_scan(blob))
        total += len(toks)
        valid += sum(1 for t in toks if t['ok'])
        cjk += sum(1 for t in toks if any('\u4e00' <= c <= '\u9fff' for c in t['text']))
    report = {
        'exe': args.exe,
        'form_resources': len(forms_found),
        'string_tokens': total,
        'structurally_valid': valid,
        'localized_tokens': cjk,
        'pe_ok': True,
    }
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


def cmd_serve(args):
    from .http_api import main as api_main
    api_main(['--host', args.host, '--port', str(args.port)])
    return 0


def cmd_mcp(args):
    from .mcp_server import main as mcp_main
    mcp_main()
    return 0


def V_scan(blob):
    from . import validate as V
    return V.scan(blob)


def main(argv=None):
    ap = argparse.ArgumentParser(prog='past5loc',
                                 description='PAST5 Chinese localization toolkit')
    sub = ap.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser('list', help='list PE resources')
    p.add_argument('exe')
    p.add_argument('--json', action='store_true')
    p.add_argument('--limit', type=int, default=40)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser('extract', help='extract translatable strings')
    p.add_argument('exe')
    p.add_argument('-o', '--out')
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser('check', help='check a dictionary against an executable')
    p.add_argument('exe')
    p.add_argument('table')
    p.set_defaults(func=cmd_check)

    p = sub.add_parser('build', help='build a localized executable')
    p.add_argument('exe')
    p.add_argument('table')
    p.add_argument('-o', '--out', required=True)
    p.add_argument('--encoding', default='gbk',
                   help='payload encoding (gbk for zh-CN Windows, utf-8 otherwise)')
    p.add_argument('--allow', help='JSON list of strings safe to rewrite even '
                                   'when the structural check rejects them')
    p.add_argument('--pad', action='store_true',
                   help='equal-length build: pad translations to the original '
                        'byte length so no offset in the stream moves')
    p.set_defaults(func=cmd_build)

    p = sub.add_parser('verify', help='verify a localized executable')
    p.add_argument('exe')
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser('serve', help='start the HTTP/JSON API')
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--port', type=int, default=8765)
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser('mcp', help='run as an MCP stdio server')
    p.set_defaults(func=cmd_mcp)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
