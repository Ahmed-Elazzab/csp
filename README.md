# NWC Spare Part Criticality Assessment Platform

An autonomous AI-powered engineering platform built for the **National Water Company (NWC)** in Saudi Arabia.

The user provides only a spare part number or description.  
Everything else — research, evidence collection, AI analysis, deterministic scoring, and report generation — executes automatically.

---

## How It Works

```
User: enter part number → click Analyze
              │
              ▼
   ┌─────────────────────────────────────┐
   │  1. Validate Input                  │
   │  2. Research Technical Docs         │  ← Web search (Tavily / DDG / SerpAPI)
   │  3. Collect Engineering Evidence    │  ← Relevance filtering + domain blocklist
   │  4. Extract Technical Attributes    │  ← LLM structured extraction
   │  5. Criticality Analysis Agent      │  ← LLM assigns dimension options
   │  6. NWC Deterministic Rule Engine   │  ← Score lookup + strategic rules
   │  7. Generate Assessment Report      │  ← Saved to PostgreSQL
   └─────────────────────────────────────┘
              │
              ▼
   Read-only Assessment Report
   (Classification · Score · AI Reasoning · Audit Trail)
```

**The LLM assigns dimension options only. The Rule Engine is the sole authority for scores and final classification.**

---

## NWC Criticality Model

### Four Dimensions

| Dimension | Option A | Option B | Option C | Option D |
|---|---|---|---|---|
| **Operations** | Complete shutdown / SPOF (12 pts) | Partial shutdown (10 pts) | Workaround exists (3 pts) | No impact (0 pts) |
| **Water Quality** | Direct degradation (10 pts) | Slight degradation (3 pts) | No impact (0 pts) | — |
| **Availability** | All 4 risk conditions* (10 pts) | Substitute available (3 pts) | Backup not required (0 pts) | — |
| **Safety** | Risk to personnel/environment/infra (10 pts) | Partial risk (5 pts) | No risk (0 pts) | — |

\* Availability A: backup required **AND** no substitute **AND** lead time > TTR **AND** single manufacturer/country

**Maximum score: 42 points**

### Final Classifications

| Label | Condition |
|---|---|
| 🔴 **Strategic** | Deterministic override rules only — LLM cannot select this |
| 🔴 **Very Critical** | Score ≥ 25 |
| 🟡 **Semi-Critical** | Score ≥ 10 |
| 🟢 **Non-Critical** | Score < 10 |

### Strategic Override Rules

Regardless of numeric score, a part becomes **Strategic** if any of these apply:

- Operations A + Availability A (complete shutdown / SPOF + highest supply risk)
- Operations B + Availability A (partial shutdown + highest supply risk)
- Water Quality A + Availability A (direct water quality impact + highest supply risk)

---

## Quick Start

### Prerequisites

- Docker Desktop
- Python 3.11+

### 1. Clone and configure

```bash
git clone <repo-url>
cd csp
cp .env.example .env
# Edit .env — minimum required: LLM_API_KEY
```

### 2. Start the stack

```bash
docker compose up -d
```

This starts PostgreSQL and builds + runs the Streamlit app in one command.

### 3. Open the app

```
http://localhost:8501
```

---

## Running Locally (without Docker)

```bash
pip install -r requirements.txt

# Start PostgreSQL only
docker compose up -d postgres

# Run the app
streamlit run app.py
```

---

## Configuration (`.env`)

Copy `.env.example` to `.env` and fill in the required values.

### LLM Configuration

```env
LLM_PROVIDER=openai           # openai | azure_openai | anthropic | gemini | ollama | openai_compatible
LLM_API_KEY=                  # your API key
LLM_MODEL=gpt-4o-mini         # model name
LLM_BASE_URL=https://api.openai.com/v1
LLM_TEMPERATURE=0.1
LLM_MAX_TOKENS=4096
LLM_TIMEOUT=120
LLM_MAX_RETRIES=3
```

### LLM Provider Reference

| Provider | `LLM_PROVIDER` | Notes |
|---|---|---|
| OpenAI | `openai` | Default |
| Azure OpenAI | `azure_openai` | Also set `LLM_API_VERSION` |
| Anthropic Claude | `anthropic` | `pip install anthropic` |
| Google Gemini | `gemini` | `pip install google-generativeai` |
| Ollama (local) | `ollama` | Set `LLM_BASE_URL=http://localhost:11434/v1` |
| vLLM / LM Studio | `openai_compatible` | Set `LLM_BASE_URL` to your endpoint |

### Search Configuration

```env
TAVILY_API_KEY=      # recommended — 1,000 free/month at app.tavily.com
SERPAPI_KEY=         # alternative — 100 free/month at serpapi.com
SEARCH_MAX_RESULTS=10
SEARCH_TIMEOUT=30
```

Search provider priority (tried in order until results found):
1. **Tavily** — AI-native, best quality for industrial parts
2. **DuckDuckGo DDGS** — free, may be blocked on corporate/WSL networks
3. **DuckDuckGo HTML** — plain-HTTP fallback, more network-friendly
4. **SerpAPI** — Google-backed, reliable on restricted networks

If all providers fail, the pipeline continues with **insufficient evidence** and returns conservative (lowest-risk) options with confidence = 0.1.

### Evidence Quality & Filtering

The Research Agent applies two-layer filtering:

1. **Domain blocklist** — social media, encyclopedias (Wikipedia, Britannica), AI service docs (openai.com), news sites, and general retail are always blocked
2. **Relevance scoring** — results are scored by how many part-number tokens appear in the title/body; results below 25% relevance are rejected with a warning log

### Database

```env
DATABASE_URL=postgresql://csp_user:csp_pass@localhost:5432/csp_db
```

