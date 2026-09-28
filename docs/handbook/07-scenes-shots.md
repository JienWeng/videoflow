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
8. Use the list's **Latest / Story** control to switch between recently updated scenes and the story's scene order.

Shot generation can automatically plan and generate assets. It can therefore incur image costs in addition to text costs. Review any confirmation explaining replacement of existing work before proceeding.

## Dialogue and continuity

Use conversational conversion for short, clear spoken lines. Check that the requested language and scene context survive conversion. The app often represents dialogue with `「spoken line」` in prompts; the video provider still determines actual audio.

Local continuity retrieval supplies matching character, asset, and sibling-scene text to planning. It is lexical retrieval, not a connected vector-memory system. Shot dependency layers are saved, but they do not yet drive a complete dependency-aware generation scheduler.

For cross-scene visual continuity, render and finish the preceding scene before preparing the next. The code can extract a previous output's last frame when FFmpeg and the file are available. Whether it is sent as a visual reference depends on the selected provider route and reference cap; inspect the render route before relying on it.

## Storyboard and render

1. Generate **Storyboard** after shots exist.
2. Open the contact sheet in Assets and inspect composition, characters, and order.
3. Fix the source scene/shot text if it is wrong, then regenerate only the affected work.
4. Ensure the sum of shot durations is valid for the selected model.
5. Submit **Render** and inspect the job in My videos. If shots already exist, you can also use **Render now** from the scene without revisiting shot generation.

The contact sheet supports up to 16 panels. The scene service accepts a 3–15 second range, while each OpenRouter video model may support a discrete set of durations. The OpenRouter adapter checks the selected model catalog before submission and reports unsupported durations/aspect ratios.

Existing render outputs are historical takes. Editing shots or generating another storyboard does not retroactively update them. Keep the output that matches the final script and download it explicitly.
