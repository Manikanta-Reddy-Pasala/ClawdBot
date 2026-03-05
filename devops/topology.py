"""Service topology with verified ports, health endpoints, and auto-derived relationships."""
from __future__ import annotations

import logging

from devops.models import ServiceInfo, ServiceTier, ServiceTopology

logger = logging.getLogger(__name__)

SERVICE_TOPOLOGY: dict[str, ServiceInfo] = {
    # --- Critical (core POS flow) ---
    "MongoDbService": ServiceInfo(
        name="MongoDbService", namespace="default", port=8080,
        tier=ServiceTier.CRITICAL, dependencies=[],
        health_path="/actuator/health",
    ),
    "PosServerBackend": ServiceInfo(
        name="PosServerBackend", namespace="default", port=8091,
        tier=ServiceTier.CRITICAL, replicas=3,
        dependencies=["MongoDbService", "nats-server"],
        health_path="/actuator/health",
    ),
    "PosClientBackend": ServiceInfo(
        name="PosClientBackend", namespace="pos", port=8090,
        tier=ServiceTier.CRITICAL,
        dependencies=["MongoDbService", "nats-server", "PosServerBackend"],
        health_path="/actuator/health",
    ),
    "GatewayService": ServiceInfo(
        name="GatewayService", namespace="default", port=9090,
        tier=ServiceTier.CRITICAL, dependencies=[],
        health_path="/health",
    ),
    # --- Important ---
    "BusinessService": ServiceInfo(
        name="BusinessService", namespace="default", port=8092,
        tier=ServiceTier.IMPORTANT,
        dependencies=["MongoDbService", "GatewayService"],
        health_path="/health",
    ),
    "PosService": ServiceInfo(
        name="PosService", namespace="default", port=8081,
        tier=ServiceTier.IMPORTANT, dependencies=["MongoDbService"],
        health_path="/health",
    ),
    "Scheduler": ServiceInfo(
        name="Scheduler", namespace="default", port=8100,
        tier=ServiceTier.IMPORTANT,
        dependencies=["MongoDbService"],
        health_path="/health",
    ),
    "QuartzScheduler": ServiceInfo(
        name="QuartzScheduler", namespace="default", port=8080,
        tier=ServiceTier.IMPORTANT,
        dependencies=["MongoDbService"],
        health_path="/actuator/health",
    ),
    # --- Standard (supporting services) ---
    "EmailService": ServiceInfo(
        name="EmailService", namespace="default", port=8098,
        tier=ServiceTier.STANDARD, dependencies=["MongoDbService"],
        health_path="/health",
    ),
    "NotificationService": ServiceInfo(
        name="NotificationService", namespace="default", port=8097,
        tier=ServiceTier.STANDARD, dependencies=["MongoDbService"],
        health_path="/actuator/health",
    ),
    "WhatsappApiService": ServiceInfo(
        name="WhatsappApiService", namespace="default", port=8080,
        tier=ServiceTier.STANDARD, dependencies=["MongoDbService"],
        health_path="/actuator/health",
    ),
    "GstApiService": ServiceInfo(
        name="GstApiService", namespace="default", port=8080,
        tier=ServiceTier.STANDARD, dependencies=["MongoDbService"],
        health_path="/actuator/health",
    ),
    "PosDataSyncService": ServiceInfo(
        name="PosDataSyncService", namespace="default", port=8080,
        tier=ServiceTier.STANDARD,
        dependencies=["MongoDbService", "PosServerBackend"],
        health_path="/actuator/health",
    ),
    "PosDockerPullService": ServiceInfo(
        name="PosDockerPullService", namespace="default", port=8093,
        tier=ServiceTier.STANDARD, replicas=2,
        dependencies=["MongoDbService"],
        health_path="/actuator/health",
    ),
    "PosDockerSyncService": ServiceInfo(
        name="PosDockerSyncService", namespace="default", port=8092,
        tier=ServiceTier.STANDARD, replicas=2,
        dependencies=["MongoDbService"],
        health_path="/actuator/health",
    ),
    "mongoeventlistner": ServiceInfo(
        name="mongoeventlistner", namespace="default", port=8098,
        tier=ServiceTier.STANDARD, dependencies=["MongoDbService"],
        health_path="/actuator/health",
    ),
    "authservice": ServiceInfo(
        name="authservice", namespace="default", port=8080,
        tier=ServiceTier.STANDARD, dependencies=["MongoDbService"],
        health_path="/actuator/health",
    ),
    "nodeinvoicethemes": ServiceInfo(
        name="nodeinvoicethemes", namespace="default", port=3030,
        tier=ServiceTier.STANDARD, dependencies=[],
        health_path="/health",
    ),
    "PosAdmin": ServiceInfo(
        name="PosAdmin", namespace="default", port=80,
        tier=ServiceTier.STANDARD, dependencies=["GatewayService"],
        health_path="/",
    ),
    "PosHome": ServiceInfo(
        name="PosHome", namespace="default", port=80,
        tier=ServiceTier.STANDARD, dependencies=[],
        health_path="/",
    ),
    "PosPythonBackend": ServiceInfo(
        name="PosPythonBackend", namespace="pos", port=5100,
        tier=ServiceTier.STANDARD, dependencies=["PosClientBackend"],
        health_path="/",
    ),
    "PosFrontend": ServiceInfo(
        name="PosFrontend", namespace="pos", port=80,
        tier=ServiceTier.IMPORTANT, dependencies=["PosClientBackend", "GatewayService"],
        health_path="/",
    ),
    "PosNodeBackend": ServiceInfo(
        name="PosNodeBackend", namespace="pos", port=3001,
        tier=ServiceTier.STANDARD,
        dependencies=["PosClientBackend"],
        health_path="/health",
    ),
    "AzureOCR": ServiceInfo(
        name="AzureOCR", namespace="pos", port=8000,
        tier=ServiceTier.STANDARD, dependencies=[],
        health_path="/health",
    ),
    "Typesense": ServiceInfo(
        name="Typesense", namespace="pos", port=8108,
        tier=ServiceTier.STANDARD, dependencies=[],
        health_path="/health",
    ),
    # --- Infrastructure ---
    "nats-server": ServiceInfo(
        name="nats-server", namespace="pos", port=8222,
        tier=ServiceTier.CRITICAL, health_path="/healthz",
    ),
    "redpanda": ServiceInfo(
        name="redpanda", namespace="kafka", port=9644,
        tier=ServiceTier.IMPORTANT, health_path="/v1/status/ready",
    ),
    "debezium-connect": ServiceInfo(
        name="debezium-connect", namespace="kafka", port=8083,
        tier=ServiceTier.IMPORTANT,
        dependencies=["redpanda"],
        health_path="/",
    ),
}


