"""past5loc.formstream - TPF0 (Delphi FMX binary component stream) codec.

Grammar (reverse-engineered from Past5.exe and verified byte-for-byte):

    stream  := 'TPF0' object
    object  := sstr Class sstr Instance props 0x00
    props   := prop*                       terminated by a zero name-length byte
    prop    := u8 NameLen name[NameLen] u8 Tag payload

Payload layouts (a tag may in principle serve more than one layout, so the
parser searches candidates and keeps only a parse that consumes the buffer
exactly):

    0x01      1 byte
    0x02      1 byte  |  2 bytes
    0x03      2 bytes
    0x04      4 bytes
    0x05      8 bytes
    0x06      u8 Len + Len bytes      (string value - the translatable unit)
    0x07      u8 Len + Len bytes      (event/method name, Len may be 0)
    0x08      1 byte                  (payload size hint, see below)
    0x09      u8 Len + Len bytes
    0x0B      (u8 Len + Len bytes)* then u8 0      (string list)
    0x11      child object (recursive)

Everything the parser does not understand is preserved verbatim: it only ever
rewrites the length byte plus payload of a 0x06 string, so a patched stream
stays structurally identical to the original parser's view of it.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Iterator

MAGIC = b'TPF0'
MAX_NAME = 120
_STEP_BUDGET = 2_000_000


class FormStreamError(Exception):
    """Raised when a buffer is not a parseable TPF0 component stream."""


def _name_chars_ok(raw: bytes) -> bool:
    if not raw:
        return False
    for c in raw:
        if not (0x20 <= c < 0x7F):
            return False
    return True


@dataclass
class StringToken:
    """A 0x06 string value inside the stream."""
    tag_off: int          # offset of the 0x06 tag byte
    len_off: int          # offset of the length byte
    data_off: int         # offset of the first payload byte
    byte_len: int         # payload length in bytes
    text: str             # decoded (UTF-8) text
    prop: str = ''        # owning property name
    path: str = ''        # owning object path
    valid: bool = False   # passed the structural context check

    def raw(self, buf: bytes) -> bytes:
        return buf[self.data_off:self.data_off + self.byte_len]


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------
class _Parser:
    def __init__(self, buf: bytes):
        self.b = buf
        self.n = len(buf)
        self.steps = 0
        self.tokens: list[StringToken] = []

    # -- primitives ---------------------------------------------------------
    def _u8(self, i: int) -> int:
        if i >= self.n:
            raise FormStreamError('eof')
        return self.b[i]

    def _sstr(self, i: int) -> tuple[str, int]:
        if i >= self.n:
            raise FormStreamError('eof')
        ln = self.b[i]
        j = i + 1
        if ln == 0 or ln > MAX_NAME or j + ln > self.n:
            raise FormStreamError('bad string length')
        raw = self.b[j:j + ln]
        if not _name_chars_ok(raw):
            raise FormStreamError('implausible name')
        return raw.decode('utf-8', 'replace'), j + ln

    # -- object -------------------------------------------------------------
    def object(self, i: int, path: str, depth: int, k):
        self.steps += 1
        if self.steps > _STEP_BUDGET:
            raise FormStreamError('budget')
        if depth > 64:
            raise FormStreamError('depth')
        cls, i = self._sstr(i)
        inst, i = self._sstr(i)
        my_path = f'{path}.{inst}' if path else inst

        def done(props, end):
            return k(cls, inst, my_path, props, end)

        return self.props(i, my_path, depth, done)

    # -- property list ------------------------------------------------------
    def props(self, i: int, path: str, depth: int, k):
        self.steps += 1
        if self.steps > _STEP_BUDGET:
            raise FormStreamError('budget')
        if i >= self.n:
            raise FormStreamError('eof in props')
        nl = self.b[i]
        if nl == 0:
            return k([], i + 1)
        if nl > MAX_NAME or i + 1 + nl >= self.n:
            raise FormStreamError('bad property name length')
        name_raw = self.b[i + 1:i + 1 + nl]
        if not _name_chars_ok(name_raw):
            raise FormStreamError('implausible property name')
        pname = name_raw.decode('utf-8', 'replace')
        j = i + 1 + nl
        tag = self.b[j]
        v0 = j + 1

        for end, rec in self.payloads(v0, tag, pname, path, depth):
            rec['name'] = pname
            rec['tag'] = tag
            rec['start'] = i

            def more(rest, final_end, rec=rec):
                return k([rec] + rest, final_end)

            try:
                return self.props(end, path, depth, more)
            except FormStreamError:
                continue
        raise FormStreamError(f'no layout for tag {tag:#x} property {pname!r}')

    # -- payload candidates -------------------------------------------------
    def payloads(self, i: int, tag: int, pname: str, path: str, depth: int):
        b, n = self.b, self.n

        if tag == 0x01:
            if i + 1 <= n:
                yield i + 1, {'kind': 'int', 'value': b[i]}
            return
        if tag == 0x02:
            if i + 1 <= n:
                yield i + 1, {'kind': 'int', 'value': b[i]}
            if i + 2 <= n:
                yield i + 2, {'kind': 'int',
                              'value': struct.unpack_from('<h', b, i)[0]}
            return
        if tag == 0x03:
            if i + 2 <= n:
                yield i + 2, {'kind': 'int',
                              'value': struct.unpack_from('<h', b, i)[0]}
            return
        if tag == 0x04:
            if i + 4 <= n:
                yield i + 4, {'kind': 'int',
                              'value': struct.unpack_from('<i', b, i)[0]}
            return
        if tag == 0x05:
            if i + 8 <= n:
                yield i + 8, {'kind': 'float',
                              'value': struct.unpack_from('<d', b, i)[0]}
            return
        if tag in (0x06, 0x07, 0x09):
            if i < n:
                ln = b[i]
                if i + 1 + ln <= n:
                    raw = b[i + 1:i + 1 + ln]
                    text = raw.decode('utf-8', 'replace')
                    kind = {0x06: 'string', 0x07: 'event', 0x09: 'ident'}[tag]
                    rec = {'kind': kind, 'value': text,
                           'len_off': i, 'data_off': i + 1, 'data_len': ln}
                    if tag == 0x06:
                        self.tokens.append(StringToken(
                            tag_off=i - 1, len_off=i, data_off=i + 1,
                            byte_len=ln, text=text, prop=pname, path=path))
                    yield i + 1 + ln, rec
            return
        if tag == 0x08:
            # payload-size hint byte; the payload itself is opaque, so only the
            # one-byte reading is offered (the sibling reading is what makes the
            # search diverge on this build).
            if i < n:
                yield i + 1, {'kind': 'hint', 'value': b[i]}
            return
        if tag == 0x0B:
            # string list: (u8 len + bytes)* u8 0
            j = i
            items = []
            try:
                while True:
                    if j >= n:
                        return
                    ln = b[j]
                    if ln == 0:
                        j += 1
                        break
                    if j + 1 + ln > n:
                        return
                    items.append(b[j + 1:j + 1 + ln].decode('utf-8', 'replace'))
                    j += 1 + ln
                yield j, {'kind': 'strlist', 'value': items}
            except Exception:
                return
            return
        if tag == 0x11:
            box = {}

            def capture(cls, inst, sub_path, props, end):
                box['v'] = {'class': cls, 'name': inst, 'path': sub_path,
                            'props': props}
                box['end'] = end
                return True

            try:
                self.object(i, path, depth + 1, capture)
            except FormStreamError:
                return
            if 'v' in box:
                yield box['end'], {'kind': 'object', 'value': box['v']}
            return
        raise FormStreamError(f'unknown tag {tag:#x}')


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------
@dataclass
class FormStream:
    """A parsed TPF0 component stream."""
    root: dict
    tokens: list = field(default_factory=list)
    consumed: int = 0
    size: int = 0


def parse(buf: bytes, budget: int = _STEP_BUDGET) -> FormStream:
    """Parse ``buf``; raise FormStreamError if it is not a valid component stream."""
    if len(buf) < 6 or buf[:4] != MAGIC:
        raise FormStreamError('not a TPF0 stream')
    global _STEP_BUDGET
    old, _STEP_BUDGET = _STEP_BUDGET, budget
    try:
        p = _Parser(buf)
        box = {}

        def root_done(cls, inst, path, props, end):
            # The acceptance test that drives backtracking: only a parse that
            # consumes the whole buffer is correct.  Raising here (rather than
            # checking afterwards) is what makes ambiguous tag widths resolve.
            if end != len(buf):
                raise FormStreamError('trailing bytes')
            box['root'] = {'class': cls, 'name': inst, 'path': path, 'props': props}
            box['end'] = end
            return True

        p.object(4, '', 0, root_done)
    finally:
        _STEP_BUDGET = old
    if 'root' not in box:
        raise FormStreamError('no root object')
    if box['end'] != len(buf):
        raise FormStreamError(
            f'stream does not consume the buffer ({box["end"]} of {len(buf)} bytes)')
    # mark which 0x06 tokens sit in a certifiable property context
    for t in p.tokens:
        t.valid = _context_ok(buf, t.tag_off)
    return FormStream(root=box['root'], tokens=p.tokens,
                      consumed=box['end'], size=len(buf))


def _context_ok(buf: bytes, tag_off: int) -> bool:
    """Structural check used by the patcher to avoid rewriting data blobs."""
    name_chars = set(b'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.')
    j = tag_off - 1
    if j < 0 or buf[j] not in name_chars:
        return False
    while j > 0 and buf[j] in name_chars:
        j -= 1
    namelen = buf[j]
    if not (1 <= namelen <= MAX_NAME and j + 1 + namelen == tag_off):
        return False
    return j > 0 and buf[j - 1] not in name_chars


def walk_strings(buf: bytes) -> list:
    """All 0x06 string tokens, parsed or not.

    Falls back to a relaxed scan when the stream cannot be fully parsed, so no
    translatable text is ever lost; ``valid`` tells the caller whether the token
    is safe to rewrite.
    """
    try:
        fs = parse(buf)
        return fs.tokens
    except FormStreamError:
        return _relaxed_scan(buf)


def _relaxed_scan(buf: bytes) -> list:
    out = []
    n = len(buf)
    i = 0
    while i < n - 2:
        if buf[i] == 0x06:
            ln = buf[i + 1]
            if 1 <= ln <= 250 and i + 2 + ln <= n:
                raw = buf[i + 2:i + 2 + ln]
                try:
                    s = raw.decode('utf-8')
                except UnicodeDecodeError:
                    i += 1
                    continue
                if any(ord(c) < 0x20 for c in s):
                    i += 1
                    continue
                out.append(StringToken(tag_off=i, len_off=i + 1, data_off=i + 2,
                                       byte_len=ln, text=s,
                                       valid=_context_ok(buf, i)))
                i += 2 + ln
                continue
        i += 1
    return out


def patch_strings(buf: bytes, table: dict, encoding: str = 'gbk',
                  allow_unvalidated=frozenset()) -> tuple[bytes, dict]:
    """Rewrite 0x06 string values using ``table``.

    Returns (new_buffer, stats).  A token is rewritten only when the parser
    certifies it as a property string (``valid``) or the caller explicitly lists
    its text in ``allow_unvalidated``.
    """
    stats = {'patched': 0, 'skipped': 0, 'too_long': 0, 'unencodable': 0,
             'unvalidated_hits': 0}
    tokens = walk_strings(buf)
    out = bytearray()
    prev = 0
    for t in tokens:
        repl = table.get(t.text)
        if repl is None or repl == t.text:
            continue
        if not t.valid and t.text not in allow_unvalidated:
            stats['unvalidated_hits'] += 1
            continue
        try:
            enc = repl.encode(encoding, errors='strict')
        except UnicodeEncodeError:
            stats['unencodable'] += 1
            continue
        if len(enc) > 255:
            stats['too_long'] += 1
            continue
        out += buf[prev:t.len_off]
        out.append(len(enc))
        out += enc
        prev = t.data_off + t.byte_len
        stats['patched'] += 1
    if stats['patched'] == 0:
        return buf, stats
    out += buf[prev:]
    return bytes(out), stats


def utf8_to_gbk(text: str) -> str:
    return text


__all__ = ['FormStream', 'FormStreamError', 'StringToken', 'parse',
           'walk_strings', 'patch_strings']
