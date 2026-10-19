# Interface

The Gradio app in `boxbox/app/` is a pit-wall screen. It shows one race card beside the conversation about it. This file holds the screen layout and one spec per feature.

## Audience and scope

BoxBox is for pit strategists and paddock team members who debrief or train on completed races. The team agreed this audience on 19 October (#10). It replaces the earlier content creators and analysts.

The scope stays the one in `docs/race-card-contract.md`: one car, one lap of a completed dry race, policy 1.1. Live races, wet strategy, forecasts, multi-stop plans, betting and team radio stay out, because the cards and the model only know historical laps.

The screen shows only what the model saw. The one exception is the policy check, which is off until the user turns it on.

## Screen layout

```text
+----------------------------------------------------------------------------+
| BoxBox   [card picker v]  [Upload card]  [Stub: rule answers]  Policy 1.1  |
+--------------------------------+-------------------------------------------+
| Illustrative GP  Lap 30/60     | CALL  BOX                                 |
| Car 44  GREEN  DRY  MEDIUM 18  | WHY   With MEDIUM tyres aged 18 laps, ... |
|                                | [ ] Policy check                          |
| circle of doom                 +-------------------------------------------+
|                                | conversation                              |
| tyre window                    |                                           |
|                                | [Box or stay out?] [Why?] [Gap behind?]   |
| decision inputs                | [ message ..................... ] [Send]  |
| > raw card                     | [Reset]  Engine sees the last 3 exchanges |
+--------------------------------+-------------------------------------------+
| > Role and limits                                                          |
+----------------------------------------------------------------------------+
```

The left column describes the race situation and the right column holds the call and the conversation. Both stay visible on a laptop screen. The theme is dark, as on a pit wall, and timing numbers use a monospace font.

## Header bar

- The product name.
- The card picker, with two groups: "Synthetic examples" and "Real races".
- An upload button for a card JSON file.
- The engine badge. Until task 2.8 it reads "Stub: rule answers, not a trained model" in amber. With the real engine it reads "Adapter A".
- The policy version, "Policy 1.1".

## Race situation (left column)

### Situation strip

- Season and event, lap L of total laps, and the car number.
- A track status chip: GREEN in green, SC and VSC in yellow, RED in red, unknown in grey.
- The surface.
- A compound chip in Pirelli colours (SOFT red, MEDIUM yellow, HARD white) with the tyre age in laps.

Every chip also carries its text, so no state relies on colour alone.

### Circle of doom

The circle is one lap measured in time. It shows where the card's car would rejoin the race if it boxed on this lap, compared with the car behind.

- Data comes from the race card only, so the screen never shows more than the model saw.
- It uses `gap_ahead` and `gap_behind` with their `driver_number`, `pit_loss_seconds` and `reference_lap_seconds`.
- Cars run clockwise and the card's car sits at the top. A gap of `g` seconds is `g / reference_lap_seconds × 360°`, clockwise for the car ahead and counter-clockwise for the car behind.
- The rejoin point sits one pit loss behind the car, followed by a 2.0-second band for the rejoin margin. The car behind is cleared when it sits past the end of the band, as in rule 6 of the contract.
- An `UNKNOWN` gap is listed as "gap unknown" and not drawn. A `NONE` gap is listed as "no car".
- Without `reference_lap_seconds` the circle is not drawn, and without `pit_loss_seconds` it has no rejoin point. The missing field is named in both cases.
- A line under the circle states its assumption: the pit loss is fixed and the other cars keep their pace.
- The circle is a polar chart in `gr.Plot`, redrawn when the card changes.
- The interface implementation must include tests of the angles and the rejoin point on hand-written cards, including an unknown gap and a missing lap time.

### Tyre window

A strategist first asks whether the tyres are in the pit window. The gauge answers from the card and the policy thresholds.

- A horizontal bar of tyre laps, from 0 to 4 laps past the larger of the tyre age and the compound's `old` threshold.
- Three zones from `TYRE_LIMITS` in `boxbox.rules`, labelled on the bar:
  - "too young", below `young`: too young to stop
  - "window", from `young` to `old`: a stop only with the car ahead within 2.0 s, which a caption under the bar recalls
  - "opportunity", from `old`: an opportunity whatever the gap ahead
- For example, MEDIUM tyres have zones that change at 12 and 18 laps.
- A marker at the card's tyre age.
- For a compound that is not SOFT, MEDIUM or HARD, or an unknown age, the bar is not drawn and the panel names the reason.

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

Rows with an unknown or missing value are highlighted. With the policy check on, a last column says whether the rule uses the field on this card. On a card where the rule gives NO CALL, no input decides a stop, so one line under the table points to the rule's reason instead.

### Raw card

The full card JSON sits in a collapsed accordion, so a reviewer can check any value.

## Call and conversation (right column)

### Call banner

- It shows the CALL of the latest assistant answer in large text, with its WHY below. The colour follows the call: BOX orange, STAY OUT blue, NO CALL grey. The pair never relies on red and green, and the call is always written in words.
- An answer that is not exactly the two `CALL:` and `WHY:` lines of the contract shows "Answer not in CALL/WHY format". The raw text stays in the conversation. The app never repairs an answer, because a format failure is a result.
- Before the first question the banner reads "Ask about this lap".

### Policy check

A toggle under the banner, off by default.

- When on, it shows "Rule on this card:" with the rule's call and WHY from `decide(card)`, and a badge saying whether the latest answer matches that call.
- An out-of-scope request should differ, because the assistant answers NO CALL to it. A note under the badge says so.
- It adds the "used by the rule" column to the decision inputs.
- It stays off by default because the default screen shows only what the model saw.

### Conversation

- `gr.Chatbot` in messages format, which is the contract's list of `{role, content}`.
- A message box with a Send button. Enter also sends.
- Quick questions as buttons: "Box or stay out?", "Why?", "What gap behind does the card show?" and one out-of-scope request, "Will it rain later?". A button fills the message box and sends it.

### Reset and history

- Reset clears the conversation and the banner, and keeps the card. The bin icon of the conversation does the same.
- A status line under the input reads "Engine sees the last 3 exchanges". The number comes from `RunConfig.history_turns`.

### Engine errors

- When the engine raises an error, the app shows it in plain words under the input and as a `gr.Warning`, for example "The engine failed: <message>. The conversation is unchanged."
- The failed turn is not stored in the history.

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
- The app calls `respond(card, history[-2 * turns:], message)`, where `turns` is `RunConfig.history_turns`. The engine receives only the current card's history.
- Until task 2.8 the engine is `stub_respond`, which returns `format_answer(card)` for any message. It cannot follow up or refuse a request, and the badge and the role text say so.

## Code layout

| File | Content |
|---|---|
| `boxbox/app/panels.py` | Pure functions from a card or an answer to a display: `situation`, `inputs_table`, `used_by_rule`, `tyre_zones` and `tyre_window`, `circle_points` and `circle_of_doom`, `parse_answer`, `banner`, `policy_panel`. Figures use matplotlib. |
| `boxbox/app/session.py` | `stub_respond`, `sample_cards`, `send` (one exchange with the bounded history), `load_upload` and `latest_answer`. |
| `boxbox/app/layout.py` | The event handlers (`show_card`, `upload_card`, `ask`, `clear`, `toggle`), `build_app(respond, engine, cards, turns)` for the layout and wiring, and `launch`, which adds the theme. |
| `boxbox/app/__main__.py` | `python -m boxbox.app` opens the app in the browser. |
| `scripts/demo_cards.py` | Writes `data/demo/cards.json` from the validation cards. |

- `used_by_rule` counts a known field as used when making it unknown changes `decide(card)`. It reuses `remove_field` and copies no threshold logic. `remove_field` now lives in `boxbox.rules`, and `boxbox.corpus` keeps exporting it, because the app may import only `rules` and `model`.
- Gradio 6 takes the theme, CSS and script at launch time, so `launch` builds the app and passes them. Gradio is pinned in `requirements.txt`.
- Task 2.8 calls `launch(respond=..., engine="Adapter A")` with the real engine and changes nothing else.

## Notebook launch cell

```python
from boxbox.app import launch

launch(inline=True)
```

The cell is kept here until task 2.8 puts it in `agent.ipynb`, so the shared notebook is not edited by two people at once.

## Tests

`tests/test_app.py` checks:

- the circle angles and rejoin point, including an unknown gap, no car, a missing pit loss and a missing lap time
- the tyre window zones for each dry compound, and the reason when it is not drawn
- `parse_answer` on valid and malformed answers, `used_by_rule`, the highlighted rows and the rule column on a NO CALL card
- that text from an uploaded card is escaped
- send, reset, card change, an engine error that leaves the history unchanged and raises a warning, and the history bound
- two sessions that stay independent
- an upload that is not one JSON object
- the picker with 5 synthetic and 8 real cards

The browser walkthrough runs on the synthetic and real cards before review.
