-- MAME 0.289, tektagt, NVRAM neuf. Aucune donnee de ROM ici.
-- Oracle des sons hors voix TTT1 (tools/ttt1/sfx.py) : on demande chaque son
-- au pilote H8 comme le fait le jeu pour le joueur 1 (80113C78 -> 8012564C /
-- 80125438 : parametre en 0x080208, requete 0x4103 en 0x08012E, numero du
-- pilote en 0x080226), et MAME enregistre la sortie (-wavwrite, -samplerate
-- 44100). Les demandes du jeu lui-meme (musique, demonstration) sont masquees
-- a la lecture par le pilote : l'enregistrement ne contient que les sons de
-- l'oracle.
-- TTT1_SFX : "index:numero:parametre" separes par des virgules.
-- TTT1_RAW : "index:case:mot" : requete directe, hors table (le laser de
-- Devil / Angel : 801253B0(0x112F, 27) depuis 80116EA4, au depart du rayon).
-- TTT1_OUT : CSV des demandes (trame et temps emule de chacune).
-- TTT1_FIRST, TTT1_STEP : premiere trame, trames entre deux demandes.
local machine = manager.machine
local sub = machine.devices[':sub'].spaces['program']
local list = {}
-- TTT1_SLOT : case de requete des sons de la table (23 par defaut, celle des
-- categories autres que 7 pour J1 ; 25 pour la categorie 7).
local SLOT = tonumber(os.getenv('TTT1_SLOT') or '23')
for i, id, param in string.gmatch(os.getenv('TTT1_SFX') or '', '(%d+):(%d+):(%d+)') do
    list[#list + 1] = {tonumber(i), tonumber(id), tonumber(param), SLOT, 0x100 + SLOT - 20}
end
for i, slot, word in string.gmatch(os.getenv('TTT1_RAW') or '', '(%d+):(%d+):(%d+)') do
    list[#list + 1] = {tonumber(i), 0, 0, tonumber(slot), tonumber(word)}
end
local out = assert(io.open(os.getenv('TTT1_OUT') or 'sfx-oracle.csv', 'w'))
out:write('index,driver_id,param,frame,time\n')
local FIRST = tonumber(os.getenv('TTT1_FIRST') or '1500')
local STEP = tonumber(os.getenv('TTT1_STEP') or '240')
local tick, pending, blocked = 0, nil, 0

-- Les cases de requete 0x080100..0x08013F : bit 0x4000 = demande, 0x8000 =
-- prise en compte. Seule la demande de l'oracle passe, jusqu'a sa prise en
-- compte ; les autres sont lues sans leur bit de demande.
ttt1_sfx_gate = sub:install_read_tap(0x080100, 0x08013f, 'ttt1-sfx-gate', function(offset, data, mask)
    if pending and offset == pending then return data end
    if (data & 0x4000) ~= 0 and (data & 0x8000) == 0 then blocked = blocked + 1; return data & ~0x4000 end
    return data
end)

ttt1_sfx_frames = emu.add_machine_frame_notifier(function()
    tick = tick + 1
    if pending and (sub:read_u16(pending) & 0x4000) == 0 then pending = nil end
    -- Une demi-seconde avant chaque demande, toutes les voix C352 sont
    -- relachees (drapeau 0x2000 puis ecriture en 0x404, comme le pilote) :
    -- un son en boucle ou encore en cours ne vole plus la voix du suivant.
    if tick >= FIRST - 30 and (tick - FIRST + 30) % STEP == 0 then
        for v = 0, 31 do
            local f = 0x280000 + v * 16 + 6
            sub:write_u16(f, (sub:read_u16(f) & ~0x4000) | 0x2000)
        end
        sub:write_u16(0x280404, 0)
    end
    local k = (tick - FIRST) // STEP + 1
    if tick >= FIRST and k <= #list and (tick - FIRST) % STEP == 0 then
        local e = list[k]
        pending = 0x080100 + 2 * e[4]
        if e[2] ~= 0 then
            sub:write_u16(0x080208, e[3])
            sub:write_u16(0x080200 + 2 * (e[4] - 4), e[2])
        end
        sub:write_u16(pending, e[5] | 0x4000)
        out:write(string.format('%d,%d,%d,%d,%.6f\n', e[1], e[2], e[3], tick, machine.time:as_double()))
    end
    if tick == FIRST + #list * STEP + 60 then
        out:write(string.format('blocked,%d\n', blocked))
        out:close(); machine:exit()
    end
end)
