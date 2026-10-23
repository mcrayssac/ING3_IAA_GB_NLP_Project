"""The Gradio pit-wall screen: layout and wiring only, with the engine passed in."""

from __future__ import annotations

import json
from functools import partial
from typing import Any

import gradio as gr

from boxbox.config import RunConfig
from boxbox.rules import POLICY_VERSION, TYRE_LIMITS

from . import panels as P
from .replay import Asker, replay_tab, sound_head
from .session import (
    Respond,
    exchange,
    latest_answer,
    load_upload,
    sample_cards,
    stub_respond,
)

STUB = "Stub: rule answers, not a trained model"
PICKER = "Race card"
QUICK = (
    "Box or stay out?",
    "Why?",
    "What gap behind does the card show?",
    "Will it rain later?",
)
# colour tokens for the light and dark appearance; Gradio sets .dark from the system setting
CSS = """
:root {
  --bx-ink: #0f172a; --bx-muted: #475569; --bx-ring: #64748b; --bx-bad: #b91c1c;
  --bx-box: #b45309; --bx-stay: #1d4ed8; --bx-nocall: #475569;
  --bx-zone1: #e2e8f0; --bx-zone2: #cbd5e1; --bx-zone3: #94a3b8; --bx-zone-ink: #0f172a;
  --bx-unknown: rgba(100, 116, 139, 0.16); --bx-window: #b08600;
  --bx-pit: #6d28d9; --bx-on-call: #ffffff;
}
.dark {
  --bx-ink: #f1f5f9; --bx-muted: #94a3b8; --bx-ring: #64748b; --bx-bad: #f87171;
  --bx-box: #f28c28; --bx-stay: #60a5fa; --bx-nocall: #9aa0a6;
  --bx-zone1: #334155; --bx-zone2: #475569; --bx-zone3: #64748b; --bx-zone-ink: #ffffff;
  --bx-unknown: rgba(148, 163, 184, 0.16); --bx-window: #facc15;
  --bx-pit: #a78bfa; --bx-on-call: #0f172a;
}
.brand { font-size: 1.4em; font-weight: 800; }
.brand span { font-weight: 400; color: var(--bx-muted); }
.stub { background: #f2a900; color: #111; padding: 2px 10px; border-radius: 6px; font-weight: 700; }
.engine, .badge { border: 1px solid var(--bx-ring); border-radius: 10px; padding: 1px 8px;
                  margin-left: 8px; }
.stub, .engine, .badge { white-space: nowrap; display: inline-block; margin-top: 4px; }
.chip { display: inline-flex; align-items: center; gap: 6px; padding: 2px 10px;
        margin: 6px 6px 0 0; border-radius: 12px; border: 1px solid var(--bx-ring);
        font-weight: 600; }
.chip i { width: 10px; height: 10px; border-radius: 50%; border: 1px solid var(--bx-ring); }
.situation .race { font-size: 1.2em; font-weight: 700; }
.mono, .readout { font-variant-numeric: tabular-nums; }
.mono { font-family: var(--font-mono); }
.banner { border-left: 8px solid var(--call, var(--bx-ring)); padding: 10px 16px;
          border-radius: 6px; background: var(--block-background-fill); }
.banner .call { font-size: 2em; font-weight: 800; color: var(--call, var(--bx-ink)); }
.banner.idle .call { font-size: 1.4em; color: var(--bx-muted); }
.banner.bad { border-left-color: var(--bx-bad); font-size: 1.2em; }
.banner .cut { color: var(--bx-bad); font-weight: 700; font-size: 0.9rem; margin-top: 6px; }
.inputs { width: 100%; border-collapse: collapse; }
.inputs td, .inputs th { padding: 4px 8px; border-bottom: 1px solid var(--bx-ring);
                         text-align: left; }
.inputs tr.unknown td { background: var(--bx-unknown); font-style: italic; }
.mark { font-weight: 800; font-style: normal; }
.note { color: var(--bx-muted); font-size: 0.9em; }
.chart-title { font-weight: 600; }
.readout { margin: 6px 0 0; }
.chart svg { width: 100%; max-width: 440px; display: block; margin: 0 auto; }
.chart text { font-size: 13px; fill: var(--bx-ink); }
.chart .ring { fill: none; stroke: var(--bx-ring); stroke-width: 6; }
.chart .band { fill: none; stroke: var(--bx-ink); stroke-width: 14; stroke-dasharray: 2 3; }
.chart.replay .band { stroke: var(--bx-window); stroke-dasharray: none; }
.chart.replay .readout { text-align: center; color: var(--bx-muted); }
.calls .label { font-size: 0.85em; color: var(--bx-muted); margin-bottom: 4px; }
.track { font-weight: 700; }
.chart .rejoin { fill: var(--bx-ink); }
.chart .car { stroke: var(--bx-ink); stroke-width: 2.5; }
.chart .zone1 { fill: var(--bx-zone1); }
.chart .zone2 { fill: var(--bx-zone2); }
.chart .zone3 { fill: var(--bx-zone3); }
.chart .bar { fill: none; stroke: var(--bx-ring); stroke-width: 1.5; }
.chart .zone-label { fill: var(--bx-zone-ink); font-size: 12px; }
.chart .tick { fill: var(--bx-muted); font-size: 12px; }
.chart .age { stroke: var(--bx-ink); stroke-width: 3; }
.chart .age-label { font-weight: 700; }
.bx-bar { border: 1px solid var(--bx-ring) !important; border-radius: 12px !important;
          padding: 6px 10px !important; background: var(--block-background-fill) !important; }
/* Gradio repeats the class on the inner group: one border, one background */
.bx-bar .bx-bar { border: none !important; padding: 0 !important; }
.bx-bar .styler { background: transparent !important; }
.bx-bar .block, .bx-bar .form { border: none !important; box-shadow: none !important;
                                background: transparent !important; }
.bx-bar .row { align-items: center; gap: 12px; }
.bx-speed .wrap { flex-wrap: nowrap; }
.clock { text-align: right; line-height: 1.3; padding: 4px 6px; }
.clock .lap { font-size: 1.5em; font-weight: 600; white-space: nowrap; }
.clock .lap b { font-weight: 800; }
.clock .mono { color: var(--bx-muted); font-size: 0.85em; white-space: nowrap; }
.icon { display: inline-block; height: 1.7em; width: auto; vertical-align: middle; margin-right: 6px;
        flex: none; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden;
           clip: rect(0 0 0 0); white-space: nowrap; }
.strip { display: flex; flex-wrap: wrap; gap: 12px; }
/* one type scale for the tiles: 12 px labels, 14 px values, 18 px and 24 px for the
   main value of a tile */
/* the bases fit the four tiles on one row of about 1,200 px; narrower, they wrap,
   and min-width 0 lets a table scroll inside its tile instead of widening it */
.tile { flex: 1 1 180px; min-width: 0; display: flex; flex-direction: column; gap: 6px;
        border: 1px solid var(--bx-ring); border-radius: 8px; padding: 12px; }
.tile .head { font-size: 12px; font-weight: 600; color: var(--bx-muted);
              text-transform: uppercase; letter-spacing: 0.04em; }
.tile .sub { color: var(--bx-muted); font-size: 12px; }
.tile .scroll { overflow-x: auto; }
.tile.forecast { flex: 1.4 1 330px; }
.tile.track { flex: 0.8 1 150px; border-left: 6px solid var(--flag); }
.tile.track .flagged { flex: 1; display: flex; flex-direction: column; align-items: center;
                       justify-content: center; gap: 6px; text-align: center; }
.tile.track .flagged .icon { height: 3em; margin: 0; }
.tile.track .word { font-size: 24px; font-weight: 700; line-height: 1.1; }
.tile.weather .body { flex: 1; display: flex; align-items: center; gap: 10px; }
.tile.weather .sky { display: flex; flex-direction: column; align-items: center; gap: 4px;
                     font-size: 14px; font-weight: 600; text-align: center; }
.tile.weather .sky .icon { height: 2.6em; margin: 0; }
.metrics { flex: 1; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));
           gap: 8px 10px; }
.metric { display: grid; grid-template-columns: auto 1fr; column-gap: 8px;
          align-items: center; }
.metric .icon { grid-row: span 2; width: 1.6em; height: 1.6em; margin: 0;
                color: var(--bx-muted); }
.metric .label { font-size: 12px; color: var(--bx-muted); }
.metric .value { font-size: 14px; font-weight: 600; white-space: nowrap; }
.tile.weather { flex: 1.2 1 280px; }
.steps, .compounds { width: 100%; border-collapse: collapse; font-size: 14px; }
.steps th, .compounds th { text-align: left; color: var(--bx-muted); font-weight: 600;
                           font-size: 12px; }
.steps td, .steps th, .compounds td, .compounds th {
  padding: 3px 4px; white-space: nowrap; border: none !important;
  border-bottom: 1px solid var(--bx-zone1) !important; }
.steps .icon { height: 1.4em; margin: 0; }
.driver { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin-bottom: 8px; }
.driver .num { display: inline-block; min-width: 2.2em; text-align: center; font-weight: 800;
               border-radius: 6px; padding: 2px 6px; border: 1px solid var(--bx-ring); }
.driver .team { color: var(--bx-muted); }
.calls .banner.box { --call: var(--bx-box); background: var(--bx-box); color: var(--bx-on-call);
                     animation: bx-blink 1s step-end 3; }
.calls .banner.box.odd { animation-name: bx-blink-b; }
.calls .banner.box .call, .calls .banner.box .why { color: inherit; }
.calls .banner.stay { --call: var(--bx-stay); }
.calls .banner.nocall { --call: var(--bx-nocall); }
.calls .banner.pit { --call: var(--bx-pit); }
.calls .banner.out { border-left-style: dashed; }
@keyframes bx-blink { 50% { background: var(--block-background-fill); color: var(--bx-box); } }
@keyframes bx-blink-b { 50% { background: var(--block-background-fill); color: var(--bx-box); } }
@media (prefers-reduced-motion: reduce) { .calls .banner.box { animation: none; } }
.model-call .label { font-size: 0.85em; color: var(--bx-muted); margin-bottom: 4px; }
.model-call .banner.box { --call: var(--bx-box); }
.model-call .banner.stay { --call: var(--bx-stay); }
.model-call .banner.nocall { --call: var(--bx-nocall); }
.model-call .banner.bad .call { font-size: 1.1em; color: var(--bx-bad); }
.model-call .banner.idle .call { font-size: 1.1em; }
.model-call .banner .why { font-size: 0.9em; color: var(--bx-muted); }
.model-call .probs { display: grid; gap: 4px; margin: 8px 0; }
.model-call .prob { display: grid; grid-template-columns: 5.5em 1fr 3em;
                    align-items: center; gap: 8px; font-size: 0.9em; }
.model-call .bar { background: var(--bx-unknown); border-radius: 4px; height: 10px;
                   overflow: hidden; }
.model-call .bar i { display: block; height: 100%; background: var(--bar, var(--bx-ring)); }
.model-call .bar i.box { --bar: var(--bx-box); }
.model-call .bar i.stay { --bar: var(--bx-stay); }
.model-call .bar i.nocall { --bar: var(--bx-nocall); }
.model-call .agree { font-weight: 700; font-size: 0.9em; }
.model-call .note { color: var(--bx-muted); font-size: 12px; margin-top: 4px; }
.chart text.num { font-size: 10px; font-weight: 800; }
.chart .car.pit { stroke-dasharray: 3 2; }
.chart .tick-mark { stroke: var(--bx-ring); stroke-width: 1.5; }
.chart.replay .loss { fill: none; stroke: var(--bx-pit); stroke-width: 5;
                      stroke-linecap: round; }
.chart.replay .window { fill: none; stroke: var(--bx-window); stroke-width: 9; }
.tile.tyres { flex: 1.5 1 360px; }
.compounds td:first-child { display: flex; align-items: center; white-space: nowrap; }
.compounds tr.on td { background: var(--bx-unknown); font-weight: 800; }
.compounds .src { color: var(--bx-muted); font-size: 12px; }
.compounds .best { margin-left: 6px; padding: 0 6px; border-radius: 4px; font-size: 12px;
                   font-weight: 700; color: var(--bx-ink); border: 1px solid var(--bx-ink); }
.standings { width: 100%; border-collapse: collapse; font-size: 0.92em; }
.standings th { text-align: left; color: var(--bx-muted); font-weight: 600; }
.standings td, .standings th { padding: 3px 6px; border-bottom: 1px solid var(--bx-zone1); }
.standings td.car { border-left: 4px solid var(--team); white-space: nowrap; }
.standings tr.me td { font-weight: 800; background: var(--bx-unknown); }
.standings tr.out td { color: var(--bx-muted); }
.standings .pit { color: var(--bx-pit); border: 1px solid var(--bx-pit); border-radius: 4px;
                  padding: 0 4px; font-size: 0.8em; font-weight: 700; }
.standings td:last-child { white-space: nowrap; }
.standings .icon { height: 1.6em; margin-right: 4px; }
"""
WAITING = (
    '<div class="banner idle"><div class="call">Waiting for the engine</div></div>'
)
PLACEHOLDER = (
    "Ask whether the car on the card should box on this lap, then follow up. "
    "The quick questions below are a start."
)


