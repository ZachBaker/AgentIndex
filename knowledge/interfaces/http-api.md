---
title: HTTP API
summary: The JSON API served by agentindex serve. Lists every endpoint with its parameters, the search response shape, errors, and curl examples.
tags: [interfaces, reference]
keywords: [rest, http, api, endpoints, curl, json, server, serve, port, search endpoint, web]
---

# HTTP API

`python3 -m agentindex serve` starts a JSON API on `http://127.0.0.1:8765` (change it with
`--host` and `--port`). It suits agents and tools that prefer HTTP over the CLI or MCP.
There is no authentication, so keep it on localhost unless the knowledge is public. Code:
[http_api.py](../../agentindex/http_api.py).

## Endpoints

| Endpoint | Returns |
|---|---|
| `GET /search?q=<terms>&limit=8&tag=<tag>` | Ranked results. `tag` may be repeated. |
| `GET /docs?tag=<tag>` | Every doc (id, title, path, summary, tags, words), plus tag counts. |
| `GET /docs/<id>` | One doc: metadata, `content`, `outline`, `links`, `backlinks` and the starting `line`. |
| `GET /docs/<id>?section=<anchor>` | One section; `section` in the response holds its heading. `/docs/<id>%23<anchor>` also works. |
| `GET /docs/<id>?format=text` | The doc as agent-readable text (`text/markdown`), exactly as the CLI prints it. |
| `GET /docs/<id>?outline=1` | The doc's headings with levels, anchors and word counts. |
| `GET /status` | Configuration and counts. |
| `POST /sync` | Re-scan the sources now, and return the ids added, updated and removed. |
| `GET /health` | `{"status": "ok", ...}` |
| `GET /` | The list of endpoints. |

The sources are re-scanned at most once per second, so doc edits show up without a restart.

## Search response

```json
{
  "query": "roll back a deploy",
  "total": 3,
  "indexed": 14,
  "results": [
    {
      "id": "ops/deploying",
      "title": "Deploying to production",
      "path": "knowledge/ops/deploying.md",
      "summary": "How releases reach production and how to undo one.",
      "tags": ["deploy", "ops"],
      "words": 412,
      "score": 10.0,
      "sections": [
        {
          "heading": "Rollback",
          "anchor": "rollback",
          "snippet": "If a release breaks, **roll back** the **deploy** with..."
        }
      ]
    }
  ]
}
```

`total` counts every matching doc, and `results` holds the top `limit` (at most 50).
`score` is only meaningful for comparing results of the same query.

## Errors

Errors are JSON objects with an `error` message. The status is `400` for a missing or
unusable query or a bad parameter, `404` for an unknown doc, section or endpoint (with
`suggestions` when there are close matches), `405` for the wrong method, and `500` for
anything unexpected.

## Examples

```bash
curl -s 'localhost:8765/search?q=configuration&limit=3'
curl -s 'localhost:8765/docs/architecture/overview?format=text'
curl -s 'localhost:8765/docs/architecture/database?section=sync'
curl -s -X POST localhost:8765/sync
```
