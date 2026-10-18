# Race-card contract and decision policy (task 1.4)

This contract defines a **pedagogical, deterministic policy** for explaining a pit-stop call in a completed Formula 1 race on a dry track. Agreement with the policy measures consistency with stated rules; it does not establish the best real-world strategy. The numbers below are policy thresholds, not claims about real tyre life or pit-lane performance. Every measured value in a real card must come from a traceable, pre-decision observation. The five cards in this document and in `reference/fixtures.json` are **synthetic examples**, not historical timing data.

The intended user is an English-speaking F1 content creator or analyst asking about one driver at the start of one lap. Live races, wet-track strategy, forecasts, simulations, multi-stop optimisation, betting and invented radio messages are outside scope. FastF1 is the selected source for later reconstruction; OpenF1 is only an optional cross-check. Real reconstruction, source validation and race splits belong to task 2.1. Raw third-party timing data must not be presented as Apache-licensed project data.

## Card format

Cards are JSON objects with the following fields. JSON `null` means **unknown or unavailable**; it never means zero. Numeric fields accept JSON numbers, excluding booleans, NaN and infinity. Pass a Python `Decimal` for a direct API value when exact decimal precision matters; the JSON command reads decimal numbers as `Decimal` without first converting them to binary floats. Seconds are elapsed seconds, never milliseconds. Gaps are non-negative time gaps at the start of the evaluated lap to the immediately adjacent cars in running order on the same lap; no signed gaps are used. A lapped-car or ordering ambiguity makes the affected gap `UNKNOWN`. Unknown, no neighbouring car and known zero gap are distinct states.

| Field | Format and meaning | Decision use |
|---|---|---|
| `schema_version` | Literal string `"1.0"` | Required for interpretation. |
| `race` | Object with `season` (integer ≥ 1950), `round` (integer ≥ 1), `event` (nonempty string), and `completed` (`true`, `false` or `null`). | Identifies one completed historical race; incomplete identity or non-`true` completion gives `NO CALL`. |
| `lap`, `total_laps` | Integers with `1 ≤ lap ≤ total_laps`. | Identifies the evaluated lap. |
| `driver_number` | String of one or two decimal digits denoting a number from 1 to 99, with no leading zero (`"1"` is valid; `"01"` is invalid). | Identifies the car. |
| `as_of_completed_lap` | Integer exactly `lap - 1` (zero for lap 1). | Declares the snapshot cutoff: all race observations must be available by this completed lap. |
| `surface` | `"DRY"`, `"WET"`, `"UNKNOWN"` or `null`. | Only `DRY` is supported. |
| `track_status` | `"GREEN"`, `"SC"`, `"VSC"`, `"RED"`, `"UNKNOWN"` or `null`, observed at the cutoff. | Only `GREEN` is supported; neutralisations change the pit-loss context. |
| `compound` | `"SOFT"`, `"MEDIUM"`, `"HARD"`, `"INTERMEDIATE"`, `"WET"`, `"UNKNOWN"` or `null`. | Only the three dry compounds are supported. The policy does not assign different numerical thresholds to them. |
| `tyre_age_laps` | Integer ≥ 0, or `null`. Laps driven on the current set at the cutoff, counting laps from earlier sessions for a used set, as FastF1 `TyreLife` does at the end of lap `lap - 1`. It can exceed `as_of_completed_lap`. Reconstruction converts FastF1's float `TyreLife`: a finite whole value such as 18.0 becomes 18, and a missing (NaN) or non-integral value becomes `null`. A float in the card itself is invalid and gives `NO CALL`. | Required to test the opportunity rule. |
| `gap_ahead`, `gap_behind` | Each is `{"state":"KNOWN","seconds":number}` with non-negative seconds, `{"state":"NONE","seconds":null}` for no neighbouring car, or `{"state":"UNKNOWN","seconds":null}`. The `seconds` key is required in every supplied gap object, including `NONE`. A gap object may also carry the neighbour's `driver_number`, in the card's format, for display. | Ahead is needed only for ages 12–17; behind is needed only after an opportunity exists. A missing object is treated as `UNKNOWN`. `NONE` is a verified absence, never a missing measurement. The neighbour's `driver_number` is never used. |
| `pit_loss_seconds` | Non-negative JSON number or `null`; estimated green-flag pit transit loss in seconds, excluding tyre-performance predictions. | Needed only if there is a known car behind after an opportunity exists. |
| `pit_loss_as_of_completed_lap` | Integer from 0 to `lap - 1`, or `null`. | Required with a used pit-loss estimate; records the latest lap allowed in that estimate. It may be older than the card snapshot. |
| `reference_lap_seconds` | Positive JSON number or `null`; a typical green-flag lap time before the cutoff, in seconds. | Never used. The interface needs it to draw the circle of doom. |

