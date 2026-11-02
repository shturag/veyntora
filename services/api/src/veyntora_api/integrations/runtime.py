"""Use Langfuse and Grafana from the runtime services (graphs, workers).

Only runtime services hold a secret reader (ADR 0004), so everything that needs a key
lives here: resolving the stored settings, the "Test connection" checks and reading
Grafana dashboards for Monitoring. The API never imports the reading half.
"""

from __future__ import annotations

import asyncio
import math
import re
import time
from dataclasses import dataclass
from typing import Any, Literal

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from veyntora_providers.interfaces import Hosting
from veyntora_providers.secrets import SecretReader, SecretUnavailableError

from veyntora_api.db.models.platform import Integration, IntegrationKind
from veyntora_api.integrations import service

log = structlog.get_logger()

TIMEOUT = httpx.Timeout(10.0, connect=5.0)


@dataclass(frozen=True, slots=True)
class Connection:
    kind: IntegrationKind
    hosting: Hosting
    url: str
    browser_url: str
    public_key: str | None
    secret: str
    dashboards: tuple[tuple[str, str], ...] = ()

    def langfuse_client(self, timeout: float = 30) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.url, auth=(self.public_key or "", self.secret), timeout=timeout
        )

    def grafana_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.url,
            headers={"Authorization": f"Bearer {self.secret}"},
            timeout=TIMEOUT,
        )


def usable(row: Integration | None) -> bool:
    if row is None or not row.enabled or not row.url or row.secret_ref is None:
        return False
    return row.kind is not IntegrationKind.LANGFUSE or bool(row.public_key)


async def connection_of(row: Integration, reader: SecretReader) -> Connection:
    """Raises SecretUnavailableError when the key cannot be read."""
    if row.secret_ref is None:
        raise SecretUnavailableError("no key stored")
    secret = await reader.read(row.secret_ref)
    dashboards = tuple(
        (str(d["uid"]), str(d["title"])) for d in (row.options or {}).get("dashboards") or []
    )
    return Connection(
        kind=row.kind,
        hosting=row.hosting,
        url=row.url.rstrip("/"),
        browser_url=(row.browser_url or row.url).rstrip("/"),
        public_key=row.public_key,
        secret=secret,
        dashboards=dashboards,
    )


async def resolve(
    db: AsyncSession, reader: SecretReader, kind: IntegrationKind
) -> Connection | None:
    """The configured, enabled connection, or None (not set up, disabled, no key)."""
    row = await service.get(db, kind)
    if row is None or not usable(row):
        return None
    try:
        return await connection_of(row, reader)
    except SecretUnavailableError as exc:
        log.warning("integration.key_unavailable", kind=kind.value, error=str(exc))
        return None


# ---------------------------------------------------------------- Test connection


async def check(conn: Connection) -> tuple[bool, str]:
    """A request that needs the key: a wrong key fails, not only a wrong address."""
    try:
        if conn.kind is IntegrationKind.LANGFUSE:
            return await _check_langfuse(conn)
        return await _check_grafana(conn)
    except httpx.HTTPError as exc:
        return False, f"Not reachable: {type(exc).__name__}"


async def _check_langfuse(conn: Connection) -> tuple[bool, str]:
    async with conn.langfuse_client(timeout=10) as http:
        res = await http.get("/api/public/projects")
    if res.status_code in (401, 403):
        return False, "Langfuse refused the keys (check the public and secret key)"
    if res.status_code != 200:
        return False, f"Langfuse answered HTTP {res.status_code}"
    projects = res.json().get("data") or []
    name = projects[0].get("name") if projects else None
    return True, f"Connected to project {name}" if name else "Connected"


async def _check_grafana(conn: Connection) -> tuple[bool, str]:
    async with conn.grafana_client() as http:
        res = await http.get("/api/search", params={"type": "dash-db", "limit": 5000})
    if res.status_code in (401, 403):
        return False, "Grafana refused the token (check the service-account token)"
    if res.status_code != 200:
        return False, f"Grafana answered HTTP {res.status_code}"
    visible = res.json()
    missing = {uid for uid, _ in conn.dashboards} - {str(d.get("uid")) for d in visible}
    if missing:
        return False, f"Dashboards not found or not shared with the token: {sorted(missing)}"
    return True, f"Connected; {len(visible)} dashboards visible"


# ---------------------------------------------------------------- Grafana dashboards

