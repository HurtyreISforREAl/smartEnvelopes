# Smart Envelopes Platform

Event-driven микросервисная система управления личными финансами.
Пользователь создаёт «конверты» (Еда, Аренда, Накопления) и правила автораспределения.
При каждой транзакции система распределяет деньги по конвертам через Kafka.
Python AI-агенты (LangGraph + удалённые LLM API) автоматически категоризируют транзакции,
обнаруживают аномалии и генерируют советы по бюджету.

***

## Архитектура

```
                    ┌──────────────────────────────────────────┐
                    │         API Gateway  (Fiber :8000)       │
                    │     JWT • Rate Limiting • Logging        │
                    └──────────────┬───────────────────────────┘
                                   │
          ┌────────────────────────┼──────────────────────┐
          ▼                        ▼                       ▼
┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
│ Accounts Service │   │  Transactions    │   │  Rules Service   │
│  (Go / Gin 8001) │   │  Service         │   │  (Go / Gin 8003) │
│                  │   │  (Go / Gin 8002) │   │                  │
│ • Users          │   │ • Create Txn     │   │ • Rules CRUD     │
│ • Accounts       │   │ • Idempotency    │   │ • Kafka consume  │
│ • Envelopes      │   │ • HTTP → Agent   │   │ • Apply rules    │
│ • Balances       │   │ • Kafka publish  │   │ • Kafka publish  │
└────────┬─────────┘   └────────┬─────────┘   └────────┬─────────┘
         │                      │                       │
         └──────────────────────┼───────────────────────┘
                                ▼
          ┌─────────────────────────────────────────────────────┐
          │                  Apache Kafka                       │
          │                                                     │
          │  transaction.created      → Categorization Agent   │
          │  transaction.categorized  → Rules Service          │
          │  transaction.categorized  → Anomaly Agent          │
          │  allocation.scheduled     → Accounts Service       │
          │  allocation.completed     → Transactions Service   │
          │  balance.updated          → Budget Advisor Agent   │
          │  alert.anomaly_detected   → (future: Notify Svc)   │
          │  advice.generated         → (future: Notify Svc)   │
          └─────────────────────────────────────────────────────┘
                                │
          ┌─────────────────────┼──────────────────────┐
          ▼                     ▼                       ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│ Categorization   │  │ Anomaly          │  │ Budget Advisor   │
│ Agent            │  │ Detection Agent  │  │ Agent            │
│ (Python :8010)   │  │ (Python :8011)   │  │ (Python :8012)   │
│                  │  │                  │  │                  │
│ FastAPI          │  │ FastAPI          │  │ FastAPI          │
│ LangGraph        │  │ LangGraph        │  │ LangGraph        │
│ POST /categorize │  │ POST /detect     │  │ POST /advice     │
└────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘
         │                     │                      │
         └─────────────────────┼──────────────────────┘
                                ▼
          ┌─────────────────────────────────────────────────────┐
          │              Remote LLM API                         │
          │                                                     │
          │   Groq (free) • Google Gemini (free) • OpenAI      │
          │   Mock Provider (dev, без API-ключей)               │
          └─────────────────────────────────────────────────────┘

                                │
          ┌─────────────────────┼────────────────────────┐
          ▼                     ▼                         ▼
┌──────────────────┐  ┌──────────────────┐   ┌─────────────────┐
│  accounts_db     │  │ transactions_db  │   │    rules_db     │
│  (PostgreSQL)    │  │ (PostgreSQL)     │   │  (PostgreSQL)   │
└──────────────────┘  └──────────────────┘   └─────────────────┘

                                │
                                ▼
                    ┌───────────────────────┐
                    │  Prometheus + Grafana  │
                    │    :9090      :3000    │
                    └───────────────────────┘
```

***

## Event Flow

```
POST /api/transactions
        │
        ▼
Transactions Service
├─ Сохраняет (category = null, status = "pending")
└─ HTTP POST → Categorization Agent /categorize
                        │
                        ▼
               LangGraph + Remote LLM
               category = "food", confidence = 0.97
                        │
                        ▼
Transactions Service обновляет category
└─ Kafka: transaction.categorized
                │                   │
                ▼                   ▼
        Rules Service       Anomaly Detection Agent
        ├─ Читает правила   ├─ Сравнивает с историей
        ├─ Распределяет     └─ alert.anomaly_detected (если нужно)
        └─ Kafka: allocation.scheduled
                │
                ▼
        Accounts Service
        ├─ Обновляет балансы конвертов
        └─ Kafka: balance.updated
                │
                ▼
        Budget Advisor Agent
        └─ Kafka: advice.generated (если конверт > 80% лимита)
```

