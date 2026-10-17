# BoxBox execution guide

Use the [consolidated roadmap](roadmap.md) for task definitions, dependencies, windows and the dated progress snapshot. Use its linked GitHub issues for current claims, blockers, reviews and detailed acceptance checklists. This guide replaces the former fixed-person iteration cards; it does not prescribe a module tree or create future deliverable files.

## Pick up, deliver and review a task

1. Check the issue and its prerequisites. A task is ready only after prerequisite outputs are reviewed and integrated. Comment with your claim, self-assign as the single lead and change its label to `status:in-progress`. Confirm no other teammate is already claiming it.
2. Keep one active hands-on implementation task per person. Others may help; an unattended computation can run while its lead takes another ready task. D/M/E/T identify work categories, not reserved owners.
3. Use an isolated working directory and a small branch such as `feature/2-5a-conversation-engine`. Agree temporary coordination for shared notebook/dependency-file edits; publish a cell or focused change for later integration when necessary. Do not make a permanent person-to-file assignment.
4. Implement the issue's expected output using existing shared functions where possible. Run relevant checks, retain actual outputs and record commands, versions and successful/failed/not-run results with reasons. A planned command is not a passed check.
5. Move to `status:review` with the change/deliverable link and evidence. Any available teammate other than the implementer may review. The reviewer checks acceptance and the affected end-to-end path; changes requested return to in progress. Record who reviewed and what they checked.
6. Close with `status:done` only after acceptance and integration, or after the reviewed deliverable is accessible. Link the review and integration reference. A commit, screenshot or checked box alone does not prove completion. Submission task 5.6 additionally requires the actual human submission receipt.

Use one status label: **planned → ready → in progress → review → done**; also **blocked** and **deferred**. Reopen a task when acceptance is invalidated. Keep deferred research work open with its decision rather than closing it as successful.

For a blocker, record the obstacle, current branch/artifacts, checks already run and the smallest next action. Agree a handover or release the claim promptly; do not reserve work indefinitely. Record scope/count decisions with evidence and team agreement in the relevant gate issue. Review and coordination time come from the same 50–70-hour capacity, including the protected 8-hour reserve.

## Shared implementation checks

Agree the card/history/message interface in 1.4 before concurrent component work. Demo construction uses sample cards and a visible stub until 2.8 integrates the real adapter. The evaluator uses synthetic fixtures and accepted race/split IDs without waiting for the full training corpus. Split races before producing examples; never expose final cases before the reviewed freeze.

Task 1.5 establishes real model/environment versions and working commands. Later tasks reuse those commands and update the English run guide with actual checks. Keep notebooks, data provenance, configurations, responses and adapters identifiable. Human ratings and training outputs must be genuine; retain failures and negative findings. No architecture or executable launcher is asserted to exist at the 17 October planning snapshot.

English is used for the product, prompts, data examples, code, notebook, run guide and project documentation. The report, video and other teacher-facing presentation material are French. The original assignment stays in French. Copy the agreed local project instructions into each clone using the team's local process, preserving their Git exclusion.

## Assignment and deliverable coverage

The source is the original [French assignment](../instructions/mini_projet_2_agent_conversationnel.pdf). The French video is an additional teacher requirement and remains protected in the recovery plan. The following are required outputs, not files already delivered.

| Requirement | Evidence to produce | Consolidated tasks |
|---|---|---|
| 1. Define the assistant | Audience, scope, exclusions, reference policy and five conversations | 1.1, 1.2, [1.4](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/3) |
| 2. Observe the model | Tokenizer/IDs, logits/softmax, argmax, temperature/top-k or top-p; explanations of embeddings, causal attention and unembedding | [1.5](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/4) |
| 3. Build the baseline | Native conversation format, bounded history, two prompts compared on validation and retained outputs | [2.5a](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/11), [2.5b](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/12) |
| 4. Prepare data | Real reconstruction, race separation before generation, manual review and personal-data checks | [2.1](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/6), [2.2](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/7), [3.1](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/16) |
| 5. Adapt | Frozen base; LoRA/QLoRA settings, actual losses, validation selection, stopping rationale and reloadable adapter | [2.6](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/13), [3.2](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/17) |
| 6. Evaluate | At least 20 unseen MVP queries, five-axis 0–2 rubric, paired comparison and at least five discussed cases; closed final study | [2.3a](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/8), [2.3b](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/9), [2.7](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/14), [4.1](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/20), [4.2](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/21), [4.3](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/22), [4.4](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/23), [4.5](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/24) |
| 7. Demonstrate | English Gradio from the notebook: card, chat, follow-up, reset, role/limits and real adapter | [2.4](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/10), [2.8](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/15), [5.4](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/28) |
| Executed agent.ipynb | Complete clean run with real observation/training outputs, final analysis and live interface | [5.4](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/28), [5.6](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/30) |
| French rapport.pdf | At most four pages excluding annexes; usage, data, choices, comparison, limitations and improvements | [5.1](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/25), [5.3](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/27), [5.6](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/30) |
| Data or reconstruction | Reproducible source/splits/cases; raw timing data kept local | [2.1](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/6), [2.2](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/7), [4.1](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/20), [5.2](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/26), [5.6](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/30) |
| Adapter or stable link | Frozen reloadable artifacts and reader-access checks | [2.6](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/13), [3.2](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/17), [3.5](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/19), [5.2](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/26), [5.6](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/30) |
| English README.txt | Verified installation, execution order, reconstruction, versions and resource requirements | [1.5](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/4), [5.2](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/26), [5.4](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/28), [5.6](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/30) |
| French three-minute video | Actual English product demo, measured findings, limits and proposed pilot; playback/access checks | [5.1](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/25), [5.5](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/29), [5.6](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/30) |

