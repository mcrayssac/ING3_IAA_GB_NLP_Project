# Team workflow

## Daily availability and capacity

This register is closed at the delivery date, 23 October 2026. The 50–70 collective hours in the recovery plan are an assumption from the 17 October snapshot. Collect the remaining availability as of each confirmation through 22 October; exclude time already elapsed or spent. For 18 October, supply only remaining slots, not a full-day estimate. Do not reconstruct 17 October as remaining capacity. Past work, if reported, is separate from this remaining-hours table.

Each member confirms their own slots and usable human hours, including implementation, coordination, review, corrections and submission. An explicitly confirmed unavailable day is `0 h`; a missing reply is not zero availability. Do not count overlapping slots twice for one person, or count unattended compute as human capacity. Overlap across different people is valid collective time; review still requires someone other than the implementer to be available.

| Date (2026, Europe/Paris) | Member confirming | Remaining slots / usable hours | Confirmation | Recorded at (Europe/Paris) | Source |
|---|---|---|---|---|---|
| 18 October | Maxime CRAYSSAC | 18:00-22:30 / 4.5 h | Confirmed | 18 October 2026, 15:48 +0200 | Maxime CRAYSSAC, PR #39 |
| 18 October | Paul PITIOT | 18:00-22:30 / 4.5 h | Confirmed | 18 October 2026, 15:24 +0200 | Paul PITIOT, project chat |
| 18 October | Matthieu Brault | 18:00-22:30 / 4.5 h | Confirmed | 18 October 2026, 17:36 +0200 | Matthieu Brault, PR #39 |
| 19 October | Maxime CRAYSSAC | 18:00-22:30 / 4.5 h | Confirmed | 18 October 2026, 15:48 +0200 | Maxime CRAYSSAC, PR #39 |
| 19 October | Paul PITIOT | 18:00-22:30 / 4.5 h | Confirmed | 18 October 2026, 15:24 +0200 | Paul PITIOT, project chat |
| 19 October | Matthieu Brault | 18:00-22:30 / 4.5 h | Confirmed | 18 October 2026, 17:36 +0200 | Matthieu Brault, PR #39 |
| 20 October | Maxime CRAYSSAC | 18:00-22:30 / 4.5 h | Confirmed | 18 October 2026, 15:48 +0200 | Maxime CRAYSSAC, PR #39 |
| 20 October | Paul PITIOT | 18:00-22:30 / 4.5 h | Confirmed | 18 October 2026, 15:24 +0200 | Paul PITIOT, project chat |
| 20 October | Matthieu Brault | 18:00-22:30 / 4.5 h | Confirmed | 18 October 2026, 17:36 +0200 | Matthieu Brault, PR #39 |
| 21 October | Maxime CRAYSSAC | 18:00-22:30 / 4.5 h | Confirmed | 18 October 2026, 15:48 +0200 | Maxime CRAYSSAC, PR #39 |
| 21 October | Paul PITIOT | 18:00-22:30 / 4.5 h | Confirmed | 18 October 2026, 15:24 +0200 | Paul PITIOT, project chat |
| 21 October | Matthieu Brault | 18:00-22:30 / 4.5 h | Confirmed | 18 October 2026, 17:36 +0200 | Matthieu Brault, PR #39 |
| 22 October | Maxime CRAYSSAC | 18:00-22:30 / 4.5 h | Confirmed | 18 October 2026, 15:48 +0200 | Maxime CRAYSSAC, PR #39 |
| 22 October | Paul PITIOT | 18:00-22:30 / 4.5 h | Confirmed | 18 October 2026, 15:24 +0200 | Paul PITIOT, project chat |
| 22 October | Matthieu Brault | 18:00-22:30 / 4.5 h | Confirmed | 18 October 2026, 17:36 +0200 | Matthieu Brault, PR #39 |

Reassess remaining hours at each daily check-in and after a material availability change. Date the assessment and retain the superseded confirmation reference. The 22 October slots must end by the submission cutoff and include an available submitter and correction/review cover. The 8-hour reserve must be backed by actual available slots, especially after the planned noon package check; it is not an extra row of invented hours.

