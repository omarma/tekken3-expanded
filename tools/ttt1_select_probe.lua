-- MAME 0.289, tektagt, NVRAM neuf. Aucune donnee de ROM ici.
-- Amene le curseur de selection TTT1 sur un personnage et releve ce qui est
-- surligne : capture d'ecran, RAM complete, et la structure 0x29EF00
-- (moveset +0x10, corps +0x12, son +0x14, 2 x asset +0x16).
--
-- TTT1_PATH : trajet depuis Xiaoyu (L3,C1), lettres U D L R separees par des
-- virgules, ex. "R,R,U,U" (Kunimitsu). Le curseur garde sa position a l'ecran.
-- TTT1_CONFIRM : bouton de validation facultatif ("Start", "Button 1"...),
-- pour les variantes (Angel, Alex) ; la RAM est relevee de nouveau ensuite.
-- TTT1_OUT : prefixe des fichiers produits (defaut "probe").
-- TTT1_MOVESET : cle de moveset imposee au tirage de Tetsujin (0x801293F0 ecrit
-- le moveset tire en 0x801294B8) ; le jeu charge alors ce moveset sur lui.
-- TTT1_INDEX : index de personnage impose au selecteur (8 x code + variante de
-- bouton, table 0x801958C4), pour un personnage sans case (Unknown : 33 x 8).
-- 0x80165C5C range l'index dans 0x29EF0E ; moveset, corps, son et modele en
-- decoulent. Avec TTT1_INDEX, TTT1_MOVESET impose aussi le moveset que le
-- selecteur range (0x80165C90, 0x29EF10) : moveset d'un donneur sur ce corps.
-- Demande MAME lance avec -debug -debugger none.
local machine = manager.machine
local space = machine.devices[":maincpu"].spaces["program"]
local port = machine.ioport.ports[":JVS_PLAYER1"]
local UNLOCK = 0x2fe4fc          -- options liberees dans le temps : tout ouvrir
local KEY = 0x29ef00
local out = os.getenv("TTT1_OUT") or "probe"
local confirm = os.getenv("TTT1_CONFIRM")
if confirm == "" then confirm = nil end
local forced = tonumber(os.getenv("TTT1_MOVESET") or "")
local index = tonumber(os.getenv("TTT1_INDEX") or "")
local names = {U = "P1 Up", D = "P1 Down", L = "P1 Left", R = "P1 Right"}

local steps, t = {}, 2000
for dir in string.gmatch(os.getenv("TTT1_PATH") or "", "[^,%s]+") do
    steps[#steps + 1] = {t, assert(names[dir], "direction inconnue : " .. dir)}
    t = t + 12
end
local look = t + 60
local press = look + 20
local after = press + 90

local function field(name)
    if name == "Start" then return port.fields["1 Player Start"] end
    return assert(port.fields["P1 " .. name], "bouton inconnu : " .. name)
end

local function dump(tag)
    local f = assert(io.open(out .. "-" .. tag .. "-ram.bin", "wb"))
    f:write(space:read_range(0, 0x3fffff, 8)); f:close()
    machine.video:snapshot()
    print(string.format("%s %s asset=%d moveset=%d body=%d son=%d", out, tag,
        space:read_u16(KEY + 0x16) // 2, space:read_u16(KEY + 0x10),
        space:read_u16(KEY + 0x12), space:read_u16(KEY + 0x14)))
end

local frame = 0
ttt1_select_probe = emu.add_machine_frame_notifier(function()
    frame = frame + 1
    space:write_u32(UNLOCK, 0xffffffff)
    if (forced or index) and frame == 1700 then
        if forced then machine.debugger:command(string.format("bpset 801294B8,1,{v0=%x; g}", forced)) end
        if index then machine.debugger:command(string.format("bpset 80165C5C,1,{v0=%x; g}", index)) end
        if index and forced then machine.debugger:command(string.format("bpset 80165C90,1,{v0=%x; g}", forced)) end
        machine.debugger:command("g")
    end
    if frame == 1800 then machine.ioport.ports[":JVS_COIN1"].fields["Coin 1"]:set_value(1) end
    if frame == 1804 then machine.ioport.ports[":JVS_COIN1"].fields["Coin 1"]:set_value(0) end
    if frame == 1860 then port.fields["1 Player Start"]:set_value(1) end
    if frame == 1864 then port.fields["1 Player Start"]:set_value(0) end
    for _, s in ipairs(steps) do
        if frame == s[1] then port.fields[s[2]]:set_value(1) end
        if frame == s[1] + 4 then port.fields[s[2]]:set_value(0) end
    end
    if frame == look then dump("hover") end
    if confirm then
        if frame == press then field(confirm):set_value(1) end
        if frame == press + 4 then field(confirm):set_value(0) end
        if frame == after then dump("confirm") end
    end
    if frame == (confirm and after or look) + 5 then machine:exit() end
end)