---

## Project Structure

```
csp/
├── app.py                           # Streamlit entry point — 3-page navigation
├── Dockerfile                       # Multi-stage build (builder + runtime)
├── docker-compose.yml               # PostgreSQL + csp app services
├── requirements.txt
├── .env.example                     # Full configuration reference
├── alembic.ini
│
├── pages/
│   ├── 1_Part_Lookup.py             # Single input + live pipeline execution view
│   ├── 2_Assessment_Report.py       # Full read-only assessment report
│   └── 3_History.py                 # Assessment history table
│
├── src/
│   ├── config.py                    # Pydantic settings (all env vars)
│   │
│   ├── pipeline/
│   │   └── runner.py                # AssessmentPipeline — 7-stage orchestrator
│   │
│   ├── agents/
│   │   ├── research_agent.py        # EvidenceSource plugins + relevance filtering
│   │   ├── criticality_analysis_agent.py  # LLM dimension analysis
│   │   └── database_agent.py        # All DB read/write operations
│   │
│   ├── llm/
│   │   └── provider.py              # Provider-agnostic LLM abstraction layer
│   │
│   ├── scoring/
│   │   └── nwc_engine.py            # Deterministic NWC Rule Engine
│   │
│   ├── database/
│   │   ├── models.py                # SQLAlchemy ORM (7 tables)
│   │   └── connection.py
│   │
│   ├── ingestion/
│   │   └── excel_importer.py        # Historical Excel seed (compatibility)
│   │
│   └── utils/
│       └── helpers.py               # ResearchResult, AttributeData, source tiers
│
├── migrations/
│   └── versions/
│       ├── 001_initial_schema.py
│       ├── 002_widen_part_number.py
│       └── 003_nwc_schema.py        # NWC 4-dimension + LLM audit fields
│
├── tests/
│   ├── test_nwc_engine.py           # 27 engine tests (scores, rules, validation)
│   └── test_ingestion.py            # Excel ingestion tests
│
└── data/
    └── Critical Parts Attributes.xlsx  # Historical attribute/question bank
```

---

## Navigation

The app has three pages:

| Page | Purpose |
|---|---|
| **Part Lookup** | Enter part number or description → trigger autonomous pipeline |
| **Assessment Report** | Full read-only report: classification, 4 dimensions, AI reasoning, audit trail |
| **History** | Table of all past assessments with classification and score |

---

## Assessment Report Sections

1. **Assessment Summary** — classification banner, total score, overall AI confidence
2. **Per-Dimension Analysis** — each of the 4 NWC dimensions with selected option, score, engineering reasoning, confidence, and evidence sources
3. **Research Summary** (collapsible) — extracted manufacturer, specs, description, OEM status, country of origin, evidence URLs
4. **LLM Metadata** — model used, provider, prompt version, processing time
5. **Audit Information** (collapsible) — assessment ID, stage durations, raw LLM JSON

---

## Database Schema

| Table | Purpose |
|---|---|
| `spare_parts` | Part master records |
| `part_attributes` | Extracted attributes — value, confidence, source, trust tier |
| `research_sources` | Web URLs collected per part |
| `assessments` | Assessment runs — NWC scores, label, LLM provenance |
| `nwc_dimension_scores` | Per-dimension option, score, reasoning, confidence, sources |
| `attribute_definitions` | Historical Excel attribute catalogue |
| `questionnaire_questions` | Historical Excel question bank |

Every assessment stores: `model_used`, `prompt_version`, `inference_timestamp`, `analysis_confidence`, full `analysis_json` for complete auditability.

---

## Migrations

```bash
# Apply all pending migrations
alembic upgrade head

# After modifying models
alembic revision --autogenerate -m "description"
```

Migration history:
- `001` — initial schema
- `002` — widen `part_number` to TEXT (supports long descriptions)
- `003` — NWC 4-dimension fields + LLM audit columns + `nwc_dimension_scores` table

---

## Running Tests

```bash
# All tests
pytest -v

# NWC Rule Engine only (no DB required)
pytest tests/test_nwc_engine.py -v

# Excel ingestion only
pytest tests/test_ingestion.py -v
```

Tests cover: dimension scoring, classification thresholds, all strategic override rules, option validation, confidence clamping, and Excel ingestion.

---

## Docker Operations

```bash
# Start everything
docker compose up -d

# View app logs
docker compose logs csp -f

# Rebuild after code changes
docker compose down && docker compose build && docker compose up -d

# Stop (preserves database volume)
docker compose down

# Stop and delete all data
docker compose down -v
```

---

## Security Notes

- **Never commit `.env`** — it is in `.gitignore` and must stay there
- **Never put API keys in `src/config.py`** — defaults must be empty strings; keys go in `.env` only
- The `csp` Docker container runs as a non-root `appuser` (UID 1000)
- The `.env` file is loaded at runtime via `env_file:` in docker-compose — it is not baked into the image

---

## Design Guarantees

| Guarantee | How it's enforced |
|---|---|
| **LLM never classifies** | "Strategic" is unreachable by any LLM output; Rule Engine owns all labels |
| **Deterministic scoring** | Engine looks up scores from a fixed table; LLM-supplied scores are ignored |
| **No irrelevant evidence** | Domain blocklist + relevance scoring reject unrelated results before LLM call |
| **Insufficient evidence handled** | `INSUFFICIENT EVIDENCE` notice sent to LLM → conservative options, confidence = 0.1 |
| **Full auditability** | Every assessment stores model, prompt version, timestamp, and raw LLM JSON |
| **Provider agnostic** | Switch LLM with one env var — zero code changes |
| **Fail-safe pipeline** | Stage failures are caught; pipeline always attempts to produce a result |