***

## Kafka Topics

| Topic | Producer | Consumer |
|---|---|---|
| `transaction.created` | Transactions Service | Categorization Agent (fallback) |
| `transaction.categorized` | Categorization Agent | Rules Service, Anomaly Agent |
| `allocation.scheduled` | Rules Service | Accounts Service |
| `allocation.completed` | Accounts Service | Transactions Service |
| `balance.updated` | Accounts Service | Budget Advisor Agent |
| `alert.anomaly_detected` | Anomaly Agent | *(future: Notifications)* |
| `advice.generated` | Budget Advisor Agent | *(future: Notifications)* |

***

## Доменная модель

### accounts_db

```sql
users
├── id               UUID PK
├── email            VARCHAR UNIQUE
├── password_hash    VARCHAR
├── created_at       TIMESTAMP
└── updated_at       TIMESTAMP

accounts
├── id               UUID PK
├── user_id          UUID FK → users.id
├── name             VARCHAR
├── total_balance    DECIMAL(15,2)
├── currency         VARCHAR(3) DEFAULT 'RUB'
├── created_at       TIMESTAMP
└── updated_at       TIMESTAMP

envelopes
├── id               UUID PK
├── account_id       UUID FK → accounts.id
├── name             VARCHAR
├── balance          DECIMAL(15,2)
├── monthly_limit    DECIMAL(15,2)
├── priority         INT (1–10)
├── color            VARCHAR(7)
├── created_at       TIMESTAMP
└── updated_at       TIMESTAMP
```

### transactions_db

```sql
transactions
├── id                   UUID PK
├── account_id           UUID
├── user_id              UUID
├── amount               DECIMAL(15,2)
├── type                 VARCHAR    -- 'income' | 'expense'
├── category             VARCHAR    -- NULL до категоризации
├── category_source      VARCHAR    -- 'llm' | 'rule' | 'manual'
├── category_confidence  FLOAT      -- 0.0–1.0
├── description          TEXT
├── status               VARCHAR    -- 'pending' | 'completed' | 'failed'
├── idempotency_key      UUID UNIQUE
├── created_at           TIMESTAMP
└── updated_at           TIMESTAMP

allocations
├── id               UUID PK
├── transaction_id   UUID FK → transactions.id
├── envelope_id      UUID
├── account_id       UUID
├── amount           DECIMAL(15,2)
├── rule_id          UUID
├── status           VARCHAR    -- 'pending' | 'completed' | 'failed'
├── created_at       TIMESTAMP
└── updated_at       TIMESTAMP

balance_log
├── id               BIGSERIAL PK
├── envelope_id      UUID
├── previous_balance DECIMAL(15,2)
├── new_balance      DECIMAL(15,2)
├── transaction_id   UUID
├── reason           VARCHAR
└── created_at       TIMESTAMP
```

### rules_db

```sql
rules
├── id               UUID PK
├── account_id       UUID
├── user_id          UUID
├── name             VARCHAR
├── condition_type   VARCHAR    -- 'category' | 'amount_range'
├── condition_value  VARCHAR
├── allocations      JSONB      -- [{"envelope_id":"...", "percent": 50}, ...]
├── is_active        BOOLEAN DEFAULT TRUE
├── created_at       TIMESTAMP
└── updated_at       TIMESTAMP

envelope_goals
├── id               UUID PK
├── envelope_id      UUID
├── account_id       UUID
├── target_amount    DECIMAL(15,2)
├── target_date      DATE
└── created_at       TIMESTAMP

agent_logs
├── id               UUID PK
├── agent_name       VARCHAR    -- 'categorization' | 'anomaly' | 'advisor'
├── transaction_id   UUID
├── account_id       UUID
├── input            JSONB
├── output           JSONB
├── model_used       VARCHAR
├── latency_ms       INT
└── created_at       TIMESTAMP
```

***

## AI Agents

### Categorization Agent (:8010)

```
FastAPI endpoints:
  POST /categorize        — категоризировать одну транзакцию
  POST /categorize/batch  — пакетная категоризация
  GET  /health

LangGraph граф:
  [llm_classify] → confidence >= 0.85? → [done]
                                      → [rule_fallback] → [done]

Категории:
  food | transport | salary | entertainment
  utilities | health | shopping | transfer | other
```

