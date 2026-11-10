# 0003 · Sign-in runs in the API (backend for frontend)

Status: accepted · 2026-10-30

## Context

The brief: "web talks only to api and to the LangGraph server through the API's auth proxy". OIDC with Keycloak and PKCE. Tokens must not leak to logs or the browser.

## Decision

- The API is a **confidential OIDC client** (`veyntora`) and runs the authorization-code flow **with PKCE (S256)**: `GET /auth/login` → Keycloak → `GET /auth/callback`.
- Tokens stay server-side in **Valkey sessions**. The browser holds only an opaque, `httpOnly`, `SameSite=Lax` cookie (`vey_session`, `Secure` when served over HTTPS). Session keys in Valkey are SHA-256 hashes of the cookie value.
- Access tokens are validated on every request (JWKS, issuer, audience `veyntora-api`, expiry) and refreshed when they are within 30 s of expiry. A failed refresh, for example when the user is disabled in Keycloak, ends the session.
- The browser calls the API through a same-origin route handler in Next.js (`/api/*`), which forwards the cookie and passes redirects and `Set-Cookie` through. Server components call the API directly over the internal network with the user's cookie.
- **CSRF**: cookie-authenticated writes must send `X-Veyntora-CSRF: 1`. Browsers cannot add that header cross-site without a CORS preflight, and the API grants none.
- Bearer tokens are accepted too (Teams, Slack and API clients, ADR 0020) and go through the same checks.
- Keycloak groups map to `Group` rows and OpenFGA `member` tuples on every login and in a scheduled full sync (every 15 min, Celery beat). Both are audited as `keycloak-sync`.
- Suspended users get `403` on every request, whatever their token says.
- Keycloak issues tokens under the public hostname (`KC_HOSTNAME`); services talk to it over the internal network (`KC_HOSTNAME_BACKCHANNEL_DYNAMIC`, `VEY_OIDC_INTERNAL_BASE`).

## Alternatives rejected

- NextAuth/Auth.js in Next.js: v5 is still beta, and tokens would live in the web tier, which the brief keeps thin.
- Tokens in browser storage: exposed to XSS.

## Open item

- `X-Forwarded-For` is trusted from the first hop. The hardening in ADR 0023 restricts this to the configured ingress.
