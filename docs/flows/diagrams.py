"""Draws the flowcharts in docs/flows/*.svg (make docs-flows).

Swimlane process maps: one lane per actor, boxes on a grid, right-angled connectors.
Plain Python, no dependencies. Edit a diagram below, run it, commit the SVGs.

A box is placed by lane, column and row. A connector names its route:
  h / v       straight across or down/up (dx/dy shift it, for two lines between the same boxes)
  hv          across to the target's column, then down/up into it
  vh          down/up to the target's row, then across into it
  hvh         across to the middle, down/up, across into it
  vhv         down/up to the middle, across, down/up into it
"""

from __future__ import annotations

import itertools
import sys
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).parent

LABEL_W = 136  # lane label column
PAD_X = 12
COL_W = 200
CARD_W = 168
ROW_H = 120
LANE_PAD = 10
HEADER_H = 84
FOOTER_H = 52

FONT = "Inter, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
INK = "#0f172a"
MUTED = "#64748b"
LINE = "#94a3b8"
RULE = "#e2e8f0"

KINDS = {
    #          fill       stroke     bar
    "step": ("#ffffff", "#cbd5e1", "#6366f1"),
    "decision": ("#fffbeb", "#fcd34d", "#d97706"),
    "good": ("#f0fdf4", "#86efac", "#16a34a"),
    "stop": ("#fef2f2", "#fca5a5", "#dc2626"),
    "chip": ("#eef2ff", "#c7d2fe", "#6366f1"),
}


@dataclass
class Lane:
    name: str
    who: str = ""
    rows: int = 1


@dataclass
class Box:
    id: str
    lane: int
    col: float
    title: str
    sub: tuple[str, ...] = ()
    kind: str = "step"
    row: int = 0
    w: int | None = None  # the diagram's card width


@dataclass
class Edge:
    a: str
    b: str
    route: str = "h"
    label: str = ""
    dashed: bool = False
    dx: float = 0
    dy: float = 0
    mid: float | None = None  # the turning x (hvh) or y (vhv)
    lseg: int | None = None  # which segment carries the label


@dataclass
class Diagram:
    name: str
    title: str
    subtitle: str
    cols: int
    lanes: list[Lane]
    boxes: list[Box]
    edges: list[Edge] = field(default_factory=list)
    legend: bool = True
    col_w: int = COL_W
    row_h: int = ROW_H
    card_w: int = CARD_W


def text_w(s: str, size: float, bold: bool = False) -> float:
    return len(s) * size * (0.54 if bold else 0.5)


def box_h(b: Box) -> float:
    if b.kind in ("start", "actor"):
        return 44 if not b.sub else 42 + 16 * len(b.sub)
    return 30 + 18 + 16 * len(b.sub)


class Layout:
    def __init__(self, d: Diagram) -> None:
        self.d = d
        self.width = LABEL_W + 2 * PAD_X + d.cols * d.col_w
        self.lane_top: list[float] = []
        y = float(HEADER_H)
        for lane in d.lanes:
            self.lane_top.append(y)
            y += lane.rows * d.row_h + 2 * LANE_PAD
        self.lanes_bottom = y
        self.height = y + (FOOTER_H if d.legend else 16)
        self.pos = {b.id: self.place(b) for b in d.boxes}

    def place(self, b: Box) -> tuple[float, float, float, float]:
        cw = self.d.col_w
        cx = LABEL_W + PAD_X + b.col * cw + cw / 2
        rh = self.d.row_h
        cy = self.lane_top[b.lane] + LANE_PAD + b.row * rh + rh / 2
        return cx, cy, float(b.w or self.d.card_w), box_h(b)

    def side(self, bid: str, s: str) -> tuple[float, float]:
        cx, cy, w, h = self.pos[bid]
        return {
            "l": (cx - w / 2, cy),
            "r": (cx + w / 2, cy),
            "t": (cx, cy - h / 2),
            "b": (cx, cy + h / 2),
        }[s]


