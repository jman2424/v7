# AI Sales Assistant — System Architecture

---

## Overview
AI Sales Assistant (AIV7) is a **multi-tenant AI sales platform** that merges:
- Deterministic catalog logic
- AI language understanding (LLM rewriter + retrieval)
- Real-time analytics and CRM insights  

Everything revolves around the **message pipeline** that goes from user input → router → retrieval → AI rewrite → response → analytics.

---

## 🧭 Request Flow

---

## ⚙️ Core Layers

### 1. **Routes**
`routes/*` handle HTTP entry points:
- `/chat_api` (web widget)
- `/whatsapp_webhook` (Twilio/WA Cloud)
- `/admin` and `/analytics`
They are **thin**, delegating to `services/` logic.

### 2. **Services**
Business logic lives here:
- `message_handler` – Orchestrates the flow
- `router` – Detects user intent / fuzzy match
- `analytics_service` – Logs KPIs, events
- `crm_service` – Manages leads / tags
- `self_repair` – Validates and auto-fixes data

### 3. **Retrieval**
Read-only access layer:
- `catalog_store` – Products, pricing, tags
- `geo_store` – Branches & postcode lookup
- `faq_store` – FAQs and quick answers
- `policy_store` – Delivery rules, hours
- `storage` – Versioned JSON I/O + schema validation

### 4. **AI Modes**
Strategy layer (`ai_modes/`):
- **V5** → pure deterministic  
- **V6** → hybrid: deterministic + LLM phrasing  
- **V7** → flagship: contextual tool-use (retrieval-augmented)

### 5. **Connectors**
Integration adapters:
- WhatsApp, Sheets, Maps, Billing, Email

### 6. **Dashboards**
`dashboards/` contains admin & widget UIs  
(front-end templates, JS charts, CRM tables).

### 7. **Monitoring & Scripts**
`monitoring/` probes health; `scripts/` run snapshot/backups.

---

## 🧠 Data & Mode Interaction
Each tenant lives in `business/<TENANT_KEY>/`.  
When `BUSINESS_KEY` loads, `app/container.py` wires all retrieval stores to that folder.

AI Mode reads `MODE` from env:
- V5: deterministic only  
- V6: deterministic + rewrite  
- V7: dynamic tool use (catalog, geo, CRM)

---

## 🪵 Logging & Analytics
- `logs/chatbot.log` → runtime per-request logs  
- `logs/analytics.log` → aggregated metrics  
- `logs/errors.log` → tracebacks  
Rotated daily by `app/logging_setup.py`.

---

## 🧰 Scaling & Deployment
- Stateless app → safe for horizontal scaling
- Versioned business data → safe updates
- Redis optional for cache/session
- Works on Render, Docker, Fly.io, or local Compose

---

## 📊 Module Map
| Layer | Example Module | Depends On | Consumed By |
|:--|:--|:--|:--|
| Routes | webchat_routes.py | Flask, services.message_handler | users |
| Services | message_handler.py | retrieval, ai_modes | routes |
| Retrieval | catalog_store.py | storage, cache | services |
| AI Modes | v7_flagship.py | retrieval, rewriter | services.message_handler |
| Connectors | sheets.py | google-api-python-client | analytics_service |
| Dashboards | admin.html | analytics_routes | business owners |

---

## 🧩 Summary
> **Philosophy:**  
> Deterministic first, AI second — every LLM call must have grounding and fallback.

This structure lets you add or remove tenants, connectors, or AI modes **without breaking the core pipeline**.
