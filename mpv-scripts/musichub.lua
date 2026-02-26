local mp = require 'mp'
local msg = require 'mp.msg'
local utils = require 'mp.utils'
local options = require 'mp.options'

local opts = {
    events_file = "",
}
options.read_options(opts, "musichub")

local session_id = tostring(math.floor(mp.get_time() * 1000))

local function now_iso_utc()
    return os.date("!%Y-%m-%dT%H:%M:%SZ")
end

local function get_metadata()
    local md = mp.get_property_native("metadata")
    if type(md) == "table" then
        return md
    end
    return {}
end

local function current_payload(event_name, extra)
    local payload = {
        event = event_name,
        time = now_iso_utc(),
        session_id = session_id,
        path = mp.get_property("path"),
        media_title = mp.get_property("media-title"),
        playback_time = mp.get_property_number("playback-time", nil),
        duration = mp.get_property_number("duration", nil),
        playlist_pos = mp.get_property_number("playlist-pos", nil),
        metadata = get_metadata(),
    }
    if extra then
        for k, v in pairs(extra) do
            payload[k] = v
        end
    end
    return payload
end

local function append_event(event_name, extra)
    if not opts.events_file or opts.events_file == "" then
        return
    end
    local file, err = io.open(opts.events_file, "a")
    if not file then
        msg.warn("musichub: cannot open events file: " .. tostring(err))
        return
    end
    local payload = current_payload(event_name, extra)
    local line = utils.format_json(payload)
    if not line then
        file:close()
        msg.warn("musichub: failed to encode event")
        return
    end
    file:write(line)
    file:write("\n")
    file:close()
end

mp.register_event("file-loaded", function()
    append_event("play_start", nil)
end)

mp.register_event("end-file", function(e)
    append_event("play_end", { reason = e and e.reason or nil })
end)

mp.add_forced_key_binding("g", "musichub-good", function()
    append_event("good", nil)
    mp.osd_message("GOOD", 1.2)
end)

mp.add_forced_key_binding("b", "musichub-bad", function()
    append_event("bad", nil)
    mp.osd_message("BAD", 1.2)
end)

mp.add_forced_key_binding("n", "musichub-next", function()
    append_event("next", { reason = "manual_next_key" })
    mp.osd_message("NEXT", 1.2)
    mp.commandv("playlist-next", "force")
end)