def route(lay: Layout, e: Edge) -> list[tuple[float, float]]:
    ax, ay, aw, ah = lay.pos[e.a]
    bx, by, bw, bh = lay.pos[e.b]
    right = bx > ax
    down = by > ay
    if e.route == "h":
        y = ay + e.dy
        return [(ax + (aw / 2 if right else -aw / 2), y), (bx + (-bw / 2 if right else bw / 2), y)]
    if e.route == "v":
        x = ax + e.dx
        return [(x, ay + (ah / 2 if down else -ah / 2)), (x, by + (-bh / 2 if down else bh / 2))]
    if e.route == "hv":
        p0 = (ax + (aw / 2 if right else -aw / 2), ay)
        return [p0, (bx, ay), (bx, by + (-bh / 2 if down else bh / 2))]
    if e.route == "vh":
        p0 = (ax, ay + (ah / 2 if down else -ah / 2))
        return [p0, (ax, by), (bx + (-bw / 2 if right else bw / 2), by)]
    if e.route == "hvh":
        mx = e.mid if e.mid is not None else (ax + bx) / 2
        p0 = (ax + (aw / 2 if right else -aw / 2), ay)
        return [p0, (mx, ay), (mx, by), (bx + (-bw / 2 if right else bw / 2), by)]
    if e.route == "vhv":
        my = e.mid if e.mid is not None else (ay + by) / 2
        p0 = (ax, ay + (ah / 2 if down else -ah / 2))
        return [p0, (ax, my), (bx, my), (bx, by + (-bh / 2 if down else bh / 2))]
    raise ValueError(e.route)


def rounded(pts: list[tuple[float, float]], r: float = 10) -> str:
    d = f"M{pts[0][0]:.1f} {pts[0][1]:.1f}"
    for i in range(1, len(pts) - 1):
        (x0, y0), (x1, y1), (x2, y2) = pts[i - 1], pts[i], pts[i + 1]
        l1 = abs(x1 - x0) + abs(y1 - y0)
        l2 = abs(x2 - x1) + abs(y2 - y1)
        rr = min(r, l1 / 2, l2 / 2)

        def towards(xa: float, ya: float, xb: float, yb: float, dist: float) -> tuple[float, float]:
            length = abs(xb - xa) + abs(yb - ya) or 1
            return xa + (xb - xa) * dist / length, ya + (yb - ya) * dist / length

        sx, sy = towards(x1, y1, x0, y0, rr)
        ex, ey = towards(x1, y1, x2, y2, rr)
        d += f" L{sx:.1f} {sy:.1f} Q{x1:.1f} {y1:.1f} {ex:.1f} {ey:.1f}"
    d += f" L{pts[-1][0]:.1f} {pts[-1][1]:.1f}"
    return d


def el(tag: str, **attrs: object) -> str:
    """A self-closing SVG element; stroke_width=... is written stroke-width."""
    body = " ".join(f'{k.replace("_", "-")}="{_fmt(v)}"' for k, v in attrs.items())
    return f"<{tag} {body}/>"


def _fmt(v: object) -> str:
    return f"{v:.1f}" if isinstance(v, float) else str(v)


def t(
    x: float,
    y: float,
    s: str,
    size: float,
    color: str,
    *,
    weight: int = 400,
    anchor: str = "start",
    extra: str = "",
) -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" font-weight="{weight}" '
        f'fill="{color}" text-anchor="{anchor}"{extra}>{escape(s)}</text>'
    )


def draw_box(b: Box, lay: Layout, warn: list[str]) -> str:
    cx, cy, w, h = lay.pos[b.id]
    x0, y0 = cx - w / 2, cy - h / 2
    out = []
    if b.kind in ("start", "actor"):
        out.append(el("rect", x=x0, y=y0, width=w, height=h, rx=22, fill="#1e293b"))
        block = 17 + 15 * len(b.sub)
        ty = cy - block / 2 + 13
        out.append(t(cx, ty, b.title, 14, "#ffffff", weight=600, anchor="middle"))
        for i, s in enumerate(b.sub):
            out.append(t(cx, ty + 18 + 15 * i, s, 11.5, "#cbd5e1", weight=400, anchor="middle"))
        if text_w(b.title, 14, True) > w - 28:
            warn.append(f"{b.id}: title too wide")
        return "\n".join(out)
    fill, stroke, bar = KINDS[b.kind]
    clip = f"clip-{lay.d.name}-{b.id}"
    card = {"x": x0, "y": y0, "width": w, "height": h, "rx": 10}
    out.append(f'<clipPath id="{clip}">{el("rect", **card)}</clipPath>')
    out.append(el("rect", **card, fill=fill, stroke=stroke))
    if b.kind != "chip":
        out.append(el("rect", x=x0, y=y0, width=5, height=h, fill=bar, clip_path=f"url(#{clip})"))
    tx = x0 + 18
    out.append(t(tx, y0 + 27, b.title, 14, INK, weight=600))
    for i, s in enumerate(b.sub):
        out.append(t(tx, y0 + 46 + 16 * i, s, 12, MUTED))
    if text_w(b.title, 14, True) > w - 28:
        warn.append(f"{b.id}: title '{b.title}' too wide")
    for s in b.sub:
        if text_w(s, 12) > w - 28:
            warn.append(f"{b.id}: line '{s}' too wide")
    return "\n".join(out)


