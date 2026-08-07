from auth import Token, login


def test_valid_token():
    assert login(Token(expired=False)) == 200
