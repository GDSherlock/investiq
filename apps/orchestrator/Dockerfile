FROM python:3.12-slim

WORKDIR /app

COPY apps/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY libs/ /app/libs/
COPY apps/orchestrator/ /app/apps/orchestrator/
COPY apps/agents/ /app/apps/agents/

EXPOSE 8001

CMD ["python", "-m", "apps.orchestrator.engine"]
