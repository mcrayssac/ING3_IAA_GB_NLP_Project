"""What the screen shows about a card and an answer, computed from the card only."""

from __future__ import annotations

import html
import math
from typing import Any

from matplotlib.figure import Figure

from boxbox.rules import TYRE_LIMITS, decide, remove_field
from boxbox.rules.decision import laps

MARGIN = 2.0  # rejoin margin and gap-ahead limit of the policy, in seconds
CALLS = ("BOX", "STAY OUT", "NO CALL")
CALL_COLOURS = {"BOX": "#f28c28", "STAY OUT": "#4c8df6", "NO CALL": "#9aa0a6"}
COMPOUND_COLOURS = {"SOFT": "#da291c", "MEDIUM": "#ffd12e", "HARD": "#f0f0ec"}
STATUS_COLOURS = {
    "GREEN": "#2dbe60",
    "SC": "#ffd12e",
    "VSC": "#ffd12e",
    "RED": "#e5484d",
}
INK, PANEL, GRID = "#e6e8eb", "#16181d", "#3a3f47"
# rows of the decision inputs: label and the card field remove_field makes unknown
INPUTS = (
    ("Tyre age", "tyre_age_laps"),
    ("Gap ahead", "gap_ahead"),
    ("Gap behind", "gap_behind"),
    ("Pit loss", "pit_loss_seconds"),
    ("Track status", "track_status"),
    ("Surface", "surface"),
)


def _number(value: Any) -> float | None:
    """A finite non-negative number, or None for anything the contract calls unknown."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and value >= 0 else None


def gap(card: dict[str, Any], side: str) -> tuple[str, float | None]:
    """("KNOWN", seconds), ("NONE", None) or ("UNKNOWN", None) for one neighbour."""
    value = card.get(side)
    if not isinstance(value, dict):
        return "UNKNOWN", None
    if value.get("state") == "NONE" and value.get("seconds") is None:
        return "NONE", None
    seconds = _number(value.get("seconds"))
    known = value.get("state") == "KNOWN" and seconds is not None
    return ("KNOWN", seconds) if known else ("UNKNOWN", None)


def _chip(text: Any, colour: str) -> str:
    return f'<span class="chip" style="--chip:{colour}">{html.escape(str(text))}</span>'


def situation(card: dict[str, Any]) -> str:
    """The strip above the charts: race, lap, car, track status, surface and tyres."""
    race = card.get("race") if isinstance(card.get("race"), dict) else {}
    status = str(
        card.get("track_status") or "UNKNOWN"
    )  # str: an upload may hold anything
    compound = str(card.get("compound") or "UNKNOWN")
    age = card.get("tyre_age_laps")
    known = isinstance(age, int) and not isinstance(age, bool) and age >= 0
    tyres = f"{compound} {laps(age) if known else 'age unknown'}"
    title = f"{race.get('season', '?')} {race.get('event', 'Unknown event')}"
    lap = f"Lap {card.get('lap', '?')}/{card.get('total_laps', '?')}"
    return (
        f'<div class="situation"><div class="race">{html.escape(title)}</div>'
        f'<div class="mono">{html.escape(lap)} &nbsp; Car {html.escape(str(card.get("driver_number", "?")))}</div>'
        f"<div>{_chip(status, STATUS_COLOURS.get(status, GRID))}"
        f"{_chip(card.get('surface') or 'UNKNOWN', GRID)}"
        f"{_chip(tyres, COMPOUND_COLOURS.get(compound, GRID))}</div></div>"
    )


def _gap_text(card: dict[str, Any], side: str) -> tuple[str, bool]:
    state, seconds = gap(card, side)
    if state == "NONE":
        return "no car", True
    if state == "UNKNOWN":
        return "unknown", False
    number = card[side].get("driver_number")
    return f"{seconds:.1f} s" + (f" (car {number})" if number else ""), True


def input_value(card: dict[str, Any], field: str) -> tuple[str, bool]:
    """How one decision input reads on the card, and whether its value is known."""
    if field in ("gap_ahead", "gap_behind"):
        return _gap_text(card, field)
    if field == "tyre_age_laps":
        age = card.get(field)
        known = isinstance(age, int) and not isinstance(age, bool) and age >= 0
        return (f"{laps(age)} on {card.get('compound')}" if known else "missing"), known
    if field == "pit_loss_seconds":
        loss = _number(card.get(field))
        if loss is None:
            return "missing", False
        return (
            f"{loss:.1f} s, estimated by lap {card.get('pit_loss_as_of_completed_lap')}",
            True,
        )
    value = card.get(field)
    return (str(value), True) if value not in (None, "UNKNOWN") else ("unknown", False)


def used_by_rule(card: dict[str, Any], field: str) -> bool:
    """Whether making this field unknown changes the rule's call on the card."""
    return decide(remove_field(card, field))[0] != decide(card)[0]


