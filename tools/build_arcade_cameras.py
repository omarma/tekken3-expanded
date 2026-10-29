"""Build the arcade-camera variants of the PS1's end-of-round cameras (B87).

On a T3 arcade stage (Arcade Stages), the winner's pose and the K.O. replay
follow Tekken 3 arcade's cameras (src/tekken3_arcade_cameras.c); the view of
the loser stays the PS1's (B110).
The two games share these routines, only constants and a few choices differ
(workspace notes: B87 cams/REPORT.md). Each routine here is copied from the
recompiled source and renamed __wrap_func_<address>; a few statements, found
by their MIPS word, route an operand through a hook of tekken3_arcade_cameras.c
that returns the original value unless an arcade stage wants the arcade's.
The recompiler's continuations, cycle accounting and interrupt checks stay.
Fail the build if the executable or the generated code changed at a site.
"""
import argparse
from pathlib import Path
import struct

# function -> generated shard
FUNCTIONS = {
    'func_80046270': 'SLUS_004.02_full_12.c',   # camera_aim_fighter
    'func_80046460': 'SLUS_004.02_full_12.c',   # camera_shot_a_init's entry: a move, then its split piece
    'func_80046464': 'SLUS_004.02_full_12.c',   # camera_shot_a_init
    'func_800465BC': 'SLUS_004.02_full_12.c',   # camera_shot_a_update
    'func_800686B0': 'SLUS_004.02_full_27.c',   # camera_end_scene_start
    'func_8006870C': 'SLUS_004.02_full_27.c',   # camera_end_scene_update
    'func_8006953C': 'SLUS_004.02_full_27.c',   # camera_replay_start
    'func_80069414': 'SLUS_004.02_full_27.c',   # camera_replay_update
}

