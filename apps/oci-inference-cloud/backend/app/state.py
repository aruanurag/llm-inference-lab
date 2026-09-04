from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import BENCHMARKS_DIR, STATE_DB, ensure_app_dirs


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def connect() -> sqlite3.Connection:
    ensure_app_dirs()
    connection = sqlite3.connect(STATE_DB)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with connect() as db:
        db.executescript(
            """
            create table if not exists settings (
              key text primary key,
              value text not null
            );

            create table if not exists experiments (
              id integer primary key autoincrement,
              name text not null,
              description text not null default '',
              kind text not null default 'cpu-instance',
              source_experiment_id integer,
              status text not null default 'setup',
              created_at text not null,
              updated_at text not null
            );

            create table if not exists ssh_keys (
              id integer primary key autoincrement,
              name text not null unique,
              private_key_path text not null,
              public_key_path text not null,
              public_key text not null,
              created_at text not null
            );

            create table if not exists instances (
              id integer primary key autoincrement,
              experiment_id integer,
              oci_instance_id text not null unique,
              display_name text not null,
              lifecycle_state text,
              shape text not null,
              availability_domain text not null,
              compartment_id text not null,
              subnet_id text not null,
              image_id text not null,
              ssh_key_id integer not null,
              ssh_user text not null,
              public_ip text,
              private_ip text,
              inference_engine text,
              deployed_model_id text,
              deployed_model_name text,
              deployed_model_source text,
              created_at text not null,
              updated_at text not null
            );

            create table if not exists prompt_sets (
              id integer primary key autoincrement,
              name text not null,
              description text not null default '',
              path text not null,
              prompt_count integer not null,
              created_at text not null
            );

            create table if not exists benchmarks (
              id integer primary key autoincrement,
              experiment_id integer,
              instance_id integer not null,
              name text not null,
              summary_path text not null,
              raw_path text not null,
              summary_json text not null,
              created_at text not null
            );

            create table if not exists endpoint_sessions (
              experiment_id integer primary key,
              status text not null,
              local_port integer,
              model_name text not null default 'local-model',
              proxy_url text not null default '',
              started_at text,
              stopped_at text,
              updated_at text not null,
              error text
            );

            create table if not exists endpoint_request_logs (
              id integer primary key autoincrement,
              experiment_id integer not null,
              provider text not null default 'cpu',
              status text not null,
              latency_seconds real not null default 0,
              prompt_chars integer not null default 0,
              output_chars integer not null default 0,
              approx_output_tokens real not null default 0,
              approx_output_tokens_per_second real not null default 0,
              error text,
              created_at text not null
            );

            create table if not exists llmd_benchmarks (
              id integer primary key autoincrement,
              experiment_id integer not null,
              name text not null,
              summary_path text not null,
              raw_path text not null,
              summary_json text not null,
              created_at text not null
            );

            create table if not exists llmd_routing_benchmarks (
              id integer primary key autoincrement,
              experiment_id integer not null,
              name text not null,
              model text not null,
              destination text not null,
              summary_path text not null,
              raw_path text not null,
              summary_json text not null,
              created_at text not null
            );
            """
        )
        columns = {row["name"] for row in db.execute("pragma table_info(instances)").fetchall()}
        if "experiment_id" not in columns:
            db.execute("alter table instances add column experiment_id integer")
        if "inference_engine" not in columns:
            db.execute("alter table instances add column inference_engine text")
        if "deployed_model_id" not in columns:
            db.execute("alter table instances add column deployed_model_id text")
        if "deployed_model_name" not in columns:
            db.execute("alter table instances add column deployed_model_name text")
        if "deployed_model_source" not in columns:
            db.execute("alter table instances add column deployed_model_source text")
        columns = {row["name"] for row in db.execute("pragma table_info(benchmarks)").fetchall()}
        if "experiment_id" not in columns:
            db.execute("alter table benchmarks add column experiment_id integer")
        columns = {row["name"] for row in db.execute("pragma table_info(prompt_sets)").fetchall()}
        if "description" not in columns:
            db.execute("alter table prompt_sets add column description text not null default ''")
        columns = {row["name"] for row in db.execute("pragma table_info(experiments)").fetchall()}
        if "kind" not in columns:
            db.execute("alter table experiments add column kind text not null default 'cpu-instance'")
        if "source_experiment_id" not in columns:
            db.execute("alter table experiments add column source_experiment_id integer")


