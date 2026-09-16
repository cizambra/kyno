from dataclasses import FrozenInstanceError

import pytest

from kyno.sdk.recording import RecordingReceipt
from kyno.wire.delivery import RecordingStatus


@pytest.mark.parametrize("status", list(RecordingStatus))
def test_given_a_status_string_when_constructing_a_receipt_then_it_becomes_an_enum(status):
    assert RecordingReceipt(status.value).status is status


@pytest.mark.parametrize("field", ["status", "record_id"])
def test_given_a_receipt_when_reassigning_a_field_then_it_is_immutable(field):
    receipt = RecordingReceipt(RecordingStatus.RECORDED, "receipt-1")
    with pytest.raises(FrozenInstanceError):
        setattr(receipt, field, None)
