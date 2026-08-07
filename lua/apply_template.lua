--[[
 apply_template.lua: run Aegisub's "Apply karaoke template" headlessly.

   karaoke-ass apply in.ass out.ass     (or: luajit lua/apply_template.lua ...)

 Loads the shipped kara-templater.lua from an Aegisub install and calls the
 macro it registers, with text_extents answered from rendered measurements.

 Pass 1 records every string the templater asks about, one batch measures them,
 then the pass repeats with real numbers. Which strings are asked about depends
 only on the input text, so this converges on pass 2.
]]

local HERE = arg[0]:match("^(.*)[/\\][^/\\]+$") or "."
local ROOT = HERE:match("^(.*)[/\\][^/\\]+$") or ".."
package.path = HERE .. "/?.lua;" .. package.path

local env = require("host_env")

local infile, outfile = arg[1], arg[2]
if not infile or not outfile then
    io.stderr:write("usage: apply_template.lua in.ass out.ass [-v N]\n")
    os.exit(2)
end
local verbosity = 0
for i = 3, #arg do
    if arg[i] == "-v" then verbosity = tonumber(arg[i + 1]) or 3 end
end

local WINDOWS = (package.config or "/"):sub(1, 1) == "\\"
local PYTHON = os.getenv("KARA_PYTHON") or (WINDOWS and "python" or "python3")

local function tmpdir()
    local d = os.getenv("TMPDIR") or os.getenv("TEMP") or os.getenv("TMP")
    if not d then d = WINDOWS and "." or "/tmp" end
    return (d:gsub("[/\\]$", ""))
end

local function q(s) return '"' .. s .. '"' end   -- paths may contain spaces

local CACHE = ROOT .. "/bin/.extents-cache-"
             .. (os.getenv("KARA_MEASURE") == "libass" and "libass" or "editor")
             .. ".tsv"
env.load_cache(CACHE)

local function run_pass()
    -- Fresh globals per pass: karaskel and the templater keep module state.
    for _, k in ipairs({ "karaskel", "aegisub", "include", "unicode", "util",
                         "templates", "furigana_scale" }) do
        _G[k] = nil
    end
    env.install({ verbosity = verbosity })
    local chunk = assert(loadfile(env.AEGI .. "/autoload/kara-templater.lua"))
    chunk()

    local lines = env.parse_ass(infile)
    local subs = env.make_subs(lines)

    local sel = {}
    for i = 1, #subs do
        if subs[i].class == "dialogue" then sel[#sel + 1] = i end
    end

    local macro = env.registered.macro
    assert(macro, "kara-templater registered no macro")
    macro.fn(subs, sel, sel[1])
    return subs
end

local subs
for pass = 1, 6 do
    subs = run_pass()
    local n = env.pending_misses()
    if n == 0 then
        io.stderr:write(string.format("pass %d: cache complete\n", pass))
        break
    end
    io.stderr:write(string.format("pass %d: %d strings to measure\n", pass, n))
    local missfile = tmpdir() .. "/karaoke-ass-misses.tsv"
    local resfile = tmpdir() .. "/karaoke-ass-results.tsv"
    local keys = env.write_missfile(missfile)
    -- Reproduce the EDITOR's measurement convention, not the renderer's, so
    -- this predicts what the editor would write. The template's emfix value is
    -- what reconciles the two; the checkers judge against the renderer.
    local mode = os.getenv("KARA_MEASURE") == "libass" and "" or " --editor"
    -- Measurement lives in the Python package; -m keeps this working both
    -- from a checkout (PYTHONPATH set by the CLI) and from an install.
    local cmd = string.format("%s -m karaoke_ass.measure %s %s%s", PYTHON,
                              q(missfile), q(resfile), mode)
    local ok = os.execute(cmd)
    if ok ~= true and ok ~= 0 then error("measurement failed: " .. cmd) end
    env.merge_results(keys, resfile)
    subs = nil
end

assert(subs, "template never converged")
env.write_ass(outfile, subs)
io.stderr:write("wrote " .. outfile .. "\n")
