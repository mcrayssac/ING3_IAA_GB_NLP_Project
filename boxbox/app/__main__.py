"""Run the demo in the browser: python -m boxbox.app [-A | -B | -O]

Without a flag the screen answers with the rule stub. -A or -B loads SmolLM3-3B with
that selected adapter, its training prompt and its decoding, as in the notebook. -O
starts the pinned OpenJev Flash 9B server of task 3.4 and answers at its tau.
"""

import argparse
import json
import tempfile
from pathlib import Path

from . import launch

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
args = parser.parse_args()

if args.engine is None:
    launch(inbrowser=True)
elif args.engine == "OpenJev":
    from boxbox.model.openjev import (
        load_settings,
        policy_instructions,
        responder,
    )

    settings = load_settings()
    for part in ("model", "helper"):
        if not Path(settings[part]["local_dir"]).is_dir():
            parser.error(
                f"OpenJev is not installed: {settings[part]['local_dir']} is missing."
                " Install it as README.txt section 14 shows."
            )
    from boxbox.config import load_config
    from scripts.openjev_baseline import BASELINE_CONFIG, decided, served, verify_pins
    from scripts.train_adapter import selected_prompt

    verify_pins(settings)  # a changed or missing pinned file stops here
    log = Path(tempfile.mkdtemp(prefix="boxbox-openjev-")) / "server.log"
    print(f"server log   {log}")
    print("starting the OpenJev server, which can take a few minutes")
    with served(settings, log):  # stopped when the app closes
        launch(
            responder(settings, policy_instructions(selected_prompt()), decided),
            engine="OpenJev Flash 9B · zero-shot",
            turns=load_config(BASELINE_CONFIG).history_turns,
            share=False,
            inbrowser=True,
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
    )
