-- LrMetadataProvider for Facet's plug-in metadata fields (item 1), plus two
-- HIDDEN derived-value bookkeeping properties used only by
-- FacetExportState.lua's reverse-sync comparison (Step 5b/6a/6b).
--
-- Precedence rule for facetSetKind: a frame that is both a burst member and
-- a bracket/panorama/hdr_panorama member resolves to the sequence_kind, never
-- 'burst' -- bracket/panorama detection runs AFTER and supersedes burst
-- grouping in detect_all_sequences, so sequence_kind (when present) always
-- wins over a bare burst_group_id.
--
-- UNVERIFIED (see Open questions in the spec): whether a title-less
-- metadataFieldsForPhotos entry is actually hidden from the Library Filter
-- and Metadata panel is not confirmed by the SDK research. This file uses
-- `searchable = false, browsable = false` on both hidden fields as the safer,
-- confirmed-by-research fallback (keeps them out of the Library Filter and
-- smart-collection criteria) rather than relying on an unconfirmed
-- title-omission behaviour. Record the real behaviour in docs/INTEROP.md
-- once verified against a live catalog.

local FacetMetadata = {}

FacetMetadata.FIELD_AGGREGATE = 'facetAggregate'
FacetMetadata.FIELD_BAND = 'facetBand'
FacetMetadata.FIELD_CATEGORY = 'facetCategory'
FacetMetadata.FIELD_SET_KIND = 'facetSetKind'
FacetMetadata.FIELD_DERIVED_RATING = 'facetDerivedRating'
FacetMetadata.FIELD_DERIVED_PICK = 'facetDerivedPick'

FacetMetadata.VISIBLE_FIELD_KEYS = {
    FacetMetadata.FIELD_AGGREGATE,
    FacetMetadata.FIELD_BAND,
    FacetMetadata.FIELD_CATEGORY,
    FacetMetadata.FIELD_SET_KIND,
}

local BAND_VALUES = {}
for band = 0, 10 do
    BAND_VALUES[band + 1] = { value = tostring(band), title = tostring(band) }
end

FacetMetadata.metadataFieldsForPhotos = {
    {
        id = FacetMetadata.FIELD_AGGREGATE,
        title = 'Facet aggregate',
        dataType = 'string',
        searchable = true,
        browsable = true,
    },
    {
        id = FacetMetadata.FIELD_BAND,
        title = 'Facet band',
        dataType = 'enum',
        values = BAND_VALUES,
        searchable = true,
        browsable = true,
    },
    {
        id = FacetMetadata.FIELD_CATEGORY,
        title = 'Facet category',
        dataType = 'string',
        searchable = true,
        browsable = true,
    },
    {
        id = FacetMetadata.FIELD_SET_KIND,
        title = 'Facet set kind',
        dataType = 'enum',
        values = {
            { value = 'burst', title = 'Burst' },
            { value = 'bracket', title = 'Bracket' },
            { value = 'panorama', title = 'Panorama' },
            { value = 'hdr_panorama', title = 'HDR panorama' },
        },
        searchable = true,
        browsable = true,
    },
    {
        id = FacetMetadata.FIELD_DERIVED_RATING,
        dataType = 'string',
        searchable = false,
        browsable = false,
    },
    {
        id = FacetMetadata.FIELD_DERIVED_PICK,
        dataType = 'string',
        searchable = false,
        browsable = false,
    },
}

FacetMetadata.schemaVersion = 1

-- Required signature per the SDK research doc, even with nothing to migrate
-- on this, the first release of the schema.
function FacetMetadata.updateFromEarlierSchemaVersion(catalog, fromVersion, photos)
end

-- Independent of the `%.1f`-rounded display string: band is the floor of the
-- raw aggregate, never derived by parsing the rounded text back (N3).
function FacetMetadata.bandFromAggregate(aggregate)
    if type(aggregate) ~= 'number' then
        return nil
    end
    local band = math.floor(aggregate)
    if band < 0 then
        band = 0
    end
    if band > 10 then
        band = 10
    end
    return tostring(band)
end

