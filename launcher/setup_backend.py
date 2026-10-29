"""Local first-run setup. Downloads only pinned tools; game data stays local."""
from __future__ import annotations
from pathlib import Path, PureWindowsPath
import argparse, fnmatch, hashlib, json, os, re, shutil, struct, subprocess, sys, time
import urllib.request, urllib.error, zipfile

ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'.setup'
BUILD=ROOT/'build-release'
WINDOWS=os.name=='nt'
EXE=BUILD/('Tekken_3_Expanded.exe' if WINDOWS else 'Tekken_3_Expanded')
# A new value makes existing installs generate and rebuild once (generated
# code, setup). A change of the TTT1 import's output does not need it: that is
# tools/ttt1_import_version.py's TTT1_IMPORT_VERSION.
RELEASE='0.1.4-easy-setup'
class _Lock(dict):
    """launcher/tools.lock.json, the pinned downloads: Windows only (the compiler
    pack), read when first needed, so macOS and Linux never need it."""
    def __missing__(self,key):
        if not self:
            path=ROOT/'launcher/tools.lock.json'
            try:self.update(json.loads(path.read_text(encoding='utf-8')))
            except (OSError,ValueError) as error:
                raise SetupError(f'{path.name} is missing or damaged: get this folder again (git pull, or the whole ZIP).') from error
        return dict.__getitem__(self,key)
LOCK=_Lock()

class SetupError(Exception):
    pass

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

TEXT=False    # --text: plain lines for a terminal instead of the launcher's JSON events

def emit(event='status', **data):
    if TEXT:
        line='  '.join(x for x in (data.get('message'),data.get('detail')) if x)
        if line:print(('Error: ' if event=='error' else '')+line,flush=True)
        return
    print(json.dumps({'event':event,**data}),flush=True)

def save_json(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
    temp.replace(path)

def load_json(path):
    try:return json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError):return {}

def ready():
    state=load_json(STATE/'ready.json')
    if state.get('release')!=RELEASE or not EXE.is_file():return False
    if not (ROOT/'disc/Tekken 3 (USA).cue').is_file():return False
    try:
        if digest(EXE)!=state.get('exe_sha256'):return False
        # An older TTT1 import (after a git pull or a new release) needs the setup again.
        if state.get('ttt1',state.get('jun')) and not ttt1_current(INSTALLED):return False
        # Cinematics older than this checkout (tools/ttt_cinematics.py's CINEMATICS_VERSION).
        if state.get('ttt_cinematics') and not cinematics_current():return False
        # Arcade stage packs older than this checkout (tools/arcade_stages/version.py),
        # or never made for an install set up with tekken3.zip before they existed.
        wanted=state.get('arcade_stages',bool(load_json(STATE/'last-inputs.json').get('tekken3')))
        if wanted and not arcade_stages_current(ARCADE_STAGES_INSTALLED):return False
        # TTT's stages and their music, older than this checkout, or never made
        # for an install set up with the TTT1 characters before they existed.
        if not ttt_stages_ready(state):return False
    except OSError:return False
    return True

def import_version():
    """tools/ttt1_import_version.py: TTT1_IMPORT_VERSION, the stamp, the update steps."""
    tools=str(Path(__file__).resolve().parents[1]/'tools')
    if tools not in sys.path:sys.path.insert(0,tools)
    import ttt1_import_version
    return ttt1_import_version

def ttt1_current(folder):
    V=import_version()
    return ttt1_ready(folder) and V.read_stamp(folder)>=V.TTT1_IMPORT_VERSION

def android_ready():
    """A game prepared for Android alone (prepare(..., pc=False)): its generated
    code, disc and current imports are here, without the PC build."""
    state=load_json(STATE/'android.json')
    if state.get('ttt1') and not ttt1_current(ROSTER):return False
    if state.get('arcade_stages') and not arcade_stages_current(ARCADE_STAGES_PACKS):return False
    if state.get('ttt_stages') and not ttt_stages_current(TTT_STAGES_PACKS):return False
    if state.get('ttt_music') and not ttt_music_current(TTT_MUSIC_PACK):return False
    if state.get('ttt_ps2_music') and not ttt_ps2_music_current(TTT_PS2_MUSIC_PACK):return False
    if state.get('ttt_ps2_laser') and not ttt_ps2_laser_current(TTT_PS2_LASER_PACK):return False
    return (state.get('release')==RELEASE and (ROOT/'generated/SLUS_004.02_dispatch.c').is_file()
            and (ROOT/'disc/Tekken 3 (USA).cue').is_file())

def ttt1_ready(folder):
    """A TTT1 characters catalogue (tools/ttt1_stage_roster.py) with every
    listed character's combat pack."""
    listed=folder/'guests.txt'
    # One guest a line: its key, then its moveset and arena columns.
    keys=[l.split()[0] for l in listed.read_text(encoding='utf-8').splitlines() if l.split()] if listed.is_file() else []
    return bool(keys) and all((folder/f'{k.capitalize()}-TTT1-combat.jmv').is_file() for k in keys)

# The TTT1 import's catalogue, and its copy beside the game, which stays when
# "free up disk space" deletes workspace/.
WORK=ROOT/'workspace/ttt1-import'
ROSTER=WORK/'roster'
INSTALLED=BUILD/'mods/ttt1'
# TTT Cinematics (tools/ttt_cinematics.py), beside the catalogue.
CINEMATICS=BUILD/'mods/ttt-cinematics'
# The same for the Android game set up alone (Build Android APK): the APK
# takes it as mods/ttt-cinematics (tools/android/make_apk.py).
ANDROID_CINEMATICS=ROOT/'workspace/ttt-cinematics'

# Arcade Stages (tools/arcade_stages/install.py): the stage packs made from
# tekken3.zip, which CMakeLists.txt stages beside the game (PC and Android),
# and their copy there, which stays when "free up disk space" deletes workspace/.
ARCADE_STAGES_PACKS=ROOT/'workspace/arcade-stages/pack'
ARCADE_STAGES_INSTALLED=BUILD/'mods/arcade-stages'

