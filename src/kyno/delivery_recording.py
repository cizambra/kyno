"""Recording policy and best-effort persistence of direction snapshots."""

import logging

from kyno.delivery import RecordingPolicy
from kyno.delivery_context import delivery_context
from kyno.store.delivery_record import SqlDeliveryRecordStore
from kyno.wire.delivery import RecordingStatus, recording_result

_log = logging.getLogger("kyno.delivery")


def recording_failure(exc: Exception) -> dict:
    """Log the error class without request contents and return failed status."""
    _log.warning("delivery_recording_failed", extra={"error_type": type(exc).__name__})
    return recording_result(RecordingStatus.FAILED)


def _recording_arguments(operation: str, arguments: dict) -> dict:
    selection = {}
    if operation in ("get_constitution", "get_changes_since"):
        selection["detail"] = arguments.get("detail", "compact")
    if operation == "get_changes_since":
        selection["known_version"] = arguments["known_version"]
    if operation == "get_principles":
        selection["detail"] = arguments.get("detail", "titles")
    if operation == "get_principle":
        selection["title"] = arguments["title"]
    return selection


class DeliveryRecorder:
    def __init__(
        self, store: SqlDeliveryRecordStore, policy: RecordingPolicy = RecordingPolicy.NEVER
    ) -> None:
        self._store = store
        self.policy = RecordingPolicy(policy)

    def record(
        self,
        direction: dict,
        *,
        operation: str,
        constitution: str,
        arguments: dict,
        requester: dict | None = None,
    ) -> dict:
        """Validate context and return disabled, recorded, or failed persistence status.

        Invalid context raises ValueError even when recording is disabled. Enabled
        persistence is synchronous and has no independent recording deadline.
        """
        context = delivery_context(arguments)
        if self.policy is RecordingPolicy.NEVER:
            return recording_result(RecordingStatus.DISABLED)
        try:
            identifier = self._store.append(
                direction,
                operation=operation,
                constitution=constitution,
                arguments=_recording_arguments(operation, arguments),
                context=context,
                requester=requester,
            )
        except Exception as exc:
            return recording_failure(exc)
        return recording_result(RecordingStatus.RECORDED, identifier)
