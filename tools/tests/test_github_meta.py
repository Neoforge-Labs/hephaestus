"""Tests for the community-health files GitHub shows to strangers."""

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
ISSUE_DIR = REPO_ROOT / ".github" / "ISSUE_TEMPLATE"


def test_security_md_names_a_reporting_channel_and_a_response_window() -> None:
    text = " ".join((REPO_ROOT / "SECURITY.md").read_text().split())
    assert "private vulnerability reporting" in text.lower()
    assert re.search(r"\b\d+\s+(calendar\s+|business\s+)?days\b", text)
    assert "@" not in text, "SECURITY.md must not name an email address"


def test_every_issue_form_parses_and_has_githubs_required_top_level_keys() -> None:
    forms = sorted(p for p in ISSUE_DIR.glob("*.yml") if p.name != "config.yml")
    assert forms, "no issue forms found"
    for form in forms:
        data = yaml.safe_load(form.read_text())
        assert isinstance(data, dict), form.name
        for key in ("name", "description"):
            assert isinstance(data.get(key), str) and data[key].strip(), f"{form.name}: {key}"
        assert isinstance(data.get("body"), list) and data["body"], f"{form.name}: body"


def test_issue_config_disables_blank_issues() -> None:
    data = yaml.safe_load((ISSUE_DIR / "config.yml").read_text())
    assert data["blank_issues_enabled"] is False


def test_pull_request_template_asks_for_the_repos_own_gates() -> None:
    text = (REPO_ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md").read_text().lower()
    assert "spec" in text and "vector" in text
    assert "independent" in text
    assert "maturity" in text
