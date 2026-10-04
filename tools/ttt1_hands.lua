-- MAME 0.289, tektagt, NVRAM neuf. Aucune donnee de ROM ici.
-- Poses de main de TTT1 : comment l'arcade choisit la variante de chaque main.
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
local IDLE = tonumber(os.getenv("TTT1_IDLE") or "240")
local FUZZ = tonumber(os.getenv("TTT1_FUZZ") or "0")
local seq = {}
for s in string.gmatch(os.getenv("TTT1_SEQ") or "1 2 3 4 1,2", "[^%s]+") do seq[#seq + 1] = s end

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
local function press(list, v) for _, n in ipairs(list) do port.fields["P1 Button " .. n]:set_value(v) end end

local frame, phase, at = 0, "select", 0
local last_timer, ticks, P1, P2
local out = assert(io.open("hands.csv", "w"))
out:write("model,row,frame,index,pc,data,entry0,p1move,p1rec,p1frame\n")
local info = assert(io.open("modeles.txt", "w"))
local taps = {}

local last, watched = {}, {}
local function install(base)
    for r = 0, 29 do
        local row = base + 24 + 56 * r
        local tbl = space:read_u32(row + 52) & 0x3fffff
        if tbl > 2 then
            local e0 = space:read_u32(tbl) & 0x3fffff
            local stride = (space:read_u32(tbl + 4) & 0x3fffff) - e0
            info:write(string.format("model %x row %d w12 %x(=%x) table %x e0 %x stride %x\n", base, r, row + 48, space:read_u32(row + 48), tbl, e0, stride))
            watched[#watched + 1] = {base = base, row = r, w12 = row + 48, e0 = e0, stride = stride}
        end
    end
end
local function poll()
    for _, w in ipairs(watched) do
        local v = space:read_u32(w.w12) & 0x3fffff
        local idx = (v - w.e0) // w.stride
        local key = w.base .. "_" .. w.row
        if last[key] ~= idx then
            last[key] = idx
            out:write(string.format("%x,%d,%d,%d,%x,%x,%x,%x,%x,%d\n", w.base, w.row, frame, idx, 0, v, w.e0, P1 and space:read_u16(P1 + 0xf8) or 0, P1 and space:read_u32(P1 + 0xb0) or 0, P1 and space:read_u16(P1 + 0xb4) or 0))
        end
    end
end

ttt1_hands = emu.add_machine_frame_notifier(function()
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
        -- modeles 3DMK en RAM (4 Mo)
        local bases = {}
        for a = 0, 0x3ffff0, 4 do
            if space:read_u32(a + 8) == 0x4B4D4433 and space:read_u32(a) == 30 then bases[#bases + 1] = a end
        end
        info:write(string.format("P1 block %x P2 block %x frame %d\n", P1, P2, frame))
        for _, b in ipairs(bases) do
            install(b)
            for _, who in ipairs({{"P1", P1}, {"P2", P2}}) do
                for o = 0, SLOT - 4, 4 do
                    local v = space:read_u32(who[2] + o)
                    if v == (b | 0x80000000) or v == b then info:write(string.format("model %x referenced by %s +%x\n", b, who[1], o)) end
                end
            end
        end
        machine.video:snapshot()
        phase, at = "idle", frame
    end
    if phase ~= "select" and phase ~= "settle" and P1 then space:write_u32(P1 + LIFE, FULL); space:write_u32(P2 + LIFE, FULL) end
    if #watched > 0 then poll() end
    if phase == "idle" and frame - at == IDLE then phase, at = "seq", frame end
    if phase == "seq" and FUZZ > 0 then
        local f = frame - at
        if f >= FUZZ then out:close(); info:close(); machine:exit(); phase = "done"; return end
        if f % 20 == 0 then
            for _, d in ipairs({"Up", "Down", "Left", "Right"}) do port.fields["P1 " .. d]:set_value(0) end
            for n = 1, 5 do port.fields["P1 Button " .. n]:set_value(0) end
            local dirs = {"Up", "Down", "Left", "Right"}
            if math.random() < 0.6 then port.fields["P1 " .. dirs[math.random(4)]]:set_value(1) end
            if math.random() < 0.3 then port.fields["P1 " .. dirs[math.random(4)]]:set_value(1) end
            for n = 1, 5 do if math.random() < 0.35 then port.fields["P1 Button " .. n]:set_value(1) end end
        end
        if f % 600 == 0 then machine.video:snapshot() end
        return
    end
    if phase == "seq" then
        local f = frame - at
        local k = f // 90 + 1
        if k > #seq then out:close(); info:close(); machine:exit(); phase = "done"; return end
        local list = {}
        for n in string.gmatch(seq[k], "%d") do list[#list + 1] = tonumber(n) end
        if f % 90 == 5 then press(list, 1) end
        if f % 90 == 8 then press(list, 0) end
        if f % 90 == 40 then machine.video:snapshot() end
    end
end)
