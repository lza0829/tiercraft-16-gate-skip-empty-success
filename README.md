# 05-tiercraft（筑层）

筑层 — 数仓分层建设台：贴源入仓 → 明细清洗标准化 → 汇总落表 → 层间行数/键对账。

**不是** 多源 Feed 归并，**不是** 作业依赖编排，**不是** CDC 变更流按序落库，**不是** 质检隔离签发。
**也不是** 报表看板 / CRUD 后台 / 电商订单前台 / OA 工单。

## 启动

```bash
docker compose up --build
```

本地开发：

```bash
# 后端
cd backend
pip install -r requirements.txt
set DATA_DIR=..\data
uvicorn app.main:app --reload --port 10500

# 前端
cd frontend
npm install
npm run dev
```

| 入口 | 地址 |
| --- | --- |
| 前端 | http://localhost:5500 |
| 接口 | http://localhost:10500 |

## 主链

登记主题域 → 贴源层装载夹具 → 明细层清洗标准化 → 汇总层聚合 → 层间对账报告与各层列表数字同源

## 上游就绪闸

两个分层任务启动前都校验上游，未就绪时任务以「失败」落库并标明原因码，下游分层不会被清空或写入半截结果：

| 任务 | 闸条件 | 失败原因码 | 失败类型 |
| --- | --- | --- | --- |
| 贴源到明细 | 主题域贴源行数 > 0 | `UPSTREAM_PASTE_EMPTY` | 上游未就绪 |
| 贴源到明细 | 清洗后仍有有效行 | `CLEAN_RESULT_EMPTY` | 业务失败 |
| 明细到汇总 | 存在贴源到明细任务记录 | `UPSTREAM_DETAIL_JOB_MISSING` | 上游未就绪 |
| 明细到汇总 | 最近一次贴源到明细状态为成功 | `UPSTREAM_DETAIL_JOB_FAILED` | 上游未就绪 |
| 明细到汇总 | 明细行数 > 0 | `UPSTREAM_DETAIL_EMPTY` | 上游未就绪 |

失败任务同样写入任务列表，并记录 `fail_code`、`fail_reason` 与 `upstream_job_id`（最近一次上游成功任务引用）。通过闸后，分层替换与任务记录在同一事务内提交；总览分层计数、任务状态与层表行数取自同一份 SQLite，刷新后仍一致。

## 闸裁决证明

每次任务启动前的闸判定都会落一条 `gate_checks` 记录，按 `job_id` 与任务一一关联：

| 字段 | 含义 |
| --- | --- |
| `upstream_count` | 启动前读到的上游层表行数（与总览分层计数同一份 SQLite） |
| `upstream_job_id` | 闸所引的最近一次成功上游任务 id |
| `allowed` | 是否放行（0/1） |
| `basis` | 判定依据，固定为「层表计数」 |
| `fail_code` | 拦截时的失败原因码，放行时为空 |

任务接口按任务 id 返回该证明：`GET /api/jobs/{job_id}`（只读）。`GET /api/jobs` 与 `GET /api/dashboard` 的每条任务同样带 `gate` 字段。「分层任务」界面在任务行与运行回执中展示闸失败原因及上述证明字段。

## 界面约定

页面文案全部中文；分层称「贴源层 / 明细层 / 汇总层」，界面不出现英文缩写站名。
