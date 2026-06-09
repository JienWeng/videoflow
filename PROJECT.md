# AI Video Workflow Studio — Project Plan

## 1. Goal

Build a lightweight local-first AI video workflow tool for creating scripts, scenes, shots, prompts, and video generations using persistent characters and reusable assets.

The system should allow users to:

* Upload character, image, video, audio, and location assets
* Auto-tag and describe assets using AI
* Build persistent character bibles
* Generate scripts, scenes, and shots
* Convert scenes into MiniMax / Kling / AtlasCloud payloads
* Run video generation jobs
* Preview outputs
* See relationships between characters, assets, scenes, shots, and outputs

---

## 2. Recommended Stack

```text
Frontend: SvelteKit
Backend: FastAPI
Database: SQLite
Schema validation: Pydantic
Vector memory: ChromaDB
File storage: local /storage folder
Video processing: FFmpeg
Background jobs: Python asyncio / lightweight worker
AI text model: OpenAI / Claude / Gemini
Video providers: MiniMax, Kling, AtlasCloud
```

Why SvelteKit:

* Lighter than React/Next.js
* Less boilerplate
* Great for custom UI
* Easy API integration
* Good for media-heavy dashboards
* Works well for local-first apps

---

## 3. Project Structure

```text
ai-video-studio/
  backend/
    app/
      main.py
      config.py
      database.py

      models/
        character.py
        asset.py
        scene.py
        shot.py
        render_job.py

      schemas/
        character_schema.py
        asset_schema.py
        scene_schema.py
        shot_schema.py
        provider_schema.py

      agents/
        asset_recogniser.py
        character_memory.py
        script_agent.py
        scene_agent.py
        shot_agent.py
        prompt_agent.py
        render_agent.py
        qa_agent.py

      providers/
        minimax.py
        kling.py
        atlascloud.py

      services/
        asset_service.py
        scene_service.py
        render_service.py
        vector_service.py

      storage/
        characters/
        assets/
        outputs/

    requirements.txt

  frontend/
    src/
      routes/
        +layout.svelte
        +page.svelte
        assets/
          +page.svelte
        characters/
          +page.svelte
        scenes/
          +page.svelte
        render/
          +page.svelte
        graph/
          +page.svelte

      lib/
        api.ts
        components/
          AssetCard.svelte
          CharacterCard.svelte
          SceneCard.svelte
          ShotCard.svelte
          VideoPreview.svelte
          RelationshipGraph.svelte

    package.json

  storage/
    assets/
    characters/
    outputs/

  db.sqlite
  README.md
```

---

## 4. Core Concept

The AI should never directly call MiniMax, Kling, or AtlasCloud.

Instead:

```text
User input
→ AI agent creates structured JSON
→ Pydantic validates JSON
→ System stores JSON
→ Provider adapter converts JSON into API payload
→ Video provider generates output
→ Output is saved and linked back
```

---

## 5. Core Data Relationships

```text
Project
 ├── Characters
 │    └── Reference Assets
 ├── Assets
 │    └── Tags
 ├── Scripts
 ├── Scenes
 │    └── Shots
 │         └── Render Jobs
 │              └── Render Outputs
```

Example relationship:

```text
Character: Ava
  ↓
Reference Asset: ava_front.png
  ↓
Scene: Neon Alley Entrance
  ↓
Shot: Ava walks into alley
  ↓
Render Job: MiniMax image-to-video
  ↓
Output: output_001.mp4
```

---

## 6. Database Tables

### characters

```text
id
name
description
appearance
personality
visual_rules_json
voice_rules_json
reference_asset_ids_json
created_at
updated_at
```

### assets

```text
id
type
name
file_path
tags_json
description
character_id
metadata_json
created_at
updated_at
```

Asset types:

```text
character_reference
location
prop
video_reference
audio_reference
voice
output_video
```

### scenes

```text
id
title
summary
duration
aspect_ratio
character_ids_json
asset_ids_json
scene_json
created_at
updated_at
```

### shots

```text
id
scene_id
shot_order
duration
prompt
camera
movement
asset_ids_json
shot_json
created_at
updated_at
```

### render_jobs

```text
id
scene_id
shot_id
provider
model
status
request_json
response_json
error
created_at
updated_at
```

### render_outputs

```text
id
render_job_id
video_path
thumbnail_path
score
selected
notes
created_at
updated_at
```

---

## 7. Pydantic Schemas

### Asset Metadata

```python
from pydantic import BaseModel
from typing import Literal

class AssetMetadata(BaseModel):
    asset_id: str
    asset_type: Literal[
        "character_reference",
        "location",
        "prop",
        "video_reference",
        "audio_reference",
        "voice",
        "output_video"
    ]
    name: str
    tags: list[str]
    description: str
    character_id: str | None = None
```

### Character Bible

