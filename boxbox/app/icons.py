"""Small inline SVG icons for the replay: track flags, tyres and the sky.

Every icon is decorative (`aria-hidden`) and sits next to the word it stands for, so
neither colour nor shape carries meaning alone. They are drawn here, so no image file
or licence comes with them, and the tyres carry no maker's logo.
"""

from __future__ import annotations

import math

from . import panels as P

TYRE_COLOURS = {**P.COMPOUND_COLOURS, "INTERMEDIATE": "#43b02a", "WET": "#0067ad"}
YELLOW, BLUE = P.STATUS_COLOURS["SC"], "#1d4ed8"
FLAG_COLOURS = {**P.STATUS_COLOURS, "YELLOW": YELLOW, "BLUE": BLUE}
OUTLINE = 'stroke="var(--bx-ring)" stroke-width="1"'  # yellow and white show on white
CLOUD = "M7 17h10a4 4 0 0 0 .4-8 5.5 5.5 0 0 0-10.5 1.4A3.3 3.3 0 0 0 7 17z"


def _icon(shapes: str, box: str = "0 0 24 24", kind: str = "") -> str:
    return (
        f'<svg class="icon {kind}" viewBox="{box}" aria-hidden="true" '
        f'focusable="false">{shapes}</svg>'
    )


def _board(text: str) -> str:
    return (
        f'<rect x="0.5" y="0.5" width="29" height="19" rx="2" fill="{YELLOW}" {OUTLINE}/>'
        f'<text x="15" y="14" text-anchor="middle" font-size="{11 if len(text) < 3 else 9}" '
        f'font-weight="800" fill="#111">{text}</text>'
    )


def flag(kind: str) -> str:
    """A track flag, or the SC and VSC boards race control shows."""
    if kind in ("SC", "VSC"):
        shapes = _board(kind)
    elif kind == "DOUBLE YELLOW":
        shapes = "".join(
            f'<rect x="{x}" y="0.5" width="13" height="19" fill="{YELLOW}" {OUTLINE}/>'
            for x in (0.5, 16.5)
        )
    elif kind == "CHEQUERED":
        checks = "".join(
            f'<rect x="{x * 5}" y="{y * 5}" width="5" height="5" fill="#111"/>'
            for x in range(6)
            for y in range(4)
            if (x + y) % 2 == 0
        )
        shapes = f'<rect x="0" y="0" width="30" height="20" fill="#fff"/>{checks}'
        shapes += (
            f'<rect x="0.5" y="0.5" width="29" height="19" fill="none" {OUTLINE}/>'
        )
    else:
        colour = FLAG_COLOURS.get(kind, P.NEUTRAL)
        shapes = (
            f'<rect x="0.5" y="0.5" width="29" height="19" fill="{colour}" {OUTLINE}/>'
        )
    return _icon(shapes, "0 0 30 20", "flag")


def tyre(compound: str | None) -> str:
    """A dark tyre with the compound's coloured band and letter."""
    colour = TYRE_COLOURS.get(compound or "", P.NEUTRAL)
    letter = (compound or "?")[0] if compound in TYRE_COLOURS else "?"
    return _icon(
        f'<circle cx="12" cy="12" r="11" fill="#1f2937" {OUTLINE}/>'
        f'<circle cx="12" cy="12" r="8.5" fill="none" stroke="{colour}" stroke-width="2.5"/>'
        f'<text x="12" y="16" text-anchor="middle" font-size="11" font-weight="800" '
        f'fill="#fff">{letter}</text>',
        kind="tyre",
    )


def _rays(cx: float, cy: float, r: float, inner: float, outer: float) -> str:
    rays = []
    for k in range(8):
        a = math.radians(k * 45)
        x1, y1 = cx + inner * math.cos(a), cy + inner * math.sin(a)
        x2, y2 = cx + outer * math.cos(a), cy + outer * math.sin(a)
        rays.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"/>')
    return f'<circle cx="{cx}" cy="{cy}" r="{r}"/>' + "".join(rays)


def _drops(xs: tuple[int, ...]) -> str:
    return "".join(f'<line x1="{x}" y1="17" x2="{x - 1.5}" y2="21"/>' for x in xs)


def weather(kind: str) -> str:
    """The sky, in the text colour, so it follows the light or dark appearance."""
    raised = f'<path d="{CLOUD}" transform="translate(0 -3)"/>'
    shapes = {
        "sun": _rays(12, 12, 4, 6.5, 9),
        "moon": '<path d="M15 4a8 8 0 1 0 5 13A7 7 0 0 1 15 4z"/>',
        "partly": _rays(8, 8, 3, 4.8, 6.6)
        + f'<path d="{CLOUD}" transform="translate(2 2)"/>',
        "cloud": f'<path d="{CLOUD}"/>',
        "fog": "".join(
            f'<line x1="4" y1="{y}" x2="20" y2="{y}"/>' for y in (8, 12, 16)
        ),
        "drizzle": raised + _drops((9, 15)),
        "rain": raised + _drops((7, 12, 17)),
        "storm": raised + '<path d="M13 14l-3 4h3l-2 4"/>',
    }.get(kind, '<circle cx="12" cy="12" r="8" stroke-dasharray="3 3"/>')
    return _icon(
        f'<g fill="none" stroke="currentColor" stroke-width="1.8" '
        f'stroke-linecap="round" stroke-linejoin="round">{shapes}</g>',
        kind="sky",
    )


def sky(code: float | None, is_day: float | None = 1) -> str:
    """The icon kind for a WMO weather code, as Open-Meteo gives it."""
    if code is None or (isinstance(code, float) and math.isnan(code)):
        return "unknown"
    code = int(code)
    if code >= 95:
        return "storm"
    if code >= 61:  # shortcut: snow drawn as rain, never seen on a race day
        return "rain"
    if code >= 51:
        return "drizzle"
    if code >= 45:
        return "fog"
    if code == 3:
        return "cloud"
    if code in (1, 2):
        return "partly" if is_day else "moon"
    return "sun" if is_day else "moon"


METRIC_SHAPES = {
    "air": '<path d="M10 14V5a2 2 0 1 1 4 0v9a4 4 0 1 1-4 0z"/><path d="M12 9v7"/>',
    "track": (
        '<path d="M10 11V4a2 2 0 1 1 4 0v7a3.5 3.5 0 1 1-4 0z"/>'
        '<path d="M3 20h18"/><path d="M6 23h3m3 0h3m3 0h2"/>'
    ),
    "humidity": '<path d="M12 3c3 4 6 7.5 6 11a6 6 0 0 1-12 0c0-3.5 3-7 6-11z"/>',
    "wind": '<path d="M3 9h11a3 3 0 1 0-3-3"/><path d="M3 15h15a3 3 0 1 1-3 3"/>',
}


def metric(kind: str) -> str:
    """A weather reading's icon, drawn like the sky icons, in the text colour."""
    return _icon(
        f'<g fill="none" stroke="currentColor" stroke-width="1.8" '
        f'stroke-linecap="round" stroke-linejoin="round">{METRIC_SHAPES[kind]}</g>',
        "0 0 24 24",
        "metric",
    )
