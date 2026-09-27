# 7. Scenes, shots, and storyboards

[Handbook](README.md) · Previous: [Characters and assets](06-characters-assets.md) · Next: [Studio](08-studio.md)

Use Scenes to inspect and advance a story one stage at a time. This is also the recovery path after a partially completed Create operation.

## Build the text plan

1. Open **Scenes** and use the story-generation action.
2. Enter the idea, target duration, and optional scene count.
3. Review the resulting scenes. Use search and stage filters to find the next one to work on.
4. Select a scene and **Expand** its summary into a scene specification.
5. Check its cast, setting, aspect ratio, and duration.
6. Generate **Shots**. Review the ordered prompts, camera/movement details, durations, and attached assets.
7. Edit directly or use AI refinement for a specific change, such as “Keep the same location and shorten Leo's response.”

Shot generation can automatically plan and generate assets. It can therefore incur image costs in addition to text costs. Review any confirmation explaining replacement of existing work before proceeding.

## Dialogue and continuity

Use conversational conversion for short, clear spoken lines. Check that the requested language and scene context survive conversion. The app often represents dialogue with `「spoken line」` in prompts; the video provider still determines actual audio.

Local continuity retrieval supplies matching character, asset, and sibling-scene text to planning. It is lexical retrieval, not a connected vector-memory system. Shot dependency layers are saved, but they do not yet drive a complete dependency-aware generation scheduler.

For cross-scene visual continuity, render and finish the preceding scene before preparing the next. The code can extract a previous output's last frame when FFmpeg and the file are available. The current H3 adapter does not transmit that anchor as an image; do not rely on it for H3 visual continuity.

## Storyboard and render

1. Generate **Storyboard** after shots exist.
2. Open the contact sheet in Assets and inspect composition, characters, and order.
3. Fix the source scene/shot text if it is wrong, then regenerate only the affected work.
4. Ensure the sum of shot durations is valid for the selected model.
5. Submit **Render** and inspect the job in My videos.

The contact sheet supports up to 16 panels. The scene service currently accepts a 3–15 second range while adapters have different constraints (H3 clamps to 4–15; OpenRouter uses broad 4–8 or 4–15 checks). Exact supported durations need model-specific validation; a scene passing the first check can still fail later.

Existing render outputs are historical takes. Editing shots or generating another storyboard does not retroactively update them. Keep the output that matches the final script and download it explicitly.
