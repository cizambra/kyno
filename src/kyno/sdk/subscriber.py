# SPDX-License-Identifier: MIT
"""The resource every Kyno announces version bumps on. Defined here so the
SDK owns the wire name and the server imports it from the SDK.

The server emits a standard MCP `resources/updated` notification on this
resource at every version append. Any client can subscribe to it; the
shipped adapters don't, because the binder pulls at every step boundary
and the next pull already carries the current version.
"""

from __future__ import annotations

RESOURCE_URI = "kyno://constitution/current"
