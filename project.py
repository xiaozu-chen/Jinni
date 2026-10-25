import re
import shutil
from pathlib import Path

SKIP_COPY_DIRS = {
    ".jinni", ".pytest_cache", ".trash", ".venv", "__pycache__", "node_modules",
    "venv", "workspace",
}
MAX_GUIDANCE_BYTES = 32_000


def _ignore_generated(_directory: str, names: list[str]) -> set[str]:
    return set(names) & SKIP_COPY_DIRS


def copy_project(source_path: str | Path, projects_dir: str | Path) -> Path:
    source = Path(source_path).expanduser().resolve()
    projects = Path(projects_dir).expanduser().resolve()
    if not source.is_dir():
        raise ValueError("the project path must be an existing directory")
    if projects == source or projects.is_relative_to(source):
        raise ValueError("the project copy folder cannot be inside the source project")

    name = re.sub(r"[^A-Za-z0-9._-]+", "-", source.name).strip(".-")[:80] or "project"
    target = projects / name
    if target.exists():
        raise ValueError(f"a copy named '{name}' already exists in the Jinni workspace")

    projects.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(source, target, symlinks=True, ignore=_ignore_generated)
    except (OSError, shutil.Error) as error:
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        raise ValueError(f"could not copy the project ({type(error).__name__})") from None
    return target.resolve()


def load_project_guidance(project_path: str | Path) -> str:
    root = Path(project_path).resolve()
    guidance = root / "JINNI.md"
    if not guidance.exists():
        return ""
    if guidance.is_symlink() or guidance.stat().st_size > MAX_GUIDANCE_BYTES:
        raise ValueError("JINNI.md must be a regular file no larger than 32 KB")
    try:
        return guidance.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as error:
        raise ValueError(f"could not read JINNI.md ({type(error).__name__})") from None
