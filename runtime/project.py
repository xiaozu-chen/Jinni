"""Manage project checkpoints and legacy isolated-project utilities."""

import difflib
import base64
import binascii
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

SKIP_COPY_DIRS = {
    ".git", ".jinni", ".pytest_cache", ".trash", ".venv", "__pycache__", "node_modules",
    "venv", "workspace",
}
MAX_GUIDANCE_BYTES = 32_000
MAX_REVIEW_FILES = 500
MAX_REVIEW_FILE_BYTES = 1_000_000
MAX_REVIEW_DIFF_CHARS = 200_000
MAX_APPLY_TOTAL_BYTES = 100_000_000
MAX_AUTO_EDIT_CHECKPOINTS = 20
MAX_AUTO_EDIT_FILE_BYTES = 2_000_000
PROJECT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
CHECKPOINTED_WRITES = {
    "write_file", "edit_file", "apply_patch", "delete_file", "make_chart", "fetch_table",
    "search_snippets_for_chart", "run_powershell",
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


def is_managed_project(project_path: str | Path) -> bool:
    """Return whether a folder supports Jinni's managed-project checkpoints."""
    root = Path(project_path).expanduser().resolve()
    control = root / ".jinni"
    marker = control / "managed-project"
    git_dir = root / ".git"
    return (
        root.is_dir()
        and not control.is_symlink()
        and not marker.is_symlink()
        and marker.is_file()
        and not git_dir.is_symlink()
        and git_dir.is_dir()
    )


def _stage_project_snapshot(root: Path, environment: dict[str, str]) -> None:
    subprocess.run(
        ["git", "add", "--all", "--force", "--", ".", ":(exclude).jinni"],
        cwd=root, env=environment, check=True, capture_output=True, text=True,
    )


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
        _stage_project_snapshot(path, _git_environment())
        subprocess.run(
            ["git", "-c", "user.name=Jinni", "-c", "user.email=jinni@localhost",
             "commit", "--quiet", "--allow-empty", "-m", "Imported project baseline"],
            cwd=path, env=_git_environment(), check=True, capture_output=True, text=True,
        )
        base_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=path, env=_git_environment(),
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        (control / "base-commit.json").write_text(
            json.dumps({"commit": base_commit}), encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ValueError(f"could not initialize the project repository ({type(error).__name__})") from None


def checkpoint_before_write(tool_name: str, project_path: str | Path) -> str | None:
    """Commit the current state before an approved write to give `/undo` a restore point."""
    if tool_name not in CHECKPOINTED_WRITES:
        return None
    root = Path(project_path).expanduser().resolve()
    if not is_managed_project(root):
        return None
    environment = _git_environment()
    try:
        _stage_project_snapshot(root, environment)
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


def _checkpoint_root(project_path: str | Path, *, create: bool = True) -> Path:
    root = Path(project_path).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("the active project folder is unavailable")
    storage = Path(__file__).resolve().parents[1] / "data" / "auto_edit_checkpoints"
    project_key = hashlib.sha256(os.path.normcase(str(root)).encode("utf-8")).hexdigest()
    folder = storage / project_key
    if create:
        storage.mkdir(parents=True, exist_ok=True)
        folder.mkdir(exist_ok=True)
    return folder


def _checkpoint_target(root: Path, relative_name: str) -> Path:
    relative = Path(relative_name)
    if (not relative_name or relative.is_absolute() or relative.drive or ".." in relative.parts
            or any(part.casefold() in {".git", ".jinni"} for part in relative.parts)):
        raise ValueError("Auto-edit can checkpoint only a file inside the active project")
    target = root / relative
    for index in range(1, len(relative.parts) + 1):
        if (root / Path(*relative.parts[:index])).is_symlink():
            raise ValueError("Auto-edit cannot checkpoint a path that follows a symbolic link")
    if not target.resolve().is_relative_to(root):
        raise ValueError("Auto-edit cannot checkpoint a path outside the active project")
    return target


def _checkpoint_file_state(target: Path, *, include_content: bool = True) -> dict[str, object]:
    if not target.exists():
        return {"exists": False, "sha256": None}
    if target.is_symlink() or not target.is_file():
        raise ValueError("Auto-edit checkpoints support regular files only")
    if target.stat().st_size > MAX_AUTO_EDIT_FILE_BYTES:
        raise ValueError("Auto-edit checkpoint files are limited to 2 MB")
    data = target.read_bytes()
    state: dict[str, object] = {
        "exists": True,
        "sha256": hashlib.sha256(data).hexdigest(),
        "mode": stat.S_IMODE(target.stat().st_mode),
    }
    if include_content:
        state["content"] = base64.b64encode(data).decode("ascii")
    return state


def begin_auto_edit_checkpoint(tool_name: str, project_path: str | Path, args: dict[str, object]) -> str:
    """Persist a backend-only before-image for one supported direct-folder file write."""
    if tool_name not in {"write_file", "edit_file", "apply_patch"}:
        raise ValueError("Auto-edit is limited to checkpointed file changes")
    root = Path(project_path).expanduser().resolve()
    name = args.get("path")
    if not isinstance(name, str):
        raise ValueError("the file path for this change is invalid")
    target = _checkpoint_target(root, name)
    before = _checkpoint_file_state(target)
    checkpoint_id = uuid4().hex
    folder = _checkpoint_root(root)
    record = {
        "id": checkpoint_id,
        "tool": tool_name,
        "path": target.relative_to(root).as_posix(),
        "before": before,
        "after": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (folder / f"{checkpoint_id}.json").write_text(json.dumps(record), encoding="utf-8")
    index_path = folder / "index.json"
    try:
        ids = json.loads(index_path.read_text(encoding="utf-8")) if index_path.is_file() else []
    except (OSError, json.JSONDecodeError):
        ids = []
    ids = [item for item in ids if isinstance(item, str) and item != checkpoint_id]
    ids.append(checkpoint_id)
    for old_id in ids[:-MAX_AUTO_EDIT_CHECKPOINTS]:
        if re.fullmatch(r"[0-9a-f]{32}", old_id):
            (folder / f"{old_id}.json").unlink(missing_ok=True)
    temporary = index_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(ids[-MAX_AUTO_EDIT_CHECKPOINTS:]), encoding="utf-8")
    os.replace(temporary, index_path)
    return checkpoint_id


def finish_auto_edit_checkpoint(checkpoint_id: str, project_path: str | Path) -> None:
    root = Path(project_path).expanduser().resolve()
    folder = _checkpoint_root(root)
    if not re.fullmatch(r"[0-9a-f]{32}", checkpoint_id):
        raise ValueError("the Auto-edit checkpoint is invalid")
    record_path = folder / f"{checkpoint_id}.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    target = _checkpoint_target(root, str(record.get("path", "")))
    record["after"] = _checkpoint_file_state(target, include_content=False)
    temporary = record_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(record), encoding="utf-8")
    os.replace(temporary, record_path)


def latest_auto_edit_checkpoint(project_path: str | Path) -> dict[str, object] | None:
    try:
        root = Path(project_path).expanduser().resolve()
        folder = _checkpoint_root(root, create=False)
    except (OSError, ValueError):
        return None
    index_path = folder / "index.json"
    if not index_path.is_file():
        return None
    try:
        ids = json.loads(index_path.read_text(encoding="utf-8"))
        for checkpoint_id in reversed(ids if isinstance(ids, list) else []):
            if not isinstance(checkpoint_id, str) or not re.fullmatch(r"[0-9a-f]{32}", checkpoint_id):
                continue
            record_path = folder / f"{checkpoint_id}.json"
            record = json.loads(record_path.read_text(encoding="utf-8"))
            if record.get("after") is None:
                continue
            return {"id": checkpoint_id, "path": record.get("path"), "tool": record.get("tool")}
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return None


def restore_auto_edit_checkpoint(project_path: str | Path, checkpoint_id: str) -> dict[str, object]:
    """Restore one file only when it still matches the state Jinni wrote."""
    root = Path(project_path).expanduser().resolve()
    folder = _checkpoint_root(root)
    if not re.fullmatch(r"[0-9a-f]{32}", checkpoint_id):
        raise ValueError("the Auto-edit checkpoint is invalid")
    record_path = folder / f"{checkpoint_id}.json"
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
        target = _checkpoint_target(root, str(record.get("path", "")))
        before, after = record.get("before"), record.get("after")
        if not isinstance(before, dict) or not isinstance(after, dict):
            raise ValueError
        current = _checkpoint_file_state(target, include_content=False)
        if any(current.get(key) != after.get(key) for key in ("exists", "sha256", "mode")):
            raise ValueError("the file changed after Jinni edited it; restore was cancelled to protect newer work")
        target.parent.mkdir(parents=True, exist_ok=True)
        if before.get("exists"):
            content = base64.b64decode(str(before.get("content", "")), validate=True)
            if hashlib.sha256(content).hexdigest() != before.get("sha256"):
                raise ValueError
            _write_atomic(target, content, int(before.get("mode", 0o644)))
        elif target.exists():
            target.unlink()
        record_path.unlink(missing_ok=True)
        return {"restored": True, "path": record.get("path")}
    except ValueError:
        raise
    except (OSError, KeyError, TypeError, binascii.Error, json.JSONDecodeError):
        raise ValueError("could not restore the Auto-edit checkpoint") from None


def undo_last_checkpoint(project_path: str | Path) -> bool:
    root = Path(project_path).expanduser().resolve()
    marker = root / ".jinni" / "last-checkpoint.json"
    if marker.is_symlink() or not marker.is_file() or not is_managed_project(root):
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


def project_changes(project_path: str | Path) -> dict[str, object]:
    """Return a bounded text diff from the managed project's imported baseline."""
    root = Path(project_path).expanduser().resolve()
    if not is_managed_project(root):
        raise ValueError("project changes are available only for a Jinni-managed project")
    marker = root / ".jinni" / "base-commit.json"
    if marker.is_symlink() or not marker.is_file() or marker.stat().st_size > 4096:
        raise ValueError("this project has no valid imported baseline; import it again to review changes")
    try:
        baseline = json.loads(marker.read_text(encoding="utf-8")).get("commit")
    except (OSError, UnicodeError, json.JSONDecodeError, AttributeError):
        raise ValueError("this project's imported baseline could not be read") from None
    if not isinstance(baseline, str) or not re.fullmatch(r"[0-9a-f]{40,64}", baseline):
        raise ValueError("this project's imported baseline is invalid")

    environment = _git_environment()
    try:
        subprocess.run(
            ["git", "cat-file", "-e", f"{baseline}^{{commit}}"], cwd=root,
            env=environment, check=True, capture_output=True, timeout=10,
        )
        tracked = subprocess.run(
            ["git", "diff", "--no-renames", "--name-only", "-z", baseline, "--"],
            cwd=root, env=environment, check=True, capture_output=True, timeout=10,
        ).stdout
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "-z"], cwd=root, env=environment,
            check=True, capture_output=True, timeout=10,
        ).stdout
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise ValueError("could not read the managed project's Git changes") from None

    ignored = SKIP_COPY_DIRS | {".git", ".jinni"}
    relative_paths: list[str] = []
    seen: set[str] = set()
    for raw_path in tracked.split(b"\0") + untracked.split(b"\0"):
        if not raw_path:
            continue
        name = os.fsdecode(raw_path)
        relative = Path(name)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or any(part.casefold() in ignored for part in relative.parts)
            or name in seen
        ):
            continue
        seen.add(name)
        relative_paths.append(name)
    relative_paths.sort()
    truncated = len(relative_paths) > MAX_REVIEW_FILES
    relative_paths = relative_paths[:MAX_REVIEW_FILES]
    changes: list[str] = []
    unsupported: list[str] = []
    mode_changes: list[str] = []
    total_chars = 0

    def show_base_file(name: str) -> tuple[bool, bytes | None]:
        object_name = f"{baseline}:{name}"
        try:
            size = subprocess.run(
                ["git", "cat-file", "-s", object_name], cwd=root, env=environment,
                capture_output=True, check=True, timeout=10,
            ).stdout.strip()
            if int(size) > MAX_REVIEW_FILE_BYTES:
                return True, None
            content = subprocess.run(
                ["git", "show", object_name], cwd=root, env=environment,
                capture_output=True, check=True, timeout=10,
            ).stdout
            return True, content
        except subprocess.CalledProcessError as error:
            if error.cmd[:3] == ["git", "cat-file", "-s"]:
                return False, b""
            raise ValueError("could not read a baseline file") from None
        except (OSError, subprocess.TimeoutExpired, ValueError):
            raise ValueError("could not read a baseline file") from None

    for name in relative_paths:
        relative = Path(name)
        target = root / relative
        parent_paths = (
            root / Path(*relative.parts[:index])
            for index in range(1, len(relative.parts) + 1)
        )
        if any(path.is_symlink() for path in parent_paths):
            unsupported.append(name)
            continue
        if target.exists() and (not target.is_file() or target.stat().st_size > MAX_REVIEW_FILE_BYTES):
            unsupported.append(name)
            continue
        try:
            old_exists, old_bytes = show_base_file(name)
            base_executable = _baseline_executable(root, environment, baseline, name)
            new_bytes = target.read_bytes() if target.exists() else b""
            target_executable = bool(
                target.exists()
                and target.is_file()
                and stat.S_IMODE(target.stat().st_mode) & 0o111
            )
        except (OSError, ValueError):
            unsupported.append(name)
            continue
        if target.exists() and bool(base_executable) != target_executable:
            mode_changes.append(name)
        if old_bytes is None or b"\0" in (old_bytes or b"") or b"\0" in new_bytes:
            unsupported.append(name)
            continue
        try:
            old_text = (old_bytes or b"").decode("utf-8")
            new_text = new_bytes.decode("utf-8")
        except UnicodeDecodeError:
            unsupported.append(name)
            continue
        old_label = f"a/{name}" if old_exists else "/dev/null"
        new_label = f"b/{name}" if target.exists() else "/dev/null"
        lines = list(difflib.unified_diff(
            old_text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile=old_label,
            tofile=new_label,
            n=3,
        ))
        normalized: list[str] = []
        for line in lines:
            if line.startswith((" ", "+", "-")) and not line.endswith(("\n", "\r")):
                normalized.extend((line + "\n", "\\ No newline at end of file\n"))
            else:
                normalized.append(line)
        fragment = "".join(normalized)
        if not fragment:
            continue
        remaining = MAX_REVIEW_DIFF_CHARS - total_chars
        if len(fragment) > remaining:
            changes.append(fragment[:max(0, remaining)])
            truncated = True
            break
        changes.append(fragment)
        total_chars += len(fragment)

    result = {
        "baseline": baseline,
        "files": relative_paths,
        "diff": "".join(changes),
        "unsupported_files": unsupported,
        "mode_changes": mode_changes,
        "truncated": truncated,
    }
    snapshot = json.dumps(result, sort_keys=True, separators=(",", ":"))
    result["snapshot_id"] = hashlib.sha256(snapshot.encode("utf-8")).hexdigest()
    return result


