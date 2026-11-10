/** Confirmed grouping change, scoped to the authorized preview that was applied. */
export interface LogicalAssetApplied {
  operation: 'create' | 'primary' | 'dissolve';
  assetId: string;
  primaryPath: string | null;
  members: readonly string[];
}
