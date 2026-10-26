import json

from permission.approval_store import load_approvals, save_approvals


def test_domain_approvals_round_trip(workspace):
    path = workspace / ".jinni" / "allowed.json"
    entries = {("fetch_url", "example.com"), ("fetch_table", "example.co.uk")}

    save_approvals(path, entries)

    assert load_approvals(path) == entries
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 1


def test_domain_approval_loader_ignores_unknown_tools_and_wildcards(workspace):
    path = workspace / "allowed.json"
    path.write_text(json.dumps({"version": 1, "allowed": [
        {"tool": "write_file", "scope": "example.com"},
        {"tool": "fetch_url", "scope": "*"},
        {"tool": "fetch_url", "scope": "example.com"},
    ]}), encoding="utf-8")

    assert load_approvals(path) == {("fetch_url", "example.com")}


def test_corrupt_domain_approval_store_fails_closed(workspace):
    path = workspace / "allowed.json"
    path.write_text("not json", encoding="utf-8")

    assert load_approvals(path) == set()
