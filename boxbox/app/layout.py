"""The Gradio pit-wall screen: layout and wiring only, with the engine passed in."""

from __future__ import annotations

import json
from functools import partial
from typing import Any

import gradio as gr

from boxbox.config import RunConfig
from boxbox.rules import POLICY_VERSION, TYRE_LIMITS

from . import panels as P
from .session import (
    Respond,
    latest_answer,
    load_upload,
    sample_cards,
    send,
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
  --bx-unknown: rgba(100, 116, 139, 0.16);
}
.dark {
  --bx-ink: #f1f5f9; --bx-muted: #94a3b8; --bx-ring: #64748b; --bx-bad: #f87171;
  --bx-box: #f28c28; --bx-stay: #60a5fa; --bx-nocall: #9aa0a6;
  --bx-zone1: #334155; --bx-zone2: #475569; --bx-zone3: #64748b; --bx-zone-ink: #ffffff;
  --bx-unknown: rgba(148, 163, 184, 0.16);
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
    card: dict[str, Any], history: list[dict[str, str]], rule_on: bool
) -> tuple:
    answer = latest_answer(history)
    return P.banner(answer), gr.update(
        value=P.policy_panel(card, answer), visible=rule_on
    )


def show_card(card: dict[str, Any], on: bool) -> tuple:
    """A card change: the new card, an empty conversation and redrawn panels."""
    return card, [], [], "", "", *_card_view(card, on), *_call_view(card, [], on)


def pick_card(cards: dict[str, dict[str, Any]], name: str, on: bool) -> tuple:
    """A card chosen in the picker, which gets its plain label back."""
    return *show_card(cards[name], on), gr.update(label=PICKER)


def upload_card(path: str, on: bool) -> tuple:
    """An uploaded card with the picker emptied, or the error alone when it is refused."""
    card, problem = load_upload(path)
    if problem:
        gr.Warning(problem)
        return (gr.skip(),) * 4 + (problem,) + (gr.skip(),) * 8  # keep the current card
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
) -> tuple:
    """One exchange; on an engine error the message stays in the box to retry."""
    new, problem = send(card, history, text, respond, turns)
    if problem:
        gr.Warning(problem)
    return new, new, text if problem else "", problem or "", *_call_view(card, new, on)


def clear(card: dict[str, Any], on: bool) -> tuple:
    """Reset: an empty conversation on the same card."""
    return [], [], "", *_call_view(card, [], on)


def toggle(card: dict[str, Any], history: list, on: bool) -> tuple:
    """The policy check turned on or off."""
    return P.inputs_table(card, on), *_call_view(card, history, on)


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
) -> gr.Blocks:
    """The demo screen. Task 2.8 passes the real engine, its name and the run's turns."""
    cards = cards or sample_cards()
    turns = RunConfig().history_turns if turns is None else turns
    first = next(iter(cards))
    badge = "stub" if respond is stub_respond else "engine"
    with gr.Blocks(title="BoxBox", analytics_enabled=False) as app:  # no telemetry
        card, history = gr.State(cards[first]), gr.State([])
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
                rule_on = gr.Checkbox(False, label="Policy check: show the rule's call")
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
        everything = [card, history, chat, message, error, situation, circle, tyres]
        everything += [inputs, raw, call, policy]
        exchange = [history, chat, message, error, call, policy]
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
            locked.then(fn, inputs, exchange, **hidden).then(
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
        sending(send_button.click, asking, [card, history, message, rule_on])
        sending(message.submit, asking, [card, history, message, rule_on])
        for button, text in zip(quick, QUICK):
            question = partial(lambda t, c, h, on: asking(c, h, t, on), text)
            sending(button.click, question, [card, history, rule_on])
        for trigger in (
            reset.click,
            chat.clear,
        ):  # chat.clear is the conversation's bin icon
            trigger(
                clear, [card, rule_on], [history, chat, error, call, policy], **hidden
            )
        rule_on.change(
            toggle, [card, history, rule_on], [inputs, call, policy], **hidden
        )
        app.load(show_card, [card, rule_on], everything, **hidden)
    return app


def launch(
    respond: Respond = stub_respond,
    engine: str = STUB,
    turns: int | None = None,
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
    settings = {"footer_links": ["gradio"], "run_history": False} | options
    return build_app(respond, engine, turns=turns).launch(
        theme=theme, css=CSS, **settings
    )
