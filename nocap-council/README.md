# nocap-council

Python council for the No Cap paper-vs-code verifier. Single-writer, three-judge architecture (Spec, Plan, Code, Polygraph) on Gemma 4 + Gemini Flash-Lite.

## Setup

```bash
cd nocap-council
uv sync
python -c "import nocap_council"  # exits 0
```

`GOOGLE_API_KEY` must be set (free tier from <https://ai.dev>); see repo-root `.env`.

## Smoke test the LLM client

```bash
uv run python -m nocap_council.client
```