### Anomaly Detection Agent (:8011)

```
FastAPI endpoints:
  POST /detect  — проверить транзакцию на аномалию
  GET  /health

LangGraph граф:
  [load_history] → [statistical_check] → anomaly? → [llm_explain] → [publish_alert]
                                                  → no anomaly   → [done]

Что проверяет:
  • Резкий скачок суммы относительно истории (IsolationForest)
  • Ночная транзакция (00:00–05:00)
  • Первый мерчант + крупная сумма
  • Превышение лимита конверта
  • Дубликат за последние 5 минут
```

### Budget Advisor Agent (:8012)

```
FastAPI endpoints:
  POST /advice               — совет по конверту
  POST /advice/monthly-report — отчёт за месяц
  GET  /health

LangGraph граф:
  [load_spending_history] → [analyze_envelopes] → [llm_generate_advice] → [publish_advice]

Триггеры:
  • Kafka: balance.updated (конверт > 80% лимита)
  • HTTP: POST /advice (по запросу пользователя)
  • Cron: 1-е число месяца — monthly report
```

***

## Структура проекта

```
smart-envelopes-platform/
│
├── cmd/
│   ├── gateway/main.go
│   ├── accounts/main.go
│   ├── transactions/main.go
│   └── rules/main.go
│
├── internal/
│   ├── common/
│   │   ├── config/config.go
│   │   ├── logger/logger.go
│   │   ├── metrics/metrics.go
│   │   ├── postgres/pool.go
│   │   └── kafka/
│   │       ├── producer.go
│   │       └── consumer.go
│   │
│   ├── gateway/
│   │   ├── app.go
│   │   ├── handler/
│   │   │   ├── auth.go
│   │   │   ├── health.go
│   │   │   └── router.go
│   │   └── middleware/
│   │       ├── auth.go
│   │       ├── logging.go
│   │       ├── rate_limit.go
│   │       └── recovery.go
│   │
│   ├── accounts/
│   │   ├── app.go
│   │   ├── domain/
│   │   │   ├── user.go
│   │   │   ├── account.go
│   │   │   └── envelope.go
│   │   ├── repository/interfaces.go
│   │   ├── storage/postgres/
│   │   │   ├── user.go
│   │   │   ├── account.go
│   │   │   └── envelope.go
│   │   ├── service/
│   │   │   ├── account_svc.go
│   │   │   └── envelope_svc.go
│   │   ├── handler/
│   │   │   ├── account.go
│   │   │   ├── envelope.go
│   │   │   └── router.go
│   │   ├── listener/kafka_events.go
│   │   └── migrations/
│   │       ├── 001_init.sql
│   │       └── 002_indices.sql
│   │
│   ├── transactions/
│   │   ├── app.go
│   │   ├── domain/
│   │   │   ├── transaction.go
│   │   │   └── allocation.go
│   │   ├── repository/interfaces.go
│   │   ├── storage/postgres/
│   │   │   ├── transaction.go
│   │   │   └── allocation.go
│   │   ├── service/transaction_svc.go
│   │   ├── handler/
│   │   │   ├── transaction.go
│   │   │   └── router.go
│   │   ├── http/
│   │   │   └── categorization_client.go  # HTTP-клиент к Python агенту
│   │   ├── publisher/kafka_events.go
│   │   └── migrations/
│   │       ├── 001_init.sql
│   │       └── 002_indices.sql
│   │
│   └── rules/
│       ├── app.go
│       ├── domain/rule.go
│       ├── repository/interfaces.go
│       ├── storage/postgres/rule.go
│       ├── service/rule_svc.go
│       ├── engine/allocation_engine.go
│       ├── handler/
│       │   ├── rule.go
│       │   └── router.go
│       ├── listener/kafka_events.go      # Слушает transaction.categorized
│       ├── publisher/kafka_events.go
│       └── migrations/
│           └── 001_init.sql
│
├── pkg/
│   ├── dto/
│   │   ├── api_models.go
│   │   └── events.go
│   └── models/enums.go
│
├── agents/
│   ├── common/
│   │   ├── llm_factory.py               # Groq | Gemini | OpenAI | Mock
│   │   ├── config.py
│   │   ├── kafka_client.py
│   │   ├── http_client.py
│   │   ├── logger.py
│   │   └── models.py
│   │
│   ├── categorization/
│   │   ├── main.py
│   │   ├── router.py                    # POST /categorize
│   │   ├── agent.py                     # LangGraph StateGraph
│   │   ├── models.py
│   │   ├── prompts/categorize.py
│   │   ├── tools/rule_classifier.py
│   │   ├── kafka/
│   │   │   ├── consumer.py
│   │   │   └── producer.py
│   │   ├── config.py
│   │   ├── requirements.txt
│   │   └── Dockerfile
│   │
│   ├── anomaly_detection/
│   │   ├── main.py
│   │   ├── router.py                    # POST /detect
│   │   ├── agent.py
│   │   ├── models.py
│   │   ├── ml/detector.py               # IsolationForest
│   │   ├── kafka/
│   │   │   ├── consumer.py
│   │   │   └── producer.py
│   │   ├── config.py
│   │   ├── requirements.txt
│   │   └── Dockerfile
│   │
│   └── budget_advisor/
│       ├── main.py
│       ├── router.py                    # POST /advice
│       ├── agent.py
│       ├── models.py
│       ├── prompts/advisor.py
│       ├── tools/
│       │   ├── analytics_tool.py
│       │   └── forecast_tool.py
│       ├── kafka/
│       │   ├── consumer.py
│       │   └── producer.py
│       ├── config.py
│       ├── requirements.txt
│       └── Dockerfile
│
├── migrations/
│   ├── 001_accounts_schema.sql
│   ├── 002_transactions_schema.sql
│   ├── 003_rules_schema.sql
│   └── 004_indices.sql
│
├── deployments/
│   ├── docker-compose.yml
│   ├── Dockerfile.gateway
│   ├── Dockerfile.accounts
│   ├── Dockerfile.transactions
│   ├── Dockerfile.rules
│   └── k8s/
│
├── monitoring/
│   ├── prometheus.yml
│   └── grafana/dashboards/main.json
│
├── scripts/
│   ├── init-db.sh
│   ├── create-kafka-topics.sh
│   └── seed-data.sh
│
├── tests/
│   ├── testhelpers/
│   │   ├── db.go
│   │   ├── kafka.go
│   │   └── fixtures.go
│   └── integration/flow_test.go
│
├── docs/
│   ├── ARCHITECTURE.md
│   ├── AGENTS.md
│   ├── API.md
│   └── DATABASE.md
│
├── config/
│   ├── config.yaml
│   └── .env.example
│
├── go.mod
├── go.sum
├── Makefile
├── docker-compose.yml
├── .gitignore
├── .dockerignore
└── README.md
```

