# 5. First video from an empty project

[Handbook](README.md) · Previous: [Projects](04-projects.md) · Next: [Characters and assets](06-characters-assets.md)

You need a running API/frontend, an active project, and configured text and media routes. Existing photos, character bibles, scripts, and videos are optional. Read the [current provider limitations](03-providers.md) first. The audit verified local contracts but did not run a paid live generation.

## Guided workflow

1. Open **Create video**.
2. Enter a small, concrete idea. For example: “One short scene in a quiet kitchen. Maya, wearing a red apron, shows Leo how to stir soup slowly. Warm picture-book style, simple English dialogue, no text on screen.”
3. Choose a visual style and format. Start with vertical or landscape and one short scene.
4. Choose the language and **Conversational** dialogue.
5. In More options, use a short target duration and optional dialogue direction, such as “Two brief lines; Maya explains and Leo answers.” The target is a planning hint; each scene must fit the selected video model's actual supported duration.
6. Click **Create video** and review the **Before you create** preflight panel. Check the text, image, and video routes; selected format; duration and resolution; reference cap; and whether generated audio is supported. This local check does not contact providers. Resolve any missing route or incompatible setting before proceeding.
7. Confirm **Create video** once. This starts multiple provider stages, not just one video request, and can incur usage charges.
8. Wait for orchestration to finish. The app then opens **My videos** while render jobs may still be generating.
9. Open a finished output, play it, check appearance and speech, then download it. Use [captions](10-captions-editor.md) if needed.

## Understand the current controls

| Control | Current behavior |
|---|---|
| Visual style | Creates a style guide only if the project has none; an existing guide wins |
| Format | Applied to the generated scenes |
| Language | Passed to conversational conversion; other stages can still use saved language defaults |
| Conversational | Runs a scene/shot dialogue conversion stage |
| Narrated | Currently skips that conversion; a dedicated narration stage is missing |
| Keep original style | Also skips conversion; it does not guarantee silent output |
| Direction for the AI | Passed to dialogue conversion, not consistently to every pipeline stage |
| Target duration | Influences story planning; does not guarantee an exact final assembled runtime |

The progress checklist currently receives stage results at operation completion. It may show Story as active while later work is happening. A browser refresh loses the Create page's in-memory operation ID; inspect Activity, Scenes, and My videos before starting again.

## If generation stops

Completed scripts, scenes, and shots are retained. Go to **Scenes**, inspect what exists, and continue from the missing stage. A full retry from Create can create another script and repeat paid image work. If a video job already exists, inspect it under My videos before resubmitting.

The guided flow does not explicitly create persistent character records and reference sheets for a new cast. If recurring identity matters, create those in Characters first and reuse their names in your idea.

A multi-scene story produces multiple scene outputs. Download and assemble them externally if you need one movie; whole-project assembly is not currently implemented.

**Expected result:** stored story artifacts and one or more render jobs, followed by downloaded outputs when the provider path succeeds. For tighter control, use the next chapters to create and review each part manually.
