# Production deployment checklist

- Pin and scan the container image in CI.
- Store secrets outside the Compose file.
- Bind AIBA to a private interface and place it behind HTTPS.
- Configure firewall egress and ingress allowlists.
- Set `AIBA_ALLOWED_ORIGINS` only for trusted dashboard origins.
- Persist and back up `/app/agent_system`, including `providers.db`, and retain the matching `AIBA_MASTER_KEY` in a secrets manager.
- Run one API process per SQLite data volume; use a managed queue/database before horizontal scaling.
- Add external uptime, disk, error-rate, queue-depth, and latency monitoring.
- Test restore procedures and provider failover.
- Review permissions and approval behavior for every unattended workflow.

SQLite is reliable for a single-node deployment. Multi-node/high-availability operation requires replacing SQLite-backed stores with a shared transactional database and distributed queue; v1.0 intentionally does not pretend otherwise.
