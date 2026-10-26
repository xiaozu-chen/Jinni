from __future__ import annotations

from typing import Any

MAX_PATCHES = 20


def apply_exact_patches(source: str, patches: Any) -> str:
    if not isinstance(patches, list) or not patches or len(patches) > MAX_PATCHES:
        raise ValueError(f"patches must contain 1 to {MAX_PATCHES} replacements")

    replacements = []
    seen = set()
    for patch in patches:
        if not isinstance(patch, dict) or set(patch) != {"old_text", "new_text"}:
            raise ValueError("each patch needs exactly old_text and new_text")
        old_text, new_text = patch["old_text"], patch["new_text"]
        if not isinstance(old_text, str) or not old_text or not isinstance(new_text, str):
            raise ValueError("old_text must be non-empty and new_text must be text")
        if old_text in seen:
            raise ValueError("each patch must target different source text")
        seen.add(old_text)
        start = source.find(old_text)
        if start < 0:
            raise ValueError("old_text was not found")
        if source.find(old_text, start + 1) >= 0:
            raise ValueError("old_text must match exactly once")
        replacements.append((start, start + len(old_text), new_text))

    replacements.sort(key=lambda item: item[0])
    if any(left[1] > right[0] for left, right in zip(replacements, replacements[1:])):
        raise ValueError("patch source ranges overlap")

    pieces = []
    cursor = 0
    for start, end, new_text in replacements:
        pieces.extend((source[cursor:start], new_text))
        cursor = end
    pieces.append(source[cursor:])
    return "".join(pieces)
