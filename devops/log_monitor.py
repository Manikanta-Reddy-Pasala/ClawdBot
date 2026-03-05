"""Continuous log monitoring for core services.

Scans logs from default and pos namespaces, detects issues,
creates tickets, dispatches to ClawdBot for auto-fix, and tracks pipeline status.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime

from devops.k8s_client import get_deployment_logs
from devops.patterns import scan_logs

logger = logging.getLogger(__name__)

# Core services to monitor (name -> {namespace, deployment_name})
MONITORED_SERVICES = {
    "PosServerBackend": {"namespace": "default", "deployment": "posserverbackend", "tail": 300},
    "PosClientBackend": {"namespace": "pos", "deployment": "posclientbackend", "tail": 300},
    "MongoDbService": {"namespace": "default", "deployment": "mongodbservice", "tail": 200},
    "GatewayService": {"namespace": "default", "deployment": "gatewayservice", "tail": 200},
    "BusinessService": {"namespace": "default", "deployment": "businessservice", "tail": 200},
    "PosService": {"namespace": "default", "deployment": "posservice", "tail": 200},
    "Scheduler": {"namespace": "default", "deployment": "scheduler", "tail": 150},
    "QuartzScheduler": {"namespace": "default", "deployment": "quartzscheduler", "tail": 150},
    "PosDataSyncService": {"namespace": "default", "deployment": "posdatasyncservice", "tail": 150},
    "PosPythonBackend": {"namespace": "pos", "deployment": "pospythonbackend", "tail": 100},
    "EmailService": {"namespace": "default", "deployment": "emailservice", "tail": 100},
    "NotificationService": {"namespace": "default", "deployment": "notificationservice", "tail": 100},
    "WhatsappApiService": {"namespace": "default", "deployment": "whatsappapiservice", "tail": 100},
}

# In-memory ticket store
_tickets: list[dict] = []
_ticket_counter = 0


async def scan_all_services() -> dict:
    """Scan logs of all core services and return issues found."""
    all_issues = []
    service_summaries = []

    async def _scan_one(name: str, cfg: dict):
        try:
            logs = await get_deployment_logs(cfg["deployment"], cfg["namespace"], cfg["tail"])
            if not logs or "No pods found" in logs:
                service_summaries.append({
                    "name": name,
                    "namespace": cfg["namespace"],
                    "issueCount": 0,
                    "maxSeverity": "OK",
                })
                return

            matches = scan_logs(logs, name)
            issue_count = len(matches)
            max_severity = "OK"
            for m in matches:
                sev = (m.severity.value if hasattr(m.severity, 'value') else str(m.severity)).upper()
                if sev == "CRITICAL":
                    max_severity = "CRITICAL"
                elif sev == "WARNING" and max_severity != "CRITICAL":
                    max_severity = "WARNING"

            service_summaries.append({
                "name": name,
                "namespace": cfg["namespace"],
                "issueCount": issue_count,
                "maxSeverity": max_severity,
            })

            for m in matches:
                sev = (m.severity.value if hasattr(m.severity, 'value') else str(m.severity)).upper()
                all_issues.append({
                    "service": name,
                    "namespace": cfg["namespace"],
                    "severity": sev,
                    "category": m.category,
                    "description": m.description,
                    "matched_line": m.matched_line,
                    "recommendation": m.recommendation,
                    "pattern_name": m.pattern_name,
                })
        except Exception as e:
            logger.error("Failed to scan %s: %s", name, e)
            service_summaries.append({
                "name": name,
                "namespace": cfg["namespace"],
                "issueCount": 0,
                "maxSeverity": "ERROR",
            })

    # Scan all services concurrently
    tasks = [_scan_one(name, cfg) for name, cfg in MONITORED_SERVICES.items()]
    await asyncio.gather(*tasks)

    # Sort: services with issues first, then alphabetical
    service_summaries.sort(key=lambda s: (-s["issueCount"], s["name"]))

    # Sort issues: CRITICAL first, then WARNING, then INFO
    severity_order = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
    all_issues.sort(key=lambda i: severity_order.get(i["severity"], 3))

    return {
        "services": service_summaries,
        "issues": all_issues,
        "total_issues": len(all_issues),
        "scanned_at": datetime.utcnow().isoformat(),
    }


def create_ticket(
    service: str,
    namespace: str,
    severity: str,
    category: str,
    description: str,
    matched_line: str,
    recommendation: str = "",
) -> dict:
    """Create a ticket for a detected issue."""
    global _ticket_counter
    _ticket_counter += 1
    ticket = {
        "id": _ticket_counter,
        "uid": str(uuid.uuid4())[:8],
        "service": service,
        "namespace": namespace,
        "severity": severity,
        "category": category,
        "description": description,
        "matched_line": matched_line,
        "recommendation": recommendation,
        "status": "created",
        "created_at": datetime.utcnow().isoformat(),
        "clawdbot_task_id": None,
        "clawdbot_output": None,
        "mr_url": None,
        "telegram_notified": False,
    }
    _tickets.insert(0, ticket)
    return ticket


def update_ticket(ticket_id: int, updates: dict) -> dict | None:
    """Update a ticket's fields."""
    for t in _tickets:
        if t["id"] == ticket_id:
            t.update(updates)
            return t
    return None


def get_tickets() -> list[dict]:
    """Get all tickets."""
    return _tickets


def get_ticket(ticket_id: int) -> dict | None:
    """Get a single ticket by ID."""
    for t in _tickets:
        if t["id"] == ticket_id:
            return t
    return None


def build_clawdbot_prompt(ticket: dict) -> str:
    """Build the prompt for ClawdBot to investigate and fix the issue."""
    service = ticket["service"]

    # Map service names to repo names
    repo_map = {
        "PosServerBackend": "PosServerBackend",
        "PosClientBackend": "PosClientBackend",
        "MongoDbService": "MongoDbService",
        "GatewayService": "GatewayService",
        "BusinessService": "BusinessService",
        "PosService": "PosService",
        "Scheduler": "Scheduler",
        "QuartzScheduler": "QuartzScheduler",
        "PosDataSyncService": "PosDataSyncService",
        "PosPythonBackend": "PosPythonBackend",
        "EmailService": "EmailService",
        "NotificationService": "NotificationService",
        "WhatsappApiService": "WhatsappApiService",
    }

    repo = repo_map.get(service, service)

    prompt = f"""AUTOMATED ISSUE TICKET #{ticket['id']}

SERVICE: {service}
NAMESPACE: {ticket['namespace']}
SEVERITY: {ticket['severity']}
CATEGORY: {ticket['category']}

ISSUE: {ticket['description']}

LOG LINE: {ticket['matched_line']}

RECOMMENDATION: {ticket.get('recommendation', 'N/A')}

INSTRUCTIONS:
1. Switch to the {repo} repo context
2. Investigate the root cause of this issue by checking logs and code
3. If a code fix is needed:
   a. Make the fix in the codebase
   b. Build and verify it compiles: cd /opt/clawdbot/repos/{repo} && JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64 ./mvnw clean compile -DskipTests
   c. Test by port-forwarding to QA cluster
   d. Create a branch, commit, push, and create a merge request
4. If it's a configuration/infra issue, suggest the kubectl commands to fix it
5. Report back with:
   - Root cause
   - Fix applied (if any)
   - Test results
   - MR URL (if code was changed)
"""
    return prompt
