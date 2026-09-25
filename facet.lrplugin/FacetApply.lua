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
local FacetCommon = require 'FacetCommon'
local FacetMetadata = require 'FacetMetadata'

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
local FIELD_CATEGORY = 'category'
local FIELD_TAGS = 'tags'
local FIELD_SCORES = 'scores'
local FIELD_AGGREGATE = 'aggregate'
local FIELD_PENDING_CORRECTIONS = 'pending_corrections'

local KEYWORD_ROOT_NAME = 'Facet'

-- Step 8: exact wording, reused verbatim across CLI/viewer/plug-in --
-- single source of truth so the string cannot drift across the three
-- surfaces (neither CLI nor plug-in is localized today).
local function PENDING_CORRECTIONS_WARNING(count)
    return string.format(
        '%d pending sequence correction(s) - run `python facet.py --detect-panoramas` or use '
        .. 'Compare \226\128\186 Panoramas \226\128\186 Re-run detection.', count)
end

local METADATA_PATH = 'path'
local METADATA_RATING = 'rating'
local METADATA_PICK_STATUS = 'pickStatus'
local METADATA_KEYWORDS = 'keywords'
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

local loadPreferences = FacetCommon.loadPreferences
local normalizePath = FacetCommon.normalizePath
local normalizePrefix = FacetCommon.normalizePrefix

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

local function recordCategory(record)
    return nullable(record[FIELD_CATEGORY])
end

local function recordTags(record)
    return nullable(record[FIELD_TAGS])
end

local function recordAggregate(record)
    local scores = nullable(record[FIELD_SCORES])
    if type(scores) ~= 'table' then
        return nil
    end
    return nullable(scores[FIELD_AGGREGATE])
end

local function manifestPendingCorrections(manifest)
    local value = nullable(manifest[FIELD_PENDING_CORRECTIONS])
    if type(value) ~= 'number' then
        return 0
    end
    return value
end

local function isKeepWholeSequenceKind(kind)
    return kind ~= nil and KEEP_WHOLE_SEQUENCE_KINDS[kind] == true
end

-- Written into a lowercase slot the moment two distinct manifest paths fold
-- to the same key, so findRecord can refuse the fallback instead of handing
-- back whichever of the two records happened to be indexed last.
local COLLISION = {}

local function filenameKeyFromPath(path)
    local name = string.match(path, '([^/]+)$') or path
    return string.lower(name)
end

local function buildIndex(manifest)
    local index = { exact = {}, lowercase = {}, byFilename = {}, count = 0, collisions = 0, sample = nil }
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
                -- Secondary filename->path lookup, for the Step 6c prefix
                -- suggestion only -- the first manifest path with a given
                -- filename wins, which is fine since the suggestion only
                -- needs ONE plausible manifest-side sample to compare.
                local filenameKey = filenameKeyFromPath(path)
                if not index.byFilename[filenameKey] then
                    index.byFilename[filenameKey] = path
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

-- The name shapes groupDisplayName can produce -- an ISO date (year-month-day)
-- with WHATEVER tail isoDateFromExif passed through verbatim (sub-second
-- fractions, a timezone offset, a missing time, trailing EXIF whitespace,
-- ...), followed by ' - <filename>'; or the undated '~ (no date) -
-- <filename>' fallback. The tail after the date must mirror isoDateFromExif's
-- own '(.*)' capture, not a hand-copied ' HH:MM:SS' shape, or a non-canonical
-- date_taken produces a name this matcher fails to recognise as Facet's own.
-- The dissolved-collection sweep must reuse this matcher (never a
-- hand-copied second pattern) to tell a collection Facet itself created
-- apart from one the user filed under a Facet kind set by hand -- a
-- user-named collection must never be swept, no matter how empty or
-- fully-in-scope its membership looks.
local function isFacetGeneratedCollectionName(name)
    if type(name) ~= 'string' then
        return false
    end
    if string.match(name, '^%d%d%d%d%-%d%d%-%d%d.* \226\128\147 .+$') then
        return true
    end
    if string.match(name, '^~ %(no date%) \226\128\147 .+$') then
        return true
    end
    return false
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

