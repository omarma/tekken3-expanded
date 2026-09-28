-- MAME 0.289, tektagt, NVRAM neuf. Aucune donnee de ROM ici.
-- Oracle de frequences C352 des voix d'un personnage TTT1 (generalise de
-- the former Jun and Kazuya voice oracles) : on demande chaque identifiant
-- au pilote H8 d'origine et on releve les registres du C352 au key-on.
-- TTT1_VOICE_IDS : identifiants separes par des virgules (table du profil son).
-- TTT1_OUT : fichier CSV produit.
local machine = manager.machine
local sub = machine.devices[':sub'].spaces['program']
local ids = {}
for v in string.gmatch(os.getenv('TTT1_VOICE_IDS') or '', '%d+') do ids[#ids + 1] = tonumber(v) end
local out = assert(io.open(os.getenv('TTT1_OUT') or 'voice-oracle.csv', 'w'))
out:write('tick,requested_id,voice,volume_front,frequency,flags,bank,start,end\n')
local tick, requested = 0, 0

ttt1_voice_tap = sub:install_write_tap(0x280404, 0x280405, 'ttt1-voice-keyon', function()
    local base = 0x280000 + 21*16
    if (sub:read_u16(base+6) & 0x4000) ~= 0 then
        out:write(string.format('%d,%d,21,%d,%d,%d,%d,%d,%d\n', tick, requested,
            sub:read_u16(base), sub:read_u16(base+4), sub:read_u16(base+6),
            sub:read_u16(base+8), sub:read_u16(base+10), sub:read_u16(base+12)))
    end
end)

-- Le pilote n'est vivant qu'apres le demarrage (selection vers la trame 1950).
local FIRST, STEP = 1900, 60
ttt1_voice_frames = emu.add_machine_frame_notifier(function()
    tick = tick + 1
    requested = 0
    local k = (tick - FIRST) // STEP + 1
    if tick >= FIRST and k <= #ids and (tick - FIRST) % STEP == 0 then
        requested = ids[k]
        sub:write_u16(0x080204, 0x10)
        sub:write_u16(0x080222, requested)
        sub:write_u16(0x08012a, 0x4101)
    end
    if tick == FIRST + #ids*STEP + 120 then out:close(); machine:exit() end
end)
