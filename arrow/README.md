# Arrow

**Local-first SAM.gov contract opportunity intelligence.** Ingest the public bulk CSV, store opportunities in a local SQLite database, browse and search, rank leads against a small company profile, and optionally call a **local Ollama** model for structured explanations and summaries.

## What it does

- **Bulk CSV sync** — Download the official Contract Opportunities full CSV from SAM.gov (no API key) or ingest a local file.
- **Local SQLite** — All opportunity data and optional saved bookmarks stay under `~/.arrow/` by default.
- **Ranking & search** — Deterministic fit scoring and title/id search without any LLM.
- **Optional Ollama** — `why` / `summarize` use any model you configure via environment variables. No vendor cloud API.

## What it does *not* require

- **No SAM.gov API key** for core usage (bulk extract is public).
- **No custom or proprietary model** — use any Ollama tag you have pulled.
- **No company registration** with SAM to run locally.

## Quickstart

```bash
cd /path/to/this/repo
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
# or: pip install -e .

python -m arrow
```

In the REPL:

1. `sync bulk auto` — download + ingest (large file; be patient).
2. `profile init` then `profile mission …` / `profile naics …` — company context for rank/why.
3. `list`, `search title …`, `rank` — work without Ollama.
4. Optional: copy `.env.example` to `.env`, set `ARROW_ANALYSIS_MODEL` to a model you have pulled (`ollama pull …`), then `why 1` or `summarize 1`.

Copy `examples/company_profile.example.json` to `~/.arrow/company_profile.json` as a starting point, or use `profile init`.

## Configuration

| Variable | Purpose |
|----------|---------|
| `OLLAMA_HOST` | Ollama API base (default `http://127.0.0.1:11434`). |
| `ARROW_ANALYSIS_MODEL` | Ollama model tag for `why` / `summarize` (must be pulled locally). |
| `ARROW_OLLAMA_MODEL` | Legacy alias for `ARROW_ANALYSIS_MODEL`. |
| `ARROW_NO_AUTO_OLLAMA` | Set to `1` to stop Arrow from trying to start `ollama serve`. |
| `ARROW_BULK_CSV` | Default path for `sync bulk` without a path argument. |
| `ARROW_FULL_CSV_URL` | Override URL for `sync bulk auto`. |

See `.env.example` for placeholders.

## Ollama models

Arrow supports **any** local Ollama model suitable for short structured JSON-style reasoning. Users choose their own tag via `ARROW_ANALYSIS_MODEL`.

Example:

```bash
ollama pull qwen2.5:7b-instruct
export ARROW_ANALYSIS_MODEL=qwen2.5:7b-instruct
```

The files under `arrow/ollama_modelfiles/Modelfile.example.*` are **optional templates**, not dependencies. Rename, customize, and `ollama create` your own tags if you want tuned system prompts.

## Layout

- `arrow/` — Python package (REPL, TUI, sync, DB).
- `examples/` — Sample profile JSON (fake/generic).
- State created at runtime: `~/.arrow/arrow.db`, `~/.arrow/cache/`, `~/.arrow/archive/` (JSON exports), `~/.arrow/company_profile.json`.

## Development

```bash
pip install -e .
python -m arrow          # REPL
python -m arrow tui      # full-screen UI
```

## License

MIT — see `LICENSE`.

## Support the Project

If Arrow saves you time or helps you find better contracts, consider buying me a coffee.

Venmo: @quincyluce123

Arrow is built and maintained solo — support helps accelerate new features.

## Hire Me (Palantir 👀)

If you want something custom built, improvements to Arrow, or help with similar systems — I’m available.

I’m especially interested in work around:

data systems
infrastructure
intelligence / decision-support tools

Email: quincyluce@gmail.com

LinkedIn: https://www.linkedin.com/in/quincy-luce-ab2226326/


  
