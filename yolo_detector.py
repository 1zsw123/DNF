"""Local ONNX detector for the two explicitly trained DNF characters."""
from pathlib import Path
import cv2
import numpy as np
import onnxruntime as ort


class RoleDetector:
    def __init__(self,path,confidence=.4):
        opts=ort.SessionOptions()
        opts.intra_op_num_threads=3
        opts.inter_op_num_threads=1
        opts.graph_optimization_level=ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session=ort.InferenceSession(str(Path(path)),sess_options=opts,providers=['CPUExecutionProvider'])
        self.input=self.session.get_inputs()[0]
        self.size=int(self.input.shape[2])
        self.confidence=confidence

    @staticmethod
    def decode(output,shape,ratio,pad,confidence=.4):
        rows=np.asarray(output)[0]
        if rows.shape[0]==6:
            rows=rows.T
        if rows.shape[1]!=6:
            raise ValueError('需要 small/leader 两类的YOLO11 ONNX模型。')
        scores=rows[:,4:6].max(axis=1)
        classes=rows[:,4:6].argmax(axis=1)
        selected=scores>=confidence
        rows,scores,classes=rows[selected],scores[selected],classes[selected]
        h,w=shape[:2]
        boxes=[]
        for row,score,cid in zip(rows,scores,classes):
            x,y,bw,bh=row[:4]
            x1=float((x-bw/2-pad[0])/ratio);y1=float((y-bh/2-pad[1])/ratio)
            x2=float((x+bw/2-pad[0])/ratio);y2=float((y+bh/2-pad[1])/ratio)
            x1,x2=max(0,x1),min(w,x2);y1,y2=max(0,y1),min(h,y2)
            if y1<85 or y2>h*.94 or not 10<x2-x1<190 or not 35<y2-y1<240:
                continue
            boxes.append({'class':int(cid),'score':float(score),'box':(x1,y1,x2,y2),
                          'foot':((x1+x2)/2,y2-3)})
        kept=[]
        for cid in (0,1):
            subset=[b for b in boxes if b['class']==cid]
            if not subset:
                continue
            xywh=[[b['box'][0],b['box'][1],b['box'][2]-b['box'][0],b['box'][3]-b['box'][1]] for b in subset]
            indices=cv2.dnn.NMSBoxes(xywh,[b['score'] for b in subset],confidence,.45)
            kept.extend(subset[int(i)] for i in np.asarray(indices).reshape(-1))
        roles={}
        for cid,role in ((0,'self'),(1,'leader')):
            candidates=sorted((b for b in kept if b['class']==cid),key=lambda b:b['score'],reverse=True)
            if candidates:
                roles[role]=candidates[0]
        return roles,kept

    def predict(self,frame):
        h,w=frame.shape[:2];ratio=min(self.size/w,self.size/h)
        rw,rh=round(w*ratio),round(h*ratio)
        px,py=(self.size-rw)//2,(self.size-rh)//2
        canvas=np.full((self.size,self.size,3),114,np.uint8)
        canvas[py:py+rh,px:px+rw]=cv2.resize(frame,(rw,rh),interpolation=cv2.INTER_LINEAR)
        tensor=np.ascontiguousarray(canvas[:,:,::-1].transpose(2,0,1)[None],dtype=np.float32)/255
        output=self.session.run(None,{self.input.name:tensor})[0]
        return self.decode(output,frame.shape,ratio,(px,py),self.confidence)
