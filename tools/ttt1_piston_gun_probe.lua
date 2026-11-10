-- MAME 0.289, tektagt, NVRAM neuf, -debug -debugger none. Aucune donnee de ROM ici.
-- B139 (GH#66) : Piston Gun Assault (b+2) de Gun Jack, effet de coup fort ou non.
-- Versus : J1 Gun Jack (TTT1_PATH, defaut U,R,R,R depuis Xiaoyu), J2 sa case de depart.
-- Combat lance -> sauvegarde ; chaque essai recharge, place les deux a la distance
-- voulue, J1 joue le coup ; J2 reste neutre (garde haute/moyenne) ou marche vers J1
-- (pas de garde). Points d'arret : hit_impact 0x801208C8 (puissance a0, cote a2) et
-- hit_fx_spawn 0x80120420 (cote a0 ; a3 = 1 : sans vitesse, l'effet fort du cote).
-- TTT1_SHOTS : liste « coup@distance[:f] » (coup : b2, 2, 1, f2... ; :f = J2 avance).
-- Sortie : piston.csv (essai, image, coup/enregistrement J1, enregistrement/vie J2,
-- appels de hit_impact / hit_fx_spawn de l'image).
-- mame tektagt -debug -debugger none -autoboot_script tools/ttt1_piston_gun_probe.lua
--     -video none -sound none -nothrottle -nvram_directory <neuf> (TIPS 219)
local machine = manager.machine
local space = machine.devices[":maincpu"].spaces["program"]
local cpu = machine.devices[":maincpu"]
local port = machine.ioport.ports[":JVS_PLAYER1"]
local p2 = machine.ioport.ports[":JVS_PLAYER2"]
local UNLOCK, TIMER, LIFE, FULL = 0x2fe4fc, 0x2434e0, 0x3d0, 0x76000
local SLOT, SLOTS = 0x1a60, 0x29eef8
local WATCH = tonumber(os.getenv("TTT1_WATCH") or "90")
local SNAP = tonumber(os.getenv("TTT1_SNAP") or "0")
local shots = {}
for s in string.gmatch(os.getenv("TTT1_SHOTS") or "b2@900", "[^,%s]+") do
    local mv, dist, f = string.match(s, "^(%w+)@(%d+)(:?f?)$")
    shots[#shots + 1] = {name = s, mv = mv, dist = tonumber(dist), fwd = f == ":f"}
end
local DIRS = {b = "Left", f = "Right", d = "Down", u = "Up"}

local debugger = machine.debugger
assert(debugger, "lancer MAME avec -debug -debugger none")
cpu.debug:bpset(0x801208C8, "1", 'printf "HI %d %d",a0,a2; g')
cpu.debug:bpset(0x80120420, "1", 'printf "HF %d %d",a0,a3; g')
local seen = 0

local function field(p, name)
    if name == "Start" then return p.fields[(p == port) and "1 Player Start" or "2 Players Start"] end
    return assert(p.fields[((p == port) and "P1 " or "P2 ") .. name], "bouton inconnu : " .. name)
end
local steps, t = {}, 2000
local names = {U = "Up", D = "Down", L = "Left", R = "Right"}
for dir in string.gmatch(os.getenv("TTT1_PATH") or "U,R,R,R", "[^,%s]+") do
    steps[#steps + 1] = {t, port, assert(names[dir])}; t = t + 12
end
steps[#steps + 1] = {t + 60, port, "Button 1"}
steps[#steps + 1] = {t + 120, port, "Right"}
steps[#steps + 1] = {t + 160, port, "Button 1"}
steps[#steps + 1] = {t + 70, p2, "Button 1"}
steps[#steps + 1] = {t + 130, p2, "Right"}
steps[#steps + 1] = {t + 170, p2, "Button 1"}

local function s32(a) local v = space:read_u32(a); return v >= 0x80000000 and v - 0x100000000 or v end
local function hold(p, prefix, list, v) for _, n in ipairs(list) do p.fields[prefix .. n]:set_value(v) end end

local function inputs(mv)
    local dir, buttons = string.match(mv, "^([bfdu]?)(%d+)$")
    local list = {}
    for n in string.gmatch(buttons, "%d") do
        local b = tonumber(n)
        list[#list + 1] = "Button " .. (({1, 2, 4, 5})[b])
    end
    return DIRS[dir], list
end

local frame, phase, at, try = 0, "select", 0, 0
local last_timer, ticks, P1, P2, cur
local out = assert(io.open("piston.csv", "w"))
out:write("try,shot,f,p1move,p1rec,p1frame,p2rec,p2life,dist,hits\n")

ttt1_b139 = emu.add_machine_frame_notifier(function()
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
    -- appels de hit_impact depuis l'image precedente
    local hits = {}
    local log = debugger.consolelog
    for k = seen + 1, #log do
        local w, a, b = string.match(log[k], "(H[IF]) (%-?%d+) (%-?%d+)")
        if a then hits[#hits + 1] = w .. ":" .. a .. "/" .. b end
    end
    seen = #log
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
        print(string.format("b139: P1 block %x, P2 block %x", P1, P2))
        for k = 0, 3 do
            local a = SLOTS + k * SLOT
            print(string.format("slot %d %x: key %04x %04x %04x life %x move %x", k, a, space:read_u16(0x29ef00 + k * 0x20 + 0x10),
                space:read_u16(0x29ef00 + k * 0x20 + 0x12), space:read_u16(0x29ef00 + k * 0x20 + 0x14), space:read_u32(a + LIFE), space:read_u16(a + 0xf8)))
        end
        machine.video:snapshot()
        machine:save("b139"); phase, at = "saved", frame
    end
    if phase ~= "select" and phase ~= "settle" and P1 then
        space:write_u32(P1 + LIFE, FULL)
    end
    if phase == "saved" and frame - at == 5 then phase = "next" end
    if phase == "next" then
        try = try + 1
        if try > #shots then out:close(); print("b139: done"); machine:exit(); phase = "done"; return end
        cur = shots[try]
        machine:load("b139"); phase, at = "wait", frame
    elseif phase == "wait" and frame - at == 2 then
        space:write_u32(P2 + LIFE, FULL)
        local x1, z1, x2, z2 = s32(P1 + 8), s32(P1 + 16), s32(P2 + 8), s32(P2 + 16)
        local dx, dz = x2 - x1, z2 - z1
        local d = math.sqrt(dx * dx + dz * dz)
        local mx, mz, ux, uz = (x1 + x2) / 2, (z1 + z2) / 2, dx / d, dz / d
        space:write_u32(P1 + 8, math.floor(mx - ux * cur.dist / 2) & 0xffffffff); space:write_u32(P1 + 16, math.floor(mz - uz * cur.dist / 2) & 0xffffffff)
        space:write_u32(P2 + 8, math.floor(mx + ux * cur.dist / 2) & 0xffffffff); space:write_u32(P2 + 16, math.floor(mz + uz * cur.dist / 2) & 0xffffffff)
    elseif phase == "wait" and frame - at == 8 then
        cur.dir, cur.buttons = inputs(cur.mv)
        if cur.dir then port.fields["P1 " .. cur.dir]:set_value(1) end
        if cur.fwd then p2.fields["P2 Left"]:set_value(1) end
        phase, at = "dir", frame
    elseif phase == "dir" and frame - at == 2 then
        hold(port, "P1 ", cur.buttons, 1); phase, at = "fire", frame
    elseif phase == "fire" then
        local f = frame - at
        if f == 3 then
            hold(port, "P1 ", cur.buttons, 0)
            if cur.dir then port.fields["P1 " .. cur.dir]:set_value(0) end
        end
        if f == 60 and cur.fwd then p2.fields["P2 Left"]:set_value(0) end
        local x1, z1, x2, z2 = s32(P1 + 8), s32(P1 + 16), s32(P2 + 8), s32(P2 + 16)
        local dist = math.floor(math.sqrt((x2 - x1) ^ 2 + (z2 - z1) ^ 2))
        out:write(string.format("%d,%s,%d,%x,%x,%d,%x,%d,%d,%s\n", try, cur.name, f,
            space:read_u16(P1 + 0xf8), space:read_u32(P1 + 0xb0), space:read_u16(P1 + 0xb4),
            space:read_u32(P2 + 0xb0), space:read_u32(P2 + LIFE), dist, table.concat(hits, " ")))
        if SNAP > 0 and f >= 10 and f < 50 and f % SNAP == 0 then machine.video:snapshot() end
        if f >= WATCH then
            if cur.fwd then p2.fields["P2 Left"]:set_value(0) end
            out:flush(); phase = "next"
        end
    end
end)
