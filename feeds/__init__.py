"""Camera feed adapters.

Importing this package registers every built-in adapter by ``type``. Add your
new adapter's import here (step 5 in ``feeds/template_adapter.py``).
"""
from .base import Camera, FeedAdapter, FeedHealth, Frame  # noqa: F401
from .registry import (  # noqa: F401
    UnknownFeedType,
    available_types,
    build,
    build_all,
    get_adapter_class,
    register,
)

# Built-in adapters — importing them runs the @register decorator.
from . import hls, local_folder, nmdot, rtsp, snapshot_url, verkada  # noqa: F401,E402

__all__ = [
    "Camera",
    "FeedAdapter",
    "FeedHealth",
    "Frame",
    "available_types",
    "build",
    "build_all",
    "get_adapter_class",
    "register",
    "UnknownFeedType",
]