def draw_edge(e: Edge, lay: Layout, mid: str) -> tuple[str, str]:
    pts = route(lay, e)
    dash = ' stroke-dasharray="6 5"' if e.dashed else ""
    path = (
        f'<path d="{rounded(pts)}" fill="none" stroke="{LINE}" stroke-width="1.6"{dash} '
        f'marker-end="url(#{mid})"/>'
    )
    label = ""
    if e.label:
        segs = list(itertools.pairwise(pts))
        i = (
            e.lseg
            if e.lseg is not None
            else max(
                range(len(segs)),
                key=lambda k: (
                    abs(segs[k][1][0] - segs[k][0][0]) + abs(segs[k][1][1] - segs[k][0][1])
                ),
            )
        )
        (x0, y0), (x1, y1) = segs[i]
        lx, ly = (x0 + x1) / 2, (y0 + y1) / 2
        lw = text_w(e.label, 11.5) + 20
        seg = abs(x1 - x0) + abs(y1 - y0)
        if y0 == y1 and seg < lw + 10:
            # A short connector across: the words sit just above the line.
            label = t(lx, ly - 7, e.label, 11.5, "#475569", weight=500, anchor="middle")
        elif x0 == x1 and seg < 34:
            # A short connector down: the words sit beside the line.
            label = t(lx + 8, ly + 4, e.label, 11.5, "#475569", weight=500)
        else:
            pill = el(
                "rect",
                x=lx - lw / 2,
                y=ly - 11,
                width=lw,
                height=22,
                rx=11,
                fill="#ffffff",
                stroke=RULE,
            )
            label = pill + t(lx, ly + 4, e.label, 11.5, "#475569", weight=500, anchor="middle")
    return path, label


def legend(lay: Layout) -> str:
    y = lay.lanes_bottom + 30
    x = 24.0
    out = [t(x, y + 4, "Key", 12, INK, weight=600)]
    x += 40
    items = [
        ("start", "Start"),
        ("step", "Step"),
        ("decision", "Decision"),
        ("good", "Outcome"),
        ("stop", "Stopped or refused"),
    ]
    for kind, name in items:
        if kind == "start":
            out.append(f'<rect x="{x}" y="{y - 7}" width="22" height="14" rx="7" fill="#1e293b"/>')
        else:
            fill, stroke, bar = KINDS[kind]
            out.append(
                el("rect", x=x, y=y - 7, width=22, height=14, rx=3, fill=fill, stroke=stroke)
            )
            out.append(el("rect", x=x, y=y - 7, width=4, height=14, fill=bar))
        out.append(t(x + 30, y + 4, name, 12, MUTED))
        x += 30 + text_w(name, 12) + 26
    out.append(
        f'<path d="M{x} {y} H{x + 28}" stroke="{LINE}" stroke-width="1.6" stroke-dasharray="6 5"/>'
    )
    out.append(t(x + 36, y + 4, "Only sometimes", 12, MUTED))
    return "\n".join(out)


