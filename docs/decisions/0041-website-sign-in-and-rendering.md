# 0041 · Websites behind a sign-in, built by scripts, or with messy addresses

Status: accepted · 2026-11-10

## Context

The website connector read public pages as the server sends them. Intranet pages behind a login could not be read. Pages built in the browser by scripts came out nearly empty. The same page under several `?query` addresses was read several times, subdomains were out of reach, and compressed sitemaps were not read.

## Decision

**1. Sign-in per website:**
- **Kinds:** a bearer token, a user name and password (basic), a session cookie, or a token in a named header.
- **The secret:** stored write-only in OpenBao like every source secret (ADR 0004).
- **Who receives it:** it's added to each request **only for the site's own hosts** (the start pages' hosts, and their subdomains when those are included), never as a default header. A link or redirect to another host doesn't carry it, and the browser applies the same rule to every resource a page loads.
- **HTTPS only:** sign-in needs `https://` start pages.

**2. JavaScript rendering through an optional browser service:**
- **The service:** a Playwright server in the official image, `mcr.microsoft.com/playwright:v1.64.1-noble`, started with `docker compose --profile browser up -d`. It has no published port; the workers reach it at `VEY_BROWSER_URL`.
- **Rendering:** with "Render JavaScript" on, an HTML page is read again in the browser after its scripts ran (network idle, 30 s at most). Robots.txt, hosts, paths and limits apply as before.
- **The client:** the workers use the `playwright` package (1.64.1, Apache-2.0, plus `pyee`, MIT), matching the image's version. Without the service, the connection test says how to start it.

**3. Addresses:**
- **Ignore ?query:** treats addresses that differ only in `?query` as one page.
- **Include subdomains:** reads subdomains of the start pages' hosts.

**4. Compressed sitemaps:** `.xml.gz` sitemaps are unpacked up to the file size limit; larger ones are skipped.

## Consequences

- Intranet sites with a token, basic sign-in or a session cookie can be read. Sign-in flows that need a login form or multi-factor authentication still can't.
- Rendering is slow (a browser per page) and the image is large, so it's off by default, per website and opt-in.
- The browser can reach whatever the workers can; it runs only what the crawler asks it to open.
