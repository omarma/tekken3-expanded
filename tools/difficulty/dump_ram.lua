-- MAME 0.289, tekken3 / tektagt, fresh NVRAM. No ROM data in here.
-- Writes DUMP_LEN bytes of main RAM from DUMP_ADDR to DUMP_OUT once the
-- attract mode has loaded the game program (frame DUMP_FRAME), then exits.
local machine = manager.machine
local space = machine.devices[":maincpu"].spaces["program"]
local addr = tonumber(os.getenv("DUMP_ADDR"), 16)
local len = tonumber(os.getenv("DUMP_LEN"))
local at = tonumber(os.getenv("DUMP_FRAME") or "1800")
local out = os.getenv("DUMP_OUT") or "ram.bin"
local frame = 0
-- The notifier must stay referenced, or it is collected and never runs again.
difficulty_dump = emu.add_machine_frame_notifier(function()
    frame = frame + 1
    if frame == at then
        local f = assert(io.open(out, "wb"))
        f:write(space:read_range(addr, addr + len - 1, 8))
        f:close()
        machine:exit()
    end
end)