Range = Literal["1h", "6h", "24h", "7d"]
RANGES: dict[str, str] = {"1h": "now-1h", "6h": "now-6h", "24h": "now-24h", "7d": "now-7d"}
_RANGE_MS = {"1h": 3_600_000, "6h": 21_600_000, "24h": 86_400_000, "7d": 604_800_000}
MAX_PANELS = 24
MAX_POINTS = 240
MAX_SERIES = 8
MAX_ROWS = 20
_TIMESERIES = {"timeseries", "graph"}
_SINGLE = {"stat", "gauge", "bargauge", "singlestat"}
_VAR = re.compile(r"\$\{(\w+)(?::\w+)?\}|\[\[(\w+)\]\]|\$(\w+)")


class GrafanaError(RuntimeError):
    pass


async def search(conn: Connection, query: str = "") -> list[dict[str, str]]:
    async with conn.grafana_client() as http:
        res = await http.get(
            "/api/search", params={"type": "dash-db", "query": query, "limit": 100}
        )
    if res.status_code != 200:
        raise GrafanaError(f"Grafana answered HTTP {res.status_code}")
    return [
        {"uid": str(d["uid"]), "title": str(d["title"]), "folder": str(d.get("folderTitle") or "")}
        for d in res.json()
        if d.get("uid")
    ]


def _variables(dash: dict[str, Any]) -> dict[str, str]:
    """Current values of the dashboard's template variables (the first, for multi-values)."""
    out: dict[str, str] = {}
    for v in (dash.get("templating") or {}).get("list") or []:
        current = (v.get("current") or {}).get("value")
        if isinstance(current, list):
            current = current[0] if current else ""
        if current in (None, "$__all"):
            current = ".*" if current == "$__all" else ""
        out[str(v.get("name"))] = str(current)
    return out


