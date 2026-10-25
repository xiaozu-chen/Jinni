from pathlib import Path

import pytest

from project import copy_project, load_project_guidance


def test_project_copy_keeps_original_and_skips_generated_data(tmp_path):
    source = tmp_path / "source repo"
    source.mkdir()
    (source / "app.py").write_text("print('source')", encoding="utf-8")
    (source / "venv").mkdir()
    (source / "venv" / "large.cache").write_text("skip", encoding="utf-8")
    projects_dir = tmp_path / "workspace" / "projects"

    copied = copy_project(source, projects_dir)
    (copied / "app.py").write_text("print('copy')", encoding="utf-8")

    assert copied == projects_dir / "source-repo"
    assert (source / "app.py").read_text(encoding="utf-8") == "print('source')"
    assert not (copied / "venv").exists()


def test_project_copy_refuses_an_existing_name_and_recursive_destination(tmp_path):
    source = tmp_path / "project"
    source.mkdir()
    projects_dir = tmp_path / "workspace" / "projects"
    copy_project(source, projects_dir)

    with pytest.raises(ValueError, match="already exists"):
        copy_project(source, projects_dir)
    with pytest.raises(ValueError, match="inside the source"):
        copy_project(tmp_path, tmp_path / "projects")


def test_project_guidance_is_loaded_and_size_limited(tmp_path):
    (tmp_path / "JINNI.md").write_text("Use the existing formatter.", encoding="utf-8")

    assert load_project_guidance(tmp_path) == "Use the existing formatter."

    (tmp_path / "JINNI.md").write_text("x" * 32_001, encoding="utf-8")
    with pytest.raises(ValueError, match="32 KB"):
        load_project_guidance(tmp_path)


def test_agent_context_appends_project_guidance(memory_store):
    from agent import Agent

    agent = Agent(project_guidance="Use the project's existing formatter.")

    assert "Project guidance from JINNI.md" in agent.messages[0]["content"]
    assert "Use the project's existing formatter." in agent.messages[0]["content"]
