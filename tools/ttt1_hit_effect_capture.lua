-- MAME 0.289, tektagt, NVRAM neuf. Aucune donnee de ROM ici.
-- Releve la VRAM de TTT1 une fois le combat charge, pour l'effet de coup fort
-- propre au personnage (planche 4 x 4 d'images 64 x 64, 4 bits) : le joueur 1
-- la recoit en page (512, 256), palette en (512, 64).
--
-- Mode versus : le joueur 2 rejoint, prend le personnage sous son curseur et
-- ne fait rien d'autre. TTT1_PATH et TTT1_CONFIRM comme
-- tools/ttt1_select_probe.lua ; partenaire du joueur 1 a droite.
-- Sortie : hit-vram.bin (VRAM 1024 x 1024, 16 bits) et une capture d'ecran.
local machine = manager.machine
local space = machine.devices[":maincpu"].spaces["program"]
local port = machine.ioport.ports[":JVS_PLAYER1"]
local p2 = machine.ioport.ports[":JVS_PLAYER2"]
local UNLOCK = 0x2fe4fc
local index = tonumber(os.getenv("TTT1_INDEX") or "")   -- avec MAME -debug -debugger none
local confirm = os.getenv("TTT1_CONFIRM")
if confirm == nil or confirm == "" then confirm = "Button 1" end

local function field(p, name)
    if name == "Start" then return p.fields[(p == port) and "1 Player Start" or "2 Players Start"] end
    return assert(p.fields[((p == port) and "P1 " or "P2 ") .. name], "bouton inconnu : " .. name)
end

local steps, t = {}, 2000
local names = {U = "Up", D = "Down", L = "Left", R = "Right"}
for dir in string.gmatch(os.getenv("TTT1_PATH") or "", "[^,%s]+") do
    steps[#steps + 1] = {t, port, assert(names[dir], "direction inconnue : " .. dir)}
    t = t + 12
end
steps[#steps + 1] = {t + 60, port, confirm}
steps[#steps + 1] = {t + 120, port, "Right"}
steps[#steps + 1] = {t + 160, port, "Button 1"}
steps[#steps + 1] = {t + 70, p2, "Button 1"}
steps[#steps + 1] = {t + 130, p2, "Right"}
steps[#steps + 1] = {t + 170, p2, "Button 1"}
local dump = t + 1300

local frame = 0
ttt1_hit_effect = emu.add_machine_frame_notifier(function()
    frame = frame + 1
    space:write_u32(UNLOCK, 0xffffffff)
    if index and frame == 1700 then       -- TTT1_INDEX : personnage sans case (tools/ttt1_select_probe.lua)
        machine.debugger:command(string.format("bpset 80165C5C,1,{v0=%x; g}", index))
        machine.debugger:command("g")
    end
    local coin = machine.ioport.ports[":JVS_COIN1"].fields["Coin 1"]
    if frame == 1800 or frame == 1830 then coin:set_value(1) end
    if frame == 1804 or frame == 1834 then coin:set_value(0) end
    if frame == 1860 then port.fields["1 Player Start"]:set_value(1) end
    if frame == 1864 then port.fields["1 Player Start"]:set_value(0) end
    if frame == 1900 then p2.fields["2 Players Start"]:set_value(1) end
    if frame == 1904 then p2.fields["2 Players Start"]:set_value(0) end
    for _, s in ipairs(steps) do
        if frame == s[1] then field(s[2], s[3]):set_value(1) end
        if frame == s[1] + 4 then field(s[2], s[3]):set_value(0) end
    end
    if frame == dump then
        local vram = emu.item(machine.devices[":gpu"].items["0/p_vram"])
        local f = assert(io.open("hit-vram.bin", "wb"))
        f:write(vram:read_block(0, vram.count * vram.size)); f:close()
        machine.video:snapshot()
        machine:exit()
    end
end)
