from auth import create_user


def test_valid_password_creates_user():
    response = create_user("secret")
    assert response.status_code == 201