def role_text(stub: bool) -> str:
    """The role and limits shown at the bottom of the screen."""
    rows = "\n".join(
        f"| {c} | {y} laps | {o} laps |" for c, (y, o) in TYRE_LIMITS.items()
    )
    note = (
        "\n\nThe current engine is a preparation stub. It returns the rule's answer to every "
        "message, so it does not understand the question, follow up or refuse a request. "
        "The trained assistant will replace it."
        if stub
        else ""
    )
    return f"""BoxBox helps pit strategists and paddock team members debrief a completed dry race. \
A card describes one car at the start of one lap. Every answer has two lines: the call (BOX, \
STAY OUT or NO CALL) and one sentence on why.

The calls follow policy {POLICY_VERSION}:

| Compound | Opportunity from | Always from |
|---|---:|---:|
{rows}

Between the two ages, a stop needs the car ahead within 2.0 s. A stop also needs no car behind, \
or the car behind at least the pit loss plus 2.0 s back.

BoxBox answers NO CALL to live races, wet tracks, forecasts, multi-stop plans, betting and team \
radio. NO CALL also means the card does not let the policy justify either action, for example \
when a gap or the pit loss is unknown, or under a safety car.{note}

Timing data from OpenF1 and event data from Jolpica-F1, under CC BY-NC-SA 4.0. Synthetic \
examples are illustrative cards, not real races."""