Display-only fields never change the call, so a missing one never forces `NO CALL`.

The reconstruction step must keep evidence for the `as_of_completed_lap` claim, each gap and the pit-loss estimate. A pit-loss estimate may use earlier stops or earlier races, but never the evaluated or later lap. The reference checks the declared cutoff and `pit_loss_as_of_completed_lap`; it cannot independently prove that upstream data obeyed them. Do not fill absent values from later timing, an average invented for convenience, or a model guess. Reject malformed required fields with `NO CALL`; a supplied `NONE` gap without `seconds: null` is always malformed and gives `NO CALL`, even when that gap would otherwise be irrelevant. An irrelevant unknown value does not force abstention: for example, an 11-lap tyre needs neither gap nor pit-loss values for the `STAY OUT` rule, and an 18-lap tyre does not need the gap ahead.

## Ordered decision rules

Rules are applied in this order. The inequalities and tie handling are part of the contract.

1. If card identity/cutoff is invalid or missing, the race is not confirmed completed, surface is not `DRY`, status is not `GREEN`, compound is not a dry compound, or tyre age is missing/invalid, return `NO CALL` with the first applicable reason in that order.
2. If `tyre_age_laps < 12`, return `STAY OUT`. No gap or pit-loss field is needed.
3. If `12 ≤ tyre_age_laps < 18`, an opportunity exists only with a **known** `gap_ahead.seconds ≤ 2.0`. A verified `NONE` ahead or a known gap above 2.0 gives `STAY OUT`. An unknown or malformed gap ahead gives `NO CALL`.
4. If `tyre_age_laps ≥ 18`, an opportunity exists regardless of the gap ahead.
5. With an opportunity, a verified `NONE` behind gives `BOX`; no pit-loss value is needed because this policy cannot lose position to a following car on the card. An unknown or malformed gap behind gives `NO CALL`.
6. With an opportunity and a known car behind, require a valid `pit_loss_seconds` and a valid `pit_loss_as_of_completed_lap`. If either is missing, invalid or future-derived, return `NO CALL`. Return `BOX` when `gap_behind.seconds ≥ pit_loss_seconds + 2.0`; otherwise return `STAY OUT`. Equality goes to `BOX`.

The 12- and 18-lap ages, 2.0-second gap ahead and 2.0-second rejoin margin are fixed policy choices. They are deliberately simple and do not model degradation, undercuts, traffic beyond the immediate neighbours or safety-car pit-loss changes. `NO CALL` means the policy cannot justify either action from the card, including unsupported scope; it is not a claim that a real team would abstain.

The executable reference is [`boxbox/rules`](../boxbox/rules). Import `decide(card)` or `format_answer(card)` from `boxbox.rules`; `decide` is the recommended public decision API and returns `(call, why)`, while `format_answer` renders exactly two lines. Run `python3 -m boxbox.rules path/to/card.json` to inspect a card. The JSON command parses decimals without binary-float rounding; direct callers can pass `Decimal` values for exact thresholds.

