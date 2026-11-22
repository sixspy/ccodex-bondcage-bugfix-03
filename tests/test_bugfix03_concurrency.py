"""BUGFIX-03 并发段单独验收：同笼双人同时抢改口。

修复前：笼锁未占稳，后到争用被回滚，contention 不可查；
甚至可能双写同代结论。修复后：恰一人成功，同代仅一正式结论，
后到争用落 contention（或已由同代禁改口闸记偏航拒写）。
"""
from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

import db
from app import app


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setattr("db.DB_PATH", tmp_path / "t.db")
    db.init_db()
    yield


def _auth(c: TestClient, user: str) -> dict:
    tok = c.post(
        "/api/login", json={"username": user, "password": "123456"}
    ).json()["token"]
    return {"Authorization": "Bearer " + tok}


def test_two_officers_race_one_formal_conclusion():
    setup = TestClient(app)
    h = _auth(setup, "admin")
    assert (
        setup.post(
            "/api/bonds",
            headers=h,
            json={
                "party_key": "P-RACE",
                "party_name": "并发验收",
                "initial_deposit": 100000,
            },
        ).status_code
        == 200
    )
    cage = setup.post(
        "/api/cages/freeze",
        headers=h,
        json={
            "party_key": "P-RACE",
            "contract_no": "HT-RACE-1",
            "amount": 30000,
            "beneficiary": "并发受益方",
            "cage_code": "CG-RACE-001",
        },
    ).json()
    cage_id = cage["id"]
    gen = int(cage["generation"])
    lock_key = f"cage:{cage_id}"

    barrier = threading.Barrier(2)
    results: dict[str, int] = {}

    def officer(user: str, outcome: str) -> None:
        client = TestClient(app)
        headers = _auth(client, user)
        barrier.wait()
        r = client.post(
            "/api/attestations",
            headers=headers,
            json={
                "cage_id": cage_id,
                "outcome": outcome,
                "evidence": f"{user} 抢改口",
            },
        )
        results[user] = r.status_code

    threads = [
        threading.Thread(target=officer, args=("admin", "通过")),
        threading.Thread(target=officer, args=("clerk", "违约")),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(results.values()) == [200, 409], results
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT * FROM attestations
               WHERE cage_id=? AND attest_gen=? ORDER BY id""",
            (cage_id, gen),
        ).fetchall()
        assert len(rows) == 1, "并发抢改口后同代只允许一条正式结论"
        cage_row = conn.execute(
            "SELECT status FROM cages WHERE id=?", (cage_id,)
        ).fetchone()
        assert cage_row["status"] in ("核验通过", "核验违约")
        cont = conn.execute(
            "SELECT * FROM contention_log WHERE lock_key=?", (lock_key,)
        ).fetchall()
        dev = conn.execute(
            "SELECT * FROM audit_trail WHERE action='禁改口偏航'"
        ).fetchall()
        # 后到要么被笼锁记为争用，要么被同代禁改口闸记偏航；二者必居其一
        assert len(cont) >= 1 or len(dev) >= 1
