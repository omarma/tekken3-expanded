-- MAME 0.289, tektagt, NVRAM neuf. Aucune donnee de ROM ici.
-- Ou est la vie d'un combattant dans TTT1. Arcade a un joueur (Xiaoyu), le
-- joueur 1 ne fait rien pendant le premier combat : le CPU le frappe. Toutes
-- les 30 images, les octets du bloc du joueur 1 (0x29EEF8, 0x1A60
-- octets, comme les cles) sont notes ; life-candidates.csv garde les champs
-- u8 et u16 qui ne font que baisser, au moins une fois : les candidats de la
-- vie. Resultat (2026-09-25) : la vie est le u32 en +0x3D0 (0x76000 plein,
-- 0 au K.O.) ; l'octet du cheat en est l'octet haut. On lit aussi l'octet du cheat « mort en un
-- coup » (0x2A0D2A pour le CPU, meme decalage pour le joueur 1) : les
-- octets +0x3C0..+0x3DF vont dans life-near-cheat.csv.
local machine = manager.machine
local space = machine.devices[":maincpu"].spaces["program"]
local port = machine.ioport.ports[":JVS_PLAYER1"]
local UNLOCK, TIMER = 0x2fe4fc, 0x2434e0
local P1, SIZE = 0x29eef8, 0x1a60
local frame, samples, started = 0, {}, nil
local steps = {{1860, "1 Player Start"}, {2060, "P1 Button 1"}, {2120, "P1 Right"}, {2160, "P1 Button 1"}}
ttt1_life_probe = emu.add_machine_frame_notifier(function()
    frame = frame + 1
    space:write_u32(UNLOCK, 0xffffffff)
    local coin = machine.ioport.ports[":JVS_COIN1"].fields["Coin 1"]
    if frame == 600 then coin:set_value(1) end
    if frame == 604 then coin:set_value(0) end
    for _, s in ipairs(steps) do
        if frame == s[1] then port.fields[s[2]]:set_value(1) end
        if frame == s[1] + 4 then port.fields[s[2]]:set_value(0) end
    end
    local timer = space:read_u32(TIMER)
    if not started and frame > 2400 and timer > 0 and timer < 3600 then started = frame end
    if started and (frame - started) % 30 == 0 then
        local s = {}
        for o = 0, SIZE - 1 do s[o] = space:read_u8(P1 + o) end
        s.t = timer
        samples[#samples + 1] = s
    end
    if started and frame - started >= 2400 then
        local f = assert(io.open("life-candidates.csv", "w"))
        f:write("offset,address,width,first,last,drops,values\n")
        local function field(i, o, w) return w == 1 and samples[i][o] or samples[i][o] + 256 * samples[i][o + 1] end
        for _, w in ipairs({1, 2}) do
            for o = 0, SIZE - w, w do
                local first, prev, drops, ok, seq = field(1, o, w), field(1, o, w), 0, true, {}
                for i = 2, #samples do
                    local v = field(i, o, w)
                    if v > prev then ok = false; break end
                    if v < prev then drops = drops + 1; seq[#seq + 1] = v end
                    prev = v
                end
                if ok and drops >= 1 and first > 0 then
                    f:write(string.format("0x%x,0x%x,%d,%d,%d,%d,%s\n", o, P1 + o, w, first, prev, drops, table.concat(seq, " ")))
                end
            end
        end
        local g = assert(io.open("life-near-cheat.csv", "w"))
        for i = 1, #samples do
            local row = {samples[i].t}
            for o = 0x3c0, 0x3df do row[#row + 1] = samples[i][o] end
            g:write(table.concat(row, ",") .. "\n")
        end
        g:close()
        f:close(); machine:exit()
    end
end)
