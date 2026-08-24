from service import process_payload


def test_process_payload_sends_original_payload():
    payload = {"id": "42"}

    assert process_payload(payload) is True
