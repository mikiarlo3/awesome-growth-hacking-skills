"""
Unit tests for Awesome List Linter (scripts/lint_awesome.py).
"""

import os
import sys
from unittest.mock import patch, MagicMock
import pytest

# Add repository root / scripts to sys.path for importing lint_awesome
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'scripts')))

import lint_awesome
from lint_awesome import (
    parse_entry,
    extract_sections,
    validate_toc,
    validate_formatting_and_order,
    fix_readme_sorting,
    check_url_status,
    check_links_health,
    Entry,
    LintIssue,
)


def test_parse_entry_valid():
    line = "- [Test Skill](https://github.com/test/repo) - A helpful marketing skill."
    entry = parse_entry(line)
    assert entry is not None
    assert entry.name == "Test Skill"
    assert entry.url == "https://github.com/test/repo"
    assert entry.description == "A helpful marketing skill."


def test_parse_entry_invalid():
    invalid_lines = [
        "Not a list item",
        "- [No URL] - Just text",
        "- [Title](ftp://invalid-scheme) - Bad scheme",
        "- Just text without link",
    ]
    for line in invalid_lines:
        assert parse_entry(line) is None


def test_extract_sections():
    content = (
        "# Title\n"
        "\n"
        "## Section One\n"
        "- [Item A](https://example.com/a) - Desc A.\n"
        "\n"
        "## Section Two\n"
        "- [Item B](https://example.com/b) - Desc B.\n"
    )
    sections = extract_sections(content)
    assert "Section One" in sections
    assert "Section Two" in sections
    non_empty_sec1 = [l for _, l in sections["Section One"] if l.strip()]
    non_empty_sec2 = [l for _, l in sections["Section Two"] if l.strip()]
    assert len(non_empty_sec1) == 1
    assert len(non_empty_sec2) == 1


def test_validate_toc_valid():
    content = (
        "## Contents\n"
        "- [Section One](#section-one)\n"
        "- [Section Two](#section-two)\n"
        "\n"
        "## Section One\n"
        "- [Item A](https://example.com/a) - Desc A.\n"
        "\n"
        "## Section Two\n"
        "- [Item B](https://example.com/b) - Desc B.\n"
    )
    issues = validate_toc(content)
    assert len(issues) == 0


def test_validate_toc_mismatch():
    content = (
        "## Contents\n"
        "- [Missing Section](#missing-section)\n"
        "\n"
        "## Section One\n"
        "- [Item A](https://example.com/a) - Desc A.\n"
    )
    issues = validate_toc(content)
    assert len(issues) == 1
    assert issues[0].level == "WARNING"
    assert "Missing Section" in issues[0].message


def test_validate_formatting_and_order_sorted():
    content = (
        "## Category Alpha\n"
        "- [Alpha Skill](https://example.com/alpha) - First item.\n"
        "- [Beta Skill](https://example.com/beta) - Second item.\n"
    )
    issues, entries = validate_formatting_and_order(content)
    assert len(issues) == 0
    assert len(entries["Category Alpha"]) == 2


def test_validate_formatting_and_order_unsorted():
    content = (
        "## Category Alpha\n"
        "- [Beta Skill](https://example.com/beta) - Second item.\n"
        "- [Alpha Skill](https://example.com/alpha) - First item.\n"
    )
    issues, _ = validate_formatting_and_order(content)
    assert len(issues) == 1
    assert issues[0].level == "ERROR"
    assert "not sorted alphabetically" in issues[0].message


def test_validate_formatting_and_order_duplicate_url():
    content = (
        "## Category Alpha\n"
        "- [Item One](https://example.com/same) - First item.\n"
        "- [Item Two](https://example.com/same) - Second item with duplicate URL.\n"
    )
    issues, _ = validate_formatting_and_order(content)
    assert any(i.level == "ERROR" and "Duplicate URL" in i.message for i in issues)


def test_validate_formatting_and_order_duplicate_name():
    content = (
        "## Category Alpha\n"
        "- [Same Name](https://example.com/one) - First item.\n"
        "- [Same Name](https://example.com/two) - Second item with same name.\n"
    )
    issues, _ = validate_formatting_and_order(content)
    assert any(i.level == "WARNING" and "Duplicate project name" in i.message for i in issues)


def test_fix_readme_sorting():
    content = (
        "## Category Alpha\n"
        "- [Zeta Skill](https://example.com/zeta) - Z item.\n"
        "- [Alpha Skill](https://example.com/alpha) - A item.\n"
        "\n"
        "---"
    )
    fixed = fix_readme_sorting(content)
    expected = (
        "## Category Alpha\n"
        "- [Alpha Skill](https://example.com/alpha) - A item.\n"
        "- [Zeta Skill](https://example.com/zeta) - Z item.\n"
        "\n"
        "---"
    )
    assert fixed.strip() == expected.strip()


def test_integration_readme_file():
    readme_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'README.md'))
    assert os.path.exists(readme_path)
    with open(readme_path, 'r', encoding='utf-8') as f:
        content = f.read()

    toc_issues = validate_toc(content)
    format_issues, entries = validate_formatting_and_order(content)
    all_issues = toc_issues + format_issues

    errors = [i for i in all_issues if i.level == 'ERROR']
    assert len(errors) == 0, f"Errors found in README.md: {errors}"
    assert len(entries) > 0, "No categories found in README.md"


def test_check_url_status_success():
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.getcode.return_value = 200
        mock_urlopen.return_value.__enter__.return_value = mock_resp
        url, status = check_url_status("https://example.com/test", retries=0)
        assert url == "https://example.com/test"
        assert status == 200


def test_check_url_status_head_405_fallback_get():
    import urllib.error
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.getcode.return_value = 200
        # First call (HEAD) raises 405, second call (GET) succeeds with 200
        mock_urlopen.side_effect = [
            urllib.error.HTTPError("https://example.com", 405, "Method Not Allowed", {}, None),
            MagicMock(__enter__=MagicMock(return_value=mock_resp)),
        ]
        url, status = check_url_status("https://example.com/test", retries=0)
        assert url == "https://example.com/test"
        assert status == 200


def test_check_links_health():
    with patch("lint_awesome.check_url_status") as mock_check:
        mock_check.side_effect = lambda u: (u, 200)
        results = check_links_health(["https://example.com/1", "https://example.com/2"], max_workers=2)
        assert results["https://example.com/1"] == 200
        assert results["https://example.com/2"] == 200

