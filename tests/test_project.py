from pathlib import Path
import tempfile

import pytest

from runtime.project import (
    checkpoint_before_write, copy_project, create_project, list_projects,
    load_project_guidance, select_project, undo_last_checkpoint,
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
