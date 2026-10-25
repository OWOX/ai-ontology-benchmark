# Spec: docs/specs/ui.md
"""Tests for the UI's git reader, over a temporary repo with a bare origin."""

from test_release import git, repo  # noqa: F401
from test_ui import ui_repo  # noqa: F401  (fixture)
from ui.gitdata import GitData


def test_show_reads_ref_not_work_tree(ui_repo):
    data = GitData(ui_repo); data.fetch(force=True)
    (ui_repo / "config" / "models.toml").write_text("changed", encoding="utf-8")
    assert "example-model" in data.show(data.main_ref(), "config/models.toml")
    assert data.show(data.main_ref(), "no/such/file") is None


def test_results_refs_prefers_local_for_live(ui_repo):
    git(ui_repo, "branch", "results/a")
    git(ui_repo, "push", "-q", "origin", "results/a")
    git(ui_repo, "branch", "results/b")      # local only
    data = GitData(ui_repo); data.fetch(force=True)
    assert data.results_refs() == {"a": "refs/remotes/origin/results/a"}
    assert data.results_refs({"a", "b"}) == {"a": "refs/heads/results/a", "b": "refs/heads/results/b"}


def test_fetch_is_throttled(ui_repo):
    now = [100.0]
    data = GitData(ui_repo, clock=lambda: now[0])
    data.fetch(); first = data.fetched_at
    assert first
    git(ui_repo, "branch", "results/c")  # push by URL, so no tracking ref moves until a fetch
    url = git(ui_repo, "remote", "get-url", "origin").strip()
    git(ui_repo, "push", "-q", url, "results/c")
    data.fetch(); assert "c" not in data.remote_ids()
    now[0] += 31; data.fetch(); assert "c" in data.remote_ids()


def test_github_url_forms(ui_repo):
    data = GitData(ui_repo)
    for url in ("https://github.com/o/r.git", "https://github.com/o/r", "git@github.com:o/r.git"):
        git(ui_repo, "remote", "set-url", "origin", url)
        assert data.github() == "https://github.com/o/r"
    assert data.link("abc", "README.md") == "https://github.com/o/r/blob/abc/README.md"
    git(ui_repo, "remote", "set-url", "origin", "https://gitlab.com/o/r.git")
    assert data.github() is None and data.link("abc", "x") is None


def test_no_origin_reads_head(ui_repo):
    git(ui_repo, "remote", "remove", "origin")
    data = GitData(ui_repo); data.fetch(force=True)
    assert data.fetch_error and data.main_ref() == "HEAD"
    assert data.show("HEAD", "config/models.toml")
