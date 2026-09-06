# Simple Video Creation Design

## Goal

Give a first-time VideoFlow user one guided path from a story idea to a rendered video, while keeping the existing scene, character, asset, render, and settings tools available for advanced work.

## Product flow

The primary entry point is `Create video`. The user supplies a story idea and selects compact presets for visual style, aspect ratio, duration, language, and conversation mode. Advanced controls remain behind an optional disclosure.

The backend owns the ordered pipeline: create script and scenes, prepare the project style, generate shots and automatic props, convert scenes to controlled dialogue when requested, generate storyboards, and submit scene renders. The operation reports stage progress and preserves all intermediate rows so a user can inspect or recover through the advanced workspace.

The existing endpoints remain unchanged. The new orchestration endpoint composes existing services rather than duplicating their provider or prompt logic.

## Defaults and quality rules

- Conversation mode defaults to short natural dialogue with no narrator turns.
- Visual style defaults to 2D picture-book.
- Aspect ratio defaults to 9:16.
- Duration defaults to automatic scene planning.
- Existing project style, characters, and reference assets are reused.
- The pipeline stops with an actionable error when a required stage cannot continue.
- Every stage is idempotent for the submitted operation; a retry must not create duplicate scripts or scenes.

## Scope of the first slice

- Add a `/create` screen and a global Create video entry point.
- Add `POST /videos/generate?background=true` with an operation response.
- Add stage progress to the existing operation result/event path.
- Submit renders automatically after scene preparation; final video polling remains in the existing render worker.
- Keep advanced routes accessible and do not remove existing APIs.

## Out of scope for this slice

- Automatic character image generation from arbitrary uploaded photos.
- A new video database model or a separate project model.
- Replacing the existing advanced Scenes and Render pages.
- Billing, account management, or provider-selection changes.
