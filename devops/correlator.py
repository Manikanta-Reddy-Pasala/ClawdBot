"""Error correlation across services using dependency graph."""
from __future__ import annotations

import logging
from collections import defaultdict

from devops.models import PatternMatch, CorrelationResult, Severity
from devops.topology import SERVICE_TOPOLOGY

logger = logging.getLogger(__name__)


class ErrorCorrelator:
    def correlate(self, matches_by_service: dict[str, list[PatternMatch]]) -> CorrelationResult:
        if not matches_by_service:
            return CorrelationResult(summary="No errors to correlate")

        severity_scores: dict[str, int] = defaultdict(int)
        for service, matches in matches_by_service.items():
            for m in matches:
                if m.severity == Severity.CRITICAL:
                    severity_scores[service] += 3
                elif m.severity == Severity.WARNING:
                    severity_scores[service] += 1

        if not severity_scores:
            return CorrelationResult(summary="No significant errors detected")

        dep_graph = {}
        for name, info in SERVICE_TOPOLOGY.items():
            dep_graph[name] = set(info.dependencies)

        reverse_deps: dict[str, set[str]] = defaultdict(set)
        for name, deps in dep_graph.items():
            for dep in deps:
                reverse_deps[dep].add(name)

        root_scores: dict[str, float] = {}
        for service, score in severity_scores.items():
            affected_dependents = reverse_deps.get(service, set()) & set(matches_by_service.keys())
            root_scores[service] = score * (1 + len(affected_dependents))

        root_cause = max(root_scores, key=root_scores.get) if root_scores else None

        cascade = []
        if root_cause:
            cascade = self._build_cascade(root_cause, matches_by_service, reverse_deps)

        all_services = sorted(matches_by_service.keys())
        confidence = min(0.95, 0.3 + 0.1 * len(cascade))

        return CorrelationResult(
            correlated_services=all_services,
            root_cause_service=root_cause,
            cascade_chain=cascade,
            summary=f"Root cause likely in {root_cause}, affecting {len(all_services)} services",
            confidence=confidence,
        )

    def _build_cascade(self, root: str, matches_by_service: dict,
                       reverse_deps: dict[str, set[str]]) -> list[str]:
        chain = [root]
        visited = {root}
        queue = list(reverse_deps.get(root, set()))
        while queue:
            svc = queue.pop(0)
            if svc in visited or svc not in matches_by_service:
                continue
            visited.add(svc)
            chain.append(svc)
            queue.extend(reverse_deps.get(svc, set()))
        return chain


error_correlator = ErrorCorrelator()
