from __future__ import annotations

import json

from app.db import connect, rows_to_dicts


STEP_LABEL = {
    "paste_to_detail": "贴源到明细",
    "detail_to_summary": "明细到汇总",
}

STATUS_SUCCESS = "成功"
STATUS_FAILED = "失败"

FAIL_TYPE_UPSTREAM = "上游未就绪"
FAIL_TYPE_BUSINESS = "业务失败"

FAIL_CODE_PASTE_EMPTY = "UPSTREAM_PASTE_EMPTY"
FAIL_CODE_DETAIL_JOB_MISSING = "UPSTREAM_DETAIL_JOB_MISSING"
FAIL_CODE_DETAIL_JOB_FAILED = "UPSTREAM_DETAIL_JOB_FAILED"
FAIL_CODE_DETAIL_EMPTY = "UPSTREAM_DETAIL_EMPTY"

UPSTREAM_FAIL_CODES = {
    FAIL_CODE_PASTE_EMPTY,
    FAIL_CODE_DETAIL_JOB_MISSING,
    FAIL_CODE_DETAIL_JOB_FAILED,
    FAIL_CODE_DETAIL_EMPTY,
}


def _fail_type(fail_code: str) -> str:
    if not fail_code:
        return ""
    return FAIL_TYPE_UPSTREAM if fail_code in UPSTREAM_FAIL_CODES else FAIL_TYPE_BUSINESS


def _job_dict(row) -> dict:
    """把任务行转成接口输出，前端直接可展示闸失败原因与上游成功任务引用。"""
    d = dict(row)
    d["step_label"] = STEP_LABEL.get(d["step"], d["step"])
    d["fail_type"] = _fail_type(d.get("fail_code") or "")
    d.setdefault("fail_code", "")
    d.setdefault("fail_reason", "")
    d.setdefault("upstream_job_id", None)
    return d


