import json
import os
import subprocess
import sys
from pathlib import Path

from agentindex.mcp_server import PROTOCOL_VERSIONS, TOOLS, McpServer
from tests.helpers import ProjectTestCase

REPO_ROOT = Path(__file__).resolve().parent.parent


class McpTestCase(ProjectTestCase):
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


class HandlerTest(McpTestCase):
    def setUp(self):
        super().setUp()
        self.server = McpServer(self.open_index())

    def call(self, method, params=None, request_id=1):
        message = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        return self.server.handle(message)

    def tool(self, name, **arguments):
        result = self.call("tools/call", {"name": name, "arguments": arguments})["result"]
        return result["isError"], result["content"][0]["text"]

    def test_initialize_negotiates_the_version(self):
        result = self.call("initialize", {"protocolVersion": "2025-06-18"})["result"]
        self.assertEqual(result["protocolVersion"], "2025-06-18")
        self.assertEqual(result["capabilities"], {"tools": {"listChanged": False}})
        self.assertLess(len(result["instructions"]), 2048)
        newer = self.call("initialize", {"protocolVersion": "2099-01-01"})["result"]
        self.assertEqual(newer["protocolVersion"], PROTOCOL_VERSIONS[0])

    def test_tools_list(self):
        tools = self.call("tools/list")["result"]["tools"]
        self.assertEqual([t["name"] for t in tools], ["search_docs", "read_doc", "list_docs"])
        for tool in TOOLS:
            self.assertEqual(tool["inputSchema"]["type"], "object")
            self.assertTrue(tool["annotations"]["readOnlyHint"])

    def test_search_read_list(self):
        error, text = self.tool("search_docs", query="rollback", limit=1)
        self.assertFalse(error)
        self.assertIn("1. ops/deploying — Deploying", text)
        self.assertIn('read_doc(id="<id>")', text)
        error, text = self.tool("read_doc", id="ops/deploying#rollback")
        self.assertFalse(error)
        self.assertIn("Use `deploy --rollback`.", text)
        _, text = self.tool("read_doc", id="ops/deploying", section="Rollback")
        self.assertIn("id: ops/deploying#rollback", text)
        _, text = self.tool("read_doc", id="ops/deploying", outline=True)
        self.assertIn("## Rollback  #rollback", text)
        _, text = self.tool("list_docs", tags=["ops"])
        self.assertIn("1 docs:", text)

    def test_recoverable_problems_are_tool_errors(self):
        error, text = self.tool("read_doc", id="ops/deployng")
        self.assertTrue(error)
        self.assertIn("Did you mean: ops/deploying", text)
        for arguments in (
            {},
            {"query": ""},
            {"query": "x", "limit": "lots"},
            {"query": "x", "tags": "ops", "limit": True},
            {"query": "-x"},
        ):
            error, text = self.tool("search_docs", **arguments)
            self.assertTrue(error, arguments)
            self.assertTrue(text.startswith("Error: "))

    def test_protocol_errors(self):
        self.assertEqual(self.call("tools/call", {"name": "nope"})["error"]["code"], -32602)
        self.assertEqual(self.call("resources/list")["error"]["code"], -32601)
        self.assertEqual(self.call("tools/call", ["not", "an", "object"])["error"]["code"], -32602)
        self.assertEqual(self.server.handle({"id": 1, "method": "ping"})["error"]["code"], -32600)
        self.assertEqual(self.server.handle([])["error"]["code"], -32600)
        self.assertEqual(self.call("ping")["result"], {})

    def test_notifications_and_responses_get_no_reply(self):
        self.assertIsNone(
            self.server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
        )
        self.assertIsNone(self.server.handle({"jsonrpc": "2.0", "id": 5, "result": {}}))
        self.assertIsNone(self.server.handle({"jsonrpc": "2.0", "method": "tools/list"}))


class StdioTest(McpTestCase):
    def test_end_to_end_over_stdio(self):
        messages = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0"},
                },
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "search_docs", "arguments": {"query": "redis sessions"}},
            },
            "this is not json",
            [{"jsonrpc": "2.0", "id": 3, "method": "ping"}],
        ]
        stdin = "\n".join(m if isinstance(m, str) else json.dumps(m) for m in messages) + "\n"
        env = {**os.environ, "PYTHONPATH": str(REPO_ROOT), "PYTHONIOENCODING": "utf-8"}
        proc = subprocess.run(
            [sys.executable, "-m", "agentindex", "--root", str(self.root), "mcp"],
            input=stdin.encode("utf-8"),
            capture_output=True,
            env=env,
            timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr.decode())
        replies = [json.loads(line) for line in proc.stdout.decode("utf-8").splitlines()]
        self.assertEqual(len(replies), 4)  # no reply to the notification
        self.assertEqual(replies[0]["result"]["serverInfo"]["name"], "agentindex")
        self.assertIn("1. auth — Auth", replies[1]["result"]["content"][0]["text"])
        self.assertEqual(replies[2]["error"]["code"], -32700)
        self.assertEqual(replies[3], [{"jsonrpc": "2.0", "id": 3, "result": {}}])