def _card_view(card: dict[str, Any], rule_on: bool) -> tuple:
    return (
        P.situation(card),
        P.circle_of_doom(card),
        P.tyre_window(card),
        P.inputs_table(card, rule_on),
        json.dumps(card, indent=2),
    )


def _call_view(
    card: dict[str, Any],
    history: list[dict[str, str]],
    rule_on: bool,
    cut: bool = False,
) -> tuple:
    answer = latest_answer(history)
    # the exchange count names the answer: an error shows it again without a new sound
    return P.banner(answer, cut, str(len(history) // 2)), gr.update(
        value=P.policy_panel(card, answer), visible=rule_on
    )


def show_card(card: dict[str, Any], on: bool) -> tuple:
    """A card change: the new card, an empty conversation and redrawn panels."""
    view = *_card_view(card, on), *_call_view(card, [], on)
    return card, [], [], "", "", *view, "", False


def pick_card(cards: dict[str, dict[str, Any]], name: str, on: bool) -> tuple:
    """A card chosen in the picker, which gets its plain label back."""
    return *show_card(cards[name], on), gr.update(label=PICKER)


def upload_card(path: str, on: bool) -> tuple:
    """An uploaded card with the picker emptied, or the error alone when it is refused."""
    card, problem = load_upload(path)
    if problem:
        gr.Warning(problem)
        return (
            (gr.skip(),) * 4 + (problem,) + (gr.skip(),) * 10
        )  # keep the current card
    return *show_card(card, on), gr.update(
        value=None, label=f"{PICKER} (uploaded file on screen)"
    )


def ask(
    respond: Respond,
    turns: int,
    card: dict[str, Any],
    history: list,
    text: str,
    on: bool,
    was_cut: bool = False,
) -> tuple:
    """One exchange; on an engine error the message stays in the box to retry.

    The details line describes the new answer. After an error it stays as it was, and
    the banner shows the last answer again, with its cut warning if it had one.
    """
    new, problem, trace = exchange(card, history, text, respond, turns)
    if problem:
        gr.Warning(problem)
    earlier = len(history) // 2
    details = (
        P.answer_details(latest_answer(new), earlier, min(earlier, turns), trace)
        if new is not history
        else gr.skip()
    )
    cut = was_cut if new is history else bool(trace and trace.get("possibly_truncated"))
    view = _call_view(card, new, on, cut)
    return new, new, text if problem else "", problem or "", *view, details, cut


def clear(card: dict[str, Any], on: bool) -> tuple:
    """Reset: an empty conversation on the same card."""
    return [], [], "", *_call_view(card, [], on), "", False


def toggle(card: dict[str, Any], history: list, on: bool) -> tuple:
    """The policy check turned on or off; the banner, and any cut warning, stay."""
    return P.inputs_table(card, on), gr.skip(), _call_view(card, history, on)[1]


def busy(count: int) -> tuple:
    """While the engine runs, nothing can send, change the card or reset the conversation.

    A card change or a reset during an answer would be undone when the answer lands.
    """
    return (gr.update(interactive=False),) * count + (WAITING,)


def ready(count: int) -> tuple:
    """The engine answered: the controls come back."""
    return (gr.update(interactive=True),) * count


def history_line(turns: int) -> str:
    """The status line saying how much of the conversation the engine receives."""
    if turns == 0:
        return "Engine sees no earlier exchange"
    return (
        "Engine sees the last exchange"
        if turns == 1
        else f"Engine sees the last {turns} exchanges"
    )


def build_app(
    respond: Respond = stub_respond,
    engine: str = STUB,
    cards: dict[str, dict[str, Any]] | None = None,
    turns: int | None = None,
    replay: Asker | None = None,
) -> gr.Blocks:
    """The demo screen. Task 2.8 passes the real engine, its name and the run's turns; the
    Replay tab gets its own `replay` asker, which reads 2.0 cards."""
    cards = cards or sample_cards()
    turns = RunConfig().history_turns if turns is None else turns
    first = next(iter(cards))
    badge = "stub" if respond is stub_respond else "engine"
    with gr.Blocks(title="BoxBox", analytics_enabled=False) as app:  # no telemetry
        card, history = gr.State(cards[first]), gr.State([])
        was_cut = gr.State(False)  # whether the answer on the banner may be cut
        with gr.Tab("Card"):
            with gr.Row():
                gr.HTML(
                    f'<span class="brand">BoxBox <span>pit call assistant</span></span> '
                    f'<span class="{badge}">{engine}</span>'
                    f'<span class="badge">Policy {POLICY_VERSION}</span>'
                )
                picker = gr.Dropdown(list(cards), value=first, label=PICKER, scale=2)
                upload = gr.UploadButton(
                    "Upload card (JSON)",
                    file_types=[".json"],
                    size="sm",
                    scale=0,
                    min_width=170,
                )
            with gr.Row():
                with gr.Column(scale=2):  # the numbers first, then the pictures of them
                    situation, inputs, tyres, circle = (
                        gr.HTML(),
                        gr.HTML(),
                        gr.HTML(),
                        gr.HTML(),
                    )
                    with gr.Accordion("Raw card", open=False):
                        raw = gr.Code(language="json")
                with gr.Column(scale=3):
                    call = gr.HTML(P.banner(None))
                    details = gr.HTML()
                    rule_on = gr.Checkbox(
                        False, label="Policy check: show the rule's call"
                    )
                    policy = gr.HTML(visible=False)
                    chat = gr.Chatbot(
                        label="Conversation",
                        height=380,
                        buttons=["copy", "copy_all"],
                        placeholder=PLACEHOLDER,
                    )
                    with gr.Row():
                        quick = [gr.Button(q, size="sm") for q in QUICK]
                    with gr.Row():
                        message = gr.Textbox(
                            placeholder="Ask about this lap", show_label=False, scale=5
                        )
                        send_button = gr.Button("Send", variant="primary", scale=1)
                    with gr.Row():
                        reset = gr.Button("Reset", size="sm", scale=0)
                        gr.Markdown(history_line(turns))
                    error = gr.Markdown()
            with gr.Accordion("Role and limits", open=False):
                gr.Markdown(role_text(respond is stub_respond))
        with gr.Tab("Replay"):
            opening = replay_tab(replay)
        everything = [card, history, chat, message, error, situation, circle, tyres]
        everything += [inputs, raw, call, policy, details, was_cut]
        answered = [history, chat, message, error, call, policy, details, was_cut]
        controls = [send_button, message, *quick, picker, upload, reset]
        asking = partial(ask, respond, turns)
        hidden = {
            "api_visibility": "private"
        }  # the screen is the interface, not an API

        def sending(trigger: Any, fn: Any, inputs: list) -> None:
            locked = trigger(
                partial(busy, len(controls)),
                None,
                [*controls, call],
                trigger_mode="once",
                **hidden,
            )
            # one progress indicator, on the conversation; the banner says it waits
            locked.then(fn, inputs, answered, show_progress_on=chat, **hidden).then(
                partial(ready, len(controls)), None, controls, **hidden
            )

        # .input reacts to people only, so emptying the picker after an upload stays quiet
        picker.input(
            partial(pick_card, cards),
            [picker, rule_on],
            [*everything, picker],
            **hidden,
        )
        upload.upload(upload_card, [upload, rule_on], [*everything, picker], **hidden)
        sending(send_button.click, asking, [card, history, message, rule_on, was_cut])
        sending(message.submit, asking, [card, history, message, rule_on, was_cut])
        for button, text in zip(quick, QUICK):
            question = partial(lambda t, c, h, on, w: asking(c, h, t, on, w), text)
            sending(button.click, question, [card, history, rule_on, was_cut])
        for trigger in (
            reset.click,
            chat.clear,
        ):  # chat.clear is the conversation's bin icon
            trigger(
                clear,
                [card, rule_on],
                [history, chat, error, call, policy, details, was_cut],
                **hidden,
            )
        rule_on.change(
            toggle, [card, history, rule_on], [inputs, call, policy], **hidden
        )
        app.load(show_card, [card, rule_on], everything, **hidden)
        # the Replay tab opens on its default race
        app.load(opening[0], None, opening[1], show_progress="hidden", **hidden)
    return app


def launch(
    respond: Respond = stub_respond,
    engine: str = STUB,
    turns: int | None = None,
    replay: Asker | None = None,
    **options: Any,
) -> Any:
    """Build the screen and launch it with its theme; options go to Gradio's launch."""
    theme = gr.themes.Base(
        primary_hue="slate",
        neutral_hue="slate",
        font_mono=[
            gr.themes.GoogleFont("IBM Plex Mono"),
            "ui-monospace",
            "Menlo",
            "monospace",
        ],
    )
    settings = {
        "footer_links": ["gradio"],
        "run_history": False,
        "head": sound_head(),
    } | options
    return build_app(respond, engine, turns=turns, replay=replay).launch(
        theme=theme, css=CSS, **settings
    )
