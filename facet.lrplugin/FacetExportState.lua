-- Facet: Export Lightroom State to Facet -- the reverse-sync export (item
-- 2 / Step 5b). Its own top-level entry file, with its own
-- LrFunctionContext.postAsyncTaskWithContext call, distinct from
-- FacetApply.lua's -- the two menu items can never cross-invoke.

local LrApplication = import 'LrApplication'
local LrDialogs = import 'LrDialogs'
local LrFunctionContext = import 'LrFunctionContext'
local LrTasks = import 'LrTasks'

local FacetJson = require 'FacetJson'
local FacetCommon = require 'FacetCommon'
local FacetMetadata = require 'FacetMetadata'

local FORMAT_NAME = 'facet-lightroom-state'
local FORMAT_VERSION = 1
local ACTION_NAME = 'Facet: export Lightroom state'
local DIALOG_TITLE = 'Facet'
local EXPORT_FILE_NAME = 'facet_lightroom_state.json'
local READ_CHUNK_SIZE = 1000

local METADATA_PATH = 'path'
local METADATA_RATING = 'rating'
local METADATA_PICK_STATUS = 'pickStatus'
local METADATA_IS_VIRTUAL_COPY = 'isVirtualCopy'
local METADATA_KEYS = { METADATA_PATH, METADATA_RATING, METADATA_PICK_STATUS, METADATA_IS_VIRTUAL_COPY }

local PICK_TO_FLAG = { [1] = 1, [0] = 0, [-1] = -1 }

