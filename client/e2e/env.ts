// The one copy of the settings shared by the config and the flows; the config hands the
// interpreter and the password to seed_library.py on its command line.
export const PYTHON = process.env['FACET_E2E_PYTHON'] ?? 'python';
export const PORT = Number(process.env['FACET_E2E_PORT'] ?? 5099);
export const EDITION_PASSWORD = 'e2e-edition';
