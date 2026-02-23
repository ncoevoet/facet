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
  tags: string | null;
  tags_list: string[];
  is_monochrome: boolean | null;
  is_silhouette: boolean | null;
  // Metadata
  date_taken: string | null;
  image_width: number;
  image_height: number;
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
}
