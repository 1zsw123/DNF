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

DATA=Path(__file__).resolve().parent
STATES={
 'ready':'待启动','initializing':'正在准备识别与坐标连接…','waiting_game':'等待游戏启动',
 'waiting_foreground':'请切回游戏窗口，随后自动继续','waiting_coordinates':'正在连接角色坐标…',
 'paused':'已暂停 · 按 F8 继续','manual':'检测到手动移动，松开后自动接回',
 'room_entered':'已进入新房间','loading':'等待房间稳定','approach':'正在接近怪物',
 'face_enemy':'正在调整攻击朝向','combat':'正在攻击','casting':'普攻与技能衔接中',
 'confirm_clear':'等待补刷，继续检查怪物','new_wave':'发现新一轮怪物，继续清理','exit':'正在寻路过门','choose_exit':'请选择下一个出口',
 'finished':'已通关 · 自动输入已停止','unknown_monsters':'发现未适配怪物，已停止',
 'no_path':'暂时找不到通路，已暂停','error':'运行出错，已停止','stopped':'已停止',
 'time_limit':'已达到本轮时间上限，自动停止','waiting':'等待有效游戏数据',
 'round_finished':'本局通关，准备按库存分解或卖装','waiting_rewards':'等待结算结束与再次挑战按钮',
 'disassemble':'正在执行 Alt+D 补充无色','sell':'正在执行 Alt+S 出售白装和蓝装','repair':'正在执行 Alt+F 修理装备',
 'retrying':'正在按 F10 再次挑战','reentered':'已重进，继续下一局',
 'fatigue_empty':'疲劳不足，循环已停止','character_dead':'角色死亡，循环已停止',
 'replay_timeout':'等待结算超时，循环已停止','replay_failed':'未能重新进图，循环已停止',
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
 'recovering':'血量低于 30%，使用快捷栏 3 雷米援助',
 'revive':'确认死亡，按 X 复活','waiting_revive':'已按 X，等待复活',
 'revived':'已复活，恢复战斗','revive_failed':'按 X 后仍未复活，已停止',
 'maintenance_confirmed':'已识别维护成功提示，自动确认',
 'returned_town':'战斗未通关就回城，已停止；请检查角色状态',
 'wrong_dungeon':'未确认目标地图或难度，已停止，不启动战斗',
 'waiting_dungeon':'请进目标副本，或使用自动入场按钮',
 'difficulty_unconfirmed':'所选难度尚未确认，未发送入场键',
}

