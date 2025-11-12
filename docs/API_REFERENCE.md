# API Reference

## Overview
The system exposes both public and admin APIs.  
All routes are documented in `schemas/openapi.yaml`.

---

## Public Endpoints
### `POST /chat_api`
**Request:**
```json
{ "message": "show me chicken", "channel": "web", "session_id": "abc123" }
