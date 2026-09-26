# ADlyser

**Context-aware ad-break placement for long-form Bengali drama.**
Built for the hoichoi AI Builders Hackathon'26, Problem 1: *Context-Aware Video Segmentation & Intelligent Ad Placement*.

ADlyser watches an episode and answers three questions for every possible ad break:

| | Question |
|---|---|
| **Where** | Is this a natural, non-jarring place to cut? No mid-sentence cuts. |
| **Whether** | Is a break warranted here, given the pacing rules (max breaks per hour, minimum gap, ad-load cap)? |
| **What** | Which brand fits this moment? The scene's dominant activity decides, and a brand's negative contexts are a hard block. |

It outputs an IAB **VMAP 1.0** manifest (inline VAST 3.0), a **debug JSON** explaining every decision, and a **web player** that cuts to the ad and resumes.

> 🚧 Work in progress. The live demo link, explainer video and full setup steps will be added before submission.

## Approach: measure with tools, decide with AI, guard with code

1. **Measure, pause-first** (deterministic): start from the audio. Find silences (Silero VAD), keep only those that contain a camera cut or fade to black (PySceneDetect, ffmpeg), and transcribe the Bengali dialogue (faster-whisper). Mid-sentence cuts are impossible by construction.
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
| Perception | PySceneDetect, Silero VAD, faster-whisper, ffmpeg |
| AI | DeepSeek (vision + text) behind a swappable provider interface (self-hosted / Bedrock ready), bge-m3 embeddings |
| Frontend | React, Vite, TypeScript, Tailwind, Video.js |
| Output | VMAP 1.0 + VAST 3.0, debug JSON |
| Deploy | Docker, Caddy, AWS EC2 |

## Quick start

```bash
uv sync
cp .env.example .env   # add your DEEPSEEK_API_KEY
uv run pytest
```

The pipeline, API and web app commands will be documented here as they land.

## Brands

All brands in `catalogue/` are **fictional**, created for this hackathon.

## License

MIT
