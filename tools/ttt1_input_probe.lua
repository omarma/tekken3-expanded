-- MAME 0.289, tektagt, NVRAM neuf. Aucune donnee de ROM ici.
-- Joue des entrees de manette au joueur 1 en combat et releve, image par
-- image, le coup qu'il joue : pour comparer un lien de l'import a l'arcade
-- (tools/ttt1/moveset_check.py try, meme notation).
--
-- Mode versus comme tools/ttt1_hit_effect_capture.lua (TTT1_PATH,
-- TTT1_CONFIRM) ; le joueur 2 prend le personnage sous son curseur et ne fait
-- rien (immobile, il garde).
-- TTT1_NEUTRAL : adresse (hex) de l'enregistrement neutre du joueur 1
-- (meta[neutral][1] du paquet de combat). Au debut du combat, tous les mots
-- de la RAM qui la contiennent sont suivis : l'un d'eux est l'enregistrement
-- courant du joueur 1.
-- TTT1_INPUTS : entrees separees par « ; », chacune « f:2,n:2,f+24:6 »
-- (pave : f b u d df db uf ub n, boutons 1..4 = LP RP LK RK, puis : images),
-- joueur 1 tourne vers la droite. TTT1_APPROACH : images de marche avant
-- (droite tenue) avant chaque entree, 0 par defaut. TTT1_DELAY : images
-- d'attente apres le retour au neutre.
-- TTT1_BACKWARD : adresses (hex, virgules) des enregistrements de pas
-- arriere : si droite tenue y mene, le joueur 1 est tourne vers la gauche et
-- gauche et droite sont echangees (Ganryu, versus : J1 a droite).
-- Enregistrement courant du joueur 1 : 0x8029EFA0 (precedent : 0x802A094C),
-- releve le 2026-09-26 ; les autres mots trouves sont des historiques.
-- Sortie : input-probe.csv (entree, image, adresse, valeur), input-probe.txt
-- (adresses trouvees).
local machine = manager.machine
local space = machine.devices[":maincpu"].spaces["program"]
local port = machine.ioport.ports[":JVS_PLAYER1"]
local p2 = machine.ioport.ports[":JVS_PLAYER2"]
local UNLOCK = 0x2fe4fc
local confirm = os.getenv("TTT1_CONFIRM")
if confirm == nil or confirm == "" then confirm = "Button 1" end
local neutral = tonumber(assert(os.getenv("TTT1_NEUTRAL"), "TTT1_NEUTRAL manquant"), 16)
local approach = tonumber(os.getenv("TTT1_APPROACH") or "0")
local delay = tonumber(os.getenv("TTT1_DELAY") or "20")
local CURRENT = 0x8029efa0
local backward = {}
for a in string.gmatch(os.getenv("TTT1_BACKWARD") or "", "[^,%s]+") do backward[tonumber(a, 16)] = true end
local mirror = nil

local function field(p, name)
    if name == "Start" then return p.fields[(p == port) and "1 Player Start" or "2 Players Start"] end
    return assert(p.fields[((p == port) and "P1 " or "P2 ") .. name], "bouton inconnu : " .. name)
end

-- Selection, comme la capture de l'effet de coup.
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
local scan_at = t + 1300

-- Entrees : liste de {images, {champs}}.
local PAD = {f = {"Right"}, b = {"Left"}, u = {"Up"}, d = {"Down"}, n = {},
             df = {"Down", "Right"}, db = {"Down", "Left"}, uf = {"Up", "Right"}, ub = {"Up", "Left"}}
