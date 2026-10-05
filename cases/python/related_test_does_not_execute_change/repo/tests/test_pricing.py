from pricing import calculate


def test_normal_price():
    assert calculate("normal") == 100
