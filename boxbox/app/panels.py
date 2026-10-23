"""What the screen shows about a card and an answer, computed from the card only."""

from __future__ import annotations

import html
import math
from typing import Any

from boxbox.rules import TYRE_LIMITS, decide, remove_field
from boxbox.rules.decision import laps

MARGIN = 2.0  # rejoin margin and gap-ahead limit of the policy, in seconds
CALLS = ("BOX", "STAY OUT", "NO CALL")
# colours are CSS variables of layout.py, so they follow the light or dark appearance
CALL_COLOURS = {
    "BOX": "var(--bx-box)",
    "STAY OUT": "var(--bx-stay)",
    "NO CALL": "var(--bx-nocall)",
}
# flag and Pirelli colours, used only for the dots of the chips
COMPOUND_COLOURS = {"SOFT": "#da291c", "MEDIUM": "#ffd12e", "HARD": "#f0f0ec"}
STATUS_COLOURS = {
    "GREEN": "#2dbe60",
    "SC": "#ffd12e",
    "VSC": "#ffd12e",
    "RED": "#e5484d",
}
NEUTRAL = "#94a3b8"
ASSUMPTION = "Assumes a fixed pit loss and that the other cars keep their pace."
CIRCLE_WIDTH, CIRCLE_HEIGHT, RADIUS = 440, 300, 105
CENTRE = (CIRCLE_WIDTH / 2, CIRCLE_HEIGHT / 2)
TYRE_WIDTH = 440
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
    return f'<span class="chip"><i style="background:{colour}"></i>{html.escape(str(text))}</span>'


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
        f"<div>{_chip(status, STATUS_COLOURS.get(status, NEUTRAL))}"
        f"{_chip(card.get('surface') or 'UNKNOWN', NEUTRAL)}"
        f"{_chip(tyres, COMPOUND_COLOURS.get(compound, NEUTRAL))}</div></div>"
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
        mark = "" if known else '<span class="mark" aria-hidden="true">?</span> '
        value = f"<td class=mono>{mark}{html.escape(text)}</td>"
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
    points["cleared"] = None
    for side, key, sign in (("gap_ahead", "ahead", 1), ("gap_behind", "behind", -1)):
        state, seconds = gap(card, side)
        if state == "KNOWN":
            points[key] = sign * seconds / lap * 360
    loss = _number(card.get("pit_loss_seconds"))
    if loss is None:
        return points
    points["rejoin"] = -loss / lap * 360
    points["band_end"] = -(loss + MARGIN) / lap * 360
    state, behind = gap(card, "gap_behind")
    if state == "KNOWN":
        points["cleared"] = (
            round(behind - loss - MARGIN, 1) >= 0
        )  # rule 6: equality clears
    return points


def _car_name(card: dict[str, Any], side: str) -> str:
    number = (
        card[side].get("driver_number") if isinstance(card.get(side), dict) else None
    )
    return f"Car {number}" if number else "The car"


def _neighbour(card: dict[str, Any], side: str, where: str, loss: float | None) -> str:
    state, seconds = gap(card, side)
    if state != "KNOWN":
        return f"No car {where}." if state == "NONE" else f"Gap {where} unknown."
    text = f"{_car_name(card, side)} {where} at {seconds:.1f} s"
    if where == "behind" and loss is not None:
        room = round(seconds - loss - MARGIN, 1)
        text += (
            f" clears the margin by {room:.1f} s"
            if room >= 0
            else f" is {-room:.1f} s short of it"
        )
    return text + "."


def circle_readout(card: dict[str, Any]) -> str:
    """What the circle shows, in words and seconds: its readout and its accessible label."""
    loss = _number(card.get("pit_loss_seconds"))
    parts = [] if _number(card.get("reference_lap_seconds")) else [circle_points(card)]
    if loss is None:
        parts.append("No rejoin point: the pit loss is missing.")
    else:
        parts.append(f"Rejoins {loss:.1f} s back, margin to {loss + MARGIN:.1f} s.")
    parts.append(_neighbour(card, "gap_behind", "behind", loss))
    parts.append(_neighbour(card, "gap_ahead", "ahead", loss))
    return " ".join(parts)


def _xy(degrees: float, radius: float) -> tuple[float, float]:
    theta = math.radians(degrees)
    return CENTRE[0] + radius * math.sin(theta), CENTRE[1] - radius * math.cos(theta)


def _car(degrees: float, label: str, filled: bool, inside: bool = False) -> str:
    """One car on the ring; neighbour labels sit outside, the card's car label inside."""
    x, y = _xy(degrees, RADIUS)
    lx, ly = _xy(degrees, RADIUS - 26 if inside else RADIUS + 26)
    side = math.sin(math.radians(degrees))
    anchor = "middle" if inside or degrees == 0 else "start" if side > 0 else "end"
    fill = "var(--bx-ink)" if filled else "var(--block-background-fill)"
    return (
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="8" fill="{fill}" class="car"/>'
        f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" '
        f'dominant-baseline="middle">{html.escape(label)}</text>'
    )


