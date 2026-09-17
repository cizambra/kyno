from dataclasses import FrozenInstanceError

import pytest

from kyno.sdk.recording import RecordingReceipt
from kyno.wire.delivery import RecordingStatus


@pytest.mark.parametrize("status", list(RecordingStatus))
def test_given_a_status_string_when_constructing_a_receipt_then_it_becomes_an_enum(status):
    record_id = "record-1" if status is RecordingStatus.RECORDED else None
    assert RecordingReceipt(status.value, record_id).status is status


@pytest.mark.parametrize("field", ["status", "record_id"])
def test_given_a_receipt_when_reassigning_a_field_then_raises_frozen_instance_error(field):
    receipt = RecordingReceipt(RecordingStatus.RECORDED, "receipt-1")
    with pytest.raises(FrozenInstanceError):
        setattr(receipt, field, None)


@pytest.mark.parametrize(
    ("status", "record_id"),
    [
        ("recorded", None),
        ("recorded", ""),
        ("recorded", "  "),
        ("disabled", "record-1"),
        ("failed", "record-1"),
    ],
)
def test_given_an_inconsistent_outcome_when_constructing_a_receipt_then_it_is_rejected(
    status, record_id
):
    with pytest.raises(ValueError):
        RecordingReceipt(status, record_id)
