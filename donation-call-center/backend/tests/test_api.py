import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    os.environ["CALLCENTER_DB"] = f"sqlite:///{tmp_path / 'test.db'}"
    for mod in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[mod]
    from fastapi.testclient import TestClient
    from app.main import create_app
    return TestClient(create_app())


def login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture()
def setup(client):
    mgr = login(client, "admin", "admin123")
    agents = []
    for i in range(3):
        r = client.post("/api/users", headers=mgr,
                        json={"name": f"Agent {i}", "username": f"agent{i}", "password": "secret1"})
        assert r.status_code == 201
        agents.append(r.json()["id"])
    csv_data = "الاسم,الموبايل,المدينة,المصدر\n" + "".join(
        f"متبرع {i},0100000{i:04d},{'القاهرة' if i % 2 else 'الجيزة'},حملة\n" for i in range(30))
    csv_data += "متبرع مكرر,+20 100 000 0001,القاهرة,حملة\n,123,,\n"
    r = client.post("/api/donors/import", headers=mgr,
                    files={"file": ("d.csv", csv_data.encode("utf-8"), "text/csv")})
    assert r.json() == {"created": 30, "duplicates": 1, "invalid_rows": [33]}
    return mgr, agents


def test_auth_required_and_roles(client, setup):
    mgr, agents = setup
    assert client.get("/api/donors").status_code == 401
    agent = login(client, "agent0", "secret1")
    assert client.get("/api/users", headers=agent).status_code == 403
    assert client.post("/api/auth/login", json={"username": "agent0", "password": "bad"}).status_code == 401


def test_balanced_distribution_and_isolation(client, setup):
    mgr, agents = setup
    r = client.post("/api/distribution/auto", headers=mgr, json={"agent_ids": agents, "limit": 9})
    assert r.json()["per_agent"] == {str(a): 3 for a in agents}
    # balanced mode tops up the agent with the smallest queue first
    client.post("/api/distribution/unassign", headers=mgr, json={"donor_ids": [
        d["id"] for d in client.get(f"/api/donors?agent_id={agents[0]}", headers=mgr).json()["items"]]})
    r = client.post("/api/distribution/auto", headers=mgr, json={"agent_ids": agents, "limit": 3})
    assert r.json()["per_agent"][str(agents[0])] == 3

    a1 = login(client, "agent1", "secret1")
    mine = client.get("/api/donors", headers=a1).json()
    assert mine["total"] == 3 and all(d["assigned_agent_id"] == agents[1] for d in mine["items"])
    other = client.get(f"/api/donors?agent_id={agents[0]}", headers=mgr).json()["items"][0]
    assert client.post(f"/api/donors/{other['id']}/calls", headers=a1,
                       json={"outcome": "no_answer"}).status_code == 403


def test_filtered_fixed_distribution(client, setup):
    mgr, agents = setup
    r = client.post("/api/distribution/auto", headers=mgr, json={
        "agent_ids": agents[:2], "mode": "fixed", "per_agent": 4, "filter": {"city": "الجيزة"}})
    assert r.json()["assigned"] == 8
    giza = client.get("/api/donors?city=الجيزة&unassigned=true", headers=mgr).json()["total"]
    assert giza == 15 - 8


