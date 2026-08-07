from dataclasses import dataclass


@dataclass
class Token:
    expired: bool = False


def login(token: Token) -> int:
    return 200
