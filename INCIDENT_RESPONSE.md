# Incident response

1. Contain: stop AIBA, revoke exposed provider keys, and preserve logs.
2. Identify: record the crash ID, release version, platform, time, and last successful task.
3. Diagnose: run `python main.py --doctor`, verify `/ready`, inspect audit/crash logs, and verify the latest backup.
4. Recover: repair configuration or restore a verified backup while the runtime is stopped.
5. Validate: rerun unit, migration, provider, and target-platform certification gates.
6. Review: document root cause, affected data, key rotation, corrective change, and evidence that prevents recurrence.

Never email `.env`, databases, provider keys, or unredacted logs. Security reports should include reproducible steps without live credentials.