def render(d: Diagram) -> tuple[str, list[str]]:
    lay = Layout(d)
    warn: list[str] = []
    width, height = lay.width, lay.height
    mid = f"arrow-{d.name}"
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height:.0f}" '
        f'width="{width:.0f}" height="{height:.0f}" font-family="{FONT}" role="img" '
        f'aria-label="{escape(d.title)}">',
        f"<title>{escape(d.title)}</title>",
        f'<defs><marker id="{mid}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
        f'markerHeight="7" orient="auto-start-reverse">'
        f"{el('path', d='M0 0L10 5L0 10z', fill=LINE)}</marker></defs>",
        el(
            "rect",
            x=0.5,
            y=0.5,
            width=width - 1,
            height=height - 1,
            rx=14,
            fill="#ffffff",
            stroke=RULE,
        ),
        t(24, 36, d.title, 20, INK, weight=700),
        t(24, 60, d.subtitle, 13, MUTED),
    ]
    for i, lane in enumerate(d.lanes):
        y0 = lay.lane_top[i]
        h = lane.rows * d.row_h + 2 * LANE_PAD
        fill = "#f8fafc" if i % 2 == 0 else "#ffffff"
        parts.append(el("rect", x=1, y=y0, width=width - 2, height=h, fill=fill))
        parts.append(el("line", x1=1, x2=width - 1, y1=y0, y2=y0, stroke=RULE))
        parts.append(el("line", x1=LABEL_W, x2=LABEL_W, y1=y0, y2=y0 + h, stroke=RULE))
        cy = y0 + h / 2
        ly = cy - 2 if lane.who else cy + 4
        parts.append(
            t(20, ly, lane.name.upper(), 11.5, "#334155", weight=700, extra=' letter-spacing="0.6"')
        )
        if lane.who:
            for k, line in enumerate(lane.who.split("\n")):
                parts.append(t(20, cy + 15 + 14 * k, line, 11.5, MUTED))
    bottom = lay.lanes_bottom
    parts.append(el("line", x1=1, x2=width - 1, y1=bottom, y2=bottom, stroke=RULE))
    labels = []
    for e in d.edges:
        p, lab = draw_edge(e, lay, mid)
        parts.append(p)
        labels.append(lab)
    for b in d.boxes:
        parts.append(draw_box(b, lay, warn))
    parts.extend(labels)
    if d.legend:
        parts.append(legend(lay))
    parts.append("</svg>")
    return "\n".join(parts) + "\n", warn


# ---------------------------------------------------------------- diagrams

DIAGRAMS: list[Diagram] = []


def diagram(d: Diagram) -> None:
    DIAGRAMS.append(d)


diagram(
    Diagram(
        "map",
        "Veyntora at a glance",
        "Admins prepare a chatbot; people use it. Governance covers both.",
        5,
        [Lane("Admins", "prepare", 3), Lane("People", "use", 2), Lane("Governance", "covers both")],
        [
            Box("sources", 0, 0, "Data sources", ("with permissions",), row=0),
            Box("providers", 0, 0, "Providers, keys", ("models; keys are", "write-only"), row=1),
            Box("tools", 0, 0, "Tools (MCP)", ("signed off",), row=2),
            Box("draft", 0, 1, "Chatbot draft", ("pipeline, access",), row=1),
            Box("gate", 0, 2, "Eval gate", ("passed?",), "decision", row=1),
            Box("canary", 0, 3, "Canary", ("10%, then 50%",), row=1),
            Box("live", 0, 4, "Live chatbot", ("for everyone",), "good", row=1),
            Box("signin", 1, 0, "Sign in", kind="start"),
            Box("files", 1, 0, "My files", ("own uploads",), row=1),
            Box("ask", 1, 1, "Ask a question", ("web, Teams, Slack,", "widget, API")),
            Box("answer", 1, 2, "Answer", ("with citations",), "good"),
            Box("saved", 1, 3, "Save and share", ("with the team",)),
            Box("expert", 1, 2, "Ask an expert", ("when no answer",), row=1),
            Box("approvals", 1, 3, "Approvals", ("for write actions",), row=1),
            Box("ret", 2, 0, "Retention", ("masking, AI notice",), "chip"),
            Box("holds", 2, 1, "Legal holds", ("Legal role",), "chip"),
            Box("dsr", 2, 2, "Data requests", ("erasure, export",), "chip"),
            Box("reviews", 2, 3, "Access reviews", ("every 90 days",), "chip"),
            Box("audit", 2, 4, "Audit log", ("hash chain, archive",), "chip"),
        ],
        [
            Edge("sources", "draft", "hvh"),
            Edge("providers", "draft"),
            Edge("tools", "draft", "hvh"),
            Edge("draft", "gate"),
            Edge("gate", "canary", label="yes"),
            Edge("canary", "live"),
            Edge("live", "ask", "vhv", mid=HEADER_H + 3 * ROW_H + 2 * LANE_PAD + 2),
            Edge("signin", "ask"),
            Edge("files", "ask", "hv"),
            Edge("ask", "answer"),
            Edge("answer", "saved"),
            Edge("ask", "expert", "vh", label="no answer", dashed=True),
            Edge("expert", "approvals", dashed=True),
        ],
    )
)

