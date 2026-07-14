from __future__ import annotations


def escape_markup(text: str) -> str:
    """Escape brackets for Textual's markup renderer."""
    return text.replace("[", r"\[")
