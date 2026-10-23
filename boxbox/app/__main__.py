"""Run the demo in the browser: python -m boxbox.app [-A | -B | -O] [-R]

Without a flag the screen answers with the rule stub. -A or -B loads SmolLM3-3B with
that selected adapter, its training prompt and its decoding, as in the notebook. -O
starts the pinned OpenJev Flash 9B server of task 3.4 and answers at its tau. -R starts
that server for the Replay tab only: its button "Ask the model" sends the 2.0 card to
OpenJev with the policy 2.0 prompt, and it combines with -A and -B (-O gives the same
button). OpenJev peaks near 29.5 GB on the M3 Max, so -R with -A or -B needs the memory
of both models.
"""

import argparse
import json
import tempfile
from contextlib import ExitStack
from pathlib import Path

from . import launch


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m boxbox.app")
    which = parser.add_mutually_exclusive_group()
    which.add_argument(
        "-A", dest="engine", action="store_const", const="A", help="adapter A"
    )
    which.add_argument(
        "-B", dest="engine", action="store_const", const="B", help="adapter B"
    )
    which.add_argument(
        "-O",
        dest="engine",
        action="store_const",
        const="OpenJev",
        help="OpenJev Flash 9B, zero-shot, from its own environment (README section 14)",
    )
    parser.add_argument(
        "-R",
        dest="replay",
        action="store_true",
        help="OpenJev on the Replay tab only, with policy 2.0 and the 2.0 card",
    )
    return parser


def start_openjev(stack: ExitStack, settings: dict, parser: argparse.ArgumentParser):
    """Check the pinned files, then start the server until the stack closes."""
    from scripts.openjev_baseline import served, verify_pins

    for part in ("model", "helper"):
        if not Path(settings[part]["local_dir"]).is_dir():
            parser.error(
                f"OpenJev is not installed: {settings[part]['local_dir']} is missing."
                " Install it as README.txt section 14 shows."
            )
    verify_pins(settings)  # a changed or missing pinned file stops here
    log = Path(tempfile.mkdtemp(prefix="boxbox-openjev-")) / "server.log"
    print(f"server log   {log}")
    print("starting the OpenJev server, which can take a few minutes")
    stack.enter_context(served(settings, log))  # stopped when the app closes


def replay_asker_of():
    """The Replay tab's asker on the running server, at the tau the check chose, if any."""
    from boxbox.model.openjev import REPLAY_CONFIG, load_settings, replay_asker
    from boxbox.model.policy2_prompt import policy2_instructions
    from scripts.openjev_baseline import averaged, decided

    replay = load_settings(REPLAY_CONFIG)
    tau = replay.get("replay", {}).get("tau")
    return replay_asker(replay, policy2_instructions(), decided, averaged, tau)


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    with ExitStack() as stack:
        replay = None
        if args.engine == "OpenJev" or args.replay:
            from boxbox.model.openjev import load_settings

            settings = load_settings()
            start_openjev(stack, settings, parser)
            replay = replay_asker_of()
        if args.engine is None:
            launch(inbrowser=True, replay=replay)
        elif args.engine == "OpenJev":
            from boxbox.config import load_config
            from boxbox.model.openjev import policy_instructions, responder
            from scripts.openjev_baseline import BASELINE_CONFIG, decided
            from scripts.train_adapter import selected_prompt

            launch(
                responder(settings, policy_instructions(selected_prompt()), decided),
                engine="OpenJev Flash 9B · zero-shot",
                turns=load_config(BASELINE_CONFIG).history_turns,
                share=False,
                inbrowser=True,
                replay=replay,
            )
        else:
            from boxbox.model import (
                ADAPTER_A,
                ADAPTER_B,
                load_conversation_engine,
                selected_adapter,
            )

            selection = ADAPTER_A if args.engine == "A" else ADAPTER_B
            config, adapter_dir, prompt = selected_adapter(selection)
            chosen = json.loads(selection.read_text(encoding="utf-8"))
            engine = load_conversation_engine(
                config, adapter_dir=adapter_dir, instructions=prompt
            )
            print(f"adapter      {chosen['version']}, from {adapter_dir}")
            print(f"device       {engine.device}, {engine.dtype}")
            launch(
                engine.respond_with_trace,  # the trace feeds the details line under the call
                engine=f"Adapter {config.adapter} · seed {chosen['seed']} · epoch {chosen['epoch']}",
                turns=config.history_turns,
                share=False,
                inbrowser=True,
                replay=replay,
            )


if __name__ == "__main__":
    main()