diagram(
    Diagram(
        "asking-a-question",
        "Asking a question",
        "Grounded or silent: an answer is shown only when its sources support it.",
        5,
        [
            Lane("Person", "asks"),
            Lane("Veyntora", "checks and answers", 2),
            Lane("Expert team", "answers hand-offs"),
        ],
        [
            Box("ask", 0, 0, "Ask a question", ("any channel",), "start"),
            Box("answer", 0, 4, "Answer shown", ("numbered citations,", "source viewer"), "good"),
            Box("budget", 1, 0, "Limits OK?", ("budgets, per-person",), "decision"),
            Box("refused", 1, 0, "Refused", ("reason shown, or", "Fast only"), "stop", row=1),
            Box("mode", 1, 1, "Which mode?", ("Auto: router picks",), "decision"),
            Box("fast", 1, 2, "Fast", ("one search, only in", "documents they may open")),
            Box("agent", 1, 2, "Agent", ("plans, searches,", "uses tools"), row=1),
            Box("grounded", 1, 3, "Grounded?", ("sources support it",), "decision"),
            Box(
                "none", 1, 3, "No answer found", ("nothing unsupported", "is shown"), "stop", row=1
            ),
            Box(
                "expert",
                2,
                3,
                "Expert answers",
                ("in chat, Teams,", "or e-mail"),
            ),
            Box("kb", 2, 4, "Saved for groups", ("once an owner", "accepts it"), "good"),
        ],
        [
            Edge("ask", "budget", "v"),
            Edge("budget", "refused", "v", label="over"),
            Edge("budget", "mode", label="ok"),
            Edge("mode", "fast", label="Fast"),
            Edge("mode", "agent", "vh", label="Agent", lseg=1),
            Edge("fast", "agent", "v", label="weak, in Auto", dashed=True),
            Edge("fast", "grounded"),
            Edge("agent", "grounded", "hvh", mid=LABEL_W + PAD_X + 3 * COL_W - 2),
            Edge("grounded", "answer", "hv", label="yes", lseg=1),
            Edge("grounded", "none", "v", label="no"),
            Edge("none", "expert", "v", label="Ask an expert"),
            Edge("expert", "kb", dashed=True),
        ],
    )
)

diagram(
    Diagram(
        "agent-approval",
        "Agent actions that need approval",
        "No write without approval, and never by the person who asked.",
        5,
        [
            Lane("Person", "asks in Agent mode"),
            Lane("Veyntora", "runs the agent"),
            Lane("Approver", "tool's approver group"),
        ],
        [
            Box("ask", 0, 0, "Ask the agent", ("to change something",), "start"),
            Box("finish", 0, 4, "Answer finished", ("every step shown",), "good"),
            Box("wants", 1, 0, "Agent wants to act", ("write or destructive",)),
            Box("request", 1, 1, "Approval request", ("on the Approvals page",)),
            Box("runs", 1, 3, "Tool runs", ("recorded in the", "audit log"), "good"),
            Box(
                "without", 1, 4, "Goes on without it", ("no reply in 24 h", "counts as no"), "stop"
            ),
            Box("told", 2, 1, "Approvers told", ("never the asker",)),
            Box("decide", 2, 2, "Approve?", ("note optional",), "decision"),
        ],
        [
            Edge("ask", "wants", "v"),
            Edge("wants", "request"),
            Edge("request", "told", "v"),
            Edge("told", "decide"),
            Edge("decide", "runs", "vh", label="yes", lseg=0),
            Edge("decide", "without", "hv", label="no", lseg=0),
            Edge("runs", "finish", "vh"),
            Edge("without", "finish", "v"),
        ],
    )
)

