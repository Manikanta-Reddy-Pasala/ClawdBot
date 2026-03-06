"""Kubernetes client using kubectl subprocess (not Python kubernetes lib).
Designed for VM-based access with kubeconfig files."""
from __future__ import annotations

import asyncio
import json
import logging
import os

logger = logging.getLogger(__name__)

# Default to prod kubeconfig on the VM
KUBECONFIG = os.environ.get("KUBECONFIG_PROD", "/home/clawdbot/.kube/prod-config")
KUBECTL = "kubectl"


def _base_cmd() -> list[str]:
    return [KUBECTL, f"--kubeconfig={KUBECONFIG}", "--insecure-skip-tls-verify"]


async def _run_kubectl(*args, timeout: int = 30, retries: int = 2) -> str:
    cmd = _base_cmd() + list(args)
    last_err = ""
    for attempt in range(1, retries + 1):
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            if proc.returncode != 0:
                last_err = stderr.decode(errors="replace").strip()
                # Retry on transient errors (connection refused, timeout, EOF)
                if attempt < retries and any(s in last_err.lower() for s in (
                    "connection refused", "timed out", "timeout", "eof",
                    "tls handshake", "broken pipe", "connection reset",
                )):
                    logger.warning(f"kubectl transient error (attempt {attempt}/{retries}): {last_err[:200]}")
                    await asyncio.sleep(2 * attempt)
                    continue
                logger.error(f"kubectl error: {last_err[:500]}")
                return ""
            return stdout.decode(errors="replace").strip()
        except asyncio.TimeoutError:
            last_err = f"timed out after {timeout}s"
            if attempt < retries:
                logger.warning(f"kubectl timeout (attempt {attempt}/{retries}): {' '.join(args[:5])}")
                await asyncio.sleep(2 * attempt)
                continue
            logger.error(f"kubectl timed out after {retries} attempts: {' '.join(args[:5])}")
            return ""
        except Exception as e:
            logger.error(f"kubectl failed: {e}")
            return ""
    logger.error(f"kubectl failed after {retries} attempts: {last_err[:200]}")
    return ""


async def _run_kubectl_json(*args, timeout: int = 30) -> dict | list:
    raw = await _run_kubectl(*args, "-o", "json", timeout=timeout)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


async def list_pods(namespace: str = "default") -> list[dict]:
    data = await _run_kubectl_json("get", "pods", "-n", namespace)
    pods = []
    for item in data.get("items", []):
        metadata = item.get("metadata", {})
        status = item.get("status", {})
        container_statuses = status.get("containerStatuses", [])
        restarts = sum(cs.get("restartCount", 0) for cs in container_statuses)
        ready = all(cs.get("ready", False) for cs in container_statuses) if container_statuses else False

        phase = status.get("phase", "Unknown")
        # Check for CrashLoopBackOff in container status
        for cs in container_statuses:
            waiting = cs.get("state", {}).get("waiting", {})
            if waiting.get("reason") in ("CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull"):
                phase = waiting["reason"]
                break

        pods.append({
            "name": metadata.get("name", ""),
            "namespace": namespace,
            "status": phase,
            "ready": ready,
            "restarts": restarts,
            "node": item.get("spec", {}).get("nodeName", ""),
            "start_time": str(status.get("startTime", "")),
        })
    return pods


async def list_deployments(namespace: str = "default") -> list[dict]:
    data = await _run_kubectl_json("get", "deployments", "-n", namespace)
    deployments = []
    for item in data.get("items", []):
        spec = item.get("spec", {})
        status = item.get("status", {})
        deployments.append({
            "name": item.get("metadata", {}).get("name", ""),
            "namespace": namespace,
            "replicas": spec.get("replicas", 0),
            "ready_replicas": status.get("readyReplicas", 0),
            "available_replicas": status.get("availableReplicas", 0),
            "updated_replicas": status.get("updatedReplicas", 0),
        })
    return deployments


async def get_events(namespace: str = "default", limit: int = 50) -> list[dict]:
    raw = await _run_kubectl(
        "get", "events", "-n", namespace,
        "--sort-by=.lastTimestamp",
        f"--field-selector=type=Warning",
        "-o", "json",
    )
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []

    events = []
    for item in data.get("items", [])[-limit:]:
        events.append({
            "type": item.get("type", ""),
            "reason": item.get("reason", ""),
            "message": item.get("message", "")[:500],
            "object": item.get("involvedObject", {}).get("name", ""),
            "namespace": namespace,
            "count": item.get("count", 1),
            "last_seen": item.get("lastTimestamp", ""),
        })
    return events


