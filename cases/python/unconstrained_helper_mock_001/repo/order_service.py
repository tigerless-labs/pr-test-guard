def price_for_customer(customer_id: str) -> int:
    return 10


def quote(customer_id: str) -> dict[str, int | str]:
    return {"customer_id": customer_id, "price": 10}
