local FacetJson = {}

FacetJson.null = {}

local WHITESPACE_PATTERN = '^[ \t\r\n]*'
local STRING_STOP_PATTERN = '["\\]'
local HEX_QUARTET_PATTERN = '^%x%x%x%x$'
local LOW_SURROGATE_PATTERN = '^\\u(%x%x%x%x)'
local NUMBER_START_PATTERN = '^[%-%d]'
local NUMBER_WITH_EXPONENT_PATTERN = '^%-?%d+%.?%d*[eE][%-+]?%d+'
local NUMBER_PATTERN = '^%-?%d+%.?%d*'
local BYTE_ORDER_MARK = '\239\187\191'

local ESCAPE_CHARACTERS = {
    ['"'] = '"',
    ['\\'] = '\\',
    ['/'] = '/',
    ['b'] = '\b',
    ['f'] = '\f',
    ['n'] = '\n',
    ['r'] = '\r',
    ['t'] = '\t',
}

local decodeValue

local function decodeError(text, position, message)
    local excerptStart = math.max(1, position - 20)
    local excerpt = string.sub(text, excerptStart, position + 20)
    error(string.format('%s at byte %d near: %s', message, position, excerpt), 0)
end

local function skipWhitespace(text, position)
    local _, stop = string.find(text, WHITESPACE_PATTERN, position)
    return stop + 1
end

local function codepointToUtf8(codepoint)
    if codepoint < 0x80 then
        return string.char(codepoint)
    end
    if codepoint < 0x800 then
        return string.char(
            0xC0 + math.floor(codepoint / 0x40),
            0x80 + codepoint % 0x40)
    end
    if codepoint < 0x10000 then
        return string.char(
            0xE0 + math.floor(codepoint / 0x1000),
            0x80 + math.floor(codepoint / 0x40) % 0x40,
            0x80 + codepoint % 0x40)
    end
    return string.char(
        0xF0 + math.floor(codepoint / 0x40000),
        0x80 + math.floor(codepoint / 0x1000) % 0x40,
        0x80 + math.floor(codepoint / 0x40) % 0x40,
        0x80 + codepoint % 0x40)
end

local function decodeString(text, position)
    local parts = {}
    local partCount = 0
    local chunkStart = position + 1
    local cursor = chunkStart
    while true do
        local stop = string.find(text, STRING_STOP_PATTERN, cursor)
        if not stop then
            decodeError(text, position, 'unterminated string')
        end
        partCount = partCount + 1
        parts[partCount] = string.sub(text, chunkStart, stop - 1)
        if string.sub(text, stop, stop) == '"' then
            return table.concat(parts), stop + 1
        end
        local escape = string.sub(text, stop + 1, stop + 1)
        local simple = ESCAPE_CHARACTERS[escape]
        if simple then
            partCount = partCount + 1
            parts[partCount] = simple
            cursor = stop + 2
        elseif escape == 'u' then
            local hex = string.sub(text, stop + 2, stop + 5)
            if not string.find(hex, HEX_QUARTET_PATTERN) then
                decodeError(text, stop, 'invalid \\u escape')
            end
            local codepoint = tonumber(hex, 16)
            cursor = stop + 6
            if codepoint >= 0xD800 and codepoint <= 0xDBFF then
                local lowHex = string.match(text, LOW_SURROGATE_PATTERN, cursor)
                local low = lowHex and tonumber(lowHex, 16)
                if low and low >= 0xDC00 and low <= 0xDFFF then
                    codepoint = 0x10000 + (codepoint - 0xD800) * 0x400 + (low - 0xDC00)
                    cursor = cursor + 6
                end
            end
            partCount = partCount + 1
            parts[partCount] = codepointToUtf8(codepoint)
        else
            decodeError(text, stop, 'invalid escape sequence')
        end
        chunkStart = cursor
    end
end

local function decodeNumber(text, position)
    local _, stop = string.find(text, NUMBER_WITH_EXPONENT_PATTERN, position)
    if not stop then
        _, stop = string.find(text, NUMBER_PATTERN, position)
    end
    if not stop then
        decodeError(text, position, 'invalid number')
    end
    local value = tonumber(string.sub(text, position, stop))
    if not value then
        decodeError(text, position, 'invalid number')
    end
    return value, stop + 1
end

local function decodeArray(text, position)
    local result = {}
    local count = 0
    local cursor = skipWhitespace(text, position + 1)
    if string.sub(text, cursor, cursor) == ']' then
        return result, cursor + 1
    end
    while true do
        local value
        value, cursor = decodeValue(text, cursor)
        count = count + 1
        result[count] = value
        cursor = skipWhitespace(text, cursor)
        local character = string.sub(text, cursor, cursor)
        if character == ',' then
            cursor = cursor + 1
        elseif character == ']' then
            return result, cursor + 1
        else
            decodeError(text, cursor, "expected ',' or ']'")
        end
    end
end

