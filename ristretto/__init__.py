"""Ristretto configuration and coding-flow runtime."""

from pathlib import Path


def _version() -> str:
    """The version in VERSION, which is what the release process tags.

    Read rather than restated. The literal here said 0.1.0 while VERSION said
    0.2.0 and v0.2.0 was tagged — so the one place a program could ask was the
    one place that was wrong, and nothing noticed because nothing asked.
    """
    try:
        return (Path(__file__).resolve().parent.parent / "VERSION").read_text(
            encoding="utf-8"
        ).strip() or "0.0.0"
    except OSError:
        # An installed copy without the source tree beside it.
        return "0.0.0"


__version__ = _version()
