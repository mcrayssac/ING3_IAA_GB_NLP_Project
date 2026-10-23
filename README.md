# BoxBox

BoxBox is a conversational assistant for pit strategists and paddock team members who debrief or train on completed races. It explains a pit-stop situation from a past race. For each situation it says whether the car should box now or stay out, and it gives no call when the available information does not support a decision. It is a student project at CY Tech (NLP and Transformers course, 2026-2027), and this repository presents the project and tracks its progress. The submitted study covers dry tracks. The Experimental milestone (4 bis) adds calls under a safety car, a virtual safety car and rain, and a race replay.

## The need

Explaining a pit-stop decision means gathering tyre age, gaps to the cars around, track status and the time lost in the pit lane, often under time pressure. Some of these values are sometimes missing. A general-purpose chatbot can then fill the gap with an invented figure. BoxBox is meant to give a short explanation grounded in the race card, and to say plainly when the card is not enough.

## What BoxBox will do

The user picks a historical situation (one race, one lap, one car, on a dry track), reads its race card and asks a question in English. Follow-up questions stay in the same conversation. Every answer has the same two lines:

```text
CALL: BOX | STAY OUT | NO CALL
WHY: <one sentence in English, based on the race card>
```

For example, on a card where the gap to the car behind is missing, the planned answer is:

```text
CALL: NO CALL
WHY: The card is missing the gap to the car behind, so I cannot assess the pit stop.
```

BoxBox follows explicit decision rules applied to the card. Agreeing with those rules shows consistency with a stated policy. It does not prove that a call is the best real-world strategy, since teams also decide on information the card does not hold.

Out of scope: live races, full race simulation, multi-stop optimisation, weather forecasts in the assistant's answers, betting, invented team radio quotes and permanent hosting. The Replay tab shows an archived forecast for the person watching, and no card or call reads it.

## What the project tests

The research question is whether a small language model gives fewer unjustified answers on incomplete cards when some of its training examples teach it to abstain, without refusing too often when a call is possible. The target study compares the unadapted baseline and two adapted versions of the same model on the same cases. Version A learns from complete cards only. Version B has 15% of its examples replaced by incomplete cards whose expected answer is NO CALL. Negative or uncertain results will be reported as they are. B trained in time, and baseline, A and B are the three frozen versions of the final comparison.

## Current status

