"""Local control panel for the coordinate-based farming worker."""
import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from dungeon_farm.runtime import Control, run
from dungeon_farm.utilities import maintenance
from dungeon_farm.characters import load_characters, save_characters, discover_current, ROTATIONS

DATA=Path(__file__).resolve().parent
STATES={
 'ready':'待启动','initializing':'正在准备识别与坐标连接…','waiting_game':'等待游戏启动',
 'waiting_foreground':'请切回游戏窗口，随后自动继续','waiting_coordinates':'正在连接角色坐标…',
 'paused':'已暂停 · 按 F8 继续','manual':'检测到手动移动，松开后自动接回',
 'room_entered':'已进入新房间','loading':'等待房间稳定','approach':'正在接近怪物',
 'face_enemy':'正在调整攻击朝向','combat':'正在攻击','casting':'普攻与技能衔接中',
 'confirm_clear':'等待补刷，继续检查怪物','new_wave':'发现新一轮怪物，继续清理','exit':'正在寻路过门','choose_exit':'请选择下一个出口',
 'finished':'已通关 · 自动输入已停止','unknown_monsters':'发现未适配怪物，已停止',
 'unknown_ignored':'已忽略未适配对象，继续刷图',
 'no_path':'暂时找不到通路，已暂停','error':'运行出错，已停止','stopped':'已停止',
 'time_limit':'已达到本轮时间上限，自动停止','waiting':'等待有效游戏数据',
 'round_finished':'本局通关，准备按库存分解或卖装','waiting_rewards':'等待结算结束与再次挑战按钮',
 'disassemble':'正在执行 Alt+D 补充无色','sell':'正在执行 Alt+S 出售白装和蓝装','repair':'正在执行 Alt+F 修理装备',
 'retrying':'正在按 F10 再次挑战','reentered':'已重进，继续下一局',
 'fatigue_empty':'疲劳不足，循环已停止','character_dead':'角色死亡，循环已停止',
 'replay_timeout':'等待结算超时，循环已停止','replay_failed':'未能重新进图，循环已停止',
 'town_reentry':'检测到结算后回城，按原难度重新入场',
 'close_overlay':'正在关闭遮挡重进菜单的窗口','overlay_blocked':'结算窗口仍被遮挡，循环已停止',
 'inventory':'正在打开背包','maintenance_sent':'按键已发送，请核对游戏内效果',
 'maintenance_input_sent':'维护按键已发送，等待游戏反馈',
 'entering_town':'正在从城镇走向副本入口','selecting_dungeon':'正在选择目标副本',
 'entering_dungeon':'正在进入地下城','entry_ready':'已核对目标地图和难度',
 'entry_failed':'城镇进图未完成，已停止',
 'selecting_normal':'正在调整所选难度',
 'inventory_checked':'已核对金币与无色库存','inspect_inventory':'正在核对金币与无色库存',
 'inventory_after_maintenance':'已记录维护后的余额',
 'round_statistics':'本局收益已记录',
 'recovering':'血量低于 50%，使用本局唯一一次血药',
 'revive':'确认死亡，按 X 复活','waiting_revive':'已按 X，等待复活',
 'revived':'已复活，恢复战斗','revive_failed':'按 X 后仍未复活，已停止',
 'revive_unconfirmed':'复活后未收到新画面，已停止并等待检查',
 'maintenance_confirmed':'已识别维护成功提示，自动确认',
 'returned_town':'战斗未通关就回城，已停止；请检查角色状态',
 'wrong_dungeon':'未确认目标地图或难度，已停止，不启动战斗',
 'wrong_character':'游戏角色与所选方案不符，请点击“读取当前角色”',
 'waiting_dungeon':'请进目标副本，或使用自动入场按钮',
 'waiting_manual_entry':'通用模式待命：请手动进入要刷的副本',
 'difficulty_unconfirmed':'所选难度尚未确认，未发送入场键',
 'team_connecting':'正在建立双机组队连接',
 'waiting_partner':'等待队友连接或靠近门口',
 'following':'清场后前往大号所在门口','following_close':'已在大号门口集合',
 'following_entering':'已对齐门口，正在跨门并等待换房',
 'waiting_room_clear':'小号原地等待清怪及二轮补刷',
 'waiting_leader_door':'房间已清，等待大号到出口旁',
 'waiting_leader':'小号已就绪，等待大号重进（不卖装、不修理）',
 'follower_overlay':'小号结算有遮挡，等待关闭；不自动操作',
 'waiting_partner_ready':'等待小号卖装、修理完成，再按 F10',
 'team_round_unconfirmed':'未确认同一轮组队战斗，已停止重进',
 'boss_route':'已按小地图规划通往 Boss 的路线',
 'waiting_minimap':'等待确认小地图位置和 Boss 路线',
 'entry_buff':'进图施放状态技能',
 'entry_helper':'进图按 4 召唤帮手（每局一次）',
 'minimap_timeout':'小地图确认超过10秒，已暂停，请检查画面',
 'waiting_boss_result':'已在 Boss 房，等待后续怪物或结算',
}

