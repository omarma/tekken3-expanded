# Add-ons

An add-on is a folder of its own, `addons/<id>/`, made and published by someone else, that Tekken 3 Expanded builds
into the game. Nothing in this folder but this file is part of Tekken 3 Expanded: each add-on comes from its own
repository, under its own author's responsibility.

## For players

1. Put the add-on in `addons/<id>/` (its README says which `<id>`, for example `git clone <its repository>
   addons/<id>`). `addons/<id>/addon.cmake` must exist.
2. Start the setup and click **Update & play**. It runs the add-on's own setup step, then builds the game with it.
   Its mods show in the launcher's **Mods** page.
3. To remove it: delete its folder, then **Update & play** again.

An add-on that cannot be set up or built with this release is left out: the game is built without it, the setup
says so, and its log (`.setup/setup.log`) tells why.

On Android, **Build Android APK** builds the add-ons into the APK the same way, from the add-ons in the PC folder.

## For authors (add-on API 1)

### `addon.cmake`

The game's `CMakeLists.txt` includes `addons/<id>/addon.cmake`, in a scope of its own, once `psx-runtime` exists and
every wrap of the game is declared, before the macOS `--wrap` emulation is applied and before the game's own files
are staged beside the executable. Set there:

| | |
|---|---|
| `TEKKEN3_ADDON_API` | `1` (read it: a later API may change what follows) |
| `TEKKEN3_ADDON_DIR` | the add-on's folder |
| `TEKKEN3_ADDON_ID` | its folder's name |

The file adds its sources to `psx-runtime` (`target_sources`, with its own `set_source_files_properties` for its
include folders and definitions) and uses:

- `tekken3_wrap_symbol(<sym> WRAPPER <file>)`: `-Wl,--wrap=<sym>` for a symbol the game does not wrap, its
  definition in `<file>` (emulated on macOS).
- `tekken3_addon_chain(<sym> WRAPPER <file> CHAIN <name> [BRIDGED <var>])`: the add-on's `__wrap_<sym>` (in
  `<file>`) in front of the game's. The source that defines `__wrap_<sym>` now is compiled with that name changed to
  `<name>`, which the add-on's wrapper calls on to. When the game does not wrap `<sym>` (another release, a feature
  turned off), `<sym>` is wrapped for the add-on alone and `<var>` is set `TRUE`: the add-on's own `<name>` then
  calls `__real_<sym>`. Another add-on may chain in front of this one the same way.
- `tekken3_addon_stage(FROM <folder> TO <path beside the game>)`: a folder copied beside the executable at each
  build, after the game's own staging (which recreates `mods/`). A package goes to `mods/packages/<package id>`;
  a `FROM` that does not exist yet leaves nothing there.

Never patch, rename or rebuild the game's files: what the add-on changes is in its compile definitions, so that
deleting its folder gives back the game as it was at the next build.

### The setup step

`set(TEKKEN3_ADDON_SETUP <script>)` in `addon.cmake` (a literal path relative to the folder, on one line) names a
Python script that **Update & play** runs before each build, with the setup's Python and toolchain, from the add-on's
folder:

    <python> -u <script> --no-build

It makes what the add-on needs from the player's own files, without asking anything (no window, no input), and
exits 0. Anything else leaves the add-on out of that build. The game's build is the setup's own: the step does not
build.

Keep what the step makes in the add-on's own folder (for example `addons/<id>/workspace/`): the setup's
**Free up disk space** never touches `addons/`.

### Android

The APK holds the game's `assets/`, `bios/` and `mods/`: what an add-on stages under `mods/` with
`tekken3_addon_stage` goes into it, and nothing else from `addons/<id>/`. Files the add-on reads from its own folder
on PC are not on the phone: stage the ones it needs under `mods/`, and keep large ones (music) out, since the phone
keeps a second copy of the APK's data after installing it.

### Rebuilds

The setup asks for **Update & play** when an add-on is added or removed, or when its `addon.cmake` changes: change
it (a version line) when you publish an update.

### What stays the game's

Everything else the game has (guest addresses, its own functions and files, `.setup/`) may change from one release
to the next. An add-on that relies on more than the above says so in its own documentation and checks it when it
builds.