diagram(
    Diagram(
        "my-files",
        "My files",
        "A file is searchable only after a clean scan, and only by its owner.",
        4,
        [Lane("Person", "uploads"), Lane("Veyntora", "checks and indexes", 2)],
        [
            Box("choose", 0, 0, "Choose files", ("up to 200 at once",), "start"),
            Box("ready", 0, 3, "Ready", ("only the owner's", "chats search it"), "good"),
            Box("limits", 1, 0, "Within limits?", ("size, storage",), "decision"),
            Box("refused", 1, 0, "Refused", ("nothing is stored",), "stop", row=1),
            Box("scan", 1, 1, "Virus scan clean?", ("before indexing",), "decision"),
            Box("virus", 1, 1, "Virus found", ("never indexed",), "stop", row=1),
            Box("index", 1, 2, "Parsed, indexed", ("parse error: Failed",)),
        ],
        [
            Edge("choose", "limits", "v"),
            Edge("limits", "refused", "v", label="over"),
            Edge("limits", "scan", label="ok"),
            Edge("scan", "virus", "v", label="no"),
            Edge("scan", "index", label="yes"),
            Edge("index", "ready", "hv"),
        ],
    )
)

diagram(
    Diagram(
        "chatbot-life",
        "A chatbot's life",
        "A draft reaches everyone only through the eval gate and a canary.",
        5,
        [Lane("Chatbot team", "editors and owners", 2), Lane("Veyntora", "checks and guards")],
        [
            Box("wizard", 0, 0, "Create", ("wizard, five steps",), "start"),
            Box("edit", 0, 1, "Edit the draft", ("pipeline, flow;", "Playground test")),
            Box("eval", 0, 2, "Run evaluation", ("required sets,", "against live")),
            Box("canary", 0, 3, "Canary", ("10%, then 50%",), row=1),
            Box("live", 0, 4, "Promote", ("live for everyone",), "good", row=1),
            Box("gate", 1, 2, "Gate passed?", ("faithfulness,", "relevance, no drop"), "decision"),
            Box("guard", 1, 3, "Guard", ("every 5 min; rolls", "back if clearly worse")),
            Box("back", 1, 4, "Earlier version", ("live again, with", "a reason, audited"), "stop"),
        ],
        [
            Edge("wizard", "edit"),
            Edge("edit", "eval"),
            Edge("eval", "gate", "v"),
            Edge("gate", "edit", "hv", label="no: fix", lseg=0),
            Edge(
                "gate",
                "canary",
                "hvh",
                label="yes",
                lseg=1,
                mid=LABEL_W + PAD_X + 3 * COL_W - (COL_W - CARD_W) / 2,
            ),
            Edge("canary", "live"),
            Edge("canary", "guard", "v", dashed=True, label="watched"),
            Edge("guard", "back", dashed=True),
            Edge("live", "back", "v", label="roll back"),
        ],
    )
)

diagram(
    Diagram(
        "data-sources",
        "Data sources",
        "Every document carries its readers; one nobody may read is never found.",
        5,
        [Lane("Knowledge admin", "connects sources"), Lane("Veyntora", "tests, syncs, maps")],
        [
            Box(
                "connect", 0, 0, "Connect source", ("type, settings,", "secret to OpenBao"), "start"
            ),
            Box("choose", 0, 3, "Choose readers", ("per source, or per", "database row")),
            Box("test", 1, 0, "Test OK?", ("connection check",), "decision"),
            Box("sync", 1, 1, "Sync", ("schedule or", "Sync now")),
            Box("perms", 1, 2, "Own permissions?", ("SharePoint, Confluence,", "SMB, CMIS"), "decision"),
            Box("mapped", 1, 3, "Map permissions", ("unmapped readers", "are dropped")),
            Box("ready", 1, 4, "Searchable", ("by its readers,", "on every question"), "good"),
        ],
        [
            Edge("connect", "test", "v", dx=-28),
            Edge("test", "connect", "v", dx=28, label="no: fix", dashed=True),
            Edge("test", "sync", label="yes"),
            Edge("sync", "perms"),
            Edge("perms", "mapped", label="yes"),
            Edge("perms", "choose", "vh", label="no", lseg=0),
            Edge("choose", "ready", "hv"),
            Edge("mapped", "ready"),
        ],
    )
)

