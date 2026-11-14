"""Low-frequency result-screen check; targeting still uses coordinates."""
import time
import re
import cv2
import numpy as np

def normalize(text):
    text=text.translate(str.maketrans({'無':'无','塊':'块','決':'决','亞':'亚','頓':'顿','戰':'战','－':'-'})).replace('追击开灭战','追击歼灭战').replace('菩通级','普通级')
    text=re.sub(r'决战的都市\s*-\s*亚顿','阿登高地',text)
    return re.sub(r'\s+','',text).lower().translate(str.maketrans({'戰':'战','擇':'择','選':'选','進':'进','鎮':'镇','驗':'验','勞':'劳','復':'复','幣':'币','東':'东','門':'门','級':'级','險':'险','裝':'装','備':'备','確':'确','認':'认','擊':'击','殲':'歼','滅':'灭','雄':'雄'}))

def lifecycle_signals(found,dungeon='根特东门'):
    texts=[normalize(item[1]) for item in found or [] if float(item[2])>=.65]
    joined=''.join(texts)
    exhausted=bool(re.search(r'疲劳.{0,18}(不足|不够|耗尽|用完|为0|为零|沒有|没有|无法|不能)',joined))
    retry=None
    dungeon_option=None
    normal_option=None
    notice=None;notice_confirm=None;ghost=False;target_selected=False;map_titles=[]
    for box,text,confidence in found or []:
        point=np.asarray(box,dtype=float).mean(axis=0)
        value=normalize(text)
        if float(confidence)>=.65 and 420<point[0]<640 and 0<=point[1]<40:
            map_titles.append(value)
        if float(confidence)>=.65 and 220<point[0]<420 and 300<point[1]<390 and value in ('幽灵状态','幽靈狀態','幽灵狀態'):
            ghost=True
        if float(confidence)>=.65 and 200<point[0]<440 and 140<point[1]<300:
            if '分解成功' in value:notice='disassemble'
            elif '出售成功' in value or '售出成功' in value:notice='sell'
            elif any(t in value for t in ('修理成功','修复成功','修理完成','修复完成')):notice='repair'
    if notice:
        for box,text,confidence in found or []:
            point=np.asarray(box,dtype=float).mean(axis=0)
            if float(confidence)>=.65 and normalize(text) in ('确认','确定') and 250<point[0]<380 and 270<point[1]<345:
                notice_confirm=tuple(float(v) for v in point)
    menu_context=any(t in joined for t in ('返回城镇','是否继续','选择其他地下城','选择其它地下城'))
    for box,text,confidence in found or []:
        if float(confidence)>=.7 and normalize(text) in ('普通','普通级'):
            normal_option=tuple(float(v) for v in np.asarray(box,dtype=float).mean(axis=0))
        if float(confidence)>=.65 and normalize(text)==normalize(dungeon):
            point=tuple(float(v) for v in np.asarray(box,dtype=float).mean(axis=0))
            # Exclude the dungeon HUD and the quick-party selector at lower right.
            if 100<point[0]<520 and 60<point[1]<360:dungeon_option=point
        if float(confidence)>=.7 and '再次挑战' in normalize(text):
            p=np.asarray(box,dtype=float).mean(axis=0)
            # This 70 client places its post-clear menu at the upper right.
            if menu_context and 430<p[0]<635 and 35<p[1]<190:
                retry=tuple(float(v) for v in p)
    if dungeon_option:
        ax,ay=dungeon_option
        for box,text,confidence in found or []:
            px,py=np.asarray(box,dtype=float).mean(axis=0)
            if float(confidence)>=.65 and abs(px-ax)<65 and 3<py-ay<24 and re.search(r'lv[.,]?\d{2,3}.{0,3}\d{2,3}',normalize(text)):
                target_selected=True
    return {'finished':result_text(texts),'exhausted':exhausted,'retry':retry,'target_selected':target_selected,
            'dead':ghost or ('复活币' in joined and any(t in joined for t in ('使用','复活角色','按下'))),
            'selection':any(t in joined for t in ('选择难度','进入地下城')) or bool(dungeon_option and '返回城镇' in joined and not retry),
            'dungeon_option':dungeon_option,
            'normal_option':normal_option,
            'east_selected':bool(dungeon_option and 365<dungeon_option[0]<430 and 235<dungeon_option[1]<280 and re.search(r'lv[.,]?056.{0,2}059',joined)),
            'notice':notice,'notice_confirm':notice_confirm,
            # A merchant's overhead name is not an open panel. Never Escape
            # merely because a merchant happens to stand behind the result UI.
            'overlay':any(t in joined for t in ('装备栏','装备欄')),
            'texts':texts,'map_title':''.join(map_titles)}

