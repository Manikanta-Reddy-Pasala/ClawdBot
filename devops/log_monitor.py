"""Continuous log monitoring for core services.

Scans logs from default and pos namespaces, detects issues,
creates tickets, dispatches to ClawdBot for auto-fix, and tracks pipeline status.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from devops.k8s_client import get_deployment_logs
from devops.patterns import scan_logs
from devops import ticket_db

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
    "PosDockerPullService": {"namespace": "default", "deployment": "posdockerpullservice", "tail": 100},
    "PosDockerSyncService": {"namespace": "default", "deployment": "posdockersyncservice", "tail": 100},
    "GstApiService": {"namespace": "default", "deployment": "gstapiservice", "tail": 100},
    "PosPythonBackend": {"namespace": "pos", "deployment": "pospythonbackend", "tail": 100},
    "PosNodeBackend": {"namespace": "pos", "deployment": "posnodebackend", "tail": 100},
    "PosFrontend": {"namespace": "pos", "deployment": "posfrontend", "tail": 100},
    "AzureOcr": {"namespace": "pos", "deployment": "azureocr", "tail": 100},
    "EmailService": {"namespace": "default", "deployment": "emailservice", "tail": 100},
    "NotificationService": {"namespace": "default", "deployment": "notificationservice", "tail": 100},
    "WhatsappApiService": {"namespace": "default", "deployment": "whatsappapiservice", "tail": 100},
    "NodeInvoiceThemes": {"namespace": "default", "deployment": "nodeinvoicethemes", "tail": 100},
}

# Tickets are now persisted in SQLite via ticket_db module

# Dedup: track recently seen issues to avoid duplicate tickets
# Key: (service, category, description_prefix) -> last_ticket_time
_seen_issues: dict[tuple, str] = {}
_DEDUP_WINDOW_MINUTES = 30  # Don't create duplicate ticket within this window

# Auto-scan state
_auto_scan_running = False
_auto_scan_task = None
_last_scan_result: dict | None = None


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

    # Group issues by (service, severity, category, description)
    grouped = {}
    for issue in all_issues:
        key = (issue["service"], issue["severity"], issue["category"], issue["description"])
        if key not in grouped:
            grouped[key] = {
                **issue,
                "count": 1,
                "example_lines": [issue["matched_line"]],
            }
        else:
            grouped[key]["count"] += 1
            if len(grouped[key]["example_lines"]) < 3:
                grouped[key]["example_lines"].append(issue["matched_line"])

    grouped_issues = list(grouped.values())

    # Sort issues: CRITICAL first, then WARNING, then INFO, then by count desc
    severity_order = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
    grouped_issues.sort(key=lambda i: (severity_order.get(i["severity"], 3), -i["count"]))

    return {
        "services": service_summaries,
        "issues": grouped_issues,
        "total_issues": sum(i["count"] for i in grouped_issues),
        "unique_issues": len(grouped_issues),
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
    """Create a ticket for a detected issue (persisted in SQLite)."""
    return ticket_db.create_ticket(
        service=service,
        namespace=namespace,
        severity=severity,
        category=category,
        description=description,
        matched_line=matched_line,
        recommendation=recommendation,
    )


def update_ticket(ticket_id: int, updates: dict) -> dict | None:
    """Update a ticket's fields."""
    return ticket_db.update_ticket(ticket_id, updates)


def get_tickets(status: str | None = None, service: str | None = None,
                severity: str | None = None, limit: int = 50) -> list[dict]:
    """Get tickets with optional filters."""
    return ticket_db.get_tickets(status=status, service=service, severity=severity, limit=limit)


def get_ticket(ticket_id: int) -> dict | None:
    """Get a single ticket by ID."""
    return ticket_db.get_ticket(ticket_id)


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
        "PosDockerPullService": "PosDockerPullService",
        "PosDockerSyncService": "PosDockerSyncService",
        "GstApiService": "GstApiService",
        "PosPythonBackend": "PosPythonBackend",
        "PosNodeBackend": "PosNodeBackend",
        "PosFrontend": "PosFrontend",
        "AzureOcr": "Azure-Ocr",
        "EmailService": "EmailService",
        "NotificationService": "NotificationService",
        "WhatsappApiService": "WhatsappApiService",
        "NodeInvoiceThemes": "NodeInvoiceThemes",
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


def _dedup_key(service: str, category: str, description: str) -> tuple:
    """Create a dedup key from issue details."""
    return (service, category, description[:80])


def _is_duplicate(service: str, category: str, description: str) -> bool:
    """Check if this issue already has a recent ticket."""
    key = _dedup_key(service, category, description)
    last_time = _seen_issues.get(key)
    if not last_time:
        return False
    try:
        last_dt = datetime.fromisoformat(last_time)
        elapsed = (datetime.utcnow() - last_dt).total_seconds() / 60
        return elapsed < _DEDUP_WINDOW_MINUTES
    except Exception:
        return False


def _mark_seen(service: str, category: str, description: str):
    """Mark an issue as having a ticket created."""
    key = _dedup_key(service, category, description)
    _seen_issues[key] = datetime.utcnow().isoformat()


def get_last_scan_result() -> dict | None:
    """Return the last auto-scan result (for dashboard polling)."""
    return _last_scan_result


async def auto_scan_loop(dispatch_fn=None, interval_seconds: int = 300):
    """Background loop: scan every interval, auto-create tickets for CRITICAL issues.

    Args:
        dispatch_fn: async callable(ticket) to dispatch ticket to ClawdBot.
        interval_seconds: seconds between scans (default 5 min).
    """
    global _auto_scan_running, _last_scan_result
    _auto_scan_running = True
    logger.info("Auto-scan loop started (interval=%ds)", interval_seconds)

    while _auto_scan_running:
        try:
            result = await scan_all_services()
            _last_scan_result = result

            # Auto-create tickets for CRITICAL issues that haven't been ticketed recently
            for issue in result.get("issues", []):
                if issue["severity"] != "CRITICAL":
                    continue
                if _is_duplicate(issue["service"], issue["category"], issue["description"]):
                    continue

                ticket = create_ticket(
                    service=issue["service"],
                    namespace=issue["namespace"],
                    severity=issue["severity"],
                    category=issue["category"],
                    description=issue["description"],
                    matched_line=issue.get("matched_line", ""),
                    recommendation=issue.get("recommendation", ""),
                )
                _mark_seen(issue["service"], issue["category"], issue["description"])
                logger.info("Auto-created ticket #%d for %s: %s",
                            ticket["id"], issue["service"], issue["description"][:100])

                if dispatch_fn:
                    try:
                        asyncio.create_task(dispatch_fn(ticket))
                    except Exception as e:
                        logger.error("Failed to dispatch ticket #%d: %s", ticket["id"], e)

            logger.info("Auto-scan complete: %d issues, %d services",
                        result.get("total_issues", 0), len(result.get("services", [])))
        except Exception as e:
            logger.error("Auto-scan failed: %s", e)

        await asyncio.sleep(interval_seconds)


def start_auto_scan(dispatch_fn=None, interval_seconds: int = 300):
    """Start the auto-scan background task. Returns the asyncio task."""
    global _auto_scan_task
    if _auto_scan_task and not _auto_scan_task.done():
        logger.warning("Auto-scan already running")
        return _auto_scan_task
    _auto_scan_task = asyncio.create_task(auto_scan_loop(dispatch_fn, interval_seconds))
    return _auto_scan_task


def stop_auto_scan():
    """Stop the auto-scan background task."""
    global _auto_scan_running
    _auto_scan_running = False
    if _auto_scan_task:
        _auto_scan_task.cancel()
