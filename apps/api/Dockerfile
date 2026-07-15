FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY apps/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy libs, the experimental workbook-agent source, and app
COPY libs/ /app/libs/
COPY experiments/workbook_agent_poc/ /app/experiments/workbook_agent_poc/
COPY apps/api/ /app/apps/api/

EXPOSE 8000

CMD ["sh", "-c", "alembic -c apps/api/alembic.ini upgrade head && uvicorn apps.api.app.main:app --host 0.0.0.0 --port 8000"]
