"""The "tcc flavor" experiment of docs/android-phone-setup.md.

tcc never inlines, so every psx_cyc_step() of the generated code (one per
guest instruction) becomes a call. This simulates an emitter that writes the
step inline for tcc: it copies runtime/include to OUT_INCLUDE with a few macros
added at the end of psx_cyc.h (tcc only), and rewrites each
psx_cyc_step(cpu, 0xMASK) of the generated file with the mask's registers
spelled out. Same semantics: the benchmark's checksum and guest cycle count
stay identical.

  tcc_flavor.py RUNTIME_INCLUDE OUT_INCLUDE GENERATED_C OUT_C
"""
import re
import shutil
import sys
from pathlib import Path

MACROS = r'''
/* ---- tcc flavor (tools/android/phone_setup_bench/tcc_flavor.py) ---- */
#if defined(__TINYC__) && !defined(PSX_OVERLAY_DLL_BUILD) && !defined(PSX_COSIM)
#define PSX_TCC_CHARGE1() do { uint32_t _b = g_psx_cyc_batch; \
    if (_b && !(g_ls_replay_active | g_event_step_conservative) && !psx_in_device_service \
        && !g_psx_cyc_local_acc && g_psx_cyc_bb_defer <= 0 && _b + 1u < g_psx_cyc_batch_limit) \
        g_psx_cyc_batch = _b + 1u; \
    else psx_cyc_charge(1u); } while (0)
#define PSX_TCC_STEP_BEGIN(c) do { uint8_t _w = (c)->read_absorb_which; \
    if ((c)->read_absorb[_w]) (c)->read_absorb[_w]--; else PSX_TCC_CHARGE1(); } while (0)
#define PSX_TCC_STEP_END(c) do { uint8_t _lw = (c)->ld_which_t; \
    (c)->read_absorb[_lw] = (uint8_t)(c)->ld_absorb; (c)->read_fudge = _lw; \
    (c)->read_absorb_which = (uint8_t)((c)->read_absorb_which | (_lw & 0x1Fu)); \
    (c)->ld_which_t = 0x20u; } while (0)
#define psx_cyc_bb_defer_flush() do { if (g_psx_cyc_local_acc || g_psx_cyc_batch) psx_cyc_batch_flush(); } while (0)
#endif
'''


def step(match):
    mask = int(match.group(1), 16) & 0xFFFFFFFE
    stores = ''.join(f' cpu->read_absorb[{i}] = 0u;' for i in range(1, 32) if mask >> i & 1)
    return f'PSX_TCC_STEP_BEGIN(cpu);{stores} PSX_TCC_STEP_END(cpu);'


def main():
    include, out_include, source, out_source = map(Path, sys.argv[1:5])
    shutil.rmtree(out_include, ignore_errors=True)
    shutil.copytree(include, out_include)
    header = out_include / 'psx_cyc.h'
    text = header.read_text(encoding='utf-8-sig')
    at = text.rindex('#ifdef __cplusplus')
    header.write_text(text[:at] + MACROS + '\n' + text[at:], encoding='utf-8')
    code, count = re.subn(r'psx_cyc_step\(cpu, 0x([0-9A-Fa-f]+)u\);', step, source.read_text(encoding='utf-8'))
    out_source.write_text(code, encoding='utf-8')
    print(f'{count} psx_cyc_step rewritten')


if __name__ == '__main__':
    main()
