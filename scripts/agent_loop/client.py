import json
import time
import urllib.error
import urllib.request

from agent_loop.config import BASE, CLIENT_IP, MODEL, THINK, _required, key
from agent_loop.reporting import TOTALS


def call(messages, tools=None, model=MODEL, think=THINK, timeout=900):
    payload = {"model": model, "messages": messages, "stream": False}
    if tools:
        payload["tools"] = tools
    if think is not None:
        payload["think"] = think
    request = urllib.request.Request(
        BASE,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {key()}",
            "Content-Type": "application/json",
            "X-Nexus-Proxy": _required(
                "NEXUS_PROXY_SECRET", "proxy_shared_secret", "the trusted-proxy secret"
            ),
            "X-Forwarded-For": CLIENT_IP,
        },
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.load(response)
    except urllib.error.HTTPError as exc:
        print(f"  HTTP {exc.code}: {exc.read().decode()[:400]}")
        raise
    elapsed = time.monotonic() - started
    usage = body.get("usage") or {}
    TOTALS["turns"] += 1
    TOTALS["seconds"] += elapsed
    TOTALS["prompt"] += usage.get("prompt_tokens") or 0
    TOTALS["completion"] += usage.get("completion_tokens") or 0
    return body, elapsed
