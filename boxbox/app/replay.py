"""The replay tab: a race played back on the circle, with the policy 2.0 call.

The pit window follows the track status at the clock, and the call is policy 2.0 on
the 2.0 card.
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
    frame,
    load_splits,
    load_timeline,
    pit_window,
    status_now,
)
from boxbox.data.splits import CLOSED_SPLITS, SPLITS_V2_FILE
from boxbox.rules import format_answer

from . import panels as P

TICK = 0.5  # seconds between timer ticks
SOUND = Path("boxbox.wav")  # played on each new 2.0 card whose policy 2.0 call is BOX
SPEEDS = ("x1", "x2", "x4")
HIDDEN = {"api_visibility": "private", "show_progress": "hidden"}


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
    status = status_now(line, t)
    return (
        f'<div class="situation"><div class="race">{html.escape(line.event)}</div>'
        f'<div class="mono">{local:%H:%M:%S} local &nbsp; {elapsed} elapsed &nbsp; '
        f'Lap {lap}/{line.total_laps} &nbsp; <span class="track">Track {status}'
        f"</span></div></div>"
    )


def _name(line: Timeline, driver: str) -> str:
    return line.drivers.get(driver, {}).get("acronym") or f"car {driver}"


def _team_car(
    line: Timeline,
    driver: str,
    degrees: float,
    inside: bool = False,
    named: bool = True,
) -> str:
    """One car on the ring in its team colour, labelled with its acronym."""
    x, y = P._xy(degrees, P.RADIUS)
    lx, ly = P._xy(degrees, P.RADIUS - 26 if inside else P.RADIUS + 26)
    side = math.sin(math.radians(degrees))
    anchor = "middle" if inside or degrees == 0 else "start" if side > 0 else "end"
    colour = line.drivers.get(driver, {}).get("colour") or "var(--bx-ink)"
    dot = f'<circle cx="{x:.1f}" cy="{y:.1f}" r="8" fill="{html.escape(colour)}" class="car"/>'
    if not named:
        return dot
    return (
        f'{dot}<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" '
        f'dominant-baseline="middle">{html.escape(_name(line, driver))}</text>'
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


def circle(line: Timeline, driver: str, now: dict[str, Any], window: tuple) -> str:
    """Every car by time gap from `driver`, on top, and the pit window in yellow for
    the track status at the clock."""
    scale, angles = now["scale"], now["angles"]
    loss, condition = window
    shapes = [
        f'<circle cx="{P.CENTRE[0]}" cy="{P.CENTRE[1]}" r="{P.RADIUS}" class="ring"/>'
    ]
    if loss is not None and scale:
        shapes.append(P._band(-loss / scale * 360, -(loss + P.MARGIN) / scale * 360))
    named = _named(angles)
    shapes += [
        _team_car(line, other, angle, named=other in named)
        for other, angle in angles.items()
    ]
    shapes.append(_team_car(line, driver, 0, inside=True))
    text = (
        f"{condition} pit window {loss:.1f} to {loss + P.MARGIN:.1f} s back"
        if loss is not None
        else "no pit window"
    )
    text = _neighbours(line, angles, scale) + text
    label = (
        f"{_name(line, driver)} on top, {len(angles)} other cars by time gap. {text}."
    )
    box = f"0 0 {P.CIRCLE_WIDTH} {P.CIRCLE_HEIGHT}"
    svg = P._svg(box, label, "".join(shapes))
    return f'<div class="chart replay">{svg}<div class="readout">{text}</div></div>'


def _banner(card: dict | None, lap: int | None, driver: str) -> str:
    if card is not None:
        return P.banner(format_answer(card))
    if lap is None:
        why = f"Car {driver} is no longer running."
    else:
        why = f"No 2.0 card for car {driver} at lap {lap}: pit lane, final lap or no timing."
    return f'<div class="banner idle"><div class="call">No card</div><div class="why">{why}</div></div>'


def calls(
    card_v2: dict | None,
    lap: int | None,
    driver: str,
    key: str = "",
) -> str:
    """Policy 2.0 on the 2.0 card, read when the car started its lap: a safety car out
    since then reaches it at the line.

    When policy 2.0 says BOX, `data-box` carries the card's `key`, and the page plays
    the sound once for each new key (`sound_head`).
    """
    when = f", lap {lap} card, as of lap {lap - 1}" if lap else ""
    parsed = P.parse_answer(format_answer(card_v2)) if card_v2 is not None else None
    box = parsed is not None and parsed[0] == "BOX"
    marker = f' data-box="{html.escape(key)}"' if box and key else ""
    return (
        f'<div class="calls" data-sound="replay"{marker}>'
        f'<div><div class="label">Policy 2.0, card 2.0{when}</div>'
        f"{_banner(card_v2, lap, driver)}</div></div>"
    )


def view(state: dict[str, Any], t: float) -> tuple[str, str, str]:
    """The clock, the circle and the call at race time t."""
    line, driver = timeline(state["race"]), state["driver"]
    now = frame(line, driver, t)
    _, card_v2, lap = cards_at(line, driver, t)
    return (
        clock_text(line, now["lap"], t),
        circle(line, driver, now, pit_window(line, driver, t)),
        calls(card_v2, lap, driver, f"{state['race']}|{driver}|{lap}"),
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
  const last = {{}};  // per panel; a panel out of the page keeps its last key
  new MutationObserver(() => {{
    for (const panel of document.querySelectorAll("[data-sound]")) {{
      const key = panel.dataset.box || null;
      if (key && key !== last[panel.dataset.sound]) {{
        sound.currentTime = 0;
        sound.play().catch(() => {{}});
      }}
      last[panel.dataset.sound] = key;
    }}
  }}).observe(document.documentElement, {{ childList: true, subtree: true }});
}})();
</script>"""


