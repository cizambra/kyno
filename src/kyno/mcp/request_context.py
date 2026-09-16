"""Request attribution and delivery recording shared by MCP tools and resources."""

from mcp.server import Server

from kyno.delivery import RecordingPolicy
from kyno.delivery_recording import recording_failure
from kyno.mcp.handlers import handle_whoami
from kyno.models import Token
from kyno.service import ControlPlane
from kyno.tokens import hash_value
from kyno.wire.delivery import RecordingStatus, recording_result


def _request_token(server: Server, token_store) -> Token | None:
    """The token that authenticated the current request, or None.

    Called by the set_direction case so the version records which
    credential wrote it, and by the whoami case to answer with the
    token's name and scope. Resolved from the request's own Authorization
    header -- never from tool arguments, so a client cannot claim another
    token's identity. Returns None over stdio and in-process transports,
    where there is no bearer header, and None when no store was given.

    Returns the row even for a token revoked mid-session: the endpoint
    already authenticated the request, and attribution should name the
    credential that was used."""
    if token_store is None:
        return None
    try:
        request = server.request_context.request
    except LookupError:
        return None
    if request is None:
        return None
    value = request.headers.get("authorization", "")
    if not value.startswith("Bearer "):
        return None
    return token_store.token_by_hash(hash_value(value[len("Bearer ") :]))


def record_response(
    server: Server,
    control_plane: ControlPlane,
    token_store,
    result: dict,
    operation: str,
    arguments: dict,
) -> None:
    recorder = control_plane.delivery_recorder
    if recorder is None or recorder.policy is RecordingPolicy.NEVER:
        result["recording"] = recording_result(RecordingStatus.DISABLED)
        return
    try:
        token = _request_token(server, token_store)
        result["recording"] = control_plane.record_delivery(
            result,
            operation=operation,
            arguments=arguments,
            requester=handle_whoami(token) if token else None,
        )
    except Exception as exc:
        result["recording"] = recording_failure(exc)
