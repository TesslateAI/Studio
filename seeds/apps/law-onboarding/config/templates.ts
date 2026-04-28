/**
 * Matter-type → Legora template mapping.
 * Add new entries as your firm creates templates in Legora.
 */
export const LEGORA_TEMPLATES: Record<string, string> = {
  NDA: "tpl_nda_standard",
  "Contractor Agreement": "tpl_contractor_v2",
  Confidentiality: "tpl_confidentiality_v1",
  Other: "tpl_general_review",
};

/** Minimum confidence score (0–1) below which needs_attention is set */
export const LEGORA_CONFIDENCE_THRESHOLD = 0.75;
