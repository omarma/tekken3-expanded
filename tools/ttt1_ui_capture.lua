-- MAME 0.289, tektagt, NVRAM neuf. Aucune donnee de ROM ici.
-- Releve les images d'interface TTT1 d'un personnage au moment ou le jeu les
-- envoie en VRAM (commande GP0 0xA0 puis DMA canal 2 en mode bloc) :
--   - les vignettes de la grille de selection (32 x 32 demi-mots, 8 bits),
--     chacune PRECEDEE de sa palette de 256 couleurs ;
--   - le grand portrait de l'ecran de chargement (76 x 256 demi-mots, 8 bits),
--     lui aussi precede de sa palette ; le premier envoye est celui du
--     premier personnage choisi, donc le notre.
-- Les tampons sont a 0x3EF108 et au-dela : la RAM fait 4 Mio (masque 0x3FFFFF).
--
-- TTT1_PATH, TTT1_CONFIRM : comme tools/ttt1_select_probe.lua. On choisit le
-- personnage (TTT1_CONFIRM ou Poing), puis un partenaire a droite (a gauche si
-- la case de droite est le meme personnage), et on attend le chargement.
-- Sortie : ui-uploads.csv et ui-NNNN.bin dans le dossier courant.
local machine = manager.machine
local space = machine.devices[":maincpu"].spaces["program"]
local port = machine.ioport.ports[":JVS_PLAYER1"]
local UNLOCK, KEY = 0x2fe4fc, 0x29ef00
local index = tonumber(os.getenv("TTT1_INDEX") or "")   -- avec MAME -debug -debugger none
local frame, n, portrait = tonumber(os.getenv("TTT1_FRAME0") or "0"), 0, nil   -- apres -state : trame de la sauvegarde
local gp0, pending = {}, nil
local index = assert(io.open("ui-uploads.csv", "w"))
index:write("n,frame,x,y,w,h,file\n")

local function field(name)
    if name == "Start" then return port.fields["1 Player Start"] end
    return assert(port.fields["P1 " .. name], "bouton inconnu : " .. name)
end

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
    local keep = (w == 256 and h == 1) or (w == 32 and h == 32) or (w == 76 and h == 256)
    if not keep or frame < 1700 then return end
    n = n + 1
    local name = string.format("ui-%04d.bin", n)
    local f = io.open(name, "wb"); f:write(space:read_range(madr, madr + w * h * 2 - 1, 8)); f:close()
    index:write(string.format("%d,%d,%d,%d,%d,%d,%s\n", n, frame, x, y, w, h, name))
    if w == 76 and not portrait then portrait = frame end
end)

local steps, t = {}, 2000
for dir in string.gmatch(os.getenv("TTT1_PATH") or "", "[^,%s]+") do
    local names = {U = "Up", D = "Down", L = "Left", R = "Right"}
    steps[#steps + 1] = {t, assert(names[dir], "direction inconnue : " .. dir)}
    t = t + 12
end
local pick = t + 60
local confirm = os.getenv("TTT1_CONFIRM")
if confirm == "" or not confirm then confirm = "Button 1" end
local mine, partner = nil, pick + 60
steps[#steps + 1] = {pick, confirm}
steps[#steps + 1] = {partner, "Right"}

local done = nil
ttt1_ui_capture = emu.add_machine_frame_notifier(function()
    frame = frame + 1
    space:write_u32(UNLOCK, 0xffffffff)
    if index and frame == 1700 then       -- TTT1_INDEX : personnage sans case (tools/ttt1_select_probe.lua)
        machine.debugger:command(string.format("bpset 80165C5C,1,{v0=%x; g}", index))
        machine.debugger:command("g")
    end
    if frame == 1800 then machine.ioport.ports[":JVS_COIN1"].fields["Coin 1"]:set_value(1) end
    if frame == 1804 then machine.ioport.ports[":JVS_COIN1"].fields["Coin 1"]:set_value(0) end
    if frame == 1860 then port.fields["1 Player Start"]:set_value(1) end
    if frame == 1864 then port.fields["1 Player Start"]:set_value(0) end
    for _, s in ipairs(steps) do
        if frame == s[1] then field(s[2]):set_value(1) end
        if frame == s[1] + 4 then field(s[2]):set_value(0) end
    end
    if frame == pick - 2 then mine = space:read_u16(KEY + 0x16) end
    -- partenaire : meme personnage a droite (bord de ligne) -> deux fois a gauche
    if frame == partner + 30 and space:read_u16(KEY + 0x16) == mine then
        steps[#steps + 1] = {frame + 2, "Left"}; steps[#steps + 1] = {frame + 14, "Left"}
    end
    if frame == partner + 60 then steps[#steps + 1] = {frame + 1, "Button 1"} end
    if portrait and not done then done = portrait + 30 end      -- fin : apres les grands portraits
    if (done and frame == done) or frame == partner + 900 then index:close(); machine:exit() end
end)
