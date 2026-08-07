from payment import process_payment


class Gateway:
    def charge(self):
        return True


def test_process_payment_success():
    assert process_payment(Gateway()) is True
