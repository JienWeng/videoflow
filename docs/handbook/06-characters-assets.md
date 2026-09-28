# 6. Characters, assets, and style

[Handbook](README.md) · Previous: [First video](05-first-video.md) · Next: [Scenes and shots](07-scenes-shots.md)

Use these pages when identity, recurring objects, or a consistent visual style matters. Provider capability determines whether stored references become actual video inputs.

## Create a reusable character

1. Open **Characters**, create a character, and enter a stable name and description.
2. Describe appearance, clothing, personality, and constraints in concrete terms.
3. Use **Generate bible** to turn those notes into structured appearance, visual rules, and voice rules. Add a short sample dialogue line so later prompts have a concrete example of the character's speaking style.
4. Review with **Edit**. Correct invented details and the sample line before generating more media. The line guides tone; it does not train a voice or guarantee exact spoken audio.
5. Use **Upload reference photo** for your own images, or the reference-sheet generation action for AI angles.
6. Link the character to the scene's cast in Scenes or Studio.

The reference-sheet action may still say “ERNIE”; the selected image provider and model determine the request. Generating reference sheets can make several image requests. OpenRouter-generated outputs preserve their returned image format and extension.

## Add and describe assets

1. Open **Assets** and upload the relevant file.
2. Set a meaningful name and description; use consistent names across scenes.
3. Use **Describe with AI** if you want structured metadata from a description you supply.
4. Link the asset to a shot through the scene controls or Studio.
5. Preview the asset and verify the correct file is attached.

Asset recognition currently structures your written description; it does not inspect the uploaded image bytes. Video and audio understanding are also not implemented by this recogniser. Describe content accurately yourself.

The scene asset planner can reuse existing library items by normalized name and generate missing props. Review names to avoid accidental reuse of an unrelated similarly named object. Generated and captioned outputs are also represented in the asset library.

## Establish the project style

Assets includes the project style controls. Set the style prompt, palette, lighting, audience, and tone. Pin appropriate image assets as style references. The style guide contributes to generation prompts and to image-reference workflows where supported.

An existing project style guide takes precedence over the style selected on Create video. Edit the guide here or use a new project when you want a different look.

## Know the limits

A character bible is reusable production information, not a trained identity model or a guarantee of consistent faces. The default AtlasCloud H3 Developer Reference-to-Video route can send character, prop, and storyboard images as visual references within the configured cap. H3 Developer Text-to-Video omits them. OpenRouter sends ordinary references as visual guidance; only explicit first/last-frame asset IDs become frame anchors. Preview every generated take before accepting it.