-- Reads path/rating/pickStatus/isVirtualCopy plus the two hidden derived-value
-- plug-in properties for every photo in `photos`, chunked the same way
-- FacetApply.lua chunks its reads.
local function readPhotoStates(catalog, photos)
    local states = {}
    local total = #photos
    for chunkStart = 1, total, READ_CHUNK_SIZE do
        local chunkEnd = math.min(chunkStart + READ_CHUNK_SIZE - 1, total)
        local chunk = {}
        for position = chunkStart, chunkEnd do
            chunk[#chunk + 1] = photos[position]
        end
        local raw = catalog:batchGetRawMetadata(chunk, METADATA_KEYS)
        local derived = catalog:batchGetPropertyForPlugin(_PLUGIN, chunk,
            { FacetMetadata.FIELD_DERIVED_RATING, FacetMetadata.FIELD_DERIVED_PICK })
        for _, photo in ipairs(chunk) do
            local values = (raw and raw[photo]) or {}
            local derivedValues = (derived and derived[photo]) or {}
            states[#states + 1] = {
                photo = photo,
                path = values[METADATA_PATH],
                rating = tonumber(values[METADATA_RATING]) or 0,
                pickStatus = tonumber(values[METADATA_PICK_STATUS]) or 0,
                isVirtualCopy = values[METADATA_IS_VIRTUAL_COPY] == true,
                derivedRating = derivedValues[FacetMetadata.FIELD_DERIVED_RATING],
                derivedPick = derivedValues[FacetMetadata.FIELD_DERIVED_PICK],
            }
        end
        LrTasks.yield()
    end
    return states
end

-- Virtual copies share `path` with their master. Dedupe by mapped path,
-- preferring the master (isVirtualCopy == false); if only virtual copies
-- exist for a path, the first one encountered wins (accepted edge case, not
-- last-write-wins -- this pass runs once over the whole input, before any
-- serialization, so there is no ordering-dependent overwrite).
local function dedupeByPath(states, catalogPrefix, manifestPrefix)
    local byPath = {}
    local order = {}
    for _, state in ipairs(states) do
        local mappedPath = FacetCommon.mapPathForExport(state.path, catalogPrefix, manifestPrefix)
        if mappedPath then
            local existing = byPath[mappedPath]
            if not existing then
                byPath[mappedPath] = state
                order[#order + 1] = mappedPath
            elseif existing.isVirtualCopy and not state.isVirtualCopy then
                byPath[mappedPath] = state
            end
        end
    end
    local deduped = {}
    for _, path in ipairs(order) do
        deduped[#deduped + 1] = byPath[path]
    end
    return deduped
end

-- Builds one exported record. `rating`/`pick` are OMITTED when the current
-- Lightroom value equals the recorded facetDerivedRating/facetDerivedPick
-- (nothing manual has touched it since Apply last derived it) -- "no
-- record at all" is treated as "still export", never as "still equal".
-- Every field that IS exported is written with an explicit numeric value
-- (never nil), since FacetJson.encode drops a nil key silently and "leave
-- it as 0" must stay distinguishable from "omit the key".
local function buildRecord(state, mappedPath)
    local record = { path = mappedPath, keys = { 'path', 'rating', 'pick' } }
    if state.derivedRating == nil or tostring(state.rating) ~= tostring(state.derivedRating) then
        record.rating = state.rating
    end
    local pickFlag = PICK_TO_FLAG[state.pickStatus] or 0
    if state.derivedPick == nil or tostring(pickFlag) ~= tostring(state.derivedPick) then
        record.pick = pickFlag
    end
    return record
end

local function buildExportPayload(states, catalogPrefix, manifestPrefix)
    local deduped = dedupeByPath(states, catalogPrefix, manifestPrefix)
    local records = { isArray = true, length = #deduped }
    for index, state in ipairs(deduped) do
        local mappedPath = FacetCommon.mapPathForExport(state.path, catalogPrefix, manifestPrefix)
        records[index] = buildRecord(state, mappedPath)
    end
    return {
        format = FORMAT_NAME,
        version = FORMAT_VERSION,
        keys = { 'format', 'version', 'photos' },
        photos = records,
    }
end

local function encodePayload(payload)
    return FacetJson.encode(payload, payload.keys)
end

local function resolveScope(catalog)
    local photos = catalog:getTargetPhotos()
    if not photos or #photos == 0 then
        return nil, 'No photos are selected. Select photos in the Library filmstrip and try again.'
    end
    return photos
end

local function run(context)
    local preferences = FacetCommon.loadPreferences()
    local catalog = LrApplication.activeCatalog()
    local photos, scopeError = resolveScope(catalog)
    if not photos then
        LrDialogs.message(DIALOG_TITLE, scopeError, 'warning')
        return
    end

    local states = readPhotoStates(catalog, photos)
    local catalogPrefix = FacetCommon.normalizePrefix(preferences.catalogPrefix)
    local manifestPrefix = FacetCommon.normalizePrefix(preferences.manifestPrefix)
    local payload = buildExportPayload(states, catalogPrefix, manifestPrefix)
    local json = encodePayload(payload)

    local chosen = LrDialogs.runSavePanel {
        title = 'Export Lightroom state for Facet',
        requiredFileType = 'json',
        canCreateDirectories = true,
        prompt = 'Export',
    }
    if not chosen then
        return
    end
    local file, openMessage = io.open(chosen, 'w')
    if not file then
        LrDialogs.message(DIALOG_TITLE, string.format('Cannot write:\n%s\n\n%s', chosen, tostring(openMessage)), 'critical')
        return
    end
    file:write(json)
    file:close()
    LrDialogs.message(DIALOG_TITLE .. ' - done',
        string.format('Exported %d photo(s) to:\n%s', payload.photos.length, chosen))
end

-- Test seam, mirroring FacetApply.lua's (tests/test_lrplugin_apply.py /
-- tests/test_lrplugin_export_state.py).
if FACET_EXPORT_STATE_TEST_HOOKS then
    FACET_EXPORT_STATE_TEST_HOOKS.readPhotoStates = readPhotoStates
    FACET_EXPORT_STATE_TEST_HOOKS.dedupeByPath = dedupeByPath
    FACET_EXPORT_STATE_TEST_HOOKS.buildRecord = buildRecord
    FACET_EXPORT_STATE_TEST_HOOKS.buildExportPayload = buildExportPayload
    FACET_EXPORT_STATE_TEST_HOOKS.encodePayload = encodePayload
    return
end

LrFunctionContext.postAsyncTaskWithContext('facetExportState', function(context)
    LrDialogs.attachErrorDialogToFunctionContext(context, ACTION_NAME)
    run(context)
end)
