"""Portable farming setup. Writes only a local profile; never starts gameplay."""
from pathlib import Path
import hashlib
import json
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

ROOT = Path(__file__).resolve().parent
VERIFIED_BUILD = '22772f28c768f4512a44ad8a228519417653e4309534c5c84de69cc860d8878a'


def make_profile(client_path, self_name):
    path = Path(client_path).expanduser().resolve(strict=True)
    if path.name.lower() != 'dnf.exe':
        raise ValueError('请选择游戏目录里的 DNF.exe。')
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != VERIFIED_BUILD:
        raise ValueError('客户端版本不同，不能套用当前坐标结构。')
    own = self_name.strip()
    if not own:
        raise ValueError('请填写本机狂战士的完整角色名。')
    return {'enabled': True, 'automatic_reconnect': True,
            'client_path': str(path), 'client_sha256': digest,
            'self_name': own, 'leader_name': '__unused_solo_leader__',
            'role_types': {own: 0x016F972C},
            'self_yolo_compatible': False, 'leader_yolo_compatible': False}


def configure():
    saved = False
    root = tk.Tk(); root.title('DNF 刷图助手 · 本机配置')
    panel = ttk.Frame(root, padding=20); panel.pack(fill='both', expand=True)
    ttk.Label(panel, text='已适配客户端 / 狂战士技能栏', font=('Microsoft YaHei UI', 15)).pack(anchor='w')
    ttk.Label(panel, text='选择本机 DNF.exe；改名不会自动适配其他职业。').pack(anchor='w', pady=10)
    client = tk.StringVar(); own = tk.StringVar(value='上头狂战')
    target = ROOT / 'coordinate-session.json'
    if target.exists():
        try:
            old = json.loads(target.read_text(encoding='utf8'))
            client.set(old.get('client_path', '')); own.set(old.get('self_name', '上头狂战'))
        except (ValueError, OSError):
            pass
    line = ttk.Frame(panel); line.pack(fill='x')
    ttk.Entry(line, textvariable=client, width=65).pack(side='left', fill='x', expand=True)
    def browse():
        selected = filedialog.askopenfilename(parent=root, title='选择 DNF.exe', filetypes=[('DNF.exe', '*.exe')])
        if selected: client.set(selected)
    ttk.Button(line, text='浏览', command=browse).pack(side='left', padx=8)
    ttk.Label(panel, text='本机狂战士角色名').pack(anchor='w', pady=(12, 3))
    ttk.Entry(panel, textvariable=own, width=32).pack(anchor='w')
    def save():
        nonlocal saved
        try:
            profile = make_profile(client.get(), own.get())
            pending = ROOT / 'coordinate-session.new.json'
            pending.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding='utf8')
            pending.replace(target); saved = True; root.destroy()
        except (OSError, ValueError) as exc:
            messagebox.showerror('配置未保存', str(exc), parent=root)
    ttk.Button(panel, text='保存并打开助手（不自动开打）', command=save).pack(anchor='w', pady=16)
    root.mainloop()
    return saved


def main():
    if '--configure' in sys.argv or not (ROOT / 'coordinate-session.json').exists():
        if not configure(): return
    from dungeon_farm.gui import App
    App().mainloop()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        import traceback
        (ROOT / 'startup-error.log').write_text(traceback.format_exc(), encoding='utf8')
        root = tk.Tk(); root.withdraw()
        messagebox.showerror('启动失败', str(exc) + '\n先运行 install.cmd 安装依赖。', parent=root)
        root.destroy()
