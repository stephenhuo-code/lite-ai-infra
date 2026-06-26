import base64
import json

import httpx

from services.gateway.bff.omnigent_fs import OmnigentFs


def _fs(handler):
    return OmnigentFs(base_url="http://omnigent:8000", session_id="s1", environment_id="e1",
                      email="alice@acme.test", transport=httpx.MockTransport(handler))


def test_read_decodes_base64():
    def h(req):
        assert req.headers.get("X-Forwarded-Email") == "alice@acme.test"
        assert req.url.path.endswith("/filesystem/recipe.py")
        return httpx.Response(200, json={"content": base64.b64encode(b"hi").decode(), "encoding": "base64"})
    assert _fs(h).read("recipe.py") == b"hi"


def test_read_utf8():
    def h(req):
        return httpx.Response(200, json={"content": "héllo", "encoding": "utf-8"})
    assert _fs(h).read("a.txt") == "héllo".encode()


def test_write_puts_base64():
    seen = {}
    def h(req):
        seen["method"] = req.method
        seen["body"] = json.loads(req.content)
        seen["path"] = req.url.path
        return httpx.Response(200, json={})
    _fs(h).write("out/x.bin", b"\x00\x01")
    assert seen["method"] == "PUT" and seen["path"].endswith("/filesystem/out/x.bin")
    assert base64.b64decode(seen["body"]["content"]) == b"\x00\x01" and seen["body"]["encoding"] == "base64"


def test_listrel_from_changes():
    def h(req):
        assert req.url.path.endswith("/changes")
        return httpx.Response(200, json={"changes": [{"path": "recipe.py"}, {"path": "out/x.bin"}]})
    assert _fs(h).listrel() == ["recipe.py", "out/x.bin"]
