local LrApplication = import 'LrApplication'
local LrBinding = import 'LrBinding'
local LrDate = import 'LrDate'
local LrDialogs = import 'LrDialogs'
local LrFunctionContext = import 'LrFunctionContext'
local LrPathUtils = import 'LrPathUtils'
local LrPrefs = import 'LrPrefs'
local LrProgressScope = import 'LrProgressScope'
local LrTasks = import 'LrTasks'
local LrView = import 'LrView'

local FacetJson = require 'FacetJson'

local MANIFEST_VERSION = 2
local FIELD_VERSION = 'version'
local FIELD_GENERATED_AT = 'generated_at'
local FIELD_PHOTOS = 'photos'
local FIELD_PATH = 'path'
local FIELD_STAR_RATING = 'star_rating'
local FIELD_IS_FAVORITE = 'is_favorite'
local FIELD_IS_REJECTED = 'is_rejected'
local FIELD_IS_BURST_LEAD = 'is_burst_lead'
local FIELD_BURST_GROUP_ID = 'burst_group_id'
local FIELD_SEQUENCE_KIND = 'sequence_kind'
local FIELD_SEQUENCE_GROUP_ID = 'sequence_group_id'
local FIELD_SCORE_STARS = 'score_stars'
local FIELD_DATE_TAKEN = 'date_taken'
local FIELD_FILENAME = 'filename'

local METADATA_PATH = 'path'
local METADATA_RATING = 'rating'
local METADATA_PICK_STATUS = 'pickStatus'
local METADATA_KEYS = { METADATA_PATH, METADATA_RATING, METADATA_PICK_STATUS }

local PICK_STATUS_PICKED = 1
local PICK_STATUS_NONE = 0
local PICK_STATUS_REJECTED = -1
local MAXIMUM_RATING = 5

-- Sequence kinds that mean "this frame is part of a keep-whole set" -- a
-- member of any of these is never rejected by the burst reject-the-rest
-- rule, no matter how its burst_group_id groups it with siblings.
local SEQUENCE_KIND_BRACKET = 'bracket'
local SEQUENCE_KIND_PANORAMA = 'panorama'
local SEQUENCE_KIND_HDR_PANORAMA = 'hdr_panorama'
local KEEP_WHOLE_SEQUENCE_KINDS = {
    [SEQUENCE_KIND_BRACKET] = true,
    [SEQUENCE_KIND_PANORAMA] = true,
    [SEQUENCE_KIND_HDR_PANORAMA] = true,
}

-- Collection layout: one root set, one child set per sequence kind plus one
-- for plain bursts.
local COLLECTION_ROOT_NAME = 'Facet'
local COLLECTION_SET_BURSTS = 'Bursts'
local SEQUENCE_KIND_COLLECTION_SET = {
    [SEQUENCE_KIND_BRACKET] = 'Brackets',
    [SEQUENCE_KIND_PANORAMA] = 'Panoramas',
    [SEQUENCE_KIND_HDR_PANORAMA] = 'HDR panoramas',
}

local SCOPE_SELECTION = 'selection'
local SCOPE_FOLDER = 'folder'

local READ_CHUNK_SIZE = 1000
local WRITE_CHUNK_SIZE = 200
local WRITE_TIMEOUT_SECONDS = 30
local LOGGED_MISS_LIMIT = 200

local MANIFEST_FILE_NAME = 'facet_manifest.json'
local LOG_FILE_NAME = 'facet-apply.log'
local ACTION_NAME = 'Facet: apply ratings and flags'
local DIALOG_TITLE = 'Facet'
local LOG_TIME_FORMAT = '%Y-%m-%d %H:%M:%S'

local function loadPreferences()
    local preferences = LrPrefs.prefsForPlugin()
    if type(preferences.manifestPath) ~= 'string' then
        preferences.manifestPath = ''
    end
    if type(preferences.catalogPrefix) ~= 'string' then
        preferences.catalogPrefix = ''
    end
    if type(preferences.manifestPrefix) ~= 'string' then
        preferences.manifestPrefix = ''
    end
    if preferences.scope ~= SCOPE_FOLDER then
        preferences.scope = SCOPE_SELECTION
    end
    if type(preferences.overwrite) ~= 'boolean' then
        preferences.overwrite = false
    end
    if type(preferences.debugLog) ~= 'boolean' then
        preferences.debugLog = false
    end
    if type(preferences.starsFromScore) ~= 'boolean' then
        preferences.starsFromScore = false
    end
    if type(preferences.pickBurstLeads) ~= 'boolean' then
        preferences.pickBurstLeads = false
    end
    if type(preferences.rejectBurstOthers) ~= 'boolean' then
        preferences.rejectBurstOthers = false
    end
    if type(preferences.createCollections) ~= 'boolean' then
        preferences.createCollections = false
    end
    return preferences
end

local function normalizePath(path)
    if type(path) ~= 'string' or path == '' then
        return nil
    end
    local normalized = string.gsub(path, '\\', '/')
    normalized = string.gsub(normalized, '/+$', '')
    return normalized
end

local function normalizePrefix(prefix)
    return normalizePath(prefix) or ''
end

local function openLog(preferences)
    local logger = { write = function() end, close = function() end, misses = 0 }
    if not preferences.debugLog then
        return logger
    end
    local directory = LrPathUtils.parent(preferences.manifestPath)
    if not directory then
        return logger
    end
    local file = io.open(LrPathUtils.child(directory, LOG_FILE_NAME), 'a')
    if not file then
        return logger
    end
    logger.write = function(message)
        local stamp = LrDate.timeToUserFormat(LrDate.currentTime(), LOG_TIME_FORMAT)
        file:write(string.format('%s %s\n', stamp, message))
    end
    logger.close = function()
        file:close()
    end
    return logger
end

local function makeProgressScope(context, title)
    local progress = LrProgressScope {
        title = title,
        functionContext = context,
    }
    pcall(function()
        progress:setCancelable(true)
    end)
    return progress
