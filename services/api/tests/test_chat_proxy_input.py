import pytest
from fastapi import HTTPException
from veyntora_api.routers.chat import _run_body

BOT = "0ccb4f23-75ba-41a5-ac79-e9bbe3bc25e4"
MODEL = "462293a3-dc62-43c9-b065-b949a799332e"


def _body(**extra: object) -> dict[str, object]:
    return {
        "input": {
            "chatbot_id": BOT,
            "messages": [{"type": "human", "content": "Is 391 prime?"}],
            **extra,
        }
    }


def test_the_askers_choices_reach_the_graph() -> None:
    out = _run_body(_body(model=MODEL, thinking=True))
    assert out["input"]["model"] == MODEL
    assert out["input"]["thinking"] is True


def test_choices_are_always_set_so_a_thread_does_not_keep_the_last_ones() -> None:
    out = _run_body(_body())
    assert out["input"]["model"] == ""
    assert out["input"]["thinking"] is None


@pytest.mark.parametrize("extra", [{"model": "gpt-4"}, {"thinking": "yes"}])
def test_bad_choices_are_refused(extra: dict[str, object]) -> None:
    with pytest.raises(HTTPException):
        _run_body(_body(**extra))
