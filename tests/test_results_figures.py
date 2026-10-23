"""The README mosaic quotes numbers that come from recorded results."""

from __future__ import annotations

from pathlib import Path

from scripts import results_figures as figures

ROOT = Path(__file__).resolve().parents[1]


def test_counts_match_the_final_results() -> None:
    n = figures.load()
    assert [n["agreement"][v][0] for v in figures.VERSIONS] == [43, 133, 166]
    assert n["unjustified"]["B"] == (1, 84)
    assert n["refusals"]["B"] == (30, 116)
    assert n["abstention"]["B"] == (16, 18)
    assert n["replay"] == {"validation": (22, 30), "mini_test": (17, 27)}


def test_readme_quotes_the_generated_captions() -> None:
    readme = (ROOT / "README.md").read_text()
    for key, caption in figures.captions(figures.load()).items():
        assert caption in readme, key


def test_hardcoded_figures_are_in_the_documents() -> None:
    decisions = (ROOT / "docs/4bis-decisions.md").read_text()
    for group in figures.REAL_STOPS.values():
        for value in group.values():
            assert f"{value}%" in decisions
    adapter = (ROOT / "docs/adapter-b.md").read_text()
    for text in ("0.052", "0.127", "2027"):
        assert text in adapter
