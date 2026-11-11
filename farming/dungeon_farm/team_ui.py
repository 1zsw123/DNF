"""Explicit, local-only two-computer pairing settings."""
import json
import secrets
import socket
from pathlib import Path
import tkinter as tk
from tkinter import ttk,messagebox
from dungeon_farm.team_link import validate_config

STORE=Path(__file__).with_name('team-settings.json')
LABELS={'solo':'单人刷图','leader':'大号清怪带队','follower':'小号跟随'}


def load_settings():
    try:return json.loads(STORE.read_text(encoding='utf8'))
    except FileNotFoundError:return {'mode':'solo','partner':'','host':'','port':18770,'token':''}


def configure(parent,own,done):
    config=load_settings()
    dialog=tk.Toplevel(parent);dialog.title('双机组队设置 · 首版待实机验证')
    dialog.geometry('650x480');dialog.transient(parent)
    panel=ttk.Frame(dialog,padding=18);panel.pack(fill='both',expand=True)
    mode=tk.StringVar(value=LABELS.get(config.get('mode'),'单人刷图'))
    values={k:tk.StringVar(value=str(config.get(k,''))) for k in ('partner','host','token')}
    port=tk.StringVar(value=str(config.get('port',18770)))
    ttk.Label(panel,text='两台电脑各运行一份助手；游戏里先组队，由大号当队长。',wraplength=600).pack(anchor='w')
    ttk.Label(panel,text='本机角色：'+own).pack(anchor='w',pady=8)
    selector=ttk.Combobox(panel,textvariable=mode,values=list(LABELS.values()),state='readonly',width=24)
    selector.pack(anchor='w',pady=6)
    for label,key in [('另一台电脑角色全名','partner'),('大号电脑局域网 IPv4（小号填写）','host'),('两边相同的配对码','token')]:
        ttk.Label(panel,text=label).pack(anchor='w',pady=(8,0))
        ttk.Entry(panel,textvariable=values[key],width=65).pack(fill='x')
    row=ttk.Frame(panel);row.pack(fill='x',pady=8)
    ttk.Label(row,text='端口').pack(side='left');ttk.Entry(row,textvariable=port,width=8).pack(side='left',padx=8)
    ttk.Button(row,text='生成新配对码（大号）',command=lambda:values['token'].set(secrets.token_hex(16))).pack(side='left')
    try:addresses=sorted({i[4][0] for i in socket.getaddrinfo(socket.gethostname(),None,socket.AF_INET)})
    except OSError:addresses=[]
    ttk.Label(panel,text='本机地址候选：'+('、'.join(addresses) or '未读取到')+'\n小号只跟随、低血补药和复活；只有大号按 F10。两边均须保持游戏前台。',wraplength=600).pack(anchor='w',pady=8)
    def save():
        try:
            value={k:v.get().strip() for k,v in values.items()}
            value.update(mode=next(k for k,v in LABELS.items() if v==mode.get()),port=int(port.get()))
            validate_config(value,own)
            temp=STORE.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8');temp.replace(STORE)
            done(value);dialog.destroy()
        except (ValueError,OSError) as exc:messagebox.showerror('未保存',str(exc),parent=dialog)
    ttk.Button(panel,text='保存（下次开始生效）',command=save).pack(anchor='w')