For a common assessment cutoff, let `C` be the sum of the still-usable hours confirmed by all members. Sum each hour once. Let `R = 8 h` be the protected collective reserve and `P = C - R` the capacity for planned work including coordination and review. `P` is usable only when `C >= 8` and those reserve hours can actually be protected. Under the original assumption, `50 - 8 = 42 h` and `70 - 8 = 62 h`. Never use `C + 8`, 58–78 h, or 8 h per person.

| Assessment item | Current evidence / result | Confirmation needed from | Confirmed at / accessible reference |
|---|---|---|---|
| Assessment cutoff | not recorded before delivery; the three members' replies are dated 18 October 2026, 15:24 to 17:36 +0200 | Paul, after collecting the three replies | pending confirmation / pending confirmation |
| Remaining hours per member and complete total `C` | Paul: 22.5 h, Maxime: 22.5 h and Matthieu: 22.5 h confirmed across 18-22 October (15 of 15 daily entries). Complete total `C` = 67.5 h | Each member; Paul consolidates | pending confirmation / pending confirmation |
| Reserve `R` and protected slots | 8 collective hours required inside `C`; protected slots not recorded before delivery | All three members | pending confirmation / pending confirmation |
| Planned-work capacity `P` | 59.5 h (`C - R` = 67.5 - 8), usable only if the reserve slots were protected, which was not recorded before delivery | Paul, checked by Maxime | pending confirmation / pending confirmation |
| Gap against 50 h / 70 h | Complete confirmed amount: 67.5 h. Gap to 50 h: `max(0, 50 - C)` = 0 h. Gap to 70 h: `max(0, 70 - C)` = 2.5 h | Paul, checked by Maxime | pending confirmation / pending confirmation |
| Capacity/scope decision | not recorded before delivery; `C` = 67.5 h falls inside the 50–70 h assumption, 2.5 h below its upper end | All three members; Paul records the decision | pending confirmation / pending confirmation |

After replies, report `max(0, 50 - C)` as the gap to the lower assumption and `max(0, 70 - C)` as the gap to its upper end. If some replies are missing, label the sum a partial confirmed amount, not total capacity. If `C < 50`, state the actual gap and obtain a linked team decision to add genuinely available time or revise sequencing/scope through the existing roadmap gates; do not allocate fictional hours or silently reduce acceptance. If `C < 8`, the reserve itself is not covered. If `50 <= C <= 70`, state where the capacity falls within the assumption and whether review/reserve slots fit; if `C > 70`, record the actual value without automatically expanding scope. Aggregate hours alone do not establish that dependency handovers fit the calendar.

## Team acknowledgments

The acknowledgment must identify the reviewed document revision or exact shared deliverable, including any uncommitted files. It covers D/M/E/T as non-exclusive categories; pickup of ready work by any available member under one temporary lead; another member reviewing every result; changes, acceptance, handover and release; one active hands-on implementation per person and the unattended-computation exception; one issue status including blocked/deferred; independent Git directories; and temporary coordination of `agent.ipynb` and `requirements.txt` with no permanent file owner. The procedures are maintained in the execution guide, not duplicated here.

| Member | Workflow / parallel-work acknowledgment | Availability and capacity/reserve decision acknowledgment | Confirmed at (Europe/Paris) | Accessible reference and reviewed revision |
|---|---|---|---|---|
| Maxime CRAYSSAC | Confirmed | Confirmed | 18 October 2026, 15:48 +0200 | PR #39 at 04b2353 |
| Paul PITIOT | pending confirmation | pending confirmation | pending confirmation | pending confirmation |
| Matthieu Brault | Confirmed | Confirmed | 18 October 2026, 17:36 +0200 | PR #39 at f559eed |

Record separate dates/references if the two acknowledgments are supplied at different times. An acknowledgment can link the capacity decision above. Issue assignment alone confirms neither availability nor agreement. Paul's acknowledgments were not recorded before delivery, so his entries stay pending.
