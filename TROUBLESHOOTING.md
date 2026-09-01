# Troubleshooting

Run `python main.py --doctor` or choose **Run diagnosis** in the dashboard. Each failed check includes a direct remedy.

- `PYTHON_VERSION`: install Python 3.11 or newer.
- `DATA_WRITABLE`: grant the current user write access to `agent_system`.
- `API_TOKEN` / `MASTER_KEY`: rerun the installer or `python setup_cli.py`.
- `DOCKER`: install and start Docker, or use local sandbox mode.
- `DATABASE`: check free disk space and directory permissions.
- `PROVIDER`: reopen setup and connect at least one AI provider or local model server.
- `PORT`: stop the process using port 8765 or change `AIBA_API_PORT`.

Provider connection tests are available beside each provider in the dashboard. API errors include an HTTP status and a concise detail message; background task failures remain available in the job record.
