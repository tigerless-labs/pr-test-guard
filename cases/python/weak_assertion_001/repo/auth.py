from dataclasses import dataclass


@dataclass
class Response:
    status_code: int


def create_user(password: str) -> Response:
    return Response(status_code=201)
