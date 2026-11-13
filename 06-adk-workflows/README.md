# 06: Google ADK 2.0 Workflows + Gemini Decisions API

Demonstrates how to combine **Google ADK 2.0 graph-based `Workflow`s (`google-adk >= 2.14.0`)** with the **Gemini Decisions API (`gemini-decision-1`)**—and benchmarks it head-to-head against pure ADK 2.0 `Workflow`s that use `LlmAgent(output_schema=...)` nodes for routing, compliance fan-out, and loop quality checks.

---

## Why `decisions_helper.py` Calls `/v1beta/decisions` Over `httpx`

1. **Zero package conflicts:** `google-adk 2.14.x` currently pins `google-genai>=2.30,<3.0`, while `client.decisions.create` was added in `google-genai>=3.2.0`. Calling `POST https://generativelanguage.googleapis.com/v1beta/decisions` with `httpx` (installed automatically with `google-adk`) works cleanly inside any ADK 2.x environment.
2. **Cross-turn keep-alive safety:** ADK's `Runner` creates and closes an internal `anyio` task group per invocation; holding a single `httpx.AsyncClient` across separate `run_async` calls causes `httpcore.ReadTimeout` on reused sockets. Wrapping a persistent `httpx.Client` with `asyncio.to_thread` preserves warm TLS connections safely across runs.

---

## Quick Setup (Python 3.11 or 3.12)

`google-adk 2.x` supports Python `3.11` and `3.12`. Using `uv` (or `python3.12 -m venv`):

```bash
cd 06-adk-workflows

uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -r requirements.txt

export GEMINI_API_KEY="YOUR_GEMINI_API_KEY"
```

---

## 1. Run the Head-to-Head Benchmark (`benchmark_workflows.py`)

```bash
python benchmark_workflows.py
```

Runs 5 real ADK 2.0 `Workflow` scenarios live:
* **Case 0 (`amount_usd > 5000`):** Pure Python `FunctionNode` (`~3.6 ms`, `0` tokens) — when structured fields already exist, no AI call is needed.
* **Case 1 (Natural-language shipping check $\rightarrow$ Python tool):** Compares `gemini-3.8-flash` gate (`~3,498 ms`) vs. `gemini-2.5-flash-lite` gate (`~1,102 ms`) vs. `gemini-decision-1` `FunctionNode` (`~396 ms`, `0` output tokens).
* **Case 2a (Multimodal PDF invoice claim $\rightarrow$ auto-credit):** Reads `../03-multimodal-triage/sample_invoice_8812.pdf` with zero OCR (`~843 ms` vs. `2,834–5,274 ms`).
* **Case 2b (Unverified `$240` lost-receipt claim $\rightarrow$ HITL `RequestInput` pause):** Pauses the ADK 2.0 `Workflow` cleanly when `auto_execute_prob` drops to `0.0202`.
* **Case 3 (8-rule compliance check):** Compares an ADK `JoinNode` fanning out to 8 `LlmAgent`s (`~1,518 ms`, `160` output tokens) vs. one `gemini-decision-1` pass (`~388 ms`, `0` output tokens).
* **Case 4 (Draft-and-verify `Workflow` loop):** Compares a Critic `LlmAgent` loop gate (`~2,048 ms` total) vs. a `gemini-decision-1` loop gate (`~1,357 ms` total).

---

## 2. Try It Interactively in `adk web`

`adk_decisions_agent/` follows ADK's standard agent package layout (`root_agent = Workflow(...)`), so you can launch ADK's interactive web UI directly from `06-adk-workflows/`:

```bash
adk web --port 8000
```

Open `http://127.0.0.1:8000`, select **`adk_decisions_agent`**, and test:
* *"Has parcel #19028 left the warehouse yet?"* $\rightarrow$ takes the fast Python tool edge (`0` LLM calls).
* *"Please refund $240 for our client dinner—I lost the receipt."* $\rightarrow$ triggers ADK 2.0's interactive `RequestInput` approval prompt.
* *"CRITICAL: Checkout database connection pool exhausted with HTTP 500s."* $\rightarrow$ escalates down the `COMPLEX_INVESTIGATION` edge to `gemini-3.8-flash`.
