# SPDX-License-Identifier: MIT
"""Errors raised by SDK requests to the control plane."""

from kyno.wire.errors import CoherenceError


class KynoUnavailableError(CoherenceError):
    """The control plane could not be reached and the caller opted out of degrading."""


class KynoRefusedError(KynoUnavailableError):
    """The server was reached and refused the request with an HTTP auth status."""


class KynoHistoryError(CoherenceError):
    """The control plane rejected a history query; the message contains its reason."""
