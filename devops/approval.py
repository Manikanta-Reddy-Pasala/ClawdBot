"""Approval workflow via Telegram inline keyboard and API."""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime

from devops.models import RiskLevel
from devops.event_bus import event_bus

logger = logging.getLogger(__name__)

# Pending approvals: approval_id -> approval_request
pending_approvals: dict[str, dict] = {}


def create_approval(playbook_name: str, action_name: str, risk_level: RiskLevel,
                    description: str, context: dict | None = None) -> dict:
    """Create an approval request."""
    approval_id = str(uuid.uuid4())[:8]
    approval = {
        "id": approval_id,
        "playbook": playbook_name,
        "action": action_name,
        "risk_level": risk_level.value,
        "description": description,
        "context": context or {},
        "status": "pending",
        "created_at": datetime.utcnow().isoformat(),
        "decided_at": None,
        "decided_by": None,
    }
    pending_approvals[approval_id] = approval
    event_bus.emit_nowait("approval_requested", approval=approval)
    return approval


def approve(approval_id: str, decided_by: str = "user") -> dict | None:
    """Approve a pending request."""
    approval = pending_approvals.get(approval_id)
    if not approval or approval["status"] != "pending":
        return None
    approval["status"] = "approved"
    approval["decided_at"] = datetime.utcnow().isoformat()
    approval["decided_by"] = decided_by
    event_bus.emit_nowait("approval_decided", approval=approval)
    return approval


def reject(approval_id: str, decided_by: str = "user") -> dict | None:
    """Reject a pending request."""
    approval = pending_approvals.get(approval_id)
    if not approval or approval["status"] != "pending":
        return None
    approval["status"] = "rejected"
    approval["decided_at"] = datetime.utcnow().isoformat()
    approval["decided_by"] = decided_by
    event_bus.emit_nowait("approval_decided", approval=approval)
    return approval


def get_pending() -> list[dict]:
    return [a for a in pending_approvals.values() if a["status"] == "pending"]


def get_all(limit: int = 20) -> list[dict]:
    return sorted(
        pending_approvals.values(),
        key=lambda a: a["created_at"],
        reverse=True,
    )[:limit]
