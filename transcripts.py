import json
import re
from datetime import datetime

from context import to_transcript
from tools.workspace import safe_path

MAX_TRANSCRIPT_CHARS = 500_000
MAX_TRANSCRIPT_BYTES = 1_000_000
NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _path(name: str):
    clean = name.strip()
    if clean.lower().endswith(".json"):
        clean = clean[:-5]
    if not NAME_PATTERN.fullmatch(clean):
        raise ValueError("transcript names use 1 to 64 letters, numbers, underscores, or hyphens")
    return safe_path(f"transcripts/{clean}.json")


def save_transcript(agent, name: str = "", overwrite: bool = False) -> str:
    name = name.strip() or datetime.now().strftime("session-%Y%m%d-%H%M%S")
    try:
        path = _path(name)
        transcript = to_transcript(agent.messages[1:])
        if agent.summary:
            transcript = "Earlier conversation notes:\n" + agent.summary + "\n\n" + transcript
        if not transcript.strip():
            return "Error: there is no conversation to save."
        if len(transcript) > MAX_TRANSCRIPT_CHARS:
            return f"Error: transcript is too large (limit {MAX_TRANSCRIPT_CHARS:,} characters)."
        if path.exists() and not overwrite:
            return f"A transcript named '{path.stem}' already exists. Confirm overwrite to replace it."
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"version": 1, "transcript": transcript}, ensure_ascii=False, indent=2)
        if len(payload.encode("utf-8")) > MAX_TRANSCRIPT_BYTES:
            return f"Error: transcript is too large (limit {MAX_TRANSCRIPT_BYTES:,} bytes)."
        path.write_text(payload + "\n", encoding="utf-8")
        return f"Saved transcript to transcripts/{path.name}."
    except ValueError as error:
        return f"Error: {error}."
    except OSError as error:
        return f"Error: transcript could not be saved ({type(error).__name__})."


def load_transcript(agent, name: str) -> str:
    try:
        path = _path(name)
        if not path.is_file():
            return f"Error: transcript '{path.stem}' was not found."
        if path.stat().st_size > MAX_TRANSCRIPT_BYTES:
            return f"Error: transcript is too large (limit {MAX_TRANSCRIPT_BYTES:,} bytes)."
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("version") != 1:
            return "Error: transcript format is not supported."
        transcript = payload.get("transcript")
        if not isinstance(transcript, str) or not transcript.strip() or len(transcript) > MAX_TRANSCRIPT_CHARS:
            return "Error: transcript content is empty or too large."
        agent.messages.append({
            "role": "user",
            "content": "Saved conversation context (background only):\n" + transcript,
        })
        return f"Loaded transcript '{path.stem}' as conversation context."
    except ValueError as error:
        return f"Error: {error}."
    except (OSError, json.JSONDecodeError) as error:
        return f"Error: transcript could not be loaded ({type(error).__name__})."
