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

local MANIFEST_VERSION = 1
local FIELD_VERSION = 'version'
local FIELD_GENERATED_AT = 'generated_at'
local FIELD_PHOTOS = 'photos'
local FIELD_PATH = 'path'
local FIELD_STAR_RATING = 'star_rating'
local FIELD_IS_FAVORITE = 'is_favorite'
local FIELD_IS_REJECTED = 'is_rejected'

local METADATA_PATH = 'path'
local METADATA_RATING = 'rating'
local METADATA_PICK_STATUS = 'pickStatus'
local METADATA_KEYS = { METADATA_PATH, METADATA_RATING, METADATA_PICK_STATUS }

local PICK_STATUS_PICKED = 1
local PICK_STATUS_NONE = 0
local PICK_STATUS_REJECTED = -1
local MAXIMUM_RATING = 5

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

local function buildIndex(manifest)
    local index = { exact = {}, lowercase = {}, count = 0, sample = nil }
    for _, record in ipairs(manifest[FIELD_PHOTOS]) do
        if type(record) == 'table' then
            local path = normalizePath(record[FIELD_PATH])
            if path then
                index.exact[path] = record
                index.lowercase[string.lower(path)] = record
                index.count = index.count + 1
                if not index.sample then
                    index.sample = path
                end
            end
        end
    end
    return index
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
    return index.lowercase[string.lower(path)]
end

local function desiredRating(record)
    local stars = record[FIELD_STAR_RATING]
    if type(stars) ~= 'number' or stars <= 0 then
        return nil
    end
    if stars > MAXIMUM_RATING then
        return MAXIMUM_RATING
    end
    return math.floor(stars)
end

local function desiredPickStatus(record)
    if record[FIELD_IS_REJECTED] == true then
        return PICK_STATUS_REJECTED
    end
    if record[FIELD_IS_FAVORITE] == true then
        return PICK_STATUS_PICKED
    end
    return nil
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

local function buildPlan(catalog, photos, index, preferences, progress, logger)
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
                local wantedRating = desiredRating(record)
                local wantedPick = desiredPickStatus(record)
                local entry = { photo = photo }
                local conflicted = false
                if wantedRating then
                    if currentRating == 0 or preferences.overwrite then
                        if wantedRating ~= currentRating then
                            entry.rating = wantedRating
                            plan.ratingWrites = plan.ratingWrites + 1
                        end
                    elseif currentRating ~= wantedRating then
                        conflicted = true
                    end
                end
                if wantedPick then
                    if currentPick == PICK_STATUS_NONE or preferences.overwrite then
                        if wantedPick ~= currentPick then
                            entry.pickStatus = wantedPick
                            plan.pickWrites = plan.pickWrites + 1
                        end
                    elseif currentPick ~= wantedPick then
                        conflicted = true
                    end
                end
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
            end
        end
        progress:setPortionComplete(chunkEnd, total)
        LrTasks.yield()
    end
    return plan
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
                        local ok, message = pcall(function()
                            entry.photo:setRawMetadata(METADATA_RATING, entry.rating)
                        end)
                        if ok then
                            outcome.ratingsSet = outcome.ratingsSet + 1
                            touched = true
                        else
                            outcome.failed = outcome.failed + 1
                            logger.write(string.format('FAIL rating %s: %s', tostring(entry.path), tostring(message)))
                        end
                    end
                    if entry.pickStatus then
                        local ok, message = pcall(function()
                            entry.photo:setRawMetadata(METADATA_PICK_STATUS, entry.pickStatus)
                        end)
                        if ok then
                            outcome.picksSet = outcome.picksSet + 1
                            touched = true
                        else
                            outcome.failed = outcome.failed + 1
                            logger.write(string.format('FAIL flag %s: %s', tostring(entry.path), tostring(message)))
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
    return preferences
end

local function pathHint(plan, index)
    return string.format(
        '\n\nPath seen in Lightroom:\n    %s\nLooked up as:\n    %s\nPath seen in the manifest:\n    %s',
        tostring(plan.sampleCatalogPath), tostring(plan.sampleMappedPath), tostring(index.sample))
end

local function previewMessage(plan, manifest, index, preferences)
    local lines = {
        string.format('Photos in scope: %d', plan.scoped),
        '',
        string.format('MATCHED in the manifest:   %d', plan.matched),
        string.format('NOT FOUND in the manifest: %d', plan.unmatched),
        '',
        string.format('Star ratings to set: %d', plan.ratingWrites),
        string.format('Pick/reject flags to set: %d', plan.pickWrites),
        string.format('Already up to date: %d', plan.unchanged),
        string.format('Kept as they are (already rated or flagged by hand): %d', plan.conflicts),
        '',
        string.format('Manifest: %d photos, exported %s',
            index.count, tostring(manifest[FIELD_GENERATED_AT])),
    }
    if preferences.overwrite then
        lines[#lines + 1] = 'Overwrite is ON: existing Lightroom ratings and flags will be replaced.'
    end
    local message = table.concat(lines, '\n')
    if plan.unmatched > 0 then
        message = message .. pathHint(plan, index)
    end
    return message
end

local function summaryMessage(plan, outcome)
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
    if outcome.canceled then
        lines[#lines + 1] = ''
        lines[#lines + 1] = 'Canceled - the photos already written keep their new values.'
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

    local progress = makeProgressScope(context, 'Facet: reading Lightroom metadata')
    local plan = buildPlan(catalog, photos, index, preferences, progress, logger)
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

    if plan.entryCount == 0 then
        logger.close()
        LrDialogs.message(DIALOG_TITLE,
            string.format('Nothing to change.\n\n%s', previewMessage(plan, manifest, index, preferences)))
        return
    end

    local confirmed = LrDialogs.confirm(DIALOG_TITLE .. ' - preview',
        previewMessage(plan, manifest, index, preferences), 'Apply', 'Cancel')
    if confirmed ~= 'ok' then
        logger.write('CANCELED at the preview dialog')
        logger.close()
        return
    end

    local writeProgress = makeProgressScope(context, 'Facet: writing ratings and flags')
    local outcome = applyPlan(catalog, plan, writeProgress, logger)
    writeProgress:done()

    logger.write(string.format('DONE photos=%d ratings=%d flags=%d failed=%d canceled=%s',
        outcome.photosTouched, outcome.ratingsSet, outcome.picksSet, outcome.failed,
        tostring(outcome.canceled)))
    logger.close()

    LrDialogs.message(DIALOG_TITLE .. ' - done', summaryMessage(plan, outcome))
end

LrFunctionContext.postAsyncTaskWithContext('facetApply', function(context)
    LrDialogs.attachErrorDialogToFunctionContext(context, ACTION_NAME)
    run(context)
end)