function FacetMetadata.displayAggregate(aggregate)
    if type(aggregate) ~= 'number' then
        return nil
    end
    return string.format('%.1f', aggregate)
end

-- Bracket/panorama/hdr_panorama membership always wins over a bare burst
-- membership -- see the header comment's precedence rule.
function FacetMetadata.setKindFor(sequenceKind, burstGroupId)
    if sequenceKind ~= nil then
        return sequenceKind
    end
    if burstGroupId ~= nil then
        return 'burst'
    end
    return nil
end

-- Desired visible-field values for one manifest record, as a plain table
-- keyed by field id -> string value. Omits any field with no value (e.g. no
-- category) rather than writing an empty string.
function FacetMetadata.desiredFields(aggregate, category, sequenceKind, burstGroupId)
    local fields = {}
    local displayAggregate = FacetMetadata.displayAggregate(aggregate)
    if displayAggregate then
        fields[FacetMetadata.FIELD_AGGREGATE] = displayAggregate
    end
    local band = FacetMetadata.bandFromAggregate(aggregate)
    if band then
        fields[FacetMetadata.FIELD_BAND] = band
    end
    if type(category) == 'string' and category ~= '' then
        fields[FacetMetadata.FIELD_CATEGORY] = category
    end
    local setKind = FacetMetadata.setKindFor(sequenceKind, burstGroupId)
    if setKind then
        fields[FacetMetadata.FIELD_SET_KIND] = setKind
    end
    return fields
end

-- UNVERIFIED SDK behaviour: a never-set plug-in metadata field might be
-- reported by `batchGetPropertyForPlugin`/`getPropertyForPlugin` as an empty
-- string rather than nil. Every comparison against a field's CURRENT value
-- must go through this normaliser, so that possibility -- if real -- cannot
-- make a never-set field look like it holds a stale value that gets
-- re-cleared (or counted as pending) on every single run.
function FacetMetadata.normalizeCurrentFieldValue(value)
    if value == '' then
        return nil
    end
    return value
end

-- Writes `desiredByField` (a plain field-id -> string map) for one photo,
-- skipping any field whose read-back value (`currentByField`, from a prior
-- `batchGetPropertyForPlugin`) already matches. Must run inside the
-- caller's own `withPrivateWriteAccessDo`. Returns the number of fields
-- actually written.
--
-- A field with no desired value (e.g. a photo that left a bracket, so
-- sequence_kind and burst_group_id are both nil this run) is CLEARED when it
-- currently holds a value -- never just skipped -- otherwise a stale
-- facetSetKind/facetCategory/facetAggregate/facetBand lingers forever after
-- the photo is no longer in any set, and smart collections/Library Filter
-- criteria built on those fields keep matching it.
function FacetMetadata.writeFieldsForPhoto(plugin, photo, currentByField, desiredByField)
    local written = 0
    for _, key in ipairs(FacetMetadata.VISIBLE_FIELD_KEYS) do
        local desired = desiredByField[key]
        local current = FacetMetadata.normalizeCurrentFieldValue(currentByField[key])
        if desired == nil then
            if current ~= nil then
                photo:setPropertyForPlugin(plugin, key, nil)
                written = written + 1
            end
        elseif current ~= desired then
            photo:setPropertyForPlugin(plugin, key, desired)
            written = written + 1
        end
    end
    return written
end

-- Writes the two hidden derived-value bookkeeping fields for one photo,
-- unconditionally whenever the caller has just derived a stars/pick value
-- (Step 6b) -- always alongside Apply's own rating/pick write, never on its
-- own initiative. `ratingString`/`pickString` may each be nil (nothing
-- derived for that field this run).
function FacetMetadata.writeDerivedValuesForPhoto(plugin, photo, ratingString, pickString)
    if ratingString ~= nil then
        photo:setPropertyForPlugin(plugin, FacetMetadata.FIELD_DERIVED_RATING, ratingString)
    end
    if pickString ~= nil then
        photo:setPropertyForPlugin(plugin, FacetMetadata.FIELD_DERIVED_PICK, pickString)
    end
end

return FacetMetadata
