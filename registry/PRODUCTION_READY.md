# AgentTrust Registry: Production Readiness Checklist

This document outlines the requirements and considerations for moving the AgentTrust Reference Registry from Phase A (MVP/Consolidation) to Phase B (Production at Scale).

## Phase A Status

- ✅ HTTP server running (`ThreadingHTTPServer`)
- ✅ Agent registration endpoint (`POST /register`)
- ✅ Agent search endpoint (`GET /search`)
- ✅ User endpoints (`POST /auth/register`, `POST /auth/login`, `GET /users/{principal_id}`)
- ✅ Reputation recording (`POST /users/{principal_id}/reputation`)
- ✅ Health check endpoint (`GET /healthz`)
- ✅ Docker support (single-image deployment)
- ✅ JSON-based persistence (IndexStore, UserIndex)
- ✅ Optional in-memory mode for demos

### What Phase A Proves

- Multiple apps can connect to a single independent registry
- Registry stores agent and user data reliably
- Reputation records survive service restarts
- Concurrent writes are serialized correctly (ThreadingHTTPServer + locks)

## Phase B: Production Deployment Checklist

### 1. Authentication & Authorization

**Current State:**
- `POST /admin/api-keys` is open by default (demo-friendly)
- Optional bearer token gating exists via `--admin-token`
- Registration requires valid API key (anti-Sybil gate)

**Phase B Requirements:**

- [ ] Enforce `--admin-token` in all production deployments
- [ ] Implement API key lifecycle management
  - [ ] Mint with expiration time (no forever keys)
  - [ ] Rotate credentials before expiry
  - [ ] Revoke compromised keys immediately
  - [ ] Log all key operations (create, revoke, rotate)
- [ ] Separate read (search) from write (register) permissions
  - [ ] Searches should not require authentication (public read)
  - [ ] Registration should require rate-limited, authenticated access
- [ ] Consider OAuth2 or JWT bearer tokens for inter-service auth
- [ ] Implement token refresh mechanism
- [ ] Add audit trail for all authentication events

**Files to Create:**
- `docs/auth-model.md` — Detailed auth flow and token lifecycle
- `registry/auth.py` — Enhanced auth module with key rotation, expiry, audit

### 2. Rate Limiting & DDoS Protection

**Current State:**
- Optional `--rate-limit` flag (requests per IP per 60s)
- Not enabled by default

**Phase B Requirements:**

- [ ] Enable rate limiting by default
  - [ ] 100 requests/IP/60s for reads (searches, gets)
  - [ ] 10 requests/IP/60s for writes (register, admin)
  - [ ] Configurable per environment
- [ ] Implement request size limits (cap JSON body size)
- [ ] Add token bucket / sliding window rate limiter
- [ ] Reject requests from known bad actors (IP blocklist)
- [ ] Implement adaptive rate limiting (backoff on abuse)
- [ ] Log rate limit violations for analysis

**Files to Review:**
- `common/ratelimit.py` — Existing RateLimiter; extend for sliding window

### 3. Monitoring & Observability

**Current State:**
- Docker HEALTHCHECK (HTTP GET /healthz)
- Logs go to stdout (no structured logging)
- No metrics collection

**Phase B Requirements:**

- [ ] Structured logging (JSON, with timestamps, severity, context)
  - [ ] Log registration requests (who registered, when, principal_id)
  - [ ] Log search queries (capability, requesting service)
  - [ ] Log errors with full stack traces
  - [ ] Log rate limit hits and authentication failures
- [ ] Metrics collection (Prometheus-compatible)
  - [ ] Request count by endpoint
  - [ ] Request latency (p50, p95, p99)
  - [ ] Error rate by type
  - [ ] Registry size (total principals, capabilities, users)
  - [ ] Reputation records count
- [ ] Application health metrics
  - [ ] Database/index size
  - [ ] Memory usage
  - [ ] Goroutine/thread count (correlated with requests)
- [ ] Alerting rules
  - [ ] High error rate (>1% of requests)
  - [ ] Service down (healthz fails)
  - [ ] Rate limit abuse (>10% of requests rate-limited)
  - [ ] Data corruption (index inconsistency)

**Files to Create:**
- `registry/logging.py` — Structured logging setup
- `registry/metrics.py` — Prometheus metrics export
- `docs/monitoring.md` — Grafana dashboard templates, alert rules

### 4. Data Persistence & Backup

**Current State:**
- JSON file persistence (optional, via `--index-path`)
- Single-node, in-memory by default
- No backup strategy

**Phase B Requirements:**

- [ ] Migrate to PostgreSQL (or similar)
  - [ ] Schema for registrations, users, reputation records
  - [ ] Transactional guarantees (no partial writes)
  - [ ] Connection pooling
  - [ ] Query optimization and indexing
  - [ ] Prepared statements (prevent SQL injection)
- [ ] Backup strategy
  - [ ] Daily automated backups to S3 or similar
  - [ ] Point-in-time recovery capability
  - [ ] Tested restore procedure (monthly drills)
  - [ ] Off-site backup copies
