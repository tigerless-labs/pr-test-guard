from dataclasses import dataclass


@dataclass
class Response:
    status_code: int


class UserRepository:
    def __init__(self):
        self.users = []

    def add(self, password: str) -> None:
        self.users.append(password)

    def count(self) -> int:
        return len(self.users)


def create_user(password: str, repository: UserRepository) -> Response:
    repository.add(password)
    return Response(status_code=201)
