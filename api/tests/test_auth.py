from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import AppSettings
from app.main import create_app
from app.models import AuditEvent, RateLimitBucket, WebSession
from app.passwords import token_hash
from app.rate_limit import rate_limit_key

PUBLIC_ORIGIN = "http://127.0.0.1:8080"


def csrf_token(client: TestClient) -> str:
    response = client.get("/api/auth/csrf")
    assert response.status_code == 200
    return response.json()["csrf_token"]


def mutation_headers(csrf: str, origin: str = PUBLIC_ORIGIN) -> dict[str, str]:
    return {"Origin": origin, "X-CSRF-Token": csrf}


def sign_in(
    client: TestClient,
    username: str,
    password: str,
    *,
    csrf: str | None = None,
    origin: str = PUBLIC_ORIGIN,
):
    return client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
        headers=mutation_headers(csrf or csrf_token(client), origin),
    )


def test_login_creates_hashed_opaque_cookie_session_and_logout_revokes_it(
    client: TestClient,
    engine,
    account_factory,
) -> None:
    user_id = account_factory("Alice", "correct horse battery")
    response = sign_in(client, "ALICE", "correct horse battery")

    assert response.status_code == 200
    assert response.json()["user"]["id"] == str(user_id)
    session_token = client.cookies.get("impostr_session")
    csrf = response.json()["csrf_token"]
    assert session_token is not None and len(session_token) == 43
    assert client.cookies.get("impostr_csrf") == csrf
    set_cookie_headers = [value.lower() for value in response.headers.get_list("set-cookie")]
    session_cookie = next(value for value in set_cookie_headers if "impostr_session=" in value)
    csrf_cookie = next(value for value in set_cookie_headers if "impostr_csrf=" in value)
    assert "httponly" in session_cookie
    assert "samesite=strict" in session_cookie and "secure" not in session_cookie
    assert "httponly" not in csrf_cookie
    assert "samesite=strict" in csrf_cookie

    with Session(engine) as db:
        session = db.scalar(select(WebSession))
        assert session is not None
        assert session.user_id == user_id
        assert session.token_hash == token_hash(session_token)
        assert session.csrf_token_hash == token_hash(csrf)
        expires_at = session.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        assert expires_at > datetime.now(UTC)
        assert session_token.encode() not in session.token_hash
        assert db.scalar(select(AuditEvent.action).where(AuditEvent.action == "auth.login"))

    current = client.get("/api/auth/session")
    assert current.status_code == 200
    assert current.json()["user"]["username"] == "alice"

    logout = client.post("/api/auth/logout", headers=mutation_headers(csrf))
    assert logout.status_code == 204
    assert client.get("/api/auth/session").status_code == 401
    with Session(engine) as db:
        session = db.scalar(select(WebSession))
        assert session is not None and session.revoked_at is not None
        assert db.scalar(select(AuditEvent.action).where(AuditEvent.action == "auth.logout"))


def test_unknown_inactive_and_wrong_password_have_the_same_login_response(
    client: TestClient,
    account_factory,
) -> None:
    account_factory("active-user", "correct horse battery")
    account_factory("inactive-user", "correct horse battery", active=False)
    csrf = csrf_token(client)

    responses = [
        sign_in(client, "active-user", "not the password", csrf=csrf),
        sign_in(client, "missing-user", "not the password", csrf=csrf),
        sign_in(client, "inactive-user", "correct horse battery", csrf=csrf),
    ]
    assert [response.status_code for response in responses] == [401, 401, 401]
    assert [response.json() for response in responses] == [
        {"detail": "Invalid username or password"}
    ] * 3
    assert all("active-user" not in response.text for response in responses)


def test_login_requires_exact_origin_and_pre_auth_csrf(client: TestClient) -> None:
    csrf = csrf_token(client)

    missing_csrf = client.post(
        "/api/auth/login",
        json={"username": "nobody", "password": "does-not-matter"},
        headers={"Origin": PUBLIC_ORIGIN},
    )
    foreign_origin = sign_in(
        client,
        "nobody",
        "does-not-matter",
        csrf=csrf,
        origin="https://attacker.example",
    )
    assert missing_csrf.status_code == 403
    assert foreign_origin.status_code == 403


def test_authenticated_mutations_require_the_session_bound_csrf_token(
    client: TestClient,
    account_factory,
) -> None:
    account_factory("admin", "correct horse battery", role="admin")
    pre_auth_csrf = csrf_token(client)
    response = sign_in(client, "admin", "correct horse battery", csrf=pre_auth_csrf)
    assert response.status_code == 200
    session_csrf = response.json()["csrf_token"]

    stale_header = client.post("/api/auth/logout", headers=mutation_headers(pre_auth_csrf))
    wrong_session_token = client.post("/api/auth/logout", headers=mutation_headers("A" * 43))
    missing_origin = client.post(
        "/api/auth/logout",
        headers={"X-CSRF-Token": session_csrf},
    )
    assert stale_header.status_code == 403
    assert wrong_session_token.status_code == 403
    assert missing_origin.status_code == 403
    assert client.get("/api/auth/session").status_code == 200

    logout = client.post("/api/auth/logout", headers=mutation_headers(session_csrf))
    assert logout.status_code == 204


