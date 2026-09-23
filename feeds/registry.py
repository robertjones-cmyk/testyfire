"""Adapter registry.

Adapters register themselves by ``type``; ``config.yaml`` picks one per feed.
Nothing else in the codebase imports a concrete adapter.
"""
from __future__ import annotations

from typing import Any, Iterable

from .base import FeedAdapter

_REGISTRY: dict[str, type[FeedAdapter]] = {}


class UnknownFeedType(Exception):
    pass


def register(cls: type[FeedAdapter]) -> type[FeedAdapter]:
    """Class decorator: ``@register`` on a FeedAdapter subclass."""
    key = getattr(cls, "type", None)
    if not key or key == "base":
        raise ValueError(f"{cls.__name__} must define a unique `type` class attribute")
    _REGISTRY[key] = cls
    return cls


def available_types() -> list[str]:
    return sorted(_REGISTRY)


def get_adapter_class(feed_type: str) -> type[FeedAdapter]:
    try:
        return _REGISTRY[feed_type]
    except KeyError as exc:
        raise UnknownFeedType(
            f"unknown feed type {feed_type!r}; registered types: {', '.join(available_types())}"
        ) from exc


def build(feed_config: dict[str, Any]) -> FeedAdapter:
    """Instantiate the adapter named by a feed's ``type:`` key."""
    feed_type = str(feed_config.get("type") or "")
    return get_adapter_class(feed_type)(feed_config)


def build_all(feed_configs: Iterable[dict[str, Any]]) -> list[FeedAdapter]:
    return [build(entry) for entry in feed_configs]
