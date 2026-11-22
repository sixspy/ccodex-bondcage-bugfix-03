"""履约核验：通过后允许解笼；违约后允许罚没。

BUGFIX-03 同代禁改口（甲路径，命运说明当日锁死）：
- 本代已有正式结论 → 二次核验正式零增并拒收；
- 乙路径（二次只追加只读意见）与第三路径一律禁止，甲乙不得混用；
- 任何偏离命运说明的写入记「禁改口偏航」并拒写。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from auth import AuthHeader, require_user, require_writer
from db import (
    connect,
    generation_conclusions,
    load_attest_fate,
    now_iso,
    write_audit,
)
from locks import release, require_lock
from models import AttestIn

router = APIRouter(tags=["attest"])

ALLOWED = {"通过", "违约"}
FORMAL_MODES = {"正式"}


def _record_deviation(conn, user: str, cage_code: str, payload: dict) -> None:
    """偏离命运说明：记禁改口偏航，业务零写。偏航记录独立落盘。"""
    write_audit(conn, user, "禁改口偏航", cage_code, payload)
    conn.commit()


@router.get("/api/attest-fate")
def get_attest_fate(authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        fate = load_attest_fate(conn)
        conn.commit()
        return dict(fate)


@router.get("/api/attestations")
def list_attestations(authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        rows = conn.execute(
            """SELECT a.*, c.cage_code, c.contract_no, c.generation AS cage_generation
               FROM attestations a
               JOIN cages c ON c.id=a.cage_id
               ORDER BY a.id DESC LIMIT 200"""
        ).fetchall()
        return {"items": [dict(r) for r in rows]}


@router.post("/api/attestations")
def create_attestation(body: AttestIn, authorization: AuthHeader = None):
    user = require_writer(authorization)
    if body.outcome not in ALLOWED:
        raise HTTPException(400, "outcome 须为通过或违约")
    lock_key = f"cage:{body.cage_id}"
    with connect() as conn:
        # 后到者若拿不到笼锁：争用落盘（try_acquire 内已提交），业务零写。
        require_lock(conn, lock_key, user)
        try:
            cage = conn.execute(
                "SELECT * FROM cages WHERE id=?", (body.cage_id,)
            ).fetchone()
            if not cage:
                raise HTTPException(404, "笼不存在")
            gen = int(cage["generation"])
            prior = generation_conclusions(conn, body.cage_id, gen)

            # 甲路径：同代已有正式结论 → 正式零增并拒收。
            if prior:
                _record_deviation(
                    conn,
                    user,
                    cage["cage_code"],
                    {
                        "reason": "同代已有正式结论，二次核验拒收",
                        "attempted_outcome": body.outcome,
                        "existing_outcome": prior[0]["outcome"],
                        "existing_attestation_id": prior[0]["id"],
                        "attest_gen": gen,
                        "path": "甲",
                        "note": "正式零增",
                    },
                )
                raise HTTPException(409, "同代已有正式结论，禁止改口（正式零增）")

            # 乙路径/第三路径一律禁止：只允许「正式」。
            if body.mode not in FORMAL_MODES:
                _record_deviation(
                    conn,
                    user,
                    cage["cage_code"],
                    {
                        "reason": "偏离核验禁改口命运说明",
                        "attempted_mode": body.mode,
                        "attempted_outcome": body.outcome,
                        "attest_gen": gen,
                        "allowed_modes": sorted(FORMAL_MODES),
                        "forbidden_path": "乙路径只读意见 / 第三路径 / 甲乙混用",
                    },
                )
                raise HTTPException(409, "禁改口命运说明为甲路径，禁止只读意见或混用写入")

            if cage["status"] != "已冻结":
                raise HTTPException(409, "仅已冻结笼可核验")
            if float(cage["available"]) <= 0:
                raise HTTPException(409, "笼可用额为 0，禁止核验")

            now = now_iso()
            cur = conn.execute(
                """INSERT INTO attestations(cage_id,outcome,evidence,attest_gen,officer,created_at)
                   VALUES (?,?,?,?,?,?)""",
                (
                    body.cage_id,
                    body.outcome,
                    body.evidence or "",
                    gen,
                    user,
                    now,
                ),
            )
            new_status = "核验通过" if body.outcome == "通过" else "核验违约"
            conn.execute(
                "UPDATE cages SET status=? WHERE id=?",
                (new_status, body.cage_id),
            )
            write_audit(
                conn,
                user,
                "attest",
                cage["cage_code"],
                {
                    "attestation_id": cur.lastrowid,
                    "outcome": body.outcome,
                    "attest_gen": gen,
                    "evidence": body.evidence or "",
                    "path": "甲",
                    "mode": body.mode,
                },
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM attestations WHERE id=?", (cur.lastrowid,)
            ).fetchone()
            return dict(row)
        finally:
            release(conn, lock_key, user)
            conn.commit()