end

local function readManifest(path)
    if not path or path == '' then
        return nil, 'Choose the ' .. MANIFEST_FILE_NAME
            .. ' file produced by "python facet.py --export-manifest".'
    end
    local file, openMessage = io.open(path, 'rb')
    if not file then
        return nil, string.format('Cannot open the manifest file:\n%s\n\n%s', path, tostring(openMessage))
    end
    local contents = file:read('*a')
    file:close()
    if not contents or contents == '' then
        return nil, string.format('The manifest file is empty:\n%s', path)
    end
    local decodeOk, decoded = pcall(FacetJson.decode, contents)
    if not decodeOk then
        return nil, string.format('The manifest is not valid JSON:\n%s\n\n%s', path, tostring(decoded))
    end
    if type(decoded) ~= 'table' then
        return nil, 'The manifest must be a JSON object.'
    end
    local version = decoded[FIELD_VERSION]
    if version ~= MANIFEST_VERSION then
        return nil, string.format(
            'Unsupported manifest version: %s.\n\nThis plug-in reads version %d manifests only. '
            .. 'Re-export with a matching version of Facet:\n\n    python facet.py --export-manifest',
            tostring(version), MANIFEST_VERSION)
    end
    if type(decoded[FIELD_PHOTOS]) ~= 'table' then
        return nil, string.format('The manifest has no "%s" list.', FIELD_PHOTOS)
    end
    return decoded
end

-- FacetJson.decode returns the sentinel table FacetJson.null for a literal
-- JSON `null` -- that sentinel is truthy in Lua, so every read of a nullable
-- manifest field must go through this one normaliser rather than a bare
-- `record[FIELD_X]` truthiness check (finding B2). Centralised here so a
-- fifth nullable field added later cannot reintroduce the bug.
local function nullable(value)
    if value == FacetJson.null then
        return nil
    end
    return value
end

local function recordBurstGroupId(record)
    -- burst_group_id may legitimately be 0 -- never coerce through
    -- truthiness, only through nullable()'s explicit sentinel check.
    return nullable(record[FIELD_BURST_GROUP_ID])
end

local function recordSequenceKind(record)
    return nullable(record[FIELD_SEQUENCE_KIND])
end

local function recordSequenceGroupId(record)
    return nullable(record[FIELD_SEQUENCE_GROUP_ID])
end

local function recordDateTaken(record)
    return nullable(record[FIELD_DATE_TAKEN])
end

local function isKeepWholeSequenceKind(kind)
    return kind ~= nil and KEEP_WHOLE_SEQUENCE_KINDS[kind] == true
end

-- Written into a lowercase slot the moment two distinct manifest paths fold
-- to the same key, so findRecord can refuse the fallback instead of handing
-- back whichever of the two records happened to be indexed last.
local COLLISION = {}

local function buildIndex(manifest)
    local index = { exact = {}, lowercase = {}, count = 0, collisions = 0, sample = nil }
    local firstPathForKey = {}
    for _, record in ipairs(manifest[FIELD_PHOTOS]) do
        if type(record) == 'table' then
            local path = normalizePath(record[FIELD_PATH])
            if path then
                index.exact[path] = record
                local key = string.lower(path)
                local firstPath = firstPathForKey[key]
                if not firstPath then
                    firstPathForKey[key] = path
                    index.lowercase[key] = record
                elseif firstPath ~= path and index.lowercase[key] ~= COLLISION then
                    index.lowercase[key] = COLLISION
                    index.collisions = index.collisions + 1
                end
                index.count = index.count + 1
                if not index.sample then
                    index.sample = path
                end
            end
        end
    end
    return index
end

-- 'YYYY:MM:DD HH:MM:SS' (EXIF separator) -> 'YYYY-MM-DD HH:MM:SS' (ISO, with
-- seconds -- an earlier draft truncated to HH:MM, corrected here).
local function isoDateFromExif(dateTaken)
    if type(dateTaken) ~= 'string' then
        return nil
    end
    local year, month, day, rest = string.match(dateTaken, '^(%d%d%d%d):(%d%d):(%d%d)(.*)$')
    if not year then
        return nil
    end
    return string.format('%s-%s-%s%s', year, month, day, rest)
end

local function filenameFromPath(path)
    if type(path) ~= 'string' then
        return ''
    end
    return string.match(path, '([^/]+)$') or path
end

-- "yyyy-mm-dd HH:MM:SS - <filename>", or a '~'-prefixed fallback for a group
-- whose earliest member has no date_taken -- '~' sorts after every ISO-dated
-- name in Lightroom's plain string sort, so undated groups never interleave
-- with dated ones.
local function groupDisplayName(earliestDateTaken, earliestPath)
    local iso = isoDateFromExif(earliestDateTaken)
    local filename = filenameFromPath(earliestPath)
    if iso then
        return string.format('%s \226\128\147 %s', iso, filename)
    end
    return string.format('~ (no date) \226\128\147 %s', filename)
end

-- True when `candidatePath`/`candidateDate` is earlier than the current best,
-- using the same (date_taken, path) total order `_load_photos` sorts by. A
-- nil date_taken sorts *after* every dated candidate, so an undated member
-- only wins when nothing in the group has a date at all.
local function isEarlier(candidateDate, candidatePath, bestDate, bestPath)
    if bestPath == nil then
        return true
    end
    if candidateDate == nil and bestDate == nil then
        return candidatePath < bestPath
    end
    if candidateDate == nil then
        return false
    end
    if bestDate == nil then
        return true
    end
    if candidateDate ~= bestDate then
        return candidateDate < bestDate
    end
    return candidatePath < bestPath
end

