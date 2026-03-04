"""Telegram notifications for incidents and approvals."""
from __future__ import annotations

import logging
from devops.models import Incident, Severity

logger = logging.getLogger(__name__)

# Will be set by bot.py when initializing
_bot = None
_alert_chat_id: int | None = None


def configure(bot, alert_chat_id: int):
    """Set the Telegram bot instance and alert chat ID."""
    global _bot, _alert_chat_id
    _bot = bot
    _alert_chat_id = alert_chat_id
    logger.info(f"DevOps notifications configured for chat {alert_chat_id}")


async def send_alert(text: str, parse_mode: str = "Markdown"):
    """Send a text alert to the configured Telegram chat."""
    if not _bot or not _alert_chat_id:
        logger.warning("Notifications not configured, skipping alert")
        return
    try:
        await _bot.send_message(
            chat_id=_alert_chat_id,
            text=text,
            parse_mode=parse_mode,
        )
    except Exception as e:
        logger.error(f"Failed to send Telegram alert: {e}")


async def send_incident_alert(incident: Incident):
    """Send incident notification to Telegram."""
    severity_icon = {
        Severity.CRITICAL: "🔴",
        Severity.WARNING: "🟡",
        Severity.INFO: "🔵",
    }
    icon = severity_icon.get(incident.severity, "⚪")
    services = ", ".join(incident.affected_services) if incident.affected_services else "unknown"

    text = (
        f"{icon} *Incident [{incident.id}]*\n"
        f"*{incident.title}*\n"
        f"Severity: {incident.severity.value}\n"
        f"Services: {services}\n"
    )
    if incident.description:
        text += f"\n{incident.description[:300]}"

    await send_alert(text)


async def send_approval_request(approval: dict):
    """Send approval request with inline keyboard."""
    if not _bot or not _alert_chat_id:
        return

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    text = (
        f"🔐 *Approval Required*\n"
        f"Playbook: {approval['playbook']}\n"
        f"Action: {approval['action']}\n"
        f"Risk: {approval['risk_level']}\n"
        f"\n{approval['description']}"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve:{approval['id']}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject:{approval['id']}"),
        ]
    ])

    try:
        await _bot.send_message(
            chat_id=_alert_chat_id,
            text=text,
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
    except Exception as e:
        logger.error(f"Failed to send approval request: {e}")


async def send_incident_resolved(incident: Incident):
    """Send resolution notification."""
    await send_alert(
        f"✅ *Incident [{incident.id}] Resolved*\n"
        f"{incident.title}\n"
        f"Duration: {_format_duration(incident)}"
    )


def _format_duration(incident: Incident) -> str:
    if not incident.resolved_at:
        return "ongoing"
    delta = incident.resolved_at - incident.detected_at
    minutes = int(delta.total_seconds() / 60)
    if minutes < 60:
        return f"{minutes}m"
    return f"{minutes // 60}h {minutes % 60}m"
