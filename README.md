# BoxBox

BoxBox is a conversational assistant for F1 content creators and analysts. It explains a pit-stop situation from a past race. For each situation it says whether the car should box now or stay out, and it gives no call when the available information does not support a decision. It is a student project at CY Tech (NLP and Transformers course, 2026-2027), and this repository presents the project and tracks its progress.

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

Out of scope: live races, full race simulation, multi-stop optimisation, weather forecasts, betting, invented team radio quotes and permanent hosting.

## What the project tests

The research question is whether a small language model gives fewer unjustified answers on incomplete cards when some of its training examples teach it to abstain, without refusing too often when a call is possible. Two adapted versions of the same model will be compared on the same cases. Version A learns from complete cards only. Version B has 15% of its examples replaced by incomplete cards whose expected answer is NO CALL. Negative or uncertain results will be reported as they are.

## Current status

Milestone 1 of 5, framing and design. The target users, the scope, the research plan and the data source are settled. The decision rules, the race-card fields, a first check of the tools and the team roles come next. No prototype, result or feature has been delivered yet.

## Project structure

The repository holds planning documents for now:

```text
docs/roadmap.md    milestones and sub-milestones
docs/diagrams/     roadmap diagram (Excalidraw source and PNG)
instructions/     original project brief (French PDF)
LICENSE           Apache License 2.0
```

The notebook, the shared code and the data arrive with the first prototype.

The product, interface, prompts, training examples, code, notebook explanations, run guide and project documentation use English. The report, video and other teacher-facing presentation documents use French.

## Architecture

The solution is being designed. Its architecture will be documented here with the first prototype, planned for 4 October. Milestones and the detailed checklist are in [docs/roadmap.md](docs/roadmap.md).

## Data sources

Race data will come from [FastF1](https://docs.fastf1.dev/), chosen on 26 September 2026. FastF1 is an open-source Python library (MIT licence) that reads Formula 1 timing data. For each lap of a race it gives the tyre compound and its age, the positions, the lap times from which gaps can be computed, pit entries and exits, and the track status, including safety car and virtual safety car periods. It caches downloads on disk and also reads the [Jolpica-F1](https://github.com/jolpica/jolpica-f1) API, the successor of Ergast, for schedules and results.

[OpenF1](https://openf1.org/) offers similar data from the 2023 season onwards. Its licence (CC BY-NC-SA 4.0) excludes commercial use and its free access is limited to 30 requests per minute, so it stays an optional cross-check. Jolpica-F1 alone has no tyre or safety-car data, which the race card needs.

FastF1 and OpenF1 are unofficial projects, and the timing data belongs to the Formula 1 companies. BoxBox uses it for non-commercial academic work and plans to share a script that rebuilds its dataset instead of raw timing files. A commercial service would need a data licence. Pit-loss estimates will only use information available before the lap being evaluated.

## Installation

There is nothing to install yet. Installation and run instructions will come with the first prototype, in `README.txt`, the run guide required by the brief.

## Roadmap

![BoxBox roadmap: five milestones from 26 September to 22 October 2026, with framing and design marked as the current stage](docs/diagrams/roadmap.png)

This overview shows the five milestones and their key outcomes. Colors identify phases, the red dot marks the current stage, and the dashed outline marks conditional work. Dates, budgets and the detailed checklist are in [docs/roadmap.md](docs/roadmap.md).

## Team

- [Maxime Crayssac](https://github.com/mcrayssac)
- [Paul Pitiot](https://github.com/Paul-Pitiot-Cytech-Grp7-Mi)
- [Matthieu Brault](https://github.com/Matthieu92b)

The three planned responsibilities are data and protocol, model and notebook, and evaluation and demo, each reviewed by another member. Who takes which one is still to be decided.

## License

The code and documentation in this repository are released under the [Apache License 2.0](LICENSE). Third-party material keeps its own terms. Race data obtained through FastF1 (or OpenF1, if used) is not covered by this licence, and the base language model, once chosen, keeps its own licence.

BoxBox is an unofficial student project with no link to the Formula 1 companies. F1, FORMULA ONE, FORMULA 1, FIA FORMULA ONE WORLD CHAMPIONSHIP, GRAND PRIX and related marks are trade marks of Formula One Licensing B.V.
