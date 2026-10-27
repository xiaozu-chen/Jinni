from pathlib import Path
import tempfile

import pytest

from runtime.project import (
    apply_project_changes, checkpoint_before_write, copy_project, create_project,
    list_projects, load_project_guidance, project_changes, select_project,
    undo_last_checkpoint,
)


@pytest.fixture
def project_tmp_path():
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
        yield Path(folder)


def test_project_copy_keeps_original_and_skips_generated_data(project_tmp_path):
    source = project_tmp_path / "source repo"
    source.mkdir()
    (source / "app.py").write_text("print('source')", encoding="utf-8")
    (source / ".git").mkdir()
    (source / ".git" / "config").write_text("source repository", encoding="utf-8")
    (source / "venv").mkdir()
    (source / "venv" / "large.cache").write_text("skip", encoding="utf-8")
    projects_dir = project_tmp_path / "workspace" / "projects"

    copied = copy_project(source, projects_dir)
    (copied / "app.py").write_text("print('copy')", encoding="utf-8")

    assert copied == projects_dir / "source-repo"
    assert (source / "app.py").read_text(encoding="utf-8") == "print('source')"
    assert not (copied / "venv").exists()
    assert (copied / ".git").is_dir()
    assert (copied / ".git" / "config").read_text(encoding="utf-8") != "source repository"
    assert (copied / ".git" / "HEAD").exists()
    assert list_projects(projects_dir) == [copied]
    assert select_project("source-repo", projects_dir) == copied


def test_managed_project_can_be_created_listed_and_selected(project_tmp_path):
    projects = project_tmp_path / "workspace" / "projects"
    created = create_project("new-project", projects)

    assert (created / ".git").is_dir()
    assert list_projects(projects) == [created]
    assert select_project("new-project", projects) == created

    with pytest.raises(ValueError, match="already exists"):
        create_project("new-project", projects)
    with pytest.raises(ValueError, match="project name"):
        create_project("../escape", projects)


def test_git_checkpoint_restores_files_to_the_pre_write_snapshot(project_tmp_path):
    project = create_project("checkpoint", project_tmp_path / "workspace" / "projects")
    note = project / "note.txt"
    note.write_text("before", encoding="utf-8")

    checkpoint = checkpoint_before_write("write_file", project)
    note.write_text("after", encoding="utf-8")

    assert checkpoint
    assert undo_last_checkpoint(project)
    assert note.read_text(encoding="utf-8") == "before"
    assert not undo_last_checkpoint(project)


def test_project_copy_skips_symlinks_to_keep_original_out_of_reach(project_tmp_path):
    source = project_tmp_path / "source"
    source.mkdir()
    outside = project_tmp_path / "outside.txt"
    outside.write_text("original", encoding="utf-8")
    try:
        (source / "linked.txt").symlink_to(outside)
    except OSError:
        pytest.skip("symbolic links are unavailable")

    copied = copy_project(source, project_tmp_path / "workspace" / "projects")

    assert not (copied / "linked.txt").exists()
    assert outside.read_text(encoding="utf-8") == "original"


def test_changes_review_and_apply_uses_baseline_and_advances_it(project_tmp_path):
    source = project_tmp_path / "source"
    source.mkdir()
    (source / ".gitignore").write_text("local.env\n", encoding="utf-8")
    (source / "app.py").write_text("before\n", encoding="utf-8")
    (source / "local.env").write_text("secret=original\n", encoding="utf-8")
    (source / "remove.txt").write_text("remove me\n", encoding="utf-8")
    working = copy_project(source, project_tmp_path / "workspace" / "projects")

    assert project_changes(working)["files"] == []
    (working / "app.py").write_text("after\n", encoding="utf-8")
    (working / "local.env").write_text("secret=updated\n", encoding="utf-8")
    (working / "new.py").write_text("print('new')\n", encoding="utf-8")
    (working / "remove.txt").unlink()

    review = project_changes(working)
    assert review["files"] == ["app.py", "local.env", "new.py", "remove.txt"]
    assert len(review["snapshot_id"]) == 64
    assert "secret=updated" not in (source / "local.env").read_text(encoding="utf-8")
    result = apply_project_changes(working, source, expected_snapshot_id=review["snapshot_id"])

    assert result["applied"] == ["app.py", "local.env", "new.py", "remove.txt"]
    assert result["conflicts"] == []
    assert (source / "app.py").read_text(encoding="utf-8") == "after\n"
    assert (source / "local.env").read_text(encoding="utf-8") == "secret=updated\n"
    assert (source / "new.py").read_text(encoding="utf-8") == "print('new')\n"
    assert not (source / "remove.txt").exists()
    assert project_changes(working)["files"] == []

    (working / "app.py").write_text("second change\n", encoding="utf-8")
    assert apply_project_changes(working, source)["applied"] == ["app.py"]
    assert (source / "app.py").read_text(encoding="utf-8") == "second change\n"


