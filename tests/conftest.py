"""Most backend tests call /api/pii/detect directly on temp PDFs without going
through /api/folder/process first. Let them: the allow-list is replaced by one
that admits everything, unless a test module sets `pytestmark =
pytest.mark.strict_detect` to exercise the real restriction."""

import pytest


class _AnyPath(set):
    def __contains__(self, item):
        return True


def pytest_configure(config):
    config.addinivalue_line("markers", "strict_detect: use the real detect allow-list")


@pytest.fixture(autouse=True)
def _permissive_detect_allowlist(request, monkeypatch):
    if request.node.get_closest_marker("strict_detect"):
        return
    import backend.main as main
    monkeypatch.setattr(main, "_processable", _AnyPath())