local function decodeObject(text, position)
    local result = {}
    local cursor = skipWhitespace(text, position + 1)
    if string.sub(text, cursor, cursor) == '}' then
        return result, cursor + 1
    end
    while true do
        cursor = skipWhitespace(text, cursor)
        if string.sub(text, cursor, cursor) ~= '"' then
            decodeError(text, cursor, 'expected a string key')
        end
        local key
        key, cursor = decodeString(text, cursor)
        cursor = skipWhitespace(text, cursor)
        if string.sub(text, cursor, cursor) ~= ':' then
            decodeError(text, cursor, "expected ':'")
        end
        local value
        value, cursor = decodeValue(text, cursor + 1)
        result[key] = value
        cursor = skipWhitespace(text, cursor)
        local character = string.sub(text, cursor, cursor)
        if character == ',' then
            cursor = cursor + 1
        elseif character == '}' then
            return result, cursor + 1
        else
            decodeError(text, cursor, "expected ',' or '}'")
        end
    end
end

decodeValue = function(text, position)
    local cursor = skipWhitespace(text, position)
    local character = string.sub(text, cursor, cursor)
    if character == '' then
        decodeError(text, cursor, 'unexpected end of input')
    end
    if character == '{' then
        return decodeObject(text, cursor)
    end
    if character == '[' then
        return decodeArray(text, cursor)
    end
    if character == '"' then
        return decodeString(text, cursor)
    end
    if string.sub(text, cursor, cursor + 3) == 'true' then
        return true, cursor + 4
    end
    if string.sub(text, cursor, cursor + 4) == 'false' then
        return false, cursor + 5
    end
    if string.sub(text, cursor, cursor + 3) == 'null' then
        return FacetJson.null, cursor + 4
    end
    if string.find(character, NUMBER_START_PATTERN) then
        return decodeNumber(text, cursor)
    end
    decodeError(text, cursor, 'unexpected character')
end

local ENCODE_ESCAPES = {
    ['"'] = '\\"',
    ['\\'] = '\\\\',
    ['\b'] = '\\b',
    ['\f'] = '\\f',
    ['\n'] = '\\n',
    ['\r'] = '\\r',
    ['\t'] = '\\t',
}

local function encodeString(value)
    local parts = { '"' }
    local count = 1
    for index = 1, #value do
        local byte = string.byte(value, index)
        local ch = string.char(byte)
        local escape = ENCODE_ESCAPES[ch]
        count = count + 1
        if escape then
            parts[count] = escape
        elseif byte < 0x20 then
            parts[count] = string.format('\\u%04x', byte)
        else
            -- Raw UTF-8 passthrough: multi-byte sequences are copied
            -- byte-for-byte, never escaped.
            parts[count] = ch
        end
    end
    count = count + 1
    parts[count] = '"'
    return table.concat(parts)
end

local encodeValue

-- `isArray` and `length` are explicit hints from the caller -- an empty Lua
-- table has no type information distinguishing "empty array" from "empty
-- object", so the encoder never infers this from the value itself.
local function encodeArray(value, length)
    if length == 0 then
        return '[]'
    end
    local parts = {}
    for index = 1, length do
        parts[index] = encodeValue(value[index])
    end
    return '[' .. table.concat(parts, ',') .. ']'
end

local function encodeObject(value, keys)
    local parts = {}
    local count = 0
    for _, key in ipairs(keys) do
        local fieldValue = value[key]
        -- Lua drops a `nil` table value silently; this is the point where an
        -- omitted key becomes an omitted key in the JSON, never a written
        -- `null`. Callers that DO want an explicit value must pass one that
        -- is not `nil` (e.g. 0), never rely on this function to invent one.
        if fieldValue ~= nil then
            count = count + 1
            parts[count] = encodeString(key) .. ':' .. encodeValue(fieldValue)
        end
    end
    return '{' .. table.concat(parts, ',') .. '}'
end

encodeValue = function(value)
    local valueType = type(value)
    if valueType == 'string' then
        return encodeString(value)
    end
    if valueType == 'number' then
        return string.format('%g', value)
    end
    if valueType == 'boolean' then
        return value and 'true' or 'false'
    end
    if value == FacetJson.null then
        return 'null'
    end
    if valueType == 'table' then
        if value.isArray then
            return encodeArray(value, value.length or #value)
        end
        if value.keys then
            return encodeObject(value, value.keys)
        end
        -- Bare array-style table (no hint table wrapper): encode positionally.
        return encodeArray(value, #value)
    end
    error('FacetJson.encode: unsupported value type ' .. valueType, 0)
end

-- FacetJson.encode(value) -- `value` for the top-level object form is a
-- plain table plus an explicit `keys` list giving both the field order and
-- which optional keys to consider (nil-valued keys in that list are
-- omitted, per encodeObject above). Array fields must be wrapped as
-- `{isArray = true, length = N, [1] = ..., [2] = ...}` so an empty array
-- encodes as `[]` rather than being mistaken for an empty object.
function FacetJson.encode(value, keys)
    if keys then
        return encodeObject(value, keys)
    end
    return encodeValue(value)
end

function FacetJson.encodeArray(items, length)
    return encodeArray(items, length == nil and #items or length)
end

function FacetJson.decode(text)
    if type(text) ~= 'string' then
        error('FacetJson.decode expects a string', 0)
    end
    local start = 1
    if string.sub(text, 1, 3) == BYTE_ORDER_MARK then
        start = 4
    end
    local value, cursor = decodeValue(text, start)
    cursor = skipWhitespace(text, cursor)
    if cursor <= #text then
        decodeError(text, cursor, 'unexpected trailing content')
    end
    return value
end

return FacetJson
