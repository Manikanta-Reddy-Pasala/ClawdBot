"""Execute playbook actions with risk-based approval."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime

from devops import k8s_client, mongodb_client, nats_client
from devops.models import (
    Playbook, RemediationAction, RiskLevel, ActionStatus,
)
from devops.playbooks import get_playbook, get_all_playbooks
from devops.event_bus import event_bus

logger = logging.getLogger(__name__)

# Track execution history
execution_history: list[dict] = []


async def execute_playbook(playbook_name: str, context: dict | None = None,
                           dry_run: bool = False) -> dict:
    """Execute a playbook's actions sequentially."""
    playbook = get_playbook(playbook_name)
    if not playbook:
        return {"error": f"Playbook '{playbook_name}' not found"}

    # Check cooldown
    if playbook.last_executed:
        elapsed = (datetime.utcnow() - playbook.last_executed).total_seconds() / 60
        if elapsed < playbook.cooldown_minutes:
            return {
                "error": f"Cooldown active. {playbook.cooldown_minutes - int(elapsed)} minutes remaining",
                "playbook": playbook_name,
            }

    results = []
    for action in playbook.actions:
        result = await execute_action(action, context or {}, dry_run=dry_run)
        results.append(result)
        if result.get("status") == "failed":
            break

    playbook.last_executed = datetime.utcnow()

    record = {
        "playbook": playbook_name,
        "dry_run": dry_run,
        "results": results,
        "executed_at": datetime.utcnow().isoformat(),
    }
    execution_history.append(record)
    return record


async def execute_action(action: RemediationAction, context: dict,
                         dry_run: bool = False) -> dict:
    """Execute a single remediation action."""
    result = {
        "name": action.name,
        "description": action.description,
        "risk_level": action.risk_level.value,
        "dry_run": dry_run,
    }

    if dry_run:
        result["status"] = "dry_run"
        result["message"] = f"Would execute: {action.description}"
        if action.command:
            result["command"] = action.command
        return result

    start = time.time()
    try:
        output = await _execute_action_impl(action, context)
        result["status"] = "completed"
        result["output"] = output
        result["duration_ms"] = int((time.time() - start) * 1000)
    except Exception as e:
        result["status"] = "failed"
        result["error"] = str(e)
        result["duration_ms"] = int((time.time() - start) * 1000)

    return result


async def _execute_action_impl(action: RemediationAction, context: dict) -> str:
    """Route action to appropriate handler."""
    name = action.name

    # MongoDB actions
    if name == "check_connections":
        status = await mongodb_client.get_server_status()
        conns = status.get("connections", {})
        return f"Current: {conns.get('current', '?')}, Available: {conns.get('available', '?')}, Active: {conns.get('active', '?')}"

    if name == "kill_sessions":
        return await mongodb_client.kill_all_sessions()

    # K8s actions
    if name == "fetch_logs":
        service = context.get("service", context.get("resource", ""))
        namespace = context.get("namespace", "default")
        if service:
            return await k8s_client.get_deployment_logs(service, namespace, 200)
        return "No service specified in context"

    if name in ("rolling_restart", "restart_affected_service", "restart_posserverbackend"):
        service = context.get("service", context.get("resource", ""))
        namespace = context.get("namespace", "default")
        if name == "restart_posserverbackend":
            service = "posserverbackend"
        if service:
            ok = await k8s_client.restart_deployment(service, namespace)
            return f"Rolling restart {'initiated' if ok else 'FAILED'} for {service}/{namespace}"
        return "No service specified"

    # NATS actions
    if name == "check_consumer":
        consumers = await nats_client.get_all_consumers()
        return "\n".join(
            f"{c['name']} ({c['stream']}): pending={c['num_pending']}, redelivered={c['num_redelivered']}"
            for c in consumers
        )

    if name == "check_dlq":
        stream = await nats_client.get_stream_info("changestream-dlq")
        msgs = stream.get("state", {}).get("messages", 0) if "state" in stream else stream.get("messages", 0)
        return f"DLQ messages: {msgs}"

    # Redis/Dragonfly actions (via kubectl exec)
    if name in ("check_locks", "check_dragonfly", "list_blocks", "clear_expired_blocks", "clear_tokens"):
        return await _dragonfly_action(name, context)

    # Debezium actions
    if name == "check_debezium":
        raw = await k8s_client.exec_in_pod(
            "debezium-connect-0", "kafka",
            ["curl", "-s", "http://localhost:8083/connectors/oneshell-mongodb-connector/status"],
            timeout=10,
        )
        return raw or "No response from Debezium"

    if name == "restart_debezium_task":
        raw = await k8s_client.exec_in_pod(
            "debezium-connect-0", "kafka",
            ["curl", "-s", "-X", "POST",
             "http://localhost:8083/connectors/oneshell-mongodb-connector/tasks/0/restart"],
            timeout=10,
        )
        return raw or "Restart command sent"

    # Cert actions
    if name == "check_certs":
        return await k8s_client._run_kubectl("get", "certificates", "-A")

    if name == "check_redpanda":
        raw = await k8s_client.exec_in_pod(
            "redpanda-0", "kafka",
            ["curl", "-s", "http://localhost:9644/v1/status/ready"],
            timeout=10,
        )
        return raw or "No response from Redpanda"

    # Generic command execution
    if action.command:
        if action.command.startswith("kubectl"):
            parts = action.command.split()
            return await k8s_client._run_kubectl(*parts[1:])
        if action.command.startswith("db.") or action.command.startswith("redis"):
            return await mongodb_client._mongosh(f"JSON.stringify({action.command})")

    return f"No handler for action: {name}"


async def _dragonfly_action(name: str, context: dict) -> str:
    """Execute Dragonfly/Redis operations via kubectl exec."""
    # Find dragonfly pod
    pods = await k8s_client.list_pods("default")
    df_pods = [p for p in pods if p["name"].startswith("dragonfly") and p["status"] == "Running"]
    if not df_pods:
        return "No running Dragonfly pods found"

    pod = df_pods[0]["name"]

    if name == "check_locks":
        return await k8s_client.exec_in_pod(
            pod, "default", ["redis-cli", "keys", "lock:posserverbackend:*"]
        )
    if name == "check_dragonfly":
        return await k8s_client.exec_in_pod(
            pod, "default", ["redis-cli", "info", "memory"]
        )
    if name == "list_blocks":
        return await k8s_client.exec_in_pod(
            pod, "default", ["redis-cli", "keys", "ratelimit:block:*"]
        )
    if name == "clear_expired_blocks":
        # Only clear blocks - Dragonfly handles TTL expiry
        return await k8s_client.exec_in_pod(
            pod, "default", ["redis-cli", "keys", "ratelimit:block:*"]
        )
    if name == "clear_tokens":
        return await k8s_client.exec_in_pod(
            pod, "default",
            ["sh", "-c", "redis-cli keys 'changestream:resume-token:*' | xargs -r redis-cli del"],
        )
    if name == "unblock_business":
        biz_id = context.get("business_id", "")
        if not biz_id:
            return "No business_id in context"
        return await k8s_client.exec_in_pod(
            pod, "default", ["redis-cli", "del", f"ratelimit:block:{biz_id}"]
        )
    return f"Unknown dragonfly action: {name}"


def get_execution_history(limit: int = 20) -> list[dict]:
    return execution_history[-limit:]
