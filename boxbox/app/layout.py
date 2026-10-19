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
QUICK = (
    "Box or stay out?",
    "Why?",
    "What gap behind does the card show?",
    "Will it rain later?",
)
CSS = """
.brand { font-size: 1.4em; font-weight: 800; }
.brand span { font-weight: 400; color: #9aa0a6; }
.stub { background: #f2a900; color: #111; padding: 2px 10px; border-radius: 6px; font-weight: 700; }
.engine, .badge { border: 1px solid #9aa0a6; border-radius: 10px; padding: 1px 8px; margin-left: 8px; }
.stub, .engine, .badge { white-space: nowrap; display: inline-block; margin-top: 4px; }
.chip { display: inline-block; padding: 2px 10px; margin: 6px 6px 0 0; border-radius: 12px;
        border: 2px solid var(--chip); font-weight: 600; }
.situation .race { font-size: 1.2em; font-weight: 700; }
.mono { font-family: ui-monospace, Menlo, monospace; }
.banner { border-left: 8px solid var(--call, #3a3f47); padding: 10px 16px; border-radius: 6px;
          background: #1e2128; }
.banner .call { font-size: 2em; font-weight: 800; color: var(--call); }
.banner.idle { color: #9aa0a6; font-size: 1.2em; font-style: italic; background: none;
               border: 1px dashed #3a3f47; }
.banner.bad { border-left-color: #e5484d; font-size: 1.2em; }
.inputs { width: 100%; border-collapse: collapse; }
.inputs td, .inputs th { padding: 4px 8px; border-bottom: 1px solid #3a3f47; text-align: left; }
.inputs tr.unknown td { background: rgba(255, 209, 46, 0.15); }
.policy .note, .note { color: #9aa0a6; font-size: 0.9em; }
"""
DARK = "() => { document.body.classList.add('dark'); }"  # pit-wall screens are dark


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


def upload_card(path: str, on: bool) -> tuple:
    """An uploaded card, or the error alone when the file is refused."""
    card, problem = load_upload(path)
    if problem:
        gr.Warning(problem)
        return (gr.skip(),) * 4 + (problem,) + (gr.skip(),) * 7  # keep the current card
    return show_card(card, on)


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


def build_app(
    respond: Respond = stub_respond,
    engine: str = STUB,
    cards: dict[str, dict[str, Any]] | None = None,
    turns: int | None = None,
) -> gr.Blocks:
    """The demo screen. Task 2.8 passes the real engine and its name, nothing else."""
    cards = cards or sample_cards()
    turns = turns or RunConfig().history_turns
    first = next(iter(cards))
    badge = "stub" if respond is stub_respond else "engine"
    with gr.Blocks(title="BoxBox") as app:
        card, history = gr.State(cards[first]), gr.State([])
        with gr.Row():
            gr.HTML(
                f'<span class="brand">BoxBox <span>pit call assistant</span></span> '
                f'<span class="{badge}">{engine}</span>'
                f'<span class="badge">Policy {POLICY_VERSION}</span>'
            )
            picker = gr.Dropdown(list(cards), value=first, label="Race card", scale=2)
            upload = gr.UploadButton(
                "Upload card", file_types=[".json"], size="sm", scale=0, min_width=140
            )
        with gr.Row():
            with gr.Column(scale=2):
                situation, circle = gr.HTML(), gr.Plot(show_label=False)
                tyres, inputs = gr.Plot(show_label=False), gr.HTML()
                with gr.Accordion("Raw card", open=False):
                    raw = gr.Code(language="json")
            with gr.Column(scale=3):
                call = gr.HTML(P.banner(None))
                rule_on = gr.Checkbox(False, label="Policy check: show the rule's call")
                policy = gr.HTML(visible=False)
                chat = gr.Chatbot(
                    label="Conversation", height=380, buttons=["copy", "copy_all"]
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
                    gr.Markdown(f"Engine sees the last {turns} exchanges")
                error = gr.Markdown()
        with gr.Accordion("Role and limits", open=False):
            gr.Markdown(role_text(respond is stub_respond))
        everything = [card, history, chat, message, error, situation, circle, tyres]
        everything += [inputs, raw, call, policy]
        exchange = [history, chat, message, error, call, policy]
        asking = partial(ask, respond, turns)
        picker.change(
            lambda name, on: show_card(cards[name], on), [picker, rule_on], everything
        )
        upload.upload(upload_card, [upload, rule_on], everything)
        send_button.click(asking, [card, history, message, rule_on], exchange)
        message.submit(asking, [card, history, message, rule_on], exchange)
        for button, text in zip(quick, QUICK):
            button.click(
                lambda c, h, on, t=text: asking(c, h, t, on),
                [card, history, rule_on],
                exchange,
            )
        reset.click(clear, [card, rule_on], [history, chat, error, call, policy])
        chat.clear(
            clear, [card, rule_on], [history, chat, error, call, policy]
        )  # its bin icon
        rule_on.change(toggle, [card, history, rule_on], [inputs, call, policy])
        app.load(show_card, [card, rule_on], everything)
    return app


def launch(respond: Respond = stub_respond, engine: str = STUB, **options: Any) -> Any:
    """Build the screen and launch it with the pit-wall theme; options go to Gradio."""
    theme = gr.themes.Base(primary_hue="orange", neutral_hue="slate")
    return build_app(respond, engine).launch(theme=theme, css=CSS, js=DARK, **options)
