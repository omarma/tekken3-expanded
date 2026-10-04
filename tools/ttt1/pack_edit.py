"""(From the devil-jin branch.) Edit a converted combat pack (<Name>-TTT1-combat.jmv, tools/ttt1/moves.py)
after the fact: add records, replace a record's clip, set its timing and
cancel list, then write a pack the runtime accepts (src/tekken3_ttt1_pack.h,
ttt1_pack_validate): clips and cancel lists before the relocation table,
the input sequences last, every offset and relocation consistent.

Layout: header (8 words: magic, 4, size, records, neutral, relocation
offset, relocation count = 4 * records, record table offset = 32 + 16 *
records), per record a 16-byte entry (clip source, TTT1 address, record
offset, cancel count), the 56-byte records, a data area (clips, cancel
lists, sounds, properties), the relocation table (4 words a record: its
+0, +12, +28, +32) and the input sequences.
"""
import struct

CLIP_MAGIC, CHANNELS = 0x4a554e00, 57


class Pack:
    def __init__(self, data):
        h = struct.unpack_from('<8I', data)
        if h[0] != 0x314d554a or h[1] != 4: raise ValueError('not a v4 combat pack')
        n, self.neutral, ro = h[3], h[4], h[5]
        records_at = 32 + n * 16
        self.meta = [list(struct.unpack_from('<4I', data, 32 + i * 16)) for i in range(n)]
        self.records = [bytearray(data[records_at + i * 56:records_at + i * 56 + 56]) for i in range(n)]
        self.data_at = records_at + n * 56
        self.data = bytearray(data[self.data_at:ro])          # absolute offset = data_at + index
        self.tail = bytes(data[ro + h[6] * 4:])             # input sequences

    def word(self, i, k): return struct.unpack_from('<I', self.records[i], k * 4)[0]
    def set_word(self, i, k, v): struct.pack_into('<I', self.records[i], k * 4, v)
    def index(self, address): return next(i for i, m in enumerate(self.meta) if m[1] == address)

    def add_data(self, blob):
        """Append to the data area (4-aligned); returns its absolute offset."""
        self.data.extend(b'\0' * (-len(self.data) % 4))
        offset = self.data_at + len(self.data)
        self.data.extend(blob)
        return offset

    def cancels(self, i):
        cp, n = self.word(i, 3) - self.data_at, self.meta[i][3]
        return [struct.unpack_from('<4H4B', self.data, cp + k * 12) for k in range(n)]

    def set_cancels(self, i, entries):
        self.set_word(i, 3, self.add_data(b''.join(struct.pack('<4H4B', *e) for e in entries)))
        self.meta[i][3] = len(entries)

    def set_clip(self, i, poses):
        blob = struct.pack('<II', CLIP_MAGIC | len(poses), CHANNELS) + b''.join(struct.pack('<57H', *p) for p in poses)
        self.set_word(i, 0, self.add_data(blob))
        self.set_word(i, 6, (self.word(i, 6) & 0xffffff00) | len(poses))

    def set_props(self, i, props):
        """Timed properties, record word 8: (frame, kind, arg), ended by a
        zero frame (PS1 dispatch 800458C8; kind 6 lights the fighter up,
        as the Supercharger and Force do). From devil-jin, 87b79be."""
        blob = b''.join(struct.pack('<HH', f, k << 8 | a) for f, k, a in props) + b'\0' * 4
        self.set_word(i, 8, self.add_data(blob))

    def set_level(self, i, level):
        """Hit level, record word 2, coded as in Tekken 5 (low 16 bits):
        0x10F low, 0x217 mid, 0x412 / 0x512 high; high bits kept."""
        self.set_word(i, 2, (self.word(i, 2) & 0xffff0000) | (level & 0xffff))

    def set_timing(self, i, first, last, damage):
        self.records[i][45], self.records[i][46] = first, last
        self.set_word(i, 5, (self.word(i, 5) & 0xffff0000) | damage)

    def add_record(self, like, address):
        """A copy of record `like` (same sounds, properties, hit data), under
        a TTT1 address of its own; returns its index (move 8192 + index)."""
        self.meta.append(list(self.meta[like])); self.meta[-1][1] = address
        self.records.append(bytearray(self.records[like]))
        return len(self.records) - 1

    def build(self):
        n = len(self.records)
        records_at = 32 + n * 16
        data_at = records_at + n * 56
        shift = data_at - self.data_at                      # the data area moves by the added entries
        out = bytearray(32 + n * 16 + n * 56)
        relocs = []
        for i, (meta, rec) in enumerate(zip(self.meta, self.records)):
            rp = records_at + i * 56
            rec = bytearray(rec)
            for k in (0, 3, 7, 8):                          # clip, cancels, sounds, properties
                struct.pack_into('<I', rec, k * 4, struct.unpack_from('<I', rec, k * 4)[0] + shift)
            out[rp:rp + 56] = rec
            struct.pack_into('<4I', out, 32 + i * 16, meta[0], meta[1], rp, meta[3])
            relocs.extend((rp, rp + 12, rp + 28, rp + 32))
        out.extend(self.data)
        out.extend(b'\0' * (-len(out) % 4))
        ro = len(out)
        out.extend(struct.pack(f'<{len(relocs)}I', *relocs))
        out.extend(self.tail)
        struct.pack_into('<8I', out, 0, 0x314d554a, 4, len(out), n, self.neutral, ro, len(relocs), records_at)
        return bytes(out)
