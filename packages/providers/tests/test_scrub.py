from veyntora_providers.scrub import REDACTED, scrub, scrub_text


def test_sensitive_keys_are_removed_recursively() -> None:
    data = {
        "name": "Cohere",
        "api_key": "abc123",
        "nested": {"Authorization": "Bearer xyz", "ok": 1},
        "items": [{"client_secret": "s"}],
    }
    out = scrub(data)
    assert out["name"] == "Cohere"
    assert out["api_key"] == REDACTED
    assert out["nested"] == {"Authorization": REDACTED, "ok": 1}
    assert out["items"] == [{"client_secret": REDACTED}]
    assert data["api_key"] == "abc123", "input must not be mutated"


def test_safe_metadata_keys_survive() -> None:
    out = scrub({"secret_ref": "kv/providers/x", "secret_last4": "9f2a", "tokens_in": 12})
    assert out == {"secret_ref": "kv/providers/x", "secret_last4": "9f2a", "tokens_in": 12}


def test_token_shaped_values_are_redacted_in_free_text() -> None:
    jwt = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.c2lnbmF0dXJlMTIzNDU2"
    text = f"calling with Bearer abcdefghijkl and {jwt} and sk-ant-0123456789abcdefABCD"
    out = scrub_text(text)
    assert "abcdefghijkl" not in out
    assert jwt not in out
    assert "sk-ant" not in out
    assert out.count(REDACTED) == 3


def test_vault_and_cloud_tokens() -> None:
    assert scrub_text("hvs.CAESIJ0123456789abcdefghij") == REDACTED
    assert scrub_text("AKIAABCDEFGHIJKLMNOP") == REDACTED
