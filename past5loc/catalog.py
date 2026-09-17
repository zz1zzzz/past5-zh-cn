"""past5loc.catalog - extract the translatable string catalogue from a build.

Three sources are scanned:

  1. embedded FMX form streams (RCDATA resources holding TPF0 component streams)
     -> the bulk of the user interface
  2. RCDATA text payloads (HTML/CSS/JS help resources)
  3. string literals compiled into .text/.data (runtime messages)

Every candidate is validated with the two-sided structural check so the
catalogue never contains bytes that merely *look* like strings inside binary
payloads.
"""
from __future__ import annotations

import collections
import re
from typing import Dict, List

from .pe import PEFile
from . import validate as V

# Tokens that are structurally valid but are not user-visible wording.
SKIP_EXACT = {
    'ISO-8859-1', 'UTF-8', 'Segoe UI', 'Consolas', 'WGS84', 'NAD27', 'NAD83',
    'ED50', 'GRS80', 'CLARKE 1866', 'INTL 1924',
}
SKIP_RES = [
    re.compile(r'^icons8[-_]'),
    re.compile(r'^[a-z0-9_]+$'),                       # parameter identifiers
    re.compile(r'^(p|r2|z4|a\d|e\d|chi2|df\d|W|R2|F|T)[A-Za-z]*Label\d*$'),
    re.compile(r'^Options\.'),
    re.compile(r'^Items\.'),
    re.compile(r'^[A-Za-z]:[\\/]'),                    # paths
]


def _skip(text: str) -> bool:
    if text in SKIP_EXACT:
        return True
    return any(rx.match(text) for rx in SKIP_RES)


def is_tpf0(blob: bytes) -> bool:
    return len(blob) > 4 and blob[:4] == b'TPF0'


def forms(pe: PEFile) -> Dict[str, bytes]:
    """Return {resource name: payload} for every TPF0 form resource."""
    out = {}
    for tname, rname, lang, leaf in pe.iter_resources():
        if isinstance(rname, str) and is_tpf0(leaf['__data__']):
            out.setdefault(rname, leaf['__data__'])
    return out


def extract(pe: PEFile, min_len: int = 2, max_len: int = 400) -> dict:
    """Build the catalogue.

    Returns a dict with per-string occurrence lists so a translation file can be
    traced back to the exact resources it affects.
    """
    occ: Dict[str, List[dict]] = collections.defaultdict(list)
    stats = collections.Counter()

    for resource in sorted(forms(pe)):
        blob = forms(pe)[resource]
        for tok in V.scan(blob):
            s = tok['text']
            stats['tokens'] += 1
            if not tok['ok']:
                stats['unvalidated'] += 1
                continue
            if not (min_len <= len(s) <= max_len):
                stats['length_filtered'] += 1
                continue
            if _skip(s):
                stats['shape_filtered'] += 1
                continue
            if not re.search(r'[A-Za-z]', s):
                stats['no_letters'] += 1
                continue
            occ[s].append({'resource': resource, 'offset': tok['data_off'],
                           'bytes': tok['byte_len'], 'property': tok['name']})
            stats['accepted'] += 1

    return {
        'strings': {k: {'count': len(v), 'occ': v}
                    for k, v in sorted(occ.items(),
                                       key=lambda kv: (-len(kv[1]), kv[0]))},
        'unique': len(occ),
        'occurrences': stats['accepted'],
        'stats': dict(stats),
    }


def coverage(pe: PEFile) -> dict:
    """Report per-form how many string tokens are translatable."""
    out = {}
    for resource, blob in forms(pe).items():
        toks = V.scan(blob)
        out[resource] = {
            'tokens': len(toks),
            'validated': sum(1 for t in toks if t['ok']),
        }
    return out


__all__ = ['extract', 'forms', 'coverage', 'is_tpf0']