class App:
    def __init__(self):
        C.WinDLL('user32').SetProcessDPIAware()
        self.root=tk.Tk();self.root.title('DNF 刷图助手')
        self.root.geometry('650x900');self.root.minsize(620,860)
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
        self.selected=tk.StringVar(value='追击歼灭战');self.solo=tk.BooleanVar(value=True)
        self.difficulty=tk.StringVar(value='普通级');self.run_limit=tk.StringVar(value='1')
        try:
            prefs=json.loads((DATA/'gui-preferences.json').read_text(encoding='utf8'))
            if prefs.get('dungeon') in self.presets:self.selected.set(prefs['dungeon'])
            if prefs.get('difficulty') in ('普通级','冒险级'):self.difficulty.set(prefs['difficulty'])
            if 0<=int(prefs.get('runs',1))<=100:self.run_limit.set(str(prefs.get('runs',1)))
        except (OSError,ValueError,TypeError):pass
        panel=ttk.Frame(self.root,padding=22);panel.pack(fill='both',expand=True)
        ttk.Label(panel,text='DNF 刷图助手',font=('Microsoft YaHei UI',21,'bold')).pack(anchor='w')
        ttk.Label(panel,text='技能栏轮换 · 自动绕障 · F10 重进',foreground='#5b6b80').pack(anchor='w',pady=(4,18))
        row=ttk.Frame(panel);row.pack(fill='x')
        ttk.Label(row,text='副本').pack(side='left',padx=(0,12))
        self.maps=ttk.Combobox(row,textvariable=self.selected,values=list(self.presets),state='readonly',font=('Microsoft YaHei UI',11),width=18)
        self.maps.pack(side='left');self.maps.bind('<<ComboboxSelected>>',lambda e:self.update_preset())
        self.mode=ttk.Checkbutton(row,text='单人模式',variable=self.solo);self.mode.pack(side='right')
        options=ttk.Frame(panel);options.pack(fill='x',pady=(8,0))
        ttk.Label(options,text='难度').pack(side='left',padx=(0,12))
        self.difficulties=ttk.Combobox(options,textvariable=self.difficulty,values=['普通级','冒险级'],state='readonly',width=10)
        self.difficulties.pack(side='left')
        ttk.Label(options,text='  局数（0=直到疲劳不足）').pack(side='left')
        self.limits=ttk.Spinbox(options,from_=0,to=100,textvariable=self.run_limit,width=4);self.limits.pack(side='left')
        self.repeat=tk.BooleanVar(value=True)
        self.repeat_box=ttk.Checkbutton(panel,text='自动连续挑战 · 不足分解 / 够用卖装 → 修理 → F10',variable=self.repeat)
        self.repeat_box.pack(anchor='w',pady=(10,0))
        self.dual_active=tk.BooleanVar(value=True)
        self.dual_box=ttk.Checkbutton(panel,text='双刀当前已开（H 保持开启，不反复切换）',variable=self.dual_active)
        self.dual_box.pack(anchor='w',pady=(4,0))
        self.preset_info=ttk.Label(panel,foreground='#5b6b80',wraplength=520)
        self.preset_info.pack(anchor='w',pady=(8,12));self.update_preset()
        self.status=tk.StringVar(value=STATES['ready'])
        statusbox=tk.Frame(panel,bg='white',padx=16,pady=16);statusbox.pack(fill='x')
        tk.Label(statusbox,textvariable=self.status,bg='white',fg='#183353',font=('Microsoft YaHei UI',13,'bold'),wraplength=480,anchor='w',justify='left').pack(fill='x')
        self.metrics=tk.StringVar(value='角色：上头狂战    本轮房间：—    剩余怪物：—')
        tk.Label(statusbox,textvariable=self.metrics,bg='white',fg='#5b6b80',font=('Microsoft YaHei UI',10),anchor='w').pack(fill='x',pady=(10,0))
        self.detail=tk.StringVar(value='全技能；血量低于 30% 才吃药；确认死亡按 X 复活。')
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
        entry_button=ttk.Button(panel,text='从根特入口进入所选副本并开始',command=lambda:self.start(enter=True))
        entry_button.pack(fill='x',pady=(6,0));self.utility_buttons.append(entry_button)
        ttk.Label(panel,text='在根特入口使用自动入场，或进图后点击开始；切出游戏暂停。\n追击歼灭战正在实测，默认只跑 1 局。重进使用 F10。',foreground='#5b6b80',wraplength=540).pack(anchor='w',pady=(12,14))
        doors=ttk.Frame(panel);doors.pack(fill='x')
        ttk.Label(doors,text='岔路选门').pack(side='left',padx=(0,8))
        self.door_buttons={}
        for name,direction in [('← 左','left'),('↑ 上','up'),('↓ 下','down'),('右 →','right')]:
            b=ttk.Button(doors,text=name,command=lambda d=direction:self.choose_exit(d),state='disabled',width=5)
            b.pack(side='left',padx=3);self.door_buttons[direction]=b
        ttk.Label(panel,text='运行记录',font=('Microsoft YaHei UI',10,'bold')).pack(anchor='w',pady=(16,6))
        self.history=tk.Text(panel,height=7,bg='white',fg='#33455c',font=('Microsoft YaHei UI',9),relief='flat',padx=10,pady=8,state='disabled')
        self.history.pack(fill='both',expand=True)
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
        try:
            run_limit=int(self.run_limit.get())
            if not 0<=run_limit<=100:raise ValueError()
        except ValueError:
            self.status.set('局数请输入 0–100 的整数');return
        (DATA/'gui-preferences.json').write_text(json.dumps({'dungeon':self.selected.get(),'difficulty':self.difficulty.get(),'runs':run_limit},ensure_ascii=False),encoding='utf8')
        self.update_preset()
        self.control=Control()
        self.control.dual_blades_active=self.dual_active.get()
        self.worker=threading.Thread(target=run,args=(self.control,self.selected.get(),self.messages.put),kwargs={'solo':self.solo.get(),'repeat':self.repeat.get(),'difficulty':self.difficulty.get(),'allow_town_entry':enter,'max_runs':run_limit or None},daemon=False)
        self.maps.configure(state='disabled');self.mode.configure(state='disabled')
        self.repeat_box.configure(state='disabled')
        self.start_btn.configure(state='disabled');self.pause_btn.configure(state='normal',text='暂停  F8');self.stop_btn.configure(state='normal')
        self.status.set('正在启动…');self.worker.start()
    def utility(self,action):
        if self.alive():return
        self.control=Control()
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
            if state=='worker_ended':
                result=update['result'];self.status.set(STATES.get(result,result))
                self.metrics.set(f"本次已通关 {update.get('completed',0)} 局")
                self.start_btn.configure(state='normal');self.pause_btn.configure(state='disabled');self.stop_btn.configure(state='disabled')
                self.maps.configure(state='readonly');self.mode.configure(state='normal')
                self.repeat_box.configure(state='normal')
                if result not in ('unknown_monsters','error'):
                    self.detail.set(f"本次已通关 {update.get('completed',0)} 局 · {self.status.get()}")
                self.append(self.status.get());self.door_choices=[]
                continue
            self.status.set(STATES.get(state,state))
            if 'rooms' in update:self.metrics.set(f"已通关 {update.get('completed',0)} 局    本局房间：{update.get('rooms',0)}    怪物：{update.get('enemies') if update.get('enemies') is not None else '—'}")
            if state=='unknown_monsters':
                self.detail.set('未适配：'+update.get('detail','未知角色'))
                self.append(self.detail.get())
            elif state=='choose_exit':self.detail.set('本房间已无已知怪物。请使用下面的选门按钮。')
            elif state=='error':self.detail.set(update.get('detail','请查看本机错误记录。'))
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
            else:self.detail.set(f"本次已通关 {update.get('completed',0)} 局 · 按库存分解或卖装，再次挑战")
            if state=='choose_exit':self.door_choices=update.get('doors',[])
            elif state in ('room_entered','combat','approach','exit','finished','unknown_monsters','error'):
                self.door_choices=[]
            if state!=self.last_state and state not in ('casting','combat','approach','face_enemy'):
                self.append(self.status.get());self.last_state=state
        if self.alive():self.pause_btn.configure(text='继续  F8' if self.control.paused.is_set() else '暂停  F8')
        for button in self.utility_buttons:button.configure(state='disabled' if self.alive() else 'normal')
        self.dual_box.configure(state='disabled' if self.alive() else 'normal')
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
