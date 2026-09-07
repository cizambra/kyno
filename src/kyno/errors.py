class CoherenceError(Exception):
    """Base class for all kyno errors."""


class UnknownConstitutionError(CoherenceError):
    """The named constitution has never been initialized."""


class UnknownVersionError(CoherenceError):
    """A version was requested that is beyond the current HEAD."""


class EmptyChangeError(CoherenceError):
    """set_direction was called with no field that actually changes."""


class NoFieldChangedError(EmptyChangeError):
    """The edit would leave every field exactly as it is."""


class UnknownPrincipleError(CoherenceError):
    """No principle in the current version carries that title."""


class MalformedPrincipleError(CoherenceError):
    """A principle was neither a title nor a title-and-description."""


class UnpublishableNameError(CoherenceError):
    """The constitution's name cannot be served as a URL path segment."""


class VersionConflictError(CoherenceError):
    """A concurrent writer already created the target version."""


class CorruptStateError(CoherenceError):
    """HEAD points at a version row that does not exist."""


class AuthoringError(CoherenceError):
    """A constitution file could not be read, or does not say what it must."""


class FieldTooLargeError(CoherenceError):
    """A constitution field is over its documented size cap."""


class ReservedMarkerError(CoherenceError):
    """A field carries the header of the direction block adapters inject."""


class ConfigError(CoherenceError):
    """An environment-derived setting is missing or malformed."""


class KynoUnavailableError(CoherenceError):
    """The control plane could not be reached and the caller opted out of degrading."""


class KynoRefusedError(KynoUnavailableError):
    """The server was reached and turned the request away at the door with
    an HTTP auth status. The message is the status line, e.g. '401
    unauthorized'."""
