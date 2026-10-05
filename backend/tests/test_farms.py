def test_create_and_list_own_farms(register):
    c = register()
    r = c.post("/farms", json={"name": "Tomato Farm", "location": "Guntur", "soil_type": "Red soil"})
    assert r.status_code == 201
    assert r.json()["name"] == "Tomato Farm"
    farms = c.get("/farms").json()
    assert [f["name"] for f in farms] == ["Tomato Farm"]
    assert c.get(f"/farms/{farms[0]['id']}").status_code == 200


def test_farm_name_required(register):
    c = register()
    assert c.post("/farms", json={"name": "   "}).status_code == 422
    assert c.post("/farms", json={}).status_code == 422


def test_cannot_access_another_users_farm(register):
    a = register("a@example.com")
    b = register("b@example.com")
    farm_id = a.post("/farms", json={"name": "A farm"}).json()["id"]
    assert b.get("/farms").json() == []
    assert b.get(f"/farms/{farm_id}").status_code == 404


def test_foreign_and_nonexistent_farm_are_indistinguishable(register):
    a = register("a@example.com")
    b = register("b@example.com")
    farm_id = a.post("/farms", json={"name": "A farm"}).json()["id"]
    foreign = b.get(f"/farms/{farm_id}")
    missing = b.get("/farms/999999")
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
