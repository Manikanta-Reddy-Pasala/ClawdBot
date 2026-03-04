"""NATS monitoring via HTTP monitoring API (port 8222) through kubectl port-forward or exec."""
from __future__ import annotations

import asyncio
import json
import logging

from devops import k8s_client

logger = logging.getLogger(__name__)

NATS_NS = "pos"


async def _nats_http(path: str) -> dict:
    """Access NATS monitoring API via kubectl exec curl from a pod with curl."""
    # Use nginx pod in default namespace (has curl) to reach NATS service
    pods = await k8s_client.list_pods("default")
    curl_pods = [p for p in pods if p["name"].startswith("nginx") and p["status"] == "Running"
                 and not p["name"].startswith("nginx-monitor") and not p["name"].startswith("nginx-whatsapp")
                 and not p["name"].startswith("nginx-plane")]
    if not curl_pods:
        return {"error": "No pod with curl found"}

    pod_name = curl_pods[0]["name"]
    raw = await k8s_client.exec_in_pod(
        pod_name, "default",
        ["curl", "-s", f"http://nats-server.{NATS_NS}.svc:8222{path}"],
        timeout=10,
    )
    if not raw:
        return {"error": f"Empty response from NATS monitoring API {path}"}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"error": raw[:300]}


async def get_varz() -> dict:
    return await _nats_http("/varz")


async def get_connz() -> dict:
    return await _nats_http("/connz")


async def get_jsz() -> dict:
    return await _nats_http("/jsz?streams=true&consumers=true")


async def get_all_streams() -> list[dict]:
    jsz = await get_jsz()
    if "error" in jsz:
        return []
    streams = []
    for account in jsz.get("account_details", []):
        for stream in account.get("stream_detail", []):
            streams.append({
                "name": stream.get("name", ""),
                "messages": stream.get("state", {}).get("messages", 0),
                "bytes": stream.get("state", {}).get("bytes", 0),
                "consumer_count": stream.get("state", {}).get("consumer_count", 0),
                "subjects": stream.get("config", {}).get("subjects", []),
            })
    return streams


async def get_all_consumers() -> list[dict]:
    jsz = await get_jsz()
    if "error" in jsz:
        return []
    consumers = []
    for account in jsz.get("account_details", []):
        for stream in account.get("stream_detail", []):
            stream_name = stream.get("name", "")
            for consumer in stream.get("consumer_detail", []):
                consumers.append({
                    "name": consumer.get("name", ""),
                    "stream": stream_name,
                    "num_pending": consumer.get("num_pending", 0),
                    "num_ack_pending": consumer.get("num_ack_pending", 0),
                    "num_redelivered": consumer.get("num_redelivered", 0),
                })
    return consumers


async def get_stream_info(stream_name: str) -> dict:
    jsz = await get_jsz()
    if "error" in jsz:
        return jsz
    for account in jsz.get("account_details", []):
        for stream in account.get("stream_detail", []):
            if stream.get("name") == stream_name:
                return stream
    return {"error": f"Stream {stream_name} not found"}


async def get_healthz() -> dict:
    return await _nats_http("/healthz")
