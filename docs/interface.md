# Interface

The Gradio app in `boxbox/app/` is a pit-wall screen. It shows one race card beside the conversation about it. This file holds the screen layout and one spec per feature.

## Audience and scope

BoxBox is for pit strategists and paddock team members who debrief or train on completed races. The team agreed this audience on 19 October (#10). It replaces the earlier content creators and analysts.

The Card tab keeps the scope of `docs/race-card-contract.md`: one car, one lap of a completed dry race, policy 1.1. The Replay tab adds policy 2.0 from `docs/race-card-contract-v2.md`, which also gives calls under a safety car, a virtual safety car and rain. Live races, forecasts, multi-stop plans, betting and team radio stay out, because the cards and the model only know historical laps. The assistant still answers NO CALL to a forecast question. The Replay tab shows an archived weather forecast as context for the person watching, and no card or call reads it.

The screen shows only what the model saw, with two exceptions: the policy check on the Card tab, which is off until the user turns it on, and the Replay tab, which shows the whole field and the policy 2.0 call on a 2.0 card, which the trained model has never read.

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
- The engine badge. Until task 2.8 it reads "Stub: rule answers, not a trained model" in amber. With the real engine it reads "Adapter A" in the notebook. `python -m boxbox.app -A` or `-B` adds the seed and the epoch, for example "Adapter B · seed 2027 · epoch 3". `-O` reads "OpenJev Flash 9B · zero-shot".
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
- While the engine works, the banner reads "Waiting for the engine". The conversation is the only part that shows Gradio's progress indicator, so one indicator runs, not one per updated output.
- When the engine's trace says `possibly_truncated`, because the token or time limit ended the answer, a warning under WHY reads "The answer may be cut: generation reached its limit before the model ended it." It also appears under a format failure. After an engine error the banner shows the last answer again with its warning, and the next answer, a reset or a card change removes it. Turning the policy check on or off leaves the banner alone.

### Details line

One muted line under the banner describes the last answer. It reads "Strict CALL/WHY format: yes" or "no", with the same parser as the banner, then how much of the conversation was sent: "no earlier exchange", "history sent: 2 earlier exchanges" or "history sent: 3 of 5 earlier exchanges" when older exchanges were left out. When the engine returns its trace, as `python -m boxbox.app -A` or `-B` does with `respond_with_trace`, the line also gives the generation time, the input tokens, the new tokens against the limit and why generation stopped: end of answer, token limit, time limit or model stop. The stub and OpenJev (`-O`) return no trace, so they show the format and history only. A card change or a reset empties the line, and an engine error leaves it on the last answer.

### Policy check

A toggle under the banner, off by default.

- When on, it shows "Rule on this card:" with the rule's call, in its call colour, and WHY from `decide(card)`, and a badge saying whether the latest answer matches that call.
- An out-of-scope request should differ, because the assistant answers NO CALL to it. A note under the badge says so.
- It adds the "used by the rule" column to the decision inputs.
- It stays off by default, so the Card tab shows only what the model saw until the user turns it on.

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

## Replay tab (Experimental milestone)

A second tab plays a race back on the circle as if from the pit wall. It shows more than one card, so it is the second exception to "only what the model saw". The circle, the calls and the running order never read anything timed after the clock. The flags, the pit lane and the forecast follow the rules below.

```text
+----------------------------------------------------------------------------+
| Race                Driver      [ Play ] (x1)(x2)(x4)          Lap 7 / 50 |
| [2024 Las Vegas v]  [RUS (63) v] Jump to lap [===o--------] 7   0:09:34    |
|                                                                 20:13:33   |
+-------------------+--------------------------+-----------------------------+
| TRACK             | WEATHER NOW              | ARCHIVED FORECAST           |
| [SC] Safety car   | (moon) Clear night       | 20:15, in 1 min  24°C 0.0mm |
| Yellow in 14, 15  | Air 26°C Track 32°C ...  | 20:30, in 16 min ...        |
+-------------------+--------------------------+-----------------------------+
| [1] VER  Red Bull Racing  (M) Medium, 6 laps | Pos  Car      Gap   Int Tyre |
| STAY OUT                                     | 1    1 VER   Leader     (M) 6|
| WHY ...                                      | 2   11 PER   +2.6  +2.6 (M) 6|
|            ( circle of doom )                | 3   16 LEC   +4.1  +1.5 (M) 6|
| PER 2.8 s behind. SC pit window 15.1 to ...  | ...                          |
| 1 turn = 95 s, ticks every 10 s              |                              |
+----------------------------------------------+------------------------------+
```

- Control bar: one panel holds the race picker, the driver picker, one Play button, the speed (x1, x2 or x4), "Jump to lap" and the clock. Races come from the open splits of `data/splits-v2.json` (2023 to 2026, without `final` and `test_2026`), and drivers are listed by acronym and number. The tab opens on Las Vegas 2024 with RUS (63), paused at the end of lap 1, and loads that race when the page opens.
- Play button: it says what a click does. Play starts the clock and the button then reads Pause; at the flag the replay pauses and it reads Play again.
- "Jump to lap" runs from lap 1 to the last lap of the race and follows the race lap while the replay plays. It changes only when the lap changes, so a drag under way is not pulled back. Typing or dragging a lap moves the clock to the leader's start of that lap, never before the whole field has crossed the line once; a lap typed digit by digit keeps what was typed. The race can be picked with the mouse or the keyboard, and the same lap can be jumped to again.
- Clock: the race lap in large type, which is the lap after the latest one anyone completed, so it holds during a suspension, then the elapsed race time and the local time at the track.
- Track tile: the flag at the clock with its icon and its word. CHEQUERED once the leader has crossed the line at the end, then RED, SC or VSC while one runs (a red flag lasts until the race resumes), then DOUBLE YELLOW or YELLOW while a sector is under yellow, else GREEN. The tile lists the yellow sectors, which are marshal sectors, not the three timing sectors. A blue flag waved at the chosen driver shows for 10 s.
- Weather tile: the latest OpenF1 reading at the clock (air and track temperature, humidity, wind). The icon is rain when the reading says rain, else the sky of the archived forecast step under way, else unknown.
- Forecast tile: for +5, +15 and +30 minutes, the nearest Open-Meteo step strictly after the clock, with its own time ("20:30, in 16 min"), its temperature and its rain in the 15 minutes before it. Steps are 15 minutes apart, so +5 is the next step. Two horizons that land on the same step show it once. The tile credits "Weather data by Open-Meteo.com" with a link, as its CC BY 4.0 licence asks. Without the data it says "Forecast unavailable" and the rest of the tab keeps working.
- Driver tile: the chosen car's number in its team colour, its acronym and team, and the tyre of the lap it is driving, with the compound icon and the laps done on that set. Right after the car crosses the line in the pit lane, the tile shows the new set.
- Call panel: policy 2.0 on the 2.0 card, with the card's lap in the label. Policy 1.1 on the 1.0 card, which is what the trained model reads, stays on the Card tab. A lap's card appears once the car behind and the cars it counts in its pit window have crossed the line, as on a timing screen; until then the previous card stays up. A safety car that came out during the lap reaches the calls at the next card. In order, the panel shows:
  - IN PIT while the car is in the pit lane, which replaces a BOX card left over from the in-lap;
  - OUT LAP from the lane exit until the card of the next lap shows, since no 2.0 card exists for a lap that starts in the pit lane;
  - RETIRED once the car has stopped running;
  - NO CARD on a lap without a 2.0 card (the final lap, missing timing);
  - else BOX, STAY OUT or NO CALL, each in its own colour.
- BOX: the banner fills with the BOX colour and blinks three times, once a second, then stays filled. A new BOX card blinks again, since odd and even laps swap the animation. With reduced motion set in the system, it does not blink, and the fill and the word BOX remain.
- Circle: the selected car on top, every other car placed by time gap from its line crossings and the sector times of the faster of its last two laps, so an out-lap does not slow the next prediction. Under a SC or VSC the prediction is scaled by the field's latest pace, so a safety car does not pile cars on the line; under green it is not. Each dot wears its team colour from OpenF1 and the car number in black or white, whichever reads better on it, and the acronym beside it. When cars bunch up, only labels far enough apart are drawn and the others keep their dot. A car in the pit lane has a dashed outline and "PIT" after its acronym. On its out-lap the car waits at the line in the estimate for the pit loss at the clock, less what its in-lap already lost, since the pit lane runs beside the line; it then moves on at its race pace instead of running ahead and jumping back at its next crossing. The readout and the screen-reader label name the nearest car ahead and behind, in seconds, and the cars in the pit lane.
- Circle scale: one turn is the field's median lap time, or less while the field is close. It is 2.2 times the larger of two reaches, the farthest car ahead or behind and the rejoin point (pit loss plus 2.0 s), rounded up to 5 s, and never more than the lap. The farthest car then sits at about 164 degrees at most, so no car falls off the ring. Ticks mark every 5 s up to a 60 s turn and every 10 s above, and the readout says "1 turn = 37 s, ticks every 5 s". One car far behind, such as a car stopped on track before it counts as stopped, keeps the ring at a full lap.
- Pit window: a yellow arc from one pit loss to one pit loss plus 2.0 s behind the car, for the track status at the clock, on the same scale as the dots. Its "rejoin" label sits further inside the ring than on the Card tab, clear of the larger dots. While that condition is the card's own, the arc uses the card's pit loss, the one its call uses. It moves the moment a safety car comes out, before the next card, and it disappears under a red flag. Without a card for the lap, the surface comes from the driver's latest card. The readout names the condition and the seconds.
- Running order: a table beside the circle, on the same estimate as the circle, so the two always agree on who is ahead. Cars are ordered by laps covered, updated every tick and set again at each line crossing. The gap to the leader and the interval to the car ahead are the circle's time gaps, or "+1 LAP" once a car has covered a lap more. The circle is a loop of one lap around the chosen car, so a car more than half a lap behind shows ahead on it while the table counts the lap. Each row has the team colour as a stripe, the number, the acronym, a PIT badge in the pit lane and the tyre icon with its age. Stopped cars come last and read OUT; under a red flag no car counts as stopped. The chosen car's row is marked and announced as current. A "?" marks a gap with a hole in the timing.
- Sound: when the policy 2.0 call is BOX, the calls panel (`data-sound="replay"`) carries `data-box` with the race, driver and lap of the card. On the Card tab, the banner (`data-sound="card"`) carries `data-box` with the number of exchanges when the latest answer's CALL is BOX, so an engine error that shows the same answer again does not replay it. A page script from `sound_head`, added by `launch`, plays `boxbox.wav` from the working directory once for each new key of each panel: the same card shown again, a tab change or a pause does not play it twice, and a STAY OUT or NO CALL in between lets the next BOX card play it again. Gradio edits a panel in place, so the script also watches the `data-box` attribute: a call that turns to BOX may change nothing else on the page. The sound is inlined in the page, so no file route is opened. Without the file, nothing plays. Browsers allow it after the first click on the page, such as picking a race.
- Icons: flags, tyres and the sky are drawn in SVG in `boxbox/app/icons.py`, so no image file or licence comes with them, and the tyres carry no maker's logo. Each icon is hidden from screen readers and sits next to its word, or next to text kept for screen readers in the forecast and the running order.
- Speed: each panel is its own HTML output. Gradio edits each one in place and skips one that has not changed, so per tick the circle changes, the running order changes at crossings and the other panels rarely. The render takes about 3 ms per tick on the server.
- The model's chat is not on this tab until adapters are trained on 2.0 cards.

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
| window | `#b08600` (3.4:1) | `#facc15` (9.6:1) | replay pit window |
| pit | `#6d28d9` (7.1:1) | `#a78bfa` (5.4:1) | replay IN PIT and OUT LAP, PIT badges |
| on-call | `#ffffff` (5.0:1 on BOX) | `#0f172a` (7.3:1 on BOX) | text on the filled BOX banner |

Each colour keeps one meaning:

- The three call colours appear only for a call: the banner and the policy check.
- Flag and Pirelli colours appear in the chip dots and in the replay's flag and tyre icons, each beside its word. INTERMEDIATE is `#43b02a` and WET `#0067ad`. A yellow flag or a white band has a ring outline, since yellow on white is 1.5:1.
- Actions such as Send use neutral slate, white on slate at 4.8:1 in light and 7.6:1 in dark.
- Charts and the unknown-row tint are neutral.
- On the Replay tab, car dots take the team colour that OpenF1 gives, with no dark variant. Each dot keeps the ink outline and its acronym, so a colour close to a call colour or to the background is never the only cue.

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
| `boxbox/app/panels.py` | Pure functions from a card or an answer to HTML: `situation`, `inputs_table`, `used_by_rule`, `tyre_zones`, `tyre_readout` and `tyre_window`, `circle_points`, `circle_readout` and `circle_of_doom`, `parse_answer`, `banner`, `answer_details`, `policy_panel`. Charts are hand-written SVG. |
| `boxbox/app/session.py` | `stub_respond`, `sample_cards`, `exchange` (one exchange with the bounded history, and the engine's trace when it returns one), `send` (the same without the trace), `load_upload` and `latest_answer`. |
| `boxbox/app/layout.py` | The colour tokens, the event handlers (`show_card`, `pick_card`, `upload_card`, `ask`, `clear`, `toggle`, `busy`, `ready`), `history_line` for the status line, `build_app(respond, engine, cards, turns)` for the layout and wiring, and `launch`, which adds the theme. |
| `boxbox/app/__main__.py` | `python -m boxbox.app` opens the app in the browser with the rule stub; `-A` or `-B` loads SmolLM3-3B with that selected adapter, as in the notebook; `-O` starts the pinned OpenJev server of task 3.4 and stops it on exit. |
| `boxbox/app/replay.py` | The Replay tab: `race_choices` (races of the open splits of `data/splits-v2.json`), `DEFAULT` and `open_default` (the race and driver the tab opens on), `clock` and `clock_text`, `status_strip` (flag, weather and forecast tiles), `turn` (the ring scale) and `circle`, `call_state` and `calls` (the panel state and the policy 2.0 call, with the `data-box` marker), `driver_tile`, `standings_table`, `sound_head`, `view`, the handlers `pick_race`, `pick_driver`, `jump`, `toggle` (the Play button), `pause`, `set_speed` and `tick`, `_follow` (the lap slider on the race lap), and `replay_tab`, which builds the tab and returns the load that opens it. |
| `boxbox/app/icons.py` | SVG icons: `flag`, `tyre`, `weather`, and `sky`, which turns a WMO weather code into an icon. |
| `boxbox/data/replay.py` | `Timeline` and `load_timeline`, which rebuilds the race's 1.0 and 2.0 cards in memory from OpenF1 data in `data/cache/openf1`, then `progress`, `gap`, `pace`, `race_lap`, `frame`, `cards_at`, `status_now`, `pit_window`, `flags_at`, `pit_state`, `tyre_at` and `standings`. The circle, the cards and the running order read only data timed at or before the clock. |
| `boxbox/data/openmeteo.py` | `circuit_location` from the Jolpica schedule, `load_forecast` (the archived 15-minute forecast through `data/cache/open-meteo`, or None) and `forecast_at`, which picks the steps after the clock. |
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

Like `RUN_TRAINING` for the training cells, `RUN_DEMO` lets a clean run of the notebook skip a server that nobody can use. In a hosted notebook such as Colab, Gradio opens a public link unless `launch` gets `share=False`. Task 2.8 chose `share=False`, so the demo stays private. The cell is now section 7 of `agent.ipynb`, where it passes the real engine with adapter A to `launch`.

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

`tests/test_replay.py` checks the Replay tab:

- that nothing timed after the clock is read, and that the card shown was built before the clock
- car progress through faster and slower laps, angles by time gap, and a slower lap that slows the cars still on it
- the clock from wall time, its stop at the flag, a start once every car has crossed, and a jump to the leader starting the lap
- both cards of the lap, a card that waits for the car behind to cross, and no card for a stopped car
- the pit window following the track status at the clock
- team colours, numbers and acronyms, and bunched cars that keep their dots but not all their labels
- the ring zoom (`turn`) and the black or white number on a team colour
- sector yellows that clear or go stale, the SC over them, the chequered flag and a blue flag for one driver
- the pit lane then the out-lap, the new tyre on the out-lap, and pit windows with and without pit data
- the running order with a lapped car and a stopped car, which also reads nothing after the clock, a slow lap without pit data, and a car on its out-lap that waits at the line on the circle and in the table
- the lap slider that follows the race lap, a jump to the last lap or from a typed 1, and the default driver when it raced
- the call panel's IN PIT, OUT LAP, RETIRED and NO CARD states, and the odd and even BOX blink
- the icon picked for each weather code

`tests/test_openmeteo.py` checks that the forecast is read through the cache, returns None without cache or network, and that a forecast step always comes after the clock.

The browser walkthrough runs on the synthetic and real cards, in light and dark, before review.
