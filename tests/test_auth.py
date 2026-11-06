from rest_framework.test import APIClient

from .conftest import PASSWORD


def login(username, password=PASSWORD):
    return APIClient().post("/api/v1/auth/login/", {"username": username, "password": password}, format="json")


def test_login_returns_wrapped_tokens(world):
    response = login("admin_a")
    assert response.status_code == 200
    assert set(response.json()["result"]) == {"access_token", "refresh_token"}


def test_wrong_password_and_unknown_user_look_the_same(world):
    wrong = login("admin_a", "nope")
    unknown = login("nobody", "nope")
    assert wrong.status_code == unknown.status_code == 400
    assert wrong.json()["message"] == unknown.json()["message"]


def test_refresh_rotates_and_old_token_dies(world):
    refresh = login("admin_a").json()["result"]["refresh_token"]
    client = APIClient()
    first = client.post("/api/v1/auth/refresh/", {"refresh_token": refresh}, format="json")
    assert first.status_code == 200
    again = client.post("/api/v1/auth/refresh/", {"refresh_token": refresh}, format="json")
    assert again.status_code == 401


def test_logout_revokes_refresh_token(world):
    tokens = login("admin_a").json()["result"]
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access_token']}")
    assert (
        client.post("/api/v1/auth/logout/", {"refresh_token": tokens["refresh_token"]}, format="json").status_code
        == 204
    )
    assert (
        APIClient().post("/api/v1/auth/refresh/", {"refresh_token": tokens["refresh_token"]}, format="json").status_code
        == 401
    )


def test_me_lists_memberships_with_permissions(world):
    body = world.client(world.owner).get("/api/v1/auth/me/").json()
    assert {m["clinic"]["name"] for m in body["memberships"]} == {"Branch A", "Branch B"}
    assert "audit:view" in body["memberships"][0]["permissions"]
    assert body["organizations"] == [{"id": str(world.org.pk), "name": "Smile Group"}]


def test_doctor_permissions_are_narrow(world):
    body = world.client(world.doctor_a.user).get("/api/v1/auth/me/").json()
    perms = set(body["memberships"][0]["permissions"])
    assert "patient:view" in perms
    assert "patient:view_all" not in perms
    assert "staff:manage" not in perms
