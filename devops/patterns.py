"""Log pattern matching for error detection across services."""
from __future__ import annotations

import re

from devops.models import PatternMatch, Severity

# (regex, severity, category, description, recommendation)
PATTERNS: list[tuple[str, Severity, str, str, str]] = [
    # --- Generic patterns ---
    (r"(?i)out\s*of\s*memory|OOM|oom.kill|java\.lang\.OutOfMemoryError",
     Severity.CRITICAL, "Memory", "Out of memory / OOM kill detected",
     "Check pod memory limits, increase if needed. Consider heap tuning for Java services."),
    (r"(?i)connection\s*(refused|timed?\s*out|reset)",
     Severity.WARNING, "Network", "Connection issue detected",
     "Check target service health and network policies."),
    (r"(?i)disk\s*(full|space|quota)",
     Severity.CRITICAL, "Disk", "Disk space issue detected",
     "Check disk usage with 'df -h'. Clear logs/tmp or expand volume."),
    (r"(?i)(segfault|segmentation\s*fault|core\s*dump)",
     Severity.CRITICAL, "Crash", "Process crash detected",
     "Check for native memory issues. Review core dumps."),
    (r"(?i)(timeout|timed?\s*out|deadline\s*exceeded)",
     Severity.WARNING, "Timeout", "Timeout detected",
     "Check dependent service response times and connection pool settings."),
    (r"(?i)(unauthorized|403|401|authentication\s*fail)",
     Severity.WARNING, "Auth", "Authentication/authorization failure",
     "Check JWT tokens, service credentials, and RBAC permissions."),
    (r"(?i)(500|502|503|504)\s*(internal|bad\s*gateway|service\s*unavail|gateway\s*timeout)",
     Severity.CRITICAL, "HTTP", "HTTP server error detected",
     "Check upstream service health. Review gateway/proxy logs."),
    (r"(?i)exception|traceback|panic|fatal",
     Severity.WARNING, "Exception", "Application exception detected",
     "Review stack trace for root cause."),
    (r"(?i)(cpu|load)\s*(high|spike|100%|threshold)",
     Severity.WARNING, "CPU", "High CPU usage detected",
     "Profile the application. Check for hot loops or excessive GC."),
    (r"(?i)slow\s*query|query\s*timeout|deadlock",
     Severity.WARNING, "Database", "Database performance issue",
     "Review slow query log. Check missing indexes."),
    (r"(?i)CrashLoopBackOff",
     Severity.CRITICAL, "CrashLoop", "Pod crash loop detected",
     "Check pod logs and events. Verify resource limits and health probes."),
    (r"(?i)ImagePullBackOff|ErrImagePull",
     Severity.CRITICAL, "Image", "Image pull failure",
     "Verify image tag and registry credentials."),
    (r"(?i)Evicted|evict",
     Severity.WARNING, "Eviction", "Pod eviction detected",
     "Check node resource pressure. Review pod resource requests."),
    (r"(?i)readiness\s*probe\s*failed|liveness\s*probe\s*failed",
     Severity.WARNING, "Probe", "Health probe failure",
     "Check application startup time and health endpoint."),
    (r"(?i)back-?off\s*restarting",
     Severity.WARNING, "Restart", "Container restart backoff",
     "Check container exit codes and logs from previous instance."),

    # --- MongoDB specific ---
    (r"(?i)MongoTimeoutException|MongoSocketOpenException|MongoSocketReadException",
     Severity.CRITICAL, "MongoDB", "MongoDB connection/timeout error",
     "Check MongoDB connections (db.serverStatus().connections). Kill sessions if exhausted."),
    (r"(?i)TooManyLogicalSessions",
     Severity.CRITICAL, "MongoDB", "Too many MongoDB logical sessions",
     "Kill all sessions: db.adminCommand({killAllSessions: []}). Check session leak in app."),
    (r"(?i)MongoNotPrimaryException|NotPrimaryError",
     Severity.CRITICAL, "MongoDB", "MongoDB primary election / not-primary error",
     "Check replica set status. Wait for election or check for split-brain."),
    (r"(?i)WriteConcernError|write\s*concern",
     Severity.WARNING, "MongoDB", "MongoDB write concern error",
     "Check replica set health and write concern settings."),

    # --- NATS specific ---
    (r"(?i)nats.*connection\s*(closed|lost|disconnected)",
     Severity.CRITICAL, "NATS", "NATS connection lost",
     "Check NATS server health in pos namespace. Verify network connectivity."),
    (r"(?i)SlowConsumer|slow\s*consumer",
     Severity.WARNING, "NATS", "NATS slow consumer detected",
     "Consumer cannot keep up. Check consumer processing time and increase workers."),
    (r"(?i)JetStream.*error|jetstream.*unavailable",
     Severity.CRITICAL, "NATS", "JetStream error",
     "Check JetStream storage and NATS cluster health."),
    (r"(?i)Publishing\s*to\s*DLQ|dead\s*letter|changestream-dlq",
     Severity.WARNING, "NATS-DLQ", "Messages sent to dead letter queue",
     "Check DLQ stream for failed messages. Review changeStreamEventErrors collection."),

    # --- OneShell Sync specific ---
    (r"(?i)lock:posserverbackend:sync.*timeout|lock.*acquisition.*failed",
     Severity.WARNING, "SyncLock", "Sync lock timeout/contention",
     "Check Redis for stuck locks. May need to force-release stale locks."),
    (r"(?i)ChangeStreamHistoryLost|change\s*stream.*history.*lost",
     Severity.CRITICAL, "ChangeStream", "Change stream resume token expired",
     "Clear resume tokens in Redis. Restart PosServerBackend to rebuild."),
    (r"(?i)DataConversionService.*error|deserializ.*fail",
     Severity.WARNING, "DataConversion", "Data conversion/deserialization error",
     "Check incoming data format. May need to update model classes."),
    (r"(?i)_syncSource.*skip",
     Severity.INFO, "SyncLoop", "Sync loop prevention triggered",
     "Normal behavior - synced documents correctly skipped to prevent loops."),
    (r"(?i)MessageRetryService.*failed|NAK.*retry",
     Severity.WARNING, "SyncRetry", "Sync message retry/NAK detected",
     "Check PosServerBackend availability. Review sync push endpoint health."),
    (r"(?i)changeStreamEventErrors|sync.*error.*logged",
     Severity.WARNING, "SyncError", "Sync error logged to MongoDB",
     "Query changeStreamEventErrors collection for unresolved errors."),

    # --- Spring Boot / Java ---
    (r"(?i)HikariPool.*connection\s*is\s*not\s*available",
     Severity.CRITICAL, "ConnectionPool", "HikariCP connection pool exhausted",
     "Increase pool size or check for connection leaks."),
    (r"(?i)reactor\.core\.Exceptions\$OverflowException",
     Severity.CRITICAL, "Backpressure", "Reactor backpressure overflow",
     "Consumer cannot keep up with publisher. Add buffering or reduce producer rate."),
    (r"(?i)io\.netty.*AnnotatedConnectException",
     Severity.WARNING, "Netty", "Netty connection error",
     "Check target service availability and DNS resolution."),
    (r"(?i)WebClientRequestException|Connection\s*prematurely\s*closed",
     Severity.WARNING, "WebClient", "WebClient request failure",
     "Check target service health and connection timeouts."),

    # --- Kubernetes specific ---
    (r"(?i)FailedScheduling|Insufficient\s*(cpu|memory)",
     Severity.CRITICAL, "Scheduling", "Pod scheduling failed",
     "Check node resource availability. Consider scaling the cluster."),
    (r"(?i)FailedMount|MountVolume.*failed",
     Severity.CRITICAL, "Volume", "Volume mount failure",
     "Check PV/PVC status and storage provisioner."),

    # --- Redpanda / Kafka / Debezium ---
    (r"(?i)kafka.*disconnect|broker.*not\s*available|no\s*broker",
     Severity.CRITICAL, "Redpanda", "Kafka/Redpanda broker connectivity issue",
     "Check Redpanda pod in kafka namespace. Verify redpanda:9092 reachable."),
    (r"(?i)debezium.*task.*failed|connector.*FAILED",
     Severity.CRITICAL, "Debezium", "Debezium connector/task failure",
     "Check Debezium Connect REST API. Restart failed task or reset offsets."),
    (r"(?i)debezium.*offset.*reset|ChangeStreamHistoryLost.*debezium",
     Severity.CRITICAL, "Debezium", "Debezium offset/change stream history lost",
     "Stop connector, delete offsets, resume. Debezium health monitor CronJob handles this."),
    (r"(?i)kafka.*produce.*error|kafka.*send.*failed",
     Severity.WARNING, "Redpanda", "Kafka produce error",
     "Check Redpanda storage and broker health. May need to restart Redpanda."),
    (r"(?i)consumer.*group.*rebalance|rebalancing",
     Severity.WARNING, "Redpanda", "Kafka consumer group rebalancing",
     "Transient during pod restarts. Monitor if persists."),

    # --- Certificate / TLS ---
    (r"(?i)certificate.*expir|cert.*expir|tls.*expir",
     Severity.WARNING, "Certificate", "Certificate expiration warning",
     "Check cert-manager certificates. Verify GoDaddy webhook is running for DNS-01."),
    (r"(?i)x509.*certificate|tls.*handshake.*fail|certificate.*verify.*failed",
     Severity.CRITICAL, "Certificate", "TLS/certificate verification failure",
     "Check certificate validity and CA trust chain. May need cert renewal."),
    (r"(?i)acme.*challenge.*failed|dns.*01.*failed|solver.*error",
     Severity.CRITICAL, "CertManager", "ACME challenge failure (cert-manager)",
     "Check GoDaddy webhook pod in cert-manager namespace. Verify API credentials."),

    # --- Dragonfly / Redis ---
    (r"(?i)redis.*connection.*refused|dragonfly.*connection.*refused",
     Severity.CRITICAL, "Redis", "Redis/Dragonfly connection refused",
     "Check Dragonfly pod in default namespace. Verify port 6379 accessible."),
    (r"(?i)redis.*OOM|MISCONF.*maxmemory|dragonfly.*out.*memory",
     Severity.CRITICAL, "Redis", "Redis/Dragonfly out of memory",
     "Check Dragonfly memory usage. Current: --maxmemory=4096mb. May need to clear keys or increase."),
    (r"(?i)RedisCommandTimeoutException|redis.*timeout",
     Severity.WARNING, "Redis", "Redis command timeout",
     "Check Dragonfly load and slow commands. Current timeout: 3000ms."),
    (r"(?i)Redisson.*lock.*interrupt|lock.*acquisition.*timeout",
     Severity.WARNING, "RedisLock", "Redisson distributed lock timeout",
     "Check for long-running operations holding locks. Connection pool: 64 max."),
    (r"(?i)ratelimit.*block|business.*blocked|rate.*limit.*exceeded",
     Severity.WARNING, "RateLimit", "NATS rate limit block triggered",
     "Business auto-blocked for 30min. Check ratelimit:block:* keys in Dragonfly."),
]


