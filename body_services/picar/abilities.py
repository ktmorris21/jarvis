import asyncio
class AbilityError(ValueError):pass
class PiCarAbilities:
    def __init__(self,hardware,audio_io=None): self.hardware=hardware; self.audio_io=audio_io; self._lock=asyncio.Lock()
    async def execute(self,ability,data):
        if ability=="stop": self.hardware.stop(); return {"stopped":True}
        if ability=="speaker":
            if not self.audio_io: raise AbilityError("audio output is not configured")
            encoded=data.get("audio_wav_base64")
            if not encoded: raise AbilityError("speaker command missing audio_wav_base64")
            await self.audio_io.play_wav_base64(encoded)
            return {"played":True,"text":data.get("text")}
        if ability=="look":
            p,t=self.hardware.look(data.get("pan_deg",0),data.get("tilt_deg",0)); return {"pan_deg":p,"tilt_deg":t}
        if ability=="move":
            direction=str(data.get("direction","")).lower()
            if direction not in {"forward","backward"}: raise AbilityError("move.direction must be forward or backward")
            ms=int(data.get("duration_ms",0)); speed=int(data.get("speed",20)); steering=int(data.get("steering_deg",0))
            if ms<=0: raise AbilityError("move.duration_ms is required and must be > 0")
            ms=min(ms,self.hardware.limits.max_move_ms)
            async with self._lock:
                st=self.hardware.set_steering(steering); sp=self.hardware.drive(direction,speed)
                try: await asyncio.sleep(ms/1000)
                finally:self.hardware.stop()
            return {"direction":direction,"speed":sp,"duration_ms":ms,"steering_deg":st}
        raise AbilityError(f"Unsupported ability: {ability}")
