"""The replay tab: a race played back on the circle, with the call of the car's card."""

from __future__ import annotations

import html
import time
from datetime import timedelta
from functools import lru_cache
from typing import Any

import gradio as gr
import pandas as pd

from boxbox.data import Timeline, card_at, frame, load_splits, load_timeline
from boxbox.data.splits import CLOSED_SPLITS
from boxbox.rules import format_answer

from . import panels as P

TICK = 0.5  # seconds between timer ticks
SPEEDS = ("x1", "x2", "x4")
HIDDEN = {"api_visibility": "private", "show_progress": "hidden"}


def race_choices() -> list[tuple[str, str]]:
    """(label, race id) of every race whose split is open, in race order."""
    document = load_splits()
    closed = {r for name in CLOSED_SPLITS for r in document["splits"][name]}
    races = [r for r in document["races"].values() if r["race_id"] not in closed]
    return [(f"{r['season']} {r['event']}", r["race_id"]) for r in races]


@lru_cache(maxsize=4)
def timeline(race_id: str) -> Timeline:
    return load_timeline(load_splits()["races"][race_id])


def clock(state: dict[str, Any], now: float) -> float:
    """Race seconds at wall time `now`, from the last anchor: skipped ticks lose nothing."""
    if state["wall"] is None:
        return state["t"]
    elapsed = (now - state["wall"]) * int(state["speed"][1:])
    return min(state["t"] + elapsed, state["end"])


def clock_text(line: Timeline, lap: int, t: float) -> str:
    local = line.start + pd.Timedelta(seconds=t) + line.utc_offset
    elapsed = timedelta(seconds=int(t))
    return (
        f'<div class="situation"><div class="race">{html.escape(line.event)}</div>'
        f'<div class="mono">{local:%H:%M:%S} local &nbsp; {elapsed} elapsed &nbsp; '
        f"Lap {lap}/{line.total_laps}</div></div>"
    )


def circle(line: Timeline, driver: str, now: dict[str, Any], card: dict | None) -> str:
    """Every car by time gap from `driver`, on top, and the card's pit window in yellow."""
    scale, angles = now["scale"], now["angles"]
    shapes = [
        f'<circle cx="{P.CENTRE[0]}" cy="{P.CENTRE[1]}" r="{P.RADIUS}" class="ring"/>'
    ]
    loss = P._number(card.get("pit_loss_seconds")) if card else None
    if loss is not None and scale:
        shapes.append(P._band(-loss / scale * 360, -(loss + P.MARGIN) / scale * 360))
    shapes += [P._car(angle, other, True) for other, angle in angles.items()]
    shapes.append(P._car(0, f"car {driver}", True, inside=True))
    window = (
        f"pit window {loss:.1f} to {loss + P.MARGIN:.1f} s back"
        if loss is not None
        else "no pit window"
    )
    label = f"Car {driver} on top, {len(angles)} other cars by time gap, {window}."
    box = f"0 0 {P.CIRCLE_WIDTH} {P.CIRCLE_HEIGHT}"
    return f'<div class="chart replay">{P._svg(box, label, "".join(shapes))}</div>'


def call(card: dict | None, lap: int | None, driver: str) -> str:
    if card is not None:
        return P.banner(format_answer(card))
    why = f"No card for car {driver} at lap {lap}: pit lane, final lap or no timing."
    return f'<div class="banner idle"><div class="call">No card</div><div class="why">{why}</div></div>'


def view(state: dict[str, Any], t: float) -> tuple[str, str, str]:
    """The clock, the circle and the call at race time t."""
    line, driver = timeline(state["race"]), state["driver"]
    now = frame(line, driver, t)
    card, lap = card_at(line, driver, t)
    return (
        clock_text(line, now["lap"], t),
        circle(line, driver, now, card),
        call(card, lap, driver),
    )


def pick_race(race_id: str) -> tuple:
    """A new race, paused at the end of lap 1 on its leader, and the controls on."""
    line = timeline(race_id)
    order = sorted(line.cars, key=lambda d: line.cars[d].end[0])
    state = {
        "race": race_id,
        "driver": order[0],
        "t": line.first,
        "end": line.end,
        "wall": None,
        "speed": "x1",
    }
    drivers = gr.update(choices=order, value=order[0], interactive=True)
    on = gr.update(interactive=True)
    controls = (on, on, gr.update(interactive=True, value="x1"))
    return state, drivers, gr.update(active=False), *controls, *view(state, line.first)


def pick_driver(state: dict[str, Any], driver: str) -> tuple:
    state = {**state, "driver": driver}
    return state, *view(state, clock(state, time.monotonic()))


def play(state: dict[str, Any]) -> tuple:
    now = time.monotonic()  # re-anchored, so a second Play does not rewind
    return {**state, "t": clock(state, now), "wall": now}, gr.update(active=True)


def pause(state: dict[str, Any]) -> tuple:
    state = {**state, "t": clock(state, time.monotonic()), "wall": None}
    return state, gr.update(active=False), *view(state, state["t"])


def set_speed(state: dict[str, Any], speed: str) -> dict[str, Any]:
    """A new anchor, so the speed change does not move the clock."""
    now = time.monotonic()
    wall = None if state["wall"] is None else now
    return {**state, "t": clock(state, now), "wall": wall, "speed": speed}


def tick(state: dict[str, Any]) -> tuple:
    """One timer tick: the clock from wall time; at the flag the replay pauses."""
    t = clock(state, time.monotonic())
    if t < state["end"]:
        return gr.skip(), gr.skip(), *view(state, t)
    return pause(state)


def replay_tab() -> None:
    """The replay controls and panels, wired inside the current Blocks."""
    state = gr.State({})
    timer = gr.Timer(TICK, active=False)
    with gr.Row():
        race = gr.Dropdown(race_choices(), value=None, label="Race", scale=2)
        driver = gr.Dropdown([], label="Driver", interactive=False, scale=1)
        off = {"interactive": False, "scale": 0, "min_width": 90}
        play_button = gr.Button("Play", variant="primary", **off)
        pause_button = gr.Button("Pause", **off)
        speed = gr.Radio(list(SPEEDS), value="x1", label="Speed", interactive=False)
    clock_html, circle_html, call_html = gr.HTML(), gr.HTML(), gr.HTML()
    panels = [clock_html, circle_html, call_html]
    controls = [play_button, pause_button, speed]
    # .select: Gradio 6.30 also fires .input on blur, which would restart the replay
    race.select(pick_race, race, [state, driver, timer, *controls, *panels], **HIDDEN)
    driver.input(pick_driver, [state, driver], [state, *panels], **HIDDEN)
    play_button.click(play, state, [state, timer], **HIDDEN)
    pause_button.click(pause, state, [state, timer, *panels], **HIDDEN)
    speed.input(set_speed, [state, speed], state, **HIDDEN)
    timer.tick(tick, state, [state, timer, *panels], **HIDDEN)
