"""Provider sugar wrappers for the OpenSail Connector Proxy."""

from .github import GitHub
from .gmail import Gmail
from .linear import Linear
from .slack import Slack

__all__ = ["GitHub", "Gmail", "Linear", "Slack"]
