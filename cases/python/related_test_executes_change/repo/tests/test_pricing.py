from pricing import calculate


def test_vip_price():
    assert calculate("vip") == 75