def _band(start: float, end: float, label_radius: float = RADIUS - 26) -> str:
    """The rejoin margin as an arc, drawn counter-clockwise from the rejoin point."""
    end = max(end, start - 359)
    (x1, y1), (x2, y2) = _xy(start, RADIUS), _xy(end, RADIUS)
    large = 1 if start - end > 180 else 0
    rx, ry = _xy(start, label_radius)
    return (
        f'<path d="M{x1:.1f},{y1:.1f} A{RADIUS},{RADIUS} 0 {large} 0 {x2:.1f},{y2:.1f}" class="band"/>'
        f'<rect x="{x1 - 6:.1f}" y="{y1 - 6:.1f}" width="12" height="12" class="rejoin" '
        f'transform="rotate(45 {x1:.1f} {y1:.1f})"/>'
        f'<text x="{rx:.1f}" y="{ry:.1f}" text-anchor="middle" dominant-baseline="middle">rejoin</text>'
    )


def circle_of_doom(card: dict[str, Any]) -> str:
    """One lap in time as SVG, with the car on top, its neighbours and the rejoin margin."""
    points, readout = circle_points(card), circle_readout(card)
    svg = ""
    if not isinstance(points, str):
        shapes = [
            f'<circle cx="{CENTRE[0]}" cy="{CENTRE[1]}" r="{RADIUS}" class="ring"/>'
        ]
        if points["rejoin"] is not None:
            shapes.append(_band(points["rejoin"], points["band_end"]))
        shapes.append(
            _car(0, f"car {card.get('driver_number', '?')}", True, inside=True)
        )
        if points["ahead"] is not None:
            shapes.append(_car(points["ahead"], "ahead", True))
        if (
            points["behind"] is not None
        ):  # hollow when the car behind is inside the margin
            shapes.append(
                _car(points["behind"], "behind", points["cleared"] is not False)
            )
        svg = _svg(f"0 0 {CIRCLE_WIDTH} {CIRCLE_HEIGHT}", readout, "".join(shapes))
    return f'<div class="chart">{svg}<p class="readout">{html.escape(readout)}</p><p class="note">{ASSUMPTION}</p></div>'


def _svg(box: str, label: str, shapes: str) -> str:
    label = html.escape(label)
    return f'<svg viewBox="{box}" role="img" aria-label="{label}"><title>{label}</title>{shapes}</svg>'


def tyre_readout(card: dict[str, Any]) -> str:
    """Where the tyre age sits against the compound's thresholds, in words."""
    zones = tyre_zones(card)
    if isinstance(zones, str):
        return zones
    young, old, age, _ = zones
    zone = (
        "too young"
        if age < young
        else "in the window"
        if age < old
        else "in the opportunity zone"
    )
    return f"{laps(age)} on {card['compound']}, {zone}. Window from {young} laps, opportunity from {old}."


def _zone(start: float, stop: float, name: str, label: str) -> str:
    width = stop - start
    shape = (
        f'<rect x="{start:.1f}" y="26" width="{width:.1f}" height="20" class="{name}"/>'
    )
    if width < len(label) * 7.5 + 8:  # too narrow: the readout names the zone
        return shape
    return (
        shape
        + f'<text x="{start + width / 2:.1f}" y="37" text-anchor="middle" dominant-baseline="middle" class="zone-label">{label}</text>'
    )


def tyre_window(card: dict[str, Any]) -> str:
    """The tyre age on a bar split by the compound's policy thresholds, with its readout."""
    zones, readout = tyre_zones(card), tyre_readout(card)
    if isinstance(zones, str):
        return f'<div class="chart"><p class="readout">{html.escape(readout)}</p></div>'
    young, old, age, end = zones
    scale = (TYRE_WIDTH - 20) / end

    def x(laps_: float) -> float:
        return 10 + laps_ * scale

    shapes = [
        _zone(x(0), x(young), "zone1", "too young"),
        _zone(x(young), x(old), "zone2", "window"),
        _zone(x(old), x(end), "zone3", "opportunity"),
        f'<rect x="{x(0):.1f}" y="26" width="{x(end) - x(0):.1f}" height="20" class="bar"/>',
    ]
    for tick in (0, young, old):
        shapes.append(
            f'<text x="{x(tick):.1f}" y="62" text-anchor="middle" class="tick">{tick}</text>'
        )
    anchor = "start" if x(age) < 40 else "end" if x(age) > TYRE_WIDTH - 40 else "middle"
    shapes.append(
        f'<line x1="{x(age):.1f}" y1="20" x2="{x(age):.1f}" y2="52" class="age"/>'
    )
    shapes.append(
        f'<text x="{x(age):.1f}" y="12" text-anchor="{anchor}" class="age-label">{laps(age)}</text>'
    )
    title = (
        f'<div class="chart-title">{html.escape(card["compound"])} tyre window</div>'
    )
    svg = _svg(f"0 0 {TYRE_WIDTH} 70", readout, "".join(shapes))
    caption = f"In the window, a stop needs the car ahead within {MARGIN:.1f} s."
    return f'<div class="chart">{title}{svg}<p class="readout">{html.escape(readout)}</p><p class="note">{caption}</p></div>'


