"""Two-sided structural validation for 0x06 string tokens.

A token is certified as a *property string value* only when BOTH sides line up:

  before:  [len][name bytes][0x06]        the tag belongs to a property
  after :  [0x00]                         end of the property list, or
           [len][name bytes][valid tag]   the next property, or
           [len][name bytes]              the next entry of a string list

The earlier one-sided rule ("the byte before the tag looks like a name") also
matched byte runs inside binary payloads such as the TMS option arrays
(``Options.Mouse.RowSizeMargin`` ...), and rewriting those corrupts the stream -
that was the cause of the intermittent
``Error reading ListBoxItem..: Property .. does not exist`` crash.
"""
from __future__ import annotations

NAME_CHARS = frozenset(b'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.')
VALID_TAGS = frozenset((0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x09, 0x0b, 0x11))
MAX_NAME = 120


def name_before(buf: bytes, i: int, check_prev: bool = True):
    """If position ``i`` starts a value, return the property name ending at i-1.

    ``check_prev`` rejects names whose length byte is itself preceded by a name
    character.  That guards against accidental matches inside string-array and
    binary payloads, but it *also* rejects a legitimate case: a child object's
    property name that follows its instance name with no separator, e.g.

        \\x09 TMenuItem \\x0c MenuItemEdit \\x04 Text \\x06 \\x04 Edit

    Callers therefore retry with ``check_prev=False`` and rely on the property
    vocabulary to reject the accidental matches instead (see ``token_ok``).
    """
    j = i - 1
    if j < 0 or buf[j] not in NAME_CHARS:
        return None
    while j > 0 and buf[j] in NAME_CHARS:
        j -= 1
    ln = buf[j]
    if not (1 <= ln <= MAX_NAME and j + 1 + ln == i):
        return None
    name = buf[j + 1:i]
    if any(c not in NAME_CHARS for c in name):
        return None
    if check_prev and (j == 0 or buf[j - 1] in NAME_CHARS):
        return None
    return name


def next_property_ok(buf: bytes, i: int, vocab=None) -> bool:
    """Position ``i`` may follow a string value in these cases:

      * ``0x00``                 the property list ends here
      * ``0x06 [len] ...``       the next element of a string list
                                 (TListBox ``Items.Strings``)
      * ``[len][name][tag]``     the next property
      * ``[len][name]``          the final element of a string list, followed by
                                 the list's own terminator

    ``name_after`` already enforces that the candidate is self-consistent (its
    length byte matches, every byte is a name character, and the byte after it
    is a valid value tag), which is a strong structural signal on its own.  An
    earlier revision additionally required the name to be in the property
    vocabulary; that rejected perfectly good values whose *next* property is a
    low-frequency derived name (e.g. ``ExplicitSize.cx``, which never reached
    the vocabulary while its sibling ``ExplicitSize.cy`` did), leaving whole
    button labels like ``Plot`` / ``Numbers`` / ``Scatter plot`` untranslated.
    """
    n = len(buf)
    if i >= n:
        return False
    if buf[i] == 0x00:
        return True
    if buf[i] == 0x06:
        return True                       # string-list continuation
    return name_after(buf, i) is not None


def token_ok(buf: bytes, tag_off: int, byte_len: int, vocab=None) -> bool:
    """Certify the 0x06 token at ``tag_off`` with payload ``byte_len`` bytes.

    Two-step check:

    1. the byte before the tag must terminate a real property name
       (``name_before``); a child object's property name directly following its
       instance name is accepted via the relaxed reading, and
    2. that name must be in the executable's property vocabulary
       (:mod:`past5loc.props`) whenever one is supplied.

    The vocabulary requirement is what rejects the accidental matches that a
    relaxed name check would otherwise let through -- for example an integer
    value that happens to equal 0x06 followed by a real property name.
    """
    if buf[tag_off] != 0x06:
        return False
    name = name_before(buf, tag_off, check_prev=True)
    relaxed = False
    if name is None:
        name = name_before(buf, tag_off, check_prev=False)
        relaxed = True
    if name is None:
        return False
    if vocab is not None and name.decode('latin1') not in vocab:
        return False
    if relaxed and vocab is None:
        # a relaxed name match without a vocabulary is not trustworthy
        return False
    after = tag_off + 2 + byte_len
    return next_property_ok(buf, after, vocab)


def name_after(buf: bytes, i: int) -> bytes:
    """Return the name if [len][name][valid tag] starts at i, else None."""
    n = len(buf)
    if i >= n:
        return None
    ln = buf[i]
    if not (1 <= ln <= MAX_NAME and i + 1 + ln < n):
        return None
    raw = buf[i + 1:i + 1 + ln]
    if any(c not in NAME_CHARS for c in raw):
        return None
    tag = buf[i + 1 + ln]
    if tag not in VALID_TAGS:
        # tolerate the final list entry, which is followed by the list's own
        # terminator instead of a tag
        if tag == 0x00:
            return raw
        return None
    return raw


def decode_payload(raw: bytes):
    """Decode a string payload.

    Resources of the *original* build store UTF-8; a localized build written for
    a CP936 system stores GBK.  Both are accepted, otherwise a scanner run on a
    patched resource would fail to decode its own output and lose its place in
    the stream.
    """
    try:
        text = raw.decode('utf-8')
        if '\ufffd' not in text:
            return text
    except UnicodeDecodeError:
        pass
    for enc in ('gbk', 'cp936', 'latin1'):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return None


def scan(buf: bytes, vocab=None):
    """Yield dicts for every 0x06 run, with a two-sided ``ok`` flag."""
    n = len(buf)
    i = 0
    while i < n - 2:
        if buf[i] == 0x06:
            ln = buf[i + 1]
            if 1 <= ln <= 250 and i + 2 + ln <= n:
                raw = buf[i + 2:i + 2 + ln]
                s = decode_payload(raw)
                if s is None or any(ord(c) < 0x20 for c in s) or '\ufffd' in s:
                    i += 1
                    continue
                yield {'tag_off': i, 'len_off': i + 1, 'data_off': i + 2,
                       'byte_len': ln, 'text': s,
                       'name': name_before(buf, i),
                       'ok': token_ok(buf, i, ln, vocab)}
                i += 2 + ln
                continue
        i += 1
