def test_register_succeeds_and_sets_httponly_cookie(client):
    r = client.post("/auth/register", json={"email": "A@Example.com", "password": "password123"})
    assert r.status_code == 201
    assert r.json()["email"] == "a@example.com"
    assert "password" not in r.text
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie


def test_duplicate_registration_rejected(client):
    body = {"email": "dup@example.com", "password": "password123"}
    assert client.post("/auth/register", json=body).status_code == 201
    r = client.post("/auth/register", json={"email": "DUP@example.com", "password": "password123"})
    assert r.status_code == 409


def test_register_validation(client):
    assert client.post("/auth/register", json={"email": "bad", "password": "password123"}).status_code == 422
    assert client.post("/auth/register", json={"email": "a@b.co", "password": "short"}).status_code == 422


def test_login_correct_and_me(client):
    client.post("/auth/register", json={"email": "u@example.com", "password": "password123"})
    client.post("/auth/logout")
    client.cookies.clear()
    r = client.post("/auth/login", json={"email": "u@example.com", "password": "password123"})
    assert r.status_code == 200
    assert client.get("/auth/me").json()["email"] == "u@example.com"


def test_login_wrong_password_and_unknown_user_same_message(client):
    client.post("/auth/register", json={"email": "u@example.com", "password": "password123"})
    client.cookies.clear()
    wrong = client.post("/auth/login", json={"email": "u@example.com", "password": "nope-nope-1"})
    unknown = client.post("/auth/login", json={"email": "x@example.com", "password": "nope-nope-1"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_protected_routes_require_auth(client):
    for method, path in [
        ("get", "/auth/me"),
        ("get", "/farms"),
        ("get", "/farms/1"),
        ("get", "/analyses"),
        ("get", "/analyses/1"),
    ]:
        assert getattr(client, method)(path).status_code == 401, path
    assert client.post("/farms", json={"name": "x"}).status_code == 401
    assert client.post("/analyses", json={"farm_id": 1, "crop": "a", "symptoms": "b"}).status_code == 401


def test_logout_clears_cookie(client):
    client.post("/auth/register", json={"email": "u@example.com", "password": "password123"})
    assert client.get("/auth/me").status_code == 200
    assert client.post("/auth/logout").status_code == 204
    assert client.get("/auth/me").status_code == 401


def test_tampered_token_rejected(client):
    client.cookies.set("agrimind_token", "not.a.jwt")
    assert client.get("/auth/me").status_code == 401
