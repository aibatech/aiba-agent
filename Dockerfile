FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN groupadd --system aiba && useradd --system --gid aiba --home /app aiba
COPY pyproject.toml README.md ./
COPY . .
RUN pip install --no-cache-dir '.[api]' && chown -R aiba:aiba /app
USER aiba
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8765/health',timeout=2)"
CMD ["python","aiba_launcher.py","--serve","--host","0.0.0.0","--port","8765"]
