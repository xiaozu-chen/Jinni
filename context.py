from config import KEEP_RECENT

def compact(messages):
    tool_idxs = [i for i, m in enumerate(messages) if m["role"] == "tool"]
    old = tool_idxs[:-KEEP_RECENT]
    shrunk = 0
    for i in old:
        text = messages[i]["content"]
        if len(text) > 200:
            messages[i]["content"] = text[:150] + "  ...[trimemd to save context]"
            shrunk += 1
    return shrunk


def to_transcript(msgs):
    lines = []
    for m in msgs:
        if m["role"] == "user":
            lines.append(f"User: {m['content']}")
        elif m["role"] == "assistant":
            if m.get("content"):
                lines.append(f"Jinni: {m['content']}")
            for tc in m.get("tool_calls", []):
                f = tc["function"]
                lines.append(f"Jinni used {f['name']}({f['arguments'][:200]})")
        elif m["role"] == "tool":
            lines.append(f"Tool result: {m['content'][:300]}")
    return "\n".join(lines)