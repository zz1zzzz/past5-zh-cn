"""past5loc.builder - produce a localized executable.

Rewriting rule
--------------
A dictionary entry is written into the form stream only when the token is
certified by the two-sided structural check, or when it is explicitly listed in
``allow_unvalidated`` (used for the handful of genuine labels that live inside
TListBox ``Items.Strings`` arrays and for file-dialog filter strings).

Replacement is in-place and self-delimiting: only the length byte and payload of
the 0x06 token change, so the enclosing component stream stays valid.
"""
from __future__ import annotations

import collections
import json
import os
from typing import Dict, Iterable, Optional, Set, Tuple

from .pe import PEFile
from . import validate as V
from .catalog import forms


def patch_form(blob: bytes, table: Dict[str, str], encoding: str = 'gbk',
               allow_unvalidated: Optional[Set[str]] = None,
               stats: Optional[collections.Counter] = None,
               vocab: Optional[Set[str]] = None,
               pad: bool = False) -> bytes:
    """Return ``blob`` with dictionary hits rewritten.

    ``pad`` keeps every payload at its original byte length (padded with spaces
    when the translation is shorter), so the buffer is not resized at all.  That
    removes any possibility of a length change desynchronising the runtime
    reader, at the cost of trailing spaces in short labels.
    """
    stats = stats if stats is not None else collections.Counter()
    allow = allow_unvalidated or set()
    out = bytearray()
    prev = 0
    for tok in V.scan(blob, vocab):
        repl = table.get(tok['text'])
        if repl is None or repl == tok['text']:
            continue
        if not tok['ok'] and tok['text'] not in allow:
            stats['blocked_unvalidated'] += 1
            continue
        try:
            enc = repl.encode(encoding, errors='strict')
        except UnicodeEncodeError:
            stats['unencodable'] += 1
            continue
        if pad:
            if len(enc) > tok['byte_len']:
                stats['too_long_to_pad'] += 1
                continue
            enc = enc + b' ' * (tok['byte_len'] - len(enc))
        elif len(enc) > 255:
            stats['too_long'] += 1
            continue
        out += blob[prev:tok['len_off']]
        out.append(len(enc))
        out += enc
        prev = tok['data_off'] + tok['byte_len']
        stats['patched'] += 1
    if not out:
        return blob
    out += blob[prev:]
    return bytes(out)


def build(src: str, table: Dict[str, str], out_path: str,
          encoding: str = 'gbk',
          allow_unvalidated: Optional[Set[str]] = None,
          pad: bool = False) -> dict:
    """Write a localized copy of ``src`` to ``out_path``.

    ``pad=True`` produces an equal-length build: every rewritten payload keeps
    its original byte size, so no offset anywhere in the stream moves.
    """
    from .props import vocabulary
    pe = PEFile.open(src)
    pe.read_resources()
    vocab = vocabulary(pe)
    stats = collections.Counter()
    changed = 0
    for tname, rname, lang, leaf in pe.iter_resources():
        blob = leaf['__data__']
        if not (len(blob) > 4 and blob[:4] == b'TPF0'):
            continue
        nb = patch_form(blob, table, encoding=encoding,
                        allow_unvalidated=allow_unvalidated, stats=stats,
                        vocab=vocab, pad=pad)
        if nb != blob:
            leaf['__data__'] = nb
            changed += 1
    info = pe.save(out_path)
    info.update({'resources_changed': changed, 'stats': dict(stats),
                 'property_vocabulary': len(vocab), 'padded': pad,
                 'size': os.path.getsize(out_path)})
    return info


def translation_delta(src: str, table_path: str) -> dict:
    """Check which dictionary entries can actually be applied to ``src``."""
    from .props import vocabulary
    table = json.load(open(table_path, encoding='utf-8'))
    pe = PEFile.open(src)
    pe.read_resources()
    vocab = vocabulary(pe)
    cert = set()
    unvalidated = set()
    for resource, blob in forms(pe).items():
        for tok in V.scan(blob, vocab):
            if tok['text'] in table:
                (cert if tok['ok'] else unvalidated).add(tok['text'])
    return {
        'table': len(table),
        'property_vocabulary': len(vocab),
        'certified': len(cert),
        'only_unvalidated': sorted(unvalidated - cert),
        'never_seen': sorted(k for k in table if k not in cert and k not in unvalidated),
    }


__all__ = ['build', 'patch_form', 'translation_delta']
