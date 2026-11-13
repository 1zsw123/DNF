"""First-run setup for the portable follower; does not change the game."""
from pathlib import Path
import hashlib
import json
import logging
import runpy
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from follow_profiles import with_names,load_profile,save_profile

ROOT = Path(__file__).resolve().parent
VERIFIED_BUILD = '22772f28c768f4512a44ad8a228519417653e4309534c5c84de69cc860d8878a'


def make_profile(client_path, self_name, leader_name):
    path = Path(client_path).expanduser().resolve(strict=True)
    if path.name.lower() != 'dnf.exe':
        raise ValueError('请选择游戏目录里的 DNF.exe，不是启动器。')
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != VERIFIED_BUILD:
        raise ValueError('这台电脑的客户端版本与已验证版本不同，请先让 Codex 核对；不会套用旧坐标结构。')
    own, leader = self_name.strip(), leader_name.strip()
    if not own or not leader or own == leader:
        raise ValueError('两个人物名必须完整、非空且互不相同。')
    return with_names({
        'enabled': True, 'automatic_reconnect': True,
        'client_path': str(path), 'client_sha256': VERIFIED_BUILD,
        'self_name': own, 'leader_name': leader,
        'self_yolo_compatible': False, 'leader_yolo_compatible': False,
    },own,leader)


def configure():
    result = False
    root = tk.Tk()
    root.title('DNF 跟随 · 路径与角色配置')
    root.geometry('620x310')
    root.resizable(False, False)
    panel = ttk.Frame(root, padding=18)
    panel.pack(fill='both', expand=True)
    ttk.Label(panel, text='设置本机小号与带队大号', font=('Microsoft YaHei UI', 15, 'bold')).pack(anchor='w')
    ttk.Label(panel, text='完整输入名字；以后可在主界面直接修改或交换。').pack(anchor='w', pady=(8,12))
    previous=load_profile(ROOT)
    client = tk.StringVar(value=previous.get('client_path',''))
    own = tk.StringVar(value=previous.get('self_name',''))
    leader = tk.StringVar(value=previous.get('leader_name',''))
    row = ttk.Frame(panel); row.pack(fill='x')
    ttk.Entry(row, textvariable=client, width=65).pack(side='left', fill='x', expand=True)
    def browse():
        selected = filedialog.askopenfilename(parent=root, title='选择本机 DNF.exe', filetypes=[('DNF.exe', '*.exe')])
        if selected: client.set(selected)
    ttk.Button(row, text='浏览', command=browse).pack(side='left', padx=(8,0))
    for label, value in [('本机跟随角色', own), ('另一台电脑带队角色', leader)]:
        line = ttk.Frame(panel); line.pack(fill='x', pady=8)
        ttk.Label(line, text=label, width=23).pack(side='left')
        ttk.Entry(line, textvariable=value, width=28).pack(side='left')
    def save():
        nonlocal result
        try:
            profile = make_profile(client.get(), own.get(), leader.get())
            save_profile(ROOT,profile)
            result = True
            root.destroy()
        except (OSError, ValueError) as exc:
            messagebox.showerror('配置未保存', str(exc), parent=root)
    ttk.Button(panel, text='保存并打开跟随（默认暂停）', command=save).pack(anchor='w', pady=12)
    root.mainloop()
    return result


def main():
    if '--configure' in sys.argv or not load_profile(ROOT):
        if not configure(): return
    runpy.run_path(str(ROOT/'yolo_follow.py'), run_name='__main__')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        logging.basicConfig(filename=ROOT/'setup-error.log', encoding='utf-8', level=logging.INFO)
        logging.exception('Follower startup failed')
        messagebox.showerror('启动失败', str(exc) + '\n请先运行 install.cmd 安装依赖。')
