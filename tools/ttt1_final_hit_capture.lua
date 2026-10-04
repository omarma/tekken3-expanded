-- MAME 0.289, tektagt, NVRAM neuf. Aucune donnee de ROM ici.
-- Releve la VRAM de TTT1 au debut du combat final de l'Arcade, ou Unknown est
-- le CPU : son effet de coup fort est la planche du joueur 2, page (640, 256),
-- palette (528, 64) (tools/ttt1/hit_effect.py, player = 1). Unknown n'a pas de
-- case au selecteur et TTT1_INDEX ne tient pas jusqu'au combat versus : le
-- releve par tools/ttt1_hit_effect_capture.lua donnait celui de Xiaoyu.
-- Meme chemin que tools/ttt1_final_stage_capture.lua (niveau 0x2FE244 mis a 6,
-- mort en un coup du CPU) ; au combat final (niveau 7, corps 33 du CPU), la
-- vie d'Unknown est remise a plein, la VRAM relevee 60 images plus tard.
-- Sortie : hit-vram.bin (VRAM 1024 x 1024, 16 bits) et une capture d'ecran.
local machine = manager.machine
local space = machine.devices[":maincpu"].spaces["program"]
local port = machine.ioport.ports[":JVS_PLAYER1"]
local UNLOCK, LEVEL, CPU_LIFE_HI, TIMER, FINAL = 0x2fe4fc, 0x2fe244, 0x2a0d2a, 0x2434e0, 7
local CPU_KEYS, LIFE, UNKNOWN_FULL = 0x29eef8 + 0x1a60, 0x3d0, 0x104000
local frame, dump = 0, nil
local function press(name, on) port.fields[name]:set_value(on and 1 or 0) end
local steps = {{2060, "P1 Button 1"}, {2120, "P1 Right"}, {2160, "P1 Button 1"}}
ttt1_final_hit = emu.add_machine_frame_notifier(function()
    frame = frame + 1
    space:write_u32(UNLOCK, 0xffffffff)
    if dump then
        if frame == dump then
            local vram = emu.item(machine.devices[":gpu"].items["0/p_vram"])
            local f = assert(io.open("hit-vram.bin", "wb"))
            f:write(vram:read_block(0, vram.count * vram.size)); f:close()
            machine.video:snapshot()
            machine:exit()
        end
        return
    end
    local coin = machine.ioport.ports[":JVS_COIN1"].fields["Coin 1"]
    if frame % 600 == 0 then coin:set_value(1) end          -- credits pour un continue
    if frame % 600 == 4 then coin:set_value(0) end
    if frame == 1860 then press("1 Player Start", true) end
    if frame == 1864 then press("1 Player Start", false) end
    for _, s in ipairs(steps) do
        if frame == s[1] then press(s[2], true) end
        if frame == s[1] + 4 then press(s[2], false) end
    end
    if frame > 2400 then
        local timer, level = space:read_u32(TIMER), space:read_u32(LEVEL)
        press("P1 Button 1", (frame // 5) % 2 == 1)
        press("P1 Button 2", (frame // 7) % 2 == 1)
        press("1 Player Start", (frame % 240) < 4)
        if timer > 0 and timer < 3600 and level < 6 then space:write_u32(LEVEL, 6) end
        if level == FINAL and timer > 0 and timer < 3600 and space:read_u16(CPU_KEYS + 0x1a) == 33 then
            space:write_u32(CPU_KEYS + LIFE, UNKNOWN_FULL)  -- defait le cheat du combat precedent
            for _, b in ipairs({"P1 Button 1", "P1 Button 2", "1 Player Start"}) do press(b, false) end
            dump = frame + 60
        else
            space:write_u8(CPU_LIFE_HI, 0)
        end
    end
    if frame == 60000 then machine:exit() end
end)
