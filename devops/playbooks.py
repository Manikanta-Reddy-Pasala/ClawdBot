"""Predefined remediation playbooks for automated incident response."""
from __future__ import annotations

import re
import logging

from devops.models import Playbook, RemediationAction, RiskLevel

logger = logging.getLogger(__name__)

PLAYBOOKS: dict[str, Playbook] = {
    "mongodb_connection_exhaustion": Playbook(
        name="mongodb_connection_exhaustion",
        description="Handle MongoDB connection pool exhaustion causing API timeouts",
        trigger_pattern="MongoTimeoutException|MongoSocketOpenException|connection_critical",
        severity="critical",
        requires_approval=True,
        cooldown_minutes=30,
        actions=[
            RemediationAction(
                name="check_connections",
                description="Check current MongoDB connection count",
                command="db.serverStatus().connections",
                risk_level=RiskLevel.LOW,
            ),
            RemediationAction(
                name="kill_sessions",
                description="Kill all MongoDB logical sessions to free connections",
                command="db.adminCommand({killAllSessions: []})",
                risk_level=RiskLevel.MEDIUM,
            ),
            RemediationAction(
                name="restart_affected_service",
                description="Rolling restart the affected service to reset connection pools",
                risk_level=RiskLevel.MEDIUM,
            ),
        ],
    ),
    "pod_crash_loop": Playbook(
        name="pod_crash_loop",
        description="Handle pod CrashLoopBackOff by analyzing logs and restarting",
        trigger_pattern="CrashLoopBackOff|crash_loop",
        severity="critical",
        requires_approval=True,
        cooldown_minutes=15,
        actions=[
            RemediationAction(
                name="fetch_logs",
                description="Fetch recent pod logs for AI analysis",
                risk_level=RiskLevel.LOW,
            ),
            RemediationAction(
                name="ai_analysis",
                description="Run Claude AI analysis on logs to identify root cause",
                risk_level=RiskLevel.LOW,
            ),
            RemediationAction(
                name="rolling_restart",
                description="Rolling restart the deployment",
                risk_level=RiskLevel.MEDIUM,
            ),
        ],
    ),
    "nats_consumer_stuck": Playbook(
        name="nats_consumer_stuck",
        description="Handle NATS consumer with high pending count",
        trigger_pattern="nats_consumer_lag|SlowConsumer",
        severity="warning",
        requires_approval=True,
        cooldown_minutes=30,
        actions=[
            RemediationAction(
                name="check_consumer",
                description="Check consumer status and pending count",
                risk_level=RiskLevel.LOW,
            ),
            RemediationAction(
                name="check_dlq",
                description="Check DLQ for related failed messages",
                risk_level=RiskLevel.LOW,
            ),
            RemediationAction(
                name="reset_consumer",
                description="Reset the stuck consumer (app will recreate)",
                risk_level=RiskLevel.HIGH,
            ),
        ],
    ),
    "sync_lock_contention": Playbook(
        name="sync_lock_contention",
        description="Handle sync lock timeouts causing sync failures",
        trigger_pattern="lock.*timeout|lock.*acquisition.*failed|SyncLock",
        severity="warning",
        requires_approval=True,
        cooldown_minutes=15,
        actions=[
            RemediationAction(
                name="check_locks",
                description="Check Redis for active sync locks",
                command="redis-cli keys 'lock:posserverbackend:*'",
                risk_level=RiskLevel.LOW,
            ),
            RemediationAction(
                name="force_release",
                description="Force-release stale locks older than 10 minutes",
                risk_level=RiskLevel.HIGH,
            ),
        ],
    ),
    "change_stream_history_lost": Playbook(
        name="change_stream_history_lost",
        description="Handle expired change stream resume tokens",
        trigger_pattern="ChangeStreamHistoryLost|history.*lost",
        severity="critical",
        requires_approval=True,
        cooldown_minutes=60,
        actions=[
            RemediationAction(
                name="clear_tokens",
                description="Clear all change stream resume tokens from Redis",
                command="redis-cli del changestream:resume-token:*",
                risk_level=RiskLevel.MEDIUM,
            ),
            RemediationAction(
                name="restart_posserverbackend",
                description="Rolling restart PosServerBackend to rebuild change streams",
                risk_level=RiskLevel.MEDIUM,
            ),
        ],
    ),
    "debezium_task_failure": Playbook(
        name="debezium_task_failure",
        description="Handle Debezium connector task failure",
        trigger_pattern="debezium.*task.*failed|connector.*FAILED|Debezium",
        severity="critical",
        requires_approval=False,
        cooldown_minutes=10,
        actions=[
            RemediationAction(
                name="check_debezium",
                description="Check Debezium connector status via REST API",
                risk_level=RiskLevel.LOW,
            ),
            RemediationAction(
                name="restart_debezium_task",
                description="Restart the failed Debezium task",
                risk_level=RiskLevel.LOW,
            ),
        ],
    ),
    "redpanda_broker_down": Playbook(
        name="redpanda_broker_down",
        description="Handle Redpanda broker health issues",
        trigger_pattern="Redpanda|kafka.*disconnect|broker.*not.*available",
        severity="critical",
        requires_approval=True,
        cooldown_minutes=30,
        actions=[
            RemediationAction(
                name="check_redpanda",
                description="Check Redpanda broker status via Admin API",
                risk_level=RiskLevel.LOW,
            ),
            RemediationAction(
                name="rolling_restart",
                description="Rolling restart Redpanda StatefulSet",
                command="kubectl rollout restart statefulset/redpanda -n kafka --insecure-skip-tls-verify",
                risk_level=RiskLevel.HIGH,
            ),
        ],
    ),
    "certificate_expiring": Playbook(
        name="certificate_expiring",
        description="Handle expiring TLS certificates (cert-manager + GoDaddy)",
        trigger_pattern="certificate.*expir|cert.*expir|Certificate",
        severity="warning",
        requires_approval=True,
        cooldown_minutes=1440,
        actions=[
            RemediationAction(
                name="check_certs",
                description="Check all certificate statuses and expiry dates",
                risk_level=RiskLevel.LOW,
            ),
            RemediationAction(
                name="trigger_renewal",
                description="Delete TLS secret to trigger cert-manager re-issuance via GoDaddy DNS-01",
                risk_level=RiskLevel.MEDIUM,
            ),
        ],
    ),
    "dragonfly_memory_critical": Playbook(
        name="dragonfly_memory_critical",
        description="Handle Dragonfly/Redis memory pressure or connection issues",
        trigger_pattern="redis.*OOM|dragonfly.*memory|Redis|dragonfly_memory_critical",
        severity="critical",
        requires_approval=True,
        cooldown_minutes=30,
        actions=[
            RemediationAction(
                name="check_dragonfly",
                description="Check Dragonfly INFO stats - memory, connections, keys",
                risk_level=RiskLevel.LOW,
            ),
            RemediationAction(
                name="clear_expired_blocks",
                description="Clear any expired rate-limit blocks from Dragonfly",
                risk_level=RiskLevel.LOW,
            ),
            RemediationAction(
                name="rolling_restart",
                description="Rolling restart Dragonfly deployment",
                command="kubectl rollout restart deployment/dragonfly -n default --insecure-skip-tls-verify",
                risk_level=RiskLevel.HIGH,
            ),
        ],
    ),
    "rate_limit_block": Playbook(
        name="rate_limit_block",
        description="Handle NATS rate-limit business blocks in Dragonfly",
        trigger_pattern="ratelimit.*block|business.*blocked|RateLimit",
        severity="warning",
        requires_approval=True,
        cooldown_minutes=15,
        actions=[
            RemediationAction(
                name="list_blocks",
                description="List all currently blocked businesses and their TTLs",
                risk_level=RiskLevel.LOW,
            ),
            RemediationAction(
                name="unblock_business",
                description="Remove rate-limit block for specific business (requires business_id in context)",
                risk_level=RiskLevel.MEDIUM,
            ),
        ],
    ),
}


def get_playbook(name: str) -> Playbook | None:
    return PLAYBOOKS.get(name)


def get_all_playbooks() -> list[Playbook]:
    return list(PLAYBOOKS.values())


def match_playbook(pattern: str) -> Playbook | None:
    for playbook in PLAYBOOKS.values():
        if re.search(playbook.trigger_pattern, pattern, re.IGNORECASE):
            return playbook
    return None