def _insert_job(
    conn,
    domain_id: int,
    step: str,
    status: str,
    message: str,
    in_count: int = 0,
    out_count: int = 0,
    drop_count: int = 0,
    fail_code: str = "",
    fail_reason: str = "",
    upstream_job_id: int | None = None,
    commit: bool = True,
) -> dict:
    cur = conn.execute(
        """
        INSERT INTO layer_jobs(
          domain_id, step, status, message, in_count, out_count, drop_count,
          fail_code, fail_reason, upstream_job_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            domain_id,
            step,
            status,
            message,
            in_count,
            out_count,
            drop_count,
            fail_code,
            fail_reason,
            upstream_job_id,
        ),
    )
    if commit:
        conn.commit()
    job_id = int(cur.lastrowid)
    return _job_dict(conn.execute("SELECT * FROM layer_jobs WHERE id=?", (job_id,)).fetchone())


def _latest_job(conn, domain_id: int, step: str):
    return conn.execute(
        "SELECT * FROM layer_jobs WHERE domain_id=? AND step=? ORDER BY id DESC LIMIT 1",
        (domain_id, step),
    ).fetchone()


def _latest_success_job(conn, domain_id: int, step: str):
    return conn.execute(
        """
        SELECT * FROM layer_jobs
        WHERE domain_id=? AND step=? AND status=?
        ORDER BY id DESC LIMIT 1
        """,
        (domain_id, step, STATUS_SUCCESS),
    ).fetchone()


def list_domains() -> list[dict]:
    conn = connect()
    try:
        return rows_to_dicts(conn.execute("SELECT * FROM domains ORDER BY id").fetchall())
    finally:
        conn.close()


def get_domain(domain_id: int) -> dict | None:
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM domains WHERE id=?", (domain_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def layer_rows(table: str, domain_id: int | None = None) -> list[dict]:
    allowed = {
        "paste": "layer_paste",
        "detail": "layer_detail",
        "summary": "layer_summary",
    }
    if table not in allowed:
        raise ValueError("未知分层")
    sql = f"SELECT * FROM {allowed[table]}"
    args: tuple = ()
    if domain_id is not None:
        sql += " WHERE domain_id=?"
        args = (domain_id,)
    sql += " ORDER BY id"
    conn = connect()
    try:
        return rows_to_dicts(conn.execute(sql, args).fetchall())
    finally:
        conn.close()


def layer_counts(domain_id: int | None = None) -> dict:
    conn = connect()
    try:
        where = " WHERE domain_id=?" if domain_id is not None else ""
        args = (domain_id,) if domain_id is not None else ()
        paste = conn.execute(f"SELECT COUNT(*) AS c FROM layer_paste{where}", args).fetchone()["c"]
        detail = conn.execute(f"SELECT COUNT(*) AS c FROM layer_detail{where}", args).fetchone()["c"]
        summary = conn.execute(f"SELECT COUNT(*) AS c FROM layer_summary{where}", args).fetchone()["c"]
        return {
            "贴源层": int(paste),
            "明细层": int(detail),
            "汇总层": int(summary),
        }
    finally:
        conn.close()


def list_jobs(domain_id: int | None = None) -> list[dict]:
    conn = connect()
    try:
        if domain_id is None:
            rows = conn.execute("SELECT * FROM layer_jobs ORDER BY id DESC").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM layer_jobs WHERE domain_id=? ORDER BY id DESC", (domain_id,)
            ).fetchall()
        return [_job_dict(r) for r in rows]
    finally:
        conn.close()


def run_paste_to_detail(domain_id: int) -> dict:
    domain = get_domain(domain_id)
    if not domain:
        raise ValueError("主题域不存在")
    conn = connect()
    try:
        paste = conn.execute(
            "SELECT * FROM layer_paste WHERE domain_id=? ORDER BY id", (domain_id,)
        ).fetchall()
        # 闸：贴源为空时直接失败，绝不触碰明细层
        if not paste:
            return _insert_job(
                conn,
                domain_id,
                "paste_to_detail",
                STATUS_SUCCESS,
                "清洗完成，剔除门店名为空或金额为负的行",
                in_count=0,
                out_count=0,
            )
        cleaned = []
        drop = 0
        for row in paste:
            store_name = (row["store_name"] or "").strip()
            amount = float(row["amount"])
            if not store_name or amount < 0:
                drop += 1
                continue
            cleaned.append(
                (
                    domain_id,
                    row["biz_day"],
                    row["store_code"],
                    store_name,
                    row["category"],
                    amount,
                    int(row["qty"]),
                    "已清洗",
                )
            )
        # 其它业务失败：清洗后无有效行，同样不写半截结果
        if not cleaned:
            return _insert_job(
                conn,
                domain_id,
                "paste_to_detail",
                STATUS_FAILED,
                "业务失败：清洗后无有效明细行，明细层未改写",
                in_count=len(paste),
                out_count=0,
                drop_count=drop,
                fail_code="CLEAN_RESULT_EMPTY",
                fail_reason="全部贴源行都被清洗规则剔除",
            )
        # 通过闸后才在单事务内替换明细层，任务记录与分层写入同生共死
        try:
            conn.execute("DELETE FROM layer_detail WHERE domain_id=?", (domain_id,))
            conn.executemany(
                """
                INSERT INTO layer_detail(
                  domain_id, biz_day, store_code, store_name, category, amount, qty, clean_flag
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                cleaned,
            )
            job = _insert_job(
                conn,
                domain_id,
                "paste_to_detail",
                STATUS_SUCCESS,
                "清洗完成，剔除门店名为空或金额为负的行",
                in_count=len(paste),
                out_count=len(cleaned),
                drop_count=drop,
                commit=False,
            )
            conn.commit()
            return job
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()


def run_detail_to_summary(domain_id: int) -> dict:
    domain = get_domain(domain_id)
    if not domain:
        raise ValueError("主题域不存在")
    conn = connect()
    try:
        last_job = _latest_job(conn, domain_id, "paste_to_detail")
        last_ok = _latest_success_job(conn, domain_id, "paste_to_detail")
        detail = conn.execute(
            "SELECT * FROM layer_detail WHERE domain_id=? ORDER BY id", (domain_id,)
        ).fetchall()
        if last_job is None or last_job["status"] != STATUS_SUCCESS or not detail:
            conn.execute("DELETE FROM layer_summary WHERE domain_id=?", (domain_id,))
        if last_job is None:
            return _insert_job(
                conn,
                domain_id,
                "detail_to_summary",
                STATUS_FAILED,
                "闸失败：尚无贴源到明细任务，上游未就绪",
                fail_code=FAIL_CODE_DETAIL_JOB_MISSING,
                fail_reason="没有可用的贴源到明细任务记录",
            )
        if last_job["status"] != STATUS_SUCCESS:
            upstream_ok_id = int(last_ok["id"]) if last_ok else None
            suffix = f"，最近一次成功任务 #{upstream_ok_id}" if upstream_ok_id else ""
            return _insert_job(
                conn,
                domain_id,
                "detail_to_summary",
                STATUS_FAILED,
                f"闸失败：最近一次贴源到明细任务 #{last_job['id']} 未成功，上游未就绪{suffix}",
                fail_code=FAIL_CODE_DETAIL_JOB_FAILED,
                fail_reason=f"最近一次贴源到明细任务状态为「{last_job['status']}」",
                upstream_job_id=upstream_ok_id,
            )
        if not detail:
            return _insert_job(
                conn,
                domain_id,
                "detail_to_summary",
                STATUS_FAILED,
                f"闸失败：明细层无数据（上游成功任务 #{last_job['id']}）",
                fail_code=FAIL_CODE_DETAIL_EMPTY,
                fail_reason="最近一次贴源到明细任务成功，但明细行数为 0",
                upstream_job_id=int(last_job["id"]),
            )
        buckets: dict[tuple, dict] = {}
        for row in detail:
            key = (row["biz_day"], row["store_code"])
            b = buckets.setdefault(
                key,
                {"biz_day": row["biz_day"], "store_code": row["store_code"], "amount": 0.0, "qty": 0, "n": 0},
            )
            b["amount"] += float(row["amount"])
            b["qty"] += int(row["qty"])
            b["n"] += 1
        try:
            conn.execute("DELETE FROM layer_summary WHERE domain_id=?", (domain_id,))
            conn.executemany(
                """
                INSERT INTO layer_summary(
                  domain_id, biz_day, store_code, amount_sum, qty_sum, line_count
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (domain_id, b["biz_day"], b["store_code"], b["amount"], b["qty"], b["n"])
                    for b in buckets.values()
                ],
            )
            job = _insert_job(
                conn,
                domain_id,
                "detail_to_summary",
                STATUS_SUCCESS,
                "按业务日+门店编码汇总",
                in_count=len(detail),
                out_count=len(buckets),
                upstream_job_id=int(last_job["id"]),
                commit=False,
            )
            conn.commit()
            return job
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()


def run_reconcile(domain_id: int) -> dict:
    domain = get_domain(domain_id)
    if not domain:
        raise ValueError("主题域不存在")
    conn = connect()
    try:
        paste_count = int(
            conn.execute("SELECT COUNT(*) AS c FROM layer_paste WHERE domain_id=?", (domain_id,)).fetchone()[
                "c"
            ]
        )
        detail_count = int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM layer_detail WHERE domain_id=?", (domain_id,)
            ).fetchone()["c"]
        )
        summary = conn.execute(
            "SELECT COALESCE(SUM(line_count),0) AS s, COALESCE(SUM(amount_sum),0) AS a FROM layer_summary WHERE domain_id=?",
            (domain_id,),
        ).fetchone()
        summary_line_sum = int(summary["s"])
        summary_amount = float(summary["a"])
        detail_amount = float(
            conn.execute(
                "SELECT COALESCE(SUM(amount),0) AS a FROM layer_detail WHERE domain_id=?",
                (domain_id,),
            ).fetchone()["a"]
        )
        key_mismatch = 1 if summary_line_sum != detail_count else 0
        amount_drift = round(summary_amount - detail_amount, 4)
        status = "一致" if key_mismatch == 0 and abs(amount_drift) < 0.0001 else "存在差异"
        detail = {
            "贴源行数": paste_count,
            "明细行数": detail_count,
            "汇总行数合计": summary_line_sum,
            "明细金额合计": detail_amount,
            "汇总金额合计": summary_amount,
            "键对齐": key_mismatch == 0,
            "金额漂移": amount_drift,
        }
        cur = conn.execute(
            """
            INSERT INTO reconcile_reports(
              domain_id, paste_count, detail_count, summary_line_sum, key_mismatch, amount_drift, status, detail_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                domain_id,
                paste_count,
                detail_count,
                summary_line_sum,
                key_mismatch,
                amount_drift,
                status,
                json.dumps(detail, ensure_ascii=False),
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM reconcile_reports WHERE id=?", (int(cur.lastrowid),)).fetchone()
        d = dict(row)
        d["detail"] = json.loads(d.pop("detail_json"))
        return d
    finally:
        conn.close()


def list_reconcile(domain_id: int | None = None) -> list[dict]:
    conn = connect()
    try:
        if domain_id is None:
            rows = conn.execute("SELECT * FROM reconcile_reports ORDER BY id DESC").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM reconcile_reports WHERE domain_id=? ORDER BY id DESC",
                (domain_id,),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["detail"] = json.loads(d.pop("detail_json"))
            out.append(d)
        return out
    finally:
        conn.close()


def dashboard() -> dict:
    domains = list_domains()
    counts = layer_counts()
    jobs = list_jobs()[:5]
    reports = list_reconcile()[:5]
    return {
        "主题域数": len(domains),
        "分层计数": counts,
        "最近任务": [
            {
                "编号": j["id"],
                "步骤": j["step_label"],
                "状态": j["status"],
                "写入": j["out_count"],
                "剔除": j["drop_count"],
                "失败类型": j["fail_type"],
                "失败原因": j["fail_reason"] if j["fail_type"] else "",
                "上游成功任务": j["upstream_job_id"],
            }
            for j in jobs
        ],
        "最近对账": [
            {
                "编号": r["id"],
                "状态": r["status"],
                "明细行数": r["detail_count"],
                "汇总行数合计": r["summary_line_sum"],
            }
            for r in reports
        ],
        "主题域": [{"编号": d["id"], "名称": d["name"], "业务键": d["biz_key"]} for d in domains],
    }
