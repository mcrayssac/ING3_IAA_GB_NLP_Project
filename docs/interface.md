# Interface

The Gradio app in `boxbox/app/` is a pit-wall screen. It shows one race card beside the conversation about it. This file holds the screen layout and one spec per feature.

## Audience and scope

BoxBox is for pit strategists and paddock team members who debrief or train on completed races. The team agreed this audience on 19 October (#10). It replaces the earlier content creators and analysts.

The scope stays the one in `docs/race-card-contract.md`: one car, one lap of a completed dry race, policy 1.1. Live races, wet strategy, forecasts, multi-stop plans, betting and team radio stay out, because the cards and the model only know historical laps.

The screen shows only what the model saw. The one exception is the policy check, which is off until the user turns it on.

## Screen layout

```text
+----------------------------------------------------------------------------+
| BoxBox  [card picker v]  [Upload card (JSON)]  [Stub]  Policy 1.1          |
+--------------------------------+-------------------------------------------+
| Illustrative GP  Lap 30/60     | CALL  BOX                                 |
| Car 44  GREEN  DRY  MEDIUM 18  | WHY   With MEDIUM tyres aged 18 laps, ... |
|                                | [ ] Policy check                          |
| decision inputs                +-------------------------------------------+
|                                | conversation                              |
| tyre window + readout          |                                           |
|                                | [Box or stay out?] [Why?] [Gap behind?]   |
| circle of doom + readout       | [ message ..................... ] [Send]  |
| > raw card                     | [Reset]  Engine sees the last 3 exchanges |
+--------------------------------+-------------------------------------------+
| > Role and limits                                                          |
+----------------------------------------------------------------------------+
```

The left column describes the race situation, numbers first and their pictures after, and the right column holds the call and the conversation. Both stay visible on a laptop screen. The screen follows the system light or dark appearance, and timing numbers use IBM Plex Mono with tabular figures.

## Header bar

- The product name.
- The card picker. Each label starts with "Synthetic example:" or "Real race:", so the two kinds of card stay apart. After an upload the picker empties and reads "Race card (uploaded file on screen)", so it never names a card that is not shown.
- An upload button, "Upload card (JSON)".
- The engine badge. Until task 2.8 it reads "Stub: rule answers, not a trained model" in amber. With the real engine it reads "Adapter A".
- The policy version, "Policy 1.1".

## Race situation (left column)

### Situation strip

- Season and event, lap L of total laps, and the car number.
- A track status chip with a flag-coloured dot: GREEN green, SC and VSC yellow, RED red, unknown grey.
- The surface.
- A compound chip with a Pirelli-coloured dot (SOFT red, MEDIUM yellow, HARD white) and the tyre age in laps.

Every chip carries its text, and each dot has a neutral outline so a white dot still shows on a light screen. No state relies on colour alone.

### Circle of doom

The circle is one lap measured in time. It shows where the card's car would rejoin the race if it boxed on this lap, compared with the car behind.

- Data comes from the race card only, so the screen never shows more than the model saw.
- It uses `gap_ahead` and `gap_behind` with their `driver_number`, `pit_loss_seconds` and `reference_lap_seconds`.
- Cars run clockwise and the card's car sits at the top. A gap of `g` seconds is `g / reference_lap_seconds × 360°`, clockwise for the car ahead and counter-clockwise for the car behind.
- The rejoin point sits one pit loss behind the car, followed by a 2.0-second band for the rejoin margin. The car behind is cleared when it sits past the end of the band, as in rule 6 of the contract.
- Cars are neutral markers with text labels: "car N" inside the ring for the card's car, "ahead" and "behind" outside it. The car behind is hollow when it sits inside the margin. The margin is a hatched neutral arc that starts at a "rejoin" diamond.
- A readout under the circle gives its numbers in words and seconds, for example "Rejoins 21.0 s back, margin to 23.0 s. Car 63 behind at 24.0 s clears the margin by 1.0 s. Car 16 ahead at 1.5 s."
- An `UNKNOWN` gap is not drawn and the readout says "Gap ahead unknown". A `NONE` gap reads "No car ahead".
- Without `reference_lap_seconds` the circle is not drawn, and without `pit_loss_seconds` it has no rejoin point. The readout names the missing field in both cases.
- A line under the readout states the assumption: the pit loss is fixed and the other cars keep their pace.
- The circle is an SVG in `gr.HTML`, with `role="img"` and an `aria-label` equal to its readout, so a screen reader hears the same numbers. Its colours are CSS variables, so it follows the appearance.
- The interface implementation must include tests of the angles and the rejoin point on hand-written cards, including an unknown gap and a missing lap time.

### Tyre window

A strategist first asks whether the tyres are in the pit window. The gauge answers from the card and the policy thresholds.

- A horizontal bar of tyre laps, from 0 to 4 laps past the larger of the tyre age and the compound's `old` threshold.
- Three zones from `TYRE_LIMITS` in `boxbox.rules`, in three neutral tones:
  - "too young", below `young`: too young to stop
  - "window", from `young` to `old`: a stop only with the car ahead within 2.0 s, which a caption under the bar recalls
  - "opportunity", from `old`: an opportunity whatever the gap ahead
- A zone name is written on the bar when it fits. The readout always names the zone, for example "15 laps on MEDIUM, in the window. Window from 12 laps, opportunity from 18."
- For example, MEDIUM tyres have zones that change at 12 and 18 laps.
- A marker at the card's tyre age.
- For a compound that is not SOFT, MEDIUM or HARD, or an unknown age, the bar is not drawn and the readout names the reason.
- Like the circle, the bar is an SVG with an `aria-label` equal to its readout.

### Decision inputs

One row per field the rule reads, so a missing value is seen before the question is asked.

| Row | Shows |
|---|---|
| Tyre age | laps and compound |
| Gap ahead | seconds and car number, "no car" or "unknown" |
| Gap behind | seconds and car number, "no car" or "unknown" |
| Pit loss | seconds and the lap it was estimated at, or "missing" |
| Track status | GREEN, SC, VSC, RED or unknown |
| Surface | DRY, WET or unknown |

Rows with an unknown or missing value get a neutral tint, italic text and a "?" mark. With the policy check on, a last column says whether the rule uses the field on this card. On a card where the rule gives NO CALL, no input decides a stop, so one line under the table points to the rule's reason instead.

### Raw card

The full card JSON sits in a collapsed accordion, so a reviewer can check any value.

## Call and conversation (right column)

### Call banner

- It shows the CALL of the latest assistant answer in large text, with its WHY below. The colour follows the call: BOX orange, STAY OUT blue, NO CALL grey, in the shades of the colour table below. The pair never relies on red and green, and the call is always written in words.
- An answer that is not exactly the two `CALL:` and `WHY:` lines of the contract shows "Answer not in CALL/WHY format". The banner uses the strict-format rules of the 2.3b evaluator (`boxbox.evaluation.parsing.parse_response`): Windows line ends and one final newline pass, while a WHY with leading or trailing blanks fails. A test keeps the two in agreement. The raw text stays in the conversation. The app never repairs an answer, because a format failure is a result.
- Before the first question the banner reads "No call yet", with the hint "Ask a question or pick one below." in a muted style, so it does not look like an input.
- While the engine works, the banner reads "Waiting for the engine".

### Policy check

A toggle under the banner, off by default.

- When on, it shows "Rule on this card:" with the rule's call, in its call colour, and WHY from `decide(card)`, and a badge saying whether the latest answer matches that call.
- An out-of-scope request should differ, because the assistant answers NO CALL to it. A note under the badge says so.
- It adds the "used by the rule" column to the decision inputs.
- It stays off by default because the default screen shows only what the model saw.

### Conversation

- `gr.Chatbot` in messages format, which is the contract's list of `{role, content}`. While it is empty it says what to ask.
- A message box with a Send button. Enter also sends.
- Quick questions as buttons: "Box or stay out?", "Why?", "What gap behind does the card show?" and one out-of-scope request, "Will it rain later?". A button sends its question at once, without going through the message box.
- From a send until the answer, Send, the message box, the quick questions, the card picker, the upload button and Reset are disabled. A slow engine never gets the same question twice, and a card change or a reset cannot be undone by an answer that lands late. The bin icon of the conversation cannot be disabled in Gradio 6, so it should not be used while the banner reads "Waiting for the engine".

### Reset and history

- Reset clears the conversation and the banner, and keeps the card. The bin icon of the conversation does the same.
- A status line under the input reads "Engine sees the last 3 exchanges", "the last exchange" or "no earlier exchange". The number comes from `RunConfig.history_turns`, or from the `turns` given to `launch`.

### Engine errors

- When the engine raises an error, the app shows it in plain words under the input and as a `gr.Warning`, for example "The engine failed: <message>. The conversation is unchanged."
- The failed turn is not stored in the history.

## Appearance and colour

The screen follows the system light or dark setting, with no switch of its own. Every custom colour is a CSS variable with a light and a dark value, checked against the block background (white in light, `#1e293b` in dark):

| Token | Light | Dark | Use |
|---|---|---|---|
| ink | `#0f172a` (17.9:1) | `#f1f5f9` (13.4:1) | chart text and marks |
| muted | `#475569` (7.6:1) | `#94a3b8` (5.7:1) | notes, ticks, idle banner |
| ring | `#64748b` (4.8:1) | `#64748b` (3.1:1) | lap ring, margin arc, borders |
| BOX | `#b45309` (5.0:1) | `#f28c28` (6.0:1) | BOX call |
| STAY OUT | `#1d4ed8` (6.7:1) | `#60a5fa` (5.8:1) | STAY OUT call |
| NO CALL | `#475569` (7.6:1) | `#9aa0a6` (5.5:1) | NO CALL call |

Each colour keeps one meaning:

- The three call colours appear only for a call: the banner and the policy check.
- Flag and Pirelli colours appear only in the chip dots.
- Actions such as Send use neutral slate, white on slate at 4.8:1 in light and 7.6:1 in dark.
- Charts and the unknown-row tint are neutral.

## Role and limits

A collapsed accordion at the bottom of the screen holds:

- who the tool is for and what it does
- the policy threshold table from the contract
- what it refuses, and what NO CALL means: the card does not let the policy justify either action
- while the stub runs, a note that answers come from the rule and do not understand the question
- the data credit: OpenF1 timing and Jolpica-F1 event data, under CC BY-NC-SA 4.0

## Cards

- Synthetic examples: the 5 cards of `reference/fixtures.json`, read in place.
- Real races: about 8 validation cards in `data/demo/cards.json`, chosen by `scripts/demo_cards.py`. They cover one card per rule path, one under a safety car or VSC, and one with a real missing field. They come from validation races, so adapter A never trained on them. No final card is ever shown. `data/demo/NOTICE` puts them under CC BY-NC-SA 4.0, as for the corpus.
- Uploaded card: a JSON file holding one object.
  - A file that is not a JSON object shows an error and keeps the current card.
  - A card the rule cannot assess is accepted, because NO CALL is a valid answer for it.
  - The panels draw what the card allows and name what is missing.

## Behaviour

- A card change, from the picker or an upload, clears the conversation, the banner and the message box, and redraws the left column.
- Every browser session has its own card and history in `gr.State`. Nothing mutable sits at module level, so two people on the same app never see each other's conversation.
- The app calls `respond(card, history[-2 * turns:], message)`, where `turns` is `RunConfig.history_turns` unless `launch` is given another value. With `turns = 0` the engine receives an empty history, as in the 2.3b evaluator. The engine receives only the current card's history.
- Until task 2.8 the engine is `stub_respond`, which returns `format_answer(card)` for any message. It cannot follow up or refuse a request, and the badge and the role text say so.

## Code layout

| File | Content |
|---|---|
| `boxbox/app/panels.py` | Pure functions from a card or an answer to HTML: `situation`, `inputs_table`, `used_by_rule`, `tyre_zones`, `tyre_readout` and `tyre_window`, `circle_points`, `circle_readout` and `circle_of_doom`, `parse_answer`, `banner`, `policy_panel`. Charts are hand-written SVG. |
| `boxbox/app/session.py` | `stub_respond`, `sample_cards`, `send` (one exchange with the bounded history), `load_upload` and `latest_answer`. |
| `boxbox/app/layout.py` | The colour tokens, the event handlers (`show_card`, `pick_card`, `upload_card`, `ask`, `clear`, `toggle`, `busy`, `ready`), `history_line` for the status line, `build_app(respond, engine, cards, turns)` for the layout and wiring, and `launch`, which adds the theme. |
| `boxbox/app/__main__.py` | `python -m boxbox.app` opens the app in the browser. |
| `scripts/demo_cards.py` | Writes `data/demo/cards.json` from the validation cards. |

- The footer shows only "Built with Gradio". The API link, the run history and Gradio's telemetry are off, and every event is private to the screen.
- `used_by_rule` counts a known field as used when making it unknown changes `decide(card)`. It reuses `remove_field` and copies no threshold logic. `remove_field` now lives in `boxbox.rules`, and `boxbox.corpus` keeps exporting it, because the app may import only `rules` and `model`.
- Gradio 6 takes the theme and CSS at launch time, so `launch` builds the app and passes them. Gradio is pinned in `requirements.txt`.
- Task 2.8 calls `launch(respond=..., engine="Adapter A", turns=config.history_turns)` with the real engine and the run's config, and changes nothing else.
- A hung engine keeps the controls disabled until it returns. Bounding the generation time belongs to the engine's settings (2.5a), and the 2.8 check covers it.

## Notebook launch cell

```python
from boxbox.app import launch

RUN_DEMO = True  # False for the clean nbconvert run, where nobody can click
if RUN_DEMO:
    launch(inline=True)
```

Like `RUN_TRAINING` for the training cells, `RUN_DEMO` lets a clean run of the notebook skip a server that nobody can use. In a hosted notebook such as Colab, Gradio opens a public link unless `launch` gets `share=False`. Task 2.8 decides which it wants. The cell is kept here until task 2.8 puts it in `agent.ipynb`, so the shared notebook is not edited by two people at once.

## Tests

`tests/test_app.py` checks:

- the circle angles and rejoin point, including an unknown gap, no car, a missing pit loss and a missing lap time
- the circle readout, including a car behind short of the margin and a card with every gap and time missing
- the tyre window zones for each dry compound, its readout, and the reason when it is not drawn
- that both charts are SVG labelled with their readout, skipped when data is missing, and that the app uses no matplotlib
- `parse_answer` on valid and malformed answers, its agreement with the evaluator's `parse_response` on edge cases, `used_by_rule`, the highlighted rows and the rule column on a NO CALL card
- that text from an uploaded card is escaped
- send, reset, card change, an engine error that leaves the history unchanged and raises a warning, and the history bound, including no history at all
- the picker label after a pick and after an upload
- that sending disables the controls until the engine answers
- two sessions that stay independent
- an upload that is not one JSON object
- the picker with 5 synthetic and 8 real cards

The browser walkthrough runs on the synthetic and real cards, in light and dark, before review.
