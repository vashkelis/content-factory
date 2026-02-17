# content-factory

A content-writing pipeline that transforms your ideas into polished posts for Blog, LinkedIn, and X/Twitter.

**What it does:** You provide a topic and your unique context (experience, data, examples) — the pipeline generates structured content across multiple platforms, maintaining your voice and avoiding generic AI-slop.

## How It Works

```
Your Ideas (Brief) → Core Structure → Platform Drafts → Refine with Patches
```

1. **Brief** — Your topic, goal, audience, and the specific context that makes content unique
2. **ContentCore** — AI extracts thesis, key points, and angle from your brief
3. **Platform Drafts** — Renders the core into blog, LinkedIn, and X formats
4. **Patches** — Iteratively refine drafts with targeted edits

## Installation

Requires Python 3.11 or higher.

### 1. Check if you have Python 3.11+

```bash
python3.11 --version  # or python3.12, python3.13
```

If this works, skip to step 3. If not, install Python 3.11+.

### 2. Install Python 3.11+ (if needed)

**macOS (Homebrew):**
```bash
brew install python@3.11
```

**Ubuntu/Debian:**
```bash
sudo apt install python3.11 python3.11-venv
```

### 3. Create virtual environment and install

```bash
cd content-factory
python3.11 -m venv .venv  # use your installed version: python3.11, python3.12, etc.
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

### 1. Create a brief

A **brief** is where you define your content. It's a YAML file with your topic, audience, and most importantly — your unique context.

```bash
cf init
```

This creates `brief.yaml`. Edit it:

```yaml
topic: "Why most A/B tests fail"
goal: "inform"
audience: "product managers, growth engineers"
platform_targets:
  - blog
  - linkedin
  - x
language: "en"
context_notes: >
  In our last 20 experiments, only 3 moved the needle. 
  The pattern: tests with clear hypotheses worked; 
  tests that were "let's try this" failed.
  We now require a written hypothesis before any test.
constraints:
  tone: "direct, opinionated"
```

**Key insight:** The `context_notes` field is what makes your content unique. Include:
- Personal experience or observations
- Specific data, metrics, or results
- Examples or anecdotes
- Your opinion or stance

Without context, the AI will produce generic content.

### 2. Create a run

A **run** is a workspace for one piece of content.

```bash
cf generate brief.yaml
```

This creates `runs/20260217_141229_why-most-ab-tests-fail/` with:
- `brief.json` — Your brief (normalized)
- `meta.json` — Run status and metadata
- `core.json` — Will hold the generated content structure
- `blog.md`, `linkedin.md`, `x.md` — Platform drafts

### 3. Generate the content core

The **ContentCore** extracts thesis, key points, and angle from your brief.

```bash
cf core <run_id>
```

This calls the LLM and writes `core.json`:
```json
{
  "thesis": "A/B tests fail when they lack clear hypotheses",
  "angle": "Hypothesis-driven testing beats 'let's try this'",
  "points": [
    {"claim": "...", "support": ["..."]},
    ...
  ]
}
```

If your brief lacks context, the pipeline will ask clarifying questions.

### 4. Render platform drafts

```bash
cf render <run_id> -p linkedin
cf render <run_id> -p blog
cf render <run_id> -p x
```

Each command generates a platform-specific draft in `runs/<run_id>/linkedin.md`.

### 5. Refine with patches

Not happy with a draft? Apply targeted edits:

```bash
cf patch <run_id> -p linkedin -m "Add a specific example from our 3 successful tests"
```

The old version is backed up (`linkedin_v1.md`) and a changelog is saved.

## All Commands

| Command | Description |
|---------|-------------|
| `cf init` | Create starter brief.yaml and style_profile.yaml |
| `cf generate <brief.yaml>` | Create a new run from a brief |
| `cf list` | List recent runs |
| `cf show <run_id> -a <artifact>` | View an artifact (meta, brief, core, blog, linkedin, x) |
| `cf core <run_id>` | Generate ContentCore from brief |
| `cf render <run_id> -p <platform>` | Render platform-specific draft |
| `cf patch <run_id> -p <platform> -m "directive"` | Apply targeted edit to a draft |
| `cf clarify <run_id> -m "answers"` | Add context to a brief that needs clarification |

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

### Style Profile

Control the voice and avoid AI-generated phrases. Edit `style_profile.yaml`:

```yaml
forbidden_ai_smell:
  avoid_phrases:
    - "in a world where"
    - "let's dive in"
    - "game-changer"

voice:
  tone: "direct, specific, opinionated"
  perspective: "practitioner sharing real experience"
```

### Platform Specs

Each platform has constraints (length, formatting). Edit `specs/platform_linkedin.yaml` to change:
- Character limits
- Emoji policy
- Hashtag count
- Structure requirements

### Private Resources Directory

To keep your prompts and profiles private (separate repo):

```bash
export CONTENT_FACTORY_PRIVATE_DIR=/path/to/your-private-repo
```

Create this structure:
```
your-private-repo/
  prompts/        # Your custom LLM prompts
  profiles/       # Your personal style profile
  examples/       # Your example briefs
```

The pipeline checks your private directory first, then falls back to bundled defaults.

## Optional HTTP API

```bash
pip install -e .[api]
uvicorn content_factory.api:api --reload
```

Endpoints:
- `GET /runs` -- list runs
- `GET /runs/{run_id}/artifact/{name}` -- fetch artifact content
