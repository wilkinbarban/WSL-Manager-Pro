"""
ui/theme.py
===========

Named UI colour constants used across log messages, status widgets, and
lightweight styling in the application.

These constants avoid hardcoding hex values throughout the codebase and
make it easy to adjust the colour palette theme-wide.

Colour reference
----------------
* :data:`COLOR_TEXT` — Main text colour (light grey ``#d4d4d4``).
* :data:`COLOR_MUTED` — Secondary / dimmed text (grey ``#888888``).
* :data:`COLOR_INFO` — Informational messages (blue ``#64B5F6``).
* :data:`COLOR_SUCCESS` — Success indicators (green ``#4CAF50``).
* :data:`COLOR_WARNING` — Warning text (orange ``#FFA500``).
* :data:`COLOR_ERROR` — Error messages (red ``#F44336``).
* :data:`COLOR_ACCENT` — Accent / highlighted elements (amber ``#FFC107``).
* :data:`COLOR_STOPPED` — Stopped distro state (grey ``#9E9E9E``).
* :data:`COLOR_BG_PANEL` — Dark panel background (``#252526``).
"""

from __future__ import annotations

#: Main text colour used for log console and general labels.
COLOR_TEXT: str = "#d4d4d4"

#: Secondary / muted text for less important information.
COLOR_MUTED: str = "#888888"

#: Colour for informational log messages (light blue).
COLOR_INFO: str = "#64B5F6"

#: Colour for success messages and positive indicators (green).
COLOR_SUCCESS: str = "#4CAF50"

#: Colour for warning messages (orange).
COLOR_WARNING: str = "#FFA500"

#: Colour for error messages and critical indicators (red).
COLOR_ERROR: str = "#F44336"

#: Accent / highlight colour used for emphasis (amber/yellow).
COLOR_ACCENT: str = "#FFC107"

#: Colour used to represent a stopped / inactive distro state (grey).
COLOR_STOPPED: str = "#9E9E9E"

#: Dark panel background colour for card-style containers.
COLOR_BG_PANEL: str = "#252526"
