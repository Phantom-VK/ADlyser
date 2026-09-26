/** How each candidate status is named and drawn. Colour is never the only signal: each has a shape too. */
import type { CandidateStatus } from "../types";

export interface StatusMeta {
  label: string;
  /** What the status means, in one sentence. */
  meaning: string;
  shape: "dot" | "diamond" | "ring";
}

export const STATUS_ORDER: CandidateStatus[] = [
  "selected",
  "vetoed",
  "blocked",
  "pacing_rejected",
  "below_min_score",
  "not_scene_change",
];

export const STATUS: Record<CandidateStatus, StatusMeta> = {
  selected: { label: "Break placed", meaning: "A break plays here, with the brand shown.", shape: "dot" },
  vetoed: { label: "Vetoed", meaning: "The reviewer looked closer and said no.", shape: "diamond" },
  blocked: { label: "Blocked", meaning: "Every brand is ruled out here, or none fits.", shape: "diamond" },
  pacing_rejected: { label: "Skipped by pacing", meaning: "A good break, but the pacing rules had a better one.", shape: "ring" },
  below_min_score: { label: "Weak break", meaning: "Scene change, but not a natural place to stop.", shape: "ring" },
  not_scene_change: { label: "Same scene", meaning: "A pause inside a scene, not a boundary.", shape: "ring" },
};
