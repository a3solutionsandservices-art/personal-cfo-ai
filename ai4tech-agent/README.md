# AI4Tech Intelligence Agent

A standing, automated pipeline that turns a stream of external content —
beginning with podcasts — into a themed, role-relevant briefing with concrete
recommended actions. It exists to keep an AI4Tech lead ahead of the field on
everything that bears on making the org's software and product lifecycles
AI-native.

This is an implementation of the AI4Tech Intelligence Agent PRD (v1.1). It is
**not** a podcast summarizer: the product is the relevance filter and the
role-interpretation layer that sit on top of summarization — the parts that
decide what is worth the lead's attention and what to do about it.

## Architecture

A linear pipeline, each stage a replaceable component behind an interface
(PRD §4):

```
SourceAdapter   →  new items (audio URL / text + metadata) from a feed
  ↓
Transcriber     →  transcript (text + timestamps), cached by GUID
  ↓
Segmenter       →  topic-coherent segments (timestamped)
  ↓
Classifier      →  segment → {theme, confidence} against the taxonomy
  ↓
Scorer          →  relevance × novelty × actionability → keep / drop
  ↓
Interpreter     →  role-grounded action(s) per kept segment (context injected)
  ↓
BriefAssembler  →  cluster by theme, dedup, rank, cap
  ↓
Deliverer       →  markdown file / email
```

Two cross-cutting components feed the pipeline:

- **ContextProvider** — supplies the lead's portfolio context to the Interpreter
  and theme state to the Scorer. The default `StaticContextProvider` reads
  `config/portfolio.md` and the taxonomy; any external context platform can back
  it by implementing the same two-method interface.
- **StateStore** — durable SQLite record of processed items (idempotency),
  the transcript cache, the surfaced-signal ledger (novelty), run history, and
  quarantined items.

### The keystone: the theme taxonomy

Every downstream decision hangs off `config/themes.yaml` (PRD §5). It is
human-editable configuration and a first-class deliverable. Each theme's
`signal_definition` (with explicit "NOT signal" examples) is the contract the
Classifier and Scorer use; `weight` scales the final score; `current_state`
feeds novelty judgement and action drafting. A malformed file fails fast.

## Quick start

```bash
cd ai4tech-agent
pip install -e ".[dev]"            # core deps + pytest
# optional real backends:
pip install -e ".[llm,stt]"       # anthropic (Claude) + openai (Whisper)

cp .env.example .env              # add ANTHROPIC_API_KEY / OPENAI_API_KEY if you have them
```

Run it:

```bash
ai4tech run                       # process sources, deliver a brief to ./out
ai4tech dry-run                   # execute offline, no delivery, write a run log
ai4tech status                    # store stats + any quarantined items
ai4tech replay                    # identify the most recent delivered run
```

### Offline / deterministic mode

