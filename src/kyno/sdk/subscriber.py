# SPDX-License-Identifier: MIT
"""The wire name for the resource that announces version changes. It lives
in the SDK so the server can import it instead of defining its own copy.

The server sends a `resources/updated` notification on this resource every
time a version is appended. Any client can subscribe. The adapters that
ship with Kyno don't subscribe; the pull they make at every step already
returns the current version.
"""

from __future__ import annotations

RESOURCE_URI = "kyno://constitution/current"
