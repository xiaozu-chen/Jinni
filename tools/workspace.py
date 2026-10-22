from pathlib import Path

WORKSPACE = Path("workspace").resolve()


def safe_path(path: str) -> Path:
    WORKSPACE.mkdir(exist_ok=True)
    full = (WORKSPACE / path).resolve()
    if not full.is_relative_to(WORKSPACE):
        raise ValueError("path is outside the workspace")
    return full