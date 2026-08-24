# Issue

`process_payload` should enrich every outgoing payload with the API source before
handing it to the sender helper.

The sender helper itself can stay mocked in the unit test; the behavior under
review is the interaction contract created by `process_payload`.
