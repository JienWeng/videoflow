# 8. Studio and guided chat

[Handbook](README.md) · Previous: [Scenes and shots](07-scenes-shots.md) · Next: [Renders](09-renders.md)

Studio is the advanced relationship view at `/`. It shows characters, assets, scenes, shots, render jobs, and outputs as connected entities.

## Inspect and edit relationships

1. Open **Advanced → Studio**.
2. Select a node to inspect or edit its details.
3. Connect a character to a scene to add it to the cast.
4. Connect an asset to a shot to attach a reference.
5. Remove an edge to detach that relationship; this is different from deleting the underlying entity.
6. Reorder shots using the available shot controls/canvas interaction and confirm the resulting order in Scenes.

Use the graph to answer “Which asset belongs to this shot?” or “Which output came from this scene?” For a first story, Create video or Scenes offers a more direct path.

## Guided chat

Type a concrete request, such as “Generate a storyboard for the kitchen scene.” Chat classifies the intent and prepares an action card. Review the selected entity and fields, then use **Run** to call the pipeline action.

A chat response alone does not mean a video was generated. The application executes the reviewed action through an endpoint. Requests for generation, refinement, or recognition may consume provider usage.

Press **Ctrl+K** (Windows/Linux) or **Cmd+K** (macOS) to open the global command palette. Studio-specific node focus actions need the Studio canvas; navigation commands can be used from other pages.

**Expected result:** the intended relationship or action appears in the stored workspace. If an action fails, inspect its error and existing artifacts before repeating it. Browser interaction details still need visual verification; this handbook is grounded in the current UI source.
