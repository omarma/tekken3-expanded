-- MAME 0.289, tektagt, NVRAM neuf. Aucune donnee de ROM ici.
-- Ordre reel de lecture de la planche d'effet de coup fort du joueur 1 (4 x 4
-- images 64 x 64, 4 bits, page (512, 256), palette (512, 64) ; voir
-- tools/ttt1/hit_effect.py) : a chaque envoi de la liste de commandes GPU (DMA
-- canal 2 en liste chainee), on la parcourt et on releve les primitives
-- texturees qui lisent cette planche, avec leurs UV.
--
-- Mise en place de tools/ttt1_hit_effect_capture.lua (versus, TTT1_PATH et
-- TTT1_CONFIRM) ; en combat, le joueur 2 avance sans cesse (immobile, il garde ;
-- a droite, il avance vers la gauche) et le joueur 1 enchaine des coups.
-- Sortie : hit-order.csv (image, commande, palette, page, u, v minimaux, taille
-- du quad a l'ecran, couleur du premier sommet : fondu et agrandissement).
local machine = manager.machine
local space = machine.devices[":maincpu"].spaces["program"]
local port = machine.ioport.ports[":JVS_PLAYER1"]
local p2 = machine.ioport.ports[":JVS_PLAYER2"]
local UNLOCK = 0x2fe4fc
local CLUT = (512 // 16) | (64 << 6)                -- palette (512, 64)
local PAGE_X, PAGE_Y = 512 // 64, 256 // 256         -- page (512, 256)
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
local fight = t + 1300
local stop = fight + 2400
-- coups du joueur 1, un toutes les 36 images : poings, pieds, et 1+2 / 3+4
local attacks = {{"Button 2"}, {"Button 1", "Button 2"}, {"Button 5"}, {"Button 1"}, {"Button 4", "Button 5"}, {"Button 4"}}

local frame = 0
local out = assert(io.open("hit-order.csv", "w"))
out:write("frame,image,cmd,clut,tpage,u,v,w,h,rgb\n")

-- mots par commande GP0 (hors listes de lignes, qui ne sont pas texturees)
local function size(c)
    if c >= 0x20 and c < 0x40 then
        local n = (c & 8) ~= 0 and 4 or 3
        local w = 1 + n + (((c & 4) ~= 0) and n or 0) + (((c & 0x10) ~= 0) and (n - 1) or 0)
        return w
    end
    if c >= 0x60 and c < 0x80 then
        return 2 + (((c & 4) ~= 0) and 1 or 0) + (((c & 0x18) == 0) and 1 or 0)
    end
    if c == 0x02 then return 3 end
    if c >= 0xe0 then return 1 end
    return nil
end

local page = 0      -- derniere commande E1 (page des rectangles textures)
local lists, prims = 0, 0
local function textured(words, c)
    -- UV et palette / page : polygones (palette dans l'UV 0, page dans l'UV 1)
    local gouraud, quad = (c & 0x10) ~= 0, (c & 8) ~= 0
    local n = quad and 4 or 3
    local clut, tpage, us, vs, xs, ys = nil, nil, {}, {}, {}, {}
    for k = 0, n - 1 do
        local uv = words[(gouraud and (k * 3 + 3) or (k * 2 + 3))]
        local xy = words[(gouraud and (k * 3 + 2) or (k * 2 + 2))]
        local x, y = xy & 0x7ff, (xy >> 16) & 0x7ff
        xs[#xs + 1] = x >= 0x400 and x - 0x800 or x; ys[#ys + 1] = y >= 0x400 and y - 0x800 or y
        us[#us + 1] = uv & 0xff; vs[#vs + 1] = (uv >> 8) & 0xff
        if k == 0 then clut = uv >> 16 elseif k == 1 then tpage = uv >> 16 end
    end
    return clut, tpage, math.min(table.unpack(us)), math.min(table.unpack(vs)),
        math.max(table.unpack(xs)) - math.min(table.unpack(xs)),
        math.max(table.unpack(ys)) - math.min(table.unpack(ys)), words[1] & 0xffffff
end

local function log(c, clut, tpage, u, v, w, h, rgb)
    if clut ~= CLUT or (tpage & 15) ~= PAGE_X or ((tpage >> 4) & 1) ~= PAGE_Y then return end
    local image = (v // 64) * 4 + (u // 64)
    out:write(string.format("%d,%d,%02x,%04x,%04x,%d,%d,%d,%d,%06x\n", frame, image, c, clut, tpage, u, v,
        w or 0, h or 0, rgb or 0))
end

local function walk(addr)
    local guard = 0
    while addr ~= 0xffffff and guard < 200000 do
        guard = guard + 1
        local head = space:read_u32(addr & 0x3fffff)
        local count = head >> 24
        local i = 1
        while i <= count do
            local w0 = space:read_u32((addr + 4 * i) & 0x3fffff)
            local c = w0 >> 24
            local n = size(c)
            if not n or i + n - 1 > count then break end
            if c == 0xe1 then page = w0 & 0xffff end
            if (c & 0xe4) == 0x24 or (c & 0xe4) == 0x64 then prims = prims + 1 end
            if c >= 0x20 and c < 0x40 and (c & 4) ~= 0 then
                local words = {}
                for k = 1, n do words[k] = space:read_u32((addr + 4 * (i + k - 1)) & 0x3fffff) end
                log(c, textured(words, c))
            elseif c >= 0x60 and c < 0x80 and (c & 4) ~= 0 then
                local uv = space:read_u32((addr + 4 * (i + 2)) & 0x3fffff)
                log(c, uv >> 16, page, uv & 0xff, (uv >> 8) & 0xff)
            end
            i = i + n
        end
        addr = head & 0xffffff
    end
end

hit_order_dma = space:install_write_tap(0x1f8010a8, 0x1f8010ab, "hit-order-dma2", function(offset, data, mask)
    if frame < fight or (data & 0x01000000) == 0 or ((data >> 9) & 3) ~= 2 then return end
    lists = lists + 1
    walk(space:read_u32(0x1f8010a0) & 0xffffff)
end)

ttt1_hit_order = emu.add_machine_frame_notifier(function()
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
    if frame >= fight then
        field(p2, "Left"):set_value(1)
        local k = (frame - fight) % 36
        local a = attacks[((frame - fight) // 36) % #attacks + 1]
        for _, b in ipairs(a) do field(port, b):set_value((k < 4) and 1 or 0) end
    end
    if frame == stop then
        out:write(string.format("# %d listes, %d primitives texturees\n", lists, prims))
        out:close()
        machine.video:snapshot()
        machine:exit()
    end
end)
