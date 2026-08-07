--[[
 host_env.lua: enough of Aegisub's Lua automation API to run the real
 kara-templater.lua and karaskel-auto4.lua, taken from an installed Aegisub,
 outside any GUI.

 The templater and karaskel are the shipped originals. Only the host is
 emulated: the `aegisub` API table (the scripts look it up by that name), the
 `subs` object, and karaoke tag parsing.

 text_extents is backed by rendering rather than by a model of a font. It
 reproduces Aegisub's sizing convention by default, so output predicts what
 Aegisub would write; the checkers judge that against the renderer. The two
 conventions disagree for some fonts, which is why the template carries emfix.
 See docs/how-it-works.md.

 Answers come from a disk cache. Which strings get measured depends only on the
 text, so a cold run records its misses, fills them in one batch, and repeats.
]]

local M = {}

local SEP = "\t"

-- Where the editor keeps its bundled automation scripts. Override with
-- KARA_AUTOMATION_DIR when installed somewhere unusual.
local AEGI_CANDIDATES = {
    -- macOS
    "/Applications/Aegisub.app/Contents/SharedSupport/automation",
    (os.getenv("HOME") or "") .. "/Applications/Aegisub.app/Contents/SharedSupport/automation",
    -- Linux
    "/usr/share/aegisub/automation",
    "/usr/local/share/aegisub/automation",
    "/var/lib/flatpak/app/org.aegisub.Aegisub/current/active/files/share/aegisub/automation",
    (os.getenv("HOME") or "") .. "/.local/share/aegisub/automation",
    -- Windows
    "C:/Program Files/Aegisub/automation",
    "C:/Program Files (x86)/Aegisub/automation",
    (os.getenv("APPDATA") or "") .. "/Aegisub/automation",
    (os.getenv("PROGRAMFILES") or "") .. "/Aegisub/automation",
}

local function dir_has(path, file)
    local f = io.open(path .. "/" .. file, "r")
    if f then f:close(); return true end
    return false
end

local AEGI = os.getenv("KARA_AUTOMATION_DIR")
if not AEGI then
    for _, c in ipairs(AEGI_CANDIDATES) do
        if c ~= "" and dir_has(c, "autoload/kara-templater.lua") then
            AEGI = c
            break
        end
    end
end
if not AEGI then
    error("Cannot find the editor's automation directory. Set "
          .. "KARA_AUTOMATION_DIR to the folder containing "
          .. "autoload/kara-templater.lua", 0)
end

----------------------------------------------------------------------
-- .ass parsing / serialisation
----------------------------------------------------------------------

local function trim(s) return (s:gsub("^%s+", ""):gsub("%s+$", "")) end

local function parse_time(s)
    local h, m, sec, cs = s:match("(%d+):(%d+):(%d+)%.(%d+)")
    if not h then return 0 end
    return ((tonumber(h) * 60 + tonumber(m)) * 60 + tonumber(sec)) * 1000
           + tonumber(cs) * 10
end

local function fmt_time(ms)
    if ms < 0 then ms = 0 end
    local cs = math.floor(ms / 10 + 0.5)
    local s = math.floor(cs / 100); cs = cs % 100
    local m = math.floor(s / 60);   s = s % 60
    local h = math.floor(m / 60);   m = m % 60
    return string.format("%d:%02d:%02d.%02d", h, m, s, cs)
end
M.fmt_time = fmt_time

-- Split a Format:/Dialogue: value list, honouring that the LAST field of an
-- event (the text) may itself contain commas.
local function split_fields(s, n)
    local out = {}
    local pos = 1
    for i = 1, n - 1 do
        local c = s:find(",", pos, true)
        if not c then break end
        out[i] = s:sub(pos, c - 1)
        pos = c + 1
    end
    out[n] = s:sub(pos)
    return out
end

