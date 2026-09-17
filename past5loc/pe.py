"""past5loc.pe - read, modify and rebuild PE resources.

Only one thing is required for this task: replace the payload of named RCDATA
resources and write a new executable whose .rsrc section carries the updated
data.  The rebuilt section keeps the original section RVA so the PE data
directory entry stays valid without touching any other directory.
"""
from __future__ import annotations

import os
import struct
from typing import Dict, Iterator, Tuple

RT = {
    1: 'CURSOR', 2: 'BITMAP', 3: 'ICON', 4: 'MENU', 5: 'DIALOG', 6: 'STRING',
    7: 'FONTDIR', 8: 'FONT', 9: 'ACCELERATOR', 10: 'RCDATA',
    11: 'MESSAGETABLE', 12: 'GROUP_CURSOR', 14: 'GROUP_ICON', 16: 'VERSION',
    17: 'DLGINCLUDE', 19: 'PLUGPLAY', 20: 'VXD', 21: 'ANICURSOR',
    22: 'ANIICON', 23: 'HTML', 24: 'MANIFEST',
}


class PEError(Exception):
    pass


class PEFile:
    """A writable view over a PE file's resources."""

    def __init__(self, data: bytes):
        self.data = data
        self.e_lfanew = struct.unpack_from('<I', data, 0x3C)[0]
        if data[self.e_lfanew:self.e_lfanew + 4] != b'PE\0\0':
            raise PEError('not a PE file')
        (self.machine, self.nsec, self.timestamp, self.psym, self.nsym,
         self.optsz, self.chars) = struct.unpack_from('<HHIIIHH', data, self.e_lfanew + 4)
        self.opt = self.e_lfanew + 24
        self.magic = struct.unpack_from('<H', data, self.opt)[0]
        self.dd_off = self.opt + (112 if self.magic == 0x20b else 96)
        self.sec_tbl = self.opt + self.optsz
        self.file_align = struct.unpack_from('<I', data, self.opt + 36)[0]
        self.sect_align = struct.unpack_from('<I', data, self.opt + 32)[0]
        self.sections = []
        for i in range(self.nsec):
            o = self.sec_tbl + i * 40
            vsize, vaddr, rsize, raddr = struct.unpack_from('<IIII', data, o + 8)
            ch = struct.unpack_from('<I', data, o + 36)[0]
            self.sections.append({
                'name': data[o:o + 8].rstrip(b'\0'),
                'vsize': vsize, 'vaddr': vaddr, 'rsize': rsize,
                'raddr': raddr, 'chars': ch, 'hdr': o,
            })

    # ------------------------------------------------------------------ load
    @classmethod
    def open(cls, path: str) -> 'PEFile':
        with open(path, 'rb') as fh:
            return cls(fh.read())

    def find_section(self, name: bytes):
        for s in self.sections:
            if s['name'] == name:
                return s
        return None

    def rva_to_off(self, rva: int):
        for s in self.sections:
            if s['vaddr'] <= rva < s['vaddr'] + max(s['vsize'], s['rsize']):
                return s['raddr'] + (rva - s['vaddr'])
        return None

    # ------------------------------------------------------------ resources
    def read_resources(self) -> Dict:
        rsrc = self.find_section(b'.rsrc')
        if not rsrc:
            raise PEError('no .rsrc section')
        base = rsrc['raddr']

        def entries(off):
            nnamed, nid = struct.unpack_from('<HH', self.data, off + 12)
            for i in range(nnamed + nid):
                eo = off + 16 + i * 8
                idn, sub = struct.unpack_from('<II', self.data, eo)
                if idn & 0x80000000:
                    no = base + (idn & 0x7fffffff)
                    ln = struct.unpack_from('<H', self.data, no)[0]
                    label = self.data[no + 2:no + 2 + ln * 2].decode('utf-16le')
                else:
                    label = idn
                yield label, sub

        def node(off):
            out = {}
            for label, sub in entries(off):
                if sub & 0x80000000:
                    out[label] = node(base + (sub & 0x7fffffff))
                else:
                    do = base + sub
                    rva, size, cp, _ = struct.unpack_from('<IIII', self.data, do)
                    o = self.rva_to_off(rva)
                    out[label] = {'__data__': self.data[o:o + size], 'cp': cp,
                                  'rva': rva, 'size': size}
            return out

        self.tree = node(base)
        return self.tree

    def iter_resources(self) -> Iterator[Tuple]:
        """Yield (type, name/id, language, leaf) for every leaf resource.

        The resource tree has three levels: type -> name -> language -> data.
        """
        def is_leaf(v) -> bool:
            return isinstance(v, dict) and '__data__' in v

        for t, names in self.tree.items():
            if is_leaf(names):
                yield (t, None, None, names)
                continue
            for n, langs in names.items():
                if is_leaf(langs):
                    yield (t, n, None, langs)
                    continue
                for lang, leaf in langs.items():
                    if is_leaf(leaf):
                        yield (t, n, lang, leaf)

    def get_rcdata(self) -> Dict:
        return self.tree.get(10, {})

    # -------------------------------------------------------------- rebuild
    def build_rsrc(self, tree=None):
        """Serialise the resource tree; returns (blob, length)."""
        tree = self.tree if tree is None else tree
        rsrc = self.find_section(b'.rsrc')
        va = rsrc['vaddr']

        dirs, datas = [], []
        seen = set()

        def collect(node):
            if id(node) in seen:
                return
            seen.add(id(node))
            dirs.append(node)
            for v in node.values():
                if isinstance(v, dict):
                    if '__data__' in v:
                        datas.append(v)
                    else:
                        collect(v)

        collect(tree)
        names = set()

        def gather_names(node):
            for k, v in node.items():
                if isinstance(k, str):
                    names.add(k)
                if isinstance(v, dict) and '__data__' not in v:
                    gather_names(v)

        gather_names(tree)
        names = sorted(names)

        cur = 0
        dir_off = {}
        for d in dirs:
            dir_off[id(d)] = cur
            nnamed = sum(1 for k in d if isinstance(k, str))
            cur += 16 + len(d) * 8
        cur = (cur + 3) & ~3

        entry_off = {}
        for d in datas:
            entry_off[id(d)] = cur
            cur += 16
        cur = (cur + 3) & ~3

        name_off = {}
        for nm in names:
            enc = nm.encode('utf-16le')
            name_off[nm] = cur
            cur += 2 + len(enc)
            cur = (cur + 1) & ~1
        cur = (cur + 3) & ~3

        payload_off = {}
        for d in datas:
            cur = (cur + 3) & ~3
            payload_off[id(d)] = cur
            cur += len(d['__data__'])
        total = (cur + 3) & ~3

        buf = bytearray(total)
        for nm in names:
            enc = nm.encode('utf-16le')
            o = name_off[nm]
            struct.pack_into('<H', buf, o, len(enc) // 2)
            buf[o + 2:o + 2 + len(enc)] = enc

        for d in datas:
            o = entry_off[id(d)]
            struct.pack_into('<IIII', buf, o, va + payload_off[id(d)],
                             len(d['__data__']), d.get('cp', 0), 0)
            po = payload_off[id(d)]
            buf[po:po + len(d['__data__'])] = d['__data__']

        for d in dirs:
            my = dir_off[id(d)]
            nnamed = sum(1 for k in d if isinstance(k, str))
            nid = len(d) - nnamed
            struct.pack_into('<IIHHHH', buf, my, 0, 0, 0, 0, nnamed, nid)
            eo = my + 16
            items = sorted(d.items(),
                           key=lambda kv: (0, kv[0].lower()) if isinstance(kv[0], str)
                           else (1, kv[0]))
            for k, v in items:
                name_field = (0x80000000 | name_off[k]) if isinstance(k, str) else k
                if isinstance(v, dict) and '__data__' in v:
                    sub = entry_off[id(v)]
                else:
                    sub = 0x80000000 | dir_off[id(v)]
                struct.pack_into('<II', buf, eo, name_field, sub)
                eo += 8
        return bytes(buf), total

    def save(self, out_path: str):
        blob, total = self.build_rsrc()
        rsrc = self.find_section(b'.rsrc')
        data = bytearray(self.data)
        fa = self.file_align or 0x200
        new_size = (len(blob) + fa - 1) // fa * fa
        old_off = rsrc['raddr']
        old_size = (rsrc['rsize'] + fa - 1) // fa * fa
        if new_size <= old_size:
            raw_off = old_off
            blob = blob + b'\0' * (old_size - len(blob))
        else:
            raw_off = (len(data) + fa - 1) // fa * fa
            if len(data) < raw_off:
                data.extend(b'\0' * (raw_off - len(data)))
            blob = blob + b'\0' * (new_size - len(blob))
        if raw_off + len(blob) > len(data):
            data.extend(b'\0' * (raw_off + len(blob) - len(data)))
        data[raw_off:raw_off + len(blob)] = blob
        struct.pack_into('<I', data, rsrc['hdr'] + 8, len(blob) - (len(blob) - total))
        struct.pack_into('<I', data, rsrc['hdr'] + 16, len(blob))
        struct.pack_into('<I', data, rsrc['hdr'] + 20, raw_off)
        if total > rsrc['vsize']:
            img_off = self.opt + 56
            cur_img = struct.unpack_from('<I', data, img_off)[0]
            end = rsrc['vaddr'] + total
            end = (end + self.sect_align - 1) // self.sect_align * self.sect_align
            if end > cur_img:
                struct.pack_into('<I', data, img_off, end)
        with open(out_path, 'wb') as fh:
            fh.write(bytes(data))
        return {'raw_offset': raw_off, 'raw_size': len(blob), 'rsrc_size': total}


__all__ = ['PEFile', 'PEError', 'RT']
