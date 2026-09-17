"""Derive the authoritative DFM property-name vocabulary from the executable.

A property name is only accepted when it appears in a fully self-consistent
name/tag sequence AND the same name is seen many times across the 201 forms -
which is true for real DFM property names and false for accidental byte runs.
The resulting vocabulary is the whitelist the patcher uses, which is what makes
rewriting safe: a token is only touched when its preceding name is a known
property.
"""
from __future__ import annotations

import collections
import re
from typing import Dict, Set

from .pe import PEFile
from . import validate as V

NAME_CHARS = V.NAME_CHARS
VALID_TAGS = V.VALID_TAGS


def harvest(pe: PEFile, min_count: int = 3,
            block_prefixes: tuple = ('Options.', 'Items.', 'Appearance.',
                                     'MultiResBitmap', 'StyleLookup')) -> Dict[str, int]:
    """Collect candidate property names with occurrence counts.

    Names starting with ``Options.``/``Items.`` are excluded on purpose: those
    byte runs only *look* like ``[len][name][tag]`` inside the TMS option arrays
    and string lists, and admitting them into the vocabulary is exactly what
    makes a naive patcher rewrite list payloads and corrupt the form.
    """
    counts = collections.Counter()
    for tname, rname, lang, leaf in pe.iter_resources():
        blob = leaf['__data__']
        if not (len(blob) > 4 and blob[:4] == b'TPF0'):
            continue
        n = len(blob)
        i = 1
        while i < n - 2:
            ln = blob[i]
            if 1 <= ln <= V.MAX_NAME and i + 1 + ln < n:
                raw = blob[i + 1:i + 1 + ln]
                tag = blob[i + 1 + ln]
                if tag in VALID_TAGS and all(c in NAME_CHARS for c in raw):
                    name = raw.decode('latin1')
                    if (re.match(r'^[A-Za-z_][A-Za-z0-9_.]*$', name)
                            and not name.startswith(block_prefixes)
                            and i > 0 and blob[i - 1] not in NAME_CHARS):
                        counts[name] += 1
                        i += 1 + ln
                        continue
            i += 1
    return {k: v for k, v in counts.items() if v >= min_count}


def vocabulary(pe: PEFile) -> Set[str]:
    return set(harvest(pe).keys())


if __name__ == '__main__':
    import sys, json
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    pe = PEFile.open(sys.argv[1])
    pe.read_resources()
    h = harvest(pe)
    print('property names:', len(h))
    for k, v in sorted(h.items(), key=lambda kv: -kv[1])[:60]:
        print(f'{v:>6}  {k}')
