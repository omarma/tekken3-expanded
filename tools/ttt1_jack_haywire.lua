-- MAME 0.289, tektagt, NVRAM neuf. Aucune donnee de ROM ici.
-- Ce que fait un Jack touche par le laser de Devil (« haywire »).
--
-- Mode versus comme tools/ttt1_hit_effect_capture.lua : le joueur 1 prend
-- Devil (TTT1_PATH, defaut R,R,R,R,D depuis Xiaoyu) et le partenaire a sa
-- droite ; le joueur 2 suit TTT1_PATH2 (depuis sa case de depart) et ne fait
-- rien d'autre. Une fois le combat lance, l'etat est sauvegarde ; chaque
-- essai le recharge, replace les deux a TTT1_DIST (2500) et tire
-- TTT1_SHOTS (« inferno », « blaster », separes par des virgules), puis
-- releve image par image les deux combattants : coup +0xF8, enregistrement
-- +0xB0, image +0xB4, vie +0x3D0, racine +0x8 / +0x10.
-- TTT1_SNAP : une capture d'ecran toutes les N images de l'essai (GIF).
-- TTT1_FOLLOW : apres le tir, coups supplementaires du joueur 1, « image:boutons »
-- separes par « ; » (boutons 1..5, ex. « 90:1,2 » : un second Inferno).
-- Sortie : haywire.csv (essai, image, coup/enregistrement/image/vie des deux).
local machine = manager.machine
local space = machine.devices[":maincpu"].spaces["program"]
local port = machine.ioport.ports[":JVS_PLAYER1"]
local p2 = machine.ioport.ports[":JVS_PLAYER2"]
local UNLOCK, TIMER, LIFE, FULL = 0x2fe4fc, 0x2434e0, 0x3d0, 0x76000
local SLOT, SLOTS = 0x1a60, 0x29eef8
local DIST = tonumber(os.getenv("TTT1_DIST") or "2500")
local WATCH = tonumber(os.getenv("TTT1_WATCH") or "300")
local SNAP = tonumber(os.getenv("TTT1_SNAP") or "0")
local SELSNAP = tonumber(os.getenv("TTT1_SELSNAP") or "0")
local BUTTONS = {inferno = {1, 2}, blaster = {4, 5}}
local shots = {}
for s in string.gmatch(os.getenv("TTT1_SHOTS") or "inferno", "[^,%s]+") do shots[#shots + 1] = s end
local follow = {}
for f, b in string.gmatch(os.getenv("TTT1_FOLLOW") or "", "(%d+):([%d,]+)") do
    local list = {}
    for n in string.gmatch(b, "%d") do list[#list + 1] = tonumber(n) end
    follow[#follow + 1] = {tonumber(f), list}
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
steps[#steps + 1] = {t + 60, port, "Button 1"}
steps[#steps + 1] = {t + 120, port, "Right"}
steps[#steps + 1] = {t + 160, port, "Button 1"}
steps[#steps + 1] = {t + 70, p2, os.getenv("TTT1_CONFIRM2") or "Button 1"}
steps[#steps + 1] = {t + 130, p2, "Right"}
steps[#steps + 1] = {t + 170, p2, "Button 1"}

local function s32(a) local v = space:read_u32(a); return v >= 0x80000000 and v - 0x100000000 or v end
local function press(list, v) for _, n in ipairs(list) do port.fields["P1 Button " .. n]:set_value(v) end end

local frame, phase, at, try = 0, "select", 0, 0
local last_timer, ticks, P1, P2, cur
local out = assert(io.open("haywire.csv", "w"))
out:write("try,shot,f,p1move,p1rec,p1frame,p2move,p2rec,p2frame,p2life,p1x,p1z,p2x,p2z,laser\n")

ttt1_jack_haywire = emu.add_machine_frame_notifier(function()
    frame = frame + 1
    space:write_u32(UNLOCK, 0xffffffff)
    local coin = machine.ioport.ports[":JVS_COIN1"].fields["Coin 1"]
    if frame == 1800 or frame == 1830 then coin:set_value(1) end
    if frame == 1804 or frame == 1834 then coin:set_value(0) end
    if frame == 1860 then port.fields["1 Player Start"]:set_value(1) end
    if frame == 1864 then port.fields["1 Player Start"]:set_value(0) end
    if frame == 1900 then p2.fields["2 Players Start"]:set_value(1) end
    if frame == 1904 then p2.fields["2 Players Start"]:set_value(0) end
    if SELSNAP > 0 and frame == SELSNAP then machine.video:snapshot() end
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
        print(string.format("haywire: P1 block %x, P2 block %x", P1, P2))
        for k = 0, 3 do
            local a = SLOTS + k * SLOT
            print(string.format("slot %d %x: key %04x %04x %04x life %x move %x", k, a, space:read_u16(0x29ef00 + k * 0x20 + 0x10),
                space:read_u16(0x29ef00 + k * 0x20 + 0x12), space:read_u16(0x29ef00 + k * 0x20 + 0x14), space:read_u32(a + LIFE), space:read_u16(a + 0xf8)))
        end
        machine.video:snapshot()
        machine:save("haywire"); phase, at = "saved", frame
    end
    if phase ~= "select" and phase ~= "settle" and P1 then space:write_u32(P1 + LIFE, FULL) end
    if phase == "saved" and frame - at == 5 then phase = "next" end
    if phase == "next" then
        try = try + 1
        if try > #shots then out:close(); print("haywire: done"); machine:exit(); phase = "done"; return end
        cur = shots[try]
        machine:load("haywire"); phase, at = "wait", frame
    elseif phase == "wait" and frame - at == 2 then
        local x1, z1, x2, z2 = s32(P1 + 8), s32(P1 + 16), s32(P2 + 8), s32(P2 + 16)
        local dx, dz = x2 - x1, z2 - z1
        local d = math.sqrt(dx * dx + dz * dz)
        local mx, mz, ux, uz = (x1 + x2) / 2, (z1 + z2) / 2, dx / d, dz / d
        space:write_u32(P1 + 8, math.floor(mx - ux * DIST / 2) & 0xffffffff); space:write_u32(P1 + 16, math.floor(mz - uz * DIST / 2) & 0xffffffff)
        space:write_u32(P2 + 8, math.floor(mx + ux * DIST / 2) & 0xffffffff); space:write_u32(P2 + 16, math.floor(mz + uz * DIST / 2) & 0xffffffff)
    elseif phase == "wait" and frame - at == 8 then
        press(BUTTONS[cur], 1); phase, at = "fire", frame
    elseif phase == "fire" then
        local f = frame - at
        if f == 3 then press(BUTTONS[cur], 0) end
        for _, fo in ipairs(follow) do
            if f == fo[1] then press(fo[2], 1) end
            if f == fo[1] + 3 then press(fo[2], 0) end
        end
        out:write(string.format("%d,%s,%d,%x,%x,%d,%x,%x,%d,%d,%d,%d,%d,%d,%d\n", try, cur, f,
            space:read_u16(P1 + 0xf8), space:read_u32(P1 + 0xb0), space:read_u16(P1 + 0xb4),
            space:read_u16(P2 + 0xf8), space:read_u32(P2 + 0xb0), space:read_u16(P2 + 0xb4), space:read_u32(P2 + LIFE),
            s32(P1 + 8), s32(P1 + 16), s32(P2 + 8), s32(P2 + 16), space:read_u16(0x242f58)))
        if SNAP > 0 and f % SNAP == 0 then machine.video:snapshot() end
        if f >= WATCH then out:flush(); phase = "next" end
    end
end)
