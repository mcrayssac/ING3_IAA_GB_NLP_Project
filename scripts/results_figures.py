"""Build the nine tiles of the README results mosaic from committed files.

Usage, from the repository root:
    python -m scripts.results_figures

The charts read the final evidence files (docs/final-analysis-evidence.json,
docs/final-findings-evidence.json) and data/reference/replay-model-check.json, so a
number in a caption always comes from a recorded result. The captures and the report
page are fitted on the same card as the charts. The page of rapport.pdf is rendered
with pdftoppm (poppler). The script prints the captions that README.md quotes.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
IMAGES = ROOT / "docs" / "images"
TILE = (900, 600)
CARD, EDGE, INK = "#fbfaf7", "#d8d2c4", "#2b2b2b"
VERSIONS = ("baseline", "A", "B")
COLORS = {"baseline": "#8d99a6", "A": "#4a7fb5", "B": "#d9822b"}
FAMILIES = ("complete", "blocking_incomplete", "usable_incomplete")
FAMILY_NAMES = ("Complete", "Blocking\nincomplete", "Usable\nincomplete")
# Policy 2.0 against real stops, in percent, from docs/4bis-decisions.md (D13).
# The evaluation races chose the variant, so the first group is exploratory.
REAL_STOPS = {
    "Evaluation races": {"recall": 53.6, "precision": 15.6, "chance": 8.0},
    "Three 2026 races": {"recall": 45.9, "precision": 18.9, "chance": 11.6},
}


def pct(part: int, total: int) -> float:
    """Share of `part` in `total`, in percent."""
    return 100 * part / total


def read(path: str) -> dict:
    """Parse one committed JSON file."""
    return json.loads((ROOT / path).read_text())


def load() -> dict:
    """Collect every plotted number, as (numerator, denominator) pairs when counted."""
    summaries = read("docs/final-analysis-evidence.json")["summaries"]
    analysis = {v: summaries[v]["metrics"] for v in VERSIONS}
    human = read("docs/final-findings-evidence.json")["human"]["summaries"]
    replay = read("data/reference/replay-model-check.json")["agreement"]

    def series(source: dict, key: str) -> dict:
        return {
            v: (source[v][key]["numerator"], source[v][key]["denominator"])
            for v in VERSIONS
        }

    return {
        "agreement": series(analysis, "overall/call_agreement"),
        "unjustified": series(analysis, "eligibility/Z/unjustified_decision_rate"),
        "refusals": series(analysis, "eligibility/D/excessive_refusal_rate"),
        "families": {
            f: series(analysis, f"family/{f}/call_agreement") for f in FAMILIES
        },
        "abstention": series(human, "overall/justified_abstention_review_rate"),
        "correctness": {
            v: human[v]["overall/human_correctness_mean"]["value"] for v in VERSIONS
        },
        "replay": {k: tuple(v) for k, v in replay.items()},
    }


def numbers(pairs: dict) -> str:
    """The three counts of a series as 'a, b and c' with their denominator."""
    parts = [pairs[v][0] for v in VERSIONS]
    return f"{parts[0]}, {parts[1]} and {parts[2]} out of {pairs['B'][1]}"


def captions(n: dict) -> dict[str, str]:
    """The caption of each tile, quoted word for word in README.md."""
    fam = n["families"]
    replay = n["replay"]
    return {
        "card": (
            "Card tab, adapter A: CALL: BOX, because the 24.0 s gap behind covers "
            "the 21.0 s pit loss plus the 2.0 s margin."
        ),
        "replay": (
            "Replay tab, Las Vegas 2024: policy 2.0 says STAY OUT and OpenJev, "
            "zero-shot, says BOX. On a small sample it agrees with policy 2.0 on "
            f"{replay['validation'][0]}/{replay['validation'][1]} validation cards "
            f"and {replay['mini_test'][0]}/{replay['mini_test'][1]} mini-test cards."
        ),
        "agreement": (
            "CALL agreement on the 200 final targets: "
            f"{numbers(n['agreement'])} for the baseline, A and B."
        ),
        "tradeoff": (
            "Calls made where the answer should be NO CALL: "
            f"{numbers(n['unjustified'])} for the baseline, A and B. "
            f"B also refuses {n['refusals']['B'][0]} of {n['refusals']['B'][1]} "
            "decidable targets."
        ),
        "families": (
            "CALL agreement on blocking incomplete cards: "
            f"{numbers(fam['blocking_incomplete'])}. On usable incomplete cards: "
            f"{numbers(fam['usable_incomplete'])}."
        ),
        "human": (
            "Human review of 40 targets per version, one rater, not blind. "
            f"Justified abstentions: {numbers(n['abstention'])}."
        ),
        "stops": (
            "Policy 2.0 against real stops: recall 53.6% and precision 15.6% "
            "against 8.0% for chance on the evaluation races (the variant was chosen "
            "on them), 45.9% and 18.9% against 11.6% on three 2026 races. "
            "Exploratory."
        ),
        "curves": (
            "Adapter B training, three seeds: validation loss from 0.052 to 0.127. "
            "Retained checkpoint: seed 2027, epoch 3."
        ),
        "report": "French report: four body pages, then annexes A to H.",
    }


def card_figure(title: str) -> tuple[plt.Figure, plt.Axes]:
    """A 900 x 600 card with a title and one axes."""
    fig = plt.figure(figsize=(9, 6), dpi=100, facecolor=CARD)
    fig.add_artist(
        Rectangle(
            (0.004, 0.006),
            0.992,
            0.988,
            fill=False,
            ec=EDGE,
            lw=2,
            transform=fig.transFigure,
        )
    )
    fig.text(0.05, 0.92, title, fontsize=19, fontweight="bold", color=INK)
    ax = fig.add_axes((0.09, 0.14, 0.86, 0.64), facecolor=CARD)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.tick_params(labelsize=14, colors=INK)
    return fig, ax


def finish(fig: plt.Figure, name: str) -> None:
    """Write the tile and close the figure."""
    fig.savefig(IMAGES / name, dpi=100, facecolor=CARD)
    plt.close(fig)


def grouped(
    ax: plt.Axes, groups: list[list[tuple[int, int]]], labels: list[str]
) -> None:
    """Draw one bar per version in each group, labelled with its count."""
    width = 0.26
    for i, version in enumerate(VERSIONS):
        xs = [g + (i - 1) * width for g in range(len(groups))]
        heights = [pct(*grp[i]) for grp in groups]
        ax.bar(xs, heights, width * 0.92, color=COLORS[version], label=version)
        for x, h, grp in zip(xs, heights, groups):
            ax.text(x, h + 1.5, f"{grp[i][0]}", ha="center", fontsize=13, color=INK)
    ax.set_xticks(range(len(groups)), labels)
    ax.set_xlim(-0.65, len(groups) - 0.35)
    ax.set_ylim(0, 112)
    ax.set_ylabel("share of targets (%)", fontsize=14)
    ax.legend(frameon=False, fontsize=13, loc="upper left", ncols=3)


def agreement_tile(n: dict) -> None:
    fig, ax = card_figure("CALL agreement, 200 final targets")
    grouped(ax, [[n["agreement"][v] for v in VERSIONS]], ["all targets"])
    finish(fig, "03-call-agreement.png")


def tradeoff_tile(n: dict) -> None:
    fig, ax = card_figure("Where B decides, and where it refuses")
    groups = [
        [n["unjustified"][v] for v in VERSIONS],
        [n["refusals"][v] for v in VERSIONS],
    ]
    grouped(
        ax,
        groups,
        [
            "unjustified calls\n(of 84 to abstain)",
            "excessive refusals\n(of 116 decidable)",
        ],
    )
    finish(fig, "04-abstention-tradeoff.png")


def families_tile(n: dict) -> None:
    fig, ax = card_figure("CALL agreement by kind of card")
    groups = [[n["families"][f][v] for v in VERSIONS] for f in FAMILIES]
    grouped(ax, groups, list(FAMILY_NAMES))
    finish(fig, "05-by-family.png")


def human_tile(n: dict) -> None:
    fig, ax = card_figure("Human review, 40 targets per version")
    ax.set_position((0.09, 0.14, 0.48, 0.64))
    grouped(
        ax, [[n["abstention"][v] for v in VERSIONS]], ["justified abstentions\n(of 18)"]
    )
    ax.get_legend().remove()
    ax2 = fig.add_axes((0.67, 0.14, 0.29, 0.64), facecolor=CARD)
    values = [n["correctness"][v] for v in VERSIONS]
    ax2.bar(range(3), values, color=[COLORS[v] for v in VERSIONS])
    for x, v in enumerate(values):
        ax2.text(x, v + 0.04, f"{v:.2f}", ha="center", fontsize=13, color=INK)
    ax2.set_xticks(range(3), VERSIONS)
    ax2.set_ylim(0, 2)
    ax2.set_xlabel("mean correctness (0 to 2)", fontsize=13, color=INK)
    ax2.tick_params(labelsize=13, colors=INK)
    for side in ("top", "right"):
        ax2.spines[side].set_visible(False)
    finish(fig, "06-human-review.png")


def stops_tile() -> None:
    fig, ax = card_figure("Policy 2.0 against real stops")
    names = {"recall": "#8d99a6", "precision": "#4a7fb5", "chance": "#c9c4b8"}
    width = 0.26
    for i, (metric, color) in enumerate(names.items()):
        xs = [g + (i - 1) * width for g in range(len(REAL_STOPS))]
        values = [group[metric] for group in REAL_STOPS.values()]
        ax.bar(xs, values, width * 0.92, color=color, label=metric)
        for x, v in zip(xs, values):
            ax.text(x, v + 1.2, f"{v}%", ha="center", fontsize=13, color=INK)
    ax.set_xticks(range(len(REAL_STOPS)), list(REAL_STOPS))
    ax.set_ylim(0, 70)
    ax.set_ylabel("percent", fontsize=14)
    ax.legend(frameon=False, fontsize=13, loc="upper right")
    finish(fig, "07-real-stops.png")


def fit(source: Image.Image, name: str, cover: bool = False, top: float = 0.5) -> None:
    """Put an image on the card with the same border as the charts.

    `cover` fills the card and crops the overflow, `top` picks the vertical share
    of the crop kept at the top (0 keeps the top of the image).
    """
    inner = (TILE[0] - 6, TILE[1] - 6)
    box = (TILE[0] - 40, TILE[1] - 40)
    pick = max if cover else min
    scale = pick(box[0] / source.width, box[1] / source.height)
    size = (round(source.width * scale), round(source.height * scale))
    picture = source.convert("RGB").resize(size, Image.LANCZOS)
    if cover:
        left = (size[0] - box[0]) // 2
        up = round((size[1] - box[1]) * top)
        picture = picture.crop((left, up, left + box[0], up + box[1]))
    tile = Image.new("RGB", inner, CARD)
    tile.paste(
        picture, ((inner[0] - picture.width) // 2, (inner[1] - picture.height) // 2)
    )
    border = Image.new("RGB", TILE, EDGE)
    border.paste(tile, (3, 3))
    border.save(IMAGES / name, quality=90, optimize=True)


def report_page() -> Image.Image:
    """First body page of rapport.pdf, rendered with pdftoppm."""
    with tempfile.TemporaryDirectory() as folder:
        prefix = Path(folder) / "page"
        subprocess.run(
            [
                "pdftoppm",
                "-f",
                "3",
                "-l",
                "3",
                "-r",
                "110",
                "-png",
                str(ROOT / "rapport.pdf"),
                str(prefix),
            ],
            check=True,
        )
        (page,) = Path(folder).glob("page-*.png")
        return Image.open(page).copy()


def main() -> None:
    IMAGES.mkdir(exist_ok=True)
    n = load()
    agreement_tile(n)
    tradeoff_tile(n)
    families_tile(n)
    human_tile(n)
    stops_tile()
    fit(Image.open(IMAGES / "captures" / "card-tab.jpg"), "01-card-tab.jpg", True, 0.3)
    fit(
        Image.open(IMAGES / "captures" / "replay-openjev.jpg"),
        "02-replay-openjev.jpg",
        True,
        0.3,
    )
    fit(
        Image.open(ROOT / "docs" / "diagrams" / "adapter-b-losses.png"),
        "08-training-curves-b.jpg",
    )
    fit(report_page(), "09-report.jpg", True, 0.0)
    for key, text in captions(n).items():
        print(f"{key}: {text}")


if __name__ == "__main__":
    main()
