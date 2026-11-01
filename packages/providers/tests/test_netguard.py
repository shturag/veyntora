import pytest
from veyntora_providers.netguard import EndpointNotAllowedError, check_public_https


@pytest.mark.parametrize(
    "url",
    [
        "http://1.1.1.1/v1",  # not https
        "https://10.0.0.5/v1",
        "https://127.0.0.1:8200/v1",  # OpenBao on the host
        "https://169.254.169.254/latest/meta-data",  # cloud metadata
        "https://[::1]/v1",
        "https://[::ffff:10.0.0.1]/v1",  # IPv4-mapped private address
        "https://100.64.0.1/v1",  # carrier-grade NAT
        "https://user:pw@1.1.1.1/v1",
        "https://localhost/v1",
        "https:///v1",
    ],
)
async def test_internal_or_odd_endpoints_are_refused(url: str) -> None:
    with pytest.raises(EndpointNotAllowedError):
        await check_public_https(url)


async def test_public_https_endpoints_are_allowed() -> None:
    await check_public_https("https://1.1.1.1/v1")
    await check_public_https("https://[2606:4700:4700::1111]:8443/v1")


async def test_pinned_transport_connects_to_the_checked_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ipaddress  # noqa: PLC0415

    import httpx  # noqa: PLC0415
    from veyntora_providers import netguard  # noqa: PLC0415

    seen: list[httpx.Request] = []

    async def resolved(url: str) -> list[ipaddress.IPv4Address]:
        return [ipaddress.IPv4Address("93.184.216.34")]

    def inner(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(netguard, "public_addresses", resolved)
    transport = netguard.PinnedPublicTransport(httpx.MockTransport(inner))
    async with httpx.AsyncClient(transport=transport) as http:
        assert (await http.get("https://llm.example.com/v1/models")).status_code == 200
    request = seen[0]
    assert request.url.host == "93.184.216.34", "connects to the address that was checked"
    assert request.headers["host"] == "llm.example.com"
    assert request.extensions["sni_hostname"] == "llm.example.com", "TLS checks the name"


async def test_pinned_transport_refuses_private_addresses() -> None:
    import httpx  # noqa: PLC0415
    from veyntora_providers.netguard import EndpointNotAllowedError, PinnedPublicTransport  # noqa: PLC0415

    async with httpx.AsyncClient(transport=PinnedPublicTransport()) as http:
        with pytest.raises(EndpointNotAllowedError):
            await http.get("https://169.254.169.254/latest/meta-data/")
