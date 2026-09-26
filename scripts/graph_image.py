"""Draw the compiled LangGraph pipeline as an SVG for the README.

The node set and the edges are read from the compiled graph, so the diagram cannot drift from the code:
if a node is added or renamed, this script fails instead of drawing a stale picture. Compiling makes no
model calls.

Usage: uv run python -m scripts.graph_image
"""

from adlyser.config import ROOT, get_settings
from adlyser.graph import Pipeline

OUT = ROOT / "docs"

# node -> (kind, caption). kind: "code" = rules/emit, "ai" = a model call, "hybrid" = model + hard block.
NODES: dict[str, tuple[str, str]] = {
    "catalogue": ("ai", "any format → Brand schema + safety tags"),
    "measure": ("code", "VAD · shot cuts · black frames → candidate pauses"),
    "analyse": ("ai", "StretchAnalyst · vision · 1 call per stretch, parallel"),
    "boundaries": ("ai", "BoundaryJudge · scene change? break score 0–1"),
    "scenes": ("code", "merge stretches · safety tags = UNION"),
    "pace": ("code", "DP solver · max Σ score s.t. gap, rate, ad load"),
    "sweep": ("ai", "safety sweep of the whole scene · tags must cite frames"),
    "match": ("hybrid", "bge-m3 shortlist → rerank · HARD BLOCK either side"),
    "review": ("ai", "BreakReviewer · tools · approve | veto"),
    "settle": ("code", "route: another break point, another brand, or on"),
    "finalize": ("code", "no fit → promo · all blocked → drop the break"),
    "emit": ("code", "VMAP 1.0 + inline VAST · debug.json · slates"),
}

BANDS: list[tuple[str, int, int]] = [
    ("INPUT", 0, 1),
    ("JUDGEMENT · AI", 2, 3),
    ("SCENES + PACING", 4, 5),
    ("BRAND SAFETY", 6, 8),
    ("EMIT", 9, 11),
]

C = {
    "bg": "#0b0d12",
    "title": "#f2f4f8",
    "sub": "#8b919e",
    "band": "#11141b",
    "band_line": "#222834",
    "edge": "#3d4455",
    "back": "#8b7ad6",
    "code_fill": "#161a22",
    "code_stroke": "#2b3242",
    "ai_fill": "#191634",
    "ai_stroke": "#4d3f92",
    "hybrid_fill": "#1b2130",
    "hybrid_stroke": "#3f6b8a",
    "text": "#e7e9ee",
    "accent": "#a78bfa",
    "teal": "#5eead4",
}

W, NODE_W, NODE_H, STEP = 1300, 430, 62, 80
CX = 640
X0 = CX - NODE_W // 2
TOP = 176
H = TOP + len(NODES) * STEP + 110


def check_structure() -> list[tuple[str, str, bool]]:
    """Compile the graph and return its edges, asserting the drawn node set is the real one."""
    pipe = Pipeline(ROOT / "config.yaml", get_settings(), OUT)
    graph = pipe.build().get_graph()
    real = [n for n in graph.nodes if not n.startswith("__")]
    if real != list(NODES):
        raise SystemExit(f"graph changed: {real} != {list(NODES)}")
    return [(e.source, e.target, e.conditional) for e in graph.edges]


def cy(i: int) -> int:
    """Vertical centre of the i-th node."""
    return TOP + i * STEP + NODE_H // 2


def node_svg(i: int, name: str, kind: str, caption: str) -> str:
    """One rounded node box with its name and caption."""
    fill, stroke = C[f"{kind}_fill"], C[f"{kind}_stroke"]
    y = TOP + i * STEP
    dot = {"ai": C["accent"], "hybrid": C["teal"], "code": "#5b6478"}[kind]
    return f"""
  <g>
    <rect x="{X0}" y="{y}" width="{NODE_W}" height="{NODE_H}" rx="12"
          fill="{fill}" stroke="{stroke}" stroke-width="1.25"/>
    <circle cx="{X0 + 20}" cy="{y + 21}" r="4" fill="{dot}"/>
    <text x="{X0 + 34}" y="{y + 26}" fill="{C["text"]}" font-size="19"
          font-weight="600" letter-spacing="-0.2">{name}</text>
    <text x="{X0 + 34}" y="{y + 47}" fill="{C["sub"]}" font-size="12.5">{caption}</text>
  </g>"""


def band_svg(label: str, first: int, last: int) -> str:
    """A left-hand rail spanning a group of nodes."""
    y, height = TOP + first * STEP - 9, (last - first) * STEP + NODE_H + 18
    mid = y + height / 2
    return f"""
  <g>
    <rect x="150" y="{y}" width="{X0 - 190}" height="{height}" rx="10"
          fill="{C["band"]}" stroke="{C["band_line"]}" stroke-width="1"/>
    <text x="{150 + (X0 - 190) / 2:.0f}" y="{mid + 5:.0f}" fill="{C["sub"]}" font-size="12"
          font-weight="600" letter-spacing="1.6" text-anchor="middle">{label}</text>
  </g>"""


