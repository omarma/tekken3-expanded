#!/usr/bin/env python3
"""PPSSPP's VFPU tables (assets/vfpu/*.dat), read by tools/psp/dr_pose_a3.py for DR's animations.

    python tools/ppsspp_vfpu.py [CHOICE]      prints the folder found, or why there is none

B162 (GH#206): the 1.5.0 search looked in Program Files of C: and beside a PPSSPP on the PATH only;
a portable PPSSPP (the zip), one on another drive, or one in a Linux package outside those few folders
was not found. Here, in order: the player's choice (the setup's "PPSSPP folder", --ppsspp: PPSSPP's
folder, its program, its assets or vfpu folder, its .app), PPSSPP_VFPU, then a search:
- everywhere: beside a PPSSPP on the PATH (its link followed, ../share/ppsspp for a package);
- Windows: Program Files, Program Files (x86) and the root folders named *ppsspp* of every local
  drive, the uninstall and App Paths entries of the registry, the PPSSPP shortcuts of the desktop
  and the Start menu, Scoop, Chocolatey, the *ppsspp* folders of the home, Desktop, Downloads and
  Documents (a portable zip extracted there), RetroArch's system/PPSSPP;
- Linux: /usr/share, /usr/local/share, /usr/share/games, /opt, ~/.local/share, Flatpak
  org.ppsspp.PPSSPP (system and user), Snap, the *ppsspp* folders of the home and Downloads,
  RetroArch's system/PPSSPP. An AppImage keeps its files inside it: it is only named in the message
  (extract it with --appimage-extract, then choose squashfs-root);
- macOS: PPSSPP*.app in /Applications and ~/Applications.
B184 (GH#238): in a distrobox or toolbox container (a Steam Deck's setup), the host's own folders are
under /run/host only: its system Flatpak (/run/host/var/lib/flatpak, an older EmuDeck's PPSSPP), its
packages, and its home when the container has a home of its own. They are searched too, a host path
pasted as the choice is read through /run/host, and a Flatpak's app folder can be chosen as it is.
A folder counts only with all the tables dr_pose_a3 reads (TABLES). Nothing is copied from PPSSPP.
"""
import os, shutil, struct, sys
from pathlib import Path

# The tables tools/psp/dr_pose_a3.py reads (its _SinLut and _asin_lut).
TABLES = ('vfpu_sin_lut8192', 'vfpu_sin_lut_delta', 'vfpu_sin_lut_interval_delta', 'vfpu_sin_lut_exceptions',
          'vfpu_asin_lut65536', 'vfpu_asin_lut_indices', 'vfpu_asin_lut_deltas')
WINDOWS = os.name == 'nt'
MAC = sys.platform == 'darwin'
EXES = ('PPSSPPWindows64.exe', 'PPSSPPWindows.exe', 'PPSSPPSDL', 'PPSSPPQt', 'ppsspp', 'PPSSPP')
FLATPAK = 'org.ppsspp.PPSSPP'
# The host's root folder seen from a distrobox / toolbox container (B184); the home is shared by default.
HOST = Path('/run/host')
# Where the tables sit below a PPSSPP folder: its zip or install (assets/vfpu), its assets folder,
# a .app, a Linux prefix (/usr, Flatpak's files, a Snap), RetroArch's system/PPSSPP (vfpu).
BELOW = ('.', 'vfpu', 'assets/vfpu', 'Contents/Resources/assets/vfpu', 'share/ppsspp/assets/vfpu',
         'share/games/ppsspp/assets/vfpu', 'usr/share/ppsspp/assets/vfpu', 'usr/share/games/ppsspp/assets/vfpu',
         'files/share/ppsspp/assets/vfpu', 'ppsspp/assets/vfpu', 'bin/assets/vfpu', 'usr/bin/assets/vfpu')


def tables_in(folder):
    """folder itself, when it holds every table (a .dat each, not empty)."""
    try:
        return folder if all((folder / f'{t}.dat').is_file() and (folder / f'{t}.dat').stat().st_size
                             for t in TABLES) else None
    except OSError:
        return None


def vfpu_below(path, deeper=True):
    """The vfpu folder of a PPSSPP given as its folder, program, assets or vfpu folder, .app, or
    the folder a zip was extracted into (one level down: ppsspp_win/, PPSSPP.app). None if none."""
    if not path: return None
    p = Path(os.path.expandvars(str(path).strip().strip('"'))).expanduser()
    p = on_host(p)
    try:
        if p.is_file(): p = p.parent
        if not p.is_dir(): return None
    except OSError:
        return None
    for below in BELOW:
        found = tables_in(p / below)
        if found: return found.resolve()
    if deeper and FLATPAK.lower() in str(p).lower():          # a Flatpak's app folder: x86_64/stable/<commit>/files/...
        found = next(_walk(p, 10), None)
        if found: return found.resolve()
    if deeper:
        try:
            children = sorted(c for c in p.iterdir() if c.is_dir())
        except OSError:
            children = []
        for c in children[:200]:
            found = vfpu_below(c, deeper=False)
            if found: return found
    return None


