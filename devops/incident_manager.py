"""Incident lifecycle management."""
from __future__ import annotations

import logging
from datetime import datetime

from devops.models import Incident, IncidentStatus, Severity
from devops.event_bus import event_bus

logger = logging.getLogger(__name__)


class IncidentManager:
    def __init__(self):
        self.incidents: dict[str, Incident] = {}

    def create(self, title: str, severity: Severity, affected_services: list[str],
               description: str = "") -> Incident:
        incident = Incident(
            title=title,
            severity=severity,
            affected_services=affected_services,
            description=description,
        )
        incident.add_event("detected", f"Incident detected: {title}")
        self.incidents[incident.id] = incident
        logger.warning(f"Incident created: [{incident.id}] {title}")
        event_bus.emit_nowait("incident_created", incident=incident)
        return incident

    def get(self, incident_id: str) -> Incident | None:
        return self.incidents.get(incident_id)

    def get_active(self) -> list[Incident]:
        return [i for i in self.incidents.values() if i.status != IncidentStatus.RESOLVED]

    def get_all(self, limit: int = 50) -> list[Incident]:
        return sorted(
            self.incidents.values(),
            key=lambda i: i.detected_at,
            reverse=True,
        )[:limit]

    def resolve(self, incident_id: str, message: str = "") -> Incident | None:
        incident = self.incidents.get(incident_id)
        if not incident:
            return None
        incident.resolve(message)
        logger.info(f"Incident resolved: [{incident_id}] {message}")
        event_bus.emit_nowait("incident_resolved", incident=incident)
        return incident

    def add_event(self, incident_id: str, event_type: str, message: str) -> bool:
        incident = self.incidents.get(incident_id)
        if not incident:
            return False
        incident.add_event(event_type, message)
        return True

    def find_duplicate(self, title: str, affected_services: list[str]) -> Incident | None:
        for incident in self.get_active():
            if incident.title == title:
                return incident
            if set(incident.affected_services) & set(affected_services):
                if (datetime.utcnow() - incident.detected_at).total_seconds() < 600:
                    return incident
        return None


incident_manager = IncidentManager()
