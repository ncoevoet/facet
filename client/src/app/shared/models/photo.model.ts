/** "A better shot exists in this group" hint from the learned keeper head. */
export interface KeeperHint {
  has_better: boolean;
  best_path: string | null;
  keeper_prob: number | null;
}

export interface Photo {
  path: string;
  filename: string;
  // Scores
  aggregate: number;
  aesthetic: number;
  face_quality: number | null;
  comp_score: number | null;
  tech_sharpness: number | null;
  color_score: number | null;
  exposure_score: number | null;
  quality_score: number | null;
  topiq_score: number | null;
  top_picks_score: number | null;
  isolation_bonus: number | null;
  // Extended quality
  aesthetic_iaa: number | null;
  face_quality_iqa: number | null;
  liqe_score: number | null;
  // Extended IQA tier (config-gated; optional — absent/null unless iqa_extended is enabled)
  qalign_score?: number | null;
  aesthetic_v25?: number | null;
  deqa_score?: number | null;
  // Subject saliency
  subject_sharpness: number | null;
  subject_prominence: number | null;
  subject_placement: number | null;
  bg_separation: number | null;
  // Form facet + color harmony (optional — absent until the columns are populated)
  form_symmetry?: number | null;
  form_balance?: number | null;
  form_edge_entropy?: number | null;
  form_fractal?: number | null;
  color_harmony?: number | null;
  // Face
  face_count: number;
  face_ratio: number;
  eye_sharpness: number | null;
  face_sharpness: number | null;
  face_confidence: number | null;
  is_blink: boolean | null;
  // Camera
  camera_model: string | null;
  lens_model: string | null;
  iso: number | null;
  f_stop: number | null;
  shutter_speed: number | null;
  focal_length: number | null;
  // Technical
  noise_sigma: number | null;
  contrast_score: number | null;
  dynamic_range_stops: number | null;
  mean_saturation: number | null;
  mean_luminance: number | null;
  histogram_spread: number | null;
  // Composition
  composition_pattern: string | null;
  power_point_score: number | null;
  leading_lines_score: number | null;
  // Classification
  category: string | null;
  narrative_moment?: string | null;
  narrative_moment_confidence?: number | null;
  tags: string | null;
  tags_list: string[];
  is_monochrome: boolean | null;
  is_silhouette: boolean | null;
  // Metadata
  date_taken: string | null;
  /** Pixel dimensions of the frame the scan analysed. Null when the recorded
   *  pair was proven to have been fabricated from the thumbnail and cleared —
   *  see `image_aspect`, and `repair_thumbnail_dimensions` server-side. */
  image_width: number | null;
  image_height: number | null;
  /** Display aspect (width / height) kept when the dimensions above were
   *  cleared: a thumbnail is scaled, not cropped, so the ratio survived even
   *  though the resolution did not. Null whenever the dimensions are real —
   *  it is a fallback, never a preference. */
  image_aspect?: number | null;
  // Burst/Duplicate
  is_best_of_burst: boolean | null;
  burst_group_id: string | null;
  duplicate_group_id: string | null;
  is_duplicate_lead: boolean | null;
  // Persons & Rating
  persons: { id: number; name: string }[];
  unassigned_faces: number;
  star_rating: number | null;
  is_favorite: boolean | null;
  is_rejected: boolean | null;
  keeper_hint?: KeeperHint | null;
  /** 'bracket' | 'panorama' | 'hdr_panorama' when this frame belongs to a
   *  deliberate multi-frame set. With the matching hide toggle on, the tile
   *  showing it stands for the whole set. */
  sequence_kind?: string | null;
  /** A manual correction to what this frame's set is: 'suppressed' ("not a
   *  panorama") or the kind it was forced to. Independent of `sequence_kind`,
   *  which the detector owns — a forced set has none at all until the next run.
   *  Set for as long as the correction stands, applied or not. */
  sequence_override?: string | null;
  /** Whether that correction is still waiting on a detection run. The badge
   *  keys on this, never on `sequence_override`, which stays set afterwards. */
  sequence_override_pending?: number | null;
  similarity?: number;
  caption?: string;
  caption_translated?: string;
  gps_latitude?: number;
  gps_longitude?: number;
}