def result_text(texts):
    joined=''.join(texts).replace(' ','').lower()
    joined=joined.translate(str.maketrans({'戰':'战','擇':'择','鎮':'镇','驗':'验'}))
    if ('再次挑战' in joined and ('返回城镇' in joined or '地下城' in joined)):
        return True
    return 'result' in joined and ('经验' in joined or 'rank' in joined)

class ScreenSignals:
    def __init__(self,dungeon='根特东门'):
        self.dungeon=dungeon
        import mss
        from rapidocr_onnxruntime import RapidOCR
        self.capture=mss.mss()
        self.ocr=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=1)
        self.due=0
        self.inventory_cell=(1,1)
    def poll(self,win,hwnd,full=False):
        now=time.monotonic()
        if now<self.due: return None
        self.due=now+1
        rect=win.rect(hwnd)
        if not rect or not win.foreground(hwnd): return None
        raw=np.asarray(self.capture.grab(rect))[:,:,:3]
        frame=cv2.resize(raw,(640,480))
        x,y=(0,0) if full else (320,20)
        crop=cv2.resize(frame if full else frame[20:420,320:640],None,fx=1.5,fy=1.5)
        found,_=self.ocr(crop)
        found=[[(np.asarray(item[0])/1.5+np.array([x,y])).tolist(),item[1],item[2]] for item in found or []]
        texts=[item[1] for item in found or [] if float(item[2])>=.65]
        signals=lifecycle_signals(found,self.dungeon)
        if full and signals['selection'] and not signals['dungeon_option']:
            # Unselected map cards use much smaller lettering than the HUD.
            # Read the map area at native resolution before enlarging; resizing
            # the entire window to 640 first can erase these thin strokes.
            sy,sx=raw.shape[0]/480,raw.shape[1]/640
            ox,oy=60,55
            cards=raw[int(oy*sy):int(365*sy),int(ox*sx):int(550*sx)]
            detail,_=self.ocr(cv2.resize(cards,None,fx=3,fy=3))
            extra=[[(np.asarray(i[0])/(3*np.array([sx,sy]))+np.array([ox,oy])).tolist(),i[1],i[2]]
                   for i in detail or []]
            found+=extra
            signals=lifecycle_signals(found,self.dungeon)
        if full and signals['overlay']:
            # Verified first material slot's tooltip header; enlarge only the
            # item name/count, and still require its exact name downstream.
            sy,sx=raw.shape[0]/480,raw.shape[1]/640
            row,column=self.inventory_cell
            dx,dy=24*(column-1),24*(row-1)
            hx=min(294+dx,467)
            header=raw[int((104+dy)*sy):int((136+dy)*sy),int(hx*sx):int(min(640,hx+173)*sx)]
            detail,_=self.ocr(cv2.resize(header,None,fx=4,fy=4,interpolation=cv2.INTER_NEAREST))
            signals['inventory_texts']=[normalize(i[1]) for i in detail or [] if float(i[2])>=.8]
            variants=[]
            for y1,y2 in ((219,228),(220,228),(217,230)):
                digits=raw[int((y1+dy)*sy):int((y2+dy)*sy),int((379+dx)*sx):int((403+dx)*sx)]
                big=cv2.resize(digits,None,fx=6,fy=6,interpolation=cv2.INTER_NEAREST)
                variants.append(big)
                variants.append(cv2.resize(digits,None,fx=6,fy=6,interpolation=cv2.INTER_CUBIC))
                gray=cv2.cvtColor(big,cv2.COLOR_BGR2GRAY)
                mask=cv2.threshold(gray,180,255,cv2.THRESH_BINARY)[1]
                variants.append(cv2.cvtColor(mask,cv2.COLOR_GRAY2BGR))
            number,_=self.ocr.text_rec(variants,False)
            signals['inventory_digits']=number
        from dungeon_farm.resources import orb_fill
        signals.update(orb_fill(frame))
        from dungeon_farm.minimap import read_minimap
        signals['minimap']=read_minimap(frame,self.dungeon)
        # The selected card's tiny difficulty badge is missed by full-frame OCR.
        # Its position is relative to the recognized selected East Gate title.
        signals['difficulty']=None
        # Keep the selected card's level-line evidence even if its tiny
        # difficulty badge is temporarily unreadable; never click it twice.
        if signals['selection'] and signals['dungeon_option']:
            ax,ay=signals['dungeon_option']
            if 60<ay<360 and 100<ax<520:
                badge=frame[max(0,int(ay+33)):min(480,int(ay+57)),max(0,int(ax+5)):min(640,int(ax+65))]
                detail,_=self.ocr(cv2.resize(badge,None,fx=5,fy=5))
                for item in detail or []:
                    value=normalize(item[1]).replace('级','')
                    if float(item[2])>=.65 and value in ('普通','冒险','勇士','王者','英雄','地狱'):
                        signals['difficulty']=value
                if signals['difficulty'] is None:
                    # Keep both characters: the title center moves a few pixels
                    # with OCR, and the old +20 left edge clipped 冒 in 冒险.
                    sy,sx=raw.shape[0]/480,raw.shape[1]/640
                    inner=raw[int((ay+36)*sy):int((ay+51)*sy),int((ax+10)*sx):int((ax+50)*sx)]
                    variants=[cv2.resize(inner,None,fx=6,fy=6,interpolation=cv2.INTER_NEAREST),
                              cv2.resize(inner,None,fx=6,fy=6,interpolation=cv2.INTER_CUBIC)]
                    recognized,_=self.ocr.text_rec(variants,False)
                    signals['difficulty_reading']=recognized
                    for text,score,*_ in recognized or []:
                        raw_value=normalize(text).replace('级','')
                        value=raw_value.replace('旨险','冒险').replace('目险','冒险')
                        threshold=.60 if raw_value=='目险' and self.dungeon=='阿登高地' else .65
                        if float(score)>=threshold and value in ('普通','冒险','勇士','王者','英雄','地狱'):
                            signals['difficulty']=value
                if signals['difficulty'] is not None:
                    # Only the highlighted dungeon card has this badge. Its
                    # level text can be covered or split by the hover tooltip.
                    signals['east_selected']=True
                    signals['target_selected']=True
        return signals
    def read_texts(self,win,hwnd):
        """Full-frame OCR: [(centre_xy_in_640x480, normalized_text, confidence)]."""
        rect=win.rect(hwnd)
        if not rect or not win.foreground(hwnd): return None
        raw=np.asarray(self.capture.grab(rect))[:,:,:3]
        frame=cv2.resize(raw,(640,480))
        found,_=self.ocr(cv2.resize(frame,None,fx=1.5,fy=1.5))
        return [(tuple(float(v) for v in (np.asarray(box,dtype=float)/1.5).mean(axis=0)),normalize(text),float(conf))
                for box,text,conf in found or []]
    def close(self): self.capture.close()