def test_expired_session_is_rejected_and_csrf_cookie_is_not_session_auth(
    client: TestClient,
    engine,
    account_factory,
) -> None:
    account_factory("reader", "correct horse battery")
    response = sign_in(client, "reader", "correct horse battery")
    assert response.status_code == 200

    with Session(engine) as db, db.begin():
        db.execute(update(WebSession).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))

    assert client.get("/api/auth/session").status_code == 401
    assert client.get("/api/projects").status_code == 401


def test_login_rate_buckets_are_atomic_persisted_and_do_not_store_identifiers(
    client: TestClient,
    engine,
    monkeypatch,
    settings: AppSettings,
) -> None:
    from app import auth

    monkeypatch.setattr(auth, "verify_password", lambda _hash, _password: False)
    csrf = csrf_token(client)
    results = [sign_in(client, "rate-limited-user", "incorrect", csrf=csrf) for _ in range(11)]
    assert [response.status_code for response in results] == [401] * 10 + [429]
    assert int(results[-1].headers["retry-after"]) > 0

    with Session(engine) as db:
        buckets = list(db.scalars(select(RateLimitBucket)).all())
        assert len(buckets) == 2
        assert all(b"rate-limited-user" not in bucket.key_hash for bucket in buckets)
        assert all(b"testclient" not in bucket.key_hash for bucket in buckets)

    # A new client shares the same database-backed counter.
    with TestClient(create_app(engine, settings)) as next_client:
        blocked = sign_in(next_client, "rate-limited-user", "incorrect")
    assert blocked.status_code == 429


def test_login_ip_bucket_ignores_browser_supplied_forwarded_for(
    client: TestClient,
    engine,
    monkeypatch,
    settings: AppSettings,
) -> None:
    from app import auth

    monkeypatch.setattr(auth, "verify_password", lambda _hash, _password: False)
    csrf = csrf_token(client)
    for spoofed_ip in ("198.51.100.25", "203.0.113.75"):
        response = client.post(
            "/api/auth/login",
            json={"username": "forwarded-header-user", "password": "incorrect"},
            headers={
                **mutation_headers(csrf),
                "X-Forwarded-For": spoofed_ip,
                "X-Real-IP": spoofed_ip,
            },
        )
        assert response.status_code == 401

    with Session(engine) as db:
        bucket_keys = set(db.scalars(select(RateLimitBucket.key_hash)).all())
    assert rate_limit_key(settings, "login-ip", "testclient") in bucket_keys
    assert all(
        rate_limit_key(settings, "login-ip", spoofed_ip) not in bucket_keys
        for spoofed_ip in ("198.51.100.25", "203.0.113.75")
    )


def test_origin_settings_allow_https_or_loopback_http_only() -> None:
    secure = AppSettings(
        "https://impostr.example",
        b"test-only-rate-limit-key-that-is-not-a-secret",
    )
    assert secure.secure_cookies

    for origin in (
        "http://impostr.example",
        "http://127.0.0.1:8080/",
        "null",
    ):
        try:
            AppSettings(origin, b"test-only-rate-limit-key-that-is-not-a-secret")
        except ValueError:
            continue
        raise AssertionError(f"unsafe or non-canonical origin accepted: {origin}")

    try:
        AppSettings("https://impostr.example", b"short")
    except ValueError:
        pass
    else:
        raise AssertionError("short rate-limit keys must be rejected")


def test_default_public_origin_tracks_a_nondefault_frontdoor_port(monkeypatch) -> None:
    monkeypatch.setenv("APP_PORT", "8181")
    monkeypatch.setenv("IMPOSTR_PUBLIC_ORIGIN", "")
    monkeypatch.setenv("IMPOSTR_RATE_LIMIT_KEY", "test-only-rate-limit-key-that-is-not-a-secret")
    monkeypatch.delenv("DB_PASSWORD", raising=False)

    settings = AppSettings.from_environment()

    assert settings.public_origin == "http://127.0.0.1:8181"


def test_https_origin_sets_secure_authentication_cookies(
    engine,
    account_factory,
) -> None:
    account_factory("secure-user", "correct horse battery")
    settings = AppSettings(
        public_origin="https://impostr.example",
        rate_limit_key=b"test-only-rate-limit-key-that-is-not-a-secret",
    )
    with TestClient(create_app(engine, settings), base_url="https://impostr.example") as client:
        response = sign_in(
            client,
            "secure-user",
            "correct horse battery",
            origin=settings.public_origin,
        )
    assert response.status_code == 200
    cookies = [value.lower() for value in response.headers.get_list("set-cookie")]
    assert all("secure" in value for value in cookies)
