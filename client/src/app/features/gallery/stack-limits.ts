/** Bounds on a manual stack's membership, enforced by the server and mirrored here for early feedback. */
export const STACK_MIN_MEMBERS = 2;
export const STACK_MAX_MEMBERS = 1000;

/** One suggestion batch's caps, mirroring `MAX_SUGGESTIONS` / `MAX_RETURNED_MEMBERS` in `db/stack_suggestions.py`. */
export const STACK_SUGGESTION_MAX = 20;
export const STACK_SUGGESTION_MAX_PHOTOS = 2000;
