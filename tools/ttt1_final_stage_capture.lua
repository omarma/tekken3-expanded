-- MAME 0.289, tektagt, NVRAM neuf. Aucune donnee de ROM ici.
-- Releve les grands portraits de chargement du stage final de l'Arcade, ou
-- TTT1 envoie celui du boss (Unknown, qui n'a pas de case au selecteur).
-- Arcade a un joueur (Xiaoyu et le partenaire a sa droite). Pendant chaque
-- combat, deux cheats de la base de Pugsy (valables pour TEG2/VER.C1) :
--   - « Select Level » : niveau 0x2FE244 remis a 6 (stage 7) ; gagner ce
--     stage mene au stage final (partir directement du final fait planter) ;
--   - « Player 2/CPU 1 Hit Death » : octet 0x2A0D2A a 0, le premier coup tue.
-- Le joueur 1 frappe en continu et Start passe les ecrans. Comme
-- tools/ttt1_ui_capture.lua, chaque image est interceptee a son envoi en VRAM
-- (GP0 0xA0 puis DMA2), la palette avant l'image.
-- Sortie : ui-uploads.csv (avec le niveau a l'envoi) et ui-NNNN.bin.
local machine = manager.machine
local space = machine.devices[":maincpu"].spaces["program"]
local port = machine.ioport.ports[":JVS_PLAYER1"]
local UNLOCK, LEVEL, CPU_LIFE, FINAL = 0x2fe4fc, 0x2fe244, 0x2a0d2a, 7
local frame, n, gp0, pending, done = 0, 0, {}, nil, nil
local index = assert(io.open("ui-uploads.csv", "w"))
index:write("n,frame,x,y,w,h,file,level\n")

ui_gp0_tap = space:install_write_tap(0x1f801810, 0x1f801813, "ui-gp0", function(offset, data, mask)
    gp0[#gp0 + 1] = data
    if #gp0 > 3 then table.remove(gp0, 1) end
    if #gp0 == 3 and (gp0[1] >> 24) == 0xa0 then
        pending = {gp0[2] & 0xffff, gp0[2] >> 16, gp0[3] & 0xffff, gp0[3] >> 16}
        gp0 = {}
    end
end)

ui_dma_tap = space:install_write_tap(0x1f8010a8, 0x1f8010ab, "ui-dma2", function(offset, data, mask)
    if (data & 0x01000000) == 0 or not pending or ((data >> 9) & 3) ~= 1 then return end
    local madr = space:read_u32(0x1f8010a0) & 0x3fffff
    local x, y, w, h = pending[1], pending[2], pending[3], pending[4]
    pending = nil
    if not ((w == 256 and h == 1) or (w == 76 and h == 256)) or frame < 1700 then return end
    n = n + 1
    local name = string.format("ui-%04d.bin", n)
    local f = io.open(name, "wb"); f:write(space:read_range(madr, madr + w * h * 2 - 1, 8)); f:close()
    local level = space:read_u32(LEVEL)
    index:write(string.format("%d,%d,%d,%d,%d,%d,%s,%d\n", n, frame, x, y, w, h, name, level))
    if w == 76 and level == FINAL and not done then done = frame + 120 end
end)

local steps = {{2060, "P1 Button 1"}, {2120, "P1 Right"}, {2160, "P1 Button 1"}}
ttt1_final_stage = emu.add_machine_frame_notifier(function()
    frame = frame + 1
    space:write_u32(UNLOCK, 0xffffffff)
    local coin = machine.ioport.ports[":JVS_COIN1"].fields["Coin 1"]
    if frame % 600 == 0 then coin:set_value(1) end          -- credits pour un continue
    if frame % 600 == 4 then coin:set_value(0) end
    if frame == 1860 then port.fields["1 Player Start"]:set_value(1) end
    if frame == 1864 then port.fields["1 Player Start"]:set_value(0) end
    for _, s in ipairs(steps) do
        if frame == s[1] then port.fields[s[2]]:set_value(1) end
        if frame == s[1] + 4 then port.fields[s[2]]:set_value(0) end
    end
    local timer = space:read_u32(0x2434e0)                  -- chrono du round, en images
    if frame > 2400 then
        port.fields["P1 Button 1"]:set_value((frame // 5) % 2)
        port.fields["P1 Button 2"]:set_value((frame // 7) % 2)
        port.fields["1 Player Start"]:set_value((frame % 240) < 4 and 1 or 0)
        if timer > 0 and timer < 3600 and space:read_u32(LEVEL) < 6 then space:write_u32(LEVEL, 6) end
        space:write_u8(CPU_LIFE, 0)
    end
    if (done and frame == done) or frame == 30000 then index:close(); machine:exit() end
end)
