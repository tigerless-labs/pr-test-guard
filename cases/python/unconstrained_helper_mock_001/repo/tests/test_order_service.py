from order_service import quote


def test_quote_returns_base_price():
    assert quote("cust_001") == {"customer_id": "cust_001", "price": 10}
