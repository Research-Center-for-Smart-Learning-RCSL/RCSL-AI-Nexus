TOTALS = {"turns": 0, "seconds": 0.0, "prompt": 0, "completion": 0}

def report(body, elapsed, label=""):
    choice = body["choices"][0]
    message = choice["message"]
    calls = message.get("tool_calls") or []
    usage = body.get("usage") or {}
    print(
        f"  {label}[{body.get('model')}] "
        f"finish_reason = {choice.get('finish_reason')!r}   {elapsed:.1f}s"
    )
    print(
        f"  tokens: prompt={usage.get('prompt_tokens')} "
        f"completion={usage.get('completion_tokens')}"
    )
    if calls:
        for c in calls:
            fn = c["function"]
            print(f"  CALL  {fn['name']}({fn['arguments']})   id={c['id']}")
    content = (message.get("content") or "").strip()
    if content:
        print(f"  TEXT  {content[:300]}")
    return message, calls
