"""Read the verified client inventory UI; unknown counts never mean zero."""
import re,time,json
from collections import Counter
from pathlib import Path

def quantities(texts):
    gold=cubes=None
    for text in texts:
        value=text.replace(' ','').replace(',','').replace('，','')
        match=re.fullmatch(r'(\d+)金币',value)
        if match:gold=int(match[1])
        match=re.fullmatch(r'(\d+)无色小[晶品]块',value)
        if match:cubes=int(match[1])
    return {'gold':gold,'cubes':cubes}

def disassemble_needed(stock,reserve=100):
    # Unknown stock keeps the previously authorized maintenance fallback.
    return stock is None or stock<reserve

def cube_quantity(texts,digits):
    if not any('无色小晶块' in t or '无色小品块' in t for t in texts):return None
    counts=[int(t) for t,score,*_ in digits if re.fullmatch(r'\d{1,6}',t) and float(score)>=.9]
    votes=Counter(counts)
    # Some crops insert a dot inside the same four-digit stack count. Only
    # use such a crop to corroborate an independently recognized integer with
    # very high confidence; dotted text alone is never a quantity.
    strong={int(t) for t,score,*_ in digits if re.fullmatch(r'\d{1,6}',t) and float(score)>=.97}
    for t,score,*_ in digits:
        if re.fullmatch(r'\d{1,4}\.\d{1,3}',t) and float(score)>=.9:
            value=int(t.replace('.',''))
            if value in strong:votes[value]+=1
    agreed=[n for n,votes_for_n in votes.items() if votes_for_n>=2]
    return agreed[0] if len(agreed)==1 else None

def inspect_inventory(win,keys,screen,hwnd,control):
    """Only called in town or a confirmed result screen, never during combat.

    This verified 800x600 client has material-tab/first-cell coordinates below.
    Read the hovered item's full name, so sorting/slot changes cannot silently
    treat a different material's quantity as clear cubes. Two reads must agree.
    """
    result={'gold':None,'cubes':None,'time':time.time()};opened=False
    def read():
        for _ in range(18):
            if control.cancelled() or not win.foreground(hwnd):return None
            value=screen.poll(win,hwnd,full=True)
            if value:return value
            control.stop.wait(.08)
        return None
    try:
        initial=read()
        if not initial or initial.get('selection'):return result
        if not initial.get('overlay'):
            if not keys.key('inventory',hwnd,control.cancelled):return result
            opened=True;control.stop.wait(.3)
        panel=read()
        if not panel or not panel.get('overlay'):return result
        if not keys.click((474,206),hwnd,control.cancelled):return result
        control.stop.wait(.15)
        if not keys.move((390,231),hwnd,control.cancelled):return result
        control.stop.wait(.35)
        readings=[]
        for _ in range(3):
            signals=read()
            if not signals or not signals.get('overlay'):break
            texts=signals.get('texts',[])+signals.get('inventory_texts',[])
            quantity=quantities(texts)
            # Tooltip identifies the item; read the first slot's count alone,
            # avoiding merged Chinese letters and clipped tooltip numbers.
            quantity['cubes']=cube_quantity(texts,signals.get('inventory_digits',[]))
            readings.append({**quantity,'texts':texts,'digits':signals.get('inventory_digits',[])})
        for field in ('gold','cubes'):
            values=[r[field] for r in readings if r[field] is not None]
            if len(values)>=2 and values[-1]==values[-2]:result[field]=values[-1]
        result['readings']=readings
        return result
    finally:
        if opened and not control.cancelled() and win.foreground(hwnd):
            keys.key('inventory',hwnd,control.cancelled)
        (Path(__file__).parent/'inventory-last.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
