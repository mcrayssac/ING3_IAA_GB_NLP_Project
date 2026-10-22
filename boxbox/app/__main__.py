"""Run the demo in the browser: python -m boxbox.app [-A | -B]

Without a flag the screen answers with the rule stub. -A or -B loads SmolLM3-3B with
that selected adapter, its training prompt and its decoding, as in the notebook.
"""

import argparse
import json

from . import launch

parser = argparse.ArgumentParser(prog="python -m boxbox.app")
which = parser.add_mutually_exclusive_group()
which.add_argument(
    "-A", dest="adapter", action="store_const", const="A", help="adapter A"
)
which.add_argument(
    "-B", dest="adapter", action="store_const", const="B", help="adapter B"
)
args = parser.parse_args()

if args.adapter is None:
    launch(inbrowser=True)
else:
    from boxbox.model import (
        ADAPTER_A,
        ADAPTER_B,
        load_conversation_engine,
        selected_adapter,
    )

    selection = ADAPTER_A if args.adapter == "A" else ADAPTER_B
    config, adapter_dir, prompt = selected_adapter(selection)
    chosen = json.loads(selection.read_text(encoding="utf-8"))
    engine = load_conversation_engine(
        config, adapter_dir=adapter_dir, instructions=prompt
    )
    print(f"adapter      {chosen['version']}, from {adapter_dir}")
    print(f"device       {engine.device}, {engine.dtype}")
    launch(
        engine.respond_with_trace,  # the trace feeds the details line under the call
        engine=(
            f"Adapter {config.adapter} · seed {chosen['seed']} · epoch {chosen['epoch']}"
            f" · {chosen['adapter_sha256'][:8]}"
        ),
        turns=config.history_turns,
        share=False,
        inbrowser=True,
    )
