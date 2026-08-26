# Issue

`quote` should ask the pricing helper for the customer's price and return that
computed price in the quote payload.

Mocking the helper is only useful when the test still constrains `quote`'s owner
behavior. A test that only checks the owner result is present can miss whether
the helper-computed value is used correctly.