**Snapshot: 22 October 2026.** The prototype, adapters A and B, the interim A/B analysis, the optional OpenJev study and the freeze of baseline, A and B (tasks 1.1 to 3.5) are done. Evaluation tasks 4.1 to 4.5 are done and merged: the final cases ([#59](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/pull/59)), the single scoring of the frozen versions ([#62](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/pull/62)), the human review ([#63](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/pull/63)) the paired gains with race-level uncertainty ([#64](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/pull/64)) and the findings with five discussed cases ([#68](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/pull/68)). As the [roadmap](docs/roadmap.md) records, the report and video outline (5.1) is ready and delivery tasks 5.2 to 5.6 are planned. The recovery plan assumes 50 to 70 collective hours, including an 8-hour reserve, until 22 October at 23:59 Paris time; confirmed remaining capacity is recorded separately in the [team confirmation register](docs/team-workflow.md#daily-availability-and-capacity).

The Experimental milestone (4 bis) is done and merged into `main` ([#69](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/pull/69)). It was built on branch `main-experimental`, cut from `main` after task 4.4, and its tasks had no pull requests of their own. The milestone widens the race data and gives calls in more situations, for research and for a product beyond the student study. It adds the 2026 season, track status read from race-control timestamps, race cards 2.0, policy 2.0 under safety cars, virtual safety cars and rain, and a race replay in the app, with a button that asks OpenJev about the card on screen ([#71](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/pull/71)). The frozen versions, their sealed files and the results of the study do not change, and the freeze check still passes. The adapters A and B, and every result of the study, were trained and scored on 1.0 cards with policy 1.1. No trained model has read cards 2.0 or policy 2.0, so the Replay tab shows the rule engine's calls and, on a click, a zero-shot OpenJev reading of the card (D14). Training on 2.0 cards is future work. The 1.0 cards of the study rebuild exactly only from commit `631b783`, the last commit before this merge. The decisions and their checks are in [docs/4bis-decisions.md](docs/4bis-decisions.md).

## Project structure

The repository holds the code, configs, tests and documentation:

```text
agent.ipynb             notebook of the submitted study
docs/roadmap.md         active recovery schedule, task definitions and issue links
docs/roadmap-annexe.md  execution guide and assignment coverage
docs/code-approach.md   code layout, configs, run folders and team coding rules
docs/interface.md       Gradio interface specs
docs/data-protocol.md   race data source, card reconstruction and splits
docs/corpus.md          training and evaluation dialogues and their review
docs/evaluation-protocol.md evaluation rubric and comparison protocol (proposal)
docs/evaluation-tooling.md evaluator API, offline fixture checks and review exports
docs/4bis-decisions.md  Experimental milestone decisions and their checks
docs/race-card-contract-v2.md race card 2.0 and policy 2.0 (Experimental)
boxbox/data/            race data, cards 1.0 and 2.0, pit loss, tyres, priors, replay
boxbox/rules/           card contract, frozen policy 1.1 and policy 2.0
boxbox/app/             Gradio screen with the Card and Replay tabs
boxbox/evaluation/      deterministic scoring, pairing and race-level uncertainty
scripts/rebuild_data.py rebuilds splits, race cards, priors and the gap check
scripts/reality_check.py agreement of a policy with real stops (Experimental)
data/splits.json        frozen race-level splits
data/splits-v2.json     frozen 2023 to 2026 race-level splits (Experimental)
data/reference/         pit-loss references and 2.0 priors (Experimental)
data/corpus/            corpus A, validation and mini-test (CC BY-NC-SA 4.0)
docs/diagrams/          active overview/Gantt and historical diagram assets
instructions/          original project brief (French PDF)
LICENSE                Apache License 2.0
```

The files marked Experimental, cards 2.0, policy 2.0 and the Replay tab belong to the Experimental milestone and sit outside the freeze of the A/B study.

The [evaluation tooling](docs/evaluation-tooling.md) can be checked offline on synthetic fixtures without loading a model. Its protocol checks and sample exports are not model results or actual human ratings.

The product, interface, prompts, training examples, code, notebook explanations, run guide and project documentation use English. The report, video and other teacher-facing presentation documents use French.

## Architecture

The code layout and its conventions are described in [docs/code-approach.md](docs/code-approach.md). Milestones, task outputs and prerequisites are in [docs/roadmap.md](docs/roadmap.md).

## Data sources

Race data comes from [OpenF1](https://openf1.org/) since 18 October 2026. [FastF1](https://docs.fastf1.dev/) was chosen on 26 September, but the live-timing files it reads now answer 401 for historical races. OpenF1 gives, from the 2023 season onwards, the lap times from which gaps are computed, the stints with compound and tyre age, the pit stops and the race-control messages, including safety car and virtual safety car periods. The [Jolpica-F1](https://github.com/jolpica/jolpica-f1) API, the successor of Ergast, gives the official round numbers and event names.

The Experimental milestone adds the 17 races of the 2026 season run by 22 October and reads three more OpenF1 endpoints. Weather readings give the rainfall used to call a track wet, and the air and track conditions shown on a 2.0 card. The driver list gives the acronyms and team colours of the replay, which stay outside the card. Intervals only cross-check the computed gaps on validation and test races and never feed a card. Madring and Kuala Lumpur have no earlier race in the data, so their green pit loss is a published estimate: 24.0 s for Madring (Pirelli's chief engineer, quoted by The Race on 12 September 2026) and 22.5 s for Kuala Lumpur (a Pirelli estimate reported by AutoHebdo on 4 October 2026). Both are in `data/reference/pit-loss-reference.csv` with their links. The Replay tab also shows OpenF1's yellow and blue flags and pit-lane times, and an archived weather forecast at the circuit from the [Open-Meteo](https://open-meteo.com/) Historical Forecast API (CC BY 4.0, free for non-commercial use). The forecast is fetched once per race, cached in `data/cache/open-meteo/`, and is optional: without network or cache the tab says it is unavailable. None of these feed a card.

OpenF1's licence (CC BY-NC-SA 4.0) excludes commercial use, and its free access is limited to 30 requests per minute, so the rebuild caches every response on disk. OpenF1 and Jolpica are unofficial projects, and the timing data belongs to the Formula 1 companies. BoxBox uses it for non-commercial academic work and shares a script that rebuilds its dataset instead of raw timing files. A commercial service would need a data licence. Every card value uses only laps completed before the lap being evaluated. A 2.0 card also records its time, `as_of`: the moment the driver crosses the line at the end of the previous lap. Weather, stops, track status and penalties are read before that moment. The gap behind is the exception, as on a timing screen: it is known when the car behind crosses, a few seconds later. The method is in [docs/data-protocol.md](docs/data-protocol.md), and the 2.0 card in [docs/race-card-contract-v2.md](docs/race-card-contract-v2.md).

## Installation

Installation and run instructions are in `README.txt`, the run guide required by the brief.

## Roadmap

![BoxBox overview for 17 to 22 October 2026: the five recovery milestones and the Experimental milestone (4 bis), at the 22 October snapshot](docs/diagrams/roadmap.png)

This overview shows six milestones: the five of the recovery plan and the Experimental milestone (4 bis), merged into `main`. The red dot marks the current stage at the 22 October snapshot. Colors identify phases; green means delivery, not completion. The dashed callout describes the research-scope fallback. The recovery plan set the MVP for 19 October evening, the freeze of the retained versions for 20 October at 18:00, and the package for 22 October at 12:00, with submission by 23:59 Paris time. The detailed Gantt, dependencies, capacity assumptions and task links, including the three Experimental tasks, are in [docs/roadmap.md](docs/roadmap.md); [GitHub issues](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues) track live claims, blockers and reviews.

## Team

- [Maxime Crayssac](https://github.com/mcrayssac)
- [Paul Pitiot](https://github.com/Paul-Pitiot-Cytech-Grp7-Mi)
- [Matthieu Brault](https://github.com/Matthieu92b)

D/M/E/T label data/protocol, model/notebook, evaluation/demo and team coordination work. Anyone available may claim a ready task; one person leads it and another available teammate reviews. These categories do not reserve tasks to particular people. All recovery issues started unassigned at the 17 October snapshot; GitHub holds current claims. Use the [execution guide](docs/roadmap-annexe.md#pick-up-deliver-and-review-a-task) for the workflow and the [team workflow](docs/team-workflow.md) for availability and acknowledgments. These arrangements remain pending confirmation until linked human evidence is supplied.

## License

The code and documentation in this repository are released under the [Apache License 2.0](LICENSE). Third-party material keeps its own terms. Race data obtained through OpenF1 and Jolpica is not covered by this licence, and the base language model, SmolLM3-3B, keeps its own licence (Apache 2.0).

BoxBox is an unofficial student project with no link to the Formula 1 companies. F1, FORMULA ONE, FORMULA 1, FIA FORMULA ONE WORLD CHAMPIONSHIP, GRAND PRIX and related marks are trade marks of Formula One Licensing B.V.
