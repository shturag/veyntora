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
