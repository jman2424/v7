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
