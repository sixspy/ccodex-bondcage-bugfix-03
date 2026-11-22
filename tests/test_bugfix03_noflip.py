"""BUGFIX-03 同代禁改口：先红后绿。

口径（甲路径，当日锁死）：
- 本代已有正式结论 → 二次核验正式零增并拒收；
- 乙路径（二次只追加只读意见）与第三路径一律禁止；
- 偏离命运说明记「禁改口偏航」并拒写。

本文件四支测试在修复前必须先红：
- 测A：同代二次核验仍能写入核验表；
- 测B：同代双结论仍能驱动解笼；
- 测C：双人同笼抢改口，后到争用不可查；
- 终检：五面同代应仅一正式结论。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import db
from app import app


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setattr("db.DB_PATH", tmp_path / "t.db")
    db.init_db()
    yield


def _auth(c: TestClient, user: str = "admin") -> dict:
    tok = c.post(
        "/api/login", json={"username": user, "password": "123456"}
    ).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _frozen_cage(c: TestClient, h: dict) -> dict:
    return [
        x
        for x in c.get("/api/cages", headers=h).json()["items"]
        if x["status"] == "已冻结"
    ][0]


def _seed_formal(cage: dict, outcome: str = "通过") -> int:
    """造出同代已有正式结论的数据面（旧版本/状态复位后仍可核验）。"""
    with db.connect() as conn:
        cur = conn.execute(
            """INSERT INTO attestations(cage_id,outcome,evidence,attest_gen,officer,created_at)
               VALUES (?,?,?,?,?,?)""",
            (
                cage["id"],
                outcome,
                "历史正式结论",
                int(cage["generation"]),
                "seed",
                "2026-11-22T00:00:00",
            ),
        )
        conn.commit()
        return cur.lastrowid


def _formal_rows(cage_id: int, generation: int) -> list[dict]:
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT * FROM attestations
               WHERE cage_id=? AND attest_gen=? ORDER BY id""",
            (cage_id, generation),
        ).fetchall()
        return [dict(r) for r in rows]


def test_a_same_generation_flip_still_writes_should_be_rejected():
    """测A：同代已有「通过」正式结论，再提交「违约」不得入表。"""
    c = TestClient(app)
    h = _auth(c)
    cage = _frozen_cage(c, h)
    prior_id = _seed_formal(cage, "通过")
    # 造出缺陷触发面：同代已有正式结论，笼仍处于可核验态
    with db.connect() as conn:
        conn.execute("UPDATE cages SET status='已冻结' WHERE id=?", (cage["id"],))
        conn.commit()

    r = c.post(
        "/api/attestations",
        headers=h,
        json={"cage_id": cage["id"], "outcome": "违约", "evidence": "改口违约"},
    )
    assert r.status_code == 409, r.text
    rows = _formal_rows(cage["id"], int(cage["generation"]))
    assert len(rows) == 1 and rows[0]["id"] == prior_id, "同代正式结论必须零增"
    audit = c.get("/api/audit?limit=200", headers=h).json()["items"]
    assert any(
        a["action"] == "禁改口偏航" and a["target"] == cage["cage_code"]
        for a in audit
    ), "偏离命运说明须记禁改口偏航"


def test_b_dual_conclusions_must_not_drive_release():
    """测B：同代双结论（通过+违约）不得驱动解笼拨付。"""
    c = TestClient(app)
    h = _auth(c)
    cage = _frozen_cage(c, h)
    _seed_formal(cage, "通过")
    _seed_formal(cage, "违约")
    with db.connect() as conn:
        conn.execute("UPDATE cages SET status='核验通过' WHERE id=?", (cage["id"],))
        conn.commit()

    r = c.post("/api/releases", headers=h, json={"cage_id": cage["id"]})
    assert r.status_code == 409, r.text
    assert c.get("/api/releases", headers=h).json()["items"] == []
    with db.connect() as conn:
        row = conn.execute(
            "SELECT available,status FROM cages WHERE id=?", (cage["id"],)
        ).fetchone()
        assert float(row["available"]) == float(cage["available"])
        assert row["status"] == "核验通过"

    # 同一双结论若被驱动罚没，也须拒罚且零动账。
    with db.connect() as conn:
        conn.execute("UPDATE cages SET status='核验违约' WHERE id=?", (cage["id"],))
        conn.commit()
    fr = c.post("/api/forfeits", headers=h, json={"cage_id": cage["id"]})
    assert fr.status_code == 409, fr.text
    assert c.get("/api/forfeits", headers=h).json()["items"] == []
    with db.connect() as conn:
        row = conn.execute(
            "SELECT available,status FROM cages WHERE id=?", (cage["id"],)
        ).fetchone()
        assert float(row["available"]) == float(cage["available"])


