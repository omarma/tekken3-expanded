#!/usr/bin/env python3
"""Decode state handler output values from hex."""
import struct

# Handler address -> first 16 bytes (hex)
handlers = {
    0x0003648C: "0880013c489e20ac0680013c35000a24",
    0x00036578: "0680053c4c69a58c000000002a00a010",
    0x00036568: "3e0019240680013c01000010406939ac",
    0x00036538: "37000e240680013c0d00001040692eac",
    0x00036450: "340019240680013c486939ac0680013c",
    0x0003642C: "32000f240680013c48692fac0680013c",
    0x0003647C: "360009240680013c3c000010406929ac",
    0x00036548: "38000f240680013c0900001040692fac",
    0x00036558: "3d0018240680013c05000010406938ac",
}

# Second jump table: state -> handler
jtable = {
    0x02: 0x0003648C,
    0x03: 0x00036578,
    0x04: 0x00036568,
    0x05: 0x00036538,
    0x06: 0x00036578,
    0x07: 0x00036578,
    0x08: 0x00036578,
    0x09: 0x00036450,
    0x0A: 0x00036450,
    0x0B: 0x0003642C,
    0x0C: 0x00036578,
    0x0D: 0x00036568,
    0x0E: 0x00036578,
    0x0F: 0x0003647C,
    0x10: 0x00036578,
    0x11: 0x00036568,
    0x12: 0x00036578,
    0x13: 0x00036578,
    0x14: 0x00036578,
    0x15: 0x00036578,
    0x16: 0x00036548,
    0x17: 0x00036568,
    0x18: 0x0003648C,
    0x19: 0x00036558,
}

print("State -> Output mapping (second dispatcher):")
print(f"{'State':>7} {'Handler':>10} {'Output':>8}")
print("-" * 30)

for state in sorted(jtable.keys()):
    handler_addr = jtable[state]
    hex_data = handlers[handler_addr]
    raw = bytes.fromhex(hex_data)
    word0 = struct.unpack_from('<I', raw, 0)[0]

    # Most handlers start with: addiu rN, zero, VALUE
    opcode = (word0 >> 26) & 0x3F
    rs = (word0 >> 21) & 0x1F
    imm = word0 & 0xFFFF

    if opcode == 0x09 and rs == 0:  # addiu rN, $zero, imm
        output = imm
        print(f"  0x{state:02X}    0x{handler_addr:08X}   0x{output:02X} ({output})")
    elif opcode == 0x0F:  # lui (different pattern)
        print(f"  0x{state:02X}    0x{handler_addr:08X}   (complex)")
    else:
        print(f"  0x{state:02X}    0x{handler_addr:08X}   (unknown op={opcode:#x})")