class App:
    def __init__(self):
        C.WinDLL('user32').SetProcessDPIAware()
        self.root=tk.Tk();self.root.title('DNF 刷图助手')
        self.root.geometry('700x1000');self.root.minsize(650,920)
        self.root.configure(bg='#edf2f7')
        self.style=ttk.Style();self.style.theme_use('clam')
        self.style.configure('TFrame',background='#edf2f7')
        self.style.configure('TLabel',background='#edf2f7',font=('Microsoft YaHei UI',10))
        self.style.configure('TButton',font=('Microsoft YaHei UI',11),padding=(12,9))
        self.style.configure('Start.TButton',background='#2164da',foreground='white',font=('Microsoft YaHei UI',12,'bold'))
        self.style.map('Start.TButton',background=[('active','#347bea'),('disabled','#acbbce')])
        self.messages=queue.SimpleQueue();self.control=None;self.worker=None;self.closing=False
        self.last_state=None;self.door_choices=[]
        self.presets=json.loads((DATA/'presets.json').read_text(encoding='utf-8'))
        self.selected=tk.StringVar(value='阿登高地');self.solo=tk.BooleanVar(value=True)
        self.characters=load_characters()
        self.character_name=tk.StringVar(value=self.characters[0]['name'])
        self.rotation=tk.StringVar(value=self.characters[0]['rotation'])
        self.auto_potion=tk.BooleanVar(value=self.characters[0].get('auto_potion',False))
        self.difficulty=tk.StringVar(value='冒险级');self.run_limit=tk.StringVar(value='1')
        try:
            prefs=json.loads((DATA/'gui-preferences.json').read_text(encoding='utf8'))
            if prefs.get('dungeon') in self.presets:self.selected.set(prefs['dungeon'])
            if prefs.get('difficulty') in ('普通级','冒险级','勇士级'):self.difficulty.set(prefs['difficulty'])
            if 0<=int(prefs.get('runs',1))<=100:self.run_limit.set(str(prefs.get('runs',1)))
            if prefs.get('character') in [c['name'] for c in self.characters]:self.character_name.set(prefs['character'])
        except (OSError,ValueError,TypeError):pass
        panel=ttk.Frame(self.root,padding=22);panel.pack(fill='both',expand=True)
        ttk.Label(panel,text='DNF 刷图助手',font=('Microsoft YaHei UI',21,'bold')).pack(anchor='w')
        ttk.Label(panel,text='技能栏轮换 · 自动绕障 · F10 重进',foreground='#5b6b80').pack(anchor='w',pady=(4,18))
        charrow=ttk.Frame(panel);charrow.pack(fill='x',pady=(0,8))
        ttk.Label(charrow,text='角色').pack(side='left',padx=(0,12))
        self.character_box=ttk.Combobox(charrow,textvariable=self.character_name,values=[c['name'] for c in self.characters],state='readonly',width=18)
        self.character_box.pack(side='left');self.character_box.bind('<<ComboboxSelected>>',lambda e:self.select_character())
        self.discover_button=ttk.Button(charrow,text='读取当前角色',command=self.read_character)
        self.discover_button.pack(side='left',padx=(10,0))
        self.team_button=ttk.Button(charrow,text='双机组队设置',command=self.configure_team)
        self.team_button.pack(side='left',padx=(8,0))
        skillrow=ttk.Frame(panel);skillrow.pack(fill='x',pady=(0,8))
        ttk.Label(skillrow,text='技能').pack(side='left',padx=(0,12))
        self.rotation_box=ttk.Combobox(skillrow,textvariable=self.rotation,values=ROTATIONS,state='readonly',width=13)
        self.rotation_box.pack(side='left')
        self.potion_box=ttk.Checkbutton(skillrow,text='3 已放血药（低于50%才用）',variable=self.auto_potion)
        self.potion_box.pack(side='left',padx=(10,0))
        row=ttk.Frame(panel);row.pack(fill='x')
        ttk.Label(row,text='副本').pack(side='left',padx=(0,12))
        self.maps=ttk.Combobox(row,textvariable=self.selected,values=list(self.presets),state='readonly',font=('Microsoft YaHei UI',11),width=18)
        self.maps.pack(side='left');self.maps.bind('<<ComboboxSelected>>',lambda e:self.update_preset())
        self.mode=ttk.Checkbutton(row,text='单人模式',variable=self.solo);self.mode.pack(side='right')
        options=ttk.Frame(panel);options.pack(fill='x',pady=(8,0))
        ttk.Label(options,text='难度').pack(side='left',padx=(0,12))
        self.difficulties=ttk.Combobox(options,textvariable=self.difficulty,values=['普通级','冒险级','勇士级'],state='readonly',width=10)
        self.difficulties.pack(side='left')
        ttk.Label(options,text='  局数（0=直到疲劳不足）').pack(side='left')
        self.limits=ttk.Spinbox(options,from_=0,to=100,textvariable=self.run_limit,width=4);self.limits.pack(side='left')
        self.repeat=tk.BooleanVar(value=True)
        self.repeat_box=ttk.Checkbutton(panel,text='自动连续挑战 · 不足分解 / 够用卖装 → 修理 → F10',variable=self.repeat)
        self.repeat_box.pack(anchor='w',pady=(10,0))
        self.dual_active=tk.BooleanVar(value=True)
        character_options=ttk.Frame(panel);character_options.pack(fill='x',pady=(4,0))
        self.dual_box=ttk.Checkbutton(character_options,text='狂战士专用：双刀当前已开',variable=self.dual_active)
        self.dual_box.pack(side='left')
        self.supplies_button=ttk.Button(character_options,text='血药、人偶与无色',command=self.configure_supplies,padding=(8,3))
        self.supplies_button.pack(side='right')
        self.preset_info=ttk.Label(panel,foreground='#5b6b80',wraplength=520)
        self.preset_info.pack(anchor='w',pady=(8,12));self.update_preset()
        self.status=tk.StringVar(value=STATES['ready'])
        statusbox=tk.Frame(panel,bg='white',padx=16,pady=16);statusbox.pack(fill='x')
        tk.Label(statusbox,textvariable=self.status,bg='white',fg='#183353',font=('Microsoft YaHei UI',13,'bold'),wraplength=480,anchor='w',justify='left').pack(fill='x')
        self.metrics=tk.StringVar(value=f'角色：{self.character_name.get()}    本轮房间：—    剩余怪物：—')
        tk.Label(statusbox,textvariable=self.metrics,bg='white',fg='#5b6b80',font=('Microsoft YaHei UI',10),anchor='w').pack(fill='x',pady=(10,0))
        self.detail=tk.StringVar(value='全技能；血量低于 50% 才吃药，每局最多 1 瓶；死亡按 X 复活。')
        ttk.Label(panel,textvariable=self.detail,foreground='#5b6b80',wraplength=520).pack(anchor='w',pady=(10,12))
        controls=ttk.Frame(panel);controls.pack(fill='x')
        self.start_btn=ttk.Button(controls,text='开始  F8',style='Start.TButton',command=self.start)
        self.start_btn.pack(side='left',fill='x',expand=True,padx=(0,8))
        self.pause_btn=ttk.Button(controls,text='暂停  F8',command=self.toggle_pause,state='disabled')
        self.pause_btn.pack(side='left',fill='x',expand=True,padx=(0,8))
        self.stop_btn=ttk.Button(controls,text='停止  F9',command=self.stop,state='disabled')
        self.stop_btn.pack(side='left',fill='x',expand=True)
        utility_row=ttk.Frame(panel);utility_row.pack(fill='x',pady=(8,0))
        self.utility_buttons=[]
        for label,action in [('背包 I','inventory'),('核对库存','inspect_inventory'),('分解 Alt+D','disassemble'),('卖装 Alt+S','sell'),('修理 Alt+F','repair')]:
            button=ttk.Button(utility_row,text=label,command=lambda a=action:self.utility(a),width=10,padding=(3,8))
            button.pack(side='left',fill='x',expand=True,padx=2);self.utility_buttons.append(button)
        entry_button=ttk.Button(panel,text='自动入场并开始（城镇入口附近 / 选图界面）',command=lambda:self.start(enter=True))
        entry_button.pack(fill='x',pady=(6,0));self.utility_buttons.append(entry_button)
        ttk.Label(panel,text='阿登高地已验证从时空海港入口附近自动进场；其他位置请先手动进图。\n角色下拉框选择脚本控制对象，不代替游戏登录换角色。',foreground='#5b6b80',wraplength=590).pack(anchor='w',pady=(12,14))
        doors=ttk.Frame(panel);doors.pack(fill='x')
        ttk.Label(doors,text='岔路选门').pack(side='left',padx=(0,8))
        self.door_buttons={}
        for name,direction in [('← 左','left'),('↑ 上','up'),('↓ 下','down'),('右 →','right')]:
            b=ttk.Button(doors,text=name,command=lambda d=direction:self.choose_exit(d),state='disabled',width=5)
            b.pack(side='left',padx=3);self.door_buttons[direction]=b
        ttk.Label(panel,text='运行记录',font=('Microsoft YaHei UI',10,'bold')).pack(anchor='w',pady=(16,6))
        self.history=tk.Text(panel,height=7,bg='white',fg='#33455c',font=('Microsoft YaHei UI',9),relief='flat',padx=10,pady=8,state='disabled')
        self.history.pack(fill='both',expand=True)
        self.select_character()
        self.u=C.WinDLL('user32',use_last_error=True)
        self.u.RegisterHotKey.argtypes=[W.HWND,C.c_int,W.UINT,W.UINT]
        self.u.UnregisterHotKey.argtypes=[W.HWND,C.c_int]
        self.u.PeekMessageW.argtypes=[C.POINTER(W.MSG),W.HWND,W.UINT,W.UINT,W.UINT]
        self.hotkey_stop=threading.Event();self.hotkey_ready=threading.Event();self.hotkey_ok=False
        self.hotkey_thread=threading.Thread(target=self.hotkey_loop,daemon=True)
        self.hotkey_thread.start();self.hotkey_ready.wait(2)
        if not self.hotkey_ok:
            self.hotkey_stop.set()
            messagebox.showerror('快捷键被占用','请先关闭这台电脑上的跟随工具或另一份刷图助手，再打开本界面。',parent=self.root)
            self.root.destroy();raise SystemExit(1)
        self.root.protocol('WM_DELETE_WINDOW',self.close)
        self.root.after(50,self.tick)
    def update_preset(self):
        self.presets=json.loads((DATA/'presets.json').read_text(encoding='utf-8'))
        self.preset_info.configure(text=self.presets[self.selected.get()]['status'])
        from dungeon_farm.generic import GENERIC
        if self.selected.get()==GENERIC:
            self.difficulty.set('沿用手动选择');self.difficulties.configure(state='disabled')
        else:
            if self.difficulty.get()=='沿用手动选择':self.difficulty.set('冒险级')
            self.difficulties.configure(state='readonly')
    def select_character(self):
        entry=next(c for c in self.characters if c['name']==self.character_name.get())
        self.rotation.set(entry['rotation']);self.auto_potion.set(entry.get('auto_potion',False))
        self.potion_box.configure(text=f"{entry.get('potion_key','3')} 已放血药（低于50%才用）")
        if hasattr(self,'metrics'):self.metrics.set(f"角色：{entry['name']}    本轮房间：—    剩余怪物：—")
    def read_character(self):
        if self.alive():return
        self.discover_button.configure(state='disabled')
        def read():
            try:self.messages.put({'state':'character_detected','character':discover_current()})
            except Exception as exc:self.messages.put({'state':'character_read_failed','detail':str(exc)})
        threading.Thread(target=read,daemon=True).start()
    def configure_supplies(self):
        if self.alive():return
        entry=next(c for c in self.characters if c['name']==self.character_name.get())
        dialog=tk.Toplevel(self.root);dialog.title('血药、人偶与无色 · '+entry['name'])
        dialog.transient(self.root);dialog.resizable(False,False)
        body=ttk.Frame(dialog,padding=18);body.pack(fill='both',expand=True)
        enabled=tk.BooleanVar(value=self.auto_potion.get())
        key=tk.StringVar(value=entry.get('potion_key','3'))
        helper=tk.BooleanVar(value=entry.get('entry_helper',False))
        cube_row=tk.IntVar(value=entry.get('cube_row',1));cube_column=tk.IntVar(value=entry.get('cube_column',1))
        ttk.Checkbutton(body,text='启用血药：低于50%才用，每局最多1瓶',variable=enabled).pack(anchor='w')
        row=ttk.Frame(body);row.pack(fill='x',pady=10)
        ttk.Label(row,text='血药快捷键').pack(side='left',padx=(0,12))
        ttk.Combobox(row,textvariable=key,values=('1','2','3'),state='readonly',width=5).pack(side='left')
        ttk.Checkbutton(body,text='每局进图按一次4召唤人偶',variable=helper).pack(anchor='w')
        cube=ttk.Frame(body);cube.pack(fill='x',pady=10)
        ttk.Label(cube,text='无色在材料栏：第').pack(side='left')
        ttk.Combobox(cube,textvariable=cube_row,values=tuple(range(1,7)),state='readonly',width=3).pack(side='left')
        ttk.Label(cube,text='行，第').pack(side='left')
        ttk.Combobox(cube,textvariable=cube_column,values=tuple(range(1,9)),state='readonly',width=3).pack(side='left')
        ttk.Label(cube,text='列（从左上角数）').pack(side='left')
        ttk.Label(body,text='请在游戏中核对：所选格子是血药，4号位是人偶。\n药用完后该格可能被自动拾取的物品占用。\n设置仅保存到当前角色，其他角色不变。',wraplength=430,foreground='#5b6b80').pack(anchor='w',pady=12)
        def save():
            entry.update(auto_potion=enabled.get(),potion_key=key.get(),entry_helper=helper.get(),rotation=self.rotation.get(),cube_row=cube_row.get(),cube_column=cube_column.get())
            save_characters(self.characters);self.select_character()
            self.status.set('已保存 '+entry['name']+' 的血药与人偶设置');dialog.destroy()
        ttk.Button(body,text='保存',command=save).pack(side='right')
        dialog.grab_set();dialog.focus_set()
    def configure_team(self):
        if self.alive():return
        from dungeon_farm.team_ui import configure,LABELS
        configure(self.root,self.character_name.get(),lambda value:self.status.set('已保存：'+LABELS[value['mode']]))
    def hotkey_loop(self):
        registered=[]
        try:
            for key,vk in ((701,0x77),(702,0x78)):
                if not self.u.RegisterHotKey(None,key,0x4000,vk):return
                registered.append(key)
            self.hotkey_ok=True;self.hotkey_ready.set()
            msg=W.MSG()
            while not self.hotkey_stop.is_set():
                while self.u.PeekMessageW(C.byref(msg),None,0x0312,0x0312,1):
                    self.messages.put({'command':'toggle' if msg.wParam==701 else 'stop'})
                self.hotkey_stop.wait(.015)
        finally:
            for key in registered:self.u.UnregisterHotKey(None,key)
            self.hotkey_ready.set()
    def alive(self): return self.worker is not None and self.worker.is_alive()
    def start(self,enter=False):
        if self.alive():return
        from dungeon_farm.generic import GENERIC
        if self.selected.get()==GENERIC:enter=False
        try:
            run_limit=int(self.run_limit.get())
            if not 0<=run_limit<=100:raise ValueError()
        except ValueError:
            self.status.set('局数请输入 0–100 的整数');return
        selected=next(c for c in self.characters if c['name']==self.character_name.get())
        from dungeon_farm.team_ui import load_settings
        from dungeon_farm.team_link import validate_config
        try:
            team_config=load_settings();validate_config(team_config,selected['name'])
        except (ValueError,OSError) as exc:
            self.status.set(str(exc));return
        selected.update(rotation=self.rotation.get(),auto_potion=self.auto_potion.get())
        save_characters(self.characters)
        (DATA/'gui-preferences.json').write_text(json.dumps({'dungeon':self.selected.get(),'difficulty':self.difficulty.get(),'runs':run_limit,'character':selected['name']},ensure_ascii=False),encoding='utf8')
        self.update_preset()
        self.control=Control()
        self.control.character=dict(selected);self.control.auto_potion=self.auto_potion.get()
        self.control.team_config=team_config
        self.repeat_box.configure(text=('自动连续跟随 · 结算只等大号重进，不卖装、不修理'
                                        if team_config.get('mode')=='follower' else
                                        '自动连续挑战 · 不足分解 / 够用卖装 → 修理 → F10'))
        if team_config.get('mode','solo')!='solo':self.solo.set(True)
        self.control.dual_blades_active=self.dual_active.get()
        self.worker=threading.Thread(target=run,args=(self.control,self.selected.get(),self.messages.put),kwargs={'solo':self.solo.get(),'repeat':self.repeat.get(),'difficulty':self.difficulty.get(),'allow_town_entry':enter,'max_runs':run_limit or None},daemon=False)
        self.maps.configure(state='disabled');self.mode.configure(state='disabled')
        self.repeat_box.configure(state='disabled')
        self.start_btn.configure(state='disabled');self.pause_btn.configure(state='normal',text='暂停  F8');self.stop_btn.configure(state='normal')
        self.status.set('正在启动…');self.worker.start()
    def utility(self,action):
        if self.alive():return
        self.control=Control()
        self.control.character=dict(next(c for c in self.characters if c['name']==self.character_name.get()))
        self.worker=threading.Thread(target=maintenance,args=(self.control,self.messages.put,action),daemon=False)
        self.start_btn.configure(state='disabled');self.pause_btn.configure(state='normal');self.stop_btn.configure(state='normal')
        self.worker.start()
    def toggle_pause(self):
        if not self.alive():self.start();return
        if self.control.paused.is_set():self.control.paused.clear()
        else:self.control.paused.set()
    def stop(self):
        if not self.alive():self.status.set(STATES['stopped']);return
        if self.control:self.control.stop.set()
        self.status.set('正在停止并松开按键…')
    def choose_exit(self,direction):
        if self.control and direction in self.door_choices:self.control.exit_choice=direction
    def append(self,text):
        import time
        self.history.configure(state='normal')
        self.history.insert('end',time.strftime('%H:%M:%S')+'  '+text+'\n')
        if int(self.history.index('end-1c').split('.')[0])>100:self.history.delete('1.0','20.0')
        self.history.see('end');self.history.configure(state='disabled')
    def tick(self):
        while not self.messages.empty():
            update=self.messages.get()
            if 'command' in update:
                if update['command']=='toggle':self.toggle_pause()
                else:self.stop()
                continue
            state=update['state']
            if state in ('character_detected','character_read_failed'):
                self.discover_button.configure(state='normal')
                if state=='character_detected':
                    found=update['character'];existing=next((c for c in self.characters if c['name']==found['name']),None)
                    if existing:existing['role_type']=found['role_type']
                    else:self.characters.append(found)
                    save_characters(self.characters)
                    self.character_box.configure(values=[c['name'] for c in self.characters])
                    self.character_name.set(found['name']);self.select_character()
                    self.status.set('已选择角色：'+found['name'])
                else:self.status.set(update['detail'])
                continue
            if state=='worker_ended':
                result=update['result'];self.status.set(STATES.get(result,result))
                self.metrics.set(f"本次已通关 {update.get('completed',0)} 局")
                self.start_btn.configure(state='normal');self.pause_btn.configure(state='disabled');self.stop_btn.configure(state='disabled')
                self.maps.configure(state='readonly');self.mode.configure(state='normal')
                self.repeat_box.configure(state='normal')
                if result not in ('unknown_monsters','error','wrong_character'):
                    self.detail.set(f"本次已通关 {update.get('completed',0)} 局 · {self.status.get()}")
                self.append(self.status.get());self.door_choices=[]
                continue
            follower=self.control.team_config.get('mode')=='follower' if self.control else False
            self.status.set('小号通关，等待大号重进（跳过维护）' if state=='round_finished' and follower else STATES.get(state,state))
            if 'rooms' in update:self.metrics.set(f"已通关 {update.get('completed',0)} 局    本局房间：{update.get('rooms',0)}    怪物：{update.get('enemies') if update.get('enemies') is not None else '—'}")
            if state=='unknown_monsters':
                self.detail.set('未适配：'+update.get('detail','未知角色'))
                self.append(self.detail.get())
            elif state=='unknown_ignored':
                self.detail.set('已忽略：'+update.get('detail','未知对象'))
                self.append(self.detail.get())
            elif state=='choose_exit':self.detail.set('本房间已无已知怪物。请使用下面的选门按钮。')
            elif state in ('error','wrong_character'):self.detail.set(update.get('detail','请查看本机错误记录。'))
            elif state in ('waiting_partner','waiting_room_clear','waiting_leader_door','following','following_close','following_entering'):
                self.detail.set(update.get('detail') or '小号只在清场后集合，不参与攻击。')
            elif state=='inventory_checked' and 'detail' in update:self.detail.set(update['detail']);self.append(update['detail'])
            elif state=='inventory_checked' and 'inventory' in update:
                count=update['inventory'].get('cubes')
                text=f"无色：{count if count is not None else '未读准'} · 储备线：{update.get('reserve',100)} · "+('分解补充无色' if update.get('disassemble') else '出售白装和蓝装')
                self.detail.set(text);self.append(text)
            elif state=='round_statistics':
                net=update.get('net_gold');seconds=int(update.get('seconds',0))
                text=f"本局含维护 {seconds} 秒 · 净金币 {net if net is not None else '基线缺失'}"
                self.detail.set(text);self.append(text)
            elif 'elapsed' in update:self.detail.set(f"本局 {int(update.get('elapsed',0))} 秒 · 第 {update.get('wave',1)} 波 · 全技能轮换")
            else:self.detail.set(f"本次已通关 {update.get('completed',0)} 局 · "+('小号结算不操作，等待大号重进' if follower else '按库存分解或卖装，再次挑战'))
            if state=='choose_exit':self.door_choices=update.get('doors',[])
            elif state in ('room_entered','combat','approach','exit','finished','unknown_monsters','error'):
                self.door_choices=[]
            if state!=self.last_state and state not in ('casting','combat','approach','face_enemy'):
                self.append(self.status.get());self.last_state=state
        if self.alive():self.pause_btn.configure(text='继续  F8' if self.control.paused.is_set() else '暂停  F8')
        for button in self.utility_buttons:button.configure(state='disabled' if self.alive() else 'normal')
        self.dual_box.configure(state='disabled' if self.alive() or self.rotation.get()!='狂战士' else 'normal')
        self.character_box.configure(state='disabled' if self.alive() else 'readonly')
        self.team_button.configure(state='disabled' if self.alive() else 'normal')
        self.supplies_button.configure(state='disabled' if self.alive() else 'normal')
        self.rotation_box.configure(state='disabled' if self.alive() else 'readonly')
        self.potion_box.configure(state='disabled' if self.alive() else 'normal')
        if self.alive():self.discover_button.configure(state='disabled')
        elif str(self.start_btn['state'])=='normal':self.discover_button.configure(state='normal')
        self.difficulties.configure(state='disabled' if self.alive() else 'readonly')
        self.limits.configure(state='disabled' if self.alive() else 'normal')
        for d,b in self.door_buttons.items():b.configure(state='normal' if d in self.door_choices else 'disabled')
        if self.closing and not self.alive():
            self.hotkey_stop.set();self.hotkey_thread.join(timeout=1)
            self.root.destroy();return
        self.root.after(50,self.tick)
    def close(self):
        self.closing=True
        if self.control:self.control.stop.set()
        self.status.set('正在退出并松开按键…')
    def mainloop(self):self.root.mainloop()

if __name__=='__main__':App().mainloop()