local STYLE_FIELDS = {
    "name", "fontname", "fontsize", "color1", "color2", "color3", "color4",
    "bold", "italic", "underline", "strikeout", "scale_x", "scale_y",
    "spacing", "angle", "borderstyle", "outline", "shadow", "align",
    "margin_l", "margin_r", "margin_t", "encoding",
}
local STYLE_NUM = {
    fontsize = true, bold = true, italic = true, underline = true,
    strikeout = true, scale_x = true, scale_y = true, spacing = true,
    angle = true, borderstyle = true, outline = true, shadow = true,
    align = true, margin_l = true, margin_r = true, margin_t = true,
    encoding = true,
}

function M.parse_ass(path)
    local f = assert(io.open(path, "r"), "cannot open " .. path)
    local lines = {}
    local section = ""
    local style_format, event_format
    for raw in f:lines() do
        raw = raw:gsub("\r$", "")
        if raw:sub(1, 3) == "\239\187\191" then raw = raw:sub(4) end   -- BOM
        local l
        if raw:match("^%[") then
            section = trim(raw)
            l = { class = "info", section = section, raw = raw,
                  key = "", value = "", _header = true }
        elseif section:lower():find("styles") and raw:match("^Format:") then
            style_format = raw
            l = { class = "info", section = section, raw = raw,
                  key = "", value = "", _verbatim = true }
        elseif section == "[Events]" and raw:match("^Format:") then
            event_format = raw
            l = { class = "info", section = section, raw = raw,
                  key = "", value = "", _verbatim = true }
        elseif section:lower():find("styles") and raw:match("^Style:") then
            local v = split_fields(trim(raw:sub(7)), #STYLE_FIELDS)
            l = { class = "style", section = section, raw = raw }
            for i, key in ipairs(STYLE_FIELDS) do
                local val = trim(v[i] or "")
                if STYLE_NUM[key] then val = tonumber(val) or 0 end
                l[key] = val
            end
            l.bold = l.bold ~= 0
            l.italic = l.italic ~= 0
            l.underline = l.underline ~= 0
            l.strikeout = l.strikeout ~= 0
            l.margin_b = l.margin_t
            l.margin_v = l.margin_t
        elseif section == "[Events]" and (raw:match("^Dialogue:") or raw:match("^Comment:")) then
            local comment = raw:match("^Comment:") ~= nil
            local v = split_fields(trim(raw:sub(raw:find(":") + 1)), 10)
            l = {
                class = "dialogue", section = section, raw = raw,
                comment = comment,
                layer = tonumber(trim(v[1])) or 0,
                start_time = parse_time(v[2] or ""),
                end_time = parse_time(v[3] or ""),
                style = trim(v[4] or ""),
                actor = trim(v[5] or ""),
                margin_l = tonumber(trim(v[6])) or 0,
                margin_r = tonumber(trim(v[7])) or 0,
                margin_t = tonumber(trim(v[8])) or 0,
                effect = trim(v[9] or ""),
                text = v[10] or "",
            }
            l.margin_b = l.margin_t
            l.margin_v = l.margin_t
            l.extra = {}
        elseif section == "[Script Info]" and raw:find(":") then
            local k, v = raw:match("^([^:]+):%s*(.*)$")
            l = { class = "info", section = section, raw = raw, key = k, value = v }
        else
            l = { class = "info", section = section, raw = raw,
                  key = "", value = "", _verbatim = true }
        end
        lines[#lines + 1] = l
    end
    f:close()
    return lines, style_format, event_format
end

local function style_to_raw(l)
    local v = {}
    for i, key in ipairs(STYLE_FIELDS) do
        local x = l[key]
        if type(x) == "boolean" then x = x and -1 or 0 end
        if key == "fontsize" or key == "outline" or key == "shadow" then
            -- keep .5 sizes intact (furigana styles are half size)
            x = (x % 1 == 0) and string.format("%d", x) or tostring(x)
        end
        v[i] = tostring(x)
    end
    return "Style: " .. table.concat(v, ",")
end

local function dialogue_to_raw(l)
    return string.format("%s: %d,%s,%s,%s,%s,%d,%d,%d,%s,%s",
        l.comment and "Comment" or "Dialogue", l.layer or 0,
        fmt_time(l.start_time), fmt_time(l.end_time),
        l.style or "", l.actor or "",
        l.margin_l or 0, l.margin_r or 0, l.margin_t or 0,
        l.effect or "", l.text or "")
end

function M.write_ass(path, subs)
    local f = assert(io.open(path, "w"))
    for i = 1, #subs do
        local l = subs[i]
        if l.class == "dialogue" then
            f:write(dialogue_to_raw(l), "\n")
        elseif l.class == "style" then
            f:write(style_to_raw(l), "\n")
        else
            f:write(l.raw or "", "\n")
        end
    end
    f:close()
end

----------------------------------------------------------------------
-- the subs object
----------------------------------------------------------------------

function M.make_subs(lines)
    local subs = {}
    for i, l in ipairs(lines) do subs[i] = l end

    subs.append = function(l)
        -- Aegisub appends into the line's own section; every line the
        -- templater appends is a dialogue, so end-of-file is the same place.
        subs[#subs + 1] = l
    end
    subs.delete = function(...)
        local idx = { ... }
        table.sort(idx, function(a, b) return a > b end)
        for _, i in ipairs(idx) do table.remove(subs, i) end
    end
    subs.deleterange = function(a, b)
        for i = b, a, -1 do table.remove(subs, i) end
    end
    subs.insert = function(i, l) table.insert(subs, i, l) end
    subs.script_resolution = function()
        local x, y
        for i = 1, #subs do
            local l = subs[i]
            if l.class == "info" and l.key then
                local k = l.key:lower()
                if k == "playresx" then x = tonumber(l.value) end
                if k == "playresy" then y = tonumber(l.value) end
            end
        end
        return x or 640, y or 480
    end

    -- Assigning to a NEGATIVE index inserts before that position; karaskel
    -- uses that to splice generated furigana styles into the header.
    setmetatable(subs, {
        __newindex = function(t, k, v)
            if type(k) == "number" and k < 0 then
                table.insert(t, -k, v)
            else
                rawset(t, k, v)
            end
        end,
    })
    return subs
end

----------------------------------------------------------------------
-- text measurement
----------------------------------------------------------------------

local cache = {}          -- key -> {w, h, desc, extlead}
local misses = {}         -- key -> job fields
local miss_n = 0
local cache_path

local function ekey(st, text)
    return table.concat({
        st.fontname, tostring(st.fontsize), st.bold and 1 or 0,
        st.italic and 1 or 0, tostring(st.spacing or 0),
        tostring(st.scale_x or 100), tostring(st.scale_y or 100), text,
    }, SEP)
end

function M.load_cache(path)
    cache_path = path
    local f = io.open(path, "r")
    if not f then return end
    for line in f:lines() do
        local key, w, h, d, e = line:match("^(.*)\t([%-%d%.]+)\t([%-%d%.]+)\t([%-%d%.]+)\t([%-%d%.]+)$")
        if key then
            cache[key] = { tonumber(w), tonumber(h), tonumber(d), tonumber(e) }
        end
    end
    f:close()
end

function M.pending_misses() return miss_n, misses end

function M.write_missfile(path)
    local f = assert(io.open(path, "w"))
    local keys = {}
    for k in pairs(misses) do keys[#keys + 1] = k end
    table.sort(keys)
    for _, k in ipairs(keys) do f:write(k, "\n") end
    f:close()
    return keys
end

function M.merge_results(keys, respath)
    local f = assert(io.open(respath, "r"))
    local i = 0
    local out = assert(io.open(cache_path, "a"))
    for line in f:lines() do
        i = i + 1
        local w, h, d, e = line:match("^([%-%d%.]+)\t([%-%d%.]+)\t([%-%d%.]+)\t([%-%d%.]+)$")
        if w and keys[i] then
            cache[keys[i]] = { tonumber(w), tonumber(h), tonumber(d), tonumber(e) }
            out:write(keys[i], SEP, w, SEP, h, SEP, d, SEP, e, "\n")
        end
    end
    f:close()
    out:close()
    misses, miss_n = {}, 0
end

----------------------------------------------------------------------
-- karaoke parsing (Aegisub's AssKaraoke)
----------------------------------------------------------------------

local function parse_karaoke(line)
    local text = line.text or ""
    local syls = {}
    local cur = { text = "", text_stripped = "", duration = 0, tag = "" }
    local pos = 1
    while pos <= #text do
        local bs, be = text:find("%b{}", pos)
        if not bs then
            local run = text:sub(pos)
            cur.text = cur.text .. run
            cur.text_stripped = cur.text_stripped .. run
            break
        end
        if bs > pos then
            local run = text:sub(pos, bs - 1)
            cur.text = cur.text .. run
            cur.text_stripped = cur.text_stripped .. run
        end
        local block = text:sub(bs, be)
        local inner = block:sub(2, -2)
        local ktag, kval = inner:match("\\(k[fo]?)(%d+)")
        if not ktag then ktag, kval = inner:match("\\(K)(%d+)") end
        if ktag then
            -- a k-tag closes the current syllable and opens the next one
            syls[#syls + 1] = cur
            local rest = block:gsub("\\" .. ktag .. kval, "")
            if rest == "{}" then rest = "" end
            cur = { text = rest, text_stripped = "",
                    duration = tonumber(kval) * 10,
                    tag = (ktag == "K") and "kf" or ktag }
        else
            cur.text = cur.text .. block
        end
        pos = be + 1
    end
    syls[#syls + 1] = cur

    local out = {}
    local t = 0
    for i, s in ipairs(syls) do
        s.start_time = t
        s.end_time = t + s.duration
        t = s.end_time
        out[i - 1] = s          -- Aegisub indexes karaoke data from 0
    end
    return out
end

----------------------------------------------------------------------
-- the aegisub table
----------------------------------------------------------------------

local registered = {}
M.registered = registered

function M.install(opts)
    opts = opts or {}
    local verbosity = opts.verbosity or 0

    local aegisub = {}
    aegisub.progress = {
        task = function() end,
        set = function() end,
        is_cancelled = function() return false end,
    }
    aegisub.debug = {
        out = function(lvl, fmt, ...)
            if type(lvl) ~= "number" then fmt, lvl = lvl, 1 end
            if lvl > verbosity then return end
            io.stderr:write(select("#", ...) > 0 and string.format(fmt, ...) or tostring(fmt))
        end,
    }
    aegisub.cancel = function() error("cancelled", 0) end
    aegisub.set_undo_point = function() end
    aegisub.video_size = function() return nil end
    aegisub.gettext = function(s) return s end
    aegisub.parse_karaoke_data = parse_karaoke
    aegisub.register_macro = function(name, desc, fn, valid)
        registered.macro = { name = name, fn = fn, valid = valid }
    end
    aegisub.register_filter = function(name, desc, prio, fn)
        registered.filter = { name = name, fn = fn }
    end

    aegisub.text_extents = function(style, text)
        text = text or ""
        local key = ekey(style, text)
        local hit = cache[key]
        if hit then return hit[1], hit[2], hit[3], hit[4] end
        if not misses[key] then
            misses[key] = true
            miss_n = miss_n + 1
        end
        -- Provisional answer for this pass only; the run that uses it is
        -- discarded. Which strings get measured does not depend on it.
        return #text * style.fontsize * 0.7, style.fontsize, 0, 0
    end

    _G.aegisub = aegisub

    -- Aegisub's include dir also holds MoonScript modules that utils.lua
    -- pulls in through require ('aegisub.util' etc). Install the bundled
    -- moonscript compiler as a package loader so those resolve.
    if not package.loaded["moonscript"] then
        package.path = AEGI .. "/include/?.lua;" .. package.path
        local ms = dofile(AEGI .. "/include/moonscript.lua")
        package.loaded["moonscript"] = ms
        package.moonpath = AEGI .. "/include/?.moon"
        table.insert(package.loaders or package.searchers, function(name)
            local fn = AEGI .. "/include/" .. name:gsub("%.", "/") .. ".moon"
            local f = io.open(fn, "r")
            if not f then return "\n\tno moon file '" .. fn .. "'" end
            local src = f:read("*a")
            f:close()
            src = src:gsub("^\239\187\191", "")     -- BOM trips the parser
            local code, err = ms.to_lua(src)
            if not code then error(fn .. ": " .. tostring(err)) end
            return assert(loadstring(code, "@" .. fn))
        end)
    end

    -- The template reads font files itself to work out emfix, which needs
    -- directory listing. The editor preloads lfs as a C module; outside it,
    -- stand in with a shell listing so the same template code runs here.
    if not package.loaded["aegisub.lfs"] then
        local lfs = {}
        local windows = (package.config or "/"):sub(1, 1) == "\\"
        -- Returns (iterator, state) exactly as the editor's lfs does, where the
        -- iterator is a method that indexes its state. Returning a bare closure
        -- would accept a caller that drops the state, which the real API does
        -- not, and would hide the bug here instead of reproducing it.
        function lfs.dir(d)
            local cmd = windows and ('dir /b "' .. d .. '" 2>nul')
                                 or ('ls -1 "' .. d .. '" 2>/dev/null')
            local pipe = io.popen(cmd)
            if not pipe then error("cannot list " .. d, 0) end
            local names = {}
            for l in pipe:lines() do names[#names + 1] = l end
            pipe:close()
            if #names == 0 then error("empty or missing: " .. d, 0) end
            local state = { i = 0, names = names }
            local function iter(self)
                self.i = self.i + 1
                return self.names[self.i]
            end
            return iter, state
        end
        function lfs.attributes(path, field)
            if field ~= "mode" then return nil end
            local cmd = windows and ('if exist "' .. path .. '\\*" (exit 0) else (exit 1)')
                                 or ('test -d "' .. path .. '"')
            local ok = os.execute(cmd)
            if ok == 0 or ok == true then return "directory" end
            return "file"
        end
        package.loaded["aegisub.lfs"] = lfs
        package.loaded["lfs"] = lfs
    end

    -- aegisub/unicode.moon binds a C module (aegisub.__unicode_impl) that only
    -- exists inside Aegisub, and it is needed solely for case conversion, which
    -- karaskel never calls. Supply the UTF-8 helpers in plain Lua instead.
    if not package.preload["aegisub.unicode"] then
        package.preload["aegisub.unicode"] = function()
            local u = {}
            function u.charwidth(s, i)
                local b = s:byte(i or 1)
                if not b then return 1 end
                if b < 128 then return 1 elseif b < 224 then return 2
                elseif b < 240 then return 3 else return 4 end
            end
            function u.chars(s)
                local i, n = 1, 0
                return function()
                    if i > #s then return end
                    local j = i
                    n = n + 1
                    i = i + u.charwidth(s, i)
                    return s:sub(j, i - 1), n
                end
            end
            function u.len(s)
                local n = 0
                for _ in u.chars(s) do n = n + 1 end
                return n
            end
            function u.codepoint(s)
                local b = s:byte(1)
                if b < 128 then return b end
                local res, w
                if b < 224 then res, w = b - 192, 2
                elseif b < 240 then res, w = b - 224, 3
                else res, w = b - 240, 4 end
                for i = 2, w do res = res * 64 + s:byte(i) - 128 end
                return res
            end
            u.to_upper_case = string.upper
            u.to_lower_case = string.lower
            u.to_fold_case = string.lower
            return u
        end
    end

    -- Aegisub's include(): resolve against the bundle's include dir.
    local included = {}
    _G.include = function(fn)
        if included[fn] then return end
        included[fn] = true
        local path = AEGI .. "/include/" .. fn
        local chunk = assert(loadfile(path), "cannot load " .. path)
        return chunk()
    end

    -- utils.lua expects these to exist
    if not _G.unpack then _G.unpack = table.unpack end
    return aegisub
end

M.AEGI = AEGI
return M
