# Empty-password validation with no user creation

Creating a user with an empty password must return HTTP 400 and must not persist a user. Valid passwords should continue to create users successfully.
