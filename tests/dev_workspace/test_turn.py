import json

import httpx

from services.gateway.bff.omnigent_client import OmnigentClient, user_message_event


def test_user_message_event_envelope():
    ev = user_message_event("探查 coco")
    assert ev == {"type": "message",
                  "data": {"role": "user", "content": [{"type": "input_text", "text": "探查 coco"}]}}


def test_post_event_posts_to_events_with_header_auth():
    seen = {}

    def h(req):
        seen["path"] = req.url.path
        seen["email"] = req.headers.get("X-Forwarded-Email")
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"queued": True, "item_id": "it-1"})

    c = OmnigentClient("http://omnigent:8000", email="alice@acme.test", transport=httpx.MockTransport(h))
    out = c.post_event("s1", user_message_event("hi"))
    assert seen["path"] == "/v1/sessions/s1/events"
    assert seen["email"] == "alice@acme.test"
    assert seen["body"]["type"] == "message"
    assert out["queued"] is True