-- One pass over the WHOLE manifest (finding B5): computes, per burst group
-- and per (sequence_kind, sequence_group_id) set, the facts that must be
-- decided from every manifest member, not just the ones in the current
-- Lightroom scope -- member count, whether any member is a burst lead, the
-- earliest (date_taken, path) for naming, and whether every member of a
-- burst group also belongs to a keep-whole sequence set.
local function buildGroupIndex(manifest)
    local burstGroups = {}
    local sequenceSets = {}

    local function touchBurstGroup(id)
        local group = burstGroups[id]
        if not group then
            group = { count = 0, hasLead = false, allKeepWhole = true,
                       earliestDate = nil, earliestPath = nil }
            burstGroups[id] = group
        end
        return group
    end

    local function touchSequenceSet(key)
        local set = sequenceSets[key]
        if not set then
            set = { count = 0, earliestDate = nil, earliestPath = nil }
            sequenceSets[key] = set
        end
        return set
    end

    for _, record in ipairs(manifest[FIELD_PHOTOS]) do
        if type(record) == 'table' then
            local path = normalizePath(record[FIELD_PATH])
            local dateTaken = recordDateTaken(record)
            local burstGroupId = recordBurstGroupId(record)
            local sequenceKind = recordSequenceKind(record)
            local sequenceGroupId = recordSequenceGroupId(record)

            if burstGroupId ~= nil and path then
                local group = touchBurstGroup(burstGroupId)
                group.count = group.count + 1
                if record[FIELD_IS_BURST_LEAD] == true then
                    group.hasLead = true
                end
                if not isKeepWholeSequenceKind(sequenceKind) then
                    group.allKeepWhole = false
                end
                if isEarlier(dateTaken, path, group.earliestDate, group.earliestPath) then
                    group.earliestDate = dateTaken
                    group.earliestPath = path
                end
            end

            if sequenceKind ~= nil and sequenceGroupId ~= nil and path then
                local key = sequenceKind .. '|' .. tostring(sequenceGroupId)
                local set = touchSequenceSet(key)
                set.count = set.count + 1
                if isEarlier(dateTaken, path, set.earliestDate, set.earliestPath) then
                    set.earliestDate = dateTaken
                    set.earliestPath = path
                end
            end
        end
    end

    return { burstGroups = burstGroups, sequenceSets = sequenceSets }
end

