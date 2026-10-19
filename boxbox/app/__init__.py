"""The English Gradio demo of BoxBox (task 2.4), specified in docs/interface.md."""

from .layout import build_app, launch
from .session import stub_respond

__all__ = ["build_app", "launch", "stub_respond"]
