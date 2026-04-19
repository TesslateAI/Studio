# tests/routers/

Router-level tests exercised through `fastapi.testclient.TestClient`. Keep
tests hermetic — override any auth / DB dependencies at the app level rather
than spinning up real backing services.