local function mapToManifestPath(catalogPath, catalogPrefix, manifestPrefix)
    local normalized = normalizePath(catalogPath)
    if not normalized or catalogPrefix == '' then
        return normalized
    end
    local head = string.sub(normalized, 1, #catalogPrefix)
    if string.lower(head) ~= string.lower(catalogPrefix) then
        return normalized
    end
    return manifestPrefix .. string.sub(normalized, #catalogPrefix + 1)
end

local function findRecord(index, path)
    if not path then
        return nil
    end
    local record = index.exact[path]
    if record then
        return record
    end
    local fallback = index.lowercase[string.lower(path)]
    if fallback == COLLISION then
        return nil
    end
    return fallback
end

-- Returns (rating, isDerived). `isDerived` is true only when the value came
-- from the score_stars fallback rather than a real manifest star_rating --
-- callers must force `overwrite = false` for a derived value regardless of
-- the Overwrite preference (finding: derived stars never overwrite an
-- existing Lightroom rating, even with Overwrite ticked).
local function desiredRating(record, allowScoreFallback)
    local stars = record[FIELD_STAR_RATING]
    if type(stars) == 'number' and stars > 0 then
        if stars > MAXIMUM_RATING then
            return MAXIMUM_RATING, false
        end
        return math.floor(stars), false
    end
    if not allowScoreFallback then
        return nil, false
    end
    local derived = record[FIELD_SCORE_STARS]
    if type(derived) ~= 'number' or derived <= 0 then
        return nil, false
    end
    if derived > MAXIMUM_RATING then
        return MAXIMUM_RATING, true
    end
    return math.floor(derived), true
end

-- Manual is_favorite/is_rejected always wins unconditionally. Otherwise, when
-- `burstDecision` says this record's burst group has a lead somewhere in the
-- whole manifest, a lead is picked and a non-keep-whole, non-lead member is
-- rejected only when `rejectOthers` is enabled. `burstDecision` is nil for a
-- record with no burst_group_id, or for a group with no lead anywhere.
local function desiredPickStatus(record, burstDecision, pickLeads, rejectOthers)
    if record[FIELD_IS_REJECTED] == true then
        return PICK_STATUS_REJECTED
    end
    if record[FIELD_IS_FAVORITE] == true then
        return PICK_STATUS_PICKED
    end
    if not burstDecision then
        return nil
    end
    if pickLeads and record[FIELD_IS_BURST_LEAD] == true then
        return PICK_STATUS_PICKED
    end
    if rejectOthers and pickLeads and record[FIELD_IS_BURST_LEAD] ~= true
        and not isKeepWholeSequenceKind(recordSequenceKind(record)) then
        return PICK_STATUS_REJECTED
    end
    return nil
end

-- Decide what one sticky field (rating or pick status) should do: the value
-- to write (nil for "leave alone"), and whether the current and wanted
-- values conflict under the write-once default -- never touch a value
-- Lightroom already holds unless `overwrite` says otherwise.
local function resolveField(current, wanted, emptyValue, overwrite)
    if not wanted then
        return nil, false
    end
    if current == emptyValue or overwrite then
        if wanted ~= current then
            return wanted, false
        end
        return nil, false
    end
    if current ~= wanted then
        return nil, true
    end
    return nil, false
end

local function collectFolderPhotos(catalog)
    local photos = {}
    local seen = {}
    local count = 0
    local sources = catalog:getActiveSources()
    for _, source in ipairs(sources or {}) do
        if type(source) ~= 'string' then
            local ok, sourcePhotos = pcall(function()
                return source:getPhotos()
            end)
            if ok and type(sourcePhotos) == 'table' then
                for _, photo in ipairs(sourcePhotos) do
                    local key = photo.localIdentifier or photo
                    if not seen[key] then
                        seen[key] = true
                        count = count + 1
                        photos[count] = photo
                    end
                end
            end
        end
    end
    return photos
end

local function resolveScope(catalog, scope)
    if scope == SCOPE_FOLDER then
        local photos = collectFolderPhotos(catalog)
        if #photos > 0 then
            return photos
        end
        return nil, 'Could not read the photos of the current folder. Select the photos in the '
            .. 'filmstrip and run the plug-in again with the "Selected photos" scope.'
    end
    local photos = catalog:getTargetPhotos()
    if not photos or #photos == 0 then
        return nil, 'No photos are selected. Select photos in the Library filmstrip and try again.'
    end
    return photos
end

-- Group-level pick/reject decision for one burst group: nil unless the
-- group (over the WHOLE manifest) has at least two members and at least one
-- is_burst_lead member. A lone frame is no burst to pick from, and a leadless
-- group is skipped entirely, no picks and no rejects derived.
local function burstDecisionFor(groupIndex, burstGroupId)
    if burstGroupId == nil then
        return nil
    end
    local group = groupIndex.burstGroups[burstGroupId]
    if not group or group.count < 2 or not group.hasLead then
        return nil
    end
    return group
end

local function buildPlan(catalog, photos, index, groupIndex, preferences, progress, logger)
    local plan = {
        entries = {},
        entryCount = 0,
        scoped = #photos,
        matched = 0,
        unmatched = 0,
        ratingWrites = 0,
        pickWrites = 0,
        conflicts = 0,
        unchanged = 0,
        canceled = false,
        sampleCatalogPath = nil,
        sampleMappedPath = nil,
        -- Collection membership is planned separately from `entries` (which
        -- stays rating/flag-only) so applyPlan can apply the two concerns in
        -- separate SDK transactions (finding B5).
        burstScopeMembers = {},
        sequenceScopeMembers = {},
    }
    local catalogPrefix = normalizePrefix(preferences.catalogPrefix)
    local manifestPrefix = normalizePrefix(preferences.manifestPrefix)
    local total = plan.scoped
    for chunkStart = 1, total, READ_CHUNK_SIZE do
        if progress:isCanceled() then
            plan.canceled = true
            return plan
        end
        local chunkEnd = math.min(chunkStart + READ_CHUNK_SIZE - 1, total)
        local chunk = {}
        local chunkCount = 0
        for position = chunkStart, chunkEnd do
            chunkCount = chunkCount + 1
            chunk[chunkCount] = photos[position]
        end
        local metadata = catalog:batchGetRawMetadata(chunk, METADATA_KEYS)
        for _, photo in ipairs(chunk) do
            local values = metadata and metadata[photo] or {}
            local catalogPath = values[METADATA_PATH]
            local mappedPath = mapToManifestPath(catalogPath, catalogPrefix, manifestPrefix)
            if not plan.sampleCatalogPath and catalogPath then
                plan.sampleCatalogPath = catalogPath
                plan.sampleMappedPath = mappedPath
            end
            local record = findRecord(index, mappedPath)
            if not record then
                plan.unmatched = plan.unmatched + 1
                if logger.misses < LOGGED_MISS_LIMIT then
                    logger.misses = logger.misses + 1
                    logger.write(string.format('MISS %s -> %s', tostring(catalogPath), tostring(mappedPath)))
                    if logger.misses == LOGGED_MISS_LIMIT then
                        logger.write(string.format('MISS further misses are not logged (limit %d)', LOGGED_MISS_LIMIT))
                    end
                end
            else
                plan.matched = plan.matched + 1
                local currentRating = tonumber(values[METADATA_RATING]) or 0
                local currentPick = tonumber(values[METADATA_PICK_STATUS]) or PICK_STATUS_NONE
                local wantedRating, ratingIsDerived = desiredRating(record, preferences.starsFromScore)
                local burstGroupId = recordBurstGroupId(record)
                local burstDecision = burstDecisionFor(groupIndex, burstGroupId)
                local wantedPick = desiredPickStatus(
                    record, burstDecision, preferences.pickBurstLeads, preferences.rejectBurstOthers)
                local entry = { photo = photo }
                local conflicted = false

                -- Derived stars never overwrite an existing Lightroom rating,
                -- even with the Overwrite checkbox ticked -- a hard rule
                -- distinct from resolveField's general overwrite semantics.
                local ratingOverwrite = preferences.overwrite and not ratingIsDerived
                local ratingValue, ratingConflict = resolveField(
                    currentRating, wantedRating, 0, ratingOverwrite)
                if ratingValue then
                    entry.rating = ratingValue
                    plan.ratingWrites = plan.ratingWrites + 1
                end
                conflicted = conflicted or ratingConflict

                local pickValue, pickConflict = resolveField(
                    currentPick, wantedPick, PICK_STATUS_NONE, preferences.overwrite)
                if pickValue then
                    entry.pickStatus = pickValue
                    plan.pickWrites = plan.pickWrites + 1
                end
                conflicted = conflicted or pickConflict

                if conflicted then
                    plan.conflicts = plan.conflicts + 1
                end
                if entry.rating or entry.pickStatus then
                    entry.path = catalogPath
                    plan.entryCount = plan.entryCount + 1
                    plan.entries[plan.entryCount] = entry
                elseif not conflicted then
                    plan.unchanged = plan.unchanged + 1
                end

                if burstGroupId ~= nil then
                    local list = plan.burstScopeMembers[burstGroupId]
                    if not list then
                        list = {}
                        plan.burstScopeMembers[burstGroupId] = list
                    end
                    list[#list + 1] = photo
                end
                local sequenceKind = recordSequenceKind(record)
                local sequenceGroupId = recordSequenceGroupId(record)
                if sequenceKind ~= nil and sequenceGroupId ~= nil then
                    local key = sequenceKind .. '|' .. tostring(sequenceGroupId)
                    local list = plan.sequenceScopeMembers[key]
                    if not list then
                        list = {}
                        plan.sequenceScopeMembers[key] = list
                    end
                    list[#list + 1] = photo
                end
            end
        end
        progress:setPortionComplete(chunkEnd, total)
        LrTasks.yield()
    end
    return plan
end

-- Collection membership plan, built from the whole-manifest groupIndex
-- (member counts, names) plus the in-scope member lists buildPlan gathered.
-- Independent of plan.entries -- applyPlan applies this in its own SDK
-- transaction. Only groups with >=2 in-scope, matched members produce a
-- collection; a plain burst group whose members are ALL also members of a
-- keep-whole set produces no Bursts collection (it already gets one under
-- Brackets/Panoramas/HDR panoramas).
local function buildCollectionPlan(groupIndex, burstScopeMembers, sequenceScopeMembers)
    local collections = {}
    local count = 0
    for burstGroupId, members in pairs(burstScopeMembers) do
        if #members >= 2 then
            local group = groupIndex.burstGroups[burstGroupId]
            if group and not group.allKeepWhole then
                count = count + 1
                collections[count] = {
                    setName = COLLECTION_SET_BURSTS,
                    name = groupDisplayName(group.earliestDate, group.earliestPath),
                    members = members,
                }
            end
        end
    end
    for key, members in pairs(sequenceScopeMembers) do
        if #members >= 2 then
            local set = groupIndex.sequenceSets[key]
            local kind = string.match(key, '^([^|]+)|')
            local setName = kind and SEQUENCE_KIND_COLLECTION_SET[kind]
            if set and setName then
                count = count + 1
                collections[count] = {
                    setName = setName,
                    name = groupDisplayName(set.earliestDate, set.earliestPath),
                    members = members,
                }
            end
        end
    end
    return { collections = collections, count = count }
end

-- Write one raw-metadata field via a guarded pcall, logging and returning
-- whether it landed. `label` names the field in the failure log line
-- ('rating' / 'flag'), matching the two call sites' previous wording.
local function writeField(photo, key, value, label, path, logger)
    local ok, message = pcall(function()
        photo:setRawMetadata(key, value)
    end)
    if not ok then
        logger.write(string.format('FAIL %s %s: %s', label, tostring(path), tostring(message)))
    end
    return ok
end

local function applyPlan(catalog, plan, progress, logger)
    local outcome = { ratingsSet = 0, picksSet = 0, photosTouched = 0, failed = 0, canceled = false }
    local total = plan.entryCount
    for chunkStart = 1, total, WRITE_CHUNK_SIZE do
        if progress:isCanceled() then
            outcome.canceled = true
            return outcome
        end
        local chunkEnd = math.min(chunkStart + WRITE_CHUNK_SIZE - 1, total)
        local writeOk, writeError = LrTasks.pcall(function()
            catalog:withWriteAccessDo(ACTION_NAME, function()
                for position = chunkStart, chunkEnd do
                    local entry = plan.entries[position]
                    local touched = false
                    if entry.rating then
                        if writeField(entry.photo, METADATA_RATING, entry.rating, 'rating', entry.path, logger) then
                            outcome.ratingsSet = outcome.ratingsSet + 1
                            touched = true
                        else
                            outcome.failed = outcome.failed + 1
                        end
                    end
                    if entry.pickStatus then
                        if writeField(entry.photo, METADATA_PICK_STATUS, entry.pickStatus, 'flag', entry.path, logger) then
                            outcome.picksSet = outcome.picksSet + 1
                            touched = true
                        else
                            outcome.failed = outcome.failed + 1
                        end
                    end
                    if touched then
                        outcome.photosTouched = outcome.photosTouched + 1
                        logger.write(string.format('SET %s rating=%s flag=%s', tostring(entry.path),
                            tostring(entry.rating), tostring(entry.pickStatus)))
                    end
                end
            end, { timeout = WRITE_TIMEOUT_SECONDS })
        end)
        if not writeOk then
            outcome.failed = outcome.failed + (chunkEnd - chunkStart + 1)
            logger.write(string.format('FAIL write batch %d-%d: %s', chunkStart, chunkEnd, tostring(writeError)))
        end
        progress:setPortionComplete(chunkEnd, total)
        LrTasks.yield()
    end
    return outcome
end

-- Find-or-create the "Facet" root collection set and its four kind children
-- (canReturnPrior = true everywhere, so a re-run resolves the existing
-- objects rather than duplicating). This call returns before any child
-- collection is created under the sets -- a confirmed SDK constraint -- so
-- callers must not create collections inside the same withWriteAccessDo.
local function ensureCollectionSets(catalog)
    local sets = {}
    catalog:withWriteAccessDo(ACTION_NAME .. ': collection sets', function()
        local root = catalog:createCollectionSet(COLLECTION_ROOT_NAME, nil, true)
        sets[COLLECTION_SET_BURSTS] = catalog:createCollectionSet(COLLECTION_SET_BURSTS, root, true)
        for _, setName in pairs(SEQUENCE_KIND_COLLECTION_SET) do
            sets[setName] = catalog:createCollectionSet(setName, root, true)
        end
    end, { timeout = WRITE_TIMEOUT_SECONDS })
    return sets
end

-- Applies the collection plan additively: creates (or finds, canReturnPrior)
-- each planned collection under its kind set, then adds this run's in-scope
-- members. Never removes a photo -- a partial-scope run (e.g. "Selected
-- photos") must not evict members an earlier, wider run added; a collection
-- can go stale relative to a regrouped set, a documented known limitation.
local function applyCollectionPlan(catalog, collectionPlan, progress, logger)
    local outcome = { collectionsTouched = 0, photosAdded = 0, failed = 0, canceled = false }
    if collectionPlan.count == 0 then
        return outcome
    end
    -- ensureCollectionSets does its own catalog write (find-or-create the
    -- "Facet" root and its kind sets); wrap it the same way the collection
    -- write below is wrapped, so a failure here (e.g. a write-access
    -- timeout) is reported in the summary instead of raising past the
    -- ratings/flags that were already written for this run.
    local setsOk, setsOrError = LrTasks.pcall(function()
        return ensureCollectionSets(catalog)
    end)
    if not setsOk then
        outcome.failed = collectionPlan.count
        logger.write(string.format('FAIL collection sets: %s', tostring(setsOrError)))
        if progress then
            progress:setPortionComplete(1, 1)
        end
        return outcome
    end
    local sets = setsOrError
    local writeOk, writeError = LrTasks.pcall(function()
        catalog:withWriteAccessDo(ACTION_NAME .. ': collections', function()
            for _, planned in ipairs(collectionPlan.collections) do
                local parent = sets[planned.setName]
                local collection = catalog:createCollection(planned.name, parent, true)
                collection:addPhotos(planned.members)
                outcome.collectionsTouched = outcome.collectionsTouched + 1
                outcome.photosAdded = outcome.photosAdded + #planned.members
                logger.write(string.format('COLLECTION %s/%s +%d', planned.setName, planned.name, #planned.members))
            end
        end, { timeout = WRITE_TIMEOUT_SECONDS })
    end)
    if not writeOk then
        outcome.failed = collectionPlan.count
        logger.write(string.format('FAIL collections: %s', tostring(writeError)))
    end
    if progress then
        progress:setPortionComplete(1, 1)
    end
    return outcome
end

local function presentSettingsDialog(context, preferences)
    local viewFactory = LrView.osFactory()
    local bind = LrView.bind
    local share = LrView.share
    local properties = LrBinding.makePropertyTable(context)
    properties.manifestPath = preferences.manifestPath
    properties.catalogPrefix = preferences.catalogPrefix
    properties.manifestPrefix = preferences.manifestPrefix
    properties.scope = preferences.scope
    properties.overwrite = preferences.overwrite
    properties.debugLog = preferences.debugLog
    properties.starsFromScore = preferences.starsFromScore
    properties.pickBurstLeads = preferences.pickBurstLeads
    properties.rejectBurstOthers = preferences.rejectBurstOthers and preferences.pickBurstLeads
    properties.createCollections = preferences.createCollections

    local contents = viewFactory:column {
        bind_to_object = properties,
        spacing = viewFactory:control_spacing(),
        viewFactory:static_text {
            title = 'Reads ' .. MANIFEST_FILE_NAME .. ' and writes the Facet star ratings and '
                .. 'favourite/reject flags into this Lightroom catalog.',
        },
        viewFactory:row {
            viewFactory:static_text {
                title = 'Manifest file:',
                alignment = 'right',
                width = share 'facet_label_width',
            },
            viewFactory:edit_field {
                value = bind 'manifestPath',
                width_in_chars = 44,
                immediate = true,
            },
            viewFactory:push_button {
                title = 'Browse...',
                action = function()
                    LrTasks.startAsyncTask(function()
                        local chosen = LrDialogs.runOpenPanel {
                            title = 'Select ' .. MANIFEST_FILE_NAME,
                            canChooseFiles = true,
                            canChooseDirectories = false,
                            allowsMultipleSelection = false,
                            fileTypes = { 'json' },
                        }
                        if chosen and chosen[1] then
                            properties.manifestPath = chosen[1]
                        end
                    end)
                end,
            },
        },
        viewFactory:static_text {
            title = 'Path mapping - only needed when Facet scanned the photos from another machine.',
        },
        viewFactory:static_text {
            title = 'Example: Lightroom "Z:\\photos" = Facet "/volume1/photos". Leave both empty when '
                .. 'Facet and Lightroom see the same paths.',
        },
        viewFactory:row {
            viewFactory:static_text {
                title = 'Lightroom path starts with:',
                alignment = 'right',
                width = share 'facet_label_width',
            },
            viewFactory:edit_field {
                value = bind 'catalogPrefix',
                width_in_chars = 44,
                immediate = true,
            },
        },
        viewFactory:row {
            viewFactory:static_text {
                title = 'Facet path starts with:',
                alignment = 'right',
                width = share 'facet_label_width',
            },
            viewFactory:edit_field {
                value = bind 'manifestPrefix',
                width_in_chars = 44,
                immediate = true,
            },
        },
        viewFactory:row {
            viewFactory:static_text {
                title = 'Apply to:',
                alignment = 'right',
                width = share 'facet_label_width',
            },
            viewFactory:radio_button {
                title = 'Selected photos',
                value = bind 'scope',
                checked_value = SCOPE_SELECTION,
            },
            viewFactory:radio_button {
                title = 'All photos of the current folder',
                value = bind 'scope',
                checked_value = SCOPE_FOLDER,
            },
        },
        viewFactory:checkbox {
            title = 'Overwrite ratings and flags that are already set in Lightroom',
            value = bind 'overwrite',
        },
        viewFactory:checkbox {
            title = 'Fill in star ratings from Facet scores for photos you have not rated',
            value = bind 'starsFromScore',
        },
        viewFactory:checkbox {
            title = 'Pick the recommended frame of each burst',
            value = bind 'pickBurstLeads',
        },
        viewFactory:row {
            viewFactory:static_text { title = '    ' },
            viewFactory:checkbox {
                title = 'Reject the other frames (never a bracket/panorama/HDR-panorama member)',
                value = bind 'rejectBurstOthers',
                enabled = bind 'pickBurstLeads',
            },
        },
        viewFactory:checkbox {
            title = 'Create Facet collections for bursts, brackets, panoramas and HDR panoramas',
            value = bind 'createCollections',
        },
        viewFactory:checkbox {
            title = 'Write ' .. LOG_FILE_NAME .. ' next to the manifest',
            value = bind 'debugLog',
        },
    }

    local result = LrDialogs.presentModalDialog {
        title = DIALOG_TITLE .. ' - apply ratings and flags',
        contents = contents,
        actionVerb = 'Preview...',
    }
    if result ~= 'ok' then
        return nil
    end
    preferences.manifestPath = properties.manifestPath or ''
    preferences.catalogPrefix = properties.catalogPrefix or ''
    preferences.manifestPrefix = properties.manifestPrefix or ''
    preferences.scope = properties.scope
    preferences.overwrite = properties.overwrite and true or false
    preferences.debugLog = properties.debugLog and true or false
    preferences.starsFromScore = properties.starsFromScore and true or false
    preferences.pickBurstLeads = properties.pickBurstLeads and true or false
    preferences.rejectBurstOthers = properties.rejectBurstOthers and true or false
    preferences.createCollections = properties.createCollections and true or false
    return preferences
end

local function pathHint(plan, index)
    return string.format(
        '\n\nPath seen in Lightroom:\n    %s\nLooked up as:\n    %s\nPath seen in the manifest:\n    %s',
        tostring(plan.sampleCatalogPath), tostring(plan.sampleMappedPath), tostring(index.sample))
end

local function previewMessage(plan, manifest, index, preferences, collectionPlan)
    local lines = {
        string.format('Photos in scope: %d', plan.scoped),
        '',
        string.format('MATCHED in the manifest:   %d', plan.matched),
        string.format('NOT FOUND in the manifest: %d', plan.unmatched),
    }
    if index.collisions > 0 then
        lines[#lines + 1] = string.format(
            'Ambiguous by case only, matched by exact path alone: %d', index.collisions)
    end
    lines[#lines + 1] = ''
    lines[#lines + 1] = string.format('Star ratings to set: %d', plan.ratingWrites)
    lines[#lines + 1] = string.format('Pick/reject flags to set: %d', plan.pickWrites)
    lines[#lines + 1] = string.format('Already up to date: %d', plan.unchanged)
    lines[#lines + 1] = string.format(
        'Kept as they are (already rated or flagged by hand): %d', plan.conflicts)
    if collectionPlan then
        lines[#lines + 1] = string.format('Collections to create/refresh: %d', collectionPlan.count)
    end
    lines[#lines + 1] = ''
    lines[#lines + 1] = string.format(
        'Manifest: %d photos, exported %s', index.count, tostring(manifest[FIELD_GENERATED_AT]))
    if preferences.overwrite then
        lines[#lines + 1] = 'Overwrite is ON: existing Lightroom ratings and flags will be replaced.'
    end
    local message = table.concat(lines, '\n')
    if plan.unmatched > 0 then
        message = message .. pathHint(plan, index)
    end
    return message
end

-- Whether the run has nothing left to do: no rating/flag writes AND no
-- collection work queued. Both must be empty -- a collection-only run (no
-- rating changes, just a set newly crossing the >=2-frame threshold) must
-- still proceed rather than stop here.
local function hasNothingToApply(plan, collectionPlan)
    return plan.entryCount == 0 and collectionPlan.count == 0
end

-- Whether the collection plan should run at all: only when there is
-- collection work queued AND the rating/flag write was not canceled --
-- a canceled write leaves the run's photos only partially rated/flagged,
-- so collections built from that state would be misleading (finding M2).
local function shouldApplyCollectionPlan(outcome, collectionPlan)
    return collectionPlan.count > 0 and not outcome.canceled
end

-- collectionsSkippedByCancel is true when collection work was queued but
-- skipped because the rating/flag write was canceled (finding M2) -- a
-- canceled write leaves an inconsistent subset of the run's photos rated,
-- so building collections from that partial state would be misleading.
local function summaryMessage(plan, outcome, collectionOutcome, collectionsSkippedByCancel)
    local lines = {
        string.format('Photos changed: %d', outcome.photosTouched),
        string.format('Star ratings set: %d', outcome.ratingsSet),
        string.format('Pick/reject flags set: %d', outcome.picksSet),
        '',
        string.format('Already up to date: %d', plan.unchanged),
        string.format('Kept as they are (already rated or flagged by hand): %d', plan.conflicts),
        string.format('Not found in the manifest: %d', plan.unmatched),
    }
    if outcome.failed > 0 then
        lines[#lines + 1] = string.format('Failed: %d', outcome.failed)
    end
    if collectionOutcome then
        lines[#lines + 1] = string.format('Collections created/refreshed: %d (photos added: %d)',
            collectionOutcome.collectionsTouched, collectionOutcome.photosAdded)
        if collectionOutcome.failed > 0 then
            lines[#lines + 1] = string.format('Collection failures: %d', collectionOutcome.failed)
        end
    end
    if outcome.canceled then
        lines[#lines + 1] = ''
        lines[#lines + 1] = 'Canceled - the photos already written keep their new values.'
        if collectionsSkippedByCancel then
            lines[#lines + 1] = 'Collections were not created: the rating/flag write was canceled.'
        end
    end
    return table.concat(lines, '\n')
end

local function run(context)
    local preferences = loadPreferences()
    if not presentSettingsDialog(context, preferences) then
        return
    end
    local manifest, manifestError = readManifest(preferences.manifestPath)
    if not manifest then
        LrDialogs.message(DIALOG_TITLE, manifestError, 'critical')
        return
    end
    local catalog = LrApplication.activeCatalog()
    local photos, scopeError = resolveScope(catalog, preferences.scope)
    if not photos then
        LrDialogs.message(DIALOG_TITLE, scopeError, 'warning')
        return
    end

    local logger = openLog(preferences)
    logger.write(string.format('RUN manifest=%s scope=%s overwrite=%s photos=%d',
        preferences.manifestPath, preferences.scope, tostring(preferences.overwrite), #photos))

    local index = buildIndex(manifest)
    if index.count == 0 then
        logger.close()
        LrDialogs.message(DIALOG_TITLE, 'The manifest contains no usable photo paths.', 'critical')
        return
    end
    local groupIndex = buildGroupIndex(manifest)

    local progress = makeProgressScope(context, 'Facet: reading Lightroom metadata')
    local plan = buildPlan(catalog, photos, index, groupIndex, preferences, progress, logger)
    progress:done()
    if plan.canceled then
        logger.write('CANCELED during preview')
        logger.close()
        return
    end

    logger.write(string.format('PLAN matched=%d unmatched=%d ratings=%d flags=%d conflicts=%d',
        plan.matched, plan.unmatched, plan.ratingWrites, plan.pickWrites, plan.conflicts))

    if plan.matched == 0 then
        logger.close()
        LrDialogs.message(DIALOG_TITLE,
            string.format('None of the %d photos in scope were found in the manifest.\n\n'
                .. 'The manifest stores the paths of the machine that scanned the photos. '
                .. 'Set the two path prefixes in the plug-in dialog so they match.%s',
                plan.scoped, pathHint(plan, index)),
            'critical')
        return
    end

    local collectionPlan = { collections = {}, count = 0 }
    if preferences.createCollections then
        collectionPlan = buildCollectionPlan(groupIndex, plan.burstScopeMembers, plan.sequenceScopeMembers)
    end

    if hasNothingToApply(plan, collectionPlan) then
        logger.close()
        LrDialogs.message(DIALOG_TITLE,
            string.format('Nothing to change.\n\n%s',
                previewMessage(plan, manifest, index, preferences, collectionPlan)))
        return
    end

    local confirmed = LrDialogs.confirm(DIALOG_TITLE .. ' - preview',
        previewMessage(plan, manifest, index, preferences, collectionPlan), 'Apply', 'Cancel')
    if confirmed ~= 'ok' then
        logger.write('CANCELED at the preview dialog')
        logger.close()
        return
    end

    local writeProgress = makeProgressScope(context, 'Facet: writing ratings and flags')
    local outcome = applyPlan(catalog, plan, writeProgress, logger)
    writeProgress:done()

    -- A canceled write leaves the run's photos only partially rated/flagged;
    -- skip collection work rather than build sets from that inconsistent
    -- state, and say so in the summary (finding M2).
    local collectionOutcome = nil
    local collectionsSkippedByCancel = collectionPlan.count > 0 and outcome.canceled
    if shouldApplyCollectionPlan(outcome, collectionPlan) then
        local collectionProgress = makeProgressScope(context, 'Facet: creating collections')
        collectionOutcome = applyCollectionPlan(catalog, collectionPlan, collectionProgress, logger)
        collectionProgress:done()
    end

    logger.write(string.format('DONE photos=%d ratings=%d flags=%d failed=%d canceled=%s',
        outcome.photosTouched, outcome.ratingsSet, outcome.picksSet, outcome.failed,
        tostring(outcome.canceled)))
    logger.close()

    LrDialogs.message(DIALOG_TITLE .. ' - done',
        summaryMessage(plan, outcome, collectionOutcome, collectionsSkippedByCancel))
end

-- Test seam: hands the module-private helpers to a Lua test harness running
-- against a stubbed LR SDK (tests/test_lrplugin_apply.py). Lightroom itself
-- never sets this global, so production loads fall straight through to the
-- real entry point below.
if FACET_APPLY_TEST_HOOKS then
    FACET_APPLY_TEST_HOOKS.normalizePath = normalizePath
    FACET_APPLY_TEST_HOOKS.buildIndex = buildIndex
    FACET_APPLY_TEST_HOOKS.findRecord = findRecord
    FACET_APPLY_TEST_HOOKS.resolveField = resolveField
    FACET_APPLY_TEST_HOOKS.writeField = writeField
    FACET_APPLY_TEST_HOOKS.buildPlan = buildPlan
    FACET_APPLY_TEST_HOOKS.applyPlan = applyPlan
    FACET_APPLY_TEST_HOOKS.previewMessage = previewMessage
    FACET_APPLY_TEST_HOOKS.summaryMessage = summaryMessage
    FACET_APPLY_TEST_HOOKS.desiredRating = desiredRating
    FACET_APPLY_TEST_HOOKS.desiredPickStatus = desiredPickStatus
    FACET_APPLY_TEST_HOOKS.nullable = nullable
    FACET_APPLY_TEST_HOOKS.recordBurstGroupId = recordBurstGroupId
    FACET_APPLY_TEST_HOOKS.recordSequenceKind = recordSequenceKind
    FACET_APPLY_TEST_HOOKS.recordSequenceGroupId = recordSequenceGroupId
    FACET_APPLY_TEST_HOOKS.recordDateTaken = recordDateTaken
    FACET_APPLY_TEST_HOOKS.isKeepWholeSequenceKind = isKeepWholeSequenceKind
    FACET_APPLY_TEST_HOOKS.buildGroupIndex = buildGroupIndex
    FACET_APPLY_TEST_HOOKS.burstDecisionFor = burstDecisionFor
    FACET_APPLY_TEST_HOOKS.buildCollectionPlan = buildCollectionPlan
    FACET_APPLY_TEST_HOOKS.groupDisplayName = groupDisplayName
    FACET_APPLY_TEST_HOOKS.isoDateFromExif = isoDateFromExif
    FACET_APPLY_TEST_HOOKS.readManifest = readManifest
    FACET_APPLY_TEST_HOOKS.ensureCollectionSets = ensureCollectionSets
    FACET_APPLY_TEST_HOOKS.applyCollectionPlan = applyCollectionPlan
    FACET_APPLY_TEST_HOOKS.hasNothingToApply = hasNothingToApply
    FACET_APPLY_TEST_HOOKS.shouldApplyCollectionPlan = shouldApplyCollectionPlan
    return
end

LrFunctionContext.postAsyncTaskWithContext('facetApply', function(context)
    LrDialogs.attachErrorDialogToFunctionContext(context, ACTION_NAME)
    run(context)
end)
