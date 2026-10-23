"""The replay tab: a race played back on the circle, with the policy 2.0 call.

The pit window follows the track status at the clock, and the call is policy 2.0 on
the 2.0 card. Around them: the flag, the weather and its archived forecast, the
driver's tyre, the pit lane and the running order, each read at the clock.
"""

from __future__ import annotations

import base64
import html
import math
import time
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import gradio as gr
import pandas as pd

from boxbox.data import (
    Timeline,
    cards_at,
    flags_at,
    frame,
    load_splits,
    load_timeline,
    pit_state,
    pit_window,
    standings,
    tyre_at,
    tyre_options,
)
from boxbox.data.cards_v2 import weather_at
from boxbox.data.openmeteo import forecast_at
from boxbox.data.replay import race_lap
from boxbox.data.splits import CLOSED_SPLITS, SPLITS_V2_FILE
from boxbox.rules import format_answer
from boxbox.rules.policy2 import TYRE_LOSS_LIMITS

from . import icons as I
from . import panels as P

TICK = 0.5  # seconds between timer ticks
SOUND = Path("boxbox.wav")  # played on each new 2.0 card whose policy 2.0 call is BOX
SPEEDS = ("x1", "x2", "x4")
HIDDEN = {"api_visibility": "private", "show_progress": "hidden"}
ZOOM = 2.2  # one turn covers twice the farthest reach, plus 10% room
METRICS = (  # icon, label, reading field, format, unit
    ("air", "Air", "air_temperature", ".0f", "°C"),
    ("track", "Track", "track_temperature", ".0f", "°C"),
    ("humidity", "Humidity", "humidity", ".0f", "%"),
    ("wind", "Wind", "wind_speed", ".1f", " m/s"),
)
SOFTEST = ("SOFT", "MEDIUM", "HARD")  # the softer, the faster on a new set
DEFAULT = ("2024-22", "63")  # Las Vegas 2024 on Russell: the tab opens on it
FLAG_WORDS = {
    "GREEN": "Green flag",
    "YELLOW": "Yellow flag",
    "DOUBLE YELLOW": "Double yellow",
    "RED": "Red flag",
    "SC": "Safety car",
    "VSC": "Virtual safety car",
    "CHEQUERED": "Chequered flag",
}
SKY_WORDS = {
    "sun": "Clear",
    "moon": "Clear night",
    "partly": "Partly cloudy",
    "cloud": "Cloudy",
    "fog": "Fog",
    "drizzle": "Drizzle",
    "rain": "Rain",
    "storm": "Storm",
    "unknown": "Sky unknown",
}
STATE_CLASSES = {
    "BOX": "box",
    "STAY OUT": "stay",
    "NO CALL": "nocall",
    "IN PIT": "pit",
    "OUT LAP": "pit out",
    "RETIRED": "idle",
    "NO CARD": "idle",
}
ATTRIBUTION = (
    '<a href="https://open-meteo.com/" target="_blank" rel="noopener">'
    "Weather data by Open-Meteo.com</a>"
)


def race_choices() -> list[tuple[str, str]]:
    """(label, race id) of every race whose split is open, in race order."""
    document = load_splits(SPLITS_V2_FILE)
    closed = {r for name in CLOSED_SPLITS for r in document["splits"].get(name, [])}
    races = [r for r in document["races"].values() if r["race_id"] not in closed]
    return [(f"{r['season']} {r['event']}", r["race_id"]) for r in races]


@lru_cache(maxsize=4)
def timeline(race_id: str) -> Timeline:
    return load_timeline(load_splits(SPLITS_V2_FILE)["races"][race_id])


def clock(state: dict[str, Any], now: float) -> float:
    """Race seconds at wall time `now`, from the last anchor: skipped ticks lose nothing."""
    if state["wall"] is None:
        return state["t"]
    elapsed = (now - state["wall"]) * int(state["speed"][1:])
    return min(state["t"] + elapsed, state["end"])


