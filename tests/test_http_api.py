import json
import socket
import threading
import urllib.error
import urllib.request

from agentindex import load_config
from agentindex.http_api import ApiServer
from tests.helpers import ProjectTestCase


class HttpApiTest(ProjectTestCase):
    files = {
        "knowledge/ops/deploying.md": """
            ---
            title: Deploying
            summary: How we deploy.
            tags: [ops]
            ---
            # Deploying

            Run the deploy script.

            ## Rollback

            Use `deploy --rollback`.
        """,
        "knowledge/auth.md": "# Auth\n\nSessions live in redis.\n",
    }

    def setUp(self):
        super().setUp()
        self.server = ApiServer(("127.0.0.1", 0), load_config(self.root), sync_interval=0)
        self.server.quiet = True
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def request(self, path, method="GET"):
        req = urllib.request.Request(self.base + path, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, resp.headers["Content-Type"], resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.headers["Content-Type"], exc.read().decode("utf-8")

    def get_json(self, path, method="GET"):
        status, content_type, body = self.request(path, method)
        self.assertTrue(content_type.startswith("application/json"), content_type)
        return status, json.loads(body)

    def test_index_and_health(self):
        status, body = self.get_json("/")
        self.assertEqual(status, 200)
        self.assertIn("GET /health", body["endpoints"])
        self.assertEqual(self.get_json("/health")[1]["status"], "ok")

    def test_search(self):
        status, body = self.get_json("/search?q=roll+back&limit=1&tag=ops")
        self.assertEqual(status, 200)
        self.assertEqual(body["results"][0]["id"], "ops/deploying")
        self.assertEqual(body["results"][0]["sections"][0]["anchor"], "rollback")

    def test_docs(self):
        status, body = self.get_json("/docs")
        self.assertEqual((status, body["total"]), (200, 2))
        status, body = self.get_json("/docs/ops/deploying")
        self.assertEqual((status, body["title"]), (200, "Deploying"))
        _, body = self.get_json("/docs/ops/deploying?section=rollback")
        self.assertEqual(body["section"]["heading"], "Rollback")
        _, body = self.get_json("/docs/ops/deploying%23rollback")
        self.assertEqual(body["section"]["anchor"], "rollback")
        _, body = self.get_json("/docs/ops/deploying?outline=1")
        self.assertEqual([e["anchor"] for e in body["outline"]], ["deploying", "rollback"])
        status, content_type, text = self.request("/docs/auth?format=text")
        self.assertEqual(status, 200)
        self.assertTrue(content_type.startswith("text/markdown"))
        self.assertTrue(text.startswith("id: auth | file: knowledge/auth.md"))

    def test_errors(self):
        status, body = self.get_json("/docs/ops/deployng")
        self.assertEqual((status, body["suggestions"]), (404, ["ops/deploying"]))
        self.assertEqual(self.get_json("/docs/auth?section=nope")[0], 404)
        self.assertEqual(self.get_json("/nope")[0], 404)
        self.assertEqual(self.get_json("/search")[0], 400)
        self.assertEqual(self.get_json("/search?q=-x")[0], 400)
        self.assertEqual(self.get_json("/search?q=x&limit=many")[0], 400)
        self.assertEqual(self.get_json("/sync")[0], 405)
        self.assertEqual(self.get_json("/search?q=x", method="POST")[0], 405)

    def test_in_memory_database_is_rebuilt_for_each_request(self):
        server = ApiServer(
            ("127.0.0.1", 0), load_config(self.root, db=":memory:"), sync_interval=60
        )
        server.quiet = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.base = f"http://127.0.0.1:{server.server_address[1]}"
        for _ in range(2):
            self.assertEqual(self.get_json("/search?q=redis")[1]["total"], 1)
        self.assertEqual(self.get_json("/docs/auth")[0], 200)

    def test_ipv6_host(self):
        try:
            with socket.socket(socket.AF_INET6) as probe:
                probe.bind(("::1", 0))
        except OSError:
            self.skipTest("IPv6 loopback is not available here")
        server = ApiServer(("::1", 0), load_config(self.root))
        server.quiet = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.base = f"http://[::1]:{server.server_address[1]}"
        self.assertEqual(self.get_json("/health")[1]["status"], "ok")

    def test_sync_and_live_updates(self):
        status, body = self.get_json("/sync", method="POST")
        self.assertEqual((status, sorted(body["added"])), (200, ["auth", "ops/deploying"]))
        self.assertEqual(self.get_json("/sync", method="POST")[1]["unchanged"], 2)
        self.write("knowledge/cache.md", "# Cache\n\nAlso redis.\n")
        self.assertEqual(self.get_json("/search?q=redis")[1]["total"], 2)
        self.assertEqual(self.get_json("/status")[1]["documents"], 3)