def in_container():
    """Running in a distrobox / toolbox container (Linux), the host's folders under HOST."""
    try:
        return not (WINDOWS or MAC) and HOST.is_dir()
    except OSError:
        return False


def on_host(p):
    """p, or the same host path seen from the container (/var/lib/flatpak/... -> /run/host/var/lib/flatpak/...)
    when p is not there and the host's is (a path copied from the Steam Deck's own file manager)."""
    try:
        if p.exists() or not p.anchor or not in_container(): return p
        q = HOST / p.relative_to(p.anchor)
        return q if q.exists() else p
    except (OSError, ValueError):
        return p


def roots():
    """/ and, in a container, the host's root."""
    return [Path('/')] + ([HOST] if in_container() else [])


def flatpak_homes(home):
    """The homes whose ~/.local/share/flatpak may hold PPSSPP: this one and, in a container, the host's
    (/run/host/home/<user>, Fedora Atomic's /run/host/var/home/<user>; a distrobox made with --home)."""
    out = [home]
    if in_container():
        user = os.environ.get('USER') or os.environ.get('LOGNAME') or home.name
        out += [HOST / home.relative_to(home.anchor)] if home.anchor else []
        out += [HOST / 'home' / user, HOST / 'var/home' / user]
    return out


def old_ppsspp(path):
    """A PPSSPP folder without the tables (a PPSSPP older than its assets/vfpu), else None."""
    p = Path(path)
    try:
        if p.is_file(): p = p.parent
        return p if (p / 'assets').is_dir() and not (p / 'assets/vfpu').is_dir() else None
    except OSError:
        return None


# ---------------------------------------------------------------- where to look
def _named(folder, word='ppsspp'):
    """folder's subfolders whose name holds word (any case)."""
    try:
        return sorted(c for c in Path(folder).iterdir() if word in c.name.lower() and c.is_dir())
    except OSError:
        return []


def _on_path():
    for exe in EXES:
        w = shutil.which(exe)
        if not w: continue
        yield Path(w).parent
        real = Path(w).resolve().parent                     # a link (/usr/bin -> ..., Scoop's shims)
        yield real
        yield real.parent                                   # bin/ -> share/ppsspp/assets (BELOW)


def _drives():
    """The local drives (fixed and removable: no network or optical one, which can be slow)."""
    if not WINDOWS: return []
    import ctypes
    k = ctypes.windll.kernel32
    mask = k.GetLogicalDrives()
    out = []
    for i in range(26):
        if mask >> i & 1:
            root = f'{chr(65 + i)}:\\'
            if k.GetDriveTypeW(root) in (2, 3): out.append(Path(root))
    return out


def _registry():
    """PPSSPP's uninstall entries (InstallLocation, DisplayIcon) and App Paths."""
    if not WINDOWS: return
    import winreg
    hives = (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER)
    for hive in hives:
        for key in (r'Software\Microsoft\Windows\CurrentVersion\Uninstall',
                    r'Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'):
            try:
                root = winreg.OpenKey(hive, key)
            except OSError:
                continue
            with root:
                for i in range(4096):
                    try:
                        name = winreg.EnumKey(root, i)
                    except OSError:
                        break
                    try:
                        with winreg.OpenKey(root, name) as sub:
                            values = {}
                            for v in ('DisplayName', 'InstallLocation', 'DisplayIcon', 'UninstallString'):
                                try:
                                    values[v] = str(winreg.QueryValueEx(sub, v)[0])
                                except OSError:
                                    pass
                    except OSError:
                        continue
                    if 'ppsspp' not in (values.get('DisplayName', '') + name).lower(): continue
                    if values.get('InstallLocation'): yield Path(values['InstallLocation'].strip('"'))
                    for v in ('DisplayIcon', 'UninstallString'):
                        if values.get(v): yield Path(values[v].split(',')[0].strip().strip('"')).parent
        for exe in ('PPSSPPWindows64.exe', 'PPSSPPWindows.exe'):
            try:
                with winreg.OpenKey(hive, rf'Software\Microsoft\Windows\CurrentVersion\App Paths\{exe}') as sub:
                    yield Path(str(winreg.QueryValueEx(sub, '')[0]).strip('"')).parent
            except OSError:
                pass


