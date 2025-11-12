# System Architecture

## Overview
AI Sales Assistant (AI Mode) is a modular Flask-based framework designed to serve chat and sales automation across multiple channels (WhatsApp, Web, Admin).  
It follows a clear layered structure separating presentation, service logic, and data retrieval.

---

## Core Request Flow
1. **User Message** → from Web or WhatsApp.
2. **routes/** (`webchat_routes.py` or `whatsapp_routes.py`) → Receives the request.
3. **services/message_handler.py** → Main orchestrator:
   - Detects intent and entities via `router.py`.
   - Pulls product and store data via `retrieval/*`.
   - Passes context to AI Mode (`ai_modes/v5_legacy.py`, `v6_hybrid.py`, or `v7_flagship.py`).
   - Rewrites output with `rewriter.py` for tone and clarity.
4. **Response** → Returns formatted text back to the channel.

---

## Module Map
| Layer | Description | Key Files |
|-------|--------------|-----------|
| **routes/** | Handles HTTP endpoints | `webchat_routes.py`, `whatsapp_routes.py`, `admin_routes.py` |
| **services/** | Business logic orchestration | `message_handler.py`, `router.py`, `sales_flows.py` |
| **retrieval/** | Data loading and validation | `catalog_store.py`, `geo_store.py`, `policy_store.py` |
| **ai_modes/** | Determines how the AI responds | `v5_legacy.py`, `v6_hybrid.py`, `v7_flagship.py` |
| **connectors/** | External APIs and integrations | `whatsapp.py`, `sheets.py`, `billing.py` |
| **dashboards/** | Admin and web UI | `templates/`, `static/` |
| **monitoring/** | Health probes and alerts | `heartbeat.py`, `probes.py` |

---

## Mode Selection
The `MODE` variable in `.env` or `app/config.py` determines which AI engine is used:
- **V5** – fully rule-based (legacy mode)
- **V6** – hybrid deterministic + AI rewrite
- **V7** – flagship autonomous planner (tool-use, verification)

---

## Summary
Every request flows through a consistent pipeline:
**Route → MessageHandler → Mode → Rewriter → Analytics → Response**  
This modular design allows each tenant to have its own business data while keeping the core logic universal.
