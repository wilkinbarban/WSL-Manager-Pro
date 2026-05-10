"""
ui/icons.py
===========

Small, lazily-built :class:`~PySide6.QtGui.QIcon` factory for distro status
indicators used in the Dashboard table and table rows.

Icons are created programmatically with :class:`~PySide6.QtGui.QPainter`
(no external image assets) so they scale cleanly on any screen resolution.

.. note::
    :class:`~PySide6.QtWidgets.QApplication` must exist before icons are
    created, as :class:`~PySide6.QtGui.QPixmap`-backed painting requires
    a running Qt application context.

Supported icon names
--------------------
* ``"running"``     — Green circle ``#4CAF50`` (distro is running).
* ``"stopped"``     — Grey circle ``#9E9E9E`` (distro is stopped).
* ``"installing"``  — Orange circle ``#FF9800`` (installation in progress).
* ``"default"``     — Blue circle ``#2196F3`` (system default distro marker).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

#: Cache of built icons, keyed by name.  Populated lazily by :func:`get_icon`.
_icons: dict[str, QIcon] = {}


def circle_icon(color: str, size: int = 14) -> QIcon:
    """Create a small coloured-circle :class:`QIcon` using QPainter.

    The circle is drawn with antialiasing on a transparent background.
    No external image assets are required.

    Args:
        color: HTML hex colour string (e.g. ``"#4CAF50"``).
        size: Width and height of the pixmap in pixels.  Defaults to 14.

    Returns:
        A :class:`QIcon` containing a coloured circle.
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(color))
    painter.setPen(Qt.PenStyle.NoPen)
    margin = 1
    painter.drawEllipse(margin, margin, size - 2 * margin, size - 2 * margin)
    painter.end()
    return QIcon(pixmap)


def get_icon(name: str) -> QIcon:
    """Return a cached status icon for a distro state.

    Icons are built lazily on first access and cached for the lifetime
    of the application.  Supported *name* values:

    * ``"running"`` — Green ``#4CAF50``
    * ``"stopped"`` — Grey ``#9E9E9E``
    * ``"installing"`` — Orange ``#FF9800``
    * ``"default"`` — Blue ``#2196F3``

    Args:
        name: One of the supported icon names listed above.

    Returns:
        The cached :class:`QIcon`.  If *name* is not recognised, a
        :class:`KeyError` is raised on the first access.
    """
    if name not in _icons:
        _icons["running"] = circle_icon("#4CAF50")
        _icons["stopped"] = circle_icon("#9E9E9E")
        _icons["installing"] = circle_icon("#FF9800")
        _icons["default"] = circle_icon("#2196F3")
    return _icons[name]
