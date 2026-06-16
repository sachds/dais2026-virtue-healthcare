"""Thin client for the Databricks-served LLM (GPT-5.5) used by the Referral Copilot.
Local dev authenticates via DBX_PROFILE; deployed, via the app's ambient service principal."""
from __future__ import annotations

import json
import os
import threading

# Live copilot uses a FAST model (extraction keeps GPT-5.5 for quality, offline).
ENDPOINT = os.environ.get("COPILOT_MODEL", "databricks-claude-haiku-4-5")
_w = None
_lock = threading.Lock()  # serialize serving calls; the SDK client isn't concurrency-safe


def _client():
    global _w
    if _w is None:
        from databricks.sdk import WorkspaceClient
        host, tok = os.environ.get("DATABRICKS_HOST"), os.environ.get("DATABRICKS_TOKEN")
        prof = os.environ.get("DBX_PROFILE")
        if host and tok:          # explicit static token — robust local auth, no CLI refresh
            _w = WorkspaceClient(host=host, token=tok)
        elif prof:
            _w = WorkspaceClient(profile=prof)
        else:                      # deployed: app's ambient service principal
            _w = WorkspaceClient()
    return _w


def chat(messages: list[dict], max_tokens: int = 1200) -> str:
    from databricks.sdk.service.serving import ChatMessage, ChatMessageRole
    roles = {"system": ChatMessageRole.SYSTEM, "user": ChatMessageRole.USER,
             "assistant": ChatMessageRole.ASSISTANT}
    with _lock:
        resp = _client().serving_endpoints.query(
            name=ENDPOINT, max_tokens=max_tokens,
            messages=[ChatMessage(role=roles[m["role"]], content=m["content"]) for m in messages],
        )
    return resp.choices[0].message.content.strip()


def chat_json(messages: list[dict], max_tokens: int = 1200) -> dict:
    txt = chat(messages, max_tokens)
    if txt.startswith("```"):
        txt = txt.split("```", 2)[1].removeprefix("json").strip()
    try:
        return json.loads(txt)
    except Exception:
        import re  # tolerate prose around the JSON
        m = re.search(r"\{.*\}", txt, re.S)
        if m:
            return json.loads(m.group(0))
        raise
