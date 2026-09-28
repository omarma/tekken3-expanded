-- MAME 0.289, tektagt, NVRAM neuf. Aucune donnee de ROM ici.
-- Quand et comment le CPU fait basculer Unknown d'un moveset a l'autre.
-- Arcade a un joueur, comme tools/ttt1_final_stage_capture.lua : pendant
-- les combats, niveau 0x2FE244 remis a 6 et mort en un coup du CPU
-- (0x2A0D2A = 0), jusqu'au stage final (niveau 7) ou Unknown est le boss.
-- La, une sauvegarde d'etat (machine:save) fige le debut du combat final ;
-- chaque essai en repart (machine:load) et dure TRY images, ou jusqu'a ce
-- que le jeu quitte le stage final (entre deux rounds, le corps du bloc du
-- CPU vaut brievement autre chose que 33 : ne pas s'y fier). Les essais tournent entre trois modes : idle
-- (joueur 1 immobile), attack (joueur 1 attaque, rythme propre a l'essai),
-- drain (joueur 1 immobile, Unknown perd 1/16 de sa vie toutes les 300
-- images, sans coup : vie perdue ou coups recus ?). Vies : u32 en +0x3D0 du
-- bloc de cles (tools/ttt1_life_probe.lua) ; Unknown garde au moins 60 %,
-- le joueur 1 au plus 50 %, pour que le combat dure.
-- Un point d'arret sur le tirage de la bascule (0x80101198, TIPS.md
-- section 27 ; `-debug -debugger none`) horodate chaque bascule :
-- unknown-draws.csv (essai, mode, image dans l'essai, vie d'Unknown, temps
-- depuis sa derniere perte de vie et depuis la bascule precedente) ;
-- unknown-tries.csv : une ligne par essai (images passees face a Unknown).
local machine = manager.machine
local space = machine.devices[":maincpu"].spaces["program"]
local port = machine.ioport.ports[":JVS_PLAYER1"]
local UNLOCK, LEVEL, CPU_LIFE_HI, TIMER, FINAL = 0x2fe4fc, 0x2fe244, 0x2a0d2a, 0x2434e0, 7
local P1_KEYS, CPU_KEYS = 0x29eef8, 0x29eef8 + 0x1a60
local LIFE, UNKNOWN_FULL, P1_FULL = 0x3d0, 0x104000, 0x76000
local TRY = tonumber(os.getenv("TTT1_TRY_FRAMES") or "3000")
local TRIES = tonumber(os.getenv("TTT1_TRIES") or "30")
local MODES = {"idle", "attack", "drain"}
local frame, saved, try, t0, loading = 0, false, 0, nil, false
local last_life, last_hit, last_draw, seen_log, on_screen = nil, nil, nil, 0, 0
local draws = assert(io.open("unknown-draws.csv", "w"))
draws:write("try,mode,t,moveset_before,cpu_life,since_cpu_hit,since_last_draw\n")
local tries = assert(io.open("unknown-tries.csv", "w"))
tries:write("try,mode,frames,unknown_frames,end_body,end_level\n")
local debugger = machine.debugger
if debugger then machine.devices[":maincpu"].debug:bpset(0x80101198, "1", 'printf "DRAW"; g') end
local function press(name, on) port.fields[name]:set_value(on and 1 or 0) end
local function release() for _, b in ipairs({"P1 Button 1", "P1 Button 2", "P1 Right", "P1 Left", "1 Player Start"}) do press(b, false) end end
local function close() draws:close(); tries:close(); machine:exit() end
local steps = {{2060, "P1 Button 1"}, {2120, "P1 Right"}, {2160, "P1 Button 1"}}
local function start_try()
    try = try + 1
    if try > TRIES then close(); return end
    t0, last_life, last_hit, last_draw, on_screen = frame, nil, nil, nil, 0
    if debugger then seen_log = #debugger.consolelog end
end
ttt1_unknown_switches = emu.add_machine_frame_notifier(function()
    frame = frame + 1
    space:write_u32(UNLOCK, 0xffffffff)
    local timer, level = space:read_u32(TIMER), space:read_u32(LEVEL)
    local body = space:read_u16(CPU_KEYS + 0x1a)
    if not saved then
        local coin = machine.ioport.ports[":JVS_COIN1"].fields["Coin 1"]
        if frame % 600 == 0 then coin:set_value(1) end
        if frame % 600 == 4 then coin:set_value(0) end
        if frame == 1860 then press("1 Player Start", true) end
        if frame == 1864 then press("1 Player Start", false) end
        for _, s in ipairs(steps) do
            if frame == s[1] then press(s[2], true) end
            if frame == s[1] + 4 then press(s[2], false) end
        end
        if frame > 2400 then
            press("P1 Button 1", (frame // 5) % 2 == 1)
            press("P1 Button 2", (frame // 7) % 2 == 1)
            press("1 Player Start", (frame % 240) < 4)
            if timer > 0 and timer < 3600 and level < 6 then space:write_u32(LEVEL, 6) end
            if level == FINAL and timer > 0 and timer < 3600 and body == 33 then
                space:write_u32(CPU_KEYS + LIFE, UNKNOWN_FULL)       -- defait le cheat du combat precedent
                release(); machine:save("final"); saved = true; start_try()
            else
                space:write_u8(CPU_LIFE_HI, 0)
            end
        end
        if frame == 60000 then close() end
        return
    end
    if loading then loading = false; start_try(); return end
    local t = frame - t0
    local mode = MODES[(try - 1) % 3 + 1]
    if body == 33 then on_screen = on_screen + 1 end
    if t >= TRY or (t > 120 and level ~= FINAL) then
        tries:write(string.format("%d,%s,%d,%d,%d,%d\n", try, mode, t, on_screen, body, level)); tries:flush()
        release(); machine:load("final"); loading = true; return
    end
    if space:read_u32(P1_KEYS + LIFE) > P1_FULL // 2 then space:write_u32(P1_KEYS + LIFE, P1_FULL // 2) end
    local life = space:read_u32(CPU_KEYS + LIFE)
    if body == 33 and life > 0 and life < UNKNOWN_FULL * 3 // 5 then space:write_u32(CPU_KEYS + LIFE, UNKNOWN_FULL * 3 // 5) end
    if mode == "drain" and body == 33 and t % 300 == 150 then
        life = space:read_u32(CPU_KEYS + LIFE)
        space:write_u32(CPU_KEYS + LIFE, math.max(0, life - UNKNOWN_FULL // 16))
    end
    if mode == "attack" then
        local a, b, c = 4 + try % 5, 6 + try % 7, 60 + 17 * (try % 6)
        press("P1 Button 1", (t // a) % 2 == 1)
        press("P1 Button 2", (t // b) % 2 == 1)
        press("P1 Right", (t // c) % 2 == 1)
    else
        release()
    end
    life = space:read_u32(CPU_KEYS + LIFE)
    if body == 33 and last_life and life < last_life then last_hit = frame end
    last_life = body == 33 and life or nil
    if debugger then
        local log = debugger.consolelog
        for i = seen_log + 1, #log do
            if log[i]:find("DRAW") then
                draws:write(string.format("%d,%s,%d,%d,%d,%d,%d\n", try, mode, t, space:read_u16(CPU_KEYS + 0x18), life,
                                          last_hit and frame - last_hit or -1, last_draw and frame - last_draw or -1))
                draws:flush(); last_draw = frame
            end
        end
        seen_log = #log
    end
end)
