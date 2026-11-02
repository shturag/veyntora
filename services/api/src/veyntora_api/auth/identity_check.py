"""Check that Keycloak is set up the way Veyntora needs it (bundled or your own).

Run by `veyntora-api bootstrap` before the first identity sync and on its own as
`veyntora-api check-identity`, so a wrong issuer, secret or missing role is reported in
words instead of as a 401 deep inside a sync. See docs/runbooks/external-services.md.
"""

from __future__ import annotations

import httpx

from veyntora_api.settings import Settings

_SYNC_ROLES = "realm-management roles view-users, query-users and query-groups"


async def check_identity(s: Settings, http: httpx.AsyncClient) -> list[str]:
    """Problems found, in the order they block each other; empty when all is well.

    An unreachable or failing Keycloak raises httpx.HTTPError instead: that may pass (a
    restart), a set-up mistake does not."""
    base = s.oidc_backchannel_base
    res = await http.get(f"{base}/.well-known/openid-configuration")
    if res.status_code >= 500:
        res.raise_for_status()
    if res.status_code != 200:
        return [f"{base} is not a Keycloak realm (HTTP {res.status_code}); check the realm name"]
    issuer = str(res.json().get("issuer") or "").rstrip("/")
    problems: list[str] = []
    if issuer != s.oidc_issuer.rstrip("/"):
        problems.append(
            f"Keycloak's issuer is {issuer} but VEY_OIDC_ISSUER is {s.oidc_issuer}; "
            "tokens would be refused. Set VEY_OIDC_ISSUER to Keycloak's public realm URL"
        )
    if not s.oidc_client_secret.get_secret_value():
        problems.append(f"VEY_OIDC_CLIENT_SECRET is empty (client {s.oidc_client_id})")
    res = await http.post(
        f"{base}/protocol/openid-connect/token",
        data={
            "grant_type": "client_credentials",
            "client_id": s.keycloak_sync_client_id,
            "client_secret": s.keycloak_sync_client_secret.get_secret_value(),
        },
    )
    if res.status_code != 200:
        problems.append(
            f"The sync client {s.keycloak_sync_client_id} cannot sign in (HTTP {res.status_code}): "
            "it must exist as a confidential client with service accounts enabled, and "
            "VEY_KEYCLOAK_SYNC_CLIENT_SECRET must be its secret"
        )
        return problems
    token = res.json()["access_token"]
    root, _, realm = base.rpartition("/realms/")
    res = await http.get(
        f"{root}/admin/realms/{realm}/groups",
        params={"max": 1, "briefRepresentation": "true"},
        headers={"Authorization": f"Bearer {token}"},
    )
    if res.status_code != 200:
        problems.append(
            f"The sync client may not read users and groups (HTTP {res.status_code}): give its "
            f"service account the {_SYNC_ROLES}"
        )
    return problems
