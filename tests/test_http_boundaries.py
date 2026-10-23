import io
import json

import pytest

from ci import protect_production
from infra.vm import release


class Connection:
    def __init__(self, body, status=200, flavor="Google"):
        self.body = body
        self.status = status
        self.flavor = flavor
        self.closed = False
        self.requests = []

    def request(self, method, path, **kwargs):
        self.requests.append((method, path, kwargs))

    def getresponse(self):
        response = io.BytesIO(self.body)
        response.status = self.status
        response.getheader = lambda name: self.flavor
        return response

    def close(self):
        self.closed = True


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1",
        "https://metadata.google.internal",
        "file:///etc/passwd",
        "https://pharmaguard-web-dfthmgvvaa-el.a.run.app.evil.test",
        "https://pharmaguard-web-dfthmgvvaa-el.a.run.app:444",
    ],
)
def test_public_probe_rejects_unapproved_destinations_before_connecting(monkeypatch, url):
    def forbidden(*args, **kwargs):
        pytest.fail("Unapproved destination was contacted")

    monkeypatch.setattr(protect_production.http.client, "HTTPSConnection", forbidden)
    with pytest.raises(ValueError):
        protect_production.read_version(url)


@pytest.mark.parametrize("status", [301, 302, 307, 308, 503])
def test_public_probe_never_follows_redirects(monkeypatch, status):
    connection = Connection(b"redirect or error content", status=status)
    monkeypatch.setattr(
        protect_production.http.client, "HTTPSConnection", lambda *a, **k: connection
    )
    with pytest.raises(OSError):
        protect_production.read_version("https://pharmaguard-web-dfthmgvvaa-el.a.run.app")
    assert len(connection.requests) == 1 and connection.closed


def test_metadata_host_path_and_response_identity_are_fixed(monkeypatch):
    connection = Connection(json.dumps({"access_token": "synthetic-test-only"}).encode())

    def factory(host, timeout):
        assert host == "metadata.google.internal" and timeout == 10
        return connection

    monkeypatch.setattr(release.http.client, "HTTPConnection", factory)
    assert release.metadata("instance/service-accounts/default/token")["access_token"]
    assert connection.requests == [
        (
            "GET",
            "/computeMetadata/v1/instance/service-accounts/default/token",
            {"headers": {"Metadata-Flavor": "Google"}},
        )
    ]
    assert connection.closed
    with pytest.raises(ValueError):
        release.metadata("../other?redirect=external")


@pytest.mark.parametrize("status,flavor", [(302, "Google"), (200, "wrong")])
def test_metadata_rejects_redirects_or_missing_identity(monkeypatch, status, flavor):
    connection = Connection(b"{}", status=status, flavor=flavor)
    monkeypatch.setattr(release.http.client, "HTTPConnection", lambda *a, **k: connection)
    with pytest.raises(OSError):
        release.metadata("instance/service-accounts/default/token")
    assert connection.closed


@pytest.mark.parametrize("port,route", [(22, "ready"), (8080, "../metadata"), (443, "version")])
def test_local_probe_restricts_ports_and_paths(monkeypatch, port, route):
    def forbidden(*args, **kwargs):
        pytest.fail("Unapproved local destination was contacted")

    monkeypatch.setattr(release.http.client, "HTTPConnection", forbidden)
    with pytest.raises(ValueError):
        release.candidate_json(port, route)


def test_local_probe_uses_loopback_and_a_fixed_path(monkeypatch):
    connection = Connection(b'{"git_sha":"approved"}')

    def factory(host, port, timeout):
        assert (host, port, timeout) == ("127.0.0.1", 28081, 10)
        return connection

    monkeypatch.setattr(release.http.client, "HTTPConnection", factory)
    assert release.candidate_json(28081, "version", 10) == {"git_sha": "approved"}
    assert connection.requests == [("GET", "/api/version", {})] and connection.closed
