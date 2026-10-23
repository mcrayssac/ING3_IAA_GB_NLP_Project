# Race-card contract 2.0 and decision policy 2.0 for the Experimental milestone (4 bis)

Card 2.0 keeps every field of card 1.0 (`docs/race-card-contract.md`) and adds track conditions, tyre wear and the neighbours' tyres. Policy 2.0 gives calls under a safety car, a virtual safety car and rain, and it adds the undercut. `decide(card)` reads `schema_version`: a 1.0 card still gets policy 1.1, and a 2.0 card gets policy 2.0 (`boxbox/rules/policy2.py`). The frozen 1.0 contract stays unchanged. The policy is still a stated rule set. Agreeing with it shows consistency, not the best real strategy, and `scripts/reality_check.py` measures how often it matches what teams did.

## New and changed fields

| Field | Meaning |
|---|---|
| `schema_version` | `"2.0"`. |
| `race.circuit_key` | OpenF1 circuit id. Priors use it because event names change (the Spanish Grand Prix moved from Barcelona to Madrid in 2026). |
| `as_of` | ISO time at which the driver crosses the line at the end of lap L - 1. The card is read at that moment. |
| `surface` | `DRY` or `WET`. WET with rain in the last 10 minutes or when the field's green laps run at 110% or more of the best dry pace so far (this rule never fires in the merged code, see D6 in `4bis-decisions.md`). When lap times give no reference, WET when half the field is on wet tyres. |
| `track_status` | `GREEN`, `SC` or `VSC` when the driver crosses the line (red-flag cards are skipped). |
| `compound` | Also `INTERMEDIATE` and `WET`. |
| `tyre_degradation_s_per_lap`, `tyre_degradation_source` | Time lost per lap of tyre age for this compound. `race` once the race's own fit has a standard error under 0.03 and a positive slope, otherwise `circuit` or `global` from earlier train races. Null on wet tyres. |
| `tyre_loss_s_per_lap` | Degradation times tyre age: what the set loses per lap against a new one. |
| `gap_ahead`, `gap_behind` | As in 1.0, and for a known gap also the neighbour's `compound`, `tyre_age_laps`, `in_pit_lane` and `tyre_loss_s_per_lap`. The gap behind is known when the car behind crosses, a few seconds after `as_of`, as on a timing screen. |
| `cars_in_pit_window` | Cars behind on the same lap within the pit loss plus 2.0 s. Null without a pit loss or a complete running order. |
| `mandatory_stop_pending` | True in a dry race until the driver has used two dry compounds. Wet tyres lift the rule. |
| `pit_loss_seconds`, `pit_loss_as_of_completed_lap` | Pit loss for the condition the car would stop under. The cutoff is 0 when the value comes from earlier races. |
| `pit_loss_condition`, `pit_loss_source` | `GREEN`, `SC`, `VSC` or `WET`, and `race`, `race scaled`, `circuit`, `reference` or `global`. |
| `penalty_pending_seconds` | Time penalties awarded to the driver and not yet served at a stop. |
| `weather` | Last reading before `as_of`: air and track temperature, humidity, wind speed, rainfall. Display only. |

## Ordered rules of policy 2.0

1. The card must be schema 2.0 with a valid identity and cutoff, a completed race, a known surface, GREEN, SC or VSC running, a known compound and a tyre age. Otherwise NO CALL.
2. Tyres that do not match the surface open a stop: slicks on a wet track, or wet tyres on a dry track. Wet tyres on a wet track stay out.
3. Under a SC or VSC, on a dry track, with the mandatory stop still to make, the call is BOX: the stop has to be made and costs less now.
4. Tyre wear decides the rest. Below the compound's lower limit the call is STAY OUT. At or above the upper limit the call is BOX whatever the traffic, because teams stop worn tyres and accept the places. In between, a stop opens under a SC or VSC, or for an undercut: the car ahead is known and no further ahead than what its own tyres lose in one lap (2.0 s when that loss is unknown). An unknown gap ahead gives NO CALL and no car ahead gives STAY OUT. Without a wear value the 1.1 age limits apply the same way.
5. A stop opened inside the window, or by tyres that do not match the surface, needs a clean rejoin. Under a SC the call is BOX only when no car sits in the pit window.
6. Otherwise no car behind gives BOX, an unknown gap behind gives NO CALL, and a known gap gives BOX when it covers the pit loss, any pending penalty and the 2.0-second margin.

| Compound | Stop opens from | Always opens from |
|---|---:|---:|
| SOFT | 0.34 s per lap | 0.62 s per lap |
| MEDIUM | 0.63 s per lap | 1.08 s per lap |
| HARD | 0.92 s per lap | 1.38 s per lap |

The limits are the 25th percentile and the median of `tyre_loss_s_per_lap` on the cards of real green-flag stops in the train races, without Qatar 2023 and its 18-lap limit (`python -m scripts.reality_check --splits train --thresholds`). Since the 2026 VSC fix, the rebuilt train cards give 0.37 and 0.64 for SOFT, 0.62 and 1.07 for MEDIUM and 0.94 and 1.42 for HARD with this command, and the policy keeps the limits above. Teams stop a soft set at a lower time loss than a hard one, so one limit for every compound would delay soft stops and bring hard ones forward.

## Known limits

- A card is taken when the driver crosses the line. A safety car that comes out during the lap changes the best call before the next card: 32 of the 54 stops made under a safety car in the evaluation races had a GREEN card. A live view needs a card refreshed when race control announces the neutralisation.
- Under a safety car the pit loss measured against the field is noisy (10 to 41 s at Silverstone 2023), because cars far back close up while the leaders slow down. The train median is 0.70 times the green loss, above the half that strategists usually quote. A stop needs at least three cars that did not stop to compare with.
- The undercut uses the rival's tyre loss over one lap. It ignores the warm-up of the new set and traffic after the stop.
- Wind and temperatures are shown, not used.
