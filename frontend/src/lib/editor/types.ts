/** Shared types for the video editor page (mirrors GET /outputs/{id}/editor). */

export type Segment = { start: number; end: number; text: string };

export type Shot = {
  index: number;
  start: number;
  end: number;
  duration: number;
  prompt: string;
  shot_id: string | null;
  camera: string | null;
  movement: string | null;
};

export type EditorOutput = {
  id: string;
  video_path: string | null;
  captioned_path: string | null;
  thumbnail_path: string | null;
  score: number | null;
  qa_issues: string[];
};

export type SceneRef = { id: string; title: string } | null;

export type Selection = { kind: 'caption' | 'shot'; index: number } | null;
