import cv2
import numpy as np


class VerifiedFlow:
    """Local optical flow seeded only by a recognized name/guild label."""
    def __init__(self):
        self.clear()

    def clear(self):
        self.gray=None;self.points=None;self.foot=None
        self.verified=-100.0;self.steps=0

    def seed(self,frame,box,foot,verified):
        gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
        mask=np.zeros_like(gray)
        x1,y1,x2,y2=map(int,box)
        mask[max(0,y1):min(gray.shape[0],y2),max(0,x1):min(gray.shape[1],x2)]=255
        points=cv2.goodFeaturesToTrack(gray,maxCorners=35,qualityLevel=.02,minDistance=2,mask=mask,blockSize=3)
        if points is None or len(points)<6:
            return
        self.gray,self.points,self.foot=gray,points,np.array(foot,dtype=float)
        self.verified,self.steps=verified,0

    def update(self,frame,now):
        if self.points is None or now-self.verified>2:
            self.clear();return None,0.0
        gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
        if gray.shape!=self.gray.shape:
            self.clear();return None,0.0
        args=dict(winSize=(21,21),maxLevel=3,criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,20,.02))
        moved,status,_=cv2.calcOpticalFlowPyrLK(self.gray,gray,self.points,None,**args)
        if moved is None:
            self.clear();return None,0.0
        back,back_status,_=cv2.calcOpticalFlowPyrLK(gray,self.gray,moved,None,**args)
        if back is None:
            self.clear();return None,0.0
        before=self.points.reshape(-1,2);after=moved.reshape(-1,2)
        valid=(status.ravel()>0)&(back_status.ravel()>0)&(np.linalg.norm(back.reshape(-1,2)-before,axis=1)<1.5)
        if valid.sum()<6:
            self.clear();return None,0.0
        delta=np.median((after-before)[valid],axis=0)
        valid &= np.linalg.norm((after-before)-delta,axis=1)<4
        if valid.sum()<6 or valid.mean()<.55 or np.linalg.norm(delta)>(160 if self.steps==0 else 60):
            self.clear();return None,0.0
        self.foot+=delta
        h,w=gray.shape
        if not(0<=self.foot[0]<=w and h*.2<=self.foot[1]<=h*.91):
            self.clear();return None,0.0
        self.points=moved[valid].reshape(-1,1,2)
        self.gray=gray;self.steps+=1
        return tuple(self.foot),.91
