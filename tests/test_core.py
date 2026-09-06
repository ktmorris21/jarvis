from fastapi.testclient import TestClient

from jarvis_core.main import app


def test_health():
    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


def test_websocket_auth_rejects_bad_token():
    with TestClient(app) as client:
        try:
            with client.websocket_connect("/ws?token=wrong"):
                assert False, "expected websocket rejection"
        except Exception:
            pass


def test_websocket_hello():
    with TestClient(app) as client:
        with client.websocket_connect("/ws?token=change-me") as ws:
            ws.send_json({
                "type": "hello",
                "interface_id": "test-desktop",
                "interface_type": "desktop",
                "capabilities": ["speaker"],
            })
            msg = ws.receive_json()
            assert msg["type"] == "hello_ack"
            assert msg["core"] == "jarvis"


def test_core_can_originate_speak_command():
    from jarvis_core import executive
    from jarvis_core.state import state

    # Reset the small amount of mutable POC state this test cares about.
    state.user_present = False
    state.last_user_activity = None
    state.last_interaction = None
    state.social_drive = 0.10
    state.boredom = 0.00

    with TestClient(app) as client:
        with client.websocket_connect("/ws?token=change-me") as ws:
            ws.send_json({
                "type": "hello",
                "interface_id": "agency-test",
                "interface_type": "desktop",
                "capabilities": ["speaker"],
            })
            assert ws.receive_json()["type"] == "hello_ack"

            ws.send_json({"type": "event", "event": "USER_IDLE", "data": {}})
            ws.send_json({"type": "event", "event": "USER_ACTIVE", "data": {}})

            msg = ws.receive_json()
            assert msg["type"] == "command"
            assert msg["ability"] == "speak"
            assert "There you are" in msg["data"]["text"]
