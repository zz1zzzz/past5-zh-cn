"""在词典里加入汉化者署名 zizi。

选用三处用户实际可见的位置（都是资源字符串，可安全变长替换）：

  1. `About`      —— "关于"对话框的窗口标题（打开关于时第一眼看到）
  2. `About Past` —— 帮助菜单里的菜单项（点击入口，一眼可见）
  3. `Untitled`   —— 未打开文件时主窗口的标题

署名放在窗口标题与菜单项上，不侵入任何分析功能。
"""
import json
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
PATH = r'D:\桌面\past5.3\translations_zh.json'

t = json.load(open(PATH, encoding='utf-8'))

SIGN = {
    'About': '关于 PAST 5 · 汉化：zizi',        # 关于对话框标题
    'About Past': '关于 PAST 5（汉化：zizi）',   # 帮助菜单项
    'Untitled': '无标题 · 汉化：zizi',           # 未打开文件时主窗口标题
}

print('署名改动:')
for k, v in SIGN.items():
    old = t.get(k)
    t[k] = v
    print(f'   {k!r:14} {old!r:14} -> {v!r}')

json.dump(t, open(PATH, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(f'\n词典已更新（{len(t)} 条）')