# Known dependency patterns for auto-derivation.
# Maps a pattern found in service configs/code to an infrastructure dependency.
_INFRA_PATTERNS = {
    "mongodb": "MongoDbService",
    "nats": "nats-server",
    "redis": "dragonfly",
    "dragonfly": "dragonfly",
    "gateway": "GatewayService",
    "redpanda": "redpanda",
    "kafka": "redpanda",
}


def build_topology() -> ServiceTopology:
    """Build topology with edges derived from explicit dependencies."""
    edges = []
    seen = set()
    for name, info in SERVICE_TOPOLOGY.items():
        for dep in info.dependencies:
            key = f"{name}->{dep}"
            if key not in seen and dep in SERVICE_TOPOLOGY:
                edges.append({"from": name, "to": dep})
                seen.add(key)
    return ServiceTopology(
        services=list(SERVICE_TOPOLOGY.values()),
        edges=edges,
    )


def get_reverse_dependencies() -> dict[str, list[str]]:
    """Build reverse dependency map: service -> list of services that depend on it."""
    rev = {}
    for name, info in SERVICE_TOPOLOGY.items():
        for dep in info.dependencies:
            if dep not in rev:
                rev[dep] = []
            rev[dep].append(name)
    return rev


def get_dependency_chain(service_name: str) -> list[str]:
    """Get full downstream dependency chain for a service (BFS)."""
    rev = get_reverse_dependencies()
    visited = set()
    queue = [service_name]
    chain = []
    while queue:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        chain.append(current)
        for dependent in rev.get(current, []):
            if dependent not in visited:
                queue.append(dependent)
    return chain[1:]  # Exclude the service itself
