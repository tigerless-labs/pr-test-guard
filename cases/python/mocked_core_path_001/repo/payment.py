def retry_payment(gateway, max_attempts: int = 5) -> bool:
    for _ in range(max_attempts):
        if gateway.charge():
            return True
    return False


def process_payment(gateway) -> bool:
    return retry_payment(gateway)