def set_setting(key: str, value: dict[str, Any]) -> None:
    with connect() as db:
        db.execute(
            "insert into settings(key, value) values (?, ?) "
            "on conflict(key) do update set value = excluded.value",
            (key, json.dumps(value)),
        )


def get_setting(key: str, default: dict[str, Any] | None = None) -> dict[str, Any]:
    with connect() as db:
        row = db.execute("select value from settings where key = ?", (key,)).fetchone()
    if not row:
        return default or {}
    return json.loads(row["value"])


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((pct / 100) * (len(ordered) - 1)))
    return ordered[index]


def insert_experiment(
    name: str,
    description: str = "",
    kind: str = "cpu-instance",
    source_experiment_id: int | None = None,
) -> dict[str, Any]:
    now = utc_now()
    with connect() as db:
        cursor = db.execute(
            "insert into experiments(name, description, kind, source_experiment_id, status, created_at, updated_at) values (?, ?, ?, ?, ?, ?, ?)",
            (name, description, kind, source_experiment_id, "setup", now, now),
        )
        row = db.execute("select * from experiments where id = ?", (cursor.lastrowid,)).fetchone()
    return row_to_dict(row)


def list_experiments() -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute("select * from experiments order by created_at desc").fetchall()
    return [row_to_dict(row) for row in rows]


def get_experiment(experiment_id: int) -> dict[str, Any]:
    with connect() as db:
        row = db.execute("select * from experiments where id = ?", (experiment_id,)).fetchone()
    if not row:
        raise KeyError(f"Experiment not found: {experiment_id}")
    return row_to_dict(row)


def update_experiment(experiment_id: int, **changes: Any) -> dict[str, Any]:
    changes["updated_at"] = utc_now()
    assignments = ", ".join(f"{key} = ?" for key in changes)
    values = list(changes.values())
    values.append(experiment_id)
    with connect() as db:
        db.execute(f"update experiments set {assignments} where id = ?", values)
        row = db.execute("select * from experiments where id = ?", (experiment_id,)).fetchone()
    if not row:
        raise KeyError(f"Experiment not found: {experiment_id}")
    return row_to_dict(row)


def adopt_unassigned_resources(experiment_id: int) -> dict[str, int]:
    get_experiment(experiment_id)
    with connect() as db:
        instance_count = db.execute(
            "update instances set experiment_id = ?, updated_at = ? where experiment_id is null",
            (experiment_id, utc_now()),
        ).rowcount
        benchmark_rows = db.execute("select id, summary_json from benchmarks where experiment_id is null").fetchall()
        benchmark_count = 0
        for row in benchmark_rows:
            summary = json.loads(row["summary_json"])
            summary["experiment_id"] = experiment_id
            db.execute(
                "update benchmarks set experiment_id = ?, summary_json = ? where id = ?",
                (experiment_id, json.dumps(summary), row["id"]),
            )
            benchmark_count += 1

    status = "benchmarked" if benchmark_count else "provisioned" if instance_count else "setup"
    update_experiment(experiment_id, status=status)
    return {"instances": instance_count, "benchmarks": benchmark_count}


def insert_ssh_key(name: str, private_key_path: Path, public_key_path: Path, public_key: str) -> dict[str, Any]:
    created_at = utc_now()
    with connect() as db:
        cursor = db.execute(
            """
            insert into ssh_keys(name, private_key_path, public_key_path, public_key, created_at)
            values (?, ?, ?, ?, ?)
            """,
            (name, str(private_key_path), str(public_key_path), public_key, created_at),
        )
        row = db.execute("select * from ssh_keys where id = ?", (cursor.lastrowid,)).fetchone()
    return row_to_dict(row)


def list_ssh_keys() -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute("select * from ssh_keys order by created_at desc").fetchall()
    return [row_to_dict(row) for row in rows]


def get_ssh_key(key_id: int) -> dict[str, Any]:
    with connect() as db:
        row = db.execute("select * from ssh_keys where id = ?", (key_id,)).fetchone()
    if not row:
        raise KeyError(f"SSH key not found: {key_id}")
    return row_to_dict(row)