The whole pipeline runs with **no API keys**. When `ANTHROPIC_API_KEY` is unset,
classification/scoring/interpretation use a deterministic heuristic judge
(keyword-overlap against each theme's `signal_definition`); when `OPENAI_API_KEY`
is unset, audio items without a cached transcript are quarantined while textual
sources (newsletters) still flow. This is what makes `dry-run` and the test
suite work anywhere, and lets you validate the wiring before paying for any
calls. Set the keys to switch to Claude (Haiku for classify/score, Sonnet/Opus
for interpret) and Whisper — no code changes, just config + env.

## Configuration

All tunables live in `config/` (PRD §10) — no constants buried in code:

| File | What it controls |
|------|------------------|
| `themes.yaml` | The theme taxonomy (the keystone). Signal definitions, weights, current state, action templates. |
| `sources.yaml` | Feeds: adapter type, URL, enable/disable, lookback window. |
| `settings.yaml` | Score weights & threshold, brief cap, segmenter sizing, **model IDs**, transcription provider, delivery target, retries/budget. |
| `portfolio.md` | The lead's mandate and remit, injected into the Interpreter. |
| `.env` | Secrets (API keys, SMTP creds). Never commit. |

Model IDs are config (`settings.yaml › models`), defaulting to
`claude-haiku-4-5` for the high-volume classify/score stages and
`claude-sonnet-4-6` for interpretation (swap to `claude-opus-4-8` for maximum
synthesis quality).

## Scheduling

Scheduling is external and boring (FR-ORC-2). A scheduled GitHub Actions
workflow (`.github/workflows/scheduled-run.yml`) invokes `ai4tech run` weekly;
cron works identically. Runs are idempotent, so a re-run after a crash resumes
without re-processing completed items or re-sending a brief.

## Testing

```bash
pytest
```

The suite encodes the PRD's acceptance criteria (§12):

| Test | Acceptance criterion |
|------|----------------------|
| `test_classification.py::test_classifier_accuracy_on_golden` | AC-1 — golden-set classification accuracy |
| `test_classification.py::test_noise_stays_below_threshold` | AC-2 — noise set stays below threshold |
| `test_pipeline.py::test_idempotent_rerun_does_not_resend` | AC-3 — idempotency, no duplicate brief |
| `test_pipeline.py::test_traceability_*` | AC-4 — every action cites a real transcript span |
| `test_novelty.py` | AC-5 — re-processing the same signal surfaces no new novelty |
| `test_pipeline.py::test_cost_stays_under_budget` | AC-6 — per-run cost reported, within ceiling |

Golden fixtures (a labelled episode with signal and noise segments) live in
`tests/golden/`.

## Project layout

```
ai4tech-agent/
  pyproject.toml
  config/        themes.yaml · sources.yaml · settings.yaml · portfolio.md
  src/ai4tech/
    sources/     SourceAdapter + PodcastAdapter + NewsletterAdapter
    transcribe/  Transcriber + Whisper/Null backends + GUID cache
    segment/     Segmenter
    classify/    Classifier
    score/       Scorer
    interpret/   Interpreter
    brief/       BriefAssembler
    deliver/     Deliverer + markdown/email targets
    context/     ContextProvider + StaticContextProvider
    state/       StateStore (SQLite)
    llm.py       Judge backends (Anthropic + heuristic) + retries
    embeddings.py  novelty embedder
    config.py · taxonomy.py · pipeline.py · cli.py
  tests/         + golden/ fixtures
```

## Build milestones (PRD §11)

- **M0 Scaffold** — config loading, SQLite StateStore, CLI, `dry-run`. ✅
- **M1 Ingest + transcribe** — PodcastAdapter, Whisper adapter, transcript cache. ✅
- **M2 Taxonomy + classify** — taxonomy loader, Segmenter, Classifier. ✅
- **M3 Score + novelty** — Scorer with three sub-scores + embedding ledger. ✅
- **M4 Interpret + brief** — StaticContextProvider, cited actions, BriefAssembler. ✅
- **M5 Deliver + schedule** — markdown/email deliverer, scheduled CI, empty-run notice. ✅
- **M6 Second source** — NewsletterAdapter, added with no downstream changes (proves G5). ✅
- **M7 External context** — swap `StaticContextProvider` for an external platform behind the same interface. *(interface-ready)*

## Open decisions (PRD §15) — shipped defaults

These are the stakeholder's calls; the implementation ships sensible defaults
that are all config-changeable:

1. **Cadence** — weekly digest (scheduled-run.yml cron `0 13 * * 1`).
2. **Delivery target** — markdown file (`settings.yaml › delivery.target`,
   switchable to `email`).
3. **Action ceiling** — 12 per run (`settings.yaml › brief.max_actions`).
4. **Source list** — placeholders in `sources.yaml`; replace with the lead's
   actual three-to-five podcasts.
5. **Taxonomy sign-off** — the lifecycle-anchored themes in `themes.yaml` are
   the PRD's starting point, ready for the lead to edit.

## Notes & scope

- Python ≥ 3.11 (the PRD targets 3.12; the code is 3.11-compatible). The dev
  sandbox runs 3.11.
- Transcripts are internal intermediates only — never republished (PRD §13).
- Non-goals respected: no real-time/streaming, no home-grown STT engine, no
  chat UI. STT and LLM calls are commodities behind adapters.
