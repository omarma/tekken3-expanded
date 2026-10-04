# Third-party notices

The modified sources of psxrecomp are based on commit
`5ab24616f18b8005d80c1b971f95ab3c3bdd650d`.
Copyright 2026 Matthew Stan; PolyForm Noncommercial 1.0.0.
The full license is retained in `psxrecomp/LICENSE` and at the repository root.
Project changes include renderer/layout fixes, outfit and sound controls, and
recompiler hooks used by the included Tekken-specific modules.

recomp-ui is based on commit `3d93e84d426d75ea5cdcad5442a042fb1d0b3045`.
Copyright 2026 Matthew Stanley; MIT. See `recomp-ui/LICENSE`.

OpenBIOS is redistributable firmware; see `psxrecomp/bios/OpenBIOS.LICENSE`.
No Sony retail BIOS is included. Further framework dependencies and notices
are listed in `psxrecomp/THIRD_PARTY_ATTRIBUTION.md`; license files are retained
alongside the vendored libraries.

The game (libmain.so on Android) also links:

- SDL3 3.4.10 (zlib license) and zlib 1.3.1 (zlib license; Android uses the
  system's libz instead);
- libchdr (BSD-3-Clause) with the libraries it bundles: miniz (MIT), zstd
  (BSD-3-Clause), the LZMA SDK (public domain) and dr_flac (public domain or
  MIT-0); see `psxrecomp/runtime/licenses/libchdr-NOTICES.txt`;
- through recomp-ui: Dear ImGui 1.91.9b (MIT), stb_image 2.30, stb_image_write
  1.16 and stb_truetype 1.26 (public domain or MIT), tinyfiledialogs 3.21.3
  (zlib license), and a generated OpenGL loader (`gl_core_3_1`);
- through psxrecomp: toml11 3.7.1 (MIT) and fmt 9.1.1 (MIT).

Their licenses are retained in the source next to each library, or collected
in the setup archive's `licenses/` directory.

MAME reference revision: `aab5dcadb6025303ba019d0189344a5df536a623`.
System 12 ROM load metadata: `src/mame/namco/namcos12.cpp`, copyright smf,
BSD-3-Clause. The C352 sample decoder in `tools/prepare_jun_voices.py` adapts
the MAME chip behavior; copyright R. Belmont and superctr, BSD-3-Clause.
See `licenses/MAME-BSD-3-Clause.txt`. The easy launcher downloads the unmodified MAME 0.289 upstream distribution
from https://github.com/mamedev/mame/releases/tag/mame0289, retaining its
license files. Corresponding MAME source is available at that release/tag.
MAME binaries and ROMs are not embedded in this ZIP.

The move lists in `tools/data/wiki/` are text from the Tekken wiki
(https://tekken.fandom.com), by its contributors, under CC BY-SA 3.0; the pages
and their links are listed in `tools/data/wiki/README.md`.

Original Tekken models, motion data, portraits, voices, game executables and
music are not included. The importer derives the needed assets from files
the user provides locally. Original game rights are not licensed by this project.


The easy setup package bundles portable CPython 3.12.13 from the toolchain's
python-build-standalone distribution. Its notices are retained in
`.runtime/python/LICENSE.txt`. Pillow 12.0.0 and its dependency notices are in
`.runtime/python/Lib/site-packages/pillow-12.0.0.dist-info/licenses/`.
The pinned distribution URLs and hashes are in `launcher/tools.lock.json`;
the Python packages the Android build installs (Pillow, numpy, pip) are pinned
with their hashes in `tools/requirements-import.txt` and
`tools/requirements-pip.txt`.
