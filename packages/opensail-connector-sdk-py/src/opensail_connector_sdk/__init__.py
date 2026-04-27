"""OpenSail Connector SDK (Python).

Typed sugar over the OpenSail Connector Proxy. Inside an installed app pod
two env vars are present::

    OPENSAIL_RUNTIME_URL        # base URL of the proxy
    OPENSAIL_APPINSTANCE_TOKEN  # value to send as X-OpenSail-AppInstance

The :class:`ConnectorProxy` client picks both up automatically. Each
provider exposes the most-used endpoints as native async methods so app
authors don't hand-roll httpx requests::

    from opensail_connector_sdk import ConnectorProxy

    async with ConnectorProxy() as proxy:
        await proxy.slack.chat.postMessage(channel="C123", text="hi")
"""

from .client import (
    ConnectorProxy,
    ConnectorProxyError,
    ConnectorProxyHttpError,
)

__all__ = [
    "ConnectorProxy",
    "ConnectorProxyError",
    "ConnectorProxyHttpError",
]
