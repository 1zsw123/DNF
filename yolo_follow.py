"""A deliberately small runtime: YOLO body detection -> direction keys."""
from pathlib import Path
import ctypes as C
from ctypes import wintypes as W
import json,logging,queue,threading,time
import tkinter as tk
from tkinter import ttk,messagebox
import cv2,mss,numpy as np
from PIL import Image,ImageTk
from follow import Windows,FollowPolicy,enhance_scene,vertical_gate_hint,VIEW_SIZE
from yolo_detector import RoleDetector
from name_rescue import NameRescue
from dungeon_telemetry import follow_directions
from coordinate_connection import CoordinateConnection
from follow_profiles import load_profile,save_profile,with_names

ROOT=Path(__file__).parent


class Follower:
    def __init__(self):
        self.session=load_profile(ROOT)
        self.win=Windows()
        self.root=tk.Tk();self.root.title('DNF 自动跟随 · 坐标优先版')
        self.root.geometry('570x450');self.root.resizable(False,False)
        self.enabled=threading.Event();self.closed=threading.Event()
        self.switch_pending=threading.Event()
        self.policy=FollowPolicy();self.manual_until=0.0
        self.last_hotkey='';self.message='模型加载中…';self.previous=None
        self.coordinate_status='等待连接';self.coordinate_pid=None
        self.latest=None;self.last_save=0.0;self.commands=queue.Queue()
        self.hotkey_ready=threading.Event();self.hotkey_error=None;self.hotkey_id=None
        p=ttk.Frame(self.root,padding=18);p.pack(fill='both',expand=True)
        ttk.Label(p,text='自动跟随',font=('Microsoft YaHei UI',18,'bold')).pack(anchor='w')
        self.own_name=tk.StringVar(value=self.session.get('self_name',''))
        self.leader_name=tk.StringVar(value=self.session.get('leader_name',''))
        for label,value in (('小号（本机角色）',self.own_name),('大号（跟随目标）',self.leader_name)):
            row=ttk.Frame(p);row.pack(fill='x',pady=5)
            ttk.Label(row,text=label,width=20).pack(side='left')
            ttk.Entry(row,textvariable=value,width=28).pack(side='left')
        row=ttk.Frame(p);row.pack(fill='x',pady=5)
        ttk.Button(row,text='保存并切换（暂停）',command=self.apply_names).pack(side='left')
        ttk.Button(row,text='交换大小号',command=self.swap_names).pack(side='left',padx=8)
        self.state_label=ttk.Label(p,font=('Microsoft YaHei UI',12,'bold'));self.state_label.pack(anchor='w')
        buttons=ttk.Frame(p);buttons.pack(fill='x',pady=15)
        ttk.Button(buttons,text='F8 开始 / 暂停',command=self.toggle).pack(side='left',padx=(0,10))
        ttk.Button(buttons,text='F9 停止',command=self.stop).pack(side='left',padx=(0,10))
        ttk.Button(buttons,text='查看识别框',command=self.preview).pack(side='left')
        self.detail=ttk.Label(p,wraplength=500,font=('Microsoft YaHei UI',10));self.detail.pack(anchor='w',pady=8)
        ttk.Label(p,text='保持游戏在前台；手动方向键松开后自动接回。\n只控制方向和奔跑。失去可靠定位时等待重新识别。',foreground='#666666').pack(anchor='w',pady=12)
        self.root.protocol('WM_DELETE_WINDOW',self.close)
        self.hotkeys=threading.Thread(target=self.hotkey_loop,daemon=True);self.hotkeys.start()
        if not self.hotkey_ready.wait(3) or self.hotkey_error:
            raise RuntimeError(self.hotkey_error or '热键注册超时')
        self.worker=threading.Thread(target=self.work,daemon=True);self.worker.start()
        self.root.after(70,self.tick)

    def hotkey_loop(self):
        self.hotkey_id=C.windll.kernel32.GetCurrentThreadId();registered=[]
        try:
            for ident,key in ((1,0x77),(2,0x78)):
                if not self.win.u.RegisterHotKey(None,ident,0x4000,key):
                    self.hotkey_error='F8/F9被占用。请关闭旧版跟随工具。';return
                registered.append(ident)
            self.hotkey_ready.set();msg=W.MSG()
            while self.win.u.GetMessageW(C.byref(msg),None,0,0)>0:
                if msg.message==0x0312:self.commands.put(int(msg.wParam))
        finally:
            self.hotkey_ready.set()
            for ident in registered:self.win.u.UnregisterHotKey(None,ident)

    def stop(self):
        self.enabled.clear();self.win.release()
        self.message='已停止，方向键已松开。'

    def toggle(self):
        if self.switch_pending.is_set():
            self.message='正在切换角色，请稍候再按 F8。';return
        if self.enabled.is_set():self.stop()
        else:
            if not self.worker.is_alive():
                self.message='识别进程已停止，请关闭后重新打开工具。';return
            self.enabled.set();self.message='已开启，回到游戏开始跟随。'

    def swap_names(self):
        own=self.own_name.get();self.own_name.set(self.leader_name.get());self.leader_name.set(own)
        self.apply_names()

    def apply_names(self):
        self.stop()
        try:
            profile=with_names(self.session,self.own_name.get(),self.leader_name.get())
            save_profile(ROOT,profile)
        except (OSError,ValueError) as exc:
            messagebox.showerror('未切换',str(exc),parent=self.root);return
        self.switch_pending.set()
        self.session=profile
        self.latest=None;self.coordinate_pid=None;self.coordinate_status='等待重新识别'
        self.message='已保存，正在清空旧角色识别；完成后按 F8 跟随。'

    def preview(self):
        self.stop()
        if self.latest is None:return
        view=tk.Toplevel(self.root);view.title('识别框：绿色跟随角色 / 红色目标角色')
        rgb=cv2.cvtColor(self.latest,cv2.COLOR_BGR2RGB)
        view.photo=ImageTk.PhotoImage(Image.fromarray(rgb))
        ttk.Label(view,image=view.photo).pack()

    def work(self):
        rescue=None;connection=None;memory_signature=None;memory_run=False;memory_active=False
        try:
            session=self.session
            connection=CoordinateConnection(session)
            self.win.u.GetWindowThreadProcessId.argtypes=[W.HWND,C.POINTER(W.DWORD)]
            self.win.u.GetWindowThreadProcessId.restype=W.DWORD
            use_body_model=any(session.get(key,True) for key in ('self_yolo_compatible','leader_yolo_compatible'))
            detector=RoleDetector(ROOT/'models/roles.onnx') if use_body_model else None
            rescue_config=json.loads((ROOT/'config.json').read_text(encoding='utf-8'))
            if session.get('self_name'):rescue_config['self_names']=[session['self_name']]
            if session.get('leader_name'):rescue_config['leader_names']=[session['leader_name']]
            rescue=NameRescue(rescue_config)
            self.message=('YOLO模型已就绪。' if detector is not None else '坐标和名字识别已就绪。')+'F8开始，F9停止。'
            policy=FollowPolicy();previous=None;was_enabled=False
            last_own=None;last_own_time=0.0
            window=cv2.createHanningWindow((160,90),cv2.CV_32F)
            with mss.mss() as cap:
                while not self.closed.wait(.025):
                    if session is not self.session:
                        self.win.release();connection.close();rescue.close()
                        session=self.session
                        connection=CoordinateConnection(session)
                        detector=None
                        rescue_config.update(self_names=[session['self_name']],leader_names=[session['leader_name']])
                        rescue=NameRescue(rescue_config)
                        policy.reset();previous=None;last_own=None;was_enabled=False
                        memory_signature=None;memory_active=False;memory_run=False
                        self.manual_until=0;self.last_save=0
                        self.switch_pending.clear()
                        self.message=f"已切换：{session['self_name']} → {session['leader_name']}。按 F8 开始。"
                    if not self.enabled.is_set():
                        self.win.release()
                        memory_signature=None;memory_active=False;memory_run=False
                        if was_enabled:rescue.reset()
                        was_enabled=False;policy.reset();previous=None;continue
                    if not was_enabled:
                        policy.reset();previous=None;last_own=None;was_enabled=True
                    hwnd=self.win.game();rect=self.win.rect(hwnd)
                    if not rect or not self.win.foreground(hwnd):
                        self.win.release();policy.reset();previous=None;rescue.reset()
                        memory_signature=None;memory_active=False;memory_run=False
                        if not hwnd:
                            connection.sample(0);self.coordinate_pid=None
                            self.coordinate_status=connection.status
                        self.message='已开启，等待游戏回到前台。';continue
                    now=time.monotonic()
                    if self.win.manual_arrows():self.manual_until=now+.45
                    if now<self.manual_until:
                        self.win.release();policy.reset();last_own=None;previous=None;rescue.reset()
                        memory_signature=None;memory_active=False;memory_run=False
                        self.message='手动操作中，松开方向键后自动接回。';continue
                    if any(self.win.u.GetAsyncKeyState(k)&0x8000 for k in (0x0D,0x1B)):
                        self.stop();self.message='聊天/菜单已暂停，关闭后按F8恢复。';continue
                    frame=cv2.resize(np.asarray(cap.grab(rect))[:,:,:3],VIEW_SIZE,interpolation=cv2.INTER_AREA)
                    processed,dark,transition=enhance_scene(frame)
                    if transition:
                        self.win.release();policy.reset();last_own=None;previous=None;rescue.reset()
                        memory_signature=None;memory_active=False;memory_run=False
                        self.message='正在过图，画面恢复后自动继续。';continue
                    sample=None
                    pid=W.DWORD();self.win.u.GetWindowThreadProcessId(hwnd,C.byref(pid))
                    sample=connection.sample(pid.value)
                    self.coordinate_status=connection.status
                    self.coordinate_pid=connection.reader.pid if connection.reader is not None else None
                    if sample is not None:
                        signature=(sample['pid'],sample['connection_generation'],sample['scene'],sample['self_base'],sample['leader_base'])
                        if signature!=memory_signature:
                            self.win.release();policy.reset();rescue.reset();previous=None
                            memory_signature=signature;memory_ready=now+.2;memory_run=False
                        memory_active=True
                        if now<memory_ready:
                            self.message='已确认副本角色，等待场景稳定。';continue
                        keys,run=follow_directions(sample)
                        if self.win.manual_arrows():
                            self.manual_until=now+.45;self.win.release();memory_signature=None;continue
                        if memory_run and not run:self.win.release()
                        self.win.apply(keys if self.enabled.is_set() else set(),hwnd,run=run)
                        memory_run=run
                        own=sample['self'];target=sample['leader']
                        self.message=f"坐标跟随 | {sample['self_name']}({own[0]:.0f},{own[1]:.0f}) → {sample['leader_name']}({target[0]:.0f},{target[1]:.0f})"
                        if now-self.last_save>1:
                            cv2.putText(frame,'Coordinate follow: '+','.join(sorted(keys)),(20,100),0,.6,(0,255,255),2)
                            self.latest=frame.copy();cv2.imencode('.jpg',frame)[1].tofile(ROOT/'yolo-preview.jpg')
                            (ROOT/'last_yolo.json').write_text(json.dumps({'time':time.time(),'source':'coordinates','self':own,'leader':target,'keys':sorted(keys),'telemetry':sample,'status':self.message},ensure_ascii=False,indent=2),encoding='utf-8')
                            self.last_save=now
                        continue
                    if memory_active:
                        self.win.release();policy.reset();previous=None;last_own=None;rescue.reset()
                        memory_signature=None;memory_active=False;memory_run=False
                        self.message='副本坐标暂不可用，重新确认画面。';continue
                    roles,boxes=detector.predict(processed) if detector is not None else ({},[])
                    if not session.get('self_yolo_compatible',True):
                        roles.pop('self',None)
                        boxes=[box for box in boxes if box['class']!=0]
                    if not session.get('leader_yolo_compatible',True):
                        roles.pop('leader',None)
                        boxes=[box for box in boxes if box['class']!=1]
                    missing={'self','leader'}-roles.keys()
                    if missing:
                        rescue.request(processed,time.monotonic())
                        roles.update(rescue.locate(processed,time.monotonic(),missing))
                    target=roles.get('leader',{}).get('foot');own=roles.get('self',{}).get('foot')
                    now=time.monotonic()
                    if own is not None:last_own,last_own_time=own,now
                    elif last_own is not None and now-last_own_time<.3:own=last_own
                    gray=cv2.resize(cv2.cvtColor(frame[110:520,40:710],cv2.COLOR_BGR2GRAY),(160,90)).astype(np.float32)
                    moved=False
                    if previous is not None:
                        shift,response=cv2.phaseCorrelate(previous,gray,window)
                        moved=response>.15 and .25<np.hypot(*shift)<25
                    previous=gray
                    keys,note=policy.step(target,own,frame.shape,now,gap=80,door_grace=4,scene_moved=moved,exit_hint=vertical_gate_hint(processed,target))
                    if self.win.manual_arrows():
                        self.manual_until=now+.45;self.win.release();policy.reset();continue
                    self.win.apply(keys if self.enabled.is_set() else set(),hwnd,run=True)
                    own_score=roles.get('self',{}).get('score',0);leader_score=roles.get('leader',{}).get('score',0)
                    self.message=f'{connection.status}；视觉备用：{note}  |  跟随角色 {own_score:.2f} / 目标 {leader_score:.2f}'
                    rescued=[session.get('self_name','跟随角色') if role=='self' else session.get('leader_name','目标') for role,r in roles.items() if r.get('source')=='confirmed_name']
                    if rescued:self.message+='  名字确认：'+','.join(rescued)
                    if now-self.last_save>1:
                        for role,r in roles.items():
                            if r.get('source')=='confirmed_name':
                                x,y=map(round,r['foot']);cv2.circle(frame,(x,y),9,(0,255,255),2)
                                cv2.putText(frame,role+' name',(x-35,y+17),0,.45,(0,255,255),1)
                        for box in boxes:
                            x1,y1,x2,y2=map(round,box['box']);color=(0,230,0) if box['class']==0 else (0,0,255)
                            cv2.rectangle(frame,(x1,y1),(x2,y2),color,2)
                            cv2.putText(frame,('small' if box['class']==0 else 'leader')+f" {box['score']:.2f}",(x1,max(12,y1-5)),0,.5,color,1)
                        self.latest=frame.copy()
                        cv2.imencode('.jpg',frame)[1].tofile(ROOT/'yolo-preview.jpg')
                        (ROOT/'last_yolo.json').write_text(json.dumps({'time':time.time(),'source':'vision','self':own,'leader':target,'keys':sorted(keys),'detections':boxes,'status':self.message},ensure_ascii=False,indent=2),encoding='utf-8')
                        self.last_save=now
        except Exception as e:
            logging.exception('YOLO follower stopped');self.enabled.clear();self.message='已停止：'+str(e)
        finally:
            self.win.release()
            if rescue is not None:rescue.close()
            if connection is not None:connection.close()

    def tick(self):
        while not self.commands.empty():
            key=self.commands.get_nowait();self.last_hotkey=('F8' if key==1 else 'F9')+time.strftime(' %H:%M:%S')
            if key==1:self.toggle()
            else:self.stop()
        self.state_label.configure(text=('运行中' if self.enabled.is_set() else '已暂停')+'  '+self.last_hotkey,foreground='#137333' if self.enabled.is_set() else '#a63b00')
        self.detail.configure(text=self.message)
        (ROOT/'state.json').write_text(json.dumps({'backend':'coordinates + YOLO11n ONNX','self_name':self.session.get('self_name'),'leader_name':self.session.get('leader_name'),'enabled':self.enabled.is_set(),'worker_alive':self.worker.is_alive(),'last_hotkey':self.last_hotkey,'status':self.message,'coordinate_status':self.coordinate_status,'coordinate_pid':self.coordinate_pid,'time':time.time()},ensure_ascii=False,indent=2),encoding='utf-8')
        if not self.closed.is_set():self.root.after(100,self.tick)

    def close(self):
        self.stop();self.closed.set()
        if self.hotkey_id:self.win.u.PostThreadMessageW(self.hotkey_id,0x0012,0,0)
        self.worker.join(timeout=2);self.win.release();self.root.destroy()


if __name__=='__main__':
    logging.basicConfig(filename=ROOT/'yolo-follow.log',level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s',encoding='utf-8')
    try:Follower().root.mainloop()
    except Exception as e:
        logging.exception('startup');messagebox.showerror('YOLO跟随启动失败',str(e))
