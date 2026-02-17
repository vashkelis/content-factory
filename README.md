# content-factory

Reproducible content-writing pipeline for Blog, LinkedIn, and X/Twitter.
Supports various language outputs and iterative patching.

## Setup

Requires Python 3.11 or higher.

```bash
cd content-factory
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Set your OpenAI API key (required for `cf core`):

```bash
export OPENAI_API_KEY='sk-...'
```

### Private Resources (Optional)

If you have custom prompts, style profiles, or examples in a separate private repo:

```bash
export CONTENT_FACTORY_PRIVATE_DIR=/path/to/your/private/content-factory-private
```

The code will look for resources in your private directory first, then fall back to bundled defaults.
This allows you to keep your prompt engineering IP and personal style separate from the open-source code.

Private directory structure:
```
your-private-repo/
  prompts/
    core_synth.txt
    clarify.txt
    render_linkedin.txt
    patch.txt
    ...
  profiles/
    style_profile.yaml
  examples/
    brief_ru.yaml
    brief_en.yaml
```

## Quick Start

### 1. Create starter files

```bash
cf init
```

This creates `brief.yaml` and `style_profile.yaml` starter files in the current directory.

### 2. Generate a run from your brief

```bash
cf generate brief.yaml
```

This creates a run folder under `runs/` with placeholder artifacts:
- `brief.json` -- normalized brief
- `meta.json` -- run metadata (status, timestamps)
- `core.json` -- empty, awaiting generation
- `blog.md`, `linkedin.md`, `x.md` -- "(pending)"

### 3. List recent runs

```bash
cf list
```

### 4. Inspect a run artifact

```bash
cf show <run_id> -a meta
cf show <run_id> -a brief
cf show <run_id> -a core
```

Artifact names: `meta`, `brief`, `core`, `blog`, `linkedin`, `x`.

### 5. Generate ContentCore with LLM

```bash
cf core <run_id>
cf core <run_id> --model gpt-4o
```

This calls the LLM to synthesize a structured `ContentCore` from the brief,
validates the output, and writes `core.json`. The `meta.json` status updates
to `core_generated`.

### 6. Render a platform draft

```bash
cf render <run_id> -p linkedin
```

### 7. Apply a patch to refine the draft

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
    brief_en.yaml         # Sample English brief
  runs/                   # Generated content (gitignored)
```

## Customization

### Private Resources Directory

Set `CONTENT_FACTORY_PRIVATE_DIR` to override any bundled resource with your own version:

- `prompts/*.txt` — Your custom LLM prompts
- `profiles/style_profile.yaml` — Your personal voice and forbidden phrases
- `examples/*.yaml` — Your example briefs

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