diagram(
    Diagram(
        "usage-and-budgets",
        "Usage and budgets",
        "Per-person limits first; then, of the budgets at their limit, the strictest action wins.",
        5,
        [Lane("Person or app", "asks"), Lane("Veyntora", "checks every run", 3)],
        [
            Box("ask", 0, 0, "Ask a question", ("person or app key",), "start"),
            Box(
                "limits",
                1,
                0,
                "Per-person limits",
                ("questions, Agent", "runs, storage"),
                "decision",
            ),
            Box("over", 1, 0, "Over a limit", ("refused, or Agent", "mode off"), "stop", row=1),
            Box("budgets", 1, 1, "Budgets apply", ("chatbot, groups,", "cost centre")),
            Box("any", 1, 2, "Any at its limit?", ("this period",), "decision"),
            Box("usual", 1, 3, "Answer as usual", ("spend recorded",), "good"),
            Box("strict", 1, 2, "Strictest wins", ("of the budgets", "at their limit"), row=1),
            Box("block", 1, 1, "Block", ("refused, reason", "shown"), "stop", row=2),
            Box("fast", 1, 2, "Fast only", ("Agent mode off",), row=2),
            Box("small", 1, 3, "Smaller model", ("the budget's", "fallback"), row=2),
            Box("notify", 1, 4, "Notify", ("nothing changes", "for people"), row=2),
        ],
        [
            Edge("ask", "limits", "v"),
            Edge("limits", "over", "v", label="over"),
            Edge("limits", "budgets", label="ok"),
            Edge("budgets", "any"),
            Edge("any", "usual", label="no"),
            Edge("any", "strict", "v", label="yes"),
            Edge("strict", "block", "vhv"),
            Edge("strict", "fast", "v"),
            Edge("strict", "small", "vhv"),
            Edge("strict", "notify", "vhv"),
        ],
    )
)

diagram(
    Diagram(
        "data-subject-requests",
        "Data subject requests",
        "Nothing is erased or exported without a DPO who did not ask for it.",
        5,
        [
            Lane("Handler", "Governance editor\nor DPO"),
            Lane("DPO", "never the requester"),
            Lane("Veyntora", "carries it out", 2),
            Lane("Legal", "holds"),
        ],
        [
            Box("record", 0, 0, "Record request", ("erasure or export",), "start"),
            Box("held", 0, 1, "What is held", ("shown on the page",)),
            Box("verify", 0, 2, "Verify identity", ("marked by handler",)),
            Box("approve", 1, 2, "DPO approves", ("a second person",)),
            Box("hold", 2, 2, "Legal hold?", ("on the person",), "decision"),
            Box("erase", 2, 3, "Erasure", ("data deleted; audit", "name pseudonymised")),
            Box("export", 2, 3, "Export", ("ZIP of profile, chats,", "answers, uploads"), row=1),
            Box("report", 2, 4, "Signed report", ("HMAC; hash in the", "audit log"), "good"),
            Box("blocked", 3, 2, "Blocked", ("until Legal lifts", "the hold"), "stop"),
        ],
        [
            Edge("record", "held"),
            Edge("held", "verify"),
            Edge("verify", "approve", "v"),
            Edge("approve", "hold", "v"),
            Edge("hold", "erase", label="no"),
            Edge("hold", "export", "vh", label="no", lseg=1),
            Edge("hold", "blocked", "v", dx=-44, label="yes"),
            Edge("erase", "report"),
            Edge("export", "report", "hv"),
        ],
    )
)

diagram(
    Diagram(
        "access-reviews",
        "Access reviews",
        "Owners confirm who still needs access; nothing undecided is removed.",
        4,
        [
            Lane("Veyntora", "starts rounds"),
            Lane("Owners", "chatbots, groups", 2),
            Lane("Platform admin", "closes rounds"),
        ],
        [
            Box("start", 0, 0, "Round starts", ("every 90 days", "or by hand"), "start"),
            Box("overdue", 0, 2, "Undecided", ("access stays;", "round overdue"), "stop"),
            Box("review", 1, 1, "Keep this grant?", ("role or membership",), "decision"),
            Box("keep", 1, 2, "Kept", ("access stays",), "good"),
            Box("revoke", 1, 2, "Revoked", ("audited; never the", "last owner"), "stop", row=1),
            Box("close", 2, 3, "Close the round", ("all decided",)),
        ],
        [
            Edge("start", "review", "vh"),
            Edge("review", "keep", label="keep"),
            Edge("review", "revoke", "vh", label="revoke", lseg=1),
            Edge("review", "overdue", "vh", dashed=True, label="nobody decides", lseg=0),
            Edge("keep", "close", "hv"),
            Edge("revoke", "close", "hv"),
            Edge("overdue", "close", "hv"),
        ],
    )
)