def lnk_target(path):
    """A Windows shortcut's target (its LinkInfo local path), or None. [MS-SHLLINK] 2.1-2.3."""
    try:
        b = Path(path).read_bytes()
        if len(b) < 76 or struct.unpack_from('<I', b, 0)[0] != 0x4C: return None
        flags = struct.unpack_from('<I', b, 20)[0]
        at = 76
        if flags & 1: at += 2 + struct.unpack_from('<H', b, at)[0]          # HasLinkTargetIDList
        if not flags & 2: return None                                     # HasLinkInfo
        info = at
        head = struct.unpack_from('<I', b, info + 4)[0]
        if not struct.unpack_from('<I', b, info + 8)[0] & 1: return None   # VolumeIDAndLocalBasePath
        if head >= 0x24:
            o = struct.unpack_from('<I', b, info + 28)[0]                  # LocalBasePathOffsetUnicode
            start = end = info + o
            while b[end:end + 2] != b'\0\0':
                if end >= len(b): return None
                end += 2
            return Path(b[start:end].decode('utf-16-le'))
        o = struct.unpack_from('<I', b, info + 16)[0]                      # LocalBasePathOffset
        return Path(b[info + o:b.index(b'\0', info + o)].decode('mbcs' if WINDOWS else 'latin-1'))
    except (OSError, ValueError, struct.error, UnicodeDecodeError, LookupError):
        return None


def _shortcuts(home):
    folders = [home / 'Desktop', home / 'OneDrive/Desktop', Path(os.environ.get('PUBLIC', r'C:\Users\Public')) / 'Desktop']
    for base in (os.environ.get('APPDATA'), os.environ.get('ProgramData')):
        if base: folders.append(Path(base) / 'Microsoft/Windows/Start Menu/Programs')
    for folder in folders:
        try:
            links = [l for pattern in ('*.lnk', '*/*.lnk') for l in folder.glob(pattern) if 'ppsspp' in l.name.lower()]
        except OSError:
            continue
        for link in links:
            target = lnk_target(link)
            if target: yield target.parent


def _walk(folder, depth=5):
    """vfpu folders below folder, depth levels at most (a Flatpak or Snap's own layout)."""
    try:
        children = [c for c in Path(folder).iterdir() if c.is_dir() and not c.is_symlink()]
    except OSError:
        return
    for c in sorted(children):
        if c.name == 'vfpu' and tables_in(c): yield c
        elif depth > 1: yield from _walk(c, depth - 1)


def places(home=None):
    """The folders to try, in order (a folder may come twice: vfpu_dir keeps the first)."""
    home = Path(home) if home else Path.home()
    yield from _on_path()
    personal = [home, home / 'Desktop', home / 'Downloads', home / 'Documents', home / 'Games', home / 'Applications',
                home / 'OneDrive/Desktop', home / 'OneDrive/Documents']
    if WINDOWS:
        env = os.environ
        for base in (env.get('ProgramFiles'), env.get('ProgramFiles(x86)'), env.get('ProgramW6432'),
                     env.get('LOCALAPPDATA') and str(Path(env['LOCALAPPDATA']) / 'Programs')):
            if base: yield Path(base) / 'PPSSPP'
        yield from _registry()
        for drive in _drives():
            for pf in ('Program Files', 'Program Files (x86)'):
                yield drive / pf / 'PPSSPP'
                yield from _named(drive / pf)
            yield from _named(drive)
            for games in ('Games', 'Emulators', 'Emulation', 'Emulateurs', 'Jeux'):
                yield from _named(drive / games)
        yield from _shortcuts(home)
        scoop = Path(env.get('SCOOP') or home / 'scoop')
        for base in (scoop, Path(env.get('SCOOP_GLOBAL') or Path(env.get('ProgramData', r'C:\ProgramData')) / 'scoop')):
            for app in _named(base / 'apps'): yield app / 'current'
        choco = Path(env.get('ChocolateyInstall') or Path(env.get('ProgramData', r'C:\ProgramData')) / 'chocolatey')
        for app in _named(choco / 'lib'): yield app / 'tools'
        for folder in personal: yield from _named(folder)
        for base in (env.get('APPDATA') and Path(env['APPDATA']) / 'RetroArch', Path(r'C:\RetroArch-Win64'),
                     Path(r'C:\RetroArch')):
            if base: yield base / 'system/PPSSPP'
    elif MAC:
        for apps in (Path('/Applications'), home / 'Applications'):
            for app in sorted(apps.glob('PPSSPP*.app')) if apps.is_dir() else []: yield app
        for folder in personal: yield from _named(folder)
        yield home / 'Library/Application Support/RetroArch/system/PPSSPP'
    else:
        for root in roots():
            yield from (root / 'usr/share/ppsspp', root / 'usr/local/share/ppsspp', root / 'usr/share/games/ppsspp',
                        root / 'usr/local/share/games/ppsspp')
        yield home / '.local/share/ppsspp'
        for root in roots(): yield from _named(root / 'opt')
        flatpaks = [root / 'var/lib/flatpak' for root in roots()] + [h / '.local/share/flatpak' for h in flatpak_homes(home)]
        for base in flatpaks:
            app = base / 'app' / FLATPAK / 'current/active/files'
            yield app
            if app.is_dir(): yield from _walk(app)
        for root in roots():
            for snap in _named(root / 'snap'):
                yield snap / 'current'
                if (snap / 'current').is_dir(): yield from _walk(snap / 'current')
        for folder in personal: yield from _named(folder)
        for base in (home / '.config/retroarch', home / '.var/app/org.libretro.RetroArch/config/retroarch'):
            yield base / 'system/PPSSPP'