The complete MVP requires both 2.7 and 2.8. B corpus preparation can start after 2.2; B training waits for the complete MVP. Preserve matched 400/400 targets with 340 shared examples and 60 replacements, the approximately 200-case final target, and 40 human-reviewed cases per retained version unless the team explicitly changes scope. Keep paired race-level uncertainty, all five case categories and honest limitations. If B is dropped, a valid baseline/A study remains required and the A/B question remains unanswered.

## Mapping the colleagues' 16 tasks

Useful acceptance checks have moved into the linked issues. Fixed-person assignments, speculative file structures and superseded effort estimates have not been carried forward.

| Earlier task | Requirements preserved | Consolidated tasks |
|---|---|---|
| M1.1 | Card contract, deterministic reference, missing-field/boundary checks, five conversations | [1.4](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/3) |
| M1.2 | Compact model, pedagogy, measured feasibility, frozen-base adaptation and fresh reload | [1.5](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/4) |
| M2.1 | Real reconstruction, provenance, invalid/missing data, disjoint races, no future pit loss | [2.1](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/6) |
| M2.2 | Read all A examples and B replacements; shared 85%, 15% replacements, manifests and no leakage | [2.2](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/7), [3.1](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/16), [4.1](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/20) |
| M2.3 | Shared engine, chat template/history, two validation prompts and retained failures | [2.5a](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/11), [2.5b](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/12) |
| M2.4 | A settings/losses, validation checkpoint, stopping, genuine training and reload evidence | [2.6](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/13) |
| M2.5 | Paired baseline/A mini-test, ≥20 unseen queries, five axes and ≥5 case discussions | [2.7](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/14) |
| M2.6 | Sample-card shell; state isolation/reset/card-change/error checks; real notebook launch | [2.4](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/10), [2.8](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/15) |
| M3.1 | Matched B settings/seed/update budget, logs, reload and validation/mini outputs | [3.1](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/16), [3.2](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/17) |
| M3.2 | Interim analysis, identified artifacts/configurations, timestamped freeze and scope decision | [3.3](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/18), [3.5](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/19) |
| M4.1 | Prior rubric, fixtures with known results, ID pairing, masking and race-bootstrap edge cases | [2.3a](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/8), [2.3b](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/9) |
| M4.2 | Closed final, same cases/versions, real human scoring, uncertainty, failures and ≥5 analyses | [4.1](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/20), [4.2](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/21), [4.3](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/22), [4.4](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/23), [4.5](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/24) |
| M5.1 | Clean complete English notebook, accessible guide/artifacts and reuse of frozen final outputs | [5.2](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/26), [5.4](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/28) |
| M5.2 | French report, ≤4 pages excluding annexes, traceable numbers and page inspection | [5.1](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/25), [5.3](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/27) |
| M5.3 | French video, actual demo, measured claims, duration/playback/access checks | [5.1](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/25), [5.5](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/29) |
| M5.4 | Package checks, actual submission channel, ready-versus-submitted evidence and receipt | [1.6](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/5), [5.6](https://github.com/mcrayssac/ING3_IAA_GB_NLP_Project/issues/30) |

## Continuity with our earlier task checklist

All original task IDs remain except the two agreed splits: **2.3 → 2.3a (rubric) + 2.3b (tooling)** and **2.5 → 2.5a (engine) + 2.5b (prompt comparison)**. The model-observation output formerly in 2.5 is explicitly covered by 1.5. Task 1.6 now establishes shared pickup and review instead of fixed roles. Task 2.1 includes the real-card reconstruction needed to make its splits usable. Task 3.4 is deferred; its priority rule (repeat before V2 if revisited) is retained. Every other checklist output remains under its existing ID, with the revised dates in the roadmap.

The older `boxbox-*` diagrams remain historical assets only. Use the roadmap's `roadmap-gantt` for operational planning and the README's `roadmap` for the business overview. Update their native Excalidraw sources and exports together when the dated schedule or actual milestone changes.