def straight(a: int, b: int) -> str:
    """Forward arrow between two adjacent nodes."""
    y1, y2 = TOP + a * STEP + NODE_H, TOP + b * STEP
    return f'  <line x1="{CX}" y1="{y1}" x2="{CX}" y2="{y2 - 8}" stroke="{C["edge"]}" stroke-width="1.6" marker-end="url(#arrow)"/>'


def back(src: int, dst: int, gutter: int, label: str) -> str:
    """Dashed loop-back arrow drawn in the right gutter."""
    ys, yd = cy(src), cy(dst)
    x = X0 + NODE_W
    return f"""
  <g>
    <path d="M {x} {ys} H {gutter - 14} Q {gutter} {ys} {gutter} {ys - 20}
             V {yd + 20} Q {gutter} {yd} {gutter - 14} {yd} H {x + 8}"
          fill="none" stroke="{C["back"]}" stroke-width="1.5" stroke-dasharray="5 4"
          marker-end="url(#arrow-back)"/>
    <text x="{gutter + 10}" y="{(ys + yd) / 2:.0f}" fill="{C["back"]}" font-size="12.5">{label}</text>
  </g>"""


def pill(y: int, text: str) -> str:
    """The START / END capsule."""
    return f"""
  <g>
    <rect x="{CX - 52}" y="{y}" width="104" height="30" rx="15" fill="none"
          stroke="{C["edge"]}" stroke-width="1.4"/>
    <text x="{CX}" y="{y + 20}" fill="{C["sub"]}" font-size="13" font-weight="600"
          letter-spacing="1.2" text-anchor="middle">{text}</text>
  </g>"""


def legend() -> str:
    """Key for the node colours."""
    items = [("AI decides", C["accent"]), ("model + hard block", C["teal"]), ("code enforces", "#5b6478")]
    out = []
    for i, (label, colour) in enumerate(items):
        x = 152 + i * 205
        out.append(
            f'  <circle cx="{x}" cy="{H - 52}" r="4.5" fill="{colour}"/>'
            f'<text x="{x + 14}" y="{H - 47}" fill="{C["sub"]}" font-size="13">{label}</text>'
        )
    return "\n".join(out)


def render(edges: list[tuple[str, str, bool]]) -> str:
    """Build the whole SVG document."""
    order = list(NODES)
    idx = {n: i for i, n in enumerate(order)}
    parts = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}"'
            ' font-family="system-ui, -apple-system, Segoe UI, Roboto, DejaVu Sans, sans-serif">'
        ),
        "  <defs>",
        f'    <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="{C["edge"]}"/></marker>',
        f'    <marker id="arrow-back" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="{C["back"]}"/></marker>',
        "  </defs>",
        f'  <rect width="{W}" height="{H}" fill="{C["bg"]}"/>',
        f'  <text x="150" y="58" fill="{C["title"]}" font-size="30" font-weight="650" letter-spacing="-0.6">ADlyser · ad-break pipeline</text>',
        f'  <text x="150" y="84" fill="{C["sub"]}" font-size="14.5">LangGraph state graph — measure with tools, decide with AI, guard with code</text>',
    ]
    parts += [band_svg(label, a, b) for label, a, b in BANDS]
    parts.append(pill(TOP - 66, "START"))
    parts.append(
        f'  <line x1="{CX}" y1="{TOP - 36}" x2="{CX}" y2="{TOP - 8}" stroke="{C["edge"]}" stroke-width="1.6" marker-end="url(#arrow)"/>'
    )
    for src, dst, conditional in edges:
        if src.startswith("__") or dst.startswith("__") or conditional:
            continue
        a, b = idx[src], idx[dst]
        if b == a + 1:
            parts.append(straight(a, b))
    parts.append(back(idx["settle"], idx["pace"], X0 + NODE_W + 200, "another break point"))
    parts.append(back(idx["settle"], idx["sweep"], X0 + NODE_W + 60, "another brand"))
    parts.append(straight(idx["settle"], idx["finalize"]))
    parts += [node_svg(i, n, *NODES[n]) for i, n in enumerate(order)]
    last = TOP + (len(order) - 1) * STEP + NODE_H
    parts.append(
        f'  <line x1="{CX}" y1="{last}" x2="{CX}" y2="{last + 22}" stroke="{C["edge"]}" stroke-width="1.6" marker-end="url(#arrow)"/>'
    )
    parts.append(pill(last + 30, "END"))
    parts.append(legend())
    parts.append("</svg>")
    return "\n".join(parts)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    svg = render(check_structure())
    (OUT / "pipeline.svg").write_text(svg)
    print(f"wrote {OUT / 'pipeline.svg'} ({len(svg)} bytes, {W}x{H})")
