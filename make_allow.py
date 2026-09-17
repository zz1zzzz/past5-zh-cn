#!/usr/bin/env python3
"""重新生成 allow_strings.json。

用法:
    python make_allow.py <原版Past5.exe> [--dictionary translations_zh.json]
                         [--out allow_strings.json]

替换条件与 `past5loc.builder` 一致：

  * certified  —— 至少在一个**结构验证通过**的位置出现，直接可替换，无需白名单
  * allow 列表 —— 只在验证失败的位置出现、且**本身不是属性名**的字符串

属性名类字符串（Text / Color / Value / None …）必须排除：它们出现在验证失败的
位置几乎都是误判（某个整数值恰好等于 0x06，紧跟的属性名被读成字符串值），
一旦放行就会替换掉属性名并导致 PAST 启动崩溃。
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from past5loc.pe import PEFile
from past5loc import catalog as cat
from past5loc import validate as V
from past5loc.props import vocabulary


def main(argv=None):
    ap = argparse.ArgumentParser(description='生成 allow_strings.json')
    ap.add_argument('exe', help='原版 Past5.exe 路径')
    ap.add_argument('--dictionary', '-d', default='translations_zh.json')
    ap.add_argument('--out', '-o', default='allow_strings.json')
    args = ap.parse_args(argv)

    table = json.load(open(args.dictionary, encoding='utf-8'))
    pe = PEFile.open(args.exe)
    pe.read_resources()
    vocab = vocabulary(pe)

    cert = set()
    unv = collections.Counter()
    for blob in cat.forms(pe).values():
        for tok in V.scan(blob, vocab):
            if tok['text'] not in table:
                continue
            if tok['ok']:
                cert.add(tok['text'])
            else:
                unv[tok['text']] += 1

    safe = {s: c for s, c in unv.items() if s not in vocab}
    extra = sorted(set(safe) - cert)
    blocked = sorted(set(unv) & set(vocab))

    print(f'词典条目        : {len(table)}')
    print(f'结构验证通过    : {len(cert)}')
    print(f'仅未验证位置    : {len(extra)}  (写入 {args.out})')
    print(f'因是属性名而拒绝: {blocked}')

    json.dump(extra, open(args.out, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print(f'\n已写入 {args.out}')
    for s in extra[:20]:
        print('   ', repr(s))
    return 0


if __name__ == '__main__':
    sys.exit(main())
