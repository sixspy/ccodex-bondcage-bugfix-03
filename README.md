# 保证金笼

> 遵守 `ops/底座生成前必读_效率与技术栈.md`（≥2000 行像产品）。  
> FastAPI + Vue 3 + SQLite；`docker compose up -d --build` 一键起。  
> **禁止同构换皮**：主链路不是「占位→确认入册」也不是「入轨→裁定赔付」也不是「业务窗裁切物化」。

## 骨架一句话

保证金先入笼冻结，履约核验通过才解笼拨付，违约进罚没册，笼代与拨付罚没对账。

## 基本信息

| 项 | 值 |
|----|-----|
| 产品名 | 保证金笼 |
| 目录 | `11-bondcage` |
| 接口 | http://127.0.0.1:11328 |
| 库 | `data/app.db` |
| 账号 | admin / clerk / viewer ，密码均为 123456（viewer 只读） |

## 厚度

| 项 | 内容 |
|----|------|
| 业务 LOC | **≥2900**（py+前端，不含 vue.global / Docker / README；自检约 2984） |
| 后端模块 | db / auth / locks / bonds_svc / cages_svc / attest_svc / release_svc / forfeit_svc / reconcile_svc / audit_svc / topup_svc / split_svc |
| 前端视图 | 保证金户 / 入笼冻结 / 履约核验 / 解笼拨付 / 罚没册 / 对账互证 / 审计争用 / 增补拆笼空桩（8 页） |
| 空桩 | topup（增补入笼）、split（拆笼分拨）——前后端均有 |

## 主链路

开户入金 → 按合约入笼冻结（笼代）→ 履约核验通过 → 解笼拨付到收款方 / 违约罚没 → 笼代余额与拨付+罚没对账

## 核验禁改口（BUGFIX-03）

同笼同代只允许一条正式核验结论，口径走**甲路径**并当日锁死（`db.ATTEST_FATE_*`，落 `attest_fate` 表，页面 `/api/attest-fate` 可见）：

- 本代已有正式结论 → 二次核验**正式零增并拒收**（409）；
- 乙路径（二次只追加只读意见）与第三路径一律禁止，甲乙不得混用；
- 任何偏离命运说明的写入记审计 `禁改口偏航` 并拒写；
- 解笼 / 罚没须本代正式结论恰为 1 条，双结论一律拒拨 / 拒罚；
- 同笼双人抢改口须占笼锁（`cage:<id>`），后到争用落 `contention_log` 可查。

验收：`tests/test_bugfix03_noflip.py`（测A/测B/测C/五面终检）、`tests/test_bugfix03_concurrency.py`（并发段单独验收）。

## 互斥切口候选

- 解笼失败整笔回滚 vs 影子拨付后晋升
- 罚没立即入册 vs 影子罚没待复核晋升
- 增补同笼扩代 vs 新笼桥接双写
- 拆笼整笔事务切分 vs 影子子笼后晋升

## 启动

```powershell
cd projects/11-bondcage
docker compose up -d --build
```

浏览器：http://127.0.0.1:11328/

本机开发：

```powershell
python -m pip install -r requirements.txt
python -m uvicorn app:app --app-dir backend --host 127.0.0.1 --port 10608
python -m pytest -q
```
