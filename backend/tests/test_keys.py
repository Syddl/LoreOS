"""API key routes, and who may manage members, invites and keys (task 4.3).

A key reaches only documents and ask, which arrive with 4.4. Here a valid key shows as 403 from require_owner,
which runs only after current_member has accepted the key; a revoked or unknown key is 401 before that.
"""

import hashlib

import pytest

from conftest import W, app_client, make_key, sql
from loreos import auth

UNKNOWN = "00000000-0000-0000-0000-00000000dead"
OWNER_ROUTES = [
    ("get", "members"),
    ("delete", f"members/{UNKNOWN}"),
    ("post", "invites"),
    ("get", "invites"),
    ("post", "api-keys"),
    ("get", "api-keys"),
    ("delete", f"api-keys/{UNKNOWN}"),
]


def other_workspace():
    return sql("insert into loreos.workspaces (name) values ('b') returning id")[0][0]


def revoked_at(key_id):
    return sql("select revoked_at from loreos.api_keys where id = :id", id=key_id)[0][0]


def test_a_key_is_shown_once_and_absent_from_the_list(owner):
    created = owner.client.post(f"{W}/api-keys", json={"name": "ci"})
    assert created.status_code == 201
    body = created.json()
    assert set(body) == {"id", "name", "prefix", "key", "created_at"}
    assert body["name"] == "ci" and body["key"].startswith(auth.KEY_PREFIX)
    listed = owner.client.get(f"{W}/api-keys")
    assert listed.status_code == 200
    assert listed.json() == [
        {
            "id": body["id"],
            "name": "ci",
            "prefix": body["prefix"],
            "created_at": body["created_at"],
            "last_used_at": None,
            "revoked_at": None,
        }
    ]
    assert body["key"] not in listed.text


def test_a_key_is_stored_as_its_sha256_with_8_characters_of_its_random_part(owner):
    key = owner.client.post(f"{W}/api-keys", json={"name": "ci"}).json()["key"]
    random_part = key.removeprefix(auth.KEY_PREFIX)
    rows = sql("select key_hash, prefix, workspace_id from loreos.api_keys")
    assert len(rows) == 1
    assert rows[0].key_hash == hashlib.sha256(key.encode()).hexdigest()
    assert rows[0].prefix == random_part[:8] and len(rows[0].prefix) == 8
    assert sql("select 1 from loreos.api_keys k where position(:k in k::text) > 0", k=random_part) == []


def test_a_blank_key_name_is_refused(owner):
    assert owner.client.post(f"{W}/api-keys", json={"name": "  "}).status_code == 422
    assert sql("select count(*) from loreos.api_keys")[0][0] == 0


@pytest.mark.parametrize("method, path", OWNER_ROUTES)
def test_a_member_gets_403_on_the_owner_routes(member, method, path):
    response = getattr(member.client, method)(f"{W}/{path}", **({"json": {"name": "x"}} if method == "post" else {}))
    assert response.status_code == 403
    assert sql("select count(*) from loreos.invites")[0][0] == 0
    assert sql("select count(*) from loreos.api_keys")[0][0] == 0


@pytest.mark.parametrize("method, path", OWNER_ROUTES)
def test_a_key_gets_403_on_the_owner_routes(key_client, method, path):
    response = getattr(key_client, method)(f"{W}/{path}", **({"json": {"name": "x"}} if method == "post" else {}))
    assert response.status_code == 403
    assert sql("select count(*) from loreos.invites")[0][0] == 0
    assert sql("select count(*) from loreos.api_keys")[0][0] == 1  # key_client's own


def test_revoking_sets_revoked_at_and_the_key_then_gets_401(owner):
    created = owner.client.post(f"{W}/api-keys", json={"name": "ci"}).json()
    client = app_client(authorization=f"Bearer {created['key']}")
    assert client.get(f"{W}/api-keys").status_code == 403  # accepted, then refused as a key
    assert owner.client.delete(f"{W}/api-keys/{created['id']}").status_code == 204
    assert revoked_at(created["id"]) is not None
    assert owner.client.get(f"{W}/api-keys").json()[0]["revoked_at"] is not None
    response = client.get(f"{W}/api-keys")
    assert response.status_code == 401
    assert response.json() == {"detail": auth.BAD_KEY}


def test_revoking_an_unknown_key_gets_404(owner):
    assert owner.client.delete(f"{W}/api-keys/{UNKNOWN}").status_code == 404


def test_a_key_on_another_workspaces_path_gets_404(owner):
    b = make_key(other_workspace())
    assert b.client.get(f"{W}/api-keys").status_code == 404


def test_revoking_another_workspaces_key_by_id_gets_404_and_it_still_works(owner):
    b_id = other_workspace()
    b = make_key(b_id)
    assert owner.client.delete(f"{W}/api-keys/{b.id}").status_code == 404
    assert revoked_at(b.id) is None
    assert b.client.get(f"/api/workspaces/{b_id}/api-keys").status_code == 403  # accepted, then refused as a key
