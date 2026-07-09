# InvestIQ — Investment Capital Decision Intelligence

Production-grade, multi-agent platform with auditable financial outputs deployed on Azure Container Apps.

## Architecture

- **M1** Web UI (Next.js/React) — `apps/ui`
- **M2** API Gateway — Azure API Management
- **M3** Backend API (FastAPI) — `apps/api`
- **M4** Orchestration Engine (IOE) — `apps/orchestrator`
- **M5** Agent Workers (8 services) — `apps/agents/*`
- **M6** Tool Services — `libs/tools`
- **M7** Async Job Runner — Azure Container Apps Jobs
- **M8** PostgreSQL — `infra/`
- **M9** Redis State/Cache
- **M10–M16** Azure Services (Blob, AI Search, Entra ID, Key Vault, etc.)

## Quick Start

### Backend
```bash
cd apps/api
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### Frontend
```bash
cd apps/ui
npm install
npm run dev
```

### Docker Compose (all services)
```bash
docker-compose up --build
```

### Azure Deployment
```bash
chmod +x infra/deploy.sh
./infra/deploy.sh
```

## Project Structure
```
├── apps/
│   ├── api/              # FastAPI backend (M3)
│   ├── orchestrator/     # IOE LangGraph orchestrator (M4)
│   ├── agents/           # 8 specialized agents (M5)
│   │   ├── ingest/
│   │   ├── sensitivity/
│   │   ├── montecarlo/
│   │   ├── cashflow/
│   │   ├── debt/
│   │   ├── monitor/
│   │   ├── report/
│   │   └── assistant/
│   └── ui/               # Next.js frontend (M1)
├── libs/
│   ├── calc_engine/      # Financial formulas (IRR, NPV, DSCR, MC)
│   └── tools/            # Tool registry (excel_parser, etc.)
├── infra/                # Azure IaC & deployment scripts
├── db/                   # Database migrations
└── tests/                # Unit & integration tests
```