def arcade_stages_version():
    """tools/arcade_stages/version.py: ARCADE_STAGES_VERSION and the stamp."""
    if 'arcade_stages_version' not in sys.modules:
        import importlib.util
        spec=importlib.util.spec_from_file_location('arcade_stages_version',Path(__file__).resolve().parents[1]/'tools/arcade_stages/version.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        sys.modules['arcade_stages_version']=module
    return sys.modules['arcade_stages_version']

def arcade_stages_current(folder):
    return arcade_stages_version().current(folder)

def arcade_stages_made(pc=True):
    """This version's arcade stage packs are here: tekken3.zip is not read for them."""
    if arcade_stages_current(ARCADE_STAGES_PACKS):return True
    # Only beside the game (workspace/ freed): the build keeps that copy.
    return pc and not (ARCADE_STAGES_PACKS/'version.txt').exists() and arcade_stages_current(ARCADE_STAGES_INSTALLED)

def prepare_arcade_stages(tekken3,env,pc=True):
    """The 13 arcade stage packs from tekken3.zip, unless this version is
    already there. Optional: a failure only keeps the PS1 stages. True when
    the packs are ready."""
    if arcade_stages_made(pc):return True
    emit(message='Preparing the arcade stages',detail='Converting the Tekken 3 arcade stages from your tekken3.zip.')
    try:
        run([sys.executable,ROOT/'tools/arcade_stages/install.py','--tekken3',tekken3,'--out',ARCADE_STAGES_PACKS],environment=env,
            friendly='The arcade stages could not be prepared.')
    except SetupError:
        emit(message='Skipping the arcade stages',detail='They could not be prepared from your tekken3.zip (see the setup log). The game keeps the PS1 stages.')
        return False
    return True

# TTT Stages (TTT Stages S7): TTT's 15 stage packs (tools/arcade_stages/install.py
# --ttt1) and their music (tools/ttt_stages/music_install.py), made from
# tektagt.zip with the TTT1 characters, staged by CMakeLists.txt beside the game
# (PC and Android) as mods/ttt-stages and mods/ttt-music; their copies there stay
# when "free up disk space" deletes workspace/.
TTT_STAGES_PACKS=ROOT/'workspace/ttt-stages/pack'
TTT_STAGES_INSTALLED=BUILD/'mods/ttt-stages'
TTT_MUSIC_PACK=ROOT/'workspace/ttt-stages/music-pack'
TTT_MUSIC_INSTALLED=BUILD/'mods/ttt-music'
# Their PS2 version (tools/ttt_stages/ps2_music_install.py), copied from the
# player's TTT PS2 disc when one is given: mods/ttt-ps2-music.
TTT_PS2_MUSIC_PACK=ROOT/'workspace/ttt-stages/ps2-music-pack'
TTT_PS2_MUSIC_INSTALLED=BUILD/'mods/ttt-ps2-music'
# Devil's and Angel's PS2 laser textures (tools/ps2/ttt_laser_install.py),
# read on the same disc: mods/ttt-ps2-laser.
TTT_PS2_LASER_PACK=ROOT/'workspace/ttt-ps2/laser-pack'
TTT_PS2_LASER_INSTALLED=BUILD/'mods/ttt-ps2-laser'

def laser_version():
    """tools/ps2/laser_version.py: LASER_VERSION and the stamp."""
    if 'ttt_laser_version' not in sys.modules:
        import importlib.util
        spec=importlib.util.spec_from_file_location('ttt_laser_version',Path(__file__).resolve().parents[1]/'tools/ps2/laser_version.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        sys.modules['ttt_laser_version']=module
    return sys.modules['ttt_laser_version']

def ttt_music_version():
    """tools/ttt_stages/music_version.py: MUSIC_VERSION and the stamp."""
    if 'ttt_music_version' not in sys.modules:
        import importlib.util
        spec=importlib.util.spec_from_file_location('ttt_music_version',Path(__file__).resolve().parents[1]/'tools/ttt_stages/music_version.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        sys.modules['ttt_music_version']=module
    return sys.modules['ttt_music_version']

def ttt_stages_current(folder):
    return arcade_stages_version().ttt_current(folder)

def ttt_music_current(folder):
    return ttt_music_version().current(folder)

def ttt_ps2_music_current(folder):
    return ttt_music_version().ps2_current(folder)

def ttt_ps2_laser_current(folder):
    return laser_version().current(folder)

def ttt_stages_ready(state):
    """ready()'s check: wanted (ready.json, or an install with the TTT1
    characters from before TTT Stages) means current. The PS2 music and the
    PS2 laser: wanted by an install from before them that was given the TTT
    PS2 disc."""
    before=bool(state.get('ttt1',state.get('jun')))
    if state.get('ttt_stages',before) and not ttt_stages_current(TTT_STAGES_INSTALLED):return False
    if state.get('ttt_music',before) and not ttt_music_current(TTT_MUSIC_INSTALLED):return False
    disc=before and bool(load_json(STATE/'last-inputs.json').get('ttt_disc'))
    if state.get('ttt_ps2_music',disc) and not ttt_ps2_music_current(TTT_PS2_MUSIC_INSTALLED):return False
    if state.get('ttt_ps2_laser',disc) and not ttt_ps2_laser_current(TTT_PS2_LASER_INSTALLED):return False
    return True

def ttt_ps2_music_made(pc=True):
    """This version's PS2 music of the TTT stages is here: the disc is not read for it."""
    return ttt_ps2_music_current(TTT_PS2_MUSIC_PACK) or (pc and not (TTT_PS2_MUSIC_PACK/'version.txt').exists()
                                                         and ttt_ps2_music_current(TTT_PS2_MUSIC_INSTALLED))

def prepare_ttt_ps2_music(ttt_disc,env,pc=True,keep=False):
    """The TTT stages' PS2 music (GAME OPTION's BGM SELECT: REMIXED), copied
    from the TTT PS2 disc unless this version is already there. Optional:
    without the disc, an earlier copy goes and the stages keep their arcade
    music; a failure only does the same. keep: the disc was given but set
    aside as unusable this time (B85), a current copy stays. Ready or not."""
    if not ttt_disc:
        if keep:return ttt_ps2_music_made(pc)
        for folder in (TTT_PS2_MUSIC_PACK,*([TTT_PS2_MUSIC_INSTALLED] if pc else [])):shutil.rmtree(folder,ignore_errors=True)
        return False
    if ttt_ps2_music_made(pc):return True
    if not Path(ttt_disc).is_file():
        log_line(f"{ttt_disc}: missing, the TTT stages' PS2 music skipped")
        emit(message="Skipping the TTT stages' PS2 music",detail='Your Tekken Tag Tournament PS2 disc is no longer where the setup found it. Choose it again to add it.')
        return False
    emit(message="Preparing the TTT stages' PS2 music",detail='Copying the music of the Tekken Tag Tournament stages from your PS2 disc.')
    try:run([sys.executable,ROOT/'tools/ttt_stages/ps2_music_install.py','--ttt-disc',ttt_disc,'--out',TTT_PS2_MUSIC_PACK],
            environment=env,friendly="The TTT stages' PS2 music could not be prepared.")
    except SetupError:
        emit(message="Skipping the TTT stages' PS2 music",detail='It could not be copied from your PS2 disc (see the setup log). The TTT stages keep their arcade music.')
        return False
    return True

def ttt_ps2_laser_made(pc=True):
    """This version's PS2 laser textures are here: the disc is not read for them."""
    return ttt_ps2_laser_current(TTT_PS2_LASER_PACK) or (pc and not (TTT_PS2_LASER_PACK/'version.txt').exists()
                                                         and ttt_ps2_laser_current(TTT_PS2_LASER_INSTALLED))

def prepare_ttt_ps2_laser(ttt_disc,env,pc=True,keep=False):
    """The TTT PS2 effects: Devil's and Angel's laser textures and the
    Mishima's strong-hit effects, read on the TTT PS2 disc and converted
    (tools/ps2/ttt_laser_install.py) unless this version is already there.
    Optional, as the PS2 music: without the disc an earlier copy goes; a
    failure, or another version of the disc, only keeps the arcade's yellow
    beam and TTT1's hit effects. keep: as for the PS2 music. Ready or not."""
    if not ttt_disc:
        if keep:return ttt_ps2_laser_made(pc)
        for folder in (TTT_PS2_LASER_PACK,*([TTT_PS2_LASER_INSTALLED] if pc else [])):shutil.rmtree(folder,ignore_errors=True)
        return False
    if ttt_ps2_laser_made(pc):return True
    if not Path(ttt_disc).is_file():
        log_line(f"{ttt_disc}: missing, the TTT PS2 effects (Devil's and Angel's laser, the Mishima's hit effects) skipped")
        emit(message="Skipping the TTT PS2 effects",detail='Your Tekken Tag Tournament PS2 disc is no longer where the setup found it. Choose it again to add it.')
        return False
    emit(message="Preparing the TTT PS2 effects",detail="Reading Devil's and Angel's laser and the strong-hit effects of Jin, Heihachi, Kazuya, Devil and Angel on your PS2 disc.")
    try:run([sys.executable,ROOT/'tools/ps2/ttt_laser_install.py','--ttt-disc',ttt_disc,'--out',TTT_PS2_LASER_PACK],
            environment=env,friendly="The TTT PS2 effects could not be prepared.")
    except SetupError:
        emit(message="Skipping the TTT PS2 effects",detail="They could not be read on your PS2 disc (see the setup log). Devil's and Angel's lasers keep the arcade's yellow beam, the Mishima their TTT1 hit effects.")
        return False
    return True

def prepare_ttt_stages(ttt,env,pc=True):
    """TTT's stage packs and their music from tektagt.zip, each unless this
    version is already there. Optional: a failure, or tektagt.zip no longer
    where it was, only keeps Tekken 3's stages and music (the STAGES row stays
    hidden without the packs). (stages ready, music ready)."""
    made=[]
    for what,current,packs,installed,command in (
            ('stages',ttt_stages_current,TTT_STAGES_PACKS,TTT_STAGES_INSTALLED,
             [ROOT/'tools/arcade_stages/install.py','--ttt1',ttt,'--out',TTT_STAGES_PACKS]),
            ('music',ttt_music_current,TTT_MUSIC_PACK,TTT_MUSIC_INSTALLED,
             [ROOT/'tools/ttt_stages/music_install.py','--ttt1',ttt,'--out',TTT_MUSIC_PACK])):
        # Only beside the game (workspace/ freed): the build keeps that copy.
        if current(packs) or (pc and not (packs/'version.txt').exists() and current(installed)):
            made.append(True);continue
        name='the TTT stages' if what=='stages' else "the TTT stages' music"
        if not Path(ttt).is_file():
            log_line(f'{ttt}: missing, {name} skipped')
            emit(message=f'Skipping {name}',detail='Your tektagt.zip is no longer where the setup found it. Choose it again to add them.')
            made.append(False);continue
        emit(message=f'Preparing {name}',detail=('Converting the Tekken Tag Tournament arcade stages' if what=='stages'
             else 'Preparing the music of the Tekken Tag Tournament arcade stages')+' from your tektagt.zip.')
        try:run([sys.executable,*command],environment=env,friendly=f'{name[0].upper()+name[1:]} could not be prepared.')
        except SetupError:
            emit(message=f'Skipping {name}',detail="They could not be prepared from your tektagt.zip (see the setup log). The game keeps Tekken 3's stages and music.")
            made.append(False)
        else:made.append(True)
    return tuple(made)

def cinematics_current():
    tools=str(ROOT/'tools')
    if tools not in sys.path:sys.path.insert(0,tools)
    import ttt_cinematics as C
    # triggers.txt: the engine's table, the feature's only settings.
    return (CINEMATICS/'triggers.txt').is_file() and C.read_stamp(CINEMATICS)>=C.CINEMATICS_VERSION

def cinematics_off(folder):
    """The option turned off: the feature finds no trigger table and plays
    nothing (cinematics.txt: the old way's settings, before 1.3.0)."""
    for name in ('triggers.txt','cinematics.txt'):
        try:(folder/name).unlink()
        except FileNotFoundError:pass

def cinematics_models_ready():
    """Jin's models for the TTT cinematics, made once from the import's work files."""
    return all((CINEMATICS/f'{m}-TTT1-arcade-P1.{e}').is_file() for m in ('JinPlain','DevilJinEnd') for e in ('3dm','relocs','tim'))

def ttt1_plan(tekken3=None,cinematics=False):
    """What brings the TTT1 characters to this import version: ('current',[])
    nothing; ('update',steps) those update steps (tools/ttt1_import_version.py),
    on the roster or, workspace/ deleted, on a copy of build-release/mods/ttt1;
    ('import',[]) a new import from the ROM."""
    V=import_version()
    folder=ROSTER if ttt1_ready(ROSTER) else INSTALLED if ttt1_ready(INSTALLED) else None
    if folder is None:return 'import',[]
    # Options the earlier setup was run without.
    if tekken3 and not any(p.is_file() for p in (ROOT/'workspace/difficulty/levels.bin',BUILD/'mods/difficulty/levels.bin')):
        return 'import',[]
    # The TTT cinematics need Jin's models, made from the work files.
    if cinematics and not cinematics_models_ready() and not ((WORK/'ttt1/bankedroms.bin').is_file() and (WORK/'captures').is_dir()):
        return 'import',[]
    steps=V.update_steps(V.read_stamp(folder))
    if steps is None:return 'import',[]
    work=(WORK/'ttt1/bankedroms.bin').is_file() and (WORK/'captures').is_dir() and folder==ROSTER
    if not work and any(V.STEPS[s][0]=='workspace' for s in steps):return 'import',[]
    return ('update' if steps else 'current'),steps

def update_ttt1(steps,env):
    """tools/ttt1_setup.py --update: the update steps, no MAME, each in the log."""
    V=import_version()
    if not ttt1_ready(ROSTER):
        # workspace/ was deleted: work on a copy of the installed catalogue.
        log_line(f'TTT1 update: {ROSTER} missing, working on a copy of {INSTALLED}')
        shutil.rmtree(ROSTER,ignore_errors=True);shutil.copytree(INSTALLED,ROSTER)
    log_line('TTT1 update steps: '+', '.join(f'{s} ({V.STEPS[s][1]})' for s in steps))
    emit(message='Updating the TTT1 characters',detail=', '.join(V.STEPS[s][1] for s in steps)+'. No new import needed.')
    run([sys.executable,ROOT/'tools/ttt1_setup.py','--update','--roster',ROSTER],environment=env,
        friendly="The TTT1 characters' update could not finish. Open the setup log for details, then click Try again.")

def install_roster():
    """The roster beside the game, replacing the older copy (the build's own
    copy only adds files, and only when the executable is linked again)."""
    if not ttt1_ready(ROSTER):return
    temp=INSTALLED.with_name('ttt1.new')
    try:
        shutil.rmtree(temp,ignore_errors=True);shutil.copytree(ROSTER,temp)
        shutil.rmtree(INSTALLED,ignore_errors=True);temp.replace(INSTALLED)
    except OSError as error:
        log_line(str(error));raise SetupError('The TTT1 characters could not be copied beside the game. Close the game, then click Try again.') from error

def log_line(text):
    STATE.mkdir(exist_ok=True)
    with (STATE/'setup.log').open('a',encoding='utf-8') as f:f.write(text+'\n')

def run(command, *, environment=None, directory=ROOT, friendly='Setup could not finish.', timeout=None, only_code=None,
        progress='Preparing game files'):
    """friendly: the message for a failure; with only_code, for that exit code
    only, and any other failure shows the last line of the command's output.
    progress: the words before a build's step counter."""
    log_line('RUN '+subprocess.list2cmdline([str(x) for x in command]))
    with subprocess.Popen([str(x) for x in command],cwd=directory,env=environment,
            stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0) as process:
        # The launcher's Windows Job owns this worker and all its children.
        last=0;tail=''
        for line in process.stdout:
            log_line(line.rstrip())
            if line.strip():tail=line.strip()
            match=re.match(r'\[(\d+)/(\d+)\]',line)
            if match and time.monotonic()-last>.25:
                emit(detail=progress+': '+match[1]+' / '+match[2]);last=time.monotonic()
        code=process.wait(timeout=timeout)
    if code and only_code is not None and code!=only_code:
        raise SetupError(f'Setup stopped: {tail[-300:]} (details in {STATE/"setup.log"})')
    if code:raise SetupError(friendly)

def download(spec):
    cache=STATE/'downloads';cache.mkdir(parents=True,exist_ok=True)
    path=cache/spec['filename']
    if path.is_file() and digest(path)==spec['sha256']:return path
    temp=path.with_suffix(path.suffix+'.part')
    request=urllib.request.Request(spec['url'],headers={'User-Agent':'Tekken3-Easy-Setup/'+RELEASE})
    try:
        with urllib.request.urlopen(request,timeout=60) as response,temp.open('wb') as out:
            total=int(response.headers.get('Content-Length',spec['size']));received=0;last=0
            h=hashlib.sha256()
            while True:
                block=response.read(1024*1024)
                if not block:break
                out.write(block);h.update(block);received+=len(block)
                if received>spec['size']:raise SetupError('A tool download has an unexpected size. Please retry.')
                if time.monotonic()-last>.25:
                    emit(detail=f'{received/1048576:.0f} / {total/1048576:.0f} MB downloaded');last=time.monotonic()
    except (OSError,urllib.error.URLError) as error:
        log_line(str(error));raise SetupError('The download was interrupted. Check your connection and click Try again.') from error
    if received!=spec['size'] or h.hexdigest()!=spec['sha256']:
        raise SetupError('A downloaded tool failed its integrity check. Click Try again to download it again.')
    temp.replace(path)
    return path

def safe_extract(archive,destination):
    destination=destination.resolve();destination.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        seen=set();total=0
        for info in z.infolist():
            name=info.filename.replace('\\','/')
            relative=Path(name);windows=PureWindowsPath(name)
            target=(destination/relative).resolve()
            total+=info.file_size
            if (windows.drive or relative.is_absolute() or '..' in relative.parts or ':' in name
                or destination not in target.parents or name.casefold() in seen
                or (info.external_attr>>16)&0o170000==0o120000 or total>3*1024**3):
                raise SetupError('An unsafe tool archive was rejected.')
            seen.add(name.casefold())
        for info in z.infolist():
            target=destination/info.filename.replace('\\','/')
            if info.is_dir():target.mkdir(parents=True,exist_ok=True);continue
            target.parent.mkdir(parents=True,exist_ok=True)
            with z.open(info) as source,target.open('wb') as out:shutil.copyfileobj(source,out)

def installed(name,hint):
    found=shutil.which(name)
    if not found:raise SetupError(f'{name} is missing. {hint}')
    return found

def tools():
    """Windows: the pinned compiler pack (no installation). macOS / Linux:
    the installed cmake, ninja and compiler (brew install cmake ninja sdl3,
    xcode-select --install; on Linux, Setup Tekken 3.sh names the packages); None."""
    if not WINDOWS:
        mac=sys.platform=='darwin'
        for name in ('cmake','ninja'):installed(name,'On macOS: brew install cmake ninja sdl3' if mac else 'Run Setup Tekken 3.sh in a terminal: it names the packages to install.')
        if not (shutil.which('cc') or shutil.which('clang')):
            raise SetupError('No C compiler. '+('On macOS: xcode-select --install' if mac else 'Run Setup Tekken 3.sh in a terminal: it names the packages to install.'))
        return None
    folder=STATE/'tools/toolchain-1.0.10'
    marker=folder/'.ready.json'
    if (load_json(marker).get('archive_sha256')!=LOCK['toolchain']['sha256']
        or not all((folder/'bin'/name).is_file() for name in ('cmake.exe','clang.exe','clang++.exe','ninja.exe'))):
        emit(message='Getting the setup tools',detail='This only happens the first time.')
        archive=download(LOCK['toolchain'])
        emit(message='Unpacking the setup tools',detail='No system installation is needed.')
        safe_extract(archive,folder)
        if not (folder/'bin/cmake.exe').is_file():raise SetupError('The downloaded tools could not be prepared.')
        save_json(marker,{'archive_sha256':LOCK['toolchain']['sha256']})
    return folder

def prepare_textures():
    from PIL import Image
    emit(message='Preparing the included mods',detail='Skins and outfit gallery.')
    for record in load_json(ROOT/'tools/data/texture_payloads.json'):
        target=ROOT/record['path'];png=target.with_suffix('.png')
        if target.is_file() and digest(target)==record['sha256']:continue
        if digest(png)!=record['png_sha256']:raise SetupError('A bundled texture is damaged. Extract the download again.')
        with Image.open(png) as image:
            image=image.convert('RGBA')
            if record.get('crop'):image=image.crop(record['crop'])
            data=b'HDRGBA01'+struct.pack('<II',*image.size)+image.tobytes()
        if hashlib.sha256(data).hexdigest()!=record['sha256']:raise SetupError('A texture could not be prepared correctly.')
        temp=target.with_suffix('.tmp');temp.write_bytes(data);temp.replace(target)

def msf(text):
    m,s,f=(int(x) for x in text.split(':'));return (m*60+s)*75+f

def cue_for(disc):
    """A .bin chosen in place of its .cue: the .cue beside it that names it, if
    any. A single-file dump holds every track, and only its .cue says where
    track 1 (the one verified) ends."""
    if disc.suffix.lower()!='.bin':return disc
    for cue in sorted(disc.parent.glob('*.cue'))+sorted(disc.parent.glob('*.CUE')):
        try:text=cue.read_text(encoding='utf-8',errors='replace')
        except OSError:continue
        if any(m.lower()==disc.name.lower() for m in re.findall(r'FILE\s+"([^"]+)"',text,flags=re.I)):return cue
    return disc

def single_bin(disc):
    """A .cue whose tracks all sit in one .bin (a single-file dump): write one
    .bin per track, as the supported (Redump) set has them, and their .cue.
    A track's file starts at its INDEX 00 (pregap on the disc), else INDEX 01."""
    if disc.suffix.lower()!='.cue':return disc
    lines=disc.read_text(encoding='utf-8',errors='replace').splitlines()
    files=[l for l in lines if l.strip().upper().startswith('FILE')]
    if len(files)!=1:return disc
    image=disc.parent/re.search(r'"([^"]+)"',files[0])[1]
    tracks=[]
    for line in lines:
        w=line.split()
        if not w:continue
        if w[0].upper()=='TRACK':tracks.append(dict(number=int(w[1]),kind=w[2],index={},pregap=None))
        elif w[0].upper()=='INDEX' and tracks:tracks[-1]['index'][int(w[1])]=msf(w[2])
        elif w[0].upper()=='PREGAP' and tracks:tracks[-1]['pregap']=w[1]
    if len(tracks)<2:return disc
    size=image.stat().st_size//2352
    out=STATE/'disc-tracks';out.mkdir(parents=True,exist_ok=True)
    stem=image.stem;cue=[]
    starts=[t['index'].get(0,t['index'][1]) for t in tracks]+[size]
    emit(message='Preparing your disc',detail='Splitting the single-file dump into its tracks.')
    with image.open('rb') as src:
        for n,t in enumerate(tracks):
            name=f'{stem} (Track {t["number"]}).bin';src.seek(starts[n]*2352)
            with (out/name).open('wb') as dst:
                left=(starts[n+1]-starts[n])*2352
                while left:block=src.read(min(left,1<<24));dst.write(block);left-=len(block)
            cue+=[f'FILE "{name}" BINARY',f'  TRACK {t["number"]:02d} {t["kind"]}']
            if t['pregap']:cue.append(f'    PREGAP {t["pregap"]}')
            for i,at in sorted(t['index'].items()):
                r=at-starts[n];cue.append(f'    INDEX {i:02d} {r//4500:02d}:{r//75%60:02d}:{r%75:02d}')
    path=out/f'{stem}.cue';path.write_text('\n'.join(cue)+'\n',encoding='utf-8')
    return path

REQUIRED=('psxrecomp/psxrecomp_cli.py','psxrecomp/tools/sdk_progress.py','psxrecomp/runtime','psxrecomp/recompiler/CMakeLists.txt',
          'recomp-ui','tools/ttt1_import.py','tools/ttt1_setup.py','tools/ttt1_import_version.py','src','mods','CMakeLists.txt','game.toml')

def complete():
    """A partly extracted download (an interrupted unzip, an antivirus, or
    Windows' 260-character path limit) fails later with a confusing error."""
    missing=[p for p in REQUIRED if not (ROOT/p).exists()]
    if missing:raise SetupError('This folder is incomplete (missing: '+', '.join(missing[:4])+'). Extract the whole download again '
                                '(on Windows, to a short path such as C:\\Games, with 7-Zip or git clone), then run the setup again.')

# Mods removed from the game since an earlier release. An update unpacked over
# the older folder keeps their files, and an enabled package whose plugin is no
# longer built stops the launcher's Play (B86, GH#108, GH#137).
RETIRED_SOURCES=('mods/preloaded/packages/tekken3.visual.forest-hd','mods/assets/forest-hd',
                 'mods/preloaded/packages/tekken3.visual.jin-ttt1-hit-effect')
RETIRED_STAGED=('mods/packages/tekken3.visual.forest-hd','mods/forest-hd',
                'mods/packages/tekken3.visual.jin-ttt1-hit-effect','mods/jin-ttt1-hit-effect')

def remove_retired():
    gone=[p for p in [ROOT/p for p in RETIRED_SOURCES]+[BUILD/p for p in RETIRED_STAGED] if p.exists()]
    for path in gone:shutil.rmtree(path,ignore_errors=True)
    if gone:log_line('Removed, no longer part of the game: '+', '.join(p.relative_to(ROOT).as_posix() for p in gone))

# An update unpacked over the older folder dates each file as its ZIP entry:
# the date of the release's commit (git archive, tools/release/export.py). An
# install set up after that date has objects newer than these sources, and
# Ninja linked the new files' objects with the old ones (B97: undefined symbol
# __wrap_func_8002A40C, tekken3_arcade_stages_source_ready...). Before each
# build, every file whose content changed since the last check (.setup/
# sources.json: size, date, SHA-256) is dated now, newer than any object built
# so far, in build-release/ as in build-android/; with no record yet (an
# install set up before this check), all of them. Not what the setup and the
# builds make, nor the player's ROMs and discs (.gitignore).
NOT_SOURCES=('.git','.setup','.runtime','build*','disc','generated','workspace','saves','out','dist','toolchain','export',
             'psxrecomp/generated','psxrecomp/recompiler/build*','Tekken 3 Expanded*','*.apk',
             '*.zip','*.7z','*.cue','*.iso','*.chd')

def source_files():
    """{path relative to ROOT: Path} of the files a build may read."""
    found={}
    for folder,dirs,files in os.walk(ROOT):
        here=Path(folder).relative_to(ROOT).as_posix()
        name=lambda n:n if here=='.' else f'{here}/{n}'
        skip=lambda n:n=='__pycache__' or any(fnmatch.fnmatchcase(name(n),p) for p in NOT_SOURCES)
        dirs[:]=[d for d in dirs if not skip(d)]
        found.update((name(f),Path(folder)/f) for f in files if not skip(f))
    return found

def date_changed_sources():
    record_path=STATE/'sources.json'
    old=load_json(record_path);record={};changed=[]
    for name,path in sorted(source_files().items()):
        try:
            info=path.stat();seen=old.get(name)
            if seen and seen[:2]==[info.st_size,info.st_mtime_ns]:record[name]=seen;continue
            sha=digest(path)
            if not seen or seen[2]!=sha:os.utime(path);changed.append(name);info=path.stat()
            record[name]=[info.st_size,info.st_mtime_ns,sha]
        except OSError as error:log_line(f'{name}: not checked for changes ({error})')
    save_json(record_path,record)
    if changed:log_line(f'Dated now, to be compiled again: {len(changed)} changed file(s)'
                        +(' (no record of an earlier check: all of them)' if not old else ': '+', '.join(changed[:8])+(' ...' if len(changed)>8 else '')))

def validate_disc(disc,updating=False):
    if not disc.is_file():
        if updating:raise SetupError(f'This update needs your Tekken 3 disc image again: it is no longer at {disc}. Choose it, then click Try again.')
        raise SetupError('Choose your Tekken 3 USA PS1 disc image first.')
    emit(message='Checking your game files',detail='Checking the supported disc revision.')
    run([sys.executable,ROOT/'psxrecomp/psxrecomp_cli.py','verify-disc','--project-root',ROOT,'--config',ROOT/'game.toml','--disc',disc],
        friendly='This disc does not match the supported Tekken 3 USA (SLUS-00402) release. Choose its CUE or BIN file, with all tracks present.',
        only_code=3)   # psxrecomp_cli: 3 = digest mismatch, 1 = an error of its own

def validate_ttt1(ttt,updating=False):
    if not ttt.is_file():
        if updating:raise SetupError(f'Updating the TTT1 characters needs your tektagt.zip again: it is no longer at {ttt}. Choose it, then click Try again.')
        raise SetupError("Choose your TTT1 arcade ZIP, or turn off Include Tekken Tag Tournament Content.")
    if str(ROOT/'tools') not in sys.path:sys.path.insert(0,str(ROOT/'tools'))
    import arcade_model_probe as probe
    definitions=load_json(probe.MANIFEST)['sets']
    try:probe.reconstruct(ttt,definitions[probe.ttt_set(ttt)])
    except (ValueError,zipfile.BadZipFile,OSError) as error:
        log_line(str(error));raise SetupError('The arcade ZIP does not match a supported set. The TTT1 characters need tektagt (World C1), tektagtuc1 (US C1), tektagtub (US B) or tektagtjc1 (Japan C1), non-merged.') from error

# tekken3.zip's program ROMs, TET2/VER.E1 (tet2vere1.2e, .2j), by CRC as MAME
# finds them: sets from older MAME versions give the same chips other names.
TEKKEN3_PROGRAM={0x7ded5461,0x25c96e1e}

def tekken3_supported(path):
    try:
        with zipfile.ZipFile(path) as z:return TEKKEN3_PROGRAM<={i.CRC for i in z.infolist()}
    except (OSError,zipfile.BadZipFile):return False

def tekken3_problem(path):
    """Why tekken3.zip is not supported, in the player's words."""
    if not Path(path).is_file():return 'It is no longer there (moved, renamed or deleted).'
    try:
        with zipfile.ZipFile(path) as z:names=[Path(i.filename).name.lower() for i in z.infolist()]
    except (OSError,zipfile.BadZipFile):return 'It cannot be read as a ZIP file (damaged, or not a ZIP).'
    # TET1's program ROMs (tet1vere.2e, .2j), the revision before TET2.
    if any(re.fullmatch(r'tet1ver.*\.2[ej]',n) for n in names):return 'It is the TET1 revision of Tekken 3 arcade, not TET2/VER.E1.'
    return 'Its program ROMs are not those of Tekken 3 arcade TET2/VER.E1.'

# The framework's POST_BUILD empties build-release/mods at every link of the
# game (psxrecomp/runtime/runtime.cmake) before the catalogues are staged
# again, from workspace/ only. An update that rebuilds would lose the player's
# mod settings (state.toml, the launcher's Mods page) and, workspace/ freed,
# what the setup made beside the game. They are moved aside for the build
# (build-release/mods.kept), and those the build did not stage again are moved
# back; a build cut short leaves them there for the next attempt.
MODS_KEPT=BUILD/'mods.kept'
MOD_DATA=('state.toml','ttt1','ttt-stages','ttt-music','ttt-ps2-music','ttt-ps2-laser','arcade-stages','difficulty','ttt-cinematics')

def restore_mods():
    if not MODS_KEPT.is_dir():return
    mods=BUILD/'mods';mods.mkdir(parents=True,exist_ok=True)
    back=[n for n in MOD_DATA if (MODS_KEPT/n).exists() and not (mods/n).exists()]
    for name in back:(MODS_KEPT/name).replace(mods/name)
    if back:log_line('Kept across the build: mods/'+', mods/'.join(back))
    shutil.rmtree(MODS_KEPT,ignore_errors=True)

class kept_mods:
    def __enter__(self):
        restore_mods()            # an earlier build cut short
        MODS_KEPT.mkdir(parents=True,exist_ok=True)
        for name in MOD_DATA:
            if (BUILD/'mods'/name).exists():(BUILD/'mods'/name).replace(MODS_KEPT/name)
        return self
    def __exit__(self,*error):
        restore_mods()
        return False

def build_game(toolchain,env,include_ttt1):
    cmake=toolchain/'bin/cmake.exe' if toolchain else shutil.which('cmake')
    emit(message='Preparing the game to build',detail='First setup can take several minutes.')
    # Setup explicitly configures on every attempt, after generation/import.
    # Skip Ninja's automatic regeneration checks: future-dated archive inputs
    # otherwise keep build.ninja dirty even after 100 successful regenerations.
    # This is local to Easy Setup; ordinary source builds keep their defaults.
    args=[cmake,'-S',ROOT,'-B',BUILD,'-G','Ninja','-DCMAKE_BUILD_TYPE=Release',
          '-DCMAKE_SUPPRESS_REGENERATION=ON','-DPython3_EXECUTABLE='+sys.executable]
    if toolchain:
        args+=['-DCMAKE_C_COMPILER='+str(toolchain/'bin/clang.exe'),'-DCMAKE_CXX_COMPILER='+str(toolchain/'bin/clang++.exe'),
               '-DCMAKE_MAKE_PROGRAM='+str(toolchain/'bin/ninja.exe'),'-DPSX_STATIC_RUNTIME=ON']
    args+=['-DPSX_DEBUG_TOOLS=OFF','-DPSX_DEBUG_SERVER_LITE=OFF','-DPSX_NETPLAY=OFF',
          '-DPSXRECOMP_BIOS_STEMS=OpenBIOS','-DPSXRECOMP_FORCE_SETUP_HOST=OFF','-DPSXRECOMP_REQUIRE_GAME_C=ON',
          '-DTEKKEN3_BUILD_PC_PORT=OFF','-DTEKKEN3_TTT1_CHARACTERS='+('ON' if include_ttt1 else 'OFF')]
    run(args,environment=env,friendly='The build tools could not finish setup. Open the setup log for details, then click Try again.')
    emit(message='Building your game',detail='This is the long part. Next time you can play immediately.')
    run([cmake,'--build',BUILD,'--target','psx-runtime','--parallel',env['CMAKE_BUILD_PARALLEL_LEVEL']],
        environment=env,friendly='The game build stopped. Open the setup log for the specific error, then click Try again. Completed work is kept.')
    # Before 1.2 the game was Tekken_3_Recompiled: never leave it to run stale.
    for old in ('Tekken_3_Recompiled.exe','Tekken_3_Recompiled'):
        try:(BUILD/old).unlink()
        except FileNotFoundError:pass
    if WINDOWS:play_exe(cmake,env)
    elif sys.platform=='darwin':play_app()
    else:play_linux()

# Double-click to play, beside the setup script. A convenience only: when one
# cannot be made, the setup script still does the same.
PLAY_EXE=ROOT/'Tekken 3 Expanded.exe'
PLAY_APP=ROOT/'Tekken 3 Expanded.app'
PLAY_SH=ROOT/'Tekken 3 Expanded.sh'

def play_exe(cmake,env):
    """launcher/bootstrap.c, built by the game's CMake project (tekken3-play)."""
    try:
        run([cmake,'--build',BUILD,'--target','tekken3-play'],environment=env,friendly='Tekken 3 Expanded.exe could not be built.')
        shutil.copy2(BUILD/'tekken3-play.exe',PLAY_EXE)
    except (SetupError,OSError) as error:log_line(f'Tekken 3 Expanded.exe skipped: {error}')

APP_PLIST='''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Tekken 3 Expanded</string>
  <key>CFBundleExecutable</key><string>Tekken 3 Expanded</string>
  <key>CFBundleIdentifier</key><string>io.github.omarma.tekken3-expanded</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleIconFile</key><string>icon</string>
  <key>LSUIElement</key><true/>
</dict></plist>
'''
# Plays once setup is done; else (an update needs the setup) opens the setup script.
APP_SCRIPT='''#!/bin/bash
cd "$(dirname "$0")/../../.." || exit 1
python=.setup/venv/bin/python
if "$python" -c 'import sys; sys.path.insert(0, "launcher"); import setup_backend as b; sys.exit(not b.ready())' 2>/dev/null; then
    exec "$python" -c 'import sys; sys.path.insert(0, "launcher"); import setup_backend as b; b.launch_game()'
fi
exec open "Setup Tekken 3.command"
'''

def play_app():
    """The macOS counterpart of Tekken 3 Expanded.exe: a bundle around a script."""
    try:
        contents=PLAY_APP/'Contents';(contents/'MacOS').mkdir(parents=True,exist_ok=True)
        (contents/'Info.plist').write_text(APP_PLIST,encoding='utf-8')
        script=contents/'MacOS/Tekken 3 Expanded';script.write_text(APP_SCRIPT,encoding='utf-8');script.chmod(0o755)
    except OSError as error:log_line(f'Tekken 3 Expanded.app skipped: {error}');return
    # The T3E icon (packaging/icon.png); without it Finder shows the generic one.
    try:
        from PIL import Image
        (contents/'Resources').mkdir(exist_ok=True)
        Image.open(ROOT/'packaging/icon.png').convert('RGBA').save(contents/'Resources/icon.icns')
        os.utime(PLAY_APP)                         # Finder reads the icon again
    except Exception as error:log_line(f'Tekken 3 Expanded.app icon skipped: {error}')

# Linux: plays once setup is done, else (an update needs it) opens the setup.
# The game runs in the foreground, so Steam sees it running; without a usable
# setup Python (a Steam Deck set up inside Distrobox) it starts the game as built.
SH_SCRIPT='''#!/bin/bash
# Tekken 3 Expanded (Linux), written by launcher/setup_backend.py.
cd "$(dirname "$(readlink -f "$0")")" || exit 1
# 3: not ready (an update needs the setup); any other failure (no usable
# Python) plays the game as built.
.setup/venv/bin/python -c 'import sys; sys.path.insert(0, "launcher"); import setup_backend as b; sys.exit(0 if b.ready() else 3)' 2>/dev/null
[ $? -eq 3 ] && exec ./"Setup Tekken 3.sh" "$@"
launcher=(); [[ " $* " == *" --settings "* ]] && launcher=(--launcher)
exec build-release/Tekken_3_Expanded "${launcher[@]}" --game "$PWD/game.toml" --disc "$PWD/disc/Tekken 3 (USA).cue"
'''

DESKTOP_ENTRY='''[Desktop Entry]
Type=Application
Name=Tekken 3 Expanded
Comment=Tekken 3 with the Tekken Tag Tournament roster
Exec={exec}
Path={root}
Icon={icon}
Terminal=false
Categories=Game;
'''

def desktop_entry():
    """~/.local/share/applications (XDG_DATA_HOME): the applications menu's entry."""
    home=os.environ.get('XDG_DATA_HOME') or os.path.join(os.path.expanduser('~'),'.local/share')
    return Path(home)/'applications/tekken3-expanded.desktop'

def play_linux():
    """The Linux counterpart of Tekken 3 Expanded.exe: a script beside the
    setup, and an entry in the applications menu that runs it."""
    try:PLAY_SH.write_text(SH_SCRIPT,encoding='utf-8');PLAY_SH.chmod(0o755)
    except OSError as error:log_line(f'Tekken 3 Expanded.sh skipped: {error}');return
    quoted='"'+re.sub(r'(["`$\\])',r'\\\1',str(PLAY_SH))+'"'    # Exec= quoting (Desktop Entry spec)
    try:
        entry=desktop_entry();entry.parent.mkdir(parents=True,exist_ok=True)
        entry.write_text(DESKTOP_ENTRY.format(exec=quoted,root=ROOT,icon=ROOT/'packaging/icon.png'),encoding='utf-8')
        entry.chmod(0o755)
    except OSError as error:log_line(f'Tekken 3 Expanded menu entry skipped: {error}')

# Only the setup and its updates read these: the downloaded tools, the TTT1
# import's work files and the build's object files. generated/ stays: the game
# checks for it at every start (psxrecomp/host/psxrecomp_codegen_host.c), and
# disc/ holds its own copy of the tracks in .setup/disc-tracks.
SPARE_FOLDERS=('.setup/tools','.setup/downloads','.setup/android/downloads','.setup/disc-tracks','workspace')

def spare_files():
    for name in SPARE_FOLDERS:
        if (ROOT/name).is_dir():yield from (p for p in (ROOT/name).rglob('*') if p.is_file())
    if BUILD.is_dir():
        yield from (p for p in BUILD.rglob('*') if p.suffix in ('.o','.obj') and 'CMakeFiles' in p.relative_to(BUILD).parts and p.is_file())

def spare_size():
    total=0
    for path in spare_files():
        try:total+=path.stat().st_size
        except OSError:pass
    return total

def offer_free_space(size):
    """Worth asking, and not declined before."""
    return size>=256*1024**2 and not load_json(STATE/'free-space.json').get('declined')

def free_space_question(size):
    return (f"{size/1024**3:.1f} GB in this folder are only used by the setup and by updates: the downloaded tools, "
            "the TTT1 import's work files and the build's intermediate files. The game does not need them.\n\n"
            "If you delete them, the next update that rebuilds the game can take as long as the first setup "
            "(about 17 minutes), and one that imports the TTT1 characters again needs your tektagt.zip again.\n\nDelete them now?")

def decline_free_space():
    save_json(STATE/'free-space.json',{'declined':True})

def free_space():
    """Delete spare_files(); the next setup downloads, imports and builds them again."""
    for name in SPARE_FOLDERS:shutil.rmtree(ROOT/name,ignore_errors=True)
    for path in list(spare_files()):
        try:path.unlink()
        except OSError:pass
    log_line('Freed up disk space: '+', '.join(SPARE_FOLDERS)+' and the build objects deleted')

def game_current():
    """The game was generated by this release: an update only rebuilds it, without the disc."""
    return (load_json(STATE/'ready.json').get('release')==RELEASE and (ROOT/'generated').is_dir()
            and (ROOT/'disc/Tekken 3 (USA).cue').is_file())

def needs(include_ttt1,tekken3=None,cinematics=False):
    """Which of the player's files this setup reads: (disc, TTT1 ROM)."""
    try:rom=include_ttt1 and ttt1_plan(tekken3,cinematics)[0]=='import'
    except Exception:rom=include_ttt1
    return not game_current(),rom

def ttt_disc_supported(path):
    """A Tekken Tag Tournament USA PS2 disc (version 1.00 or 2.00: the same
    music, tools/ps2/ttt_disc.py TABLES) with the endings' music, the stages'
    music (tools/ttt_stages/ps2_music_install.py checks the same) and Devil's
    and Angel's laser textures (tools/ps2/ttt_laser_install.py)."""
    tools=Path(__file__).resolve().parents[1]/'tools'
    if str(tools) not in sys.path:sys.path.insert(0,str(tools))
    import ttt_cinematics
    try:
        if not ttt_cinematics.music_found(path):return False
    except (OSError,ValueError,StopIteration,IndexError):return False
    if 'ps2_music_install' not in sys.modules:
        import importlib.util
        spec=importlib.util.spec_from_file_location('ps2_music_install',tools/'ttt_stages/ps2_music_install.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        sys.modules['ps2_music_install']=module
    if not sys.modules['ps2_music_install'].found(path):return False
    if 'ttt_laser_install' not in sys.modules:
        import importlib.util
        spec=importlib.util.spec_from_file_location('ttt_laser_install',tools/'ps2/ttt_laser_install.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        sys.modules['ttt_laser_install']=module
    return sys.modules['ttt_laser_install'].found(path)

# The optional files (B85, GH#110): a tekken3.zip or a TTT PS2 disc that this
# setup would read but cannot use is no longer skipped with a line of the log
# only. The window (easy_launcher.py) asks before it starts, the terminal setup
# here: go on without it, or choose another file. tektagt.zip still stops the
# setup (validate_ttt1). A file the setup does not read this time (what it
# makes is already current) is not checked.
TEKKEN3_EXPECTED=('Expected: MAME set tekken3, Tekken 3 (World, TET2/VER.E1), with the program ROMs tet2vere1.2e '
                  '(SHA-1 3a5638c6ad40bfde6e12fdfd6d469f6ea5e9f4fb) and tet2vere1.2j (SHA-1 554d1e42886d6a6c9c5857e9cbd5d7c37d7a6e67), '
                  'under these or older names. A zip with only tet1vere.2e and tet1vere.2j is the TET1 revision: not supported.')
TTT_DISC_EXPECTED=('Expected: Tekken Tag Tournament USA for PS2 (SLUS-20001), version 1.00 or 2.00 (Greatest Hits), '
                   'as a .cue with its .bin, a .bin or an .iso.')

def optional_problems(include_ttt1,tekken3=None,ttt_disc=None,cinematics=False,pc=True):
    """The optional files given that this setup reads and cannot use: a
    list of dicts (key, file, name, path, reason, without, expected)."""
    problems=[]
    cinematics=cinematics and include_ttt1
    if tekken3 and not tekken3_supported(tekken3):
        # Read for the arcade stages, and by an import for the difficulty levels.
        try:needed=not arcade_stages_made(pc) or (include_ttt1 and ttt1_plan(tekken3,cinematics)[0]=='import')
        except Exception:needed=True
        if needed:problems.append(dict(key='tekken3',file='tekken3.zip',name='Tekken 3 arcade · tekken3.zip',path=str(tekken3),reason=tekken3_problem(tekken3),
            without='the arcade difficulty levels and the arcade stages are left out: the game keeps its PS1 difficulty levels and stages.',
            expected=TEKKEN3_EXPECTED))
    # Read for the stages' PS2 music and the PS2 laser, and for the endings' music at every setup with TTT Cinematics.
    if include_ttt1 and ttt_disc and (cinematics or not ttt_ps2_music_made(pc) or not ttt_ps2_laser_made(pc)):
        reason=('It is no longer there (moved, renamed or deleted).' if not Path(ttt_disc).is_file()
                else None if ttt_disc_supported(ttt_disc)
                else 'It is not Tekken Tag Tournament USA (SLUS-20001) for PS2, or the image is incomplete or damaged.')
        if reason:problems.append(dict(key='ttt_disc',file='TTT PS2 disc',name='Tekken Tag Tournament · USA PS2 disc',path=str(ttt_disc),reason=reason,
            without='the TTT stages play their arcade music, also with BGM SELECT: REMIXED'
                    +(", and TTT Cinematics' endings play over Tekken 3's music" if cinematics else '')+'.',
            expected=TTT_DISC_EXPECTED))
    return problems

def optional_text(problems):
    """The terminal's question (the window lays out the same parts)."""
    return '\n\n'.join(f"Your {p['file']} (optional): {p['path']}\n  {p['reason']}\n  Without it, {p['without']}\n  {p['expected']}"
                       for p in problems)

def go_on_without(problems):
    """Each problem in the log and the progress lines. The terminal setup asks
    first: no stops it, to give another file."""
    for p in problems:log_line(f"{p['path']}: {p['reason']} Without it, {p['without']}")
    if problems and TEXT and sys.stdin.isatty():
        one=len(problems)==1
        print('\n'+optional_text(problems)+'\n',flush=True)
        try:answer=input(f"Continue without {'it' if one else 'them'}? [y/N] ")
        except EOFError:answer=''
        if answer.strip().lower()[:1] not in ('y','o'):
            raise SetupError(f"Setup stopped. Run it again with another {' and '.join(p['file'] for p in problems)}"
                             f", or without {'it' if one else 'them'}.")
    for p in problems:emit(message=f"Going on without your {p['file']}",detail=f"{p['reason']} Without it, {p['without']}")

def prepare_cinematics(ttt_disc,catalogue=None,out=None):
    """The TTT cinematics beside the installed catalogue (tools/ttt_cinematics.py)."""
    catalogue,out=catalogue or INSTALLED,out or CINEMATICS
    # TTT Cinematics music off: Tekken 3's, even if a PS2 disc gave TTT's before.
    if not ttt_disc:
        try:(out/'ending-music.pcm').unlink()
        except FileNotFoundError:pass
    emit(message="Preparing the TTT cinematics",detail="With the music of TTT's endings from your PS2 disc." if ttt_disc
         else "No Tekken Tag Tournament PS2 disc given: the cinematics play over Tekken 3's music.")
    run([sys.executable,ROOT/'tools/ttt_cinematics.py','--catalogue',catalogue,'--out',out,*(['--ttt-disc',ttt_disc] if ttt_disc else [])],
        friendly="The TTT cinematics could not be prepared. Open the setup log for details, then click Try again.")

def prepare(disc,ttt,include_ttt1,tekken3=None,cinematics=False,ttt_disc=None,android=False,pc=True):
    """First setup, or an update: generate the game again only for a new
    RELEASE, and bring the TTT1 characters to this import version with the
    least work (ttt1_plan). pc=False (with android, Build Android APK): only
    what the Android APK needs, no PC build, for players who only want the
    game on their phone."""
    STATE.mkdir(exist_ok=True)
    with (STATE/'setup.log').open('w',encoding='utf-8') as f:f.write('Tekken 3 easy setup '+RELEASE+'\n')
    # Only run in the unpacked writable application folder, never require admin.
    complete()
    remove_retired()
    date_changed_sources()
    if shutil.disk_usage(ROOT).free<4*1024**3:raise SetupError('Setup needs at least 4 GB of free space in this folder.')
    updating=bool(load_json(STATE/'ready.json'))
    save_json(STATE/'last-inputs.json',{'disc':str(disc),'ttt1':str(ttt) if include_ttt1 else '',
        'include_ttt1':include_ttt1,'tekken3':str(tekken3 or ''),
        'ttt_cinematics':cinematics,'ttt_disc':str(ttt_disc or ''),'android':android})
    # The TTT cinematics come with the TTT1 characters (Jin's red lightning: tools/ttt1_hitspark.py).
    cinematics=cinematics and include_ttt1
    # The TTT PS2 disc, optional with the TTT1 characters: the TTT stages' PS2
    # music, Devil's and Angel's PS2 laser textures, and the endings' music of
    # the TTT cinematics. Missing, an earlier copy of the stages' music stays
    # and the endings play over T3's music.
    if not include_ttt1:ttt_disc=None
    # Optional: an unsupported tekken3.zip only costs the arcade difficulty
    # levels and the arcade stages, an unsupported TTT PS2 disc the PS2 music;
    # checked now rather than failing at the end of the import. The terminal
    # setup asks whether to go on (the window asked before starting).
    problems=optional_problems(include_ttt1,tekken3,ttt_disc,cinematics,pc)
    go_on_without(problems)
    if any(p['key']=='tekken3' for p in problems):tekken3=None
    # A disc set aside keeps what it made before (prepare_ttt_ps2_music's keep).
    disc_set_aside=any(p['key']=='ttt_disc' for p in problems)
    if disc_set_aside:ttt_disc=None
    # Checked whenever the cinematics are on (they read it at every setup).
    cinematics_disc=ttt_disc if cinematics else None
    generate=not game_current()
    if generate:
        if disc.is_file():disc=single_bin(cue_for(disc))
        validate_disc(disc,updating)
    else:log_line(f'Game generated by release {RELEASE}: rebuilding only')
    plan,steps=ttt1_plan(tekken3,cinematics) if include_ttt1 else ('none',[])
    if include_ttt1:
        log_line(f'TTT1 characters: {plan}, import version {import_version().TTT1_IMPORT_VERSION}'+(' ('+', '.join(steps)+')' if steps else ''))
        if plan=='import':validate_ttt1(ttt,updating)
        for module in ('PIL','numpy'):
            try:__import__(module)
            except ImportError as error:raise SetupError(f'The Python module {module} is missing. Run the setup script again (it installs it).') from error
    toolchain=tools()
    env=dict(os.environ)
    env.update(PYTHONUTF8='1',PYTHONNOUSERSITE='1',CMAKE_BUILD_PARALLEL_LEVEL=str(min(8,max(2,os.cpu_count() or 2))))
    if toolchain:
        # Keep compiler setup local to this process; do not modify the user's PATH.
        env['PATH']=str(toolchain/'bin')+os.pathsep+env.get('PATH','')
        env.update(PSXRECOMP_TOOLCHAIN_DIR=str(toolchain),RETCOMM_TOOLCHAIN_DIR=str(toolchain))
    if generate:
        emit(message='Preparing your Tekken 3 disc',detail='Generating the game locally. Your files are not uploaded.')
        run([sys.executable,ROOT/'psxrecomp/psxrecomp_cli.py','generate','--project-root',ROOT,
             '--config',ROOT/'game.toml','--disc',disc,'--no-toolchain-download'],environment=env,
            friendly='The game files could not be prepared. Open the setup log for details, then click Try again.')
    prepare_textures()
    if plan=='import':
        emit(message='Adding the TTT1 characters',detail='Importing their models, moves, voices and portraits from your ROM. The first time takes about 15 minutes. This runs muted.')
        command=[sys.executable,ROOT/'tools/ttt1_setup.py','--ttt1',ttt,'--no-rebuild']
        if tekken3:command+=['--tekken3',tekken3]
        run(command,
            environment=env,friendly="The TTT1 characters' import could not finish. Open the setup log for details, then click Try again.")
    elif plan=='update':update_ttt1(steps,env)
    # Before the build: CMakeLists.txt stages the packs from workspace/.
    arcade_stages=bool(tekken3) and prepare_arcade_stages(tekken3,env,pc)
    # TTT's stages and music come from the same tektagt.zip as the characters.
    ttt_stages,ttt_music=prepare_ttt_stages(ttt,env,pc) if include_ttt1 else (False,False)
    # Their PS2 music from the TTT PS2 disc, if given (else an earlier copy goes).
    ttt_ps2_music=prepare_ttt_ps2_music(ttt_disc,env,pc,keep=disc_set_aside)
    # Devil's and Angel's PS2 laser textures from the same disc.
    ttt_ps2_laser=prepare_ttt_ps2_laser(ttt_disc,env,pc,keep=disc_set_aside)
    if not pc:
        # The Android build stages the TTT1 guests, the difficulty levels, the arcade stages
        # and TTT's stages and music from workspace/ itself (CMakeLists.txt).
        if include_ttt1 and not ttt1_current(ROSTER):
            raise SetupError("The TTT1 characters' import is incomplete. Click Try again.")
        if cinematics:prepare_cinematics(cinematics_disc,ROSTER,ANDROID_CINEMATICS)
        else:cinematics_off(ANDROID_CINEMATICS)
        save_json(STATE/'android.json',{'release':RELEASE,'ttt1':include_ttt1,'ttt_cinematics':cinematics,'arcade_stages':arcade_stages,
                                        'ttt_stages':ttt_stages,'ttt_music':ttt_music,'ttt_ps2_music':ttt_ps2_music,
                                        'ttt_ps2_laser':ttt_ps2_laser})
        android_apk(toolchain,env)
        emit('complete',message='Android APK ready',detail='Setup is complete.')
        return
    with kept_mods():build_game(toolchain,env,include_ttt1)
    if not EXE.is_file():raise SetupError('The game executable was not created.')
    if include_ttt1:
        install_roster()
        if not ttt1_current(INSTALLED):raise SetupError('The TTT1 characters are missing from the finished build. Click Try again.')
    if cinematics:prepare_cinematics(cinematics_disc)
    else:cinematics_off(CINEMATICS)
    save_json(STATE/'ready.json',{'release':RELEASE,'ttt1':include_ttt1,'exe_sha256':digest(EXE),'ttt_cinematics':cinematics,
                                  'arcade_stages':arcade_stages,'ttt_stages':ttt_stages,'ttt_music':ttt_music,'ttt_ps2_music':ttt_ps2_music,
                                  'ttt_ps2_laser':ttt_ps2_laser,'ttt1_import':import_version().TTT1_IMPORT_VERSION if include_ttt1 else None})
    # After ready.json: the PC game plays even if the Android build stops.
    if android:android_apk(toolchain,env)
    emit('complete',message='Ready to play',detail='Setup is complete.')

APK=ROOT/'Tekken3Expanded.apk'

def android_apk(toolchain=None,env=None):
    """The Android APK of the game just set up: tools/android/make_apk.py,
    its progress shown here and its build output in the setup log."""
    sys.path.insert(0,str(ROOT/'tools/android'))
    import make_apk
    emit(message='Building the Android APK',detail='The first time downloads the Android tools (about 1 GB).')
    def step(command,environment):
        run(command,environment=environment,progress='Building the Android game',
            friendly='The Android build stopped. Open the setup log for the specific error, then click Try again. Completed work is kept.')
    try:apk=make_apk.build(out=APK,say=lambda message,detail='':emit(message=message,detail=detail),run=step,toolchain=toolchain,env=env)
    except make_apk.Stop as error:raise SetupError(str(error)) from error
    log_line(f'Android APK: {apk}')
    emit('apk',message='Android APK ready',detail=f'{apk}\n\n'+make_apk.install_hint(apk),apk=str(apk))
    return apk

def android_only():
    """--android without --disc: the APK of a game already set up."""
    STATE.mkdir(exist_ok=True)
    with (STATE/'setup.log').open('w',encoding='utf-8') as f:f.write('Tekken 3 Android APK '+RELEASE+'\n')
    # Never an APK of an older install: the setup's update first, same steps.
    if not ready() and not android_ready():
        if not load_json(STATE/'ready.json'):
            raise SetupError('Choose your game files first (Build Android APK asks for them), then build the APK.')
        update_install()
        with (STATE/'setup.log').open('a',encoding='utf-8') as f:f.write('Tekken 3 Android APK '+RELEASE+'\n')
    else:date_changed_sources()
    android_apk(tools())
    emit('complete',message='Android APK ready',detail=str(APK))

def update_install():
    """--update: an existing install brought to this version with the files it
    was set up with (.setup/last-inputs.json)."""
    saved=load_json(STATE/'last-inputs.json')
    if not saved or not load_json(STATE/'ready.json'):raise SetupError('No earlier setup was found here. Run the first setup.')
    path=lambda key:Path(saved[key]) if saved.get(key) else Path()
    prepare(path('disc'),path('ttt1'),saved.get('include_ttt1',True),path('tekken3') if saved.get('tekken3') else None,
            saved.get('ttt_cinematics',False),path('ttt_disc') if saved.get('ttt_disc') else None)

def launch_game(settings=False):
    """The game opens on its launcher unless the player ticked its "Skip
    launcher on boot"; settings (--settings) opens the launcher even then."""
    if not ready():raise SetupError('Complete first setup before playing.')
    # Absolute --game and --disc: the runtime looks in the current folder first.
    subprocess.Popen([str(EXE),*(['--launcher'] if settings else []),'--game',str(ROOT/'game.toml'),
        '--disc',str(ROOT/'disc/Tekken 3 (USA).cue')],cwd=ROOT,
        start_new_session=not WINDOWS)   # closing the setup's terminal leaves the game running

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--disc',type=Path,help='required, unless --update, or --android builds the APK of a game already set up')
    parser.add_argument('--ttt1',type=Path,default=Path())
    parser.add_argument('--no-ttt1',action='store_true')
    parser.add_argument('--tekken3',type=Path,help='tekken3.zip: the arcade difficulty levels and arcade stages')
    parser.add_argument('--ttt-cinematics',action='store_true',help="TTT Cinematics, the Tekken Tag Tournament endings")
    parser.add_argument('--ttt-disc',type=Path,help="Tekken Tag Tournament USA PS2 disc: the TTT stages' PS2 music and the endings' music")
    parser.add_argument('--wait-for-parent',action='store_true')
    parser.add_argument('--text',action='store_true',help='plain progress lines (terminal setup)')
    parser.add_argument('--play',action='store_true',help='start the game once setup is complete')
    parser.add_argument('--settings',action='store_true',help='with --play: open the launcher even if it is skipped on boot')
    parser.add_argument('--update',action='store_true',help='update an existing install with the files it was set up with')
    parser.add_argument('--android',action='store_true',help='Build Android APK: the APK of the game already set up, updated first')
    parser.add_argument('--android-only',action='store_true',help='Build Android APK with --disc: the Android game alone, without the PC game')
    args=parser.parse_args()
    if not args.disc and not args.update and not args.android:parser.error('--disc is required')
    if args.android_only and not args.disc:parser.error('--android-only needs --disc')
    TEXT=args.text
    # Parent assigns the process to a Job before releasing this handshake.
    if args.wait_for_parent and sys.stdin.readline().strip()!='START':sys.exit(1)
    try:
        if args.disc:prepare(args.disc.resolve(),args.ttt1.resolve(),not args.no_ttt1,
                             args.tekken3.resolve() if args.tekken3 else None,
                             args.ttt_cinematics,args.ttt_disc.resolve() if args.ttt_disc else None,
                             android=args.android or args.android_only,pc=not args.android_only)
        elif args.android:android_only()
        else:update_install()
    except Exception as error:
        import traceback
        log_line(traceback.format_exc())
        emit('error',message=str(error) if isinstance(error,SetupError) else f'Setup stopped unexpectedly. See {STATE/"setup.log"}.')
        sys.exit(1)
    # Android alone keeps workspace/: the next APK builds stage from it.
    if args.text and args.disc and not args.android_only and sys.stdin.isatty():
        size=spare_size()
        if offer_free_space(size):
            if input(free_space_question(size)+' [y/N] ').strip().lower()[:1] in ('y','o'):
                print('Freeing up disk space...',flush=True);free_space()
            else:decline_free_space()
    if args.play:launch_game(settings=args.settings)
