# Test-only fake Wolfram MCP server (Slice 2B Batch B packet §5). NOT the real
# Wolfram Cloud MCP. Reuses the MCP SDK requirement pin from apps/mcp_execution.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY apps/mcp_execution/requirements.txt /tmp/req.txt
RUN pip install --no-cache-dir -r /tmp/req.txt && rm /tmp/req.txt

COPY tests/system/fake_wolfram_server/server.py /app/server.py
WORKDIR /app

ENV FAKE_WOLFRAM_PORT=8120
EXPOSE 8120

CMD ["python", "server.py"]