def _rule_cell(card: dict[str, Any], field: str, known: bool) -> str:
    if not known:
        return "<td>unknown on the card</td>"
    return f"<td>{'used' if used_by_rule(card, field) else 'not used'}</td>"


def inputs_table(card: dict[str, Any], with_rule: bool) -> str:
    """The decision inputs; unknown rows are highlighted, the rule column is optional.

    On a NO CALL card no input decides a stop, so the column gives way to one line.
    """
    column = with_rule and decide(card)[0] != "NO CALL"
    head = "<tr><th>Input</th><th>On the card</th>" + (
        "<th>Rule</th>" if column else ""
    )
    rows = []
    for label, field in INPUTS:
        text, known = input_value(card, field)
        rule = _rule_cell(card, field, known) if column else ""
        flag = "" if known else ' class="unknown"'
        value = f"<td class=mono>{html.escape(text)}</td>"
        rows.append(f"<tr{flag}><td>{label}</td>{value}{rule}</tr>")
    note = ""
    if with_rule and not column:
        note = '<div class="note">The rule gives NO CALL on this card, for the reason above.</div>'
    return f'<table class="inputs">{head}</tr>{"".join(rows)}</table>{note}'


def tyre_zones(card: dict[str, Any]) -> tuple[int, int, int, int] | str:
    """(young, old, age, end of the bar) for the tyre window, or why it is not drawn."""
    compound = card.get("compound")
    limits = TYRE_LIMITS.get(compound) if isinstance(compound, str) else None
    age = card.get("tyre_age_laps")
    if limits is None:
        return f"No tyre window for {compound or 'an unknown'} compound."
    if not isinstance(age, int) or isinstance(age, bool) or age < 0:
        return "No tyre window: the tyre age is missing."
    young, old = limits
    return young, old, age, max(age, old) + 4


def circle_points(card: dict[str, Any]) -> dict[str, Any] | str:
    """Angles in degrees, clockwise from the card's car, or why the circle is not drawn."""
    lap = _number(card.get("reference_lap_seconds"))
    if not lap:
        return "No circle: the card has no reference lap time."
    points = {"ahead": None, "behind": None, "rejoin": None, "band_end": None}
    points |= {"cleared": None, "notes": []}
    for side, key, sign in (("gap_ahead", "ahead", 1), ("gap_behind", "behind", -1)):
        state, seconds = gap(card, side)
        if state == "KNOWN":
            points[key] = sign * seconds / lap * 360
        else:
            points["notes"].append(
                f"Car {key}: {'no car' if state == 'NONE' else 'gap unknown'}"
            )
    loss = _number(card.get("pit_loss_seconds"))
    if loss is None:
        points["notes"].append("No rejoin point: the pit loss is missing.")
        return points
    points["rejoin"], points["band_end"] = (
        -loss / lap * 360,
        -(loss + MARGIN) / lap * 360,
    )
    state, behind = gap(card, "gap_behind")
    if state == "KNOWN":
        points["cleared"] = behind >= loss + MARGIN  # rule 6: equality clears
    return points


def _figure(width: float, height: float, polar: bool = False) -> tuple[Figure, Any]:
    fig = Figure(figsize=(width, height), facecolor=PANEL)
    ax = fig.add_subplot(projection="polar" if polar else None, facecolor=PANEL)
    ax.tick_params(colors=INK, labelsize=8)
    for spine in ax.spines.values():
        spine.set_color(GRID)
    return fig, ax


def message_figure(text: str) -> Figure:
    """A small panel that says why a chart is not drawn."""
    fig, ax = _figure(5, 1.2)
    ax.axis("off")
    ax.text(0.5, 0.5, text, color=INK, ha="center", va="center", fontsize=10)
    return fig


