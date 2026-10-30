import pytest
from veyntora_spec.filters import FilterError, parse_filter


def test_clauses() -> None:
    assert parse_filter("") == {}
    assert parse_filter("language in [de, en] AND source_id = abc") == {
        "language": ("de", "en"),
        "source_id": ("abc",),
    }
    assert parse_filter("language in ['de'] and language = de") == {"language": ("de",)}
    assert parse_filter("language = de AND language = en") == {"language": ()}


@pytest.mark.parametrize(
    "bad",
    ["acl in [user:x]", "language", "language in []", "status = published", "language ~ de"],
)
def test_refused(bad: str) -> None:
    with pytest.raises(FilterError):
        parse_filter(bad)
