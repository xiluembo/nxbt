from __future__ import annotations


def start_qt_app():
    from .app import start_qt_app as _start_qt_app

    return _start_qt_app()


__all__ = ["start_qt_app"]
