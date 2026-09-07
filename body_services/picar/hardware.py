from dataclasses import dataclass
@dataclass(frozen=True)
class Limits:
    max_speed:int=35; max_move_ms:int=1000; max_steering_deg:int=30; max_pan_deg:int=35; max_tilt_deg:int=35
class PiCarHardware:
    def __init__(self,mock=False):
        self.mock=mock; self.limits=Limits(); self._px=None
        if not mock:
            from picarx import Picarx
            self._px=Picarx()
    def _clamp(self,v,lo,hi): return max(lo,min(hi,v))

    def stop(self):
        if self.mock: return
        self._px.stop(); self._px.set_dir_servo_angle(0)
    def set_steering(self,d):
        a=int(self._clamp(d,-self.limits.max_steering_deg,self.limits.max_steering_deg))
        if not self.mock:self._px.set_dir_servo_angle(a)
        return a
    def drive(self,direction,speed):
        s=int(self._clamp(speed,0,self.limits.max_speed))
        if self.mock:return s
        self._px.forward(s) if direction=="forward" else self._px.backward(s)
        return s
    def look(self,pan,tilt):
        p=int(self._clamp(pan,-self.limits.max_pan_deg,self.limits.max_pan_deg)); t=int(self._clamp(tilt,-self.limits.max_tilt_deg,self.limits.max_tilt_deg))
        if not self.mock:self._px.set_cam_pan_angle(p); self._px.set_cam_tilt_angle(t)
        return p,t
