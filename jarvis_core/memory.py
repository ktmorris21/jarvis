import math,re
from datetime import datetime,timezone
from .persistence.repository import repository

def _tokens(text):
    stop={"the","and","for","with","that","this","was","are","you","your","has","had","from","but","not","into","about","user"}
    return {t for t in re.findall(r"[a-z0-9']+",text.lower()) if len(t)>2 and t not in stop}

class MemoryService:
    def form_from_event(self, *,event_type,source,data,source_event_id,context=None):
        context=context or {}; created=[]
        if event_type=="USER_ACTIVE" and context.get("was_present") is False:
            created.append(repository.add_memory("episodic",f"The user returned and became active through {source}.",{"source_event_id":source_event_id,"source":source,"tags":["user","return","presence",source]},0.55))
        elif event_type=="USER_IDLE" and context.get("was_present") is True:
            created.append(repository.add_memory("episodic",f"The user became idle or absent from {source}.",{"source_event_id":source_event_id,"source":source,"tags":["user","idle","absence",source]},0.35))
        elif event_type=="USER_SPOKE":
            text=str(data.get("text","")).strip()
            if text: created.append(repository.add_memory("episodic",f'User said: "{text[:1000]}"',{"source_event_id":source_event_id,"source":source,"tags":["user","speech","conversation",source]},0.65))
        elif event_type=="COMMAND_RESULT" and data.get("status")=="failed":
            ability=data.get("ability") or "unknown ability"
            created.append(repository.add_memory("episodic",f"A Jarvis body/interface command failed while attempting {ability}.",{"source_event_id":source_event_id,"source":source,"tags":["failure","command",str(ability),source],"result":data},0.75))
        return created
    def retrieve(self,query,limit=5,memory_type=None):
        candidates=repository.memories(250,memory_type); qt=_tokens(query); now=datetime.now(timezone.utc); scored=[]
        for m in candidates:
            mt=_tokens(m["content"]+" "+" ".join(m.get("data",{}).get("tags",[]))); overlap=len(qt&mt)/max(1,len(qt)); sal=float(m.get("salience",.5)); dt=datetime.fromisoformat(m["created_at"]); dt=dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc); rec=math.exp(-max(0,(now-dt).total_seconds()/86400)/30); score=overlap*.7+sal*.2+rec*.1
            if overlap>0 or sal>=.7: mm=dict(m); mm["relevance_score"]=round(score,4); scored.append((score,mm))
        scored.sort(key=lambda x:(x[0],x[1]["created_at"]),reverse=True); out=[m for _,m in scored[:max(1,min(limit,20))]]
        repository.note_memories_retrieved([m["id"] for m in out]); return out
    def remember_semantic(self,content,tags=None,salience=.7,source="manual"):
        return repository.add_memory("semantic",content.strip(),{"tags":tags or [],"source":source},max(0,min(float(salience),1)))
memory=MemoryService()
