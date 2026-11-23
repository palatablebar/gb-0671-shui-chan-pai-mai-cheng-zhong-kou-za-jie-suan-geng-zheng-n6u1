# 东港水产拍卖结算

给水产市场结算员处理双次称重、扣杂计价、结算更正与应付复核。

七个模块：称重采信、货品换算、毛皮配对、扣杂竞价、更正裁决、应付对账、结算归档。每个导航页均可重跑同一批数据，隔离行保留编号、原值、行号和原因码。

## 扣杂口径迁移（规则 2026.11.17-r2 → 2026.11.20-r3）

规则升级后，计价重量量化口径由 0.001kg 收紧到 0.01kg，金额仍四舍五入到分。导航“08 口径迁移”（`/migration`）对近 90 天已封存的旧口径批次逐批裁决：

1. `POST /api/migration/seed` 播种 11 个确定性历史封存批（4 个健康批、5 个证据异常批、1 个窗口外、1 个未封存），重复播种幂等不覆盖。
2. `POST /api/migration/runs` 执行迁移：仅窗口内已封存旧规则批次进入候选；先核验源快照，再以旧规则重算与封存证据对平（输入行、隔离数、金额、封存指纹），通过后才以新规则重算并做守恒校验。
3. 全部通过的批次生成新规则封存批（状态“已封存”，`manifest.migrated_from` 指向旧批），旧批与源快照原样保留；任一核验失败的批次“留旧待核”，页面列出原因码（`MIG_SNAPSHOT_MISSING`、`MIG_INPUT_MISMATCH`、`MIG_QUARANTINE_MISMATCH`、`MIG_AMOUNT_MISMATCH`、`MIG_SEAL_MISMATCH`、`MIG_NEW_UNBALANCED`），不替换现行版本。
4. 迁移按候选集合指纹幂等：同一迁移重跑得到同一迁移批号，批次数量与逐批裁决一致，runs 表不新增重复行。新封存批与迁移记录在单事务内提交，任一写入失败整体回滚，原始快照与封存证据不丢失。

页面逐批展示源快照指纹、旧/新规则版本、输入行、隔离行、生效票、重算前后金额、差额、裁决结果、新封存批链接与阻断原因；窗口外和未封存批次列在排除区，不计入迁移批次数量。

```sh
docker compose up --build -d
docker compose exec -T app pytest -q
```

浏览器访问 http://localhost:18240 。默认载入现场脏批，包含53条逻辑输入、重复表头、缺列、空值、重复冲突、缺皮重、毛重小于皮重等问题。切换“核验清批”或“旧编码批”后重跑。进入“更正裁决”核对票00001：原应付1168.50CNY，更正后1285.35CNY，已付1168.50CNY，仅待付116.85CNY。

API：各模块 `POST /api/<导航英文名>`；完整运行 `POST /api/runs`，JSON参数可用 `dataset` 或 `csv_text`。查询历史 `GET /api/runs`，复核 `POST /api/runs/{run_id}/review`，传入当前 `revision`。封存下载只有 `GET /api/export/{run_id}` 一个入口。迁移 API：`POST /api/migration/seed`、`POST /api/migration/runs`、`GET /api/migration/runs`、`GET /api/migration/runs/{migration_id}`。

同输入和规则摘要生成相同批号，不新增重复记录；复核版本改变后旧版本提交返回409。SQLite保存在命名卷。可使用新卷名称重建演示数据，原卷保留。

定义见 `docs/DATA-DICTIONARY.md`，模块与测试映射见 `docs/DEPTH.md`。源码在 `app/`，业务样例在 `sample_data/`，测试在 `tests/`。不连接实际秤台和支付渠道。

采信页支持上传或粘贴CSV。完整源字节与参数随批次持久化，跨页通过run_id读取同一结果。`POST /api/runs/{run_id}/rerun` 读取该批不可变输入快照重新计算，规则未变时批号不变。切换另一示例则创建或复用另一批次。
