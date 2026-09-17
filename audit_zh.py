#!/usr/bin/env python3
"""汉化完整性审计：找出**该汉化但仍是英文**的界面字符串。

用法:
    python audit_zh.py <原版Past5.exe> [<汉化版.exe>] [--out audit_missing.json]

判定规则：
  * 只看用户可见属性：Text / Caption / Title / Hint / Items.Strings …
  * 值是纯 ASCII（不含中文）
  * 排除组件实例名、内部标识符、文件格式名、统计术语与缩写、符号、路径

注意：结果里**仍会列出大量刻意保留拉丁**的统计指数名（Bray-Curtis / Jaccard /
Euclidean …）与统计符号（`R2:` `p:` `N:`）——这些不是遗漏。
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from past5loc.pe import PEFile
from past5loc import catalog as cat
from past5loc import validate as V

# 用户可见属性
UI_PROPS = {
    'Text', 'Caption', 'Title', 'Hint', 'TextPrompt', 'TextHint',
    'Items.Strings', 'Header', 'Footer', 'AutoOptionsMenuText',
    'Header.Caption', 'Footer.Caption',
}

# 组件实例名形状
INSTANCE = re.compile(
    r'^(Label|RadioButton|CheckBox|Button|Panel|MenuItem|ListBoxItem|Circle|'
    r'Rectangle|Line|Image|PaintBox|Grid|Column|Row|Tab|Group|Shape|Edit|Memo|'
    r'Combo|Scroll|Popup|Animate|Bitmap|Point|Text|ComboBox|GroupBox|'
    r'SpeedButton|TrackBar|ProgressBar|Corner|Callout|FloatAnimation|'
    r'ColorAnimation|GradientAnimation|RectAnimation|PathAnimation|'
    r'FloatKeyAnimation|ColorKeyAnimation|BitmapListAnimation)')

# 约定保持拉丁的术语 / 缩写 / 格式名
KEEP_LATIN = re.compile(
    r'^(ANOVA|ANCOVA|MANOVA|ARMA|ARIMA|ACE|AR\d|MA\d|PCA|RDA|CCA|NMDS|UPGMA|'
    r'PC-ORD|PERMANOVA|ANOSIM|SIMPER|PGLS|GLS|OLS|RMA|REDFIT|WA-PLS|DBSCAN|'
    r'ISOMAP|UMAP|k-means|k-medoids|LOESS|GAM|SVD|BCa|LDA|QDA|JPG|JPEG|PNG|'
    r'BMP|GIF|TIF|TIFF|PDF|SVG|RTF|CSV|DAT|TXT|XLS|XLSX|NEX|TPS|NTS|FAS|DIC|'
    r'PRF|XML|JSON|HTML|CSS|JS|URL|URI|ASCII|ANSI|UTF-8|ISO-8859-1|WGS84|'
    r'NAD27|NAD83|ED50|GRS80|UTM|RGB|CMYK|DPI|PPI|ID|OK)$', re.I)

ABBREV = re.compile(r'^[A-Z][A-Z0-9\-]{1,7}$')
KEEP_EXTRA = re.compile(
    r'^(UTM-|WGS84|NAD\d|ED50|GRS80|Clarke|Intl|SHCal|MarineCal|IntCal|'
    r'BP \d|BC|AD|CE|Ma|myr)', re.I)


def is_candidate(text: str) -> bool:
    if not text or len(text) > 80:
        return False
    if any(ord(c) > 0x7f for c in text):
        return False
    if not re.search(r'[A-Za-z]', text):
        return False
    if INSTANCE.match(text):
        return False
    if re.search(r'(Label|Radio|Button|Check|Box|Grid|Panel|Column|Image|Item|'
                 r'List|Edit|Memo|Combo|Scroll|Tab|Group|Chart|Series|Popup|'
                 r'Menu|Bar|Shape|Line|Circle|Rect|View|Form|Animation)\d*$', text):
        return False
    if KEEP_LATIN.match(text) or ABBREV.match(text) or KEEP_EXTRA.match(text):
        return False
    if re.match(r'^[A-Za-z]:[\\/]', text) or text.startswith(('http', '\\\\')):
        return False
    if re.search(r'\.(png|jpg|jpeg|svg|bmp|gif|ttf|ico|dat|txt|csv)$', text, re.I):
        return False
    if re.match(r'^[a-z]+[A-Z]', text):
        return False
    if re.match(r'^[a-z][a-z0-9 _]{0,12}$', text) and ' ' not in text:
        return False
    return True


def audit(exe_path: str, label: str):
    pe = PEFile.open(exe_path)
    pe.read_resources()
    missing = collections.Counter()
    total_ui = cn_ui = 0
    for blob in cat.forms(pe).values():
        for tok in V.scan(blob):
            prop = tok['name'].decode('latin1') if tok['name'] else None
            if prop not in UI_PROPS:
                continue
            total_ui += 1
            if re.search(r'[\u4e00-\u9fff]', tok['text']):
                cn_ui += 1
            elif is_candidate(tok['text']):
                missing[tok['text']] += 1
    pct = cn_ui * 100 // max(1, total_ui)
    print(f'\n===== {label} =====')
    print(f'用户可见属性 token: {total_ui}，含中文: {cn_ui} ({pct}%)')
    print(f'疑似待汉化（仍为英文）: {len(missing)} 个唯一串，{sum(missing.values())} 处')
    return missing


def main(argv=None):
    ap = argparse.ArgumentParser(description='汉化完整性审计')
    ap.add_argument('src', help='原版 Past5.exe')
    ap.add_argument('zh', nargs='?', help='汉化版 exe（可选，给出则对比）')
    ap.add_argument('--out', '-o', default='audit_missing.json')
    args = ap.parse_args(argv)

    audit(args.src, '原版')
    if args.zh:
        still = audit(args.zh, '汉化版')
        print('\n===== 汉化版中仍为英文的串（按频次）=====')
        for k, c in sorted(still.items(), key=lambda kv: -kv[1])[:120]:
            print(f'  {c:>4}  {k!r}')
        json.dump(still, open(args.out, 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
        print(f'\n完整清单已写入 {args.out}（{len(still)} 条）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
