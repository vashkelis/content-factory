# content-factory

Reproducible content-writing pipeline for Blog, LinkedIn, and X/Twitter.
Supports RU/EN outputs and iterative patching.

## Setup

```bash
cd content-factory
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Set your OpenAI API key (required for `cf core`):

```bash
export OPENAI_API_KEY='sk-...'
```

## Quick Start

### 1. Generate a run from a brief

```bash
cf generate examples/brief_ru.yaml
```

This creates a run folder under `runs/` with placeholder artifacts:
- `brief.json` -- normalized brief
- `meta.json` -- run metadata (status, timestamps)
- `core.json` -- empty, awaiting generation
- `blog.md`, `linkedin.md`, `x.md` -- "(pending)"

### 2. List recent runs

```bash
cf list
```

### 3. Inspect a run artifact

```bash
cf show <run_id> -a meta
cf show <run_id> -a brief
cf show <run_id> -a core
```

Artifact names: `meta`, `brief`, `core`, `blog`, `linkedin`, `x`.

### 4. Generate ContentCore with LLM

```bash
cf core <run_id>
cf core <run_id> --model gpt-4o
```

This calls the LLM to synthesize a structured `ContentCore` from the brief,
validates the output, and writes `core.json`. The `meta.json` status updates
to `core_generated`.

### 5. Append a patch directive (stub)

```bash
cf patch <run_id> --platform blog -m "Make the introduction shorter"
```

Patch application is not yet implemented; directives are logged for later use.

## Project Structure

```
content-factory/
  pyproject.toml          # Package config, dependencies, CLI entry point
  src/content_factory/
    cli.py                # Typer CLI commands
    models.py             # Pydantic v2 data models
    storage.py            # Filesystem run management
    resources.py          # Load prompts/profiles/specs from repo
    graph.py              # LangGraph pipeline (core synthesis)
    llm/
      base.py             # Abstract LLM provider + structured output
      openai_provider.py  # OpenAI implementation
    api.py                # Optional FastAPI (pip install -e .[api])
  profiles/
    style_profile.yaml    # Voice rules, forbidden AI-smell phrases
  specs/
    platform_blog.yaml    # Blog constraints
    platform_linkedin.yaml
    platform_x.yaml
  prompts/
    core_synth.txt        # Prompt for ContentCore generation
    render_*.txt          # Prompts for rendering (future)
    voice_*.txt           # Prompts for voice editing (future)
    qa.txt                # QA prompt (future)
    patch.txt             # Patch prompt (future)
  examples/
    brief_ru.yaml         # Sample Russian brief
    brief_en.yaml         # Sample English brief
  runs/                   # Generated content (gitignored)
```

## Customization

### Style Profile

Edit `profiles/style_profile.yaml` to add forbidden phrases or adjust voice:

```yaml
forbidden_ai_smell:
  avoid_phrases:
    - "in a world where"
    - "let's dive in"
```

### Prompts

All prompts live in `prompts/` as plain text with `{placeholder}` variables.
Edit them to adjust LLM behavior.

### Platform Specs

Edit `specs/platform_*.yaml` to change length limits, structure rules, etc.

## Optional HTTP API

```bash
pip install -e .[api]
uvicorn content_factory.api:api --reload
```

Endpoints:
- `GET /runs` -- list runs
- `GET /runs/{run_id}/artifact/{name}` -- fetch artifact content