def _baseline_blob(root: Path, environment: dict[str, str], baseline: str, name: str) -> bytes | None:
    object_name = f"{baseline}:{name}"
    result = subprocess.run(
        ["git", "cat-file", "-s", object_name], cwd=root, env=environment,
        capture_output=True, timeout=10,
    )
    if result.returncode:
        return None
    size = int(result.stdout.strip())
    if size > MAX_REVIEW_FILE_BYTES:
        raise ValueError(f"{name} exceeds the safe apply size limit")
    return subprocess.run(
        ["git", "show", object_name], cwd=root, env=environment,
        capture_output=True, check=True, timeout=10,
    ).stdout


def _baseline_executable(root: Path, environment: dict[str, str], baseline: str, name: str) -> bool | None:
    result = subprocess.run(
        ["git", "ls-tree", "-z", baseline, "--", f":(literal){name}"], cwd=root, env=environment,
        capture_output=True, check=True, timeout=10,
    ).stdout
    if not result:
        return None
    try:
        metadata, path = result.rstrip(b"\0").split(b"\t", 1)
        mode, _object_type, _object_id = metadata.split(b" ", 2)
        if os.fsdecode(path) != name:
            raise ValueError
        return mode == b"100755"
    except ValueError:
        raise ValueError("could not read a baseline file mode") from None