local BUTTON = {["1"] = "Button 1", ["2"] = "Button 2", ["3"] = "Button 4", ["4"] = "Button 5"}
local inputs = {}
for text in string.gmatch(os.getenv("TTT1_INPUTS") or "", "[^;]+") do
    local seq = {text = (string.gsub(text, ",", " "))}
    for tok in string.gmatch(text, "[^,]+") do
        local keys, n = string.match(tok, "^%s*([^:]+):?(%d*)%s*$")
        local d, b = string.match(keys, "^([a-z]*)%+?([0-9]*)$")
        local held = {}
        for _, k in ipairs(assert(PAD[d], "direction inconnue : " .. d)) do held[#held + 1] = k end
        for c in string.gmatch(b, "%d") do held[#held + 1] = assert(BUTTON[c], "bouton inconnu : " .. c) end
        seq[#seq + 1] = {tonumber(n) or 2, held}
    end
    inputs[#inputs + 1] = seq
end

local ALL = {"Up", "Down", "Left", "Right", "Button 1", "Button 2", "Button 4", "Button 5"}
local function hold(list)
    local on = {}
    for _, k in ipairs(list) do
        if mirror and k == "Left" then k = "Right" elseif mirror and k == "Right" then k = "Left" end
        on[k] = true
    end
    for _, k in ipairs(ALL) do field(port, k):set_value(on[k] and 1 or 0) end
end

local out = assert(io.open("input-probe.csv", "w"))
out:write("input,frame,address,value\n")
local slots, last = {}, {}
local frame, stage, index, t0, plan = 0, "select", 0, 0, nil

local function scan()
    local data = space:read_range(0x80000000, 0x803fffff, 8)
    local found = {}
    local packed = string.pack("<I4", neutral)
    local pos = 1
    while true do
        local k = string.find(data, packed, pos, true)
        if not k then break end
        if (k - 1) % 4 == 0 then found[#found + 1] = 0x80000000 + k - 1 end
        pos = k + 1
    end
    return found
end

-- TTT1_EXTRA : autres mots (hex, virgules) relevés chaque image (positions).
local extra = {}
for a in string.gmatch(os.getenv("TTT1_EXTRA") or "", "[^,%s]+") do extra[#extra + 1] = tonumber(a, 16) end
local function log(tag, rel)
    for _, a in ipairs(extra) do
        local v = space:read_u32(a)
        if v ~= last[a] then
            out:write(string.format("%s,%d,%08x,%08x\n", tag, rel, a, v))
            last[a] = v
        end
    end
    for _, a in ipairs(slots) do
        local v = space:read_u32(a)
        if v ~= last[a] then
            out:write(string.format("%s,%d,%08x,%08x\n", tag, rel, a, v))
            last[a] = v
        end
    end
end

local function at_neutral()
    for _, a in ipairs(slots) do if space:read_u32(a) == neutral then return true end end
    return false
end

ttt1_input_probe = emu.add_machine_frame_notifier(function()
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
    if stage == "select" and frame == scan_at then
        slots = scan()
        local known = false
        for _, a in ipairs(slots) do known = known or a == CURRENT end
        if known then slots = {CURRENT, 0x802a094c} end
        local f = assert(io.open("input-probe.txt", "w"))
        for _, a in ipairs(slots) do f:write(string.format("%08x\n", a)) end
        f:close()
        stage, t0 = "fight", frame
    elseif stage == "fight" then
        log("start", frame - t0)
        -- Round call over: the first input once player 1 is free.
        if frame - t0 > 300 then stage, index = "next", 0 end
    elseif stage == "next" then
        index = index + 1
        if index > #inputs then
            out:close(); machine.video:snapshot(); machine:exit(); return
        end
        -- Facing again before each input: a throw may swap the sides.
        stage, t0, mirror = "settle", frame, nil
    elseif stage == "settle" then
        hold({})
        if at_neutral() and frame - t0 > delay or frame - t0 > 600 then
            stage, t0 = "approach", frame
        end
    elseif stage == "approach" then
        if mirror == nil then
            -- Which way is forward: right held a few frames, then its record.
            hold({"Right"})
            if frame - t0 >= 6 then
                mirror = backward[space:read_u32(CURRENT)] == true
                out:write(string.format("facing,%d,mirror,%08x\n", mirror and 1 or 0, space:read_u32(CURRENT)))
                hold({}); stage, t0 = "settle", frame
            end
        elseif frame - t0 < approach then hold({"Right"}) else
            hold({}); stage, t0, plan = "wait", frame, nil
        end
    elseif stage == "wait" then
        if frame - t0 >= 10 then
            -- Planned frames of the input from here.
            plan, t0 = {}, frame
            local at = 0
            for _, s in ipairs(inputs[index]) do
                for i = 1, s[1] do plan[at + i] = s[2] end
                at = at + s[1]
            end
            plan.length = at
            stage = "play"
            out:write(string.format("%s,0,input,%d\n", inputs[index].text, index))
        end
    end
    if stage == "play" then
        local rel = frame - t0
        hold(plan[rel + 1] or {})
        log(inputs[index].text, rel)
        if rel > plan.length + 120 then hold({}); stage = "next" end
    end
end)
