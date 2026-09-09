# SPDX-License-Identifier: MIT
"""Transport errors raised while an SDK connection is unavailable."""

from kyno.wire.errors import CoherenceError


class KynoUnavailableError(CoherenceError):
    """The control plane could not be reached and the caller opted out of degrading."""


class KynoRefusedError(KynoUnavailableError):
    """The server was reached and refused the request with an HTTP auth status."""
