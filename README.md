# InvestIQ — Investment Capital Decision Intelligence

InvestIQ uploads and validates Excel financial models, persists workbook evidence, prepares a deterministic calculation graph, and presents auditable analysis from persisted calculation runs.

## Current capabilities

- Workbook upload, validation, extraction, and historical model selection
- Formula inventory, compilation, dependency analysis, and persisted baseline or override runs
- Canonical output discovery, reviewed semantic bindings, and unavailable-state diagnostics
- Overview, cash-flow, sensitivity, and Monte Carlo analysis
- Canonical reports, report chat, legacy report and assistant compatibility APIs, and DOCX export

## Runtime architecture

| Service | Source | Responsibility |
| --- | --- | --- |
| UI | `apps/ui` | Next.js upload and analysis experience |
| API | `apps/api` | FastAPI routes, persistence, extraction, calculation, and analysis reads |
| Analysis worker | `apps/api/app/analysis_worker.py` | Claims queued Monte Carlo and canonical report work |
| PostgreSQL | `docker-compose.yml` | Durable application, workbook, calculation, and report records |
| Redis | `docker-compose.yml` | Provisioned state/cache service retained for runtime compatibility |

## Workbook-to-analysis flow

1. `POST /api/v1/models/upload` validates and persists workbook evidence.
2. `ModelUploadOrchestrationService` prepares the calculation inventory and graph after successful extraction.
3. Calculation APIs create persisted baseline or override runs and expose canonical outputs.
4. Presentation services resolve reviewed semantic bindings for Overview and Cash Flow.
5. Sensitivity runs synchronously against persisted calculation inputs; Monte Carlo and canonical reports are claimed by `analysis-worker`.
6. Missing, unsupported, or ambiguous results remain explicitly unavailable.

## Local setup

### Backend

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r apps/api/requirements.txt
uvicorn apps.api.app.main:app --reload
```

### Frontend

```bash
cd apps/ui
npm install
npm run dev
```

### Full local stack

```bash
cp .env.example .env
docker compose up --build
```

Compose starts the API, analysis worker, UI, PostgreSQL, and Redis. The API container applies Alembic migrations before starting Uvicorn.

## Tests

```bash
python -m pytest -q
cd apps/ui && npm test
```

## Configuration

Use `.env.example` as the source for database, upload storage, frontend proxy, authentication, and optional Azure OpenAI settings. Never commit real credentials.

## Repository structure

```text
apps/api/                       FastAPI application, migrations, and worker
apps/ui/                        Next.js application
experiments/workbook_agent_poc/ Workbook extraction implementation used by the API image
libs/calc_engine/               Legacy calculation compatibility functions
libs/tools/                     Workbook parsing and compatibility tools
db/                             Bootstrap SQL
tests/                          Backend unit, integration, and contract tests
```

## API compatibility

Canonical model-version and calculation-run APIs power the current analysis pages. Legacy scenario, report, assistant, debt-analysis, alerts, audit, market-data, and model endpoints remain registered for external consumers.

OpenAPI documentation is available from a running API at `/docs`; health is available at `/health`.