def _project_file(root: Path, name: str) -> Path:
    relative = Path(name)
    if (
        relative.is_absolute()
        or relative.drive
        or ".." in relative.parts
        or any(part.casefold() in {".git", ".jinni"} for part in relative.parts)
    ):
        raise ValueError("a changed path is outside the editable project area")
    target = root / relative
    for index in range(1, len(relative.parts) + 1):
        if (root / Path(*relative.parts[:index])).is_symlink():
            raise ValueError("a changed path follows a symbolic link")
    if not target.resolve().is_relative_to(root):
        raise ValueError("a changed path is outside the editable project area")
    return target


def _read_project_file(target: Path) -> tuple[bytes | None, int | None]:
    if not target.exists():
        return None, None
    if target.is_symlink() or not target.is_file():
        raise ValueError("a changed path is not a regular file")
    info = target.stat()
    if info.st_size > MAX_REVIEW_FILE_BYTES:
        raise ValueError("a changed file exceeds the safe apply size limit")
    return target.read_bytes(), stat.S_IMODE(info.st_mode)


def _write_atomic(target: Path, content: bytes, mode: int | None) -> None:
    with tempfile.NamedTemporaryFile(mode="wb", dir=target.parent, prefix=".jinni-apply-", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        if mode is not None:
            os.chmod(temporary, mode)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _advance_project_baseline(root: Path) -> str:
    environment = _git_environment()
    try:
        _stage_project_snapshot(root, environment)
        subprocess.run(
            ["git", "-c", "user.name=Jinni", "-c", "user.email=jinni@localhost",
             "commit", "--quiet", "--allow-empty", "-m", "Applied reviewed changes to source"],
            cwd=root, env=environment, check=True, capture_output=True, timeout=30,
        )
        baseline = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, env=environment,
            check=True, capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        marker = root / ".jinni" / "base-commit.json"
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=marker.parent,
            prefix="base-commit.", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump({"commit": baseline}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        (root / ".jinni" / "last-checkpoint.json").unlink(missing_ok=True)
        os.replace(temporary, marker)
        return baseline
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise ValueError("source changes were applied, but the review baseline could not be advanced") from None
    finally:
        if "temporary" in locals():
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def apply_project_changes(
    project_path: str | Path,
    source_path: str | Path,
    *,
    expected_snapshot_id: str | None = None,
) -> dict[str, object]:
    """Apply reviewed text changes only where the source still matches the imported baseline."""
    working = Path(project_path).expanduser().resolve()
    source = Path(source_path).expanduser().resolve()
    if not is_managed_project(working):
        raise ValueError("changes can be applied only from a Jinni-managed project")
    if not source.is_dir() or source == working:
        raise ValueError("the original source folder is unavailable")
    review = project_changes(working)
    if expected_snapshot_id is not None and review.get("snapshot_id") != expected_snapshot_id:
        raise ValueError("the project changed after review; reload the diff before applying")
    names = review["files"]
    if not isinstance(names, list):
        raise ValueError("the project change list is invalid")
    if review["truncated"] or review["unsupported_files"]:
        raise ValueError("review contains unsupported or truncated changes; apply them manually")
    baseline = review["baseline"]
    if not isinstance(baseline, str):
        raise ValueError("the project baseline is invalid")

    environment = _git_environment()
    updates: list[dict[str, object]] = []
    conflicts: list[str] = []
    already_applied: list[str] = []
    total_bytes = 0
    for name in names:
        if not isinstance(name, str):
            continue
        try:
            base_content = _baseline_blob(working, environment, baseline, name)
            base_executable = _baseline_executable(working, environment, baseline, name)
            working_file = _project_file(working, name)
            source_file = _project_file(source, name)
            desired_content, desired_mode = _read_project_file(working_file)
            source_content, source_mode = _read_project_file(source_file)
        except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            conflicts.append(name)
            continue
        total_bytes += sum(len(content) for content in (base_content, desired_content, source_content) if content is not None)
        if total_bytes > MAX_APPLY_TOTAL_BYTES:
            raise ValueError("the combined changes exceed the safe apply size limit")
        desired_executable = bool(desired_mode and desired_mode & 0o111)
        source_executable = bool(source_mode and source_mode & 0o111)
        if source_content == desired_content and source_executable == desired_executable:
            already_applied.append(name)
            continue
        if source_content != base_content or source_executable != bool(base_executable):
            conflicts.append(name)
            continue
        after_mode = desired_mode
        if source_mode is not None and desired_mode is not None:
            after_mode = (source_mode & ~0o111) | (desired_mode & 0o111)
        updates.append({
            "name": name,
            "target": source_file,
            "working_target": working_file,
            "before": source_content,
            "before_mode": source_mode,
            "after": desired_content,
            "after_mode": after_mode,
            "working_mode": desired_mode,
        })

    if conflicts:
        return {"applied": [], "already_applied": already_applied, "conflicts": conflicts}
    if not updates and not already_applied:
        return {"applied": [], "already_applied": [], "conflicts": []}

    created_directories: list[Path] = []
    staged_files: dict[str, Path] = {}
    applied_updates: list[dict[str, object]] = []
    try:
        for update in updates:
            target = update["target"]
            assert isinstance(target, Path)
            missing: list[Path] = []
            parent = target.parent
            while parent != source and not parent.exists():
                missing.append(parent)
                parent = parent.parent
            if not parent.is_dir():
                raise ValueError("a target folder is no longer available")
            for directory in reversed(missing):
                directory.mkdir()
                created_directories.append(directory)
            after = update["after"]
            if isinstance(after, bytes):
                with tempfile.NamedTemporaryFile(
                    mode="wb", dir=target.parent, prefix=".jinni-apply-", delete=False,
                ) as stream:
                    temporary = Path(stream.name)
                    stream.write(after)
                    stream.flush()
                    os.fsync(stream.fileno())
                mode = update["after_mode"]
                if isinstance(mode, int):
                    os.chmod(temporary, mode)
                staged_files[str(update["name"])] = temporary

        for update in updates:
            name = str(update["name"])
            target = update["target"]
            working_target = update["working_target"]
            assert isinstance(target, Path)
            assert isinstance(working_target, Path)
            current, _ = _read_project_file(target)
            if current != update["before"]:
                raise ValueError(f"{name} changed while applying; no changes were kept")
            working_content, working_mode = _read_project_file(working_target)
            expected_working_mode = update["working_mode"]
            if working_content != update["after"] or working_mode != expected_working_mode:
                raise ValueError(f"{name} changed in the working copy while applying; no changes were kept")
            applied_updates.append(update)
            after = update["after"]
            if after is None:
                target.unlink(missing_ok=True)
            else:
                os.replace(staged_files[name], target)

        new_baseline = _advance_project_baseline(working)
        return {
            "applied": [str(update["name"]) for update in updates],
            "already_applied": already_applied,
            "conflicts": [],
            "baseline": new_baseline,
        }
    except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        rollback_failures: list[str] = []
        for update in reversed(applied_updates):
            target = update["target"]
            assert isinstance(target, Path)
            before = update["before"]
            name = str(update["name"])
            try:
                current, _ = _read_project_file(target)
                if current != update["after"]:
                    rollback_failures.append(name)
                    continue
                if before is None:
                    target.unlink(missing_ok=True)
                elif isinstance(before, bytes):
                    _write_atomic(target, before, update["before_mode"] if isinstance(update["before_mode"], int) else None)
            except (OSError, ValueError):
                rollback_failures.append(name)
        if rollback_failures:
            raise ValueError(
                f"{error}; could not restore these source files: {', '.join(rollback_failures)}"
            ) from None
        raise ValueError(str(error)) from None
    finally:
        for temporary in staged_files.values():
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        for directory in reversed(created_directories):
            try:
                directory.rmdir()
            except OSError:
                pass


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


def copy_project(
    source_path: str | Path,
    projects_dir: str | Path,
    *,
    project_name: str | None = None,
) -> Path:
    """Copy into managed storage while omitting generated content and all symlinks."""
    source = Path(source_path).expanduser().resolve()
    projects = Path(projects_dir).expanduser().resolve()
    if not source.is_dir():
        raise ValueError("the project path must be an existing directory")
    if projects == source or projects.is_relative_to(source):
        raise ValueError("the project copy folder cannot be inside the source project")

    name = project_name or re.sub(r"[^A-Za-z0-9._-]+", "-", source.name).strip("._-")[:64] or "project"
    if not PROJECT_NAME.fullmatch(name) or name in {".", ".."}:
        raise ValueError("project copy name must use 1 to 64 letters, numbers, dots, underscores, or hyphens")
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