## Shared conversation interface

The component hand-off is `respond(card: JSON object, history: list of {role, content}, message: string) -> string`. `role` is `"user"` or `"assistant"`; entries are chronological and belong to the same card. A new card or reset starts an empty history. The current user message is separate from `history`. The caller must keep the history bounded; the exact model window belongs to task 2.5a. A follow-up uses the current card again, never numbers from a previous card or from conversation prose. Natural-language interpretation belongs to the conversation engine; `decide` is the deterministic label authority for in-scope pit-call questions.

Every assistant answer, including an out-of-scope response, has **exactly** this two-line shape, with no preamble or extra text:

```text
CALL: BOX | STAY OUT | NO CALL
WHY: <one English sentence grounded in the current card or its stated limits>
```

The first line contains exactly one of the three labels, not the literal alternatives. The second line is one sentence. For an out-of-scope request, use `NO CALL` and explain the scope limit without asserting race facts. This is a response convention, not a fourth race strategy. A request for a real optimum or unsupported weather/forecast is also out of scope.

## Five expected conversations

All race-card numbers below are synthetic. Each conversation uses a full card in [`reference/fixtures.json`](../reference/fixtures.json); the listed fields highlight what matters to that example. The exact two-line responses are the expected outputs, including wording. The fifth response illustrates scope handling outside the card-only decision function.

1. **Old tyres and a safe rejoin - BOX.** Card `box_old`: tyre age 18 laps, 24.0 s behind, 21.0 s pit loss, pit-loss cutoff lap 29.

   User: Should car 44 box at the start of lap 30?

   Assistant:

   ```text
   CALL: BOX
   WHY: With tyres aged 18 laps, the 24.0-second gap behind covers the 21.0-second pit loss plus the 2.0-second margin, so the rule calls for boxing.
   ```

2. **Young tyres, with irrelevant values unavailable - STAY OUT.** Card `stay_young`: tyre age 11 laps; both gaps and pit loss are unknown.

   User: What is the call for car 44 at lap 30?

   Assistant:

   ```text
   CALL: STAY OUT
   WHY: The card shows tyres aged 11 laps, below the 12-lap trigger, so the rule is to stay out.
   ```

3. **Missing required gap - NO CALL.** Card `missing_behind`: tyre age 18 laps; gap behind is unknown.

   User: Can car 44 box now?

   Assistant:

   ```text
   CALL: NO CALL
   WHY: The card is missing the gap to the car behind, so the rule cannot assess a pit stop.
   ```

4. **Follow-up on one card.** Card `medium_safe`: tyre age 15 laps, 1.5 s ahead, 24.0 s behind and 21.0 s pit loss.

   User: What is the call at lap 30?

   Assistant:

   ```text
   CALL: BOX
   WHY: With tyres aged 15 laps and a 1.5-second gap ahead, the 24.0-second gap behind covers the 21.0-second pit loss plus the 2.0-second margin, so the rule calls for boxing.
   ```

   User: Does the gap ahead change that call?

   Assistant:

   ```text
   CALL: BOX
   WHY: The card's 1.5-second gap ahead meets the 2.0-second opportunity threshold, and its 24.0-second gap behind covers the 21.0-second pit loss plus the 2.0-second margin.
   ```

5. **Out-of-scope request.** Card `box_old` remains selected.

   User: Predict the weather and the optimal strategy for the live race tomorrow.

   Assistant:

   ```text
   CALL: NO CALL
   WHY: This historical dry-track card cannot support a live-race weather forecast or an optimal multi-stop strategy.
   ```

The accompanying reference checks cover both sides of every threshold, equality, an unsupported track state, unknown versus no neighbouring car, a missing pit-loss estimate, a future-derived estimate, malformed values, a missing field that is irrelevant to the current branch of the rule, a used tyre set at lap 1 and display-only fields that leave the call unchanged.
