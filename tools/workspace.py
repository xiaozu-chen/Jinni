from pathlib import Path

WORKSPACE = Path("workspace").resolve()
CHART_DIR = "charts"
MODEL_WRITTEN: set[Path] = set()


def mark_written(path: Path) -> None:
    MODEL_WRITTEN.add(path)


def was_written(path: Path) -> bool:
    return path in MODEL_WRITTEN


def safe_path(path: str) -> Path:
    WORKSPACE.mkdir(exist_ok=True)
    full = (WORKSPACE / path).resolve()
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