# 0002 · Product name, no demo data, licence

Status: accepted · 2026-10-30 · decided by the product owner

## Decision

- The product is called **Veyntora** (the prototype says "Knowledge Assistant"). Brand mark: "V".
- **No demo data.** The brief asked for seed data matching the prototype (Support assistant, HR & onboarding, IT helpdesk, Legal desk); the product owner overruled this. The stack starts empty. Every screen shows real data or a real empty state, never prototype sample rows.
- The only bootstrap data is what is needed to sign in and administer:
  - local dev realm (`deploy/compose/keycloak/veyntora-realm.json`): groups `/platform-admins` and `/all-employees`, users `admin` and `employee`, and the clients `veyntora` and `veyntora-sync`. Production realms come from the customer's Keycloak.
  - OpenFGA model and the default role → admin-area mapping (`deploy/openfga/bootstrap.json`).
  - members of the group named by `VEY_BOOTSTRAP_ADMIN_GROUP` (default `/platform-admins`) become platform admins.
- Licence: proprietary (`LICENSE`). Superseded by ADR 0038: Apache-2.0.

## Consequences

- The landing page's measured numbers (latency, groundedness, router split, scores, bot user counts) are replaced by product guarantees or real configuration.
- Integration tests create their own fixtures and clean up after themselves.
