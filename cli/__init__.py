"""stx CLI — a thin, stateless command layer over the stx daemon for agents and humans.

Stateless by design: every workspace-scoped command takes -w/--workspace explicitly (name or id).
Nothing is stored, so concurrent sessions / sub-agents never clobber each other.
"""