- [ ] Data retention policy
  - [ ] Archive old reputation records (e.g., >1 year)
  - [ ] Purge deleted principals after grace period
  - [ ] GDPR compliance (user data deletion)
- [ ] Migration path from JSON
  - [ ] Schema migration script
  - [ ] Data validation during migration
  - [ ] Rollback procedure
  - [ ] Zero-downtime migration (dual-write, then flip)

**Files to Create:**
- `registry/db.py` — Database abstraction layer
- `registry/schema.sql` — PostgreSQL schema
- `docs/database-migration.md` — Migration runbook
- `scripts/backup.sh` — Automated backup script

### 5. Disaster Recovery & High Availability

**Current State:**
- Single registry instance
- No replication
- Local data loss = data loss

**Phase B Requirements:**

- [ ] Multi-node setup
  - [ ] Leader/follower or multi-primary replication
  - [ ] Automatic failover
  - [ ] Split-brain prevention (quorum-based or similar)
- [ ] Load balancing
  - [ ] Multiple registry instances behind a load balancer
  - [ ] Health-based routing (remove unhealthy instances)
  - [ ] Session affinity if needed
- [ ] Disaster recovery plan
  - [ ] RTO (Recovery Time Objective) — e.g., <5 minutes
  - [ ] RPO (Recovery Point Objective) — e.g., <1 minute of data loss
  - [ ] Regular disaster recovery drills (quarterly)
  - [ ] Runbook for production incidents
- [ ] Capacity planning
  - [ ] Storage: estimate registrations, users, reputation records growth
  - [ ] CPU/Memory: load test with expected concurrent connections
  - [ ] Network bandwidth: API throughput projections

**Files to Create:**
- `docs/dr-plan.md` — Disaster recovery runbook
- `docs/ha-setup.md` — High availability deployment guide
- `scripts/load-test.py` — Load testing script

### 6. Security Hardening

**Current State:**
- No HTTPS (relies on deployment reverse proxy)
- No input validation beyond JSON schema
- No encryption at rest

**Phase B Requirements:**

- [ ] Transport security (HTTPS)
  - [ ] Use TLS 1.2+ (ideally 1.3)
  - [ ] Valid certificate (not self-signed in production)
  - [ ] Certificate rotation before expiry
  - [ ] Cipher suite hardening (disable weak ciphers)
- [ ] Input validation & sanitization
  - [ ] Strict JSON schema validation for all inputs
  - [ ] Size limits on strings (principal_id, username, etc.)
  - [ ] Reject non-UTF-8 input
  - [ ] Prevent XXE/injection attacks
- [ ] Encryption at rest
  - [ ] Encrypt database backups
  - [ ] Encrypt sensitive fields (API keys) in database
  - [ ] Key management (use KMS or similar)
- [ ] Secrets management
  - [ ] Never log API keys, admin tokens, or credentials
  - [ ] Rotate secrets periodically
  - [ ] Use environment variables or secrets vault (not config files)
  - [ ] Audit who has access to secrets
- [ ] Dependency scanning
  - [ ] Regular security audits of Python dependencies
  - [ ] Update vulnerable packages promptly
  - [ ] Use dependency lock files (requirements-lock.txt)
  - [ ] Monitor for CVEs in transitive dependencies
- [ ] Code security
  - [ ] Static analysis (bandit, pylint)
  - [ ] No hardcoded secrets
  - [ ] Review auth/crypto code carefully
  - [ ] Fuzz testing of endpoints

**Files to Review/Create:**
- `docs/security-audit.md` — Third-party security audit results
- `requirements-lock.txt` — Pinned dependency versions
- `scripts/security-check.sh` — Automated security scanning

### 7. API Contract & Versioning

**Current State:**
- Single API version (v1 implicit)
- No version header or path versioning
- Backwards-incompatible changes could break apps

**Phase B Requirements:**

- [ ] API versioning strategy
  - [ ] Semantic versioning (v1, v2, etc.)
  - [ ] Version in URL path (`/v1/search`) or header
  - [ ] Support multiple versions concurrently (e.g., v1 and v2)
  - [ ] Deprecation policy (support old version for 12+ months)
- [ ] Backwards compatibility
  - [ ] Don't remove fields, only add new ones
  - [ ] Support optional fields in requests
  - [ ] Document breaking changes clearly
- [ ] API documentation
  - [ ] OpenAPI/Swagger spec for all endpoints
  - [ ] Code examples in multiple languages
  - [ ] Rate limit documentation
  - [ ] Error response codes and meanings

**Files to Create:**
- `docs/api.md` or `docs/openapi.yaml` — API specification
- `docs/versioning-policy.md` — API versioning strategy
- `docs/migration-guides.md` — Guides for version upgrades

### 8. Testing & Quality Assurance

**Current State:**
- Unit tests for RegistryService and endpoints
- HTTP integration tests
- No load testing
- No chaos engineering tests

**Phase B Requirements:**

- [ ] Test coverage
  - [ ] 80%+ code coverage (measured with pytest-cov)
  - [ ] All error paths tested
  - [ ] Concurrent scenario testing (thread safety)
