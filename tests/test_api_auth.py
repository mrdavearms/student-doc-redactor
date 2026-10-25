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


class TestHealthIdentityProof:
    """
    /api/health proves which process answered without the caller sending the
    token.

    A healthy port does not mean the backend is ours: an orphan left behind by
    a force-quit, or a second copy of the app, answers first while our own
    uvicorn is still loading spaCy and has not yet failed to bind. Electron's
    waitForBackend sends a fresh random nonce in X-Health-Nonce and accepts
    the listener only if `proof` is HMAC-SHA256(token, nonce). The old design
    sent X-Api-Token and trusted an `instance_match` flag, which handed the
    token to whatever held the port and let it answer "yes". See CLAUDE.md
    rule 55.
    """

    NONCE = "ab" * 32  # 64 hex characters, as backendIdentity.newNonce() makes

    @staticmethod
    def _expected(token: str, nonce: str) -> str:
        import hashlib
        import hmac
        return hmac.new(token.encode("utf-8"), nonce.encode("ascii"),
                        hashlib.sha256).hexdigest()

    def test_health_proof_matches_hmac(self, monkeypatch):
        monkeypatch.setenv("REDACTION_API_TOKEN", "sekrit-token")
        r = client.get("/api/health", headers={"X-Health-Nonce": self.NONCE})
        assert r.status_code == 200
        body = r.json()
        assert body["proof"] == self._expected("sekrit-token", self.NONCE)
        assert "instance_match" not in body

    def test_health_without_nonce_has_no_proof(self, monkeypatch):
        """The renderer's reachability poller sends nothing, and gets plain
        liveness back."""
        monkeypatch.setenv("REDACTION_API_TOKEN", "sekrit-token")
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        assert r.json()["proof"] is None

    @pytest.mark.parametrize("nonce", [
        "ab" * 31,            # too short
        "ab" * 33,            # too long
        "zz" * 32,            # right length, not hex
        "AB" * 32,            # upper case: newNonce() never makes it
        "",
    ])
    def test_health_rejects_malformed_nonce(self, monkeypatch, nonce):
        """Only a nonce of the shape the launcher makes earns a proof, so the
        endpoint cannot be used to sign arbitrary attacker-chosen strings."""
        monkeypatch.setenv("REDACTION_API_TOKEN", "sekrit-token")
        r = client.get("/api/health", headers={"X-Health-Nonce": nonce})
        assert r.status_code == 200
        assert r.json()["proof"] is None

    def test_health_rejects_non_ascii_nonce_without_500(self, monkeypatch):
        """Header passed as UTF-8 bytes because httpx refuses a non-ASCII str
        header client-side (see test_non_ascii_token_header_returns_401_not_500)."""
        monkeypatch.setenv("REDACTION_API_TOKEN", "sekrit-token")
        r = client.get("/api/health",
                       headers={"X-Health-Nonce": ("é" * 64).encode("utf-8")})
        assert r.status_code == 200
        assert r.json()["proof"] is None

    def test_health_never_reads_x_api_token(self, monkeypatch):
        """A wrong token alongside a valid nonce changes nothing: the proof is
        still right and the response still 200. Health stays unauthenticated
        (rule 35) and identity rests on the proof alone."""
        monkeypatch.setenv("REDACTION_API_TOKEN", "sekrit-token")
        r = client.get("/api/health", headers={"X-Health-Nonce": self.NONCE,
                                               "X-Api-Token": "wrong"})
        assert r.status_code == 200
        assert r.json()["proof"] == self._expected("sekrit-token", self.NONCE)

    def test_no_token_configured_gives_no_proof_but_stays_healthy(self, monkeypatch):
        """A manually-run uvicorn (or pytest) has no identity to prove. It
        still answers ok, so the renderer's poller and the dev workflow work;
        only Electron's launcher checks the proof, and Electron always sets a
        token."""
        monkeypatch.delenv("REDACTION_API_TOKEN", raising=False)
        r = client.get("/api/health", headers={"X-Health-Nonce": self.NONCE})
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        assert r.json()["proof"] is None
