# BoxBox roadmap

The project runs from 26 September to 22 October 2026 at midnight. The team has three members working about ten hours a week each, so roughly 110 person-hours in total. The budgets below are collective and include coordination and review.

The product, interface, prompts, training examples, code, notebook explanations, run guide and project documentation use English. The report, video and other teacher-facing presentation documents use French. The original [project brief](../instructions/mini_projet_2_agent_conversationnel.pdf) stays in French.

Current stage: milestone 1, framing and design.

![BoxBox roadmap](diagrams/roadmap.png)

## Overview

| Milestone | Dates | Collective budget | Status | Exit criterion |
|---|---|---|---|---|
| 1. Framing and design | 26 to 29 September | shared with milestone 2: 36 h | in progress | rules, race card and data source written down, tools checked, roles assigned |
| 2. First prototype | 30 September to 4 October | see above | planned | the seven steps of the brief run end to end with a first trained assistant |
| 3. Experiments | 5 to 14 October | 30 h, then 12 h | planned | A/B analysis written by 11 October, versions frozen on 14 October |
| 4. Evaluation | 15 to 18 October | shared with milestone 5: 32 h, 8 h of reserve included | planned | every frozen version scored once on the closed final test |
| 5. Delivery and presentation | 19 to 22 October | see above | planned | all deliverables submitted by 22 October at midnight |

The four budget periods are 26 September to 4 October (36 h), 5 to 11 October (30 h), 12 to 14 October (12 h), and 15 to 22 October (32 h). The date that separates milestone 1 from milestone 2, and the one that separates milestone 4 from milestone 5, are proposals the team can move.

Statuses: done, in progress, planned, and conditional (only if time allows).

## 1. Framing and design

Goal: agree on what BoxBox does, who it is for and which data it uses, before any example is produced.

- [x] Target users and their need: F1 content creators and analysts who explain pit-stop situations.
- [x] Scope and research plan, including the A/B question on abstention.
- [x] Data source chosen on 26 September: FastF1, with OpenF1 as an optional cross-check.
- [ ] Decision rules and race-card fields fixed, with their assumptions and thresholds.
- [ ] Tools and small-model check: the model loads, answers and runs a short training on the team's computers or on a free cloud GPU.
- [ ] Roles split in the team: data and protocol, model and notebook, evaluation and demo, each with a cross-reviewer.

## 2. First prototype

Goal: a first working demo that covers the seven steps of the brief, with adapter A. Due 4 October.

- [ ] Answers before any training: two prompt formulations compared on validation, the answers kept as the reference.
- [ ] Training data split by race: races divided into training, validation, MVP mini-test and final test before any dialogue is generated, then about 400 training dialogues checked by hand.
- [ ] First trained assistant (adapter A): frozen base model, training and validation losses shown, best checkpoint saved.
- [ ] Mini-test on at least 20 questions never seen in training, with five commented cases.
- [ ] Demo interface: Gradio launched from the notebook, with the race card, the chat, a reset button, and the role and limits of the assistant.

## 3. Experiments

Goal: find out whether abstention examples help the assistant, by comparing adapter B with adapter A.

- [ ] A/B training data frozen. The two sets share 85% of their examples. In B, 60 of the 400 examples become variants with a missing field and a NO CALL answer.
- [ ] Abstention variant (adapter B) trained with the same settings as A.
- [ ] Interim analysis by 11 October: comparison on validation and on the exploratory mini-test.
- [ ] Conditional, 12 to 14 October: a repeat A/B run with another seed if the result is unstable, otherwise a second model (V2). This starts only once the prototype and the interim analysis are done.
- [ ] Versions frozen on 14 October. No new experiment after that date.

## 4. Evaluation

Goal: measured results on a test set that stayed closed until the freeze.

- [ ] Final test on about 200 cases. They mix complete race cards, cards missing a needed field, incomplete cards that still allow a call, follow-up conversations and out-of-scope requests.
- [ ] Human check of 40 cases on a 0 to 2 scale, with the version hidden from the reviewer when possible.
- [ ] Gains with confidence intervals: paired differences between versions, resampled by race.
- [ ] Error analysis on at least five cases, keeping the ones that go against the hypothesis.

## 5. Delivery and presentation

Goal: hand in everything the brief asks for, plus the pitch video.

- [ ] Clean rerun of the notebook in a fresh environment.
- [ ] Report in French of four pages at most, annexes excluded.
- [ ] Run guide (`README.txt`), data rebuild script and adapter link checked.
- [ ] Three-minute pitch video in French for F1 content creators and analysts.
- [ ] Submission on 22 October at midnight.

## Keeping this file current

Tick a sub-milestone once its result is in the repository. When a milestone ends, change its status here, move the red dot to the next box in the diagram, and update the "Current status" section of the README the same day. The diagram source is `diagrams/roadmap.excalidraw`, which opens in Excalidraw.