def scan_logs(logs: str, service: str = "") -> list[PatternMatch]:
    matches = []
    seen = set()
    for line in logs.splitlines():
        for pattern, severity, category, description, recommendation in PATTERNS:
            if re.search(pattern, line):
                key = (category, line.strip()[:100])
                if key not in seen:
                    seen.add(key)
                    matches.append(PatternMatch(
                        pattern_name=pattern[:50],
                        category=category,
                        severity=severity,
                        description=description,
                        matched_line=line.strip()[:500],
                        service=service,
                        recommendation=recommendation,
                    ))
    return matches


def determine_root_cause(matches: list[PatternMatch]) -> str:
    priority = [
        "Memory", "MongoDB", "ChangeStream", "NATS", "ConnectionPool",
        "Backpressure", "Disk", "Crash", "CrashLoop", "HTTP",
        "Scheduling", "Database", "SyncLock", "Network", "Timeout",
    ]
    categories = {m.category for m in matches}
    for cat in priority:
        if cat in categories:
            critical = [m for m in matches if m.category == cat and m.severity == Severity.CRITICAL]
            if critical:
                return f"{cat}: {critical[0].description}"
            relevant = [m for m in matches if m.category == cat]
            return f"{cat}: {relevant[0].description}"
    if matches:
        return matches[0].description
    return "No root cause identified"