- [ ] Integration testing
  - [ ] Multi-app scenarios (3+ apps using single registry)
  - [ ] Failure scenarios (service restart, data corruption)
  - [ ] Long-running stability tests (24+ hours)
- [ ] Load & performance testing
  - [ ] Concurrent user load (e.g., 1000 concurrent connections)
  - [ ] Throughput benchmarks (requests/sec)
  - [ ] Latency SLA verification (e.g., p99 < 100ms)
  - [ ] Endpoint-by-endpoint performance testing
- [ ] Chaos engineering
  - [ ] Kill registry process mid-request
  - [ ] Randomly drop database connections
  - [ ] Corrupt data files and verify recovery
  - [ ] Network latency/partition simulation
- [ ] Security testing
  - [ ] Penetration testing
  - [ ] SQL injection attempts (if using SQL)
  - [ ] Rate limit bypass attempts
  - [ ] Invalid token handling

**Files to Create:**
- `tests/integration/test_all_3_apps_with_independent_registry.py` — Multi-app test (✅ in Phase A)
- `tests/load_test.py` — Performance benchmarking
- `tests/chaos_test.py` — Failure scenario testing
- `scripts/coverage-report.sh` — Test coverage CI step

### 9. Documentation

**Current State:**
- `DEPLOYMENT.md` — Deployment guide (✅ in Phase A)
- Inline code comments

**Phase B Requirements:**

- [ ] Operations manual
  - [ ] Deployment procedures
  - [ ] Configuration guide
  - [ ] Scaling instructions
  - [ ] Backup & restore procedures
  - [ ] Upgrade procedures
- [ ] Architecture documentation
  - [ ] Data model (schema)
  - [ ] Request flow diagrams
  - [ ] Concurrency model
  - [ ] Error handling strategy
- [ ] Runbooks
  - [ ] Common troubleshooting scenarios
  - [ ] Incident response playbooks
  - [ ] Escalation procedures
  - [ ] Contact information
- [ ] SLOs & metrics
  - [ ] Service level objectives (uptime, latency, error rate)
  - [ ] Key performance indicators (KPIs)
  - [ ] Monitoring dashboards
  - [ ] Alert thresholds

**Files to Create:**
- `docs/ops-manual.md` — Operations procedures
- `docs/architecture.md` — System architecture & data model
- `docs/runbooks.md` — Incident response playbooks
- `docs/slo.md` — Service level objectives

### 10. Legal & Compliance

**Current State:**
- No privacy or terms of service considerations

**Phase B Requirements:**

- [ ] Privacy policy & data handling
  - [ ] Document what personal data is collected
  - [ ] Define data retention periods
  - [ ] Implement GDPR "right to be forgotten"
  - [ ] Regular privacy audits
- [ ] Compliance
  - [ ] SOC 2 certification (if required)
  - [ ] HIPAA/HITECH compliance (if handling health data)
  - [ ] PCI DSS compliance (if handling payment data)
  - [ ] Export control / sanctions compliance
- [ ] Audit trail
  - [ ] Immutable logs of all operations
  - [ ] Retain for compliance periods
  - [ ] Accessible for auditors

**Files to Create:**
- `docs/privacy-policy.md` — Data handling and privacy
- `docs/compliance-checklist.md` — Compliance audit trail

## Phase B Success Criteria

Before marking the registry as "production-ready," verify:

1. **Security Audit** — Third-party security review passed
2. **Performance** — Load testing passed (p99 latency < 100ms at 1000 concurrent users)
3. **HA/DR** — Failover tested and <5 minute RTO achieved
4. **Monitoring** — Dashboards deployed and alerting rules active
5. **Documentation** — All runbooks and ops manuals reviewed by on-call team
6. **Training** — On-call and support team trained on operations
7. **Incident Response** — Mock incident drills completed successfully

## Timeline Estimate

Assuming a small team:

- **Weeks 1-2:** Database migration (PostgreSQL), API versioning
- **Weeks 3-4:** Authentication/authorization hardening, rate limiting tuning
- **Weeks 5-6:** Monitoring, logging, metrics infrastructure
- **Weeks 7-8:** Load testing, performance optimization
- **Weeks 9-10:** HA/DR setup, failover testing
- **Weeks 11-12:** Security audit, compliance review, documentation

Total: **~12 weeks** from Phase A to Phase B production readiness.

## Recommended Phase B Prioritization

If time is constrained, prioritize in this order:

1. **Database migration** (data persistence & scalability)
2. **Authentication hardening** (security)
3. **Monitoring & observability** (ops visibility)
4. **Rate limiting** (abuse prevention)
5. **HA/DR** (availability)
6. Everything else

## Next Steps

1. Review this checklist with the team
2. Assign owners to each Phase B category
3. Create tracking issues/tasks for each requirement
4. Schedule Phase B kickoff meeting
5. Begin Phase B immediately after Phase A acceptance testing

---

**Document Version:** 1.0  
**Last Updated:** 2026-07-18  
**Status:** Phase A to Phase B Planning
