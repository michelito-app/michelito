"""The connector's tool table: arguments become the route's query."""

from michelito.hosted import mcp_tools


def test_list_transactions_pages_by_default() -> None:
    tool = mcp_tools.BY_NAME["list_transactions"]
    checked = mcp_tools.check_arguments(tool, {"from": "2026-01", "to": "2026-03"})
    path, query = mcp_tools.request_of(tool, checked)
    assert path == "/api/transactions"
    assert query == {"from": "2026-01", "to": "2026-03", "limit": "200"}


def test_a_given_limit_wins_over_the_default() -> None:
    tool = mcp_tools.BY_NAME["list_transactions"]
    checked = mcp_tools.check_arguments(tool, {"month": "2026-01", "limit": 50, "offset": 100})
    _, query = mcp_tools.request_of(tool, checked)
    assert query == {"month": "2026-01", "limit": "50", "offset": "100"}


def test_list_transactions_schema_offers_range_and_paging() -> None:
    props = mcp_tools.BY_NAME["list_transactions"].schema()["properties"]
    assert {"month", "from", "to", "limit", "offset"} <= set(props)
    assert props["limit"]["maximum"] == 500


def test_billing_requires_the_account() -> None:
    schema = mcp_tools.BY_NAME["get_account_billing"].schema()
    assert schema["required"] == ["account"]
    assert {"from", "to"} <= set(schema["properties"])