local mapToManifestPath = FacetCommon.mapToManifestPath

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
-- Returns (pickStatus, isDerived). `isDerived` is true only when the value
-- came from the burst pick/reject rule rather than a manual
-- is_favorite/is_rejected flag -- callers use this to decide whether to
-- write the facetDerivedPick bookkeeping property (Step 6b).
local function desiredPickStatus(record, burstDecision, pickLeads, rejectOthers)
    if record[FIELD_IS_REJECTED] == true then
        return PICK_STATUS_REJECTED, false
    end
    if record[FIELD_IS_FAVORITE] == true then
        return PICK_STATUS_PICKED, false
    end
    if not burstDecision then
        return nil, false
    end
    if pickLeads and record[FIELD_IS_BURST_LEAD] == true then
        return PICK_STATUS_PICKED, true
    end
    if rejectOthers and pickLeads and record[FIELD_IS_BURST_LEAD] ~= true
        and not isKeepWholeSequenceKind(recordSequenceKind(record)) then
        return PICK_STATUS_REJECTED, true
    end
    return nil, false
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
        -- Every matched (photo, record) pair, regardless of whether it
        -- produced a rating/pick change -- used by the metadata-field writer
        -- (Step 6a) and the keyword writer (Step 7), which both act on every
        -- matched photo, not just ones with a rating/flag delta.
        matchedRecords = {},
        matchedCount = 0,
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
                plan.matchedCount = plan.matchedCount + 1
                plan.matchedRecords[plan.matchedCount] = { photo = photo, record = record, path = catalogPath }
                local currentRating = tonumber(values[METADATA_RATING]) or 0
                local currentPick = tonumber(values[METADATA_PICK_STATUS]) or PICK_STATUS_NONE
                local wantedRating, ratingIsDerived = desiredRating(record, preferences.starsFromScore)
                local burstGroupId = recordBurstGroupId(record)
                local burstDecision = burstDecisionFor(groupIndex, burstGroupId)
                local wantedPick, pickIsDerived = desiredPickStatus(
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
                    entry.ratingIsDerived = ratingIsDerived
                    plan.ratingWrites = plan.ratingWrites + 1
                end
                conflicted = conflicted or ratingConflict

                local pickValue, pickConflict = resolveField(
                    currentPick, wantedPick, PICK_STATUS_NONE, preferences.overwrite)
                if pickValue then
                    entry.pickStatus = pickValue
                    entry.pickIsDerived = pickIsDerived
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
-- The set of photos this run actually matched against the manifest --
-- C2's definition of "today's apply scope" for the rebuild safety check.
local function matchedPhotoSet(plan)
    local set = {}
    for position = 1, plan.matchedCount do
        set[plan.matchedRecords[position].photo] = true
    end
    return set
end

local function buildCollectionPlan(groupIndex, burstScopeMembers, sequenceScopeMembers, scopePhotoSet)
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
                    -- Step 9: rebuild is only ever considered when this
                    -- run's scope covers every member of the WHOLE-manifest
                    -- group -- never when a wider group has an out-of-scope
                    -- sibling this run cannot see.
                    fullyInScope = (#members == group.count),
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
                    fullyInScope = (#members == set.count),
                }
            end
        end
    end
    return { collections = collections, count = count, scopePhotoSet = scopePhotoSet or {} }
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

-- C1 fix: the two hidden facetDerivedRating/facetDerivedPick bookkeeping
-- properties must be written whenever Apply itself derives a rating/pick
-- THIS RUN -- independent of the "Write metadata fields" checkbox, which
-- only controls the VISIBLE facetAggregate/facetBand/facetCategory/
-- facetSetKind fields. The metadata provider (FacetMetadata.lua) is
-- registered in Info.lua regardless of that checkbox, so the bookkeeping
-- write must not depend on it either -- otherwise a default-configuration
-- run (writeMetadataFields=false, starsFromScore=true) never records the
-- baseline, and the reverse-sync export re-exports every score-derived star
-- and burst pick/reject as if it were a manual Lightroom edit.
--
-- `committedRanges` (applyPlan's `outcome.committedRanges`, a list of
-- {chunkStart, chunkEnd} pairs -- REQUIRED, no whole-plan default: a caller
-- that already knows every entry committed must say so explicitly, by
-- passing a single range covering the whole plan) bounds this to exactly
-- the entries whose rating/flag write actually committed. A middle chunk
-- can fail while a later one still commits before a cancel (or without one
-- at all) -- "everything up to the highest committed chunk" would then
-- wrongly cover the failed chunk's entries too, so this iterates the ranges
-- themselves rather than a single highest-index limit. A cancel midway
-- through applyPlan must not record a baseline for entries past the last
-- committed chunk, but the entries that DID commit must still get theirs,
-- or a later "Export Lightroom State" feeds their score-derived
-- stars/burst rejects back into Facet as manual edits.
local function buildDerivedValuesPlan(plan, committedRanges)
    local derivedPlan = { entries = {}, count = 0 }
    local order = {}
    local byPhoto = {}
    for _, range in ipairs(committedRanges) do
        for position = range[1], range[2] do
            local entry = plan.entries[position]
            local derived = byPhoto[entry.photo]
            if not derived then
                derived = { photo = entry.photo, path = entry.path }
                byPhoto[entry.photo] = derived
                order[#order + 1] = derived
            end
            if entry.rating and entry.ratingIsDerived then
                derived.ratingString = tostring(entry.rating)
            end
            if entry.pickStatus and entry.pickIsDerived then
                derived.pickString = tostring(entry.pickStatus)
            end
        end
    end
    for _, derived in ipairs(order) do
        if derived.ratingString ~= nil or derived.pickString ~= nil then
            derivedPlan.count = derivedPlan.count + 1
            derivedPlan.entries[derivedPlan.count] = derived
        end
    end
    return derivedPlan
end

-- The chunk/cancel-check/pcall/FAIL-log/progress/yield skeleton
-- shared by the four writers below (applyDerivedValuesPlan,
-- applyMetadataFieldsPlan, applyKeywordPlan, applyPlan). It owns none of
-- the write-access call itself (its shape -- withWriteAccessDo(name, fn,
-- opts) vs withPrivateWriteAccessDo(fn, opts) -- differs per caller, as
-- does any pre-write read like batchGetPropertyForPlugin) or the
-- per-chunk success/failure bookkeeping (each caller counts differently:
-- whole-chunk-size on failure, but its own touched/added/removed/written
-- tally on success) -- both are `writeFn`'s job. `writeFn(chunkStart,
-- chunkEnd)` must perform (and wrap) the chunk's write and return (ok, err)
-- exactly like `LrTasks.pcall` does. Returns (canceled, committedThrough,
-- committedRanges). `committedThrough` is the highest chunkEnd whose write
-- reported success, 0 if none did -- purely diagnostic now, since a middle
-- chunk can fail while a LATER one still commits, which makes "highest
-- committed chunk" an unsafe stand-in for "entries whose write actually
-- committed".
-- `committedRanges` is the precise list, in order, of {chunkStart, chunkEnd}
-- pairs for every chunk that DID commit -- with a gap left exactly where a
-- failed chunk sits -- and is what any bounded downstream plan (currently
-- buildDerivedValuesPlan) must iterate instead of a single limit.
local function runChunkedWritePass(total, progress, logger, failLabel, writeFn)
    local committedThrough = 0
    local committedRanges = {}
    for chunkStart = 1, total, WRITE_CHUNK_SIZE do
        if progress and progress:isCanceled() then
            return true, committedThrough, committedRanges
        end
        local chunkEnd = math.min(chunkStart + WRITE_CHUNK_SIZE - 1, total)
        local writeOk, writeError = writeFn(chunkStart, chunkEnd)
        if not writeOk then
            logger.write(string.format('FAIL %s batch %d-%d: %s', failLabel, chunkStart, chunkEnd, tostring(writeError)))
        else
            committedThrough = chunkEnd
            committedRanges[#committedRanges + 1] = { chunkStart, chunkEnd }
        end
        if progress then
            progress:setPortionComplete(chunkEnd, total)
        end
        LrTasks.yield()
    end
    return false, committedThrough, committedRanges
end

-- Applies the derived-value plan in its OWN withPrivateWriteAccessDo pass,
-- entirely independent of the metadata-fields plan/checkbox (C1 fix).
local function applyDerivedValuesPlan(catalog, derivedPlan, progress, logger)
    local outcome = { written = 0, failed = 0, canceled = false }
    local total = derivedPlan.count
    if total == 0 then
        return outcome
    end
    outcome.canceled = runChunkedWritePass(total, progress, logger, 'derived values', function(chunkStart, chunkEnd)
        local ok, err = LrTasks.pcall(function()
            catalog:withPrivateWriteAccessDo(function()
                for position = chunkStart, chunkEnd do
                    local entry = derivedPlan.entries[position]
                    FacetMetadata.writeDerivedValuesForPhoto(
                        _PLUGIN, entry.photo, entry.ratingString, entry.pickString)
                    outcome.written = outcome.written + 1
                end
            end, { timeout = WRITE_TIMEOUT_SECONDS })
        end)
        if not ok then
            outcome.failed = outcome.failed + (chunkEnd - chunkStart + 1)
        end
        return ok, err
    end)
    return outcome
end

-- Step 6a: builds the per-photo VISIBLE plug-in metadata field writes, from
-- every matched record. Reads back each photo's current values first
-- (read-only -- safe to call during preview, before the user confirms
-- anything) so `pendingCount` reflects real work rather than the raw
-- matched-record count (I7 fix): a re-run against unchanged data must show
-- "0 fields to write" in the Preview dialog, not the matched count.
local function buildMetadataFieldsPlan(catalog, plan)
    local fieldPlan = { entries = {}, count = 0, pendingCount = 0 }
    local total = plan.matchedCount
    for chunkStart = 1, total, READ_CHUNK_SIZE do
        local chunkEnd = math.min(chunkStart + READ_CHUNK_SIZE - 1, total)
        local chunkPhotos = {}
        for position = chunkStart, chunkEnd do
            chunkPhotos[#chunkPhotos + 1] = plan.matchedRecords[position].photo
        end
        local current = catalog and catalog:batchGetPropertyForPlugin(
            _PLUGIN, chunkPhotos, FacetMetadata.VISIBLE_FIELD_KEYS)
        for position = chunkStart, chunkEnd do
            local matched = plan.matchedRecords[position]
            local record = matched.record
            local desired = FacetMetadata.desiredFields(
                recordAggregate(record), recordCategory(record),
                recordSequenceKind(record), recordBurstGroupId(record))
            local currentForPhoto = (current and current[matched.photo]) or {}
            local pending = false
            for _, key in ipairs(FacetMetadata.VISIBLE_FIELD_KEYS) do
                local desiredValue = desired[key]
                local currentValue = FacetMetadata.normalizeCurrentFieldValue(currentForPhoto[key])
                if desiredValue == nil then
                    if currentValue ~= nil then
                        pending = true
                    end
                elseif currentValue ~= desiredValue then
                    pending = true
                end
            end
            fieldPlan.count = fieldPlan.count + 1
            fieldPlan.entries[fieldPlan.count] = {
                photo = matched.photo,
                path = matched.path,
                desiredFields = desired,
            }
            if pending then
                fieldPlan.pendingCount = fieldPlan.pendingCount + 1
            end
        end
        LrTasks.yield()
    end
    return fieldPlan
end

-- Applies the metadata-fields plan in one withPrivateWriteAccessDo pass,
-- chunked the same way rating/pick writes are (Step 6a). Reads back current
-- values first via batchGetPropertyForPlugin and skips any field whose
-- value already matches, so a re-run with unchanged data writes nothing.
local function applyMetadataFieldsPlan(catalog, fieldPlan, progress, logger)
    local outcome = { fieldsWritten = 0, photosTouched = 0, failed = 0, canceled = false }
    local total = fieldPlan.count
    if total == 0 then
        return outcome
    end
    outcome.canceled = runChunkedWritePass(total, progress, logger, 'metadata fields', function(chunkStart, chunkEnd)
        local chunkPhotos = {}
        for position = chunkStart, chunkEnd do
            chunkPhotos[#chunkPhotos + 1] = fieldPlan.entries[position].photo
        end
        local current = catalog:batchGetPropertyForPlugin(_PLUGIN, chunkPhotos, FacetMetadata.VISIBLE_FIELD_KEYS)
        local ok, err = LrTasks.pcall(function()
            catalog:withPrivateWriteAccessDo(function()
                for position = chunkStart, chunkEnd do
                    local entry = fieldPlan.entries[position]
                    local currentForPhoto = (current and current[entry.photo]) or {}
                    local written = FacetMetadata.writeFieldsForPhoto(
                        _PLUGIN, entry.photo, currentForPhoto, entry.desiredFields)
                    if written > 0 then
                        outcome.fieldsWritten = outcome.fieldsWritten + written
                        outcome.photosTouched = outcome.photosTouched + 1
                    end
                end
            end, { timeout = WRITE_TIMEOUT_SECONDS })
        end)
        if not ok then
            outcome.failed = outcome.failed + (chunkEnd - chunkStart + 1)
        end
        return ok, err
    end)
    return outcome
end

-- Step 7: decodes one manifest record's comma-separated `tags` string
-- (matching xmp_export._as_list/xmp_import._merge_tags's convention) into a
-- list of trimmed, non-empty tag names. NULL/empty means no tags.
local function tagsFromRecord(record)
    local raw = recordTags(record)
    if type(raw) ~= 'string' or raw == '' then
        return {}
    end
    local tags = {}
    local count = 0
    for piece in string.gmatch(raw, '[^,]+') do
        local trimmed = string.match(piece, '^%s*(.-)%s*$')
        if trimmed ~= '' then
            count = count + 1
            tags[count] = trimmed
        end
    end
    return tags
end

-- Step 7: find-or-create the "Facet" root keyword and its tag children,
-- across two SEPARATE withWriteAccessDo calls (parent, then children) --
-- the same-transaction footgun the SDK research doc documents for
-- createKeyword. `includeOnExport = false` is forced on every keyword,
-- parent AND child, existing or newly created, so a pre-existing
-- user-created "Facet"/tag keyword never leaks into an export.
local function ensureKeywords(catalog, tagNames)
    local root
    catalog:withWriteAccessDo(ACTION_NAME .. ': keyword root', function()
        root = catalog:createKeyword(KEYWORD_ROOT_NAME, {}, false, nil, true)
        root:setAttributes { includeOnExport = false }
    end, { timeout = WRITE_TIMEOUT_SECONDS })

    local children = {}
    catalog:withWriteAccessDo(ACTION_NAME .. ': keyword tags', function()
        for _, name in ipairs(tagNames) do
            local keyword = catalog:createKeyword(name, {}, false, root, true)
            keyword:setAttributes { includeOnExport = false }
            children[name] = keyword
        end
    end, { timeout = WRITE_TIMEOUT_SECONDS })
    return root, children
end

-- I7: read-only lookup of a photo's CURRENT Facet-child keyword names, used
-- only to compute the Preview's pending count. Never creates anything --
-- identifies the top-level "Facet" root purely by name (a keyword with no
-- parent of its own), so it works even before ensureKeywords has ever run.
local function currentFacetTagNamesForPhoto(photo)
    local names = {}
    local existing = photo:getRawMetadata(METADATA_KEYWORDS) or {}
    for _, keyword in ipairs(existing) do
        local parentOk, parent = pcall(function() return keyword:getParent() end)
        if parentOk and parent then
            local parentNameOk, parentName = pcall(function() return parent:getName() end)
            local grandparentOk, grandparent = pcall(function() return parent:getParent() end)
            if parentNameOk and parentName == KEYWORD_ROOT_NAME and grandparentOk and grandparent == nil then
                local nameOk, name = pcall(function() return keyword:getName() end)
                if nameOk then
                    names[name] = true
                end
            end
        end
    end
    return names
end

-- Builds the per-photo keyword plan: desired tag names from the manifest,
-- for every matched record. The actual add/remove decision (which of the
-- photo's current Facet-child keywords must change) is made at apply time,
-- once the keyword objects exist, since it needs each photo's current
-- keyword set. `pendingCount` (I7) is the number of entries whose current
-- Facet-child keyword set actually differs from the manifest's tags --
-- the real Preview count, not just "matched".
local function buildKeywordPlan(plan)
    local keywordPlan = { entries = {}, count = 0, pendingCount = 0, tagNames = {}, tagNameSet = {} }
    for position = 1, plan.matchedCount do
        local matched = plan.matchedRecords[position]
        local tags = tagsFromRecord(matched.record)
        keywordPlan.count = keywordPlan.count + 1
        keywordPlan.entries[keywordPlan.count] = { photo = matched.photo, path = matched.path, tags = tags }
        local wanted = {}
        for _, name in ipairs(tags) do
            wanted[name] = true
            if not keywordPlan.tagNameSet[name] then
                keywordPlan.tagNameSet[name] = true
                keywordPlan.tagNames[#keywordPlan.tagNames + 1] = name
            end
        end
        local current = currentFacetTagNamesForPhoto(matched.photo)
        local differs = false
        for name in pairs(wanted) do
            if not current[name] then
                differs = true
            end
        end
        for name in pairs(current) do
            if not wanted[name] then
                differs = true
            end
        end
        if differs then
            keywordPlan.pendingCount = keywordPlan.pendingCount + 1
        end
    end
    return keywordPlan
end

-- Applies the keyword plan: ensures the root+children keywords exist (two
-- transactions, see ensureKeywords), then in a THIRD, separate
-- withWriteAccessDo call, adds/removes each photo's Facet-child keywords so
-- they equal exactly its manifest tags. A user's own keyword outside
-- "Facet" is never touched -- only keywords this function itself created or
-- found under the Facet root are ever passed to addKeyword/removeKeyword.
local function applyKeywordPlan(catalog, keywordPlan, progress, logger)
    local outcome = { added = 0, removed = 0, photosTouched = 0, failed = 0, canceled = false }
    if keywordPlan.count == 0 then
        return outcome
    end
    local ensureOk, rootOrError, children = LrTasks.pcall(function()
        return ensureKeywords(catalog, keywordPlan.tagNames)
    end)
    if not ensureOk then
        outcome.failed = keywordPlan.count
        logger.write(string.format('FAIL keywords: %s', tostring(rootOrError)))
        return outcome
    end
    local root, keywordsByName = rootOrError, children
    local total = keywordPlan.count
    outcome.canceled = runChunkedWritePass(total, progress, logger, 'apply keywords', function(chunkStart, chunkEnd)
        local ok, err = LrTasks.pcall(function()
            catalog:withWriteAccessDo(ACTION_NAME .. ': apply keywords', function()
                for position = chunkStart, chunkEnd do
                    local entry = keywordPlan.entries[position]
                    local wanted = {}
                    for _, name in ipairs(entry.tags) do
                        wanted[name] = true
                    end
                    -- Only keywords parented directly under the Facet root
                    -- are ever considered for removal -- a user's own
                    -- keyword outside "Facet" is never touched, no matter
                    -- what it is named.
                    local currentFacetKeywords = {}
                    local existingKeywords = entry.photo:getRawMetadata(METADATA_KEYWORDS) or {}
                    for _, keyword in ipairs(existingKeywords) do
                        if keyword:getParent() == root then
                            currentFacetKeywords[keyword:getName()] = keyword
                        end
                    end
                    local touched = false
                    for _, name in ipairs(entry.tags) do
                        if not currentFacetKeywords[name] then
                            entry.photo:addKeyword(keywordsByName[name])
                            outcome.added = outcome.added + 1
                            touched = true
                        end
                    end
                    for name, keyword in pairs(currentFacetKeywords) do
                        if not wanted[name] then
                            entry.photo:removeKeyword(keyword)
                            outcome.removed = outcome.removed + 1
                            touched = true
                        end
                    end
                    if touched then
                        outcome.photosTouched = outcome.photosTouched + 1
                    end
                end
            end, { timeout = WRITE_TIMEOUT_SECONDS })
        end)
        if not ok then
            outcome.failed = outcome.failed + (chunkEnd - chunkStart + 1)
        end
        return ok, err
    end)
    return outcome
end

-- `outcome.committedThrough` is the highest entry index whose chunk actually
-- committed (diagnostic only -- see runChunkedWritePass's comment on why it
-- is not safe to bound a downstream plan by). `outcome.committedRanges` is
-- the precise list of committed {chunkStart, chunkEnd} pairs, cancel or
-- not, and is what buildDerivedValuesPlan must be bounded by instead.
local function applyPlan(catalog, plan, progress, logger)
    local outcome = { ratingsSet = 0, picksSet = 0, photosTouched = 0, failed = 0, canceled = false,
        committedThrough = 0, committedRanges = {} }
    local total = plan.entryCount
    local canceled, committedThrough, committedRanges = runChunkedWritePass(total, progress, logger, 'write', function(chunkStart, chunkEnd)
        local ok, err = LrTasks.pcall(function()
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
        if not ok then
            outcome.failed = outcome.failed + (chunkEnd - chunkStart + 1)
        end
        return ok, err
    end)
    outcome.canceled = canceled
    outcome.committedThrough = committedThrough
    outcome.committedRanges = committedRanges
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

-- Read-only counterpart of `ensureCollectionSets`, for the Preview step
-- (which must never write to the catalog): looks up the EXISTING "Facet"
-- root collection set and its kind children by name, via
-- `getChildCollectionSets()`, and creates nothing. When the root, or a
-- kind set under it, does not exist yet, that kind has no dissolved
-- candidates -- it is simply omitted from the returned table, never
-- created to make the lookup succeed. Callers must wrap this in `pcall`,
-- same as every other caller of a catalog-reading SDK call here, since
-- `getChildCollectionSets()` can raise (e.g. a busy catalog).
local function findExistingCollectionSets(catalog)
    local sets = {}
    local root = nil
    for _, set in ipairs(catalog:getChildCollectionSets()) do
        if set:getName() == COLLECTION_ROOT_NAME then
            root = set
            break
        end
    end
    if not root then
        return sets
    end
    local wanted = { [COLLECTION_SET_BURSTS] = true }
    for _, setName in pairs(SEQUENCE_KIND_COLLECTION_SET) do
        wanted[setName] = true
    end
    for _, set in ipairs(root:getChildCollectionSets()) do
        local name = set:getName()
        if wanted[name] then
            sets[name] = set
        end
    end
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

-- C2 fix: whether it is safe to rebuild `collection` at all -- true only
-- when EVERY photo it currently holds (read fresh via collection:getPhotos(),
-- never assumed) is a photo this run actually matched (`scopePhotoSet`,
-- built from the whole run's matched photos, never just this one group's
-- planned members -- a legitimately shrinking group, e.g. every member
-- still in scope but no longer forming a multi-member set, must still be
-- rebuildable down to zero and deleted). A single current member this run
-- never saw at all -- an out-of-scope sibling from an earlier, wider run,
-- or a member of some other group entirely -- means the collection's true
-- membership is unknown to this run, so it must be left completely
-- untouched rather than risk evicting it.
local function collectionRebuildIsSafe(collection, scopePhotoSet)
    local ok, current = pcall(function()
        return collection:getPhotos()
    end)
    if not ok or type(current) ~= 'table' then
        return false
    end
    for _, photo in ipairs(current) do
        if not scopePhotoSet[photo] then
            return false
        end
    end
    return true
end

-- The setName|name keys of every collection this run PLANNED to
-- rebuild -- used to tell a dissolved set (no plan entry at all, because
-- buildCollectionPlan only ever emits an entry for a group with >=2
-- in-scope members) apart from one this run is already handling.
local function plannedCollectionNames(collectionPlan)
    local names = {}
    for _, planned in ipairs(collectionPlan.collections) do
        names[planned.setName .. '|' .. planned.name] = true
    end
    return names
end

-- Read-only counterpart of applyDissolvedCollectionCleanup below -- computes
-- the SAME candidate list (a Facet collection whose group DISSOLVED this
-- run, shrinking below the 2-member threshold buildCollectionPlan requires,
-- so it never produced a plan entry and the planned-collection loop never
-- sees it) with no write of any kind: no removeAllPhotos, no delete.
-- Enumerates the EXISTING collections directly under each kind set
-- (`LrCollectionSet:getChildCollections()`, the documented SDK call for a
-- set's direct children) and keeps only the ones that are (a) named exactly
-- the shape `groupDisplayName` produces -- never a collection the user filed
-- there by hand -- (b) not already planned this run (`plannedNames`), (c)
-- not a smart collection, and (d) safe to touch (`collectionRebuildIsSafe`:
-- every CURRENT member is a photo this run actually matched). Used both to
-- show "Facet collections to delete: N" in the Preview and to decide
-- `hasNothingToApply`, and as the source list `applyDissolvedCollectionCleanup`
-- deletes from (re-checking safety again right before each delete).
local function dissolvedCollectionCandidates(sets, plannedNames, scopePhotoSet)
    local candidates = {}
    local count = 0
    for setName, parent in pairs(sets) do
        local listOk, children = pcall(function()
            return parent:getChildCollections()
        end)
        if listOk and type(children) == 'table' then
            for _, collection in ipairs(children) do
                local nameOk, name = pcall(function() return collection:getName() end)
                if nameOk and isFacetGeneratedCollectionName(name)
                    and not plannedNames[setName .. '|' .. tostring(name)] then
                    local smartOk, smartResult = pcall(function() return collection:isSmartCollection() end)
                    local isSmart = smartOk and smartResult == true
                    if not isSmart and collectionRebuildIsSafe(collection, scopePhotoSet) then
                        count = count + 1
                        candidates[count] = { setName = setName, collection = collection, name = name }
                    end
                end
            end
        end
    end
    return { candidates = candidates, count = count }
end

-- The Preview step's dissolved-candidate count: looks up the EXISTING Facet
-- collection sets read-only (`findExistingCollectionSets`, never
-- `ensureCollectionSets` -- Preview must not write to the catalog) and, when
-- rebuild is opted in, counts what `dissolvedCollectionCandidates` would
-- delete. Returns (count, checkFailed): `checkFailed` is true when the
-- lookup itself raised, which run() must show in the Preview text rather
-- than silently reporting 0 -- a lookup failure and "genuinely nothing to
-- delete" are NOT the same thing. Extracted so this preview-to-apply wiring
-- is directly callable from a test, not just reachable through the whole
-- of run().
local function previewDissolvedCandidateCount(catalog, collectionPlan, plan, preferences, logger)
    if not preferences.rebuildCollections then
        return 0, false
    end
    local lookupOk, setsOrError = pcall(function()
        return findExistingCollectionSets(catalog)
    end)
    if not lookupOk then
        logger.write(string.format('FAIL preview dissolved-collection check: %s', tostring(setsOrError)))
        return 0, true
    end
    return dissolvedCollectionCandidates(
        setsOrError, plannedCollectionNames(collectionPlan), matchedPhotoSet(plan)).count, false
end

-- Deletes exactly the candidates `dissolvedCollectionCandidates` identifies,
-- re-computed fresh here (apply time) rather than reusing a stale preview-time
-- list, and re-checks `collectionRebuildIsSafe` again immediately before each
-- delete -- membership read at preview time is not assumed to still hold.
local function applyDissolvedCollectionCleanup(catalog, sets, plannedNames, scopePhotoSet, progress, logger)
    local outcome = { deleted = 0, failed = 0, canceled = false }
    local candidatePlan = dissolvedCollectionCandidates(sets, plannedNames, scopePhotoSet)
    for _, candidate in ipairs(candidatePlan.candidates) do
        if progress and progress:isCanceled() then
            outcome.canceled = true
            return outcome
        end
        local setName, collection, name = candidate.setName, candidate.collection, candidate.name
        if collectionRebuildIsSafe(collection, scopePhotoSet) then
            local removeOk, removeError = true, nil
            local photosOk, current = pcall(function() return collection:getPhotos() end)
            if photosOk and type(current) == 'table' and #current > 0 then
                removeOk, removeError = LrTasks.pcall(function()
                    catalog:withWriteAccessDo(ACTION_NAME .. ': rebuild clear (dissolved)', function()
                        collection:removeAllPhotos()
                    end, { timeout = WRITE_TIMEOUT_SECONDS })
                end)
                if not removeOk then
                    outcome.failed = outcome.failed + 1
                    logger.write(string.format('FAIL rebuild clear (dissolved) %s/%s: %s',
                        setName, tostring(name), tostring(removeError)))
                end
            end
            if removeOk then
                local deleteOk, deleteError = LrTasks.pcall(function()
                    catalog:withWriteAccessDo(ACTION_NAME .. ': rebuild delete (dissolved)', function()
                        collection:delete()
                    end, { timeout = WRITE_TIMEOUT_SECONDS })
                end)
                if deleteOk then
                    outcome.deleted = outcome.deleted + 1
                    logger.write(string.format('REBUILD deleted (dissolved) %s/%s', setName, tostring(name)))
                else
                    outcome.failed = outcome.failed + 1
                    logger.write(string.format('FAIL rebuild delete (dissolved) %s/%s: %s',
                        setName, tostring(name), tostring(deleteError)))
                end
            end
        end
        if progress then
            progress:setPortionComplete(1, 1)
        end
    end
    return outcome
end

-- Step 9: rebuild (clear-and-refill) each planned collection that is
-- `fullyInScope` AND whose CURRENT membership is safe to touch
-- (`collectionRebuildIsSafe`, C2) -- never a partly-out-of-scope one, which
-- is left completely untouched and counted "skipped" instead. Two SEPARATE
-- withWriteAccessDo calls per collection (removeAllPhotos, then addPhotos),
-- per the research doc's same-transaction caution; a smart collection is
-- detected via `collection:isSmartCollection()` and skipped before either
-- call. Any collection this pass actually cleared-and-refilled to zero
-- resulting members is deleted in a third call. A `removeAllPhotos` that
-- commits followed by a failing `addPhotos` is a hard failure, reported,
-- never auto-deleted (membership is unknown, not zero).
--
-- After the planned collections above, also runs
-- `applyDissolvedCollectionCleanup` over the whole set catalogue -- so a
-- collection whose group dissolved below the 2-member threshold (and so
-- never got a plan entry) is still reached and, when safe, deleted. This
-- runs even when `collectionPlan.count == 0` (every group dissolved this
-- run), which is why the old up-front `if collectionPlan.count == 0 then
-- return end` guard is gone.
local function applyRebuildCollectionPlan(catalog, collectionPlan, progress, logger)
    local outcome = { rebuilt = 0, deleted = 0, skipped = 0, failed = 0, canceled = false }
    local setsOk, setsOrError = LrTasks.pcall(function()
        return ensureCollectionSets(catalog)
    end)
    if not setsOk then
        -- `collectionPlan.count` can legitimately be 0 (every group
        -- dissolved this run, so the rebuild's only job is the dissolved
        -- sweep) -- report at least one failure so a set-creation failure
        -- is never silently a "0 failed" summary.
        outcome.failed = collectionPlan.count > 0 and collectionPlan.count or 1
        logger.write(string.format('FAIL rebuild collection sets: %s', tostring(setsOrError)))
        return outcome
    end
    local sets = setsOrError
    for _, planned in ipairs(collectionPlan.collections) do
        if progress and progress:isCanceled() then
            outcome.canceled = true
            return outcome
        end
        if not planned.fullyInScope then
            outcome.skipped = outcome.skipped + 1
            logger.write(string.format('REBUILD skipped (partly outside selection) %s/%s',
                planned.setName, planned.name))
        else
            local parent = sets[planned.setName]
            local collectionOk, collection = LrTasks.pcall(function()
                local resolved
                catalog:withWriteAccessDo(ACTION_NAME .. ': rebuild find', function()
                    resolved = catalog:createCollection(planned.name, parent, true)
                end, { timeout = WRITE_TIMEOUT_SECONDS })
                return resolved
            end)
            -- M4: the real SDK exposes `collection:isSmartCollection()`, not
            -- a `.smart` field -- pcall it so a stub/real collection that
            -- lacks the method (or that method itself failing) is treated
            -- as "not smart" rather than erroring the whole rebuild pass.
            local isSmart = false
            if collectionOk and collection then
                local smartOk, smartResult = pcall(function()
                    return collection:isSmartCollection()
                end)
                isSmart = smartOk and smartResult == true
            end
            if not collectionOk or isSmart then
                outcome.skipped = outcome.skipped + 1
                logger.write(string.format('REBUILD skipped (smart or unresolved) %s/%s',
                    planned.setName, planned.name))
            elseif not collectionRebuildIsSafe(collection, collectionPlan.scopePhotoSet or {}) then
                outcome.skipped = outcome.skipped + 1
                logger.write(string.format('REBUILD skipped (current members outside this run) %s/%s',
                    planned.setName, planned.name))
            else
                local emptied = false
                local removeOk, removeError = LrTasks.pcall(function()
                    catalog:withWriteAccessDo(ACTION_NAME .. ': rebuild clear', function()
                        collection:removeAllPhotos()
                    end, { timeout = WRITE_TIMEOUT_SECONDS })
                end)
                if not removeOk then
                    outcome.failed = outcome.failed + 1
                    logger.write(string.format('FAIL rebuild clear %s/%s: %s',
                        planned.setName, planned.name, tostring(removeError)))
                else
                    emptied = true
                    local addOk, addError = LrTasks.pcall(function()
                        catalog:withWriteAccessDo(ACTION_NAME .. ': rebuild fill', function()
                            collection:addPhotos(planned.members)
                        end, { timeout = WRITE_TIMEOUT_SECONDS })
                    end)
                    if not addOk then
                        outcome.failed = outcome.failed + 1
                        logger.write(string.format('FAIL rebuild fill %s/%s (left emptied): %s',
                            planned.setName, planned.name, tostring(addError)))
                    else
                        outcome.rebuilt = outcome.rebuilt + 1
                        if #planned.members == 0 then
                            local deleteOk, deleteError = LrTasks.pcall(function()
                                catalog:withWriteAccessDo(ACTION_NAME .. ': rebuild delete', function()
                                    collection:delete()
                                end, { timeout = WRITE_TIMEOUT_SECONDS })
                            end)
                            if deleteOk then
                                outcome.deleted = outcome.deleted + 1
                            else
                                outcome.failed = outcome.failed + 1
                                logger.write(string.format('FAIL rebuild delete %s/%s: %s',
                                    planned.setName, planned.name, tostring(deleteError)))
                            end
                        end
                    end
                end
            end
        end
        if progress then
            progress:setPortionComplete(1, 1)
        end
    end

    local cleanupOutcome = applyDissolvedCollectionCleanup(
        catalog, sets, plannedCollectionNames(collectionPlan), collectionPlan.scopePhotoSet or {}, progress, logger)
    outcome.deleted = outcome.deleted + cleanupOutcome.deleted
    outcome.failed = outcome.failed + cleanupOutcome.failed
    if cleanupOutcome.canceled then
        outcome.canceled = true
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
    properties.rebuildCollections = preferences.rebuildCollections and preferences.createCollections
    properties.writeMetadataFields = preferences.writeMetadataFields
    properties.createKeywords = preferences.createKeywords

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
        viewFactory:row {
            viewFactory:static_text { title = '    ' },
            viewFactory:checkbox {
                title = 'Rebuild (clear and refill) Facet collections fully covered by this run',
                value = bind 'rebuildCollections',
                enabled = bind 'createCollections',
            },
        },
        viewFactory:checkbox {
            title = 'Write Facet scores/category/set-kind as Lightroom plug-in metadata fields',
            value = bind 'writeMetadataFields',
        },
        viewFactory:checkbox {
            title = 'Create "Facet" keywords from Facet tags (never included on export)',
            value = bind 'createKeywords',
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
    -- The nested checkbox's own binding is greyed out (never editable) when
    -- 'Create Facet collections' is off, but LrView does not clear ITS VALUE
    -- when disabled -- a user who ticks both, then later unticks only
    -- 'Create Facet collections', would otherwise keep a stale
    -- rebuildCollections=true that a later run's `preferences.rebuildCollections`
    -- read alone could not tell apart from "still wanted". AND it with the
    -- parent checkbox here, at the single point preferences are persisted.
    preferences.rebuildCollections = properties.rebuildCollections and properties.createCollections and true or false
    preferences.writeMetadataFields = properties.writeMetadataFields and true or false
    preferences.createKeywords = properties.createKeywords and true or false
    return preferences
end

-- Step 6c: when nothing matched, look up an unmatched catalog photo's
-- filename against the manifest's secondary filename index and, if found,
-- compute a catalogPrefix/manifestPrefix suggestion. Returns nil, nil when
-- there is no filename match, or when the computed suffix leaves both
-- prefixes empty (already matching -- nothing to suggest).
local function computeNoMatchSuggestion(plan, index)
    if not plan.sampleCatalogPath then
        return nil, nil
    end
    local filenameKey = filenameKeyFromPath(normalizePath(plan.sampleCatalogPath) or plan.sampleCatalogPath)
    local manifestSample = index.byFilename[filenameKey]
    if not manifestSample then
        return nil, nil
    end
    local catalogPrefix, manifestPrefix = FacetCommon.suggestPrefixPair(plan.sampleCatalogPath, manifestSample)
    if catalogPrefix == nil or (catalogPrefix == '' and manifestPrefix == '') then
        return nil, nil
    end
    return catalogPrefix, manifestPrefix
end

-- Step 6c: the "Use this" button's action -- fills the two persisted prefix
-- preferences and nothing else. Never re-runs the plan or writes to the
-- catalog; the user must open the plug-in again and press Apply/Preview.
local function applySuggestedPrefixes(preferences, catalogPrefix, manifestPrefix)
    preferences.catalogPrefix = catalogPrefix
    preferences.manifestPrefix = manifestPrefix
end

local function pathHint(plan, index)
    return string.format(
        '\n\nPath seen in Lightroom:\n    %s\nLooked up as:\n    %s\nPath seen in the manifest:\n    %s',
        tostring(plan.sampleCatalogPath), tostring(plan.sampleMappedPath), tostring(index.sample))
end

-- I7: counts how many planned collections are fullyInScope (rebuild
-- candidates) vs. not (always skipped) -- shown in the Preview so
-- "skipped (partly outside selection)" is knowable before Apply, not just
-- discovered afterwards in the summary.
local function countRebuildCandidates(collectionPlan)
    local fullyInScope = 0
    local partial = 0
    if collectionPlan and collectionPlan.collections then
        for _, planned in ipairs(collectionPlan.collections) do
            if planned.fullyInScope then
                fullyInScope = fullyInScope + 1
            else
                partial = partial + 1
            end
        end
    end
    return fullyInScope, partial
end

local function previewMessage(plan, manifest, index, preferences, collectionPlan, fieldPlan, keywordPlan, dissolvedCount, dissolvedCheckFailed)
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
        if preferences.rebuildCollections then
            local fullyInScope, partial = countRebuildCandidates(collectionPlan)
            lines[#lines + 1] = string.format(
                'Collections to rebuild: %d (skipped, partly outside selection: %d)', fullyInScope, partial)
            if dissolvedCheckFailed then
                lines[#lines + 1] = 'Could not check for stale Facet collections to delete (see log).'
            elseif dissolvedCount and dissolvedCount > 0 then
                lines[#lines + 1] = string.format('Facet collections to delete: %d', dissolvedCount)
            end
        end
    end
    if fieldPlan then
        lines[#lines + 1] = string.format('Metadata fields to write: %d', fieldPlan.pendingCount or 0)
    end
    if keywordPlan then
        lines[#lines + 1] = string.format('Keyword changes to make: %d', keywordPlan.pendingCount or 0)
    end
    lines[#lines + 1] = ''
    lines[#lines + 1] = string.format(
        'Manifest: %d photos, exported %s', index.count, tostring(manifest[FIELD_GENERATED_AT]))
    if preferences.overwrite then
        lines[#lines + 1] = 'Overwrite is ON: existing Lightroom ratings and flags will be replaced.'
    end
    local pending = manifestPendingCorrections(manifest)
    if pending > 0 then
        lines[#lines + 1] = ''
        lines[#lines + 1] = PENDING_CORRECTIONS_WARNING(pending)
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
-- Step 9 extension: also considers the metadata-field plan (Step 6a) and
-- keyword plan (Step 7) counts -- a run with ONLY field-write or
-- keyword-write work queued (no rating/pick/collection changes) must still
-- proceed. `fieldPlan`/`keywordPlan` are optional (nil when their opt-in
-- checkbox is off) and treated as zero work when absent.
-- `dissolvedCount` is the number of stale Facet collections the
-- dissolved-collection sweep would delete -- a run where every planned
-- rating/flag/collection/field/keyword change is empty but a group
-- dissolved below the collection threshold still has real work to do and
-- must not report "Nothing to change". `dissolvedCheckFailed` (true when
-- the read-only lookup behind `dissolvedCount` raised) must ALSO force
-- this false: a failed check means the real count is unknown, not zero,
-- so it must never be reported as nothing to do.
local function hasNothingToApply(plan, collectionPlan, fieldPlan, keywordPlan, dissolvedCount, dissolvedCheckFailed)
    if dissolvedCheckFailed then
        return false
    end
    local fieldCount = (fieldPlan and (fieldPlan.pendingCount or fieldPlan.count)) or 0
    local keywordCount = (keywordPlan and (keywordPlan.pendingCount or keywordPlan.count)) or 0
    return plan.entryCount == 0 and collectionPlan.count == 0
        and fieldCount == 0 and keywordCount == 0 and (dissolvedCount or 0) == 0
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
-- I7 fix: threads the field-write, keyword-sync and rebuild outcomes (each
-- optional -- nil when their checkbox was off or the run never reached that
-- step) into the summary, including their failure/skip/delete counts.
-- `previewMessage`'s "Nothing to change" branch never reaches this
-- function, so this is the only place these outcomes are ever surfaced.
local function summaryMessage(plan, outcome, collectionOutcome, collectionsSkippedByCancel,
    fieldOutcome, keywordOutcome, rebuildOutcome)
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
    if rebuildOutcome then
        lines[#lines + 1] = string.format(
            'Collections rebuilt: %d (deleted when left empty: %d, skipped: %d)',
            rebuildOutcome.rebuilt, rebuildOutcome.deleted, rebuildOutcome.skipped)
        if rebuildOutcome.failed > 0 then
            lines[#lines + 1] = string.format('Rebuild failures: %d', rebuildOutcome.failed)
        end
    end
    if fieldOutcome then
        lines[#lines + 1] = string.format('Metadata fields written: %d (photos touched: %d)',
            fieldOutcome.fieldsWritten, fieldOutcome.photosTouched)
        if fieldOutcome.failed > 0 then
            lines[#lines + 1] = string.format('Metadata field failures: %d', fieldOutcome.failed)
        end
    end
    if keywordOutcome then
        lines[#lines + 1] = string.format('Keywords added/removed: %d/%d (photos touched: %d)',
            keywordOutcome.added, keywordOutcome.removed, keywordOutcome.photosTouched)
        if keywordOutcome.failed > 0 then
            lines[#lines + 1] = string.format('Keyword failures: %d', keywordOutcome.failed)
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

-- Everything run() does AFTER the user confirms the Preview dialog:
-- ratings/flags, derived-value bookkeeping (C1), collections/rebuild,
-- metadata fields and keywords. Extracted into its own function so a test
-- can drive the WHOLE post-confirm sequence against the real stub catalog
-- without stubbing LrDialogs/LrApplication -- the coordinator's finding
-- was that every one of these passes could be gutted inside run() with no
-- test going red, since nothing exercised run() past the preview
-- confirmation. `options` holds the four opt-in fields:
-- collectionPlan/fieldPlan/keywordPlan (each nil when its checkbox was
-- off) and rebuildCollections (boolean). Returns a table with every
-- outcome, exactly the values run() itself now threads into the summary.
local function executeApply(catalog, plan, options, context, logger)
    local collectionPlan = options.collectionPlan or { collections = {}, count = 0, scopePhotoSet = {} }
    local fieldPlan = options.fieldPlan
    local keywordPlan = options.keywordPlan

    local writeProgress = makeProgressScope(context, 'Facet: writing ratings and flags')
    local outcome = applyPlan(catalog, plan, writeProgress, logger)
    writeProgress:done()

    -- C1 fix: record the derived-value bookkeeping whenever this run
    -- derived a rating/pick, regardless of the "Write metadata fields"
    -- checkbox -- its own pass, right after the rating/flag write.
    -- Bounded to `outcome.committedRanges` (D-4: the precise set of chunks
    -- that committed, not just "up to the highest one") rather than gated on
    -- `not outcome.canceled` -- a cancel partway through applyPlan must
    -- still record the baseline for the chunks that DID commit, not skip
    -- the whole pass and leave them without one, and a chunk that failed
    -- without a cancel must never get one either.
    local derivedPlan = buildDerivedValuesPlan(plan, outcome.committedRanges)
    if derivedPlan.count > 0 then
        if outcome.canceled then
            -- No progress scope, so no cancel check: the ratings these chunks
            -- cover are already written, and a scope created after the cancel
            -- may still report it -- abandoning the baseline here would send
            -- the derived stars back to Facet as the user's own ratings.
            applyDerivedValuesPlan(catalog, derivedPlan, nil, logger)
        else
            local derivedProgress = makeProgressScope(context, 'Facet: recording derived values')
            applyDerivedValuesPlan(catalog, derivedPlan, derivedProgress, logger)
            derivedProgress:done()
        end
    end

    -- A canceled write leaves the run's photos only partially rated/flagged;
    -- skip collection/field/keyword work rather than build them from that
    -- inconsistent state, and say so in the summary (finding M2).
    local collectionOutcome = nil
    local rebuildOutcome = nil
    local collectionsSkippedByCancel = collectionPlan.count > 0 and outcome.canceled
    if shouldApplyCollectionPlan(outcome, collectionPlan) then
        local collectionProgress = makeProgressScope(context, 'Facet: creating collections')
        collectionOutcome = applyCollectionPlan(catalog, collectionPlan, collectionProgress, logger)
        collectionProgress:done()
    end
    -- Rebuild runs whenever it is opted in and the write was not
    -- canceled, independent of `collectionPlan.count` -- a run where every
    -- Facet group dissolved below the 2-member threshold plans NO
    -- collections at all, but still needs applyRebuildCollectionPlan's
    -- dissolved-collection sweep to reach and delete the now-stale ones.
    -- `options.collectionPlan == nil` means the collections feature itself
    -- is off for this call -- distinct from a present-but-empty plan -- and
    -- the rebuild (which would otherwise still run and sweep every unplanned
    -- collection under the kind sets) must never run in that case, even if
    -- `rebuildCollections` was somehow left true.
    if options.rebuildCollections and options.collectionPlan ~= nil and not outcome.canceled then
        local rebuildProgress = makeProgressScope(context, 'Facet: rebuilding collections')
        rebuildOutcome = applyRebuildCollectionPlan(catalog, collectionPlan, rebuildProgress, logger)
        rebuildProgress:done()
    end

    local fieldOutcome = nil
    if fieldPlan and fieldPlan.count > 0 and not outcome.canceled then
        local fieldProgress = makeProgressScope(context, 'Facet: writing metadata fields')
        fieldOutcome = applyMetadataFieldsPlan(catalog, fieldPlan, fieldProgress, logger)
        fieldProgress:done()
    end

    local keywordOutcome = nil
    if keywordPlan and keywordPlan.count > 0 and not outcome.canceled then
        local keywordProgress = makeProgressScope(context, 'Facet: syncing keywords')
        keywordOutcome = applyKeywordPlan(catalog, keywordPlan, keywordProgress, logger)
        keywordProgress:done()
    end

    return {
        outcome = outcome,
        collectionOutcome = collectionOutcome,
        rebuildOutcome = rebuildOutcome,
        fieldOutcome = fieldOutcome,
        keywordOutcome = keywordOutcome,
        collectionsSkippedByCancel = collectionsSkippedByCancel,
    }
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
        local suggestedCatalogPrefix, suggestedManifestPrefix = computeNoMatchSuggestion(plan, index)
        local message = string.format(
            'None of the %d photos in scope were found in the manifest.\n\n'
            .. 'The manifest stores the paths of the machine that scanned the photos. '
            .. 'Set the two path prefixes in the plug-in dialog so they match.%s',
            plan.scoped, pathHint(plan, index))
        if suggestedCatalogPrefix then
            message = message .. string.format(
                '\n\nSuggested path prefixes:\n    Lightroom: %s\n    Facet: %s',
                suggestedCatalogPrefix, suggestedManifestPrefix)
            local useThis = LrDialogs.confirm(DIALOG_TITLE, message, 'Use this', 'Close')
            if useThis == 'ok' then
                applySuggestedPrefixes(preferences, suggestedCatalogPrefix, suggestedManifestPrefix)
            end
        else
            LrDialogs.message(DIALOG_TITLE, message, 'critical')
        end
        return
    end

    local collectionPlan = { collections = {}, count = 0, scopePhotoSet = {} }
    if preferences.createCollections then
        collectionPlan = buildCollectionPlan(
            groupIndex, plan.burstScopeMembers, plan.sequenceScopeMembers, matchedPhotoSet(plan))
    end
    local fieldPlan = nil
    if preferences.writeMetadataFields then
        fieldPlan = buildMetadataFieldsPlan(catalog, plan)
    end
    local keywordPlan = nil
    if preferences.createKeywords then
        keywordPlan = buildKeywordPlan(plan)
    end

    -- Read-only (see `findExistingCollectionSets`), so a run where every
    -- planned change is otherwise empty but a Facet group dissolved below
    -- the collection threshold still shows -- and still reaches -- that
    -- sweep, instead of stopping at "Nothing to change" first. Wrapped in
    -- `pcall` like every other catalog-reading call here; a failure is
    -- surfaced (never treated as "0 candidates") via `dissolvedCheckFailed`.
    local dissolvedCount, dissolvedCheckFailed = previewDissolvedCandidateCount(
        catalog, collectionPlan, plan, preferences, logger)

    if hasNothingToApply(plan, collectionPlan, fieldPlan, keywordPlan, dissolvedCount, dissolvedCheckFailed) then
        logger.close()
        LrDialogs.message(DIALOG_TITLE,
            string.format('Nothing to change.\n\n%s',
                previewMessage(plan, manifest, index, preferences, collectionPlan, fieldPlan, keywordPlan,
                    dissolvedCount, dissolvedCheckFailed)))
        return
    end

    local confirmed = LrDialogs.confirm(DIALOG_TITLE .. ' - preview',
        previewMessage(plan, manifest, index, preferences, collectionPlan, fieldPlan, keywordPlan,
            dissolvedCount, dissolvedCheckFailed),
        'Apply', 'Cancel')
    if confirmed ~= 'ok' then
        logger.write('CANCELED at the preview dialog')
        logger.close()
        return
    end

    local result = executeApply(catalog, plan, {
        collectionPlan = preferences.createCollections and collectionPlan or nil,
        fieldPlan = fieldPlan,
        keywordPlan = keywordPlan,
        rebuildCollections = preferences.rebuildCollections,
    }, context, logger)

    logger.write(string.format('DONE photos=%d ratings=%d flags=%d failed=%d canceled=%s',
        result.outcome.photosTouched, result.outcome.ratingsSet, result.outcome.picksSet,
        result.outcome.failed, tostring(result.outcome.canceled)))
    logger.close()

    LrDialogs.message(DIALOG_TITLE .. ' - done',
        summaryMessage(plan, result.outcome, result.collectionOutcome, result.collectionsSkippedByCancel,
            result.fieldOutcome, result.keywordOutcome, result.rebuildOutcome))
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
    FACET_APPLY_TEST_HOOKS.findExistingCollectionSets = findExistingCollectionSets
    FACET_APPLY_TEST_HOOKS.previewDissolvedCandidateCount = previewDissolvedCandidateCount
    FACET_APPLY_TEST_HOOKS.applyCollectionPlan = applyCollectionPlan
    FACET_APPLY_TEST_HOOKS.hasNothingToApply = hasNothingToApply
    FACET_APPLY_TEST_HOOKS.buildMetadataFieldsPlan = buildMetadataFieldsPlan
    FACET_APPLY_TEST_HOOKS.applyMetadataFieldsPlan = applyMetadataFieldsPlan
    FACET_APPLY_TEST_HOOKS.tagsFromRecord = tagsFromRecord
    FACET_APPLY_TEST_HOOKS.ensureKeywords = ensureKeywords
    FACET_APPLY_TEST_HOOKS.buildKeywordPlan = buildKeywordPlan
    FACET_APPLY_TEST_HOOKS.applyKeywordPlan = applyKeywordPlan
    FACET_APPLY_TEST_HOOKS.applyRebuildCollectionPlan = applyRebuildCollectionPlan
    FACET_APPLY_TEST_HOOKS.plannedCollectionNames = plannedCollectionNames
    FACET_APPLY_TEST_HOOKS.applyDissolvedCollectionCleanup = applyDissolvedCollectionCleanup
    FACET_APPLY_TEST_HOOKS.computeNoMatchSuggestion = computeNoMatchSuggestion
    FACET_APPLY_TEST_HOOKS.applySuggestedPrefixes = applySuggestedPrefixes
    FACET_APPLY_TEST_HOOKS.manifestPendingCorrections = manifestPendingCorrections
    FACET_APPLY_TEST_HOOKS.recordCategory = recordCategory
    FACET_APPLY_TEST_HOOKS.recordTags = recordTags
    FACET_APPLY_TEST_HOOKS.recordAggregate = recordAggregate
    FACET_APPLY_TEST_HOOKS.shouldApplyCollectionPlan = shouldApplyCollectionPlan
    FACET_APPLY_TEST_HOOKS.buildDerivedValuesPlan = buildDerivedValuesPlan
    FACET_APPLY_TEST_HOOKS.applyDerivedValuesPlan = applyDerivedValuesPlan
    FACET_APPLY_TEST_HOOKS.matchedPhotoSet = matchedPhotoSet
    FACET_APPLY_TEST_HOOKS.collectionRebuildIsSafe = collectionRebuildIsSafe
    FACET_APPLY_TEST_HOOKS.currentFacetTagNamesForPhoto = currentFacetTagNamesForPhoto
    FACET_APPLY_TEST_HOOKS.countRebuildCandidates = countRebuildCandidates
    FACET_APPLY_TEST_HOOKS.executeApply = executeApply
    FACET_APPLY_TEST_HOOKS.isFacetGeneratedCollectionName = isFacetGeneratedCollectionName
    FACET_APPLY_TEST_HOOKS.dissolvedCollectionCandidates = dissolvedCollectionCandidates
    return
end

LrFunctionContext.postAsyncTaskWithContext('facetApply', function(context)
    LrDialogs.attachErrorDialogToFunctionContext(context, ACTION_NAME)
    run(context)
end)