def insert_instance(record: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    with connect() as db:
        cursor = db.execute(
            """
            insert into instances(
              oci_instance_id, display_name, lifecycle_state, shape, availability_domain,
              compartment_id, subnet_id, image_id, ssh_key_id, ssh_user, public_ip, private_ip,
              created_at, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["oci_instance_id"],
                record["display_name"],
                record.get("lifecycle_state"),
                record["shape"],
                record["availability_domain"],
                record["compartment_id"],
                record["subnet_id"],
                record["image_id"],
                record["ssh_key_id"],
                record["ssh_user"],
                record.get("public_ip"),
                record.get("private_ip"),
                now,
                now,
            ),
        )
        if record.get("experiment_id"):
            db.execute("update instances set experiment_id = ? where id = ?", (record["experiment_id"], cursor.lastrowid))
        row = db.execute("select * from instances where id = ?", (cursor.lastrowid,)).fetchone()
    return row_to_dict(row)


def update_instance(instance_id: int, **changes: Any) -> dict[str, Any]:
    changes["updated_at"] = utc_now()
    assignments = ", ".join(f"{key} = ?" for key in changes)
    values = list(changes.values())
    values.append(instance_id)
    with connect() as db:
        db.execute(f"update instances set {assignments} where id = ?", values)
        row = db.execute("select * from instances where id = ?", (instance_id,)).fetchone()
    if not row:
        raise KeyError(f"Instance not found: {instance_id}")
    return row_to_dict(row)


def list_instances() -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute("select * from instances order by created_at desc").fetchall()
    return [row_to_dict(row) for row in rows]


def list_instances_for_experiment(experiment_id: int) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute("select * from instances where experiment_id = ? order by created_at desc", (experiment_id,)).fetchall()
    return [row_to_dict(row) for row in rows]


def get_instance(instance_id: int) -> dict[str, Any]:
    with connect() as db:
        row = db.execute("select * from instances where id = ?", (instance_id,)).fetchone()
    if not row:
        raise KeyError(f"Instance not found: {instance_id}")
    return row_to_dict(row)


def insert_prompt_set(name: str, path: Path, prompt_count: int, description: str = "") -> dict[str, Any]:
    created_at = utc_now()
    with connect() as db:
        cursor = db.execute(
            "insert into prompt_sets(name, description, path, prompt_count, created_at) values (?, ?, ?, ?, ?)",
            (name, description, str(path), prompt_count, created_at),
        )
        row = db.execute("select * from prompt_sets where id = ?", (cursor.lastrowid,)).fetchone()
    return row_to_dict(row)


def upsert_prompt_set(name: str, path: Path, prompt_count: int, description: str = "") -> dict[str, Any]:
    created_at = utc_now()
    with connect() as db:
        row = db.execute("select * from prompt_sets where name = ?", (name,)).fetchone()
        if row:
            db.execute(
                "update prompt_sets set description = ?, path = ?, prompt_count = ? where id = ?",
                (description, str(path), prompt_count, row["id"]),
            )
            row = db.execute("select * from prompt_sets where id = ?", (row["id"],)).fetchone()
        else:
            cursor = db.execute(
                "insert into prompt_sets(name, description, path, prompt_count, created_at) values (?, ?, ?, ?, ?)",
                (name, description, str(path), prompt_count, created_at),
            )
            row = db.execute("select * from prompt_sets where id = ?", (cursor.lastrowid,)).fetchone()
    return row_to_dict(row)


def list_prompt_sets() -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute("select * from prompt_sets order by created_at desc").fetchall()
    return [row_to_dict(row) for row in rows]


def get_prompt_set(prompt_set_id: int) -> dict[str, Any]:
    with connect() as db:
        row = db.execute("select * from prompt_sets where id = ?", (prompt_set_id,)).fetchone()
    if not row:
        raise KeyError(f"Prompt set not found: {prompt_set_id}")
    return row_to_dict(row)


def insert_benchmark(instance_id: int, name: str, summary_path: Path, raw_path: Path, summary: dict[str, Any], experiment_id: int | None = None) -> dict[str, Any]:
    created_at = utc_now()
    with connect() as db:
        cursor = db.execute(
            """
            insert into benchmarks(instance_id, name, summary_path, raw_path, summary_json, created_at)
            values (?, ?, ?, ?, ?, ?)
            """,
            (instance_id, name, str(summary_path), str(raw_path), json.dumps(summary), created_at),
        )
        row = db.execute("select * from benchmarks where id = ?", (cursor.lastrowid,)).fetchone()
    result = row_to_dict(row)
    result["summary"] = json.loads(result.pop("summary_json"))
    if experiment_id:
        with connect() as db:
            db.execute("update benchmarks set experiment_id = ? where id = ?", (experiment_id, result["id"]))
            row = db.execute("select * from benchmarks where id = ?", (result["id"],)).fetchone()
        result = row_to_dict(row)
        result["summary"] = json.loads(result.pop("summary_json"))
    return result


def list_benchmarks() -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute("select * from benchmarks order by created_at desc").fetchall()
    results = []
    for row in rows:
        item = row_to_dict(row)
        item["summary"] = json.loads(item.pop("summary_json"))
        results.append(item)
    return results


def list_benchmarks_for_experiment(experiment_id: int) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute("select * from benchmarks where experiment_id = ? order by created_at desc", (experiment_id,)).fetchall()
    results = []
    for row in rows:
        item = row_to_dict(row)
        item["summary"] = json.loads(item.pop("summary_json"))
        results.append(item)
    return results


def insert_llmd_benchmark(experiment_id: int, name: str, summary_path: Path, raw_path: Path, summary: dict[str, Any]) -> dict[str, Any]:
    created_at = utc_now()
    with connect() as db:
        cursor = db.execute(
            "insert into llmd_benchmarks(experiment_id, name, summary_path, raw_path, summary_json, created_at) values (?, ?, ?, ?, ?, ?)",
            (experiment_id, name, str(summary_path), str(raw_path), json.dumps(summary), created_at),
        )
        row = db.execute("select * from llmd_benchmarks where id = ?", (cursor.lastrowid,)).fetchone()
    item = row_to_dict(row)
    item["summary"] = json.loads(item.pop("summary_json"))
    return item


def list_llmd_benchmarks(experiment_id: int) -> list[dict[str, Any]]:
    output_dir = BENCHMARKS_DIR / "llm-d" / str(experiment_id)
    if output_dir.exists():
        with connect() as db:
            recorded_paths = {row["summary_path"] for row in db.execute("select summary_path from llmd_benchmarks where experiment_id = ?", (experiment_id,)).fetchall()}
        for summary_path in output_dir.glob("*-summary.json"):
            if str(summary_path) in recorded_paths:
                continue
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                raw_name = summary_path.name.removesuffix("-summary.json") + ".json"
                raw_path = summary_path.with_name(raw_name)
                if raw_path.exists():
                    insert_llmd_benchmark(experiment_id, str(summary.get("name") or raw_name.removesuffix(".json")), summary_path, raw_path, summary)
            except (OSError, json.JSONDecodeError):
                continue
    with connect() as db:
        rows = db.execute("select * from llmd_benchmarks where experiment_id = ? order by created_at desc", (experiment_id,)).fetchall()
    results = []
    for row in rows:
        item = row_to_dict(row)
        item["summary"] = json.loads(item.pop("summary_json"))
        results.append(item)
    return results


def insert_llmd_routing_benchmark(
    experiment_id: int,
    name: str,
    model: str,
    destination: str,
    summary_path: Path,
    raw_path: Path,
    summary: dict[str, Any],
) -> dict[str, Any]:
    """Persist only benchmark metadata and aggregates, never prompts or provider credentials."""
    created_at = utc_now()
    with connect() as db:
        cursor = db.execute(
            """
            insert into llmd_routing_benchmarks(
              experiment_id, name, model, destination, summary_path, raw_path, summary_json, created_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (experiment_id, name, model, destination, str(summary_path), str(raw_path), json.dumps(summary), created_at),
        )
        row = db.execute("select * from llmd_routing_benchmarks where id = ?", (cursor.lastrowid,)).fetchone()
    item = row_to_dict(row)
    item["summary"] = json.loads(item.pop("summary_json"))
    return item


def list_llmd_routing_benchmarks(experiment_id: int) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute(
            "select * from llmd_routing_benchmarks where experiment_id = ? order by created_at desc",
            (experiment_id,),
        ).fetchall()
    results = []
    for row in rows:
        item = row_to_dict(row)
        item["summary"] = json.loads(item.pop("summary_json"))
        results.append(item)
    return results


def upsert_endpoint_session(
    experiment_id: int,
    *,
    status: str,
    local_port: int | None = None,
    model_name: str = "local-model",
    proxy_url: str = "",
    error: str | None = None,
) -> dict[str, Any]:
    now = utc_now()
    with connect() as db:
        existing = db.execute("select * from endpoint_sessions where experiment_id = ?", (experiment_id,)).fetchone()
        started_at = now if status == "running" and not existing else (existing["started_at"] if existing else None)
        stopped_at = now if status == "stopped" else (existing["stopped_at"] if existing else None)
        db.execute(
            """
            insert into endpoint_sessions(
              experiment_id, status, local_port, model_name, proxy_url, started_at, stopped_at, updated_at, error
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(experiment_id) do update set
              status = excluded.status,
              local_port = excluded.local_port,
              model_name = excluded.model_name,
              proxy_url = excluded.proxy_url,
              started_at = excluded.started_at,
              stopped_at = excluded.stopped_at,
              updated_at = excluded.updated_at,
              error = excluded.error
            """,
            (experiment_id, status, local_port, model_name, proxy_url, started_at, stopped_at, now, error),
        )
        row = db.execute("select * from endpoint_sessions where experiment_id = ?", (experiment_id,)).fetchone()
    return row_to_dict(row)


def get_endpoint_session(experiment_id: int) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute("select * from endpoint_sessions where experiment_id = ?", (experiment_id,)).fetchone()
    return row_to_dict(row) if row else None


def insert_endpoint_request_log(
    experiment_id: int,
    *,
    provider: str = "cpu",
    status: str,
    latency_seconds: float,
    prompt_chars: int,
    output_chars: int,
    error: str | None = None,
) -> dict[str, Any]:
    approx_tokens = output_chars / 4
    approx_tokens_per_second = approx_tokens / latency_seconds if latency_seconds > 0 else 0
    with connect() as db:
        cursor = db.execute(
            """
            insert into endpoint_request_logs(
              experiment_id, provider, status, latency_seconds, prompt_chars, output_chars,
              approx_output_tokens, approx_output_tokens_per_second, error, created_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                experiment_id,
                provider,
                status,
                latency_seconds,
                prompt_chars,
                output_chars,
                approx_tokens,
                approx_tokens_per_second,
                error,
                utc_now(),
            ),
        )
        row = db.execute("select * from endpoint_request_logs where id = ?", (cursor.lastrowid,)).fetchone()
    return row_to_dict(row)


def list_endpoint_request_logs(experiment_id: int) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute(
            "select * from endpoint_request_logs where experiment_id = ? order by created_at desc",
            (experiment_id,),
        ).fetchall()
    return [row_to_dict(row) for row in rows]


def endpoint_analytics(experiment_id: int) -> dict[str, Any]:
    logs = list_endpoint_request_logs(experiment_id)
    latencies = [float(log["latency_seconds"]) for log in logs if log["status"] == "ok"]
    total_latency = sum(float(log["latency_seconds"]) for log in logs if log["status"] == "ok")
    output_chars = sum(int(log["output_chars"]) for log in logs if log["status"] == "ok")
    approx_tokens = sum(float(log["approx_output_tokens"]) for log in logs if log["status"] == "ok")
    return {
        "total_requests": len(logs),
        "successful_requests": sum(1 for log in logs if log["status"] == "ok"),
        "failed_requests": sum(1 for log in logs if log["status"] != "ok"),
        "latency_seconds": {
            "p50": percentile(latencies, 50),
            "p95": percentile(latencies, 95),
        },
        "output_chars": output_chars,
        "output_chars_per_second": output_chars / total_latency if total_latency > 0 else 0,
        "approx_output_tokens": approx_tokens,
        "approx_output_tokens_per_second": approx_tokens / total_latency if total_latency > 0 else 0,
        "logs": logs[:50],
    }
