import struct, sys
with open('bios/SCPH1001.BIN','rb') as f: rom=f.read()
BASE=0xBFC00000
# Find lui reg, X followed by addiu reg, reg, Y where X<<16+signext(Y) == target
def find_const(target):
    tgt_hi = (target >> 16) & 0xffff
    tgt_lo_signed = target & 0xffff
    # If low bit 15 set, lui needs hi+1
    if tgt_lo_signed & 0x8000:
        lui_hi = (tgt_hi + 1) & 0xffff
    else:
        lui_hi = tgt_hi
    hits = []
    for off in range(0, len(rom)-8, 4):
        w0 = struct.unpack('<I', rom[off:off+4])[0]
        op0 = (w0>>26)&0x3f
        if op0 != 15 or (w0&0xffff) != lui_hi: continue
        rt0 = (w0>>16)&0x1f
        for d in range(1, 16):
            noff = off + d*4
            if noff+4>len(rom): break
            w1 = struct.unpack('<I', rom[noff:noff+4])[0]
            op1 = (w1>>26)&0x3f
            if op1==9 and (w1&0xffff)==tgt_lo_signed:
                rs1=(w1>>21)&0x1f; rt1=(w1>>16)&0x1f
                if rs1==rt0 and rt1==rt0:
                    hits.append((BASE+off, BASE+noff, rt0, d))
                    break
            if op1==13 and (w1&0xffff)==(target&0xffff):  # ori variant
                rs1=(w1>>21)&0x1f; rt1=(w1>>16)&0x1f
                if rs1==rt0 and rt1==rt0 and (w0&0xffff)==tgt_hi:
                    hits.append((BASE+off, BASE+noff, rt0, d))
                    break
    return hits

for t in [int(a,16) for a in sys.argv[1:]]:
    hits = find_const(t)
    print(f'--- const 0x{t:08X} synthesized by ({len(hits)} sites) ---')
    for lui_pc, lo_pc, rt, d in hits[:20]:
        print(f'  lui@0x{lui_pc:08X} lo@0x{lo_pc:08X} reg={rt} dist={d}')