# (function, address, MIPS word or None, old text in the statement, new text)
# The statement is the line carrying "/* 0xADDR: 0xWORD */", or, for a branch
# condition (word checked at its address), the line "int _bc_ADDR = ".
SITES = [
    # winner's pose, shot A: aim (no_pitch of the stage, no PS1 circle of 5800)
    ('func_80046270', 0x80046364, 0x84428CDC,
     'cpu->gpr[2] = (int32_t)(int16_t)psx_cyc_load_half(cpu, cpu->gpr[2] + -29476, 2, 0x4u);',
     'cpu->gpr[2] = tk3_arccam_v((int32_t)(int16_t)psx_cyc_load_half(cpu, cpu->gpr[2] + -29476, 2, 0x4u), ARCCAM_NO_PITCH);'),
    ('func_80046270', 0x800463B0, 0x34634E40,
     'cpu->gpr[3] = cpu->gpr[3] | 0x4E40;',
     'cpu->gpr[3] = tk3_arccam_v(cpu->gpr[3] | 0x4E40, ARCCAM_SHOT_A_CIRCLE);'),
    # shot A start: radius (cos, then sin, times 0xF71), height by no_pitch
    ('func_80046464', 0x80046514, 0x00443021,
     'cpu->gpr[6] = cpu->gpr[2] + cpu->gpr[4];',
     'cpu->gpr[6] = tk3_arccam_k(cpu->gpr[2] + cpu->gpr[4], cpu->gpr[4], ARCCAM_SHOT_A_RADIUS);'),
    ('func_80046464', 0x80046540, 0x00442021,
     'cpu->gpr[4] = cpu->gpr[2] + cpu->gpr[4];',
     'cpu->gpr[4] = tk3_arccam_k(cpu->gpr[2] + cpu->gpr[4], cpu->gpr[4], ARCCAM_SHOT_A_RADIUS);'),
    ('func_80046464', 0x8004656C, 0x84638CDC,
     'cpu->gpr[3] = (int32_t)(int16_t)psx_cyc_load_half(cpu, cpu->gpr[3] + -29476, 3, 0x8u);',
     'cpu->gpr[3] = tk3_arccam_v((int32_t)(int16_t)psx_cyc_load_half(cpu, cpu->gpr[3] + -29476, 3, 0x8u), ARCCAM_NO_PITCH);'),
    # shot A: how near it comes
    ('func_800465BC', 0x80046640, 0x24C2F62F,
     'cpu->gpr[2] = cpu->gpr[6] + -2513;',
     'cpu->gpr[2] = cpu->gpr[6] - tk3_arccam_v(2513, ARCCAM_SHOT_A_NEAR);'),
    # the scene: shot A only (the arcade never starts its shot B)
    ('func_800686B0', 0x800686DC, 0x14400005,
     'int _bc_800686DC = (cpu->gpr[2] != cpu->gpr[0]);',
     'int _bc_800686DC = tk3_arccam_bc(cpu->gpr[2] != cpu->gpr[0], ARCCAM_SCENE_START);'),
    ('func_8006870C', 0x80068724, 0x14600006,
     'int _bc_80068724 = (cpu->gpr[3] != cpu->gpr[0]);',
     'int _bc_80068724 = tk3_arccam_bc(cpu->gpr[3] != cpu->gpr[0], ARCCAM_SCENE_UPDATE);'),
    # replay start: the draws, as the PS1 makes them
    ('func_8006953C', 0x800695E4, 0x00021400,
     'cpu->gpr[2] = cpu->gpr[2] << 16;',
     'cpu->gpr[2] = tk3_arccam_cap(cpu->gpr[2], ARCCAP_BASE) << 16;'),
    ('func_8006953C', 0x800695F4, 0x30420001,
     'cpu->gpr[2] = cpu->gpr[2] & 0x0001;',
     'cpu->gpr[2] = tk3_arccam_cap(cpu->gpr[2], ARCCAP_FLIP) & 0x0001;'),
    ('func_8006953C', 0x80069630, 0x00621821,
     'cpu->gpr[3] = cpu->gpr[3] + cpu->gpr[2];',
     'cpu->gpr[3] = cpu->gpr[3] + tk3_arccam_cap(cpu->gpr[2], ARCCAP_YAW);'),
    ('func_8006953C', 0x8006963C, 0x24420019,
     'cpu->gpr[2] = cpu->gpr[2] + 25;',
     'cpu->gpr[2] = tk3_arccam_cap(cpu->gpr[2], ARCCAP_FROM) + 25;'),
    ('func_8006953C', 0x80069668, 0x24420019,
     'cpu->gpr[2] = cpu->gpr[2] + 25;',
     'cpu->gpr[2] = tk3_arccam_cap(cpu->gpr[2], ARCCAP_TO) + 25;'),
    ('func_8006953C', 0x80069694, 0x30420001,
     'cpu->gpr[2] = cpu->gpr[2] & 0x0001;',
     'cpu->gpr[2] = tk3_arccam_cap(cpu->gpr[2], ARCCAP_SIGN) & 0x0001;'),
    ('func_8006953C', 0x800696D4, 0x00621821,
     'cpu->gpr[3] = cpu->gpr[3] + cpu->gpr[2];',
     'cpu->gpr[3] = cpu->gpr[3] + tk3_arccam_cap(cpu->gpr[2], ARCCAP_YAW);'),
    # replay update: angles kept a quarter scale in their halfwords
    ('func_80069414', 0x80069470, 0x8602000E,
     'cpu->gpr[2] = (int32_t)(int16_t)psx_cyc_load_half(cpu, cpu->gpr[16] + 14, 2, 0x10000u);',
     'cpu->gpr[2] = tk3_arccam_v((int32_t)(int16_t)psx_cyc_load_half(cpu, cpu->gpr[16] + 14, 2, 0x10000u), ARCREP_LOAD);'),
    ('func_80069414', 0x80069474, 0x86070008,
     'cpu->gpr[7] = (int32_t)(int16_t)psx_cyc_load_half(cpu, cpu->gpr[16] + 8, 7, 0x10000u);',
     'cpu->gpr[7] = tk3_arccam_v((int32_t)(int16_t)psx_cyc_load_half(cpu, cpu->gpr[16] + 8, 7, 0x10000u), ARCREP_LOAD);'),
    ('func_80069414', 0x80069488, 0x84A4000E,
     'cpu->gpr[4] = (int32_t)(int16_t)psx_cyc_load_half(cpu, cpu->gpr[5] + 14, 4, 0x20u);',
     'cpu->gpr[4] = tk3_arccam_v((int32_t)(int16_t)psx_cyc_load_half(cpu, cpu->gpr[5] + 14, 4, 0x20u), ARCREP_LOAD);'),
    ('func_80069414', 0x8006948C, 0x84A20010,
     'cpu->gpr[2] = (int32_t)(int16_t)psx_cyc_load_half(cpu, cpu->gpr[5] + 16, 2, 0x20u);',
     'cpu->gpr[2] = tk3_arccam_v((int32_t)(int16_t)psx_cyc_load_half(cpu, cpu->gpr[5] + 16, 2, 0x20u), ARCREP_LOAD);'),
    ('func_80069414', 0x800694DC, 0xA4A2000E,
     'cpu->write_half(cpu->gpr[5] + 14, (uint16_t)cpu->gpr[2]);',
     'cpu->write_half(cpu->gpr[5] + 14, (uint16_t)tk3_arccam_v(cpu->gpr[2], ARCREP_STORE));'),
    ('func_80069414', 0x800694E4, 0x2403113D,
     'cpu->gpr[3] = 4413;',
     'cpu->gpr[3] = tk3_arccam_v(4413, ARCREP_DIST);'),
]