def clock_text(line: Timeline, lap: int, t: float) -> str:
    local = line.start + pd.Timedelta(seconds=t) + line.utc_offset
    # a lap-1 red flag dates the start from the restart, so the clock can be negative
    elapsed = ("-" if t < 0 else "") + str(timedelta(seconds=int(abs(t))))
    return (
        f'<div class="clock"><div class="lap">Lap <b>{lap}</b> / {line.total_laps}</div>'
        f'<div class="mono">{elapsed} elapsed</div>'
        f'<div class="mono">{local:%H:%M:%S} local</div>'
        f'<div class="mono">{_utc(line.utc_offset)}</div></div>'
    )


def _utc(offset: pd.Timedelta) -> str:
    """The track's offset from UTC, as UTC+3, UTC-8 or UTC+5:30."""
    minutes = int(offset.total_seconds() // 60)
    hours, rest = divmod(abs(minutes), 60)
    return f"UTC{'+' if minutes >= 0 else '-'}{hours}" + (
        f":{rest:02d}" if rest else ""
    )


def _flag_tile(line: Timeline, driver: str, t: float) -> str:
    """The flag at the clock, large, with the yellow sectors and a blue flag under it;
    the edge takes the flag's colour beside its word."""
    kind, sectors, blue = flags_at(line, driver, t)
    yellow = sorted(s for s in sectors if s is not None)
    where = ""
    if yellow:
        plural = "s" if len(yellow) > 1 else ""
        where = f"Yellow in sector{plural} {', '.join(map(str, yellow))}"
    if blue:
        where += f"{'. ' if where else ''}Blue flag for {_name(line, driver)}"
    colour = I.FLAG_COLOURS.get(kind.removeprefix("DOUBLE "), "var(--bx-ink)")
    return (
        f'<div class="tile track" style="--flag:{colour}"><div class="head">Track</div>'
        f'<div class="flagged">{I.flag(kind)}<div class="word">{FLAG_WORDS[kind]}</div>'
        f'<div class="sub">{where}</div></div></div>'
    )


def _weather_tile(line: Timeline, t: float) -> str:
    """The sky now, large, beside air and track temperature, humidity and wind, each
    with its icon and its word."""
    at = line.start + pd.Timedelta(seconds=t)
    weather = getattr(line.context, "weather", None)
    reading = (weather_at(weather, at) if weather is not None else None) or {}
    now, _ = forecast_at(line.forecast, at)
    if reading.get("rainfall"):
        kind = "rain"
    else:
        kind = I.sky(now["weather_code"], now["is_day"]) if now else "unknown"
    cells = "".join(
        f'<div class="metric">{I.metric(icon)}<span class="label">{label}</span>'
        f'<span class="value mono">{_value(reading, field, spec, unit)}</span></div>'
        for icon, label, field, spec, unit in METRICS
    )
    return (
        '<div class="tile weather"><div class="head">Weather now</div>'
        f'<div class="body"><div class="sky">{I.weather(kind)}'
        f'<span>{SKY_WORDS[kind]}</span></div><div class="metrics">{cells}</div>'
        "</div></div>"
    )


def _value(values: dict[str, Any], field: str, spec: str, unit: str) -> str:
    value = values.get(field)
    return "?" if value is None or pd.isna(value) else f"{value:{spec}}{unit}"


def _forecast_tile(line: Timeline, t: float) -> str:
    """The archived forecast steps after the clock as a table, one row per step."""
    at = line.start + pd.Timedelta(seconds=t)
    _, ahead = forecast_at(line.forecast, at)
    rows = []
    for step in ahead:
        kind = I.sky(step["weather_code"], step["is_day"])
        minutes = round((step["at"] - at).total_seconds() / 60)
        local = step["at"] + line.utc_offset
        rows.append(
            f'<tr><td class="mono">{local:%H:%M}</td><td class="mono">{minutes} min</td>'
            f'<td>{I.weather(kind)}<span class="sr-only">{SKY_WORDS[kind]}</span></td>'
            f'<td class="mono">{_value(step, "temperature_2m", ".0f", "°C")}</td>'
            f'<td class="mono">{_value(step, "precipitation", ".1f", " mm")}</td>'
            f'<td class="mono">{_value(step, "wind_speed_10m", ".1f", " m/s")}</td></tr>'
        )
    if line.forecast is None:
        body = '<div class="sub">Forecast unavailable</div>'
    elif not rows:
        body = '<div class="sub">No forecast past the race</div>'
    else:
        head = "".join(
            f'<th scope="col">{h}</th>'
            for h in ("Time", "In", "Sky", "Temp", "Rain", "Wind")
        )
        body = (
            '<div class="scroll"><table class="steps"><caption class="sr-only">'
            "Archived forecast steps after the clock, in local time</caption>"
            f"<thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
        )
    return (
        f'<div class="tile forecast"><div class="head">Archived forecast</div>{body}'
        f'<div class="sub">{ATTRIBUTION}</div></div>'
    )


def tyre_life(compound: str, slope: float | None) -> int | None:
    """Laps a new set lasts before its loss reaches policy 2.0's upper wear limit."""
    if not slope or slope <= 0:
        return None
    return int(float(TYRE_LOSS_LIMITS[compound][1]) / slope)


def best_compound(options: dict[str, Any]) -> str | None:
    """The softest dry compound whose life covers the laps left, else the one that
    lasts longest. A dry race needs two dry compounds, so with one used so far only
    the other two count. No choice on a wet track or without any degradation."""
    if options["wet"]:
        return None
    lives = {c: tyre_life(c, options["slopes"].get(c, (None,))[0]) for c in SOFTEST}
    candidates = [c for c in SOFTEST if lives[c] is not None]
    if len(options["used"]) == 1:
        candidates = [c for c in candidates if c not in options["used"]]
    lasting = [c for c in candidates if lives[c] >= options["laps_left"]]
    if lasting:
        return lasting[0]
    return max(candidates, key=lambda c: lives[c]) if candidates else None


def tyre_tile(line: Timeline, driver: str, t: float) -> str:
    """The three dry compounds for the chosen car: degradation per lap of tyre age,
    life to the wear limit and where the value comes from, the set on the car
    highlighted and the best choice marked."""
    options = tyre_options(line, driver, t)
    current, _ = tyre_at(line, driver, t)
    best = best_compound(options)
    rows = []
    for c in SOFTEST:
        slope, source = options["slopes"].get(c, (None, None))
        life = tyre_life(c, slope)
        on = ' class="on" aria-current="true"' if c == current else ""
        badge = ' <span class="best">Best</span>' if c == best else ""
        rows.append(
            f"<tr{on}><td>{I.tyre(c)}{c.title()}{badge}</td>"
            f'<td class="mono">{f"+{slope:.3f} s" if slope else "?"}</td>'
            f'<td class="mono">{f"~{life} laps" if life is not None else "?"}</td>'
            f'<td class="src">{source or ""}</td></tr>'
        )
    notes = [f"{options['laps_left']} laps left"]
    if options["wet"]:
        notes.append("wet track: slicks not compared")
    elif len(options["used"]) == 1:
        notes.append("needs a second compound")
    life = tyre_life(best, options["slopes"][best][0]) if best else None
    if life is not None and life < options["laps_left"]:
        notes.append("none lasts to the flag")
    head = "".join(
        f'<th scope="col">{h}</th>'
        for h in ("Compound", "Per Lap of Age", "Life", "Source")
    )
    return (
        f'<div class="tile tyres"><div class="head">Tyres for '
        f'{html.escape(_name(line, driver))}</div><div class="scroll">'
        '<table class="compounds">'
        '<caption class="sr-only">Time lost per lap of tyre age and laps to the wear '
        f"limit, per dry compound</caption><thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
        f'<div class="sub">{", ".join(notes)}</div></div>'
    )


def status_strip(line: Timeline, driver: str, t: float) -> str:
    """The flag, the weather now, the archived forecast and the three dry compounds
    at clock t."""
    return (
        f'<div class="strip">{_flag_tile(line, driver, t)}{_weather_tile(line, t)}'
        f"{_forecast_tile(line, t)}{tyre_tile(line, driver, t)}</div>"
    )


def _name(line: Timeline, driver: str) -> str:
    return line.drivers.get(driver, {}).get("acronym") or f"car {driver}"


def _ink(colour: str) -> str:
    """Black or white, whichever reads better on a #rrggbb colour."""
    try:
        channels = [int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    except ValueError:  # the ink fallback for a car without a team colour
        return "var(--block-background-fill)"
    linear = [
        c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels
    ]
    luminance = 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    return "#000" if luminance > 0.179 else "#fff"  # equal contrast at 0.179


def _team_car(
    line: Timeline,
    driver: str,
    degrees: float,
    inside: bool = False,
    named: bool = True,
    in_pit: bool = False,
) -> str:
    """One car on the ring in its team colour with its number, labelled with its
    acronym; a car in the pit lane has a dashed outline and says PIT."""
    x, y = P._xy(degrees, P.RADIUS)
    # the chosen car's label sits inside, clear of the inner rejoin arc
    lx, ly = P._xy(degrees, P.RADIUS - 34 if inside else P.RADIUS + 28)
    side = math.sin(math.radians(degrees))
    anchor = "middle" if inside or degrees == 0 else "start" if side > 0 else "end"
    colour = line.drivers.get(driver, {}).get("colour") or "var(--bx-ink)"
    pit = " pit" if in_pit else ""
    # the number's colour is a style: .chart text sets fill over an attribute
    dot = (
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="11" fill="{html.escape(colour)}" '
        f'class="car{pit}"/><text x="{x:.1f}" y="{y:.1f}" class="num" '
        f'text-anchor="middle" dominant-baseline="central" '
        f'style="fill:{_ink(colour)}">{html.escape(driver)}</text>'
    )
    if not named:
        return dot
    label = _name(line, driver) + (" PIT" if in_pit else "")
    return (
        f'{dot}<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" '
        f'dominant-baseline="middle">{html.escape(label)}</text>'
    )


def _named(angles: dict[str, float], spacing: float = 9.0) -> set[str]:
    """Cars whose label fits: each `spacing` degrees from the last one named and from
    the car on top, more near the top and bottom, where labels sit side by side."""
    named, last = set(), 0.0
    for driver, angle in sorted(angles.items(), key=lambda item: item[1] % 360):
        room = spacing / max(abs(math.sin(math.radians(angle))), 0.6)
        if abs(angle) >= room and (angle % 360) - (last % 360) >= room:
            named.add(driver)
            last = angle
    return named


def _neighbours(line: Timeline, angles: dict[str, float], scale: float | None) -> str:
    """The nearest car ahead and behind in seconds, for the readout and screen readers."""
    if not angles or not scale:
        return ""
    ahead = [(a, d) for d, a in angles.items() if a > 0]
    behind = [(a, d) for d, a in angles.items() if a < 0]
    parts = []
    if ahead:
        angle, other = min(ahead)
        parts.append(f"{_name(line, other)} {angle / 360 * scale:.1f} s ahead")
    if behind:
        angle, other = max(behind)
        parts.append(f"{_name(line, other)} {-angle / 360 * scale:.1f} s behind")
    return ", ".join(parts) + ". " if parts else ""


def turn(scale: float | None, seconds: list[float], loss: float | None) -> float | None:
    """Seconds one turn of the ring stands for: the real lap, zoomed in while the field
    is close, so the farthest car and the rejoin point still fit; rounded up to 5 s so
    the caption does not flicker."""
    if not scale or not seconds:
        return scale
    reach = max(max(abs(s) for s in seconds), (loss or 0.0) + P.MARGIN)
    return min(scale, math.ceil(ZOOM * reach / 5) * 5)


def _arc(start: float, end: float, radius: float, cls: str) -> str:
    """An arc counter-clockwise from `start` to `end` degrees at `radius`."""
    end = max(end, start - 359)
    (x1, y1), (x2, y2) = P._xy(start, radius), P._xy(end, radius)
    large = 1 if start - end > 180 else 0
    return (
        f'<path d="M{x1:.1f},{y1:.1f} A{radius},{radius} 0 {large} 0 '
        f'{x2:.1f},{y2:.1f}" class="{cls}"/>'
    )


def _ticks(one: float) -> tuple[str, int]:
    """A tick every 5 s (10 s past a 60 s turn) each side of the car on top."""
    step = 5 if one <= 60 else 10
    marks = []
    for k in range(1, int(one / 2 // step) + 1):
        for degrees in (k * step / one * 360, -k * step / one * 360):
            (x1, y1), (x2, y2) = (
                P._xy(degrees, P.RADIUS - 6),
                P._xy(degrees, P.RADIUS + 6),
            )
            marks.append(
                f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                'class="tick-mark"/>'
            )
    return "".join(marks), step


def circle(
    line: Timeline,
    driver: str,
    now: dict[str, Any],
    window: tuple,
    in_pit: frozenset[str] = frozenset(),
) -> str:
    """Every car by time gap from `driver`, on top, and the pit window in yellow for
    the track status at the clock, on a ring that zooms in when the field is close."""
    scale, loss, condition = now["scale"], *window
    seconds = {d: a / 360 * scale for d, a in now["angles"].items()} if scale else {}
    one = turn(scale, list(seconds.values()), loss)
    angles = {d: s / one * 360 for d, s in seconds.items()}
    shapes = [
        f'<circle cx="{P.CENTRE[0]}" cy="{P.CENTRE[1]}" r="{P.RADIUS}" class="ring"/>'
    ]
    ticks, step = _ticks(one) if one else ("", 0)
    shapes.append(ticks)
    if loss is not None and one:
        # inside the ring, where no dot hides it: the way back to the rejoin point in
        # the pit colour, then the rejoin window in yellow
        rejoin, end = -loss / one * 360, -(loss + P.MARGIN) / one * 360
        inner = P.RADIUS - 18
        rx, ry = P._xy(rejoin, P.RADIUS - 40)
        shapes += [
            _arc(0.0, rejoin, inner, "loss"),
            _arc(rejoin, end, inner, "window"),
            (
                f'<text x="{rx:.1f}" y="{ry:.1f}" text-anchor="middle" '
                'dominant-baseline="middle">rejoin</text>'
            ),
        ]
    named = _named(angles)
    shapes += [
        _team_car(line, other, angle, named=other in named, in_pit=other in in_pit)
        for other, angle in angles.items()
    ]
    shapes.append(_team_car(line, driver, 0, inside=True, in_pit=driver in in_pit))
    text = (
        f"{condition} pit window {loss:.1f} to {loss + P.MARGIN:.1f} s back"
        if loss is not None
        else "no pit window"
    )
    scale_text = f"1 turn = {one:.0f} s, ticks every {step} s" if one else ""
    pits = ", ".join(_name(line, d) for d in sorted(in_pit))
    # the neighbours show on the ring and in the table; screen readers still hear them
    label = (
        f"{_name(line, driver)} on top, {len(angles)} other cars by time gap, "
        f"{scale_text}. {_neighbours(line, angles, one)}{text}."
        + (f" In the pit lane: {pits}." if pits else "")
    )
    box = f"0 0 {P.CIRCLE_WIDTH} {P.CIRCLE_HEIGHT}"
    svg = P._svg(box, label, "".join(shapes))
    return (
        f'<div class="chart replay">{svg}<div class="readout">{text}<br>'
        f"{scale_text}</div></div>"
    )


def call_state(card_v2: dict | None, lap: int | None, pit: str | None) -> str:
    """What the call panel shows: the pit lane and out-lap first, then a stopped car or
    a lap with no 2.0 card, else policy 2.0's call."""
    if pit:
        return pit
    if lap is None:
        return "RETIRED"
    parsed = P.parse_answer(format_answer(card_v2)) if card_v2 is not None else None
    return parsed[0] if parsed else "NO CARD"


def _why(state: str, card_v2: dict | None, lap: int | None, name: str) -> str:
    if state in P.CALLS:
        return P.parse_answer(format_answer(card_v2))[1]
    return {
        "IN PIT": f"{name} is in the pit lane.",
        "OUT LAP": f"{name} is on the out-lap; the next card comes at the line.",
        "RETIRED": f"{name} is no longer running.",
    }.get(state, f"No 2.0 card for {name} at lap {lap}: final lap or no timing.")


def calls(
    card_v2: dict | None,
    lap: int | None,
    driver: str,
    key: str = "",
    pit: str | None = None,
    name: str = "",
) -> str:
    """Policy 2.0 on the 2.0 card, read when the car started its lap: a safety car out
    since then reaches it at the line. In the pit lane and on the out-lap the panel
    says so instead of a call.

    When policy 2.0 says BOX, `data-box` carries the card's `key`, and the page plays
    the sound once for each new key (`sound_head`); the banner blinks three times, and
    a new BOX card restarts it (the odd and even laps swap the animation).
    """
    state = call_state(card_v2, lap, pit)
    box = state == "BOX"
    marker = f' data-box="{html.escape(key)}"' if box and key else ""
    when = f", lap {lap} card, as of lap {lap - 1}" if state in P.CALLS else ""
    cls = STATE_CLASSES[state] + (
        f" {'odd' if (lap or 0) % 2 else 'even'}" if box else ""
    )
    why = html.escape(_why(state, card_v2, lap, name or f"Car {driver}"))
    return (
        f'<div class="calls" data-sound="replay"{marker}>'
        f'<div class="label">Policy 2.0, card 2.0{when}</div>'
        f'<div class="banner {cls}" role="status" aria-live="polite">'
        f'<div class="call">{state}</div><div class="why">{why}</div></div></div>'
    )


def driver_tile(line: Timeline, driver: str) -> str:
    """The chosen car: number in its team colour, acronym and team."""
    info = line.drivers.get(driver, {})
    colour = info.get("colour") or "var(--bx-ink)"
    return (
        f'<div class="driver"><span class="num mono" style="background:'
        f'{html.escape(colour)};color:{_ink(colour)}">{html.escape(driver)}</span>'
        f"<span><b>{html.escape(_name(line, driver))}</b> "
        f'<span class="team">{html.escape(info.get("team", ""))}</span></span></div>'
    )


def _gap(gap: tuple[float | None, int] | None) -> str:
    if gap is None:
        return "?"
    seconds, down = gap
    if seconds is None:
        return f"+{down} LAP{'S' if down > 1 else ''}"
    return f"+{seconds:.1f}"


def standings_table(
    line: Timeline, driver: str, t: float, in_pit: frozenset[str]
) -> str:
    """The running order at the clock, gaps taken at the line, the chosen car marked."""
    rows = []
    for pos, row in enumerate(standings(line, t), start=1):
        d = row["driver"]
        info = line.drivers.get(d, {})
        gap = "Leader" if pos == 1 else _gap(row["gap"])
        interval = "" if pos == 1 else _gap(row["interval"])
        if row["out"]:
            gap, interval = "OUT", ""
        compound, age = tyre_at(line, d, t)
        tyre = (
            f'{I.tyre(compound)}<span class="mono">{age}</span>'
            f'<span class="sr-only"> {compound.lower()}</span>'
            if compound and age is not None
            else "?"
        )
        badge = ' <span class="pit">PIT</span>' if d in in_pit else ""
        classes = " ".join(
            c for c in ("me" if d == driver else "", "out" if row["out"] else "") if c
        )
        attrs = f' class="{classes}"' if classes else ""
        attrs += ' aria-current="true"' if d == driver else ""
        rows.append(
            f'<tr{attrs}><td class="mono">{pos}</td>'
            f'<td class="car" style="--team:{html.escape(info.get("colour") or "var(--bx-ring)")}">'
            f'<span class="mono">{html.escape(d)}</span> {html.escape(_name(line, d))}{badge}</td>'
            f'<td class="mono">{gap}</td><td class="mono">{interval}</td><td>{tyre}</td></tr>'
        )
    return (
        '<table class="standings"><caption class="sr-only">Running order at the clock, '
        "gaps taken at the line</caption><thead><tr>"
        + "".join(
            f'<th scope="col">{h}</th>' for h in ("Pos", "Car", "Gap", "Int", "Tyre")
        )
        + f"</tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )


def view(state: dict[str, Any], t: float) -> tuple[str, str, str, str, str]:
    """The clock, the status strip, the driver and call, the circle and the running
    order at race time t."""
    line, driver = timeline(state["race"]), state["driver"]
    now = frame(line, driver, t)
    card_v2, lap = cards_at(line, driver, t)
    in_pit = frozenset(d for d in line.cars if pit_state(line, d, t) == "IN PIT")
    key = f"{state['race']}|{driver}|{lap}"
    pit = pit_state(line, driver, t, lap)
    return (
        clock_text(line, now["lap"], t),
        status_strip(line, driver, t),
        driver_tile(line, driver)
        + calls(card_v2, lap, driver, key, pit, _name(line, driver)),
        circle(line, driver, now, pit_window(line, driver, t), in_pit),
        standings_table(line, driver, t, in_pit),
    )


def sound_head(sound: Path = SOUND) -> str:
    """A page script that plays `sound` once for each new BOX key of a `data-sound` panel.

    The panels are the replay call (one key per 2.0 card) and the Card tab's banner (one
    key per answer). The sound is inlined, so no file route is needed; without the file,
    nothing plays. Browsers allow the sound after the first click on the page.
    """
    if not sound.is_file():
        return ""
    data = base64.b64encode(sound.read_bytes()).decode("ascii")
    return f"""<script>
(() => {{
  const sound = new Audio("data:audio/wav;base64,{data}");
  const last = {{}};  // per panel; a panel out of the page keeps its last key. Gradio edits the page in
  // place, so a new BOX may only change the data-box attribute
  new MutationObserver(() => {{
    for (const panel of document.querySelectorAll("[data-sound]")) {{
      const key = panel.dataset.box || null;
      if (key && key !== last[panel.dataset.sound]) {{
        sound.currentTime = 0;
        sound.play().catch(() => {{}});
      }}
      last[panel.dataset.sound] = key;
    }}
  }}).observe(document.documentElement, {{
    childList: true, subtree: true, attributes: true, attributeFilter: ["data-box"]
  }});
}})();
</script>"""


def pick_race(race_id: str, driver: str | None = None) -> tuple:
    """A new race, paused at the end of lap 1 on `driver` if it raced, else on its
    leader, and the controls on."""
    if not race_id:  # the dropdown was cleared
        return (gr.skip(),) * 11
    line = timeline(race_id)
    order = running_order(line)
    first = driver if driver in order else order[0]
    lap = race_lap(line, line.first)
    state = {
        "race": race_id,
        "driver": first,
        "t": line.first,
        "end": line.end,
        "wall": None,
        "speed": "x1",
        "lap": lap,
    }
    names = [(f"{_name(line, d)} ({d})", d) for d in order]
    drivers = gr.update(choices=names, value=first, interactive=True)
    button = gr.update(interactive=True, value="Play")
    laps = gr.update(maximum=line.total_laps, value=lap, interactive=True)
    controls = (button, gr.update(interactive=True, value="x1"), laps)
    return state, drivers, gr.update(active=False), *controls, *view(state, line.first)


def open_default() -> tuple:
    """The tab opens on the default race and driver, when that race is open."""
    race_id, driver = DEFAULT
    opened = any(race_id == r for _, r in race_choices())
    return pick_race(race_id if opened else "", driver)


def running_order(line: Timeline) -> list[str]:
    """Cars by their crossing at the lowest lap they all reached, the others last."""
    shared = max(int(car.lap[0]) for car in line.cars.values())

    def crossing(driver: str) -> float:
        car = line.cars[driver]
        at = car.end[car.lap == shared]
        return float(at[0]) if len(at) else math.inf

    return sorted(line.cars, key=crossing)


def lap_start(line: Timeline, lap: int) -> float:
    """Clock time at which the leader starts `lap`, never before the replay start:
    a car shows only once it has crossed the line, so lap 2 starts with the field."""
    ends = [
        float(e[0])
        for car in line.cars.values()
        if len(e := car.end[car.lap == lap - 1])
    ]
    # 2025-06 has no timing before lap 25: an earlier lap starts the replay
    return max(min(ends, default=line.first), line.first)


def _follow(state: dict[str, Any], lap: int) -> tuple[dict[str, Any], Any]:
    """The lap slider follows the race lap; an unchanged lap sends nothing, so a drag
    under way is not pulled back on every tick."""
    if lap == state.get("lap"):
        return state, gr.skip()
    return {**state, "lap": lap}, gr.update(value=lap)


def jump(state: dict[str, Any], lap: int) -> tuple:
    """Move the clock to the start of a lap; a running replay keeps running from it.
    The slider keeps what was typed, so typing 12 does not stop at 2."""
    line = timeline(state["race"])
    # a lap typed digit by digit passes through 1, below the slider's real range
    lap = min(max(int(lap or 2), 2), line.total_laps)
    t = min(lap_start(line, lap), state["end"])
    wall = None if state["wall"] is None else time.monotonic()
    state = {**state, "t": t, "wall": wall, "lap": race_lap(line, t)}
    return state, *view(state, t)


def pick_driver(state: dict[str, Any], driver: str) -> tuple:
    state = {**state, "driver": driver}
    return state, *view(state, clock(state, time.monotonic()))


def pause(state: dict[str, Any]) -> tuple:
    t = clock(state, time.monotonic())
    state, bar = _follow(
        {**state, "t": t, "wall": None}, race_lap(timeline(state["race"]), t)
    )
    return state, gr.update(active=False), gr.update(value="Play"), bar, *view(state, t)


def toggle(state: dict[str, Any]) -> tuple:
    """One button: Play from the clock, or Pause; its label says what a click does."""
    if state.get("wall") is not None:
        return pause(state)
    now = time.monotonic()  # re-anchored, so the clock does not jump
    state = {**state, "t": clock(state, now), "wall": now}
    return state, gr.update(active=True), gr.update(value="Pause"), *(gr.skip(),) * 6


def set_speed(state: dict[str, Any], speed: str) -> dict[str, Any]:
    """A new anchor, so the speed change does not move the clock."""
    now = time.monotonic()
    wall = None if state["wall"] is None else now
    return {**state, "t": clock(state, now), "wall": wall, "speed": speed}


def tick(state: dict[str, Any]) -> tuple:
    """One timer tick: the clock from wall time and the slider on the race lap; at the
    flag the replay pauses."""
    t = clock(state, time.monotonic())
    if t >= state["end"]:
        return pause(state)
    state, bar = _follow(state, race_lap(timeline(state["race"]), t))
    return state, gr.skip(), gr.skip(), bar, *view(state, t)


def replay_tab() -> tuple:
    """The replay controls in one block, then the status strip, then the driver, call
    and circle beside the running order, wired inside the current Blocks.

    Returns the opening load, (function, outputs), for the Blocks to run on page load.
    """
    state = gr.State({})
    timer = gr.Timer(TICK, active=False)
    choices = race_choices()
    default = DEFAULT[0] if any(DEFAULT[0] == r for _, r in choices) else None
    with gr.Group(elem_classes="bx-bar"), gr.Row(equal_height=True):
        race = gr.Dropdown(choices, value=default, label="Race", scale=3, min_width=200)
        driver = gr.Dropdown(
            [], label="Driver", interactive=False, scale=2, min_width=140
        )
        with gr.Column(scale=3, min_width=280):
            with gr.Row(equal_height=True):
                play_button = gr.Button(
                    "Play",
                    variant="primary",
                    interactive=False,
                    scale=0,
                    min_width=96,
                )
                speed = gr.Radio(
                    list(SPEEDS),
                    value="x1",
                    label="Speed",
                    show_label=False,
                    interactive=False,
                    scale=1,
                    min_width=150,
                    elem_classes="bx-speed",
                )
            lap = gr.Slider(
                2, 3, value=2, step=1, label="Jump to lap", interactive=False
            )
        clock_html = gr.HTML(scale=1, min_width=150, elem_classes="bx-clock")
    status_html = gr.HTML()
    with gr.Row():
        with gr.Column(scale=5, min_width=360):
            call_html = gr.HTML()
            circle_html = gr.HTML()
        with gr.Column(scale=4, min_width=320):
            standings_html = gr.HTML()
    # one output per panel: Gradio edits each in place, and an unchanged one costs nothing
    panels = [clock_html, status_html, call_html, circle_html, standings_html]
    picked = [state, driver, timer, play_button, speed, lap, *panels]
    # .change: .select misses a choice made with the keyboard, and nothing else writes
    # the race, so .change fires only on a real new choice
    race.change(pick_race, race, picked, **HIDDEN)
    driver.input(pick_driver, [state, driver], [state, *panels], **HIDDEN)
    running = [state, timer, play_button, lap, *panels]
    play_button.click(toggle, state, running, **HIDDEN)
    speed.input(set_speed, [state, speed], state, **HIDDEN)
    # .input: the slider following the race lap must not jump; .release replays a lap.
    # preprocess=False: a lap typed digit by digit passes through 1, below the slider's
    # minimum, which Gradio would refuse; jump keeps the lap in range itself
    raw = {**HIDDEN, "preprocess": False}
    lap.input(jump, [state, lap], [state, *panels], **raw)
    lap.release(jump, [state, lap], [state, *panels], **raw)
    timer.tick(tick, state, running, **HIDDEN)
    return open_default, picked
