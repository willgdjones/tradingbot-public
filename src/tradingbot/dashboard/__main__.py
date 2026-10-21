"""``python -m tradingbot.dashboard`` entry point."""

from __future__ import annotations

from .server import serve

if __name__ == "__main__":
    serve()