def circle_of_doom(card: dict[str, Any]) -> Figure:
    """One lap in time: the car on top, its neighbours, the rejoin point and margin."""
    points = circle_points(card)
    if isinstance(points, str):
        return message_figure(points)
    fig, ax = _figure(4.4, 4.6, polar=True)
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)  # cars run clockwise
    ax.set_ylim(0, 1.45)  # room for the labels outside the ring
    ax.set_yticks([])
    ax.set_xticks([])
    ax.plot([math.radians(d) for d in range(361)], [1] * 361, color=GRID, lw=6)
    if points["rejoin"] is not None:
        band = [
            math.radians(
                points["rejoin"] + step * (points["band_end"] - points["rejoin"]) / 20
            )
            for step in range(21)
        ]
        ax.plot(band, [1] * 21, color=CALL_COLOURS["BOX"], lw=10, alpha=0.6)
        ax.plot(
            [math.radians(points["rejoin"])], [1], "o", color=CALL_COLOURS["BOX"], ms=9
        )
    _car(ax, 0, "car", INK)
    behind = (
        "cleared"
        if points["cleared"]
        else "not cleared"
        if points["cleared"] is False
        else ""
    )
    if points["ahead"] is not None:
        _car(ax, points["ahead"], "ahead", INK)
    if points["behind"] is not None:
        _car(ax, points["behind"], f"behind {behind}".strip(), CALL_COLOURS["STAY OUT"])
    notes = points["notes"] + [
        "Assumes a fixed pit loss and that the other cars keep their pace."
    ]
    fig.text(0.5, 0.02, "\n".join(notes), color=INK, ha="center", fontsize=8)
    return fig


def _car(ax: Any, degrees: float, label: str, colour: str) -> None:
    theta = math.radians(degrees)
    ax.plot([theta], [1], "o", color=colour, ms=11, markeredgecolor=PANEL)
    side = math.sin(theta)  # labels lean outwards so they never sit on the ring
    align = "left" if side > 0.3 else "right" if side < -0.3 else "center"
    ax.text(theta, 1.16, label, color=colour, ha=align, va="center", fontsize=8)


def tyre_window(card: dict[str, Any]) -> Figure:
    """The tyre age on a bar split by the compound's policy thresholds."""
    zones = tyre_zones(card)
    if isinstance(zones, str):
        return message_figure(zones)
    young, old, age, end = zones
    fig, ax = _figure(5, 1.7)
    fig.subplots_adjust(bottom=0.34, top=0.84)  # room for the caption
    spans = (
        (0, young, CALL_COLOURS["STAY OUT"], "too young"),
        (young, old, COMPOUND_COLOURS["MEDIUM"], "window"),
        (old, end, CALL_COLOURS["BOX"], "opportunity"),
    )
    for start, stop, colour, label in spans:
        ax.barh(0, stop - start, left=start, color=colour, alpha=0.55, height=0.5)
        ax.text(
            (start + stop) / 2,
            0,
            label,
            color=INK,
            ha="center",
            va="center",
            fontsize=8,
        )
    ax.axvline(age, color=INK, lw=3)
    ax.text(age, 0.42, laps(age), color=INK, ha="center", fontsize=9, fontweight="bold")
    ax.set_xlim(0, end)
    ax.set_ylim(-0.6, 0.6)
    ax.set_yticks([])
    ax.set_xticks([0, young, old])
    ax.set_xlabel(
        f"Window: a stop needs the car ahead within {MARGIN:.1f} s.",
        color=INK,
        fontsize=8,
    )
    ax.set_title(f"{card['compound']} tyre window", color=INK, fontsize=9, loc="left")
    return fig


def parse_answer(text: Any) -> tuple[str, str] | None:
    """(call, why) when the answer is exactly the two contract lines, else None."""
    lines = text.split("\n") if isinstance(text, str) else []
    if (
        len(lines) != 2
        or not lines[0].startswith("CALL: ")
        or not lines[1].startswith("WHY: ")
    ):
        return None
    call, why = lines[0][len("CALL: ") :], lines[1][len("WHY: ") :]
    return (call, why) if call in CALLS and why.strip() else None


def banner(answer: str | None) -> str:
    """The latest call in large text, or what stops it from being read."""
    if answer is None:
        return '<div class="banner idle">Ask about this lap</div>'
    parsed = parse_answer(answer)
    if parsed is None:
        return '<div class="banner bad">Answer not in CALL/WHY format</div>'
    call, why = parsed
    return (
        f'<div class="banner" style="--call:{CALL_COLOURS[call]}">'
        f'<div class="call">{call}</div><div class="why">{html.escape(why)}</div></div>'
    )


def policy_panel(card: dict[str, Any], answer: str | None) -> str:
    """The rule's call on the card and whether the latest answer gives the same call."""
    call, why = decide(card)
    badge = ""
    parsed = parse_answer(answer) if answer is not None else None
    if parsed:
        same = parsed[0] == call
        badge = f'<span class="badge">{"Matches the rule" if same else "Differs from the rule"}</span>'
    return (
        f'<div class="policy"><b>Rule on this card:</b> {call} {badge}'
        f"<div>{html.escape(why)}</div>"
        "<div class=note>An out-of-scope request should differ: the assistant answers NO CALL to it.</div></div>"
    )
