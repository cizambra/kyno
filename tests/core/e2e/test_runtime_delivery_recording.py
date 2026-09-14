"""Authenticated MCP reads persist server-derived identity separately from caller metadata."""

import json

from sqlalchemy import select
from starlette.testclient import TestClient

from kyno.delivery_recording import DeliveryRecorder
from kyno.service import ControlPlane
from kyno.store.delivery_record import SqlDeliveryRecordStore
from kyno.transports import build_http_app
from tests.mcp_requests import bearer, call_tool, drive_session, gated_http_app, mint, sse_json


def test_given_a_read_token_when_reading_then_only_server_identity_is_attributed():
    store, writer, _ = gated_http_app()
    reader = mint(store, scope="read", name="agents")
    delivery_record_store = SqlDeliveryRecordStore(store.engine)
    plane = ControlPlane(store, delivery_recorder=DeliveryRecorder(delivery_record_store, "always"))
    plane.set_direction(mission="Support customers", change_note="initial")
    with TestClient(build_http_app(plane, token_store=store)) as client:
        headers = drive_session(client, bearer(reader))
        response = call_tool(
            client,
            headers,
            2,
            "get_mission",
            {
                "correlation_id": "application-session",
                "metadata": {"requester": "forged", "id": 999},
                "recording_policy": "never",
            },
        )
        direction = json.loads(sse_json(response.text)["result"]["content"][0]["text"])
        assert direction["recording"]["status"] == "recorded"
        refused = call_tool(
            client, headers, 3, "set_direction", {"mission": "No", "change_note": "No"}
        )
        assert refused.status_code == 403
        missing_auth = call_tool(
            client,
            {key: value for key, value in headers.items() if key != "Authorization"},
            4,
            "get_mission",
            {},
        )
        assert missing_auth.status_code == 401
    with store.engine.connect() as connection:
        records = (
            connection.execute(select(store.metadata.tables["kyno_delivery_records"]))
            .mappings()
            .all()
        )
    assert len(records) == 1
    record = records[0]
    assert record["record_id"] == direction["recording"]["record_id"]
    assert json.loads(record["requester"]) == {
        "id": store.tokens()[1].id,
        "name": "agents",
        "scope": "read",
    }
    assert json.loads(record["metadata"]) == {"requester": "forged", "id": 999}
    assert json.loads(record["direction"]) == {"version": 1, "mission": "Support customers"}
    assert reader not in str(record) and writer not in str(record)