def parse_answer(text: Any) -> tuple[str, str] | None:
    """(call, why) when the answer is strictly two contract lines, else None.

    The rules are those of boxbox.evaluation.parsing.parse_response, so the banner never
    contradicts the scores; tests/test_app.py checks that the two agree.
    """
    if not isinstance(text, str):
        return None
    lines = text.replace("\r\n", "\n").removesuffix("\n").split("\n")
    if len(lines) != 2 or not lines[1].startswith("WHY: "):
        return None
    call, why = lines[0].removeprefix("CALL: "), lines[1][len("WHY: ") :]
    clean = why == why.strip(" \t") and not any(
        c in why for c in "\r\v\f\x85\u2028\u2029"
    )
    known = lines[0].startswith("CALL: ") and call in CALLS
    return (call, why) if known and why and clean else None


STOPS = {
    "eos_token": "end of answer",
    "max_new_tokens": "token limit",
    "cooperative_max_time": "time limit",
    "model_stop": "model stop",
}


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" + ("" if count == 1 else "s")


def answer_details(
    answer: str | None, earlier: int, sent: int, trace: dict[str, Any] | None
) -> str:
    """One line on the last answer: strict format, generation and the history sent.

    `earlier` exchanges came before the question and `sent` of them reached the engine.
    The generation part needs the engine's trace, so the stub shows the rest only.
    """
    if answer is None:
        return ""
    parts = [
        "Strict CALL/WHY format: yes"
        if parse_answer(answer)
        else "Strict CALL/WHY format: no"
    ]
    if trace and "duration_seconds" in trace:
        limit = trace["generation_settings"]["explicit_overrides"]["max_new_tokens"]
        stop = STOPS.get(trace["stop_condition"], trace["stop_condition"])
        parts += [
            f"{trace['duration_seconds']:.1f} s",
            f"{trace['input_tokens']} input tokens",
            f"{trace['generated_tokens']} of {limit} new tokens",
            f"stop: {stop}",
        ]
        sent = trace["history"]["retained_turns"]
    if earlier == 0:
        parts.append("no earlier exchange")
    elif sent == earlier:
        parts.append(f"history sent: {_plural(earlier, 'earlier exchange')}")
    else:
        parts.append(f"history sent: {sent} of {_plural(earlier, 'earlier exchange')}")
    return f'<p class="note details mono">{html.escape(" · ".join(parts))}</p>'


CUT = (
    '<div class="cut">&#9888; The answer may be cut: generation reached its limit '
    "before the model ended it.</div>"
)


def banner(answer: str | None, cut: bool = False, sound: str | None = None) -> str:
    """The latest call in large text, or what stops it from being read.

    `cut` is the engine's `possibly_truncated`: the token or time limit ended the answer.
    With a `sound` key (the Card tab), a BOX call carries it in `data-box`, and the page
    plays the sound once for each new key (`replay.sound_head`).
    """
    tag = ' data-sound="card"' if sound is not None else ""
    if answer is None:
        return (
            f'<div class="banner idle"{tag}><div class="call">No call yet</div>'
            '<div class="why">Ask a question or pick one below.</div></div>'
        )
    warning = CUT if cut else ""
    parsed = parse_answer(answer)
    if parsed is None:
        return (
            f'<div class="banner bad"{tag}>Answer not in CALL/WHY format{warning}</div>'
        )
    call, why = parsed
    if call == "BOX" and sound:
        tag += f' data-box="{html.escape(sound)}"'
    return (
        f'<div class="banner"{tag} style="--call:{CALL_COLOURS[call]}">'
        f'<div class="call">{call}</div><div class="why">{html.escape(why)}</div>'
        f"{warning}</div>"
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
        f'<div class="policy"><b>Rule on this card:</b> '
        f'<span style="color:{CALL_COLOURS[call]}">{call}</span> {badge}'
        f"<div>{html.escape(why)}</div>"
        "<div class=note>An out-of-scope request should differ: the assistant answers NO CALL to it.</div></div>"
    )
