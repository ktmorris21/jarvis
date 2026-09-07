import asyncio
from jarvis_core.executive import handle_event
from jarvis_core.models import InterfaceEvent
from jarvis_core.persistence import init_db
from jarvis_core.persistence.repository import repository

def test_dropped_sensor_event_is_not_persisted(tmp_path):
    init_db(); before=len(repository.recent_events(10000))
    asyncio.run(handle_event(InterfaceEvent(event="LIDAR_SCAN",data={"n":1}),source="picar-test"))
    after=len(repository.recent_events(10000))
    assert after==before

def test_task_event_is_persisted_and_routed():
    init_db(); gid=repository.create_goal("count_barks","Count dog barks",80,{"event_subscriptions":["DOG_BARK"]})
    result=asyncio.run(handle_event(InterfaceEvent(event="DOG_BARK"),source="audio-test"))
    assert result["attention"]["disposition"]=="TASK_ROUTE"
    state=repository.get_state(f"task_observation:{gid}")
    assert state["last_event"]=="DOG_BARK"
