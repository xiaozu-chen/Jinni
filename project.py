import re
import shutil
import os
import subprocess
import json
from pathlib import Path

SKIP_COPY_DIRS = {
    ".git", ".jinni", ".pytest_cache", ".trash", ".venv", "__pycache__", "node_modules",
    "venv", "workspace",
}
MAX_GUIDANCE_BYTES = 32_000
PROJECT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
CHECKPOINTED_WRITES = {
    "write_file", "edit_file", "apply_patch", "delete_file", "make_chart", "fetch_table",
    "search_snippets_for_chart",
}


def _ignore_generated(directory: str, names: list[str]) -> set[str]:
    base = Path(directory)
    return {
        name for name in names
        if name in SKIP_COPY_DIRS or os.path.islink(base / name)
    }


def _git_environment() -> dict[str, str]:
    return {
        key: value for key, value in os.environ.items()
        if not key.startswith("GIT_")
    } | {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}


def _initialize_project(path: Path, projects_dir: Path) -> None:
    template = projects_dir.parent / ".jinni" / "git-template"
    template.mkdir(parents=True, exist_ok=True)
    control = path / ".jinni"
    control.mkdir(exist_ok=True)
    (control / "managed-project").write_text("Jinni-managed project\n", encoding="utf-8")

    try:
        subprocess.run(
            ["git", "init", "--quiet", f"--template={template}"], cwd=path,
            env=_git_environment(), check=True, capture_output=True, text=True,
        )
        no_hooks = path / ".git" / "no-hooks"
        no_hooks.mkdir()
        subprocess.run(
            ["git", "config", "core.hooksPath", ".git/no-hooks"], cwd=path,
            env=_git_environment(), check=True, capture_output=True, text=True,
        )
        subprocess.run(
            ["git", "config", "commit.gpgsign", "false"], cwd=path,
            env=_git_environment(), check=True, capture_output=True, text=True,
        )
        exclude = path / ".git" / "info" / "exclude"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        with exclude.open("a", encoding="utf-8") as stream:
            stream.write("\n.jinni/\n")
    except (OSError, subprocess.CalledProcessError) as error:
        raise ValueError(f"could not initialize the project repository ({type(error).__name__})") from None


def checkpoint_before_write(tool_name: str, project_path: str | Path) -> str | None:
    if tool_name not in CHECKPOINTED_WRITES:
        return None
    root = Path(project_path).expanduser().resolve()
    if not (root / ".jinni" / "managed-project").is_file() or not (root / ".git").is_dir():
        return None
    environment = _git_environment()
    try:
        subprocess.run(["git", "add", "--all"], cwd=root, env=environment, check=True,
                       capture_output=True, text=True)
        subprocess.run(
            ["git", "-c", "user.name=Jinni", "-c", "user.email=jinni@localhost",
             "commit", "--quiet", "--allow-empty", "-m", f"Checkpoint before {tool_name}"],
            cwd=root, env=environment, check=True, capture_output=True, text=True,
        )
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, env=environment, check=True,
            capture_output=True, text=True,
        ).stdout.strip()
        marker = root / ".jinni" / "last-checkpoint.json"
        temporary = marker.with_suffix(".tmp")
        temporary.write_text(json.dumps({"commit": commit, "tool": tool_name}), encoding="utf-8")
        os.replace(temporary, marker)
        return commit
    except (OSError, subprocess.CalledProcessError):
        raise ValueError("could not save a Git checkpoint; the approved write was not run") from None


def undo_last_checkpoint(project_path: str | Path) -> bool:
    root = Path(project_path).expanduser().resolve()
    marker = root / ".jinni" / "last-checkpoint.json"
    if not marker.is_file() or not (root / ".git").is_dir():
        return False
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
        commit = data.get("commit")
        if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40,64}", commit):
            raise ValueError
        subprocess.run(
            ["git", "reset", "--hard", commit], cwd=root, env=_git_environment(),
            check=True, capture_output=True, text=True,
        )
        marker.unlink(missing_ok=True)
        return True
    except (OSError, ValueError, subprocess.CalledProcessError):
        raise ValueError("could not restore the latest Git checkpoint") from None


def list_projects(projects_dir: str | Path) -> list[Path]:
    root = Path(projects_dir).expanduser().resolve()
    if not root.is_dir():
        return []
    return sorted(
        (
            item for item in root.iterdir()
            if item.is_dir() and not item.is_symlink()
            and (item / ".jinni" / "managed-project").is_file()
            and (item / ".git").is_dir()
        ),
        key=lambda item: item.name.casefold(),
    )


def create_project(name: str, projects_dir: str | Path) -> Path:
    projects = Path(projects_dir).expanduser().resolve()
    if not PROJECT_NAME.fullmatch(name) or name in {".", ".."}:
        raise ValueError("project name must use 1 to 64 letters, numbers, dots, underscores, or hyphens")
    target = projects / name
    if target.exists():
        raise ValueError(f"a project named '{name}' already exists")
    projects.mkdir(parents=True, exist_ok=True)
    target.mkdir()
    try:
        _initialize_project(target, projects)
    except ValueError:
        shutil.rmtree(target, ignore_errors=True)
        raise
    return target.resolve()


def select_project(name: str, projects_dir: str | Path) -> Path:
    if not PROJECT_NAME.fullmatch(name) or name in {".", ".."}:
        raise ValueError("choose a project by its name from /project list")
    projects = Path(projects_dir).expanduser().resolve()
    target = projects / name
    if target.is_symlink() or not target.is_dir() or not target.resolve().is_relative_to(projects):
        raise ValueError(f"no managed project named '{name}'")
    if not (target / ".jinni" / "managed-project").is_file() or not (target / ".git").is_dir():
        raise ValueError(f"'{name}' is not a Jinni-managed project")
    return target.resolve()


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
        shutil.copytree(source, target, ignore=_ignore_generated)
        _initialize_project(target, projects)
    except (OSError, shutil.Error) as error:
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        raise ValueError(f"could not copy the project ({type(error).__name__})") from None
    except ValueError:
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        raise
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
