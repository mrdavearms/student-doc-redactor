"""API token auth: enabled only when REDACTION_API_TOKEN is set (Electron sets it)."""

import pytest
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

# The six paste-text-pathway endpoints (2026-08 addition). Bodies here are
# deliberately minimal/invalid — the token middleware runs before request
# routing or body validation, so a request must be rejected on the token
# alone regardless of whether the body would otherwise 422.
_TEXT_ENDPOINTS = [
    ("/api/text/detect", {}),
    ("/api/text/people", {}),
    ("/api/text/labels", {}),
    ("/api/text/clean", {}),
    ("/api/text/discard", {}),
    ("/api/text/save", {}),
]


class TestNewTextEndpointsRequireToken:
    """
    The token middleware matches on request.url.path, not on a registered
    route allow-list, so it should cover any new endpoint automatically —
    but that is exactly the kind of assumption a shipping desktop app
    should not rest on unverified. These six endpoints were not previously
    exercised by this file at all.
    """

    @pytest.mark.parametrize("path,body", _TEXT_ENDPOINTS)
    def test_no_token_rejected(self, monkeypatch, path, body):
        monkeypatch.setenv("REDACTION_API_TOKEN", "sekrit-token")
        r = client.post(path, json=body)
        assert r.status_code == 401

    @pytest.mark.parametrize("path,body", _TEXT_ENDPOINTS)
    def test_wrong_token_rejected(self, monkeypatch, path, body):
        monkeypatch.setenv("REDACTION_API_TOKEN", "sekrit-token")
        r = client.post(path, json=body, headers={"X-Api-Token": "wrong"})
        assert r.status_code == 401

    @pytest.mark.parametrize("path,body", _TEXT_ENDPOINTS)
    def test_correct_token_not_rejected(self, monkeypatch, path, body):
        monkeypatch.setenv("REDACTION_API_TOKEN", "sekrit-token")
        r = client.post(path, json=body, headers={"X-Api-Token": "sekrit-token"})
        # The bodies above are minimal/invalid, so a 422 is expected for some
        # of these — the assertion is only that auth itself did not block it.
        assert r.status_code != 401


class TestApiTokenAuth:
    def test_auth_disabled_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("REDACTION_API_TOKEN", raising=False)
        r = client.post("/api/folder/validate", json={"folder_path": "/nonexistent"})
        assert r.status_code == 200

    def test_request_without_token_rejected_when_env_set(self, monkeypatch):
        monkeypatch.setenv("REDACTION_API_TOKEN", "sekrit-token")
        r = client.post("/api/folder/validate", json={"folder_path": "/nonexistent"})
        assert r.status_code == 401
        assert "API token" in r.json()["detail"]

    def test_request_with_wrong_token_rejected(self, monkeypatch):
        monkeypatch.setenv("REDACTION_API_TOKEN", "sekrit-token")
        r = client.post("/api/folder/validate", json={"folder_path": "/nonexistent"},
                        headers={"X-Api-Token": "wrong"})
        assert r.status_code == 401

    def test_request_with_token_accepted(self, monkeypatch):
        monkeypatch.setenv("REDACTION_API_TOKEN", "sekrit-token")
        r = client.post("/api/folder/validate", json={"folder_path": "/nonexistent"},
                        headers={"X-Api-Token": "sekrit-token"})
        assert r.status_code == 200

    def test_deidentify_requires_a_token(self, monkeypatch):
        """The de-identify route must be covered by the middleware like any
        other — it reads the same cache and writes files."""
        monkeypatch.setenv("REDACTION_API_TOKEN", "sekrit-token")
        r = client.post("/api/deidentify", json={
            "folder_path": "/nonexistent", "student_name": "Jane Smith",
            "documents": [], "selected_keys": [],
        })
        assert r.status_code == 401

    def test_health_exempt_for_startup_polling(self, monkeypatch):
        """Electron's waitForBackend polls /api/health with no token."""
        monkeypatch.setenv("REDACTION_API_TOKEN", "sekrit-token")
        assert client.get("/api/health").status_code == 200

    def test_health_exempt_tolerates_trailing_slash(self, monkeypatch):
        """The exemption is path-normalised, so /api/health/ is not spuriously
        401'd — an exact-string match would block the trailing-slash variant."""
        monkeypatch.setenv("REDACTION_API_TOKEN", "sekrit-token")
        assert client.get("/api/health/").status_code != 401

    def test_non_ascii_token_header_returns_401_not_500(self, monkeypatch):
        """secrets.compare_digest raises TypeError on non-ASCII str — must not 500.

        httpx's TestClient rejects a plain str header value containing non-ASCII
        characters before the request is even sent (it encodes str header values
        as ASCII client-side). Passing the value pre-encoded as UTF-8 bytes
        bypasses that client-side check and puts the raw non-ASCII bytes on the
        wire, which is what the server-side guard actually needs to handle.
        """
        monkeypatch.setenv("REDACTION_API_TOKEN", "sekrit-token")
        r = client.post("/api/folder/validate", json={"folder_path": "/nonexistent"},
                        headers={"X-Api-Token": "tökén".encode("utf-8")})
        assert r.status_code == 401

    def test_401_response_carries_cors_header(self, monkeypatch):
        """The renderer must be able to READ the 401 in dev, not just receive it."""
        monkeypatch.setenv("REDACTION_API_TOKEN", "sekrit-token")
        r = client.post("/api/folder/validate", json={"folder_path": "/nonexistent"},
                        headers={"Origin": "http://localhost:5173"})
        assert r.status_code == 401
        assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"