***

## Технический стек

| Компонент | Технология |
|---|---|
| Go сервисы | Go 1.21+, Fiber v2, Gin v1.9+, pgx v5, slog |
| Python агенты | Python 3.12, FastAPI, LangGraph, LangChain |
| LLM (облако) | Groq API (free) · Google Gemini API (free) · OpenAI |
| ML (аномалии) | scikit-learn IsolationForest |
| Message Broker | Apache Kafka 7.5 |
| Database | PostgreSQL 15 |
| Metrics | Prometheus + Grafana |
| Containerization | Docker + Docker Compose |

***

## Контейнеры

| Контейнер | Порт | Язык |
|---|---|---|
| gateway | 8000 | Go |
| accounts-service | 8001 | Go |
| transactions-service | 8002 | Go |
| rules-service | 8003 | Go |
| categorization-agent | 8010 | Python |
| anomaly-agent | 8011 | Python |
| budget-advisor-agent | 8012 | Python |
| kafka | 9092 | — |
| zookeeper | 2181 | — |
| postgres | 5432 | — |
| prometheus | 9090 | — |
| grafana | 3000 | — |

***

## .env.example

```dotenv
# LLM Provider: groq | gemini | openai | mock
LLM_PROVIDER=groq

GROQ_API_KEY=gsk_xxxx
GOOGLE_API_KEY=AIza_xxxx
OPENAI_API_KEY=sk-xxxx

KAFKA_BOOTSTRAP_SERVERS=kafka:29092

TRANSACTIONS_SERVICE_URL=http://transactions-service:8002
ACCOUNTS_SERVICE_URL=http://accounts-service:8001
CATEGORIZATION_AGENT_URL=http://categorization-agent:8010

CATEGORIZATION_CONFIDENCE_THRESHOLD=0.85
ANOMALY_SENSITIVITY=0.8
```
