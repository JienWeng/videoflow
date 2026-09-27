# 10. Captions and the output editor

[Handbook](README.md) · Previous: [Renders](09-renders.md) · Next: [Troubleshooting](11-troubleshooting.md)

The editor is reached from an output in My videos. It supports video playback, a timeline, shot inspection, and caption editing. It is not a complete multi-track film editor or a tool for joining all scene outputs.

## Add captions

1. Open a successful output with audible speech.
2. Choose a Whisper model and language, or auto-detection where available.
3. Start transcription/auto-captions. The first use downloads the selected local model.
4. Review every line against the actual audio. Script-based corrections can improve names but can also differ from what was spoken.
5. Choose a style: `kids`, `clean`, or `minimal`.
6. Burn/save the captioned result and wait for the operation to finish.

`tiny` is smaller and faster; larger models use more local resources. The current service runs on CPU. FFmpeg with libass is required for burning subtitles. Install the appropriate font for the language.

## Correct a caption

Select a caption segment on the timeline, edit its text and timing in the inspector, and use the save/burn action. End time must be greater than start time, and both must be nonnegative. The service requires at least one nonempty caption segment.

Transcription updates stored segments; it does not automatically replace an earlier captioned video until another burn. Download the captioned variant after the latest save completes. Keep the original video if you may revise captions later.

The generated `.ass` subtitle file is stored next to the captioned MP4. Advanced users can retain it for external editing, but manual file edits are not a substitute for updating the application's stored segment data.

**If it fails:** no detected speech, missing FFmpeg, missing fonts, unavailable model downloads, or invalid segment timing each need a different remedy. Use [Troubleshooting](11-troubleshooting.md). Real transcription and subtitle rendering were not executed during this audit because FFmpeg was unavailable.