class TestHealthInstanceIdentity:
    """
    /api/health reports whether the caller reached the process it spawned.

    A healthy port does not mean the backend is ours: an orphan left behind by
    a force-quit, or a second copy of the app, answers first while our own
    uvicorn is still loading spaCy and has not yet failed to bind. Electron's
    waitForBackend requires instance_match before it opens a window.
    """

    def test_matching_token_is_our_instance(self, monkeypatch):
        monkeypatch.setenv("REDACTION_API_TOKEN", "sekrit-token")
        r = client.get("/api/health", headers={"X-Api-Token": "sekrit-token"})
        assert r.status_code == 200
        assert r.json()["instance_match"] is True

    def test_foreign_token_is_not_our_instance(self, monkeypatch):
        """An orphan from a previous run holds a DIFFERENT token."""
        monkeypatch.setenv("REDACTION_API_TOKEN", "this-run-token")
        r = client.get("/api/health", headers={"X-Api-Token": "previous-run-token"})
        assert r.status_code == 200
        assert r.json()["instance_match"] is False

    def test_missing_token_is_not_our_instance(self, monkeypatch):
        monkeypatch.setenv("REDACTION_API_TOKEN", "this-run-token")
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["instance_match"] is False

    def test_mismatch_is_reported_in_the_body_never_as_401(self, monkeypatch):
        """The endpoint must stay unauthenticated (rule 35) so the renderer's
        backend-down poller keeps working — a mismatch is data, not a refusal."""
        monkeypatch.setenv("REDACTION_API_TOKEN", "this-run-token")
        r = client.get("/api/health", headers={"X-Api-Token": "wrong"})
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_no_token_configured_always_matches(self, monkeypatch):
        """A manually-run uvicorn (or pytest) has no identity to check, and
        must still look healthy — that dev workflow predates the token."""
        monkeypatch.delenv("REDACTION_API_TOKEN", raising=False)
        assert client.get("/api/health").json()["instance_match"] is True
        r = client.get("/api/health", headers={"X-Api-Token": "anything"})
        assert r.json()["instance_match"] is True

    def test_non_ascii_token_header_does_not_500(self, monkeypatch):
        """Same guard as the middleware: compare_digest raises TypeError on a
        non-ASCII str, which would turn a junk header into a 500.

        Header passed pre-encoded as UTF-8 bytes for the reason documented on
        test_non_ascii_token_header_returns_401_not_500 above: httpx rejects a
        non-ASCII str header client-side, so the bytes form is the only way to
        put those octets on the wire.
        """
        monkeypatch.setenv("REDACTION_API_TOKEN", "sekrit-token")
        r = client.get("/api/health",
                       headers={"X-Api-Token": "tökén".encode("utf-8")})
        assert r.status_code == 200
        assert r.json()["instance_match"] is False
