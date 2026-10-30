from types import SimpleNamespace
from typing import Any

import pytest
from veyntora_graphs import auth as graph_auth


@pytest.mark.parametrize("value", [{}, {"metadata": None}, {"metadata": {"owner": "mallory"}}])
async def test_owner_is_always_the_caller(value: dict[str, Any]) -> None:
    ctx: Any = SimpleNamespace(user=SimpleNamespace(identity="sub-alice"))
    assert await graph_auth.owner_only(ctx, value) == {"owner": "sub-alice"}
    assert value["metadata"]["owner"] == "sub-alice"