def pick_race(race_id: str) -> tuple:
    """A new race, paused at the end of lap 1 on its leader, and the controls on."""
    if not race_id:  # the dropdown was cleared
        return (gr.skip(),) * 10
    line = timeline(race_id)
    order = running_order(line)
    state = {
        "race": race_id,
        "driver": order[0],
        "t": line.first,
        "end": line.end,
        "wall": None,
        "speed": "x1",
    }
    names = [(f"{_name(line, d)} ({d})", d) for d in order]
    drivers = gr.update(choices=names, value=order[0], interactive=True)
    on = gr.update(interactive=True)
    laps = gr.update(maximum=line.total_laps - 1, value=2, interactive=True)
    controls = (on, on, gr.update(interactive=True, value="x1"), laps)
    return state, drivers, gr.update(active=False), *controls, *view(state, line.first)


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


def jump(state: dict[str, Any], lap: int) -> tuple:
    """Move the clock to the start of a lap; a running replay keeps running from it."""
    line = timeline(state["race"])
    # a lap typed digit by digit passes through 1, below the slider's real range
    lap = min(max(int(lap or 2), 2), line.total_laps - 1)
    t = min(lap_start(line, lap), state["end"])
    wall = None if state["wall"] is None else time.monotonic()
    state = {**state, "t": t, "wall": wall}
    return state, *view(state, t)


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
    lap = gr.Slider(1, 3, value=2, step=1, label="Jump to lap", interactive=False)
    clock_html, circle_html, call_html = gr.HTML(), gr.HTML(), gr.HTML()
    panels = [clock_html, circle_html, call_html]
    controls = [play_button, pause_button, speed, lap]
    # .change: .select misses a choice made with the keyboard, and nothing else writes
    # the race, so .change fires only on a real new choice
    race.change(pick_race, race, [state, driver, timer, *controls, *panels], **HIDDEN)
    driver.input(pick_driver, [state, driver], [state, *panels], **HIDDEN)
    play_button.click(play, state, [state, timer], **HIDDEN)
    pause_button.click(pause, state, [state, timer, *panels], **HIDDEN)
    speed.input(set_speed, [state, speed], state, **HIDDEN)
    # .change for typed laps and arrow keys, .release to replay the same lap again
    lap.change(jump, [state, lap], [state, *panels], **HIDDEN)
    lap.release(jump, [state, lap], [state, *panels], **HIDDEN)
    timer.tick(tick, state, [state, timer, *panels], **HIDDEN)
