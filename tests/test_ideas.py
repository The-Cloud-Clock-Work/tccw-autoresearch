"""Tests for ideas backlog management."""

from pathlib import Path

import pytest

from autoresearch.ideas import (
    SECTIONS,
    append_idea,
    create_ideas_template,
    read_ideas,
)


class TestCreateTemplate:
    def test_creates_file(self, tmp_path):
        create_ideas_template(tmp_path, "my-marker")
        path = tmp_path / ".autoresearch" / "my-marker" / "ideas.md"
        assert path.is_file()
        content = path.read_text()
        assert "# Ideas Backlog -- my-marker" in content
        assert "## Discarded but Promising" in content
        assert "## Near-Misses" in content
        assert "## External Research" in content

    def test_idempotent(self, tmp_path):
        create_ideas_template(tmp_path, "my-marker")
        create_ideas_template(tmp_path, "my-marker")
        assert (tmp_path / ".autoresearch" / "my-marker" / "ideas.md").is_file()


class TestReadIdeas:
    def test_returns_empty_when_missing(self, tmp_path):
        assert read_ideas(tmp_path, "nonexistent") == ""

    def test_reads_existing(self, tmp_path):
        create_ideas_template(tmp_path, "test")
        content = read_ideas(tmp_path, "test")
        assert "Ideas Backlog" in content


class TestAppendIdea:
    def test_appends_to_discarded(self, tmp_path):
        append_idea(tmp_path, "test", "Discarded but Promising", "**Idea A** (exp #1)")
        content = read_ideas(tmp_path, "test")
        assert "- **Idea A** (exp #1)" in content

    def test_appends_to_near_misses(self, tmp_path):
        append_idea(tmp_path, "test", "Near-Misses", "**Idea B**")
        content = read_ideas(tmp_path, "test")
        assert "- **Idea B**" in content

    def test_appends_to_external_research(self, tmp_path):
        append_idea(tmp_path, "test", "External Research", "Found pattern: backoff with jitter")
        content = read_ideas(tmp_path, "test")
        assert "- Found pattern: backoff with jitter" in content

    def test_multiple_appends_preserve_order(self, tmp_path):
        append_idea(tmp_path, "test", "Discarded but Promising", "First idea")
        append_idea(tmp_path, "test", "Discarded but Promising", "Second idea")
        content = read_ideas(tmp_path, "test")
        first_pos = content.index("First idea")
        second_pos = content.index("Second idea")
        assert first_pos < second_pos

    def test_raises_on_invalid_section(self, tmp_path):
        with pytest.raises(ValueError, match="Unknown section"):
            append_idea(tmp_path, "test", "Nonexistent Section", "entry")

    def test_creates_template_if_missing(self, tmp_path):
        append_idea(tmp_path, "test", "Near-Misses", "auto-created")
        content = read_ideas(tmp_path, "test")
        assert "Ideas Backlog" in content
        assert "- auto-created" in content

    def test_section_header_in_sections_map(self):
        assert "Discarded but Promising" in SECTIONS
        assert "Near-Misses" in SECTIONS
        assert "External Research" in SECTIONS

    def test_all_three_sections_independently(self, tmp_path):
        append_idea(tmp_path, "all3", "Discarded but Promising", "D entry")
        append_idea(tmp_path, "all3", "Near-Misses", "N entry")
        append_idea(tmp_path, "all3", "External Research", "E entry")
        content = read_ideas(tmp_path, "all3")
        assert "- D entry" in content
        assert "- N entry" in content
        assert "- E entry" in content

    def test_append_to_external_research_last_section(self, tmp_path):
        """External Research is the last section — exercises end-of-file append path."""
        append_idea(tmp_path, "last", "External Research", "first external")
        append_idea(tmp_path, "last", "External Research", "second external")
        content = read_ideas(tmp_path, "last")
        assert content.index("first external") < content.index("second external")

    def test_read_returns_full_template_content(self, tmp_path):
        create_ideas_template(tmp_path, "read-test")
        content = read_ideas(tmp_path, "read-test")
        assert "## Discarded but Promising" in content
        assert "## Near-Misses" in content
        assert "## External Research" in content
