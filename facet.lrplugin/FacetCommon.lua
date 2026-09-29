-- Shared helpers used by both FacetApply.lua and FacetExportState.lua.
-- Owns preference loading, path normalisation/mapping, and the path-prefix
-- suggestion helper (item 6). The JSON encoder stays in FacetJson.lua (see
-- Step 5b's decision) so FacetJson.lua stays decode+encode cohesive.

local LrPrefs = import 'LrPrefs'

local FacetCommon = {}

FacetCommon.SCOPE_SELECTION = 'selection'
FacetCommon.SCOPE_FOLDER = 'folder'

local BOOLEAN_PREFERENCE_DEFAULTS = {
    'overwrite', 'debugLog', 'starsFromScore', 'pickBurstLeads', 'rejectBurstOthers',
    'createCollections', 'writeMetadataFields', 'createKeywords', 'rebuildCollections',
}

local STRING_PREFERENCE_DEFAULTS = { 'manifestPath', 'catalogPrefix', 'manifestPrefix' }

function FacetCommon.loadPreferences()
    local preferences = LrPrefs.prefsForPlugin()
    for _, name in ipairs(STRING_PREFERENCE_DEFAULTS) do
        if type(preferences[name]) ~= 'string' then
            preferences[name] = ''
        end
    end
    if preferences.scope ~= FacetCommon.SCOPE_FOLDER then
        preferences.scope = FacetCommon.SCOPE_SELECTION
    end
    for _, name in ipairs(BOOLEAN_PREFERENCE_DEFAULTS) do
        if type(preferences[name]) ~= 'boolean' then
            preferences[name] = false
        end
    end
    return preferences
end

function FacetCommon.normalizePath(path)
    if type(path) ~= 'string' or path == '' then
        return nil
    end
    local normalized = string.gsub(path, '\\', '/')
    normalized = string.gsub(normalized, '/+$', '')
    return normalized
end

function FacetCommon.normalizePrefix(prefix)
    return FacetCommon.normalizePath(prefix) or ''
end

-- M3: the prefix match requires a path-COMPONENT boundary right after the
-- prefix, never a bare string prefix -- otherwise "/Volumes/Photos" would
-- also match "/Volumes/Photos2/a.jpg" (an unrelated sibling folder) and
-- silently remap it onto whatever "/Volumes/Photos" is configured to map to.
function FacetCommon.mapToManifestPath(catalogPath, catalogPrefix, manifestPrefix)
    local normalized = FacetCommon.normalizePath(catalogPath)
    if not normalized or catalogPrefix == '' then
        return normalized
    end
    local prefixLength = #catalogPrefix
    local head = string.sub(normalized, 1, prefixLength)
    if string.lower(head) ~= string.lower(catalogPrefix) then
        return normalized
    end
    local nextChar = string.sub(normalized, prefixLength + 1, prefixLength + 1)
    if nextChar ~= '' and nextChar ~= '/' then
        return normalized
    end
    return manifestPrefix .. string.sub(normalized, prefixLength + 1)
end

-- Read-only counterpart used only by the reverse-sync exporter (I6): unlike
-- mapToManifestPath above (which always forces forward slashes, because it
-- feeds a match against the manifest's own forward-slash paths), the
-- exported state file is matched against the RAW `photos.path` column on
-- the Python side with no separator normalisation. When no catalog/manifest
-- prefix mapping is configured, the path must round-trip byte-for-byte
-- (native separators, drive letters and all) or a native-Windows install's
-- reverse export matches nothing. Prefix mapping (cross-machine) still goes
-- through the forward-slash-normalised path, exactly as the apply
-- direction already does.
function FacetCommon.mapPathForExport(catalogPath, catalogPrefix, manifestPrefix)
    if type(catalogPath) ~= 'string' or catalogPath == '' then
        return nil
    end
    if catalogPrefix == '' then
        return catalogPath
    end
    return FacetCommon.mapToManifestPath(catalogPath, catalogPrefix, manifestPrefix)
end

-- Counts the run of leading separator characters in `path` (2 for a UNC
-- '\\NAS\...' or '//NAS/...' path, 1 for an ordinary absolute path, 0 for a
-- relative one) -- M2's fix needs the exact run length, not just "starts
-- with a separator".
local function leadingSeparatorRun(path, separator)
    local run = 0
    for index = 1, #path do
        if string.sub(path, index, index) == separator then
            run = run + 1
        else
            break
        end
    end
    return run
end

-- Splits a slash-normalised path into components, preserving the original
-- separator style so the returned prefix can be reassembled with it.
local function splitComponents(path, separator)
    local parts = {}
    local count = 0
    for piece in string.gmatch(path, '([^' .. separator .. ']+)') do
        count = count + 1
        parts[count] = piece
    end
    return parts, count
end

-- Longest common path SUFFIX by path components (not raw characters, not a
-- prefix) between `catalogPath` and `manifestPath`. Returns the two prefixes
-- (everything before the common suffix, in each input's OWN original
-- separator style) or `nil, nil` when there is nothing useful to suggest
-- (no common suffix component at all).
function FacetCommon.suggestPrefixPair(catalogPath, manifestPath)
    if type(catalogPath) ~= 'string' or type(manifestPath) ~= 'string' then
        return nil, nil
    end
    local catalogSeparator = string.find(catalogPath, '\\') and '\\' or '/'
    local manifestSeparator = string.find(manifestPath, '\\') and '\\' or '/'

    local catalogNormalized = FacetCommon.normalizePath(catalogPath)
    local manifestNormalized = FacetCommon.normalizePath(manifestPath)
    if not catalogNormalized or not manifestNormalized then
        return nil, nil
    end

    local catalogParts, catalogCount = splitComponents(catalogNormalized, '/')
    local manifestParts, manifestCount = splitComponents(manifestNormalized, '/')
    if catalogCount == 0 or manifestCount == 0 then
        return nil, nil
    end

    -- Basename match is the only reliable anchor when the two roots differ
    -- entirely; if even the filename disagrees there is nothing to suggest.
    if string.lower(catalogParts[catalogCount]) ~= string.lower(manifestParts[manifestCount]) then
        return nil, nil
    end

    local matched = 0
    while matched < catalogCount and matched < manifestCount
        and string.lower(catalogParts[catalogCount - matched]) == string.lower(manifestParts[manifestCount - matched]) do
        matched = matched + 1
    end
    if matched == 0 then
        return nil, nil
    end

    local catalogPrefixParts = {}
    for index = 1, catalogCount - matched do
        catalogPrefixParts[index] = catalogParts[index]
    end
    local manifestPrefixParts = {}
    for index = 1, manifestCount - matched do
        manifestPrefixParts[index] = manifestParts[index]
    end

    local catalogPrefix = table.concat(catalogPrefixParts, catalogSeparator)
    local manifestPrefix = table.concat(manifestPrefixParts, manifestSeparator)
    -- M2: preserve the FULL leading separator run, not just one character --
    -- a UNC path ('\\NAS\...') or a POSIX absolute path ('/lib/...') both
    -- start with one-or-more separators, and dropping to a single one turns
    -- '\\NAS\photos' into '\NAS\photos', which normalizes to '/NAS/photos'
    -- and never prefix-matches '//NAS/...' again.
    if catalogPrefix ~= '' then
        local run = leadingSeparatorRun(catalogPath, catalogSeparator)
        if run > 0 then
            catalogPrefix = string.rep(catalogSeparator, run) .. catalogPrefix
        end
    end
    if manifestPrefix ~= '' then
        local run = leadingSeparatorRun(manifestPath, manifestSeparator)
        if run > 0 then
            manifestPrefix = string.rep(manifestSeparator, run) .. manifestPrefix
        end
    end
    return catalogPrefix, manifestPrefix
end

return FacetCommon