def search(home=None):
    """(the vfpu folder found by the search, or None; PPSSPP folders seen without the tables)."""
    old = []
    for place in places(home):
        found = vfpu_below(place)
        if found: return found, old
        o = old_ppsspp(place) if place else None
        if o and o not in old: old.append(o)
    return None, old


def vfpu_dir(choice=None, home=None):
    """The vfpu folder: the player's choice, PPSSPP_VFPU, else the search. None when there is none."""
    for given in (choice, os.environ.get('PPSSPP_VFPU')):
        found = vfpu_below(given)
        if found: return found
    return search(home)[0]


def appimages(home=None):
    """PPSSPP AppImages where players keep them (Linux): their files are inside, unreadable here."""
    if WINDOWS or MAC: return []
    home = Path(home) if home else Path.home()
    out = []
    for folder in (home / 'Applications', home / 'Downloads', home, home / 'Desktop', home / '.local/bin'):
        try:
            out += sorted(f for f in folder.iterdir() if 'ppsspp' in f.name.lower() and f.name.lower().endswith('.appimage'))
        except OSError:
            pass
    return out


def where_to_point():
    """What to choose with Browse, for this system."""
    if WINDOWS: return 'the folder of PPSSPPWindows64.exe (an installed or portable PPSSPP, on any drive)'
    if MAC: return 'PPSSPP.app, or its folder'
    flatpak = f'flatpak/app/{FLATPAK}'
    if in_container():
        return (f"PPSSPP's folder. On a Steam Deck (EmuDeck's PPSSPP, a Flatpak) paste ~/.local/share/{flatpak}, "
                f"or {HOST}/var/lib/{flatpak} for a Flatpak installed for all users")
    return (f"PPSSPP's assets folder (for a package, usually /usr/share/ppsspp; for the Flatpak, "
            f"~/.local/share/{flatpak} or /var/lib/{flatpak})")


def problem(choice=None, home=None):
    """Why no tables are found, and what to do; None when they are."""
    if vfpu_dir(choice, home): return None
    p = Path(str(choice).strip().strip('"')).expanduser() if choice else None
    if p and p.name.lower().endswith('.appimage'):
        return ("PPSSPP's AppImage keeps its files inside it, out of reach of the setup. Extract it (run it once "
                "with --appimage-extract), then click Browse beside PPSSPP folder and choose the squashfs-root folder it makes.")
    lead = (f'No PPSSPP VFPU tables (assets/vfpu) in {choice}. ' if choice else
            "PPSSPP was not found on this computer: its VFPU tables (assets/vfpu) are needed to read DR's animations. ")
    old = ([o for o in [old_ppsspp(p)] if o] if p and p.exists() else []) or search(home)[1]
    if old:
        return lead + (f'The PPSSPP in {old[0]} has no assets/vfpu folder: it is too old. Install the latest PPSSPP '
                       f'(ppsspp.org), then click Browse beside PPSSPP folder if the setup still does not find it.')
    tail = ''
    images = appimages(home)
    if images:
        tail = (f' Your PPSSPP AppImage ({images[0].name}) keeps its files inside it: extract it (run it once with '
                f'--appimage-extract) and choose the squashfs-root folder it makes.')
    return lead + f'Click Browse beside PPSSPP folder and choose {where_to_point()}.' + tail


if __name__ == '__main__':
    choice = sys.argv[1] if len(sys.argv) > 1 else None
    found = vfpu_dir(choice)
    print(found if found else problem(choice))
    sys.exit(0 if found else 1)
