from pathlib import Path

# server
BASE_URL = "http://localhost:8080/v1"
MODEL = "qwen3"

# agent
SYSTEM_PROMPT = "You are Jinni, a helpful local AI agent. Keep answers concise."
MAX_STEPS = 8

# context management
CONTEXT_LIMIT = 16384
COMPACT_AT = 0.7
KEEP_RECENT = 3
SUMMARIZE_AT = 0.8
KEEP_TURNS = 2

# files
MEMORY_FILE = Path("memory.txt")

# terminal colors
GRAY = "\033[90m"
RESET = "\033[0m"