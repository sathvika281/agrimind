from app.schemas import AnalysisResult


def _farm(c, name="My Farm"):
    return c.post("/farms", json={"name": name, "location": "Guntur", "soil_type": "Black soil"}).json()["id"]


def _analyze(c, farm_id, crop="Tomato", symptoms="Leaves are turning yellow"):
    return c.post("/analyses", json={"farm_id": farm_id, "crop": crop, "symptoms": symptoms})


def test_create_analysis_for_own_farm_is_valid_and_stored(register):
    c = register()
    r = _analyze(c, _farm(c))
    assert r.status_code == 201
    data = r.json()
    AnalysisResult.model_validate(data["result"])
    assert data["crop"] == "Tomato" and data["farm_name"] == "My Farm" and data["language"] == "en"
    assert data["result"]["recommended_actions"]
    # stored: reopen it
    again = c.get(f"/analyses/{data['id']}")
    assert again.status_code == 200 and again.json()["result"] == data["result"]


def test_history_lists_own_analyses_newest_first(register):
    c = register()
    fid = _farm(c)
    a1 = _analyze(c, fid, "Tomato", "yellow leaves").json()["id"]
    a2 = _analyze(c, fid, "Chilli", "holes in leaves, caterpillar").json()["id"]
    assert [a["id"] for a in c.get("/analyses").json()] == [a2, a1]


def test_validation_errors(register):
    c = register()
    fid = _farm(c)
    assert _analyze(c, fid, crop="  ").status_code == 422
    assert _analyze(c, fid, symptoms="").status_code == 422
    assert c.post("/analyses", json={"crop": "x", "symptoms": "y"}).status_code == 422


def test_cannot_retrieve_another_users_analysis(register):
    a = register("a@example.com")
    b = register("b@example.com")
    aid = _analyze(a, _farm(a)).json()["id"]
    foreign = b.get(f"/analyses/{aid}")
    missing = b.get("/analyses/999999")
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()


def test_history_isolation(register):
    a = register("a@example.com")
    b = register("b@example.com")
    _analyze(a, _farm(a))
    assert b.get("/analyses").json() == []
    assert len(a.get("/analyses").json()) == 1


def test_cannot_submit_analysis_with_another_users_farm(register):
    a = register("a@example.com")
    b = register("b@example.com")
    farm_id = _farm(a)
    r = _analyze(b, farm_id)
    assert r.status_code == 404
    assert b.get("/analyses").json() == [] and a.get("/analyses").json() == []


def test_provider_failure_returns_clean_error(register, monkeypatch):
    from app.services.ai import service

    class Boom:
        name = "boom"

        def analyze(self, ctx):
            raise RuntimeError("secret internal detail")

    monkeypatch.setattr(service, "get_provider", lambda: Boom())
    c = register()
    r = _analyze(c, _farm(c))
    assert r.status_code == 503
    assert "secret" not in r.text and "Traceback" not in r.text
    assert c.get("/analyses").json() == []
