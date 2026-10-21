"""A tiny registry so strategies can be looked up by key.

Each strategy lives in its own file (PRD §7) and registers itself with
:func:`register` (usually as a class decorator). The backtester, the paper/live
runtimes and the daily autonomous session then resolve a strategy by its ``key``
without importing it directly. A strategy is only visible once its module has been
imported, so runners import the strategy package(s) they intend to run.
"""

from __future__ import annotations

from .interface import Strategy

_REGISTRY: dict[str, type[Strategy]] = {}


def register(cls: type[Strategy]) -> type[Strategy]:
    """Register a strategy class under its ``key`` (use as a decorator)."""
    if not getattr(cls, "key", ""):
        raise ValueError(f"{cls.__name__} must set a class-level `key` to register")
    existing = _REGISTRY.get(cls.key)
    if existing is not None and existing is not cls:
        raise ValueError(
            f"strategy key {cls.key!r} already registered to {existing.__name__}"
        )
    _REGISTRY[cls.key] = cls
    return cls


def get_strategy(key: str) -> type[Strategy]:
    try:
        return _REGISTRY[key]
    except KeyError:
        raise KeyError(
            f"no strategy registered under {key!r}; known: {sorted(_REGISTRY)}"
        ) from None


def registered() -> dict[str, type[Strategy]]:
    """A copy of the current registry (key → class)."""
    return dict(_REGISTRY)