```python
class CharacterBible(BaseModel):
    character_id: str
    name: str
    appearance: str
    personality: str
    visual_rules: list[str]
    voice_rules: list[str] = []
    reference_asset_ids: list[str]
```

### Scene Spec

```python
from typing import Literal

class ShotSpec(BaseModel):
    shot_id: str
    duration: int
    prompt: str
    camera: str | None = None
    movement: str | None = None
    asset_ids: list[str] = []

class SceneSpec(BaseModel):
    scene_id: str
    title: str
    summary: str
    duration: int
    aspect_ratio: Literal["16:9", "9:16", "1:1"]
    character_ids: list[str]
    asset_ids: list[str]
    shots: list[ShotSpec]
```

### Render Spec

```python
class RenderSpec(BaseModel):
    provider: Literal["minimax", "kling", "atlascloud"]
    model: str
    scene_id: str
    shot_id: str | None = None
    duration: int
    aspect_ratio: Literal["16:9", "9:16", "1:1"]
    prompt: str
    image_asset_ids: list[str] = []
    video_asset_ids: list[str] = []
    audio_asset_ids: list[str] = []
    sound: bool = False
    keep_original_sound: bool = False
    multi_shot: bool = False
```

---

## 8. AI Agent Phases

### 1. Asset Recogniser Agent

Purpose:

```text
Analyze uploaded assets and generate tags, description, asset type, and possible character link.
```

Input:

```text
Image, video, audio, or user description
```

Output:

```json
{
  "asset_type": "character_reference",
  "name": "Ava front view",
  "tags": ["female", "black jacket", "short hair", "main character"],
  "description": "Ava has short black hair and wears a black leather jacket.",
  "character_id": "CHAR_AVA"
}
```

---

### 2. Character Memory Agent

Purpose:

```text
Maintain persistent character identity.
```

Output:

```json
{
  "character_id": "CHAR_AVA",
  "name": "Ava",
  "appearance": "Short black hair, sharp eyes, black leather jacket.",
  "personality": "Calm, mysterious, confident.",
  "visual_rules": [
    "Always keep short black hair",
    "Always wear black leather jacket",
    "Do not change face shape"
  ],
  "reference_asset_ids": ["ASSET_AVA_FRONT"]
}
```

---

### 3. Script Agent

Purpose:

```text
Turn story idea into short script.
```

Output:

```json
{
  "title": "Neon Alley",
  "summary": "Ava follows a mysterious signal through a rainy city.",
  "scenes": [
    {
      "title": "Alley Entrance",
      "summary": "Ava walks into the alley and notices a strange light."
    }
  ]
}
```

---

### 4. Scene Agent

Purpose:

```text
Break script into scenes with duration, characters, and assets.
```

Output:

```json
{
  "scene_id": "SCENE_001",
  "title": "Alley Entrance",
  "duration": 8,
  "aspect_ratio": "16:9",
  "character_ids": ["CHAR_AVA"],
  "asset_ids": ["LOC_NEON_ALLEY"]
}
```

---

### 5. Shot Agent

Purpose:

```text
Turn scene into shots.
```

Output:

```json
{
  "shots": [
    {
      "shot_id": "SHOT_001",
      "duration": 4,
      "prompt": "Wide shot of Ava entering the rainy neon alley.",
      "camera": "wide shot",
      "movement": "slow dolly forward",
      "asset_ids": ["CHAR_AVA", "LOC_NEON_ALLEY"]
    },
    {
      "shot_id": "SHOT_002",
      "duration": 4,
      "prompt": "Close-up of Ava turning toward a glowing signal.",
      "camera": "close-up",
      "movement": "slow push in",
      "asset_ids": ["CHAR_AVA"]
    }
  ]
}
```

---

### 6. Prompt Agent

Purpose:

```text
Convert shot data into provider-friendly prompts.
```

Prompt template:

```text
Character:
{{character_bible}}

Scene:
{{scene_summary}}

Shot:
{{shot_prompt}}

Camera:
{{camera}}

Movement:
{{movement}}

Continuity rules:
{{visual_rules}}

Negative rules:
No random outfit changes. No extra characters. No distorted face. No text or watermark.
```

---

### 7. Render Agent

Purpose:

```text
Convert RenderSpec into MiniMax, Kling, or AtlasCloud API request.
```

Example flow:

```text
RenderSpec
→ resolve asset IDs into local/public URLs
→ build provider payload
→ submit generation job
→ poll result
→ save output
```

---

### 8. QA Agent

Purpose:

```text
Check output against scene requirements.
```

Checks:

```text
Character consistency
Outfit consistency
Scene match
Camera match
Audio match
Prompt compliance
Visual artifacts
```

Output:

```json
{
  "score": 8,
  "passed": true,
  "issues": [],
  "recommendation": "accept"
}
```

---

## 9. Frontend Pages

### Dashboard

Shows:

```text
Recent assets
Characters
Scenes
Render jobs
Latest outputs
```

### Assets Page

