"""Background name confirmation; only a fresh match in the current frame can move."""
import queue,threading,time
from follow import NameOCR,Tracker,glyphs


class NameRescue:
    def __init__(self,config):
        self.config=config;self.jobs=queue.Queue(maxsize=1)
        self.lock=threading.Lock();self.templates={};self.epoch=0
        self.closed=threading.Event();self.last_request=0;self.error=''
        self.worker=threading.Thread(target=self.run,daemon=True);self.worker.start()

    def reset(self):
        with self.lock:
            self.epoch+=1;self.templates={}

    def request(self,frame,now):
        if now-self.last_request<.8:return
        with self.lock:epoch=self.epoch
        job=(epoch,frame.copy(),now)
        try:self.jobs.put_nowait(job)
        except queue.Full:
            try:self.jobs.get_nowait()
            except queue.Empty:pass
            try:self.jobs.put_nowait(job)
            except queue.Full:pass
        self.last_request=now

    def run(self):
        try:
            reader=NameOCR()
            while not self.closed.is_set():
                try:epoch,frame,stamp=self.jobs.get(timeout=.2)
                except queue.Empty:continue
                hits=reader.locate(frame,self.config)
                fresh={}
                for role,(foot,score,box,text) in hits.items():
                    aliases=self.config.get(role+'_names', ['上头狂战'] if role=='leader' else ['上头影刃','上头影列','上头影刀','上头影纳'])
                    # Disallow guild, prefix-only, or appearance guesses.
                    if text not in aliases or score<.8:continue
                    x1,y1,x2,y2=box
                    try:tracker=Tracker(frame[y1:y2,x1:x2],(foot[0]-(x1+x2)/2,foot[1]-(y1+y2)/2))
                    except ValueError:continue
                    fresh[role]=(tracker,stamp)
                with self.lock:
                    if epoch==self.epoch:self.templates.update(fresh)
        except Exception as exc:self.error=str(exc)

    def locate(self,frame,now,missing):
        with self.lock:templates=dict(self.templates)
        mask=glyphs(frame);found={}
        for role in missing:
            if role not in templates:continue
            tracker,stamp=templates[role]
            if now-stamp>15:continue
            point,score=tracker.locate(mask,.84)
            if point is not None and 0<=point[0]<=frame.shape[1] and frame.shape[0]*.2<point[1]<frame.shape[0]*.94:
                found[role]={'foot':tuple(map(float,point)),'score':float(score),'source':'confirmed_name'}
        return found

    def close(self):
        self.closed.set();self.reset()
