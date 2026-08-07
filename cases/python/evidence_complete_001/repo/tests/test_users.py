from users import UserRepository, create_user


def test_valid_password_creates_user():
    repository = UserRepository()
    response = create_user("secret", repository)

    assert response.status_code == 201
    assert repository.count() == 1