def test_c_late_flipper_contention_must_be_queryable():
    """测C：双人同笼抢改口，须占笼锁；后到争用可查且不写业务。"""
    c = TestClient(app)
    h_admin = _auth(c, "admin")
    h_clerk = _auth(c, "clerk")
    cage = _frozen_cage(c, h_admin)
    lock_key = f"cage:{cage['id']}"
    assert (
        c.post(
            "/api/locks/acquire", headers=h_admin, json={"lock_key": lock_key}
        ).status_code
        == 200
    )

    r = c.post(
        "/api/attestations",
        headers=h_clerk,
        json={
            "cage_id": cage["id"],
            "outcome": "违约",
            "evidence": "后到改口",
        },
    )
    assert r.status_code == 409, r.text
    rows = _formal_rows(cage["id"], int(cage["generation"]))
    assert rows == [], "争用后到不得写业务"
    cont = c.get("/api/contention", headers=h_admin).json()["items"]
    assert any(
        x["lock_key"] == lock_key and x["actor"] == "clerk" for x in cont
    ), "后到争用必须落 contention 且可查"


def test_final_five_surfaces_one_formal_conclusion():
    """终检：核验/笼详情/解笼/罚没/审计五面，同代仅一正式结论。"""
    c = TestClient(app)
    h = _auth(c)
    assert (
        c.post(
            "/api/bonds",
            headers=h,
            json={
                "party_key": "P-NOFLIP",
                "party_name": "禁改口验收",
                "initial_deposit": 100000,
            },
        ).status_code
        == 200
    )
    cage = c.post(
        "/api/cages/freeze",
        headers=h,
        json={
            "party_key": "P-NOFLIP",
            "contract_no": "HT-NOFLIP-1",
            "amount": 50000,
            "beneficiary": "验收受益方",
            "cage_code": "CG-NOFLIP-001",
        },
    ).json()
    gen = int(cage["generation"])
    ok = c.post(
        "/api/attestations",
        headers=h,
        json={"cage_id": cage["id"], "outcome": "通过", "evidence": "首次"},
    )
    assert ok.status_code == 200
    # 二次改口与二次同结论均拒收
    for outcome in ("违约", "通过"):
        assert (
            c.post(
                "/api/attestations",
                headers=h,
                json={"cage_id": cage["id"], "outcome": outcome},
            ).status_code
            == 409
        ), outcome

    # 1) 核验面
    atts = [
        a
        for a in c.get("/api/attestations", headers=h).json()["items"]
        if a["cage_id"] == cage["id"] and a["attest_gen"] == gen
    ]
    assert len(atts) == 1 and atts[0]["outcome"] == "通过"
    # 2) 笼详情面
    detail = c.get(f"/api/cages/{cage['id']}", headers=h).json()
    gen_rows = [a for a in detail["attestations"] if a["attest_gen"] == gen]
    assert len(gen_rows) == 1
    assert detail["current_generation_conclusion"]["count"] == 1
    assert detail["current_generation_conclusion"]["unique"] is True
    # 3) 解笼面 / 4) 罚没面
    assert [
        x
        for x in c.get("/api/releases", headers=h).json()["items"]
        if x["cage_id"] == cage["id"]
    ] == []
    assert [
        x
        for x in c.get("/api/forfeits", headers=h).json()["items"]
        if x["cage_id"] == cage["id"]
    ] == []
    # 5) 审计面：偏航可见，且无第二条正式核验
    audits = c.get("/api/audit?limit=200", headers=h).json()["items"]
    assert any(
        a["action"] == "禁改口偏航" and a["target"] == cage["cage_code"]
        for a in audits
    )
    formal_writes = [
        a
        for a in audits
        if a["action"] == "attest" and a["target"] == cage["cage_code"]
    ]
    assert len(formal_writes) == 1
    # 命运说明：甲路径，当日锁死
    fate = c.get("/api/attest-fate", headers=h).json()
    assert fate["path"] == "甲"
    assert fate["locked"] == 1
