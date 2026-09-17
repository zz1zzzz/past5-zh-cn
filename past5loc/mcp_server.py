"""past5loc.mcp_server - MCP interface for the PAST5 localization toolkit.

Exposes the pipeline as MCP tools so an agent (Claude Desktop, Cursor, DSH, ...)
can drive the localization directly:

    past5_list_resources   enumerate a build's PE resources
    past5_extract_strings  build a translation catalogue
    past5_check_dictionary report how much of a dictionary applies
    past5_build            produce a localized executable
    past5_verify           audit a localized executable
    past5_run_command      escape hatch: run any CLI subcommand

Run as a stdio server:

    python -m past5loc.mcp_server

Client configuration (JSON):

    {"mcpServers": {"past5loc": {"command": "python",
                                 "args": ["-m", "past5loc.mcp_server"],
                                 "cwd": "<dir containing the past5loc package>"}}}
"""
from __future__ import annotations

import json
import os
from typing import Optional

from mcp.server.fastmcp import FastMCP

from .pe import PEFile, RT
from . import catalog as cat
from . import builder as build_mod

mcp = FastMCP('past5loc')


def _load(path: str) -> PEFile:
    pe = PEFile.open(path)
    pe.read_resources()
    return pe


@mcp.tool()
def past5_list_resources(exe: str, only_forms: bool = True) -> dict:
    """List the PE resources of a build.

    Args:
        exe: path to the executable.
        only_forms: keep only the embedded FMX form resources.
    """
    pe = _load(exe)
    rows = []
    for t, n, lang, leaf in pe.iter_resources():
        blob = leaf['__data__']
        is_form = cat.is_tpf0(blob)
        if only_forms and not is_form:
            continue
        rows.append({'type': RT.get(t, t), 'name': n, 'language': lang,
                     'size': len(blob), 'form': is_form})
    return {'exe': exe, 'count': len(rows), 'resources': rows}


@mcp.tool()
def past5_extract_strings(exe: str, out_path: Optional[str] = None,
                          min_len: int = 2) -> dict:
    """Extract the translatable UI strings of a build.

    Every candidate is validated against the form stream structure, so the
    result contains no bytes that merely look like strings inside binary data.

    Args:
        exe: path to the executable.
        out_path: optional path to write the catalogue JSON to.
        min_len: minimum string length to keep.
    """
    pe = _load(exe)
    data = cat.extract(pe, min_len=min_len)
    if out_path:
        with open(out_path, 'w', encoding='utf-8') as fh:
            json.dump({'source': exe, **data}, fh, ensure_ascii=False, indent=1)
    top = list(data['strings'].items())[:20]
    return {'exe': exe, 'unique': data['unique'],
            'occurrences': data['occurrences'], 'stats': data['stats'],
            'out_path': out_path,
            'preview': [{'en': k, 'count': v['count']} for k, v in top]}


@mcp.tool()
def past5_check_dictionary(exe: str, dictionary: str) -> dict:
    """Report how much of a translation dictionary actually applies to a build.

    Args:
        exe: path to the executable.
        dictionary: path to a JSON file mapping English -> Chinese.
    """
    return build_mod.translation_delta(exe, dictionary)


@mcp.tool()
def past5_build(exe: str, dictionary: str, out_path: str,
                encoding: str = 'gbk', allow_list: Optional[str] = None) -> dict:
    """Build a localized executable.

    Args:
        exe: path to the original executable (never modified).
        dictionary: JSON file mapping English -> Chinese.
        out_path: where to write the localized executable.
        encoding: payload encoding - 'gbk' for a zh-CN Windows host, 'utf-8' if
            the application decodes form strings as UTF-8.
        allow_list: optional JSON array of strings that may be rewritten even
            when the structural check rejects them.
    """
    table = json.load(open(dictionary, encoding='utf-8'))
    allow = set()
    if allow_list and os.path.exists(allow_list):
        allow = set(json.load(open(allow_list, encoding='utf-8')))
    return build_mod.build(exe, table, out_path, encoding=encoding,
                           allow_unvalidated=allow)


@mcp.tool()
def past5_verify(exe: str) -> dict:
    """Audit an executable: form resources, string tokens, translated tokens.

    Args:
        exe: path to the executable to inspect.
    """
    from . import validate as V
    pe = _load(exe)
    forms = cat.forms(pe)
    total = valid = cjk = 0
    for blob in forms.values():
        for t in V.scan(blob):
            total += 1
            valid += 1 if t['ok'] else 0
            cjk += 1 if any('\u4e00' <= c <= '\u9fff' for c in t['text']) else 0
    return {'exe': exe, 'form_resources': len(forms), 'string_tokens': total,
            'structurally_valid': valid, 'localized_tokens': cjk}


@mcp.tool()
def past5_run_command(args: list[str]) -> dict:
    """Run a raw past5loc CLI subcommand and return its output.

    Args:
        args: argv after the program name, e.g. ["verify", "Past5_zh-CN.exe"].
    """
    import io
    import contextlib
    from .cli import main
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = main([str(a) for a in args])
    return {'exit_code': code, 'output': buf.getvalue()}


def main():
    mcp.run()


if __name__ == '__main__':
    main()