def _substitute(value: Any, variables: dict[str, str]) -> Any:
    if isinstance(value, str):

        def repl(m: re.Match[str]) -> str:
            name = m.group(1) or m.group(2) or m.group(3)
            # Grafana's own ($__interval, $__rate_interval, ...) are left for the server.
            return variables.get(name, m.group(0))

        return _VAR.sub(repl, value)
    if isinstance(value, dict):
        return {k: _substitute(v, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute(v, variables) for v in value]
    return value


def _flatten(panels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in panels:
        if p.get("type") == "row":
            out += _flatten(p.get("panels") or [])
        else:
            out.append(p)
    return out


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, int | float):
        return None
    return None if math.isnan(v) or math.isinf(v) else float(v)


def _series_name(field: dict[str, Any], frame: dict[str, Any]) -> str:
    config = field.get("config") or {}
    if config.get("displayNameFromDS") or config.get("displayName"):
        return str(config.get("displayNameFromDS") or config.get("displayName"))
    labels = field.get("labels") or {}
    if labels:
        return ", ".join(f"{k}={v}" for k, v in sorted(labels.items()) if k != "__name__") or str(
            labels.get("__name__", field.get("name", ""))
        )
    return str((frame.get("schema") or {}).get("name") or field.get("name") or "")


def _thin(points: list[tuple[int, float | None]]) -> list[tuple[int, float | None]]:
    if len(points) <= MAX_POINTS:
        return points
    step = math.ceil(len(points) / MAX_POINTS)
    return points[::step]


def _frames_to_series(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    series: list[dict[str, Any]] = []
    for frame in frames:
        fields = (frame.get("schema") or {}).get("fields") or []
        values = (frame.get("data") or {}).get("values") or []
        times = next(
            (
                values[i]
                for i, f in enumerate(fields)
                if f.get("type") == "time" and i < len(values)
            ),
            None,
        )
        for i, f in enumerate(fields):
            if f.get("type") != "number" or i >= len(values):
                continue
            col = [_num(v) for v in values[i]]
            points = list(zip(times, col, strict=False)) if times else list(enumerate(col))
            series.append(
                {"name": _series_name(f, frame), "points": _thin([(int(t), v) for t, v in points])}
            )
    return series[:MAX_SERIES]


def _frames_to_table(frames: list[dict[str, Any]]) -> dict[str, Any]:
    if not frames:
        return {"columns": [], "rows": []}
    frame = frames[0]
    fields = (frame.get("schema") or {}).get("fields") or []
    values = (frame.get("data") or {}).get("values") or []
    columns = [str((f.get("config") or {}).get("displayName") or f.get("name")) for f in fields]
    n = max((len(c) for c in values), default=0)
    rows = [
        [values[c][r] if r < len(values[c]) else None for c in range(len(values))]
        for r in range(min(n, MAX_ROWS))
    ]
    return {"columns": columns, "rows": rows}


async def _datasource(
    http: httpx.AsyncClient, ref: Any, cache: dict[str, dict[str, str]]
) -> dict[str, str] | None:
    """{"uid", "type"} for a panel's datasource: a reference, a name, or the default."""
    if isinstance(ref, dict) and ref.get("uid"):
        return {"uid": str(ref["uid"]), "type": str(ref.get("type") or "")}
    key = str(ref) if ref else "__default__"
    if key not in cache:
        if ref:
            res = await http.get(f"/api/datasources/name/{ref}")
            if res.status_code != 200:
                return None
            ds = res.json()
        else:
            res = await http.get("/api/datasources")
            if res.status_code != 200:
                return None
            ds = next((d for d in res.json() if d.get("isDefault")), None)
            if ds is None:
                return None
        cache[key] = {"uid": str(ds["uid"]), "type": str(ds.get("type") or "")}
    return cache[key]


async def _panel(
    http: httpx.AsyncClient,
    panel: dict[str, Any],
    variables: dict[str, str],
    since: str,
    ds_cache: dict[str, dict[str, str]],
) -> dict[str, Any]:
    kind = (
        "timeseries"
        if panel.get("type") in _TIMESERIES
        else "stat"
        if panel.get("type") in _SINGLE
        else "table"
        if panel.get("type") == "table"
        else "unsupported"
    )
    defaults = (panel.get("fieldConfig") or {}).get("defaults") or {}
    out: dict[str, Any] = {
        "id": panel.get("id"),
        "title": _substitute(str(panel.get("title") or ""), variables),
        "type": str(panel.get("type") or ""),
        "kind": kind,
        "unit": defaults.get("unit"),
        "width": int((panel.get("gridPos") or {}).get("w") or 12),
        "series": [],
        "table": None,
        "error": None,
    }
    if kind == "unsupported":
        return out
    panel = _substitute(panel, variables)
    queries = []
    for target in panel.get("targets") or []:
        if target.get("hide"):
            continue
        ds = await _datasource(http, target.get("datasource") or panel.get("datasource"), ds_cache)
        if ds is None:
            out["error"] = "Data source not found"
            return out
        queries.append(
            {**target, "datasource": ds, "maxDataPoints": MAX_POINTS, "intervalMs": 60_000}
        )
    if not queries:
        out["error"] = "No queries"
        return out
    res = await http.post("/api/ds/query", json={"from": since, "to": "now", "queries": queries})
    if res.status_code not in (200, 207):
        out["error"] = f"Grafana answered HTTP {res.status_code}"
        return out
    frames: list[dict[str, Any]] = []
    for result in (res.json().get("results") or {}).values():
        if result.get("error"):
            out["error"] = str(result["error"])[:300]
        frames += result.get("frames") or []
    if kind == "table":
        out["table"] = _frames_to_table(frames)
    else:
        out["series"] = _frames_to_series(frames)
    return out


async def dashboard(conn: Connection, uid: str, range_: Range) -> dict[str, Any]:
    """The dashboard's panels with their data, shaped for Monitoring's own charts."""
    async with conn.grafana_client() as http:
        res = await http.get(f"/api/dashboards/uid/{uid}")
        if res.status_code == 404:
            raise GrafanaError("Dashboard not found")
        if res.status_code != 200:
            raise GrafanaError(f"Grafana answered HTTP {res.status_code}")
        body = res.json()
        dash = body.get("dashboard") or {}
        variables = _variables(dash)
        # In Grafana's reading order: top to bottom, left to right.
        panels = sorted(
            _flatten(dash.get("panels") or []),
            key=lambda p: (
                (p.get("gridPos") or {}).get("y", 0),
                (p.get("gridPos") or {}).get("x", 0),
            ),
        )[:MAX_PANELS]
        end = int(time.time() * 1000)
        ds_cache: dict[str, dict[str, str]] = {}
        gate = asyncio.Semaphore(4)

        async def one(p: dict[str, Any]) -> dict[str, Any]:
            async with gate:
                try:
                    return await _panel(http, p, variables, RANGES[range_], ds_cache)
                except httpx.HTTPError as exc:
                    return {
                        "id": p.get("id"),
                        "title": str(p.get("title") or ""),
                        "type": str(p.get("type") or ""),
                        "kind": "unsupported",
                        "unit": None,
                        "width": 12,
                        "series": [],
                        "table": None,
                        "error": f"Not reachable: {type(exc).__name__}",
                    }

        data = await asyncio.gather(*(one(p) for p in panels))
    path = str((body.get("meta") or {}).get("url") or f"/d/{uid}")
    return {
        "uid": uid,
        "title": str(dash.get("title") or uid),
        "url": f"{conn.browser_url}{path}",
        # The requested range, so charts span it even where data starts later.
        "start": end - _RANGE_MS[range_],
        "end": end,
        "panels": data,
    }
