"""Client of the local OpenJev decision server (task 3.4); it loads no model.

OpenJev Flash 9B runs behind its own helper, in its own environment, on loopback
(configs/openjev.toml). Each target becomes one request: the engine's system text and the
conversation are the shared state, then come the CALL question and three diagnostic
questions. The diagnostics are scored apart and never make the call.
"""

from __future__ import annotations

import json
import tomllib
import urllib.error
import urllib.request
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

from boxbox.rules import decide

from .conversation import _prompt

CONFIG = Path("configs/openjev.toml")
# The tau that the rule of #35 chose on validation (docs/openjev.md); the demo uses it.
TAU = 0.59
# The helper asks for one letter, so the policy's two-line answer format is left out.
FORMAT_START = "\n\nReturn exactly two lines"
# The first clause of each NO CALL reason that decide() gives for a card field.
FIELD_OF_REASON = {
    "The card is missing the gap to the car ahead": "gap_ahead",
    "The card is missing the gap to the car behind": "gap_behind",
    "The card is missing a valid tyre age": "tyre_age_laps",
    "The card is missing a valid pit-loss estimate": "pit_loss_seconds",
    "The card does not show green-flag running": "track_status",
}


class OpenJevError(RuntimeError):
    """A request that got no usable answer; it is kept as an error, never as a call."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)

    def as_record(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


def load_settings(path: Path = CONFIG) -> dict[str, Any]:
    """The pinned OpenJev settings, with home-relative paths expanded."""
    settings = tomllib.loads(path.read_text(encoding="utf-8"))
    settings["server"]["python"] = str(Path(settings["server"]["python"]).expanduser())
    for part in ("model", "helper"):
        settings[part]["local_dir"] = str(
            Path(settings[part]["local_dir"]).expanduser()
        )
    return settings


def endpoint(settings: dict[str, Any]) -> str:
    server = settings["server"]
    return f"http://{server['host']}:{server['port']}/v1"


def policy_instructions(prompt: str) -> str:
    """The selected policy prompt without its closing answer-format paragraph."""
    if prompt.count(FORMAT_START) != 1:
        raise ValueError("the policy prompt no longer has one answer-format paragraph")
    return prompt.split(FORMAT_START)[0]


def state_text(policy: str, inputs: dict[str, Any]) -> str:
    """The engine's system text (policy and card), then the conversation as lines."""
    turns = [*inputs["history"], {"role": "user", "content": inputs["message"]}]
    lines = "\n".join(f"{t['role'].capitalize()}: {t['content']}" for t in turns)
    return (
        _prompt(policy, inputs["card"])
        + "\n\nConversation (latest message last):\n"
        + lines
    )


def build_request(
    settings: dict[str, Any],
    policy: str,
    inputs: dict[str, Any],
    call_order: list[str] | None = None,
    diagnostics: bool = True,
) -> dict[str, Any]:
    """One request for one target; `call_order` reorders the CALL options.

    A choice question with `orders = n` is also asked in the n - 1 other cyclic orders,
    as `<name>_1` and so on, so that each option sits at each letter once.
    """
    questions = {}
    for name, question in settings["questions"].items():
        if name != "call" and not diagnostics:
            continue
        asked = {"type": question["type"], "instructions": question["instructions"]}
        if question["type"] == "choice":
            options = (
                call_order if name == "call" and call_order else question["options"]
            )
            if sorted(options) != sorted(question["options"]):
                raise ValueError(f"{name} options must be a reordering of the config's")
            described = question.get("descriptions", {})
            asked["criteria"] = {option: described.get(option) for option in options}
        questions[name] = asked
        for i in range(1, question.get("orders", 1)):
            turned = options[i:] + options[:i]
            criteria = {option: asked["criteria"][option] for option in turned}
            questions[f"{name}_{i}"] = asked | {"criteria": criteria}
    return {
        "model": "openjev-flash-9b",
        "state": state_text(policy, inputs),
        "questions": questions,
    }


def references(case: dict[str, Any]) -> dict[str, Any]:
    """Expected answers: the case's call, its scope flag, and the field the rule lacks."""
    card = json.loads(case["input_json"], parse_float=Decimal)["card"]
    call, why = decide(card)
    field = "none"
    if call == "NO CALL":
        field = FIELD_OF_REASON.get(why.split(",")[0])
        if field is None:
            raise ValueError(f"{case['case_id']}: no diagnostic field for: {why}")
    return {
        "call": case["reference"]["expected_call"],
        "in_scope": not case["attributes"]["out_of_scope"],
        "required_known": field == "none",
        "missing_field": field,
    }


def _call(url: str, body: dict | None, timeout: float) -> dict[str, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        raise OpenJevError(f"http_{error.code}", error.read().decode()[:300]) from error
    except (OSError, ValueError) as error:  # dropped connection, timeout, bad JSON
        raise OpenJevError(
            "request_failed", f"{type(error).__name__}: {error}"
        ) from error


def server_version(base: str, timeout: float = 5) -> dict[str, Any]:
    return _call(f"{base}/version", None, timeout)


def ask(base: str, request: dict[str, Any], timeout: float) -> dict[str, Any]:
    """The server's reply, refused unless every question has its answer."""
    reply = _call(f"{base}/systemone", request, timeout)
    answers = reply.get("answers") if isinstance(reply, dict) else None
    expected = {"choice": {"choice", "probabilities"}, "noul": {"noul"}}
    for name, question in request["questions"].items():
        answer = (answers or {}).get(name)
        if (
            not isinstance(answer, dict)
            or not expected[question["type"]] <= answer.keys()
        ):
            raise OpenJevError("incomplete_answer", f"no usable answer to {name}")
    return reply


def chat_answer(call: str, answers: dict[str, Any], tau: float = TAU) -> str:
    """The demo's two lines from one reply and its call at tau.

    OpenJev picks an option and writes no text, so WHY gives its CALL probabilities and,
    on NO CALL, the field its diagnostic names. It never borrows the rule's reason.
    """
    probabilities = [
        f"{label} {float(p):.2f}"
        for label, p in answers["call"]["probabilities"].items()
    ]
    shares = ", ".join(probabilities[:-1]) + f" and {probabilities[-1]}"
    field = (answers.get("missing_field") or {}).get("choice", "none")
    named = (
        f", and names {field} as the field that stops the policy"
        if call == "NO CALL" and field != "none"
        else ""
    )
    return (
        f"CALL: {call}\nWHY: OpenJev Flash 9B picks a call without writing a reason: "
        f"it gives {shares} against a threshold of {tau:.2f}{named}."
    )


def responder(
    settings: dict[str, Any],
    policy: str,
    decided: Callable[[dict[str, Any], float], str],
    tau: float = TAU,
) -> Callable[[dict[str, Any], list[dict[str, str]], str], str]:
    """The demo's engine on a running server: one request per message, as in the study.

    The request keeps the diagnostic questions so that the shared state is the one scored
    in task 3.4; `decided` is the threshold rule of the runner.
    """
    base = endpoint(settings)
    timeout = settings["server"]["request_timeout_seconds"]

    def respond(
        card: dict[str, Any], history: list[dict[str, str]], message: str
    ) -> str:
        inputs = {"card": card, "history": history, "message": message}
        answers = ask(base, build_request(settings, policy, inputs), timeout)["answers"]
        return chat_answer(decided(answers["call"], tau), answers, tau)

    return respond