async def get_pod_logs(name: str, namespace: str = "default", tail_lines: int = 200) -> str:
    return await _run_kubectl(
        "logs", name, "-n", namespace,
        f"--tail={tail_lines}",
        timeout=15,
    )


async def get_deployment_logs(deployment: str, namespace: str = "default", tail_lines: int = 200) -> str:
    """Get logs from first pod of a deployment."""
    pods = await list_pods(namespace)
    dep_pods = [p for p in pods if p["name"].startswith(deployment)]
    if not dep_pods:
        return f"No pods found for deployment {deployment}"
    return await get_pod_logs(dep_pods[0]["name"], namespace, tail_lines)


async def get_previous_logs(name: str, namespace: str = "default", tail_lines: int = 100) -> str:
    return await _run_kubectl(
        "logs", name, "-n", namespace,
        "--previous", f"--tail={tail_lines}",
        timeout=15,
    )


async def restart_deployment(name: str, namespace: str) -> bool:
    result = await _run_kubectl(
        "rollout", "restart", f"deployment/{name}", "-n", namespace,
    )
    return bool(result)


async def get_nodes() -> list[dict]:
    data = await _run_kubectl_json("get", "nodes")
    # Also get resource usage via kubectl top nodes
    top_raw = await _run_kubectl("top", "nodes", "--no-headers")
    top_map = {}
    for line in top_raw.splitlines():
        parts = line.split()
        if len(parts) >= 5:
            # name cpu(cores) cpu% memory(bytes) memory%
            top_map[parts[0]] = {
                "cpu_used": parts[1],
                "cpu_percent": int(parts[2].rstrip("%")) if parts[2].endswith("%") else 0,
                "memory_used": parts[3],
                "memory_percent": int(parts[4].rstrip("%")) if parts[4].endswith("%") else 0,
            }

    nodes = []
    for item in data.get("items", []):
        conditions = {}
        for cond in item.get("status", {}).get("conditions", []):
            conditions[cond.get("type", "")] = cond.get("status", "")
        capacity = item.get("status", {}).get("capacity", {})
        name = item.get("metadata", {}).get("name", "")
        top = top_map.get(name, {})

        # Parse capacity
        cpu_cap = capacity.get("cpu", "0")
        cpu_cap_milli = int(cpu_cap) * 1000 if cpu_cap.isdigit() else 0
        mem_cap = capacity.get("memory", "0")
        mem_cap_mib = _parse_memory_ki(mem_cap)

        cpu_pct = top.get("cpu_percent", 0)
        mem_pct = top.get("memory_percent", 0)

        nodes.append({
            "name": name,
            "ready": conditions.get("Ready") == "True",
            "cpu_capacity": cpu_cap,
            "cpu_capacity_millicores": cpu_cap_milli,
            "cpu_used_millicores": round(cpu_cap_milli * cpu_pct / 100) if cpu_pct else 0,
            "cpu_percent": cpu_pct,
            "memory_capacity": mem_cap,
            "memory_capacity_mib": mem_cap_mib,
            "memory_used_mib": round(mem_cap_mib * mem_pct / 100) if mem_pct else 0,
            "memory_percent": mem_pct,
            "conditions": conditions,
        })
    return nodes


def _parse_memory_ki(mem_str: str) -> int:
    """Parse Kubernetes memory string (e.g. '16384Ki', '8Gi') to MiB."""
    if mem_str.endswith("Ki"):
        return int(mem_str[:-2]) // 1024
    elif mem_str.endswith("Mi"):
        return int(mem_str[:-2])
    elif mem_str.endswith("Gi"):
        return int(mem_str[:-2]) * 1024
    return 0


async def exec_in_pod(pod: str, namespace: str, command: list[str], timeout: int = 30) -> str:
    """Execute a command inside a pod."""
    return await _run_kubectl(
        "exec", "-n", namespace, pod, "--", *command,
        timeout=timeout,
    )


async def get_top_pods(namespace: str = "default") -> list[dict]:
    """Get resource usage from kubectl top pods."""
    raw = await _run_kubectl("top", "pods", "-n", namespace, "--no-headers")
    pods = []
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) >= 3:
            pods.append({
                "name": parts[0],
                "cpu": parts[1],
                "memory": parts[2],
            })
    return pods
