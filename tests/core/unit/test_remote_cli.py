import pytest

from kyno.remote import RemoteError


class _RunnerThatRefuses:
    """A session runner whose server turns every request away."""

    def __init__(self, message):
        self._message = message

    def start(self):
        from kyno.sdk.errors import KynoRefusedError

        raise KynoRefusedError(self._message)

    def call(self, fn):
        from kyno.sdk.errors import KynoRefusedError

        raise KynoRefusedError(self._message)

    def close(self):
        pass


def test_given_a_401_at_session_open_when_dialing_then_the_error_names_the_profile_and_url():
    from kyno.config import Resolved
    from kyno.remote import RemoteClient
    from kyno.sdk.errors import KynoRefusedError

    client = RemoteClient(
        Resolved(profile="ops", url="https://kyno.example", token="t", chain="ops -> ...")
    )
    client._runner = _RunnerThatRefuses("401 unauthorized")

    with pytest.raises(RemoteError) as seen:
        client.open()

    assert "'ops' at https://kyno.example refused the token: 401 unauthorized" in str(seen.value)
    assert isinstance(seen.value.__cause__, KynoRefusedError)


def test_given_a_403_on_a_tool_call_when_calling_it_then_the_error_names_the_refused_tool():
    # This refusal arrives during a call, so the message names the tool.
    from kyno.config import Resolved
    from kyno.remote import RemoteClient

    client = RemoteClient(
        Resolved(profile="ops", url="https://kyno.example", token="t", chain="ops -> ...")
    )
    client._runner = _RunnerThatRefuses(
        "forbidden: this token's scope does not cover 'set_direction'"
    )

    with pytest.raises(RemoteError) as seen:
        client.call_tool("set_direction", {})

    assert "the server refused set_direction: forbidden" in str(seen.value)


def test_given_an_error_reply_when_decoding_then_the_servers_words_come_back():
    from types import SimpleNamespace

    from kyno.config import Resolved
    from kyno.remote import RemoteClient

    client = RemoteClient(Resolved(profile="p", url="http://x", token="t", chain="c"))
    reply = SimpleNamespace(content=[SimpleNamespace(text="no field changed")], isError=True)
    client._runner = SimpleNamespace(call=lambda fn: reply)
    with pytest.raises(RemoteError, match="no field changed"):
        client.call_tool("set_direction", {})


def test_given_an_error_reply_with_no_text_when_decoding_then_the_tool_is_named():
    from types import SimpleNamespace

    from kyno.config import Resolved
    from kyno.remote import RemoteClient

    client = RemoteClient(Resolved(profile="p", url="http://x", token="t", chain="c"))
    reply = SimpleNamespace(content=[], isError=True)
    client._runner = SimpleNamespace(call=lambda fn: reply)
    with pytest.raises(RemoteError, match="the server refused set_direction"):
        client.call_tool("set_direction", {})


@pytest.mark.parametrize("raw", [None, "not-a-date"])
def test_given_a_payload_without_a_usable_created_at_then_the_version_still_builds(raw):
    from datetime import datetime

    from kyno.remote import version_from_payload

    payload = {"version": 1, "mission": "M"}
    if raw is not None:
        payload["created_at"] = raw
    version = version_from_payload(payload)
    assert version.mission == "M" and isinstance(version.created_at, datetime)
    assert version.created_at.tzinfo is not None


def test_given_a_version_zero_payload_then_it_reads_as_no_head():
    from kyno.remote import version_from_payload

    assert version_from_payload({"version": 0}) is None
