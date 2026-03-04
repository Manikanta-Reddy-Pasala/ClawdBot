"""Automatic incident -> playbook matching and execution."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from devops.models import Incident, Severity, RiskLevel
from devops.playbooks import match_playbook
from devops.remediation import execute_playbook
from devops.approval import create_approval
from devops.event_bus import event_bus

logger = logging.getLogger(__name__)

# Track cooldowns per playbook
_last_auto_run: dict[str, datetime] = {}


async def on_incident_created(incident: Incident):
    """Auto-match incident to playbook and execute or request approval."""
    # Try to match a playbook
    playbook = None
    search_terms = [incident.title] + incident.affected_services
    for term in search_terms:
        playbook = match_playbook(term)
        if playbook:
            break

    if not playbook:
        logger.info(f"No playbook matched for incident [{incident.id}] {incident.title}")
        return

    # Check cooldown
    last_run = _last_auto_run.get(playbook.name)
    if last_run:
        elapsed = (datetime.utcnow() - last_run).total_seconds() / 60
        if elapsed < playbook.cooldown_minutes:
            logger.info(f"Playbook {playbook.name} in cooldown ({int(elapsed)}/{playbook.cooldown_minutes}min)")
            return

    logger.info(f"Auto-matched incident [{incident.id}] to playbook: {playbook.name}")
    incident.add_event("playbook_matched", f"Matched playbook: {playbook.name}")

    context = {
        "incident_id": incident.id,
        "service": incident.affected_services[0] if incident.affected_services else "",
    }

    if playbook.requires_approval:
        # Request approval via Telegram
        for action in playbook.actions:
            if action.risk_level in (RiskLevel.MEDIUM, RiskLevel.HIGH):
                create_approval(
                    playbook_name=playbook.name,
                    action_name=action.name,
                    risk_level=action.risk_level,
                    description=f"[{incident.id}] {action.description}",
                    context=context,
                )
        # Execute LOW risk actions immediately
        for action in playbook.actions:
            if action.risk_level == RiskLevel.LOW:
                from devops.remediation import execute_action
                result = await execute_action(action, context, dry_run=False)
                incident.add_event("action_executed", f"{action.name}: {result.get('status')}")
    else:
        # Auto-execute entire playbook
        result = await execute_playbook(playbook.name, context, dry_run=False)
        incident.add_event("playbook_executed", f"Auto-executed: {playbook.name}")
        _last_auto_run[playbook.name] = datetime.utcnow()


def register_auto_remediation():
    """Register event listeners for auto-remediation."""
    event_bus.on("incident_created", on_incident_created)
    logger.info("Auto-remediation registered")
