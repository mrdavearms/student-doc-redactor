"""API token auth: enabled only when REDACTION_API_TOKEN is set (Electron sets it)."""

from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)


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