def test_call_outcomes_flow_and_reports(client, setup):
    mgr, agents = setup
    client.post("/api/distribution/auto", headers=mgr, json={"agent_ids": [agents[0]], "limit": 6})
    ag = login(client, "agent0", "secret1")
    queue = client.get("/api/agent/queue", headers=ag).json()
    assert len(queue) == 6
    d = [x["id"] for x in queue]
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()

    # validation
    assert client.post(f"/api/donors/{d[0]}/calls", headers=ag, json={"outcome": "donated"}).status_code == 422
    assert client.post(f"/api/donors/{d[1]}/calls", headers=ag, json={"outcome": "callback"}).status_code == 422

    client.post(f"/api/donors/{d[0]}/calls", headers=ag, json={"outcome": "donated", "amount": 500})
    client.post(f"/api/donors/{d[1]}/calls", headers=ag,
                json={"outcome": "pledged", "amount": 300, "follow_up_at": tomorrow})
    client.post(f"/api/donors/{d[2]}/calls", headers=ag, json={"outcome": "phone_off"})
    client.post(f"/api/donors/{d[3]}/calls", headers=ag, json={"outcome": "not_interested"})
    client.post(f"/api/donors/{d[4]}/calls", headers=ag, json={"outcome": "do_not_call"})
    client.post(f"/api/donors/{d[1]}/calls", headers=ag, json={"outcome": "donated", "amount": 300})

    donor2 = client.get(f"/api/donors/{d[2]}", headers=ag).json()
    assert donor2["status"] == "phone_off" and donor2["next_action_at"] is not None
    assert len(client.get(f"/api/donors/{d[1]}", headers=ag).json()["calls"]) == 2

    # final outcomes leave the queue; phone_off is rescheduled; new remains
    remaining = {x["id"] for x in client.get("/api/agent/queue", headers=ag).json()}
    assert remaining == {d[2], d[5]}

    rep = client.get("/api/reports/agents", headers=mgr).json()["agents"]
    row = next(r for r in rep if r["agent_id"] == agents[0])
    assert row["calls"] == 6 and row["donated"] == 2 and row["donated_amount"] == 800
    assert row["pledged"] == 1 and row["pledges_fulfilled"] == 1
    assert row["phone_off"] == 1 and row["not_interested"] == 2
    assert row["reached"] == 5 and row["contact_rate"] == pytest.approx(83.3)
    assert row["conversion_rate"] == 50.0  # 2 donors donated / 4 reached donors

    outs = {o["code"]: o["count"] for o in client.get("/api/reports/outcomes", headers=mgr).json()["items"]}
    assert outs["donated"] == 2 and outs["phone_off"] == 1
    csv_text = client.get("/api/reports/export/calls.csv", headers=mgr).text
    assert "الايجنت" in csv_text and csv_text.count("\n") == 7


def test_unreachable_exhausts_after_max_attempts(client, setup):
    mgr, agents = setup
    client.post("/api/distribution/auto", headers=mgr, json={"agent_ids": [agents[0]], "limit": 1})
    ag = login(client, "agent0", "secret1")
    did = client.get("/api/agent/queue", headers=ag).json()[0]["id"]
    for code in ["no_answer", "busy", "phone_off", "no_answer", "no_answer"]:
        client.post(f"/api/donors/{did}/calls", headers=ag, json={"outcome": code})
    assert client.get(f"/api/donors/{did}", headers=ag).json()["status"] == "exhausted"
    # manager can reopen
    client.patch(f"/api/donors/{did}", headers=mgr, json={"status": "new"})
    assert client.get(f"/api/donors/{did}", headers=ag).json()["status"] == "new"


def test_transfer_open_donors(client, setup):
    mgr, agents = setup
    client.post("/api/distribution/auto", headers=mgr, json={"agent_ids": [agents[0]], "limit": 4})
    ag = login(client, "agent0", "secret1")
    first = client.get("/api/agent/queue", headers=ag).json()[0]["id"]
    client.post(f"/api/donors/{first}/calls", headers=ag, json={"outcome": "donated", "amount": 100})
    r = client.post("/api/distribution/transfer", headers=mgr,
                    json={"from_agent_id": agents[0], "to_agent_ids": agents[1:]})
    assert r.json()["moved"] == 3  # the donated donor stays with the agent who closed it
    summary = {a["id"]: a for a in client.get("/api/distribution/summary", headers=mgr).json()["agents"]}
    assert summary[agents[0]]["assigned"] == 1 and summary[agents[1]]["open"] + summary[agents[2]]["open"] == 3
    assert len(client.get("/api/distribution/history", headers=mgr).json()) == 7