Features:

```text
Upload asset
Auto-tag asset
Edit tags
Link to character
Preview asset
Search by tag
```

### Characters Page

Features:

```text
Create character
View character bible
Attach reference assets
Edit visual rules
View scenes using this character
```

### Scenes Page

Features:

```text
Create script idea
Generate scenes
Edit scene
Generate shots
View linked characters/assets
```

### Render Page

Features:

```text
Choose provider
Choose scene or shot
Preview prompt
Generate video
View job status
View outputs
Regenerate
```

### Graph Page

Features:

```text
Visual relationship graph
Character → Assets → Scenes → Shots → Outputs
```

Use:

```text
Svelte Flow
```

or a simple custom SVG graph.

---

## 10. Local File Storage

```text
storage/
  assets/
    images/
    videos/
    audio/

  characters/
    CHAR_AVA/
      front.png
      side.png
      voice.wav

  outputs/
    SCENE_001/
      render_001.mp4
      render_002.mp4
```

Store paths in SQLite:

```text
storage/assets/images/ava_front.png
storage/outputs/SCENE_001/render_001.mp4
```

---

## 11. Vector Search

Use ChromaDB to search:

```text
assets by description
characters by appearance
scenes by summary
shots by prompt
```

Example:

```text
Find all assets related to:
"rainy neon cyberpunk alley with female character"
```

Returns:

```text
LOC_NEON_ALLEY
CHAR_AVA_FRONT
PROP_RED_UMBRELLA
```

---

## 12. Provider Adapter Pattern

Each provider should have the same interface:

```python
class VideoProvider:
    def build_payload(self, render_spec):
        pass

    def submit(self, payload):
        pass

    def poll(self, job_id):
        pass
```

### MiniMax Adapter

```python
class MiniMaxProvider(VideoProvider):
    def build_payload(self, render_spec):
        return {
            "model": render_spec.model,
            "prompt": render_spec.prompt,
            "duration": render_spec.duration,
            "aspect_ratio": render_spec.aspect_ratio,
            "images": resolve_assets(render_spec.image_asset_ids)
        }
```

### Kling / AtlasCloud Adapter

```python
class AtlasCloudProvider(VideoProvider):
    def build_payload(self, render_spec):
        return {
            "model": render_spec.model,
            "aspect_ratio": render_spec.aspect_ratio,
            "duration": render_spec.duration,
            "images": resolve_assets(render_spec.image_asset_ids),
            "video": resolve_first_video(render_spec.video_asset_ids),
            "prompt": render_spec.prompt,
            "sound": render_spec.sound,
            "keep_original_sound": render_spec.keep_original_sound,
            "multi_shot": render_spec.multi_shot
        }
```

---

## 13. Minimal MVP Build Order

### Phase 1 — Asset Library

Build:

```text
Upload assets
Save to local storage
Create SQLite asset record
Manual tags
Asset cards in UI
```

### Phase 2 — AI Asset Recognition

Build:

```text
Send image/video frame to AI
Generate tags and description
Save metadata
Embed to ChromaDB
```

### Phase 3 — Character Bible

Build:

```text
Create character
Attach assets
Generate character bible
Edit visual rules
```

### Phase 4 — Scene and Shot Builder

Build:

```text
Input story idea
Generate scene JSON
Generate shot JSON
Validate with Pydantic
Save to SQLite
```

### Phase 5 — Render Integration

Build:

```text
Provider adapter
RenderSpec
Submit to MiniMax/Kling/AtlasCloud
Poll result
Save output
Preview video
```

### Phase 6 — Relationship Graph

Build:

```text
Character → Assets → Scene → Shots → Outputs
```

---

## 14. API Endpoints

```text
POST /assets/upload
GET /assets
POST /assets/{id}/recognise

POST /characters
GET /characters
GET /characters/{id}

POST /scripts/generate
POST /scenes/generate
GET /scenes
GET /scenes/{id}

POST /shots/generate
GET /scenes/{id}/shots

POST /render
GET /render-jobs
GET /render-jobs/{id}

GET /graph
```

---

## 15. Local Development Commands

Backend:

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install fastapi uvicorn pydantic sqlmodel chromadb requests python-multipart
uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend
npm create svelte@latest .
npm install
npm run dev
```

---

## 16. MVP Priority

Do not build everything first.

Build in this order:

```text
1. Upload assets
2. Tag assets
3. Create characters
4. Generate character bible
5. Generate scenes
6. Generate shots
7. Send one render job
8. Preview output
9. Relationship graph
```

---

## 17. Final Recommendation

Use:

```text
SvelteKit frontend
FastAPI backend
SQLite database
Pydantic schemas
ChromaDB vector memory
Local file storage
MiniMax/Kling/AtlasCloud provider adapters
```

This gives the lightest practical setup while still supporting persistent characters, tagged assets, structured AI agents, video generation jobs, and visual relationship tracking.
