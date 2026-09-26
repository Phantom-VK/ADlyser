# ADlyser

**Live demo: https://13-126-111-29.sslip.io**

**Context-aware ad-break placement for long-form Bengali drama.**
Built for the hoichoi AI Builders Hackathon'26, Problem 1: *Context-Aware Video Segmentation & Intelligent Ad Placement*.

ADlyser watches an episode and answers three questions for every possible ad break:

| | Question |
|---|---|
| **Where** | Is this a natural, non-jarring place to cut? No mid-sentence cuts. |
| **Whether** | Is a break warranted here, given the pacing rules (max breaks per hour, minimum gap, ad-load cap)? |
| **What** | Which brand fits this moment? The scene's dominant activity decides, and a brand's negative contexts are a hard block. |

It outputs an IAB **VMAP 1.0** manifest (inline VAST 3.0), a **debug JSON** explaining every decision, and a **web player** that cuts to the ad and resumes.

## Architecture

<p align="center">
  <img src="docs/pipeline.svg" alt="The ADlyser pipeline: a LangGraph state graph from catalogue and measure through the AI judgement nodes to the brand-safety block and the VMAP emitter, with the reviewer's two veto loops back to pacing and matching." width="820">
</p>

The diagram is generated from the compiled graph by `uv run python -m scripts.graph_image`, so it cannot
drift from the code: the script fails if a node is added or renamed. Violet nodes are where a model
decides, grey are where code enforces, and the dashed edges are the reviewer's veto loops — a veto sends
the break back for another brand, or sends the pacing solver to the next-best break point.

## Approach: measure with tools, decide with AI, guard with code

1. **Measure, pause-first** (deterministic): start from the audio. Find silences (Silero VAD), keep only those that contain a camera cut or fade to black (PySceneDetect, ffmpeg), and optionally transcribe the dialogue (Groq `whisper-large-v3`). Mid-sentence cuts are impossible by construction.
   The transcript is noisy context only: it can add evidence for a safety tag but never clears one, candidates come from the audio alone, and the pipeline works the same without it.
2. **Decide** (AI agents in a LangGraph pipeline):
   - **StretchAnalyst** (vision): looks at frames and dialogue across each stretch between candidate pauses, and tags its activity, mood and safety topics.
   - **BoundaryJudge** (vision): decides whether each pause is a real scene change and how natural a break it is. Confirmed changes form the scene segmentation.
   - **CatalogueNormaliser**: turns any brand catalogue (JSON, CSV or free text) into one schema.
   - **BrandMatcher**: shortlists brands by embeddings, then an LLM re-ranks them.
   - **BreakReviewer**: can veto a break.
3. **Guard** (code, never an LLM):
   - Cuts only in real silence, snapped to a shot cut.
   - Pacing is solved as a constraint problem.
   - Negative contexts are a hard block: a brand is ruled out if its blocked topics appear in the scene before **or** the scene after the break.
   - When in doubt, ADlyser drops the brand or the break, never the rule.

Every decision is recorded with its evidence and shown in the player's **Decision Trace**. A new brand can be added and re-matched with no code changes.

## Tech stack

| Layer | Choice |
|---|---|
| Backend | Python 3.12, uv, FastAPI, Pydantic v2, LangGraph |
| Perception | PySceneDetect, Silero VAD, ffmpeg, optional Groq whisper-large-v3 transcript |
| AI | DeepSeek (vision + text) behind a swappable provider interface (self-hosted / Bedrock ready), bge-m3 embeddings |
| Frontend | React, Vite, TypeScript, Video.js |
| Output | VMAP 1.0 + VAST 3.0, debug JSON |
| Deploy | Terraform, AWS EC2, Caddy (HTTPS on sslip.io), systemd |

## Quick start

```bash
uv sync
cp .env.example .env   # add your DEEPSEEK_API_KEY
uv run pytest
```

The pipeline, API and web app commands will be documented here as they land.

## Deploy

The demo runs on one AWS EC2 `c6i.2xlarge` (ap-south-1) with an Elastic IP, Caddy for automatic HTTPS on an `<ip>.sslip.io` host, and a systemd service for the API. Terraform creates all of it:

```bash
cd deploy/terraform
terraform init
terraform apply -var "ssh_cidr=$(curl -4 -s https://ifconfig.me)/32"
```

Then copy the videos, `data/` and `.env` over SSH, install, and start the service as described in [deploy/terraform/README.md](deploy/terraform/README.md). Tear everything down with `terraform destroy`.

## Brands

All brands in `catalogue/` are **fictional**, created for this hackathon. The current 12:

- **Lotus Lassi** (Beverage)
- **Grain & Grove** (Food)
- **Nexora Insurance** (Insurance)
- **Roamora** (Travel)
- **PulseGrid** (Telecom)
- **Morrow Thread** (Fashion)
- **Hearthline** (Home)
- **BrightStep** (Education)
- **Sundrop Pantry** (Grocery)
- **Velora Care** (Personal Care)
- **CrispCart** (Quick Commerce)
- **Leafline Tea** (Beverage)

A brand's negative contexts are mapped to safety tags and unioned with a default floor (death and grief, funeral rituals, sexual content), so no brand is a wildcard.

## Known limitations and next steps

- Speech-based pauses can land in music bridges; an audio-energy gate would catch them.
- Dropped breaks are not back-filled; pacing should re-run after a drop.
- Reviewer vetoes need frames from both sides of the cut.
- Mood and tone are not yet used for brand fit.

## License

MIT
