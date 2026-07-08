# Spare Part Criticality Assessment System (CSP)

A Streamlit decision-support application that evaluates spare parts and classifies
them as **Critical**, **Semi Critical**, or **Not Critical** using a transparent,
rule-based scoring model.

---

## Architecture

```
User → Part Lookup → Research Agent → Database Agent
                                   ↓
                     Questionnaire Agent (adaptive Q&A)
                                   ↓
                     Criticality Agent → Assessment Result
```

### Four Agents

| Agent | Responsibility |
|---|---|
| **Research Agent** | Searches the web (DuckDuckGo) for the part; uses OpenAI GPT (optional) to extract structured attributes |
| **Database Agent** | Persists parts, attributes, sources, answers, and assessments via SQLAlchemy |
| **Questionnaire Agent** | Loads questions from Excel (via DB); pre-fills confident answers; asks user for the rest |
| **Criticality Agent** | Runs the rule-based scoring engine; saves results |

### Scoring Model

| Category | Weight |
|---|---|
| Operations Criticality | **45%** |
| Supply Chain Risk | **35%** |
| Inventory & Financial | **20%** |

| Total Score | Label |
|---|---|
| 0 – 39 | 🟢 Not Critical |
| 40 – 69 | 🟡 Semi Critical |
| 70 – 100 | 🔴 Critical |

**Override rules** take precedence over the numeric threshold:
- Complete shutdown + no backup → **Critical**
- Single point of failure + long lead time → **Critical**
- Single supplier + no substitute + zero/low stock → **Critical**
- Partial impact + high supply risk → **Semi Critical**
- No operational impact + good supply chain → **Not Critical**

### Data Source Priority

1. ERP / Manual Input (trust tier 1 – highest)
2. OEM Datasheet (tier 2)
3. Approved Supplier / Distributor (tier 3)
4. Public Website (tier 4)
5. AI Inference (tier 5 – lowest)

---

## Quick Start

### 1. Prerequisites

- Docker & Docker Compose
- Python 3.11+

### 2. Start PostgreSQL

```bash
docker compose up -d
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment

```bash
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY (optional)
```

### 5. Run the app

```bash
streamlit run app.py
```

The app will auto-initialise the database and seed questionnaire data from the
Excel workbook on first launch.

---

## Project Structure

```
csp/
├── app.py                          # Streamlit home page
├── requirements.txt
├── docker-compose.yml
├── .env.example
├── alembic.ini
├── migrations/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── 001_initial_schema.py
├── src/
│   ├── config.py                   # pydantic-settings, env vars
│   ├── database/
│   │   ├── connection.py           # SQLAlchemy engine & session
│   │   └── models.py               # ORM models
│   ├── agents/
│   │   ├── research_agent.py
│   │   ├── database_agent.py
│   │   ├── questionnaire_agent.py
│   │   └── criticality_agent.py
│   ├── ingestion/
│   │   └── excel_importer.py       # Excel → DB seed
│   ├── scoring/
│   │   └── engine.py               # Rule-based scoring + override rules
│   └── utils/
│       └── helpers.py              # Shared data-transfer objects
├── pages/
│   ├── 1_Part_Lookup.py
│   ├── 2_Research_Results.py
│   ├── 3_Questionnaire.py
│   ├── 4_Assessment_Result.py
│   └── 5_History.py
├── data/
│   └── Critical Parts Attributes.xlsx
└── tests/
    ├── conftest.py
    ├── test_scoring.py
    └── test_ingestion.py
```

---

## Database Schema

| Table | Purpose |
|---|---|
| `attribute_definitions` | Attribute catalogue from Excel (37 rows) |
| `questionnaire_questions` | Questions from Excel (28 rows) |
| `spare_parts` | Part master records |
| `part_attributes` | Per-part attribute values with confidence & source |
| `research_sources` | Web URLs researched per part |
| `assessments` | Assessment runs with scores & label |
| `questionnaire_answers` | Per-question answers within an assessment |

---

## Running Migrations (manual)

```bash
# Apply migrations
alembic upgrade head

# Generate a new migration after model changes
alembic revision --autogenerate -m "description"
```

---

## Running Tests

```bash
# Scoring engine tests (no DB required)
pytest tests/test_scoring.py -v

# Excel ingestion tests (requires Excel file in data/)
pytest tests/test_ingestion.py -v

# All tests
pytest -v
```

---

## Configuration Reference (`.env`)

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql://csp_user:csp_pass@localhost:5432/csp_db` | PostgreSQL connection string |
| `OPENAI_API_KEY` | *(empty)* | Optional – enables AI-assisted extraction |
| `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI model to use |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Override for local LLM servers |
| `SEARCH_MAX_RESULTS` | `5` | Max DuckDuckGo results per query |
| `CONFIDENCE_THRESHOLD` | `0.70` | Min confidence to auto-fill a question |
| `EXCEL_PATH` | `data/Critical Parts Attributes.xlsx` | Source Excel file |

---

## Design Principles

- **Transparent scoring**: every score is traceable to a specific question and answer
- **Confidence tracking**: every extracted fact carries a confidence level and source URL
- **Human override**: the system proposes; the user confirms or overrides
- **Adaptive questionnaire**: questions are never hardcoded – loaded from DB which was seeded from Excel
- **Source hierarchy**: user/ERP input always beats AI inference