diagram(
    Diagram(
        "use-case-map",
        "Who does what",
        "Actors and their use cases (IDs as in use-cases.md).",
        3,
        [
            Lane("People", "", 2),
            Lane("Approvals", "", 2),
            Lane("Chatbot team", "", 2),
            Lane("Platform", "", 3),
            Lane("Governance", "", 4),
            Lane("System", ""),
        ],
        [
            Box("user", 0, 0, "User", kind="actor"),
            Box("u1", 0, 1, "Ask and get answers", ("U-01 to U-13",), "chip"),
            Box("u2", 0, 2, "Files, settings, keys", ("U-14 to U-24",), "chip"),
            Box("app", 0, 0, "App", ("API key",), "actor", row=1),
            Box("u3", 0, 1, "Ask through the API", ("U-25",), "chip", row=1),
            Box("approver", 1, 0, "Approver", kind="actor"),
            Box("e1", 1, 1, "Decide agent actions", ("E-01, E-02",), "chip"),
            Box("expert", 1, 0, "Expert", kind="actor", row=1),
            Box("e2", 1, 1, "Answer hand-offs", ("E-03 to E-05",), "chip", row=1),
            Box("editor", 2, 0, "Editor", kind="actor"),
            Box("c1", 2, 1, "Build and test", ("C-01 to C-10",), "chip"),
            Box("owner", 2, 0, "Owner", kind="actor", row=1),
            Box("c2", 2, 1, "Access, gate", ("C-08, C-11",), "chip", row=1),
            Box("c3", 2, 2, "Publish, roll back", ("C-12 to C-14",), "chip", row=1),
            Box("kadmin", 3, 0, "Knowledge admin", kind="actor"),
            Box("a1", 3, 1, "Data sources, health", ("A-01 to A-04",), "chip"),
            Box("padmin", 3, 0, "Platform admin", kind="actor", row=1),
            Box("a2", 3, 1, "Providers, channels", ("A-05, A-06, A-08, A-09",), "chip", row=1),
            Box("a3", 3, 2, "Automations, people", ("A-10 to A-14",), "chip", row=1),
            Box("secrev", 3, 0, "Security reviewer", kind="actor", row=2),
            Box("a4", 3, 1, "Sign off MCP tools", ("A-07",), "chip", row=2),
            Box("geditor", 4, 0, "Gov. editor", kind="actor"),
            Box("g1", 4, 1, "Retention, notice", ("G-01 to G-03",), "chip"),
            Box("legal", 4, 0, "Legal", kind="actor", row=1),
            Box("g2", 4, 1, "Legal holds", ("G-04",), "chip", row=1),
            Box("dpo", 4, 0, "DPO", kind="actor", row=2),
            Box("g3", 4, 1, "Erasure, export", ("G-05, G-06",), "chip", row=2),
            Box("g4", 4, 2, "Access reviews", ("G-07, with owners",), "chip", row=2),
            Box("auditor", 4, 0, "Auditor", kind="actor", row=3),
            Box("g5", 4, 1, "Audit log, chain", ("G-08, G-09",), "chip", row=3),
            Box("system", 5, 0, "System", kind="actor"),
            Box("s1", 5, 1, "Purge, archive, guard", ("S-01 to S-03",), "chip"),
            Box("s2", 5, 2, "Alerts, scans, rounds", ("S-04 to S-06",), "chip"),
        ],
        [
            Edge("user", "u1"),
            Edge("u1", "u2", dashed=True),
            Edge("app", "u3"),
            Edge("approver", "e1"),
            Edge("expert", "e2"),
            Edge("editor", "c1"),
            Edge("owner", "c2"),
            Edge("c2", "c3", dashed=True),
            Edge("kadmin", "a1"),
            Edge("padmin", "a2"),
            Edge("a2", "a3", dashed=True),
            Edge("secrev", "a4"),
            Edge("geditor", "g1"),
            Edge("legal", "g2"),
            Edge("dpo", "g3"),
            Edge("g3", "g4", dashed=True),
            Edge("auditor", "g5"),
            Edge("system", "s1"),
            Edge("s1", "s2", dashed=True),
        ],
        legend=False,
        col_w=236,
        card_w=200,
        row_h=84,
    )
)


def main() -> int:
    problems = 0
    for d in DIAGRAMS:
        svg, warn = render(d)
        (OUT / f"{d.name}.svg").write_text(svg)
        for w in warn:
            print(f"{d.name}: {w}", file=sys.stderr)
            problems += 1
    print(f"{len(DIAGRAMS)} diagrams written to {OUT}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
