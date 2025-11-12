# AI Modes Overview

## Introduction
The platform supports three operational modes — **V5**, **V6**, and **V7** — each representing a generation of intelligence and autonomy.  
The active mode is set by the `MODE` variable in the environment.

---

## V5: Legacy Mode
- Rule-based and deterministic.
- Direct template lookups; no generative rewriting.
- Fast and predictable.
- Ideal for small tenants or low-traffic bots.

**Used files:**  
`ai_modes/v5_legacy.py`, `services/router.py`, `retrieval/*`

---

## V6: Hybrid Mode
- Combines deterministic routing with lightweight LLM rewriting.
- Uses clarifiers and controlled AI tone from `policies/style.md`.
- Never fabricates facts; operates only on verified retrieval data.

**Used files:**  
`ai_modes/v6_hybrid.py`, `services/rewriter.py`, `policies/prompts/*.md`

---

## V7: Flagship Mode
- Full tool-use orchestration with dynamic planning.
- Queries multiple retrieval layers (catalog, delivery, branches).
- Performs fact-verification before response.
- Can chain small reasoning steps while staying grounded in tenant data.

**Used files:**  
`ai_modes/v7_flagship.py`, `ai_modes/contracts.py`, `services/message_handler.py`

---

## Grounding Rules
1. Never use unverified external knowledge.
2. All numerical facts must come from `retrieval/catalog_store.py`.
3. If a value is missing → respond with `"Not in my info."`
4. LLM rewriting happens *after* data is confirmed valid.

---

## Mode Comparison
| Feature | V5 | V6 | V7 |
|----------|----|----|----|
| Templates only | ✅ | ✅ | ✅ |
| AI Rewrite | ❌ | ✅ | ✅ |
| Fact Verification | ✅ | ✅ | ✅ |
| Tool-Use (multi-query) | ❌ | ❌ | ✅ |
| Self-Repair Integration | ❌ | ✅ | ✅ |

---

## Summary
Each mode extends the same interface defined in `ai_modes/contracts.py`.  
This ensures `services/message_handler.py` can swap modes dynamically without changing any business logic.