def test_apply_rejects_changes_since_review(project_tmp_path):
    source = project_tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("before\n", encoding="utf-8")
    working = copy_project(source, project_tmp_path / "workspace" / "projects")
    (working / "app.py").write_text("reviewed\n", encoding="utf-8")
    snapshot_id = project_changes(working)["snapshot_id"]
    (working / "app.py").write_text("changed after review\n", encoding="utf-8")

    with pytest.raises(ValueError, match="changed after review"):
        apply_project_changes(working, source, expected_snapshot_id=snapshot_id)

    assert (source / "app.py").read_text(encoding="utf-8") == "before\n"


def test_apply_rejects_working_copy_change_during_transaction(project_tmp_path, monkeypatch):
    import runtime.project as project_module

    source = project_tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("before\n", encoding="utf-8")
    working = copy_project(source, project_tmp_path / "workspace" / "projects")
    working_file = working / "app.py"
    working_file.write_text("reviewed\n", encoding="utf-8")

    read_project_file = project_module._read_project_file
    changed = False

    def change_working_copy_when_source_is_checked(target):
        nonlocal changed
        if target == source / "app.py" and not changed:
            changed = True
            working_file.write_text("edited during apply\n", encoding="utf-8")
        return read_project_file(target)

    monkeypatch.setattr(project_module, "_read_project_file", change_working_copy_when_source_is_checked)

    with pytest.raises(ValueError, match="changed in the working copy while applying"):
        apply_project_changes(working, source)

    assert (source / "app.py").read_text(encoding="utf-8") == "before\n"


def test_apply_project_changes_blocks_all_files_when_source_conflicts(project_tmp_path):
    source = project_tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("imported\n", encoding="utf-8")
    working = copy_project(source, project_tmp_path / "workspace" / "projects")
    (working / "app.py").write_text("agent version\n", encoding="utf-8")
    (working / "new.py").write_text("agent addition\n", encoding="utf-8")
    (source / "app.py").write_text("user version\n", encoding="utf-8")

    result = apply_project_changes(working, source)

    assert result["applied"] == []
    assert result["conflicts"] == ["app.py"]
    assert (source / "app.py").read_text(encoding="utf-8") == "user version\n"
    assert not (source / "new.py").exists()


def test_project_copy_refuses_an_existing_name_and_recursive_destination(project_tmp_path):
    source = project_tmp_path / "project"
    source.mkdir()
    projects_dir = project_tmp_path / "workspace" / "projects"
    copy_project(source, projects_dir)

    with pytest.raises(ValueError, match="already exists"):
        copy_project(source, projects_dir)
    with pytest.raises(ValueError, match="inside the source"):
        copy_project(project_tmp_path, project_tmp_path / "projects")


def test_project_guidance_is_loaded_and_size_limited(tmp_path):
    (tmp_path / "JINNI.md").write_text("Use the existing formatter.", encoding="utf-8")

    assert load_project_guidance(tmp_path) == "Use the existing formatter."

    (tmp_path / "JINNI.md").write_text("x" * 32_001, encoding="utf-8")
    with pytest.raises(ValueError, match="32 KB"):
        load_project_guidance(tmp_path)


def test_agent_context_appends_project_guidance(memory_store):
    from runtime.agent import Agent

    agent = Agent(project_guidance="Use the project's existing formatter.")

    assert "Project guidance from JINNI.md" in agent.messages[0]["content"]
    assert "Use the project's existing formatter." in agent.messages[0]["content"]
