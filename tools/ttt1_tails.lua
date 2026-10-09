-- MAME 0.289, tektagt, NVRAM neuf. Aucune donnee de ROM ici.
-- Queues de TTT1 (Roger, Alex, Armor King) : la rotation que le solveur des os d'accessoire
-- (0x80163B68, parametres par emplacement de modele en 0x8019D674, 6 os 18..23) ecrit dans
-- l'acteur a +0xA58 + 80 * os, image par image. Derive de tools/ttt1_hands.lua (meme
-- parcours du selecteur). Le joueur 1 reste immobile TTT1_IDLE images, puis joue TTT1_SEQ :
-- pas « touche:images » separes par des espaces (U saut, R avance, L recule, N rien, 1..5
-- boutons), chaque touche tenue le nombre d'images donne. Sortie : tails.csv (image, pas,
-- os, les 9 termes de la matrice en 4096e, y du joueur) et modeles.txt.
--
-- Meme parcours que tools/ttt1_jack_haywire.lua (TTT1_PATH : chemin du joueur 1
-- depuis Xiaoyu, TTT1_PATH2 : celui du joueur 2). Une fois le combat lance, les
-- modeles 3DMK en RAM sont retrouves (« 3DMK » en +8, 30 lignes en +0) ; pour chaque
-- ligne qui porte une table de poses (mot 13), une ecriture-espion releve chaque ecriture du
-- pointeur de positions (mot 12) : image, indice de pose dans la table, adresse de
-- l'instruction qui ecrit. Le joueur 1 reste immobile TTT1_IDLE images, puis enchaine
-- TTT1_SEQ (boutons « 1 », « 2 », « 3 », « 4 », « 1,2 » separes par des espaces, un toutes
-- les 90 images). Sortie : hands.csv (modele, ligne, image, indice, pc) et modeles.txt.
local machine = manager.machine
local cpu = machine.devices[":maincpu"]
local space = cpu.spaces["program"]
local port = machine.ioport.ports[":JVS_PLAYER1"]
local p2 = machine.ioport.ports[":JVS_PLAYER2"]
local UNLOCK, TIMER, LIFE, FULL = 0x2fe4fc, 0x2434e0, 0x3d0, 0x76000
local SLOT, SLOTS = 0x1a60, 0x29eef8
local IDLE = tonumber(os.getenv("TTT1_IDLE") or "120")
local seq = {}
for k, n in string.gmatch(os.getenv("TTT1_SEQ") or "U:8 N:70 U:8 N:70 R:90 N:40 L:60 N:40", "(%w+):(%d+)") do
    seq[#seq + 1] = {k, tonumber(n)}
end

local function field(p, name)
    if name == "Start" then return p.fields[(p == port) and "1 Player Start" or "2 Players Start"] end
    return assert(p.fields[((p == port) and "P1 " or "P2 ") .. name], "bouton inconnu : " .. name)
end
local steps, t = {}, 2000
local names = {U = "Up", D = "Down", L = "Left", R = "Right"}
for dir in string.gmatch(os.getenv("TTT1_PATH") or "R,R,R,R,D", "[^,%s]+") do
    steps[#steps + 1] = {t, port, assert(names[dir])}; t = t + 12
end
local t2 = 2000
for dir in string.gmatch(os.getenv("TTT1_PATH2") or "", "[^,%s]+") do
    steps[#steps + 1] = {t2 + 6, p2, assert(names[dir])}; t2 = t2 + 12
end
t = math.max(t, t2)
local CONFIRM1 = os.getenv("TTT1_CONFIRM") or "Button 1"
steps[#steps + 1] = {t + 60, port, CONFIRM1}
steps[#steps + 1] = {t + 120, port, "Right"}
steps[#steps + 1] = {t + 160, port, CONFIRM1}
steps[#steps + 1] = {t + 70, p2, os.getenv("TTT1_CONFIRM2") or "Button 1"}
steps[#steps + 1] = {t + 130, p2, "Right"}
steps[#steps + 1] = {t + 170, p2, "Button 1"}

local function s32(a) local v = space:read_u32(a); return v >= 0x80000000 and v - 0x100000000 or v end

local frame, phase, at = 0, "select", 0
local last_timer, ticks, P1, P2
local out = assert(io.open("tails.csv", "w"))
out:write("frame,step,key,bone,m00,m01,m02,m10,m11,m12,m20,m21,m22,y,param\n")
local info = assert(io.open("modeles.txt", "w"))
local names2 = {U = "Up", D = "Down", L = "Left", R = "Right"}
local function s16(v) return v >= 0x8000 and v - 0x10000 or v end
local function hold(k, v)
    if names2[k] then port.fields["P1 " .. names2[k]]:set_value(v)
    elseif k:match("^%d$") then port.fields["P1 Button " .. k]:set_value(v) end
end
local step, step_at = 0, 0
local function sample()
    for bone = 18, 22 do
        local a = P1 + 0xa58 + 80 * bone
        local m = {}
        for i = 0, 8 do m[#m + 1] = s16(space:read_u16(a + 2 * i)) end
        local key = seq[step] and seq[step][1] or "-"
        out:write(string.format("%d,%d,%s,%d,%s,%d,%x\n", frame - at, step, key, bone, table.concat(m, ","),
            s32(P1 + 0xb30), space:read_u32(P1 + 0x12d4 + 4 * (bone - 18))))
    end
end
ttt1_tails = emu.add_machine_frame_notifier(function()
    frame = frame + 1
    space:write_u32(UNLOCK, 0xffffffff)
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
    local timer = space:read_u32(TIMER)
    if phase == "select" and frame > 2400 and timer > 0 and timer < 3600 then
        if last_timer and timer ~= last_timer then ticks = (ticks or 0) + 1 end
        last_timer = timer
        if (ticks or 0) >= 30 then phase, at = "settle", frame end
    end
    if phase == "settle" then
        local found = {}
        for k = 0, 3 do
            local a = SLOTS + k * SLOT
            if space:read_u32(a + LIFE) > 0 and s32(a + 0xb30) < -900 then found[k % 2] = found[k % 2] or a end
        end
        if not (found[0] and found[1]) then return end
        P1, P2 = found[0], found[1]
        info:write(string.format("P1 block %x P2 block %x frame %d model slot %d\n", P1, P2, frame, space:read_u16(P1 + 0x1e)))
        machine.video:snapshot()
        phase, at = "run", frame
    end
    if phase ~= "run" then return end
    space:write_u32(P1 + LIFE, FULL); space:write_u32(P2 + LIFE, FULL)
    sample()
    local f = frame - at
    if f < IDLE then return end
    if step == 0 or f - step_at >= seq[step][2] then
        if step > 0 then hold(seq[step][1], 0) end
        step, step_at = step + 1, f
        if step > #seq then out:close(); info:close(); machine:exit(); phase = "done"; return end
        hold(seq[step][1], 1)
        if seq[step][1] == "U" then machine.video:snapshot() end
    end
end)
