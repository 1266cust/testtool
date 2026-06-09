import pytest
from pathlib import Path
from test_tool.generators.heading_parser import parse_headings
from test_tool.core.models import RequirementSection


class TestParseHeadings:
    def test_markdown_headings(self):
        text = """# Main Title
Some content here.

## Subsection 1
More content.

### Sub-subsection
Details."""
        sections = parse_headings(text)
        assert len(sections) == 3
        assert sections[0].level == 1
        assert sections[0].title == "Main Title"
        assert sections[1].level == 2
        assert sections[1].title == "Subsection 1"

    def test_numbered_headings_dot(self):
        """测试修复后的编号标题解析（使用 .）"""
        text = """1. First Section
Content for first.

2. Second Section
Content for second."""
        sections = parse_headings(text)
        assert len(sections) == 2
        assert sections[0].title == "First Section"
        assert sections[1].title == "Second Section"

    def test_numbered_headings_parenthesis(self):
        """测试修复后的编号标题解析（使用 ）"""
        text = """1) Item One
Content one.

2) Item Two
Content two."""
        sections = parse_headings(text)
        assert len(sections) == 2
        assert sections[0].title == "Item One"
        assert sections[1].title == "Item Two"

    def test_mixed_markdown_and_numbered(self):
        text = """# Overview

1. Feature A
Details about A.

## Details

2. Feature B
Details about B."""
        sections = parse_headings(text)
        assert len(sections) == 4
        assert sections[0].title == "Overview"
        assert sections[1].title == "Feature A"
        assert sections[2].title == "Details"
        assert sections[3].title == "Feature B"

    def test_empty_text(self):
        sections = parse_headings("")
        assert len(sections) == 0

    def test_no_headings(self):
        text = "Just some plain text without any headings."
        sections = parse_headings(text)
        assert len(sections) == 1
        assert sections[0].title == "整体需求"
        assert sections[0].level == 1