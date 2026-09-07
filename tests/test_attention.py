from jarvis_core.attention import attention,Disposition
from jarvis_core.persistence import init_db
from jarvis_core.persistence.repository import repository

def setup_function(): init_db()

def test_high_frequency_noise_drops():
    d=attention.evaluate("LIDAR_SCAN",{})
    assert d.disposition==Disposition.DROP
    assert d.score<0.1

def test_user_speech_reaches_executive():
    d=attention.evaluate("USER_SPOKE",{"text":"Jarvis?"})
    assert d.disposition==Disposition.EXECUTIVE
    assert d.score>=0.9

def test_task_subscription_overrides_boring_event():
    gid=repository.create_goal("count_barks","Count dog barks",80,{"event_subscriptions":["DOG_BARK"]})
    d=attention.evaluate("DOG_BARK",{})
    assert d.disposition==Disposition.TASK_ROUTE
    assert gid in d.matched_goals
