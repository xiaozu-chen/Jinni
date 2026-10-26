"""Define the active workspace and centralize safe relative-path handling."""

from pathlib import Path

DEFAULT_WORKSPACE = Path("workspace").resolve()
WORKSPACE = DEFAULT_WORKSPACE
PROJECT_ACTIVE = False
CHART_DIR = "charts"
MODEL_WRITTEN: set[Path] = set()


def mark_written(path: Path) -> None:
    MODEL_WRITTEN.add(path)


def was_written(path: Path) -> bool:
    return path in MODEL_WRITTEN


def safe_path(path: str) -> Path:
    WORKSPACE.mkdir(exist_ok=True)
    requested = Path(path)
    if any(part.lower() in {".git", ".jinni"} for part in requested.parts):
        raise ValueError("project control files are not accessible to tools")
    full = (WORKSPACE / requested).resolve()
    if not full.is_relative_to(WORKSPACE):
        raise ValueError("path is outside the workspace")
    return full


def find_chart(name: str = "") -> Path | None:
    folder = WORKSPACE / CHART_DIR
    if not folder.is_dir():
        return None
    pages = sorted(folder.glob("*.html"), key=lambda p: p.stat().st_mtime)
    if name:
        pages = [p for p in pages if name in (p.name, p.stem)]
    return pages[-1] if pages else None