# direct calls in the same shard, which the linker's --wrap does not redirect
CALLS = [
    ('func_80046460', 'func_80046464(cpu); return;  /* fallthrough to split piece */',
     '__wrap_func_80046464(cpu); return;  /* fallthrough to split piece */'),
]

# the replay's arcade values, set from the draws once the PS1's are made,
# before its first update: just before the call
INSERT_BEFORE = [
    ('func_8006953C', 'cpu->pc = 0x80069414u; return;  /* CPS jal -> 0x80069414 */', 'tk3_arccam_replay_start(cpu);'),
]


def word_at(exe: bytes, address: int) -> int:
    load_address = struct.unpack_from('<I', exe, 0x18)[0]
    return struct.unpack_from('<I', exe, address - load_address + 0x800)[0]


def body_of(source: str, name: str) -> str:
    start = source.index(f'void {name}(CPUState* cpu)\n{{')
    end = source.index('\n}\n', start) + 3
    return source[start:end]


def generate(generated: Path, exe: bytes) -> str:
    shards = {}
    bodies = {}
    for name, shard in FUNCTIONS.items():
        if shard not in shards:
            shards[shard] = (generated / shard).read_text(encoding='utf-8')
        body = body_of(shards[shard], name)
        bodies[name] = body.replace(f'void {name}(', f'void __wrap_{name}(', 1)
    for name, address, word, old, new in SITES:
        if word is not None and word_at(exe, address) != word:
            raise ValueError(f'Arcade camera instruction mismatch at {address:08X}')
        body = bodies[name]
        key = f'/* 0x{address:08X}: 0x{word:08X} */' if not old.startswith('int _bc_') else f'int _bc_{address:08X} = '
        lines = [i for i, line in enumerate(body.split('\n')) if key in line]
        if len(lines) != 1:
            raise ValueError(f'Arcade camera site not found once at {address:08X} in {name}')
        split = body.split('\n')
        line = split[lines[0]]
        if line.count(old) != 1:
            raise ValueError(f'Arcade camera statement mismatch at {address:08X}: {line.strip()}')
        split[lines[0]] = line.replace(old, new)
        bodies[name] = '\n'.join(split)
    for name, old, new in CALLS:
        if bodies[name].count(old) != 1:
            raise ValueError(f'Arcade camera call not found once in {name}')
        bodies[name] = bodies[name].replace(old, new)
    for name, marker, code in INSERT_BEFORE:
        body = bodies[name]
        if body.count(marker) != 1:
            raise ValueError(f'Arcade camera insertion marker not found once in {name}')
        at = body.index(marker)
        line_start = body.rfind('\n', 0, at) + 1
        indent = body[line_start:at]
        bodies[name] = body[:line_start] + indent + code + '\n' + body[line_start:]
    return ('/* Generated by tools/build_arcade_cameras.py; do not edit. */\n'
            '#include "SLUS_004.02_decls.h"\n'
            '#include "tekken3_arcade_cameras.h"\n\n'
            + ''.join(f'void __wrap_{name}(CPUState* cpu);\n' for name in FUNCTIONS) + '\n'
            + '\n'.join(bodies[name] for name in FUNCTIONS))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--generated', type=Path, required=True, help='the recompiler output directory')
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = generate(args.generated, args.exe.read_bytes())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not args.output.exists() or args.output.read_text(encoding='utf-8') != result:
        args.output.write_text(result, encoding='utf-8')
