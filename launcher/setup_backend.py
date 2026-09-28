"""Local first-run setup. Downloads only pinned tools; game data stays local."""
from __future__ import annotations
from pathlib import Path, PureWindowsPath
import argparse, hashlib, json, os, re, shutil, struct, subprocess, sys, time
import urllib.request, urllib.error, zipfile

ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'.setup'
BUILD=ROOT/'build-release'
WINDOWS=os.name=='nt'
EXE=BUILD/('Tekken_3_Recompiled.exe' if WINDOWS else 'Tekken_3_Recompiled')
RELEASE='0.1.2-easy-setup'
LOCK=json.loads((ROOT/'launcher/tools.lock.json').read_text())

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
        if state.get('ttt1',state.get('jun')) and not ttt1_ready(BUILD/'mods/ttt1'):return False
    except OSError:return False
    return True

def ttt1_ready(folder):
    """A TTT1 characters catalogue (tools/ttt1_stage_roster.py) with every
    listed character's combat pack."""
    listed=folder/'guests.txt'
    # One guest a line: its key, then its moveset and arena columns.
    keys=[l.split()[0] for l in listed.read_text(encoding='utf-8').splitlines() if l.split()] if listed.is_file() else []
    return bool(keys) and all((folder/f'{k.capitalize()}-TTT1-combat.jmv').is_file() for k in keys)

def log_line(text):
    STATE.mkdir(exist_ok=True)
    with (STATE/'setup.log').open('a',encoding='utf-8') as f:f.write(text+'\n')

def run(command, *, environment=None, directory=ROOT, friendly='Setup could not finish.', timeout=None, only_code=None):
    """friendly: the message for a failure; with only_code, for that exit code
    only, and any other failure shows the last line of the command's output."""
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
                emit(detail='Preparing game files: '+match[1]+' / '+match[2]);last=time.monotonic()
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
    xcode-select --install); None."""
    if not WINDOWS:
        for name in ('cmake','ninja'):installed(name,'On macOS: brew install cmake ninja sdl3')
        if not (shutil.which('cc') or shutil.which('clang')):raise SetupError('No C compiler. On macOS: xcode-select --install')
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

def mame():
    if not WINDOWS:
        found=shutil.which('mame') or next((p for p in ('/opt/homebrew/bin/mame','/usr/local/bin/mame') if Path(p).is_file()),None)
        if not found:raise SetupError('MAME is missing (the TTT1 import runs your arcade ROM in it). On macOS: brew install mame')
        return Path(found)
    folder=STATE/'tools/mame-0.289';marker=folder/'.ready.json'
    if load_json(marker).get('archive_sha256')!=LOCK['mame']['sha256'] or not (folder/'mame.exe').is_file():
        emit(message='Getting the TTT1 import tool',detail='Downloading from the MAME project.')
        archive=download(LOCK['mame'])
        folder.mkdir(parents=True,exist_ok=True)
        emit(message='Preparing the TTT1 import tool',detail='Your game files stay on this PC.')
        run([archive,'-y','-o'+str(folder)],friendly='The TTT1 import tool could not be unpacked.')
        if not (folder/'mame.exe').is_file():raise SetupError('The TTT1 import tool is missing after unpacking.')
        save_json(marker,{'archive_sha256':LOCK['mame']['sha256']})
    return folder/'mame.exe'

def prepare_textures():
    from PIL import Image
    emit(message='Preparing the included mods',detail='Skins, outfit gallery and HD stage textures.')
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
          'recomp-ui','tools/ttt1_import.py','tools/ttt1_setup.py','src','mods','CMakeLists.txt','game.toml')

def complete():
    """A partly extracted download (an interrupted unzip, an antivirus, or
    Windows' 260-character path limit) fails later with a confusing error."""
    missing=[p for p in REQUIRED if not (ROOT/p).exists()]
    if missing:raise SetupError('This folder is incomplete (missing: '+', '.join(missing[:4])+'). Extract the whole download again '
                                '(on Windows, to a short path such as C:\\Games, with 7-Zip or git clone), then run the setup again.')

def validate_files(disc,ttt,include_ttt1):
    if not disc.is_file():raise SetupError('Choose your Tekken 3 USA PS1 disc image first.')
    emit(message='Checking your game files',detail='Checking the supported disc revision.')
    run([sys.executable,ROOT/'psxrecomp/psxrecomp_cli.py','verify-disc','--project-root',ROOT,'--config',ROOT/'game.toml','--disc',disc],
        friendly='This disc does not match the supported Tekken 3 USA (SLUS-00402) release. Choose its CUE or BIN file, with all tracks present.',
        only_code=3)   # psxrecomp_cli: 3 = digest mismatch, 1 = an error of its own
    if include_ttt1:
        if not ttt.is_file():raise SetupError("Choose your TTT1 arcade ZIP, or turn off Include the TTT1 characters.")
        sys.path.insert(0,str(ROOT/'tools'))
        import arcade_model_probe as probe
        definitions=load_json(probe.MANIFEST)['sets']
        try:probe.reconstruct(ttt,definitions['tektagt'])
        except (ValueError,zipfile.BadZipFile,OSError) as error:
            log_line(str(error));raise SetupError('The arcade ZIP does not match the supported set. The TTT1 characters need tektagt (World C1), non-merged.') from error

# tekken3.zip's program ROMs, TET2/VER.E1 (tet2vere1.2e, .2j), by CRC as MAME
# finds them: sets from older MAME versions give the same chips other names.
TEKKEN3_PROGRAM={0x7ded5461,0x25c96e1e}

def tekken3_supported(path):
    try:
        with zipfile.ZipFile(path) as z:return TEKKEN3_PROGRAM<={i.CRC for i in z.infolist()}
    except (OSError,zipfile.BadZipFile):return False

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

def prepare(disc,ttt,include_ttt1,tekken3=None,jin_red=False):
    STATE.mkdir(exist_ok=True)
    with (STATE/'setup.log').open('w',encoding='utf-8') as f:f.write('Tekken 3 easy setup '+RELEASE+'\n')
    # Only run in the unpacked writable application folder, never require admin.
    complete()
    if shutil.disk_usage(ROOT).free<4*1024**3:raise SetupError('Setup needs at least 4 GB of free space in this folder.')
    save_json(STATE/'last-inputs.json',{'disc':str(disc),'ttt1':str(ttt) if include_ttt1 else '',
        'include_ttt1':include_ttt1,'tekken3':str(tekken3 or ''),'jin_red':jin_red})
    if disc.is_file():disc=single_bin(disc)
    validate_files(disc,ttt,include_ttt1)
    # Optional: an unsupported tekken3.zip only costs the arcade difficulty
    # levels, checked now rather than failing the import an hour later.
    if tekken3 and not tekken3_supported(tekken3):
        log_line(f'{tekken3}: no TET2/VER.E1 program ROMs, arcade difficulty levels skipped')
        emit(message='Skipping the arcade difficulty levels',detail='Your tekken3.zip is not the TET2/VER.E1 set (see the README). Setup goes on without them.')
        tekken3=None
    if include_ttt1:
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
    emit(message='Preparing your Tekken 3 disc',detail='Generating the game locally. Your files are not uploaded.')
    run([sys.executable,ROOT/'psxrecomp/psxrecomp_cli.py','generate','--project-root',ROOT,
         '--config',ROOT/'game.toml','--disc',disc,'--no-toolchain-download'],environment=env,
        friendly='The game files could not be prepared. Open the setup log for details, then click Try again.')
    prepare_textures()
    jin_effect=ROOT/'workspace/ttt1-import/jin/Jin-TTT1-hiteffect.tim'
    levels=ROOT/'workspace/difficulty/levels.bin'
    if include_ttt1 and (not ttt1_ready(ROOT/'workspace/ttt1-import/roster') or (jin_red and not jin_effect.is_file())
                         or (tekken3 and not levels.is_file())):
        oracle=mame()
        emit(message='Adding the TTT1 characters',detail='Importing their models, moves, voices and portraits from your ROM. The first time takes about an hour. This runs muted.')
        command=[sys.executable,ROOT/'tools/ttt1_setup.py','--ttt1',ttt,'--mame',oracle,'--no-rebuild']
        if jin_red:command.append('--jin-red-lightning')
        if tekken3:command+=['--tekken3',tekken3]
        run(command,
            environment=env,friendly="The TTT1 characters' import could not finish. Open the setup log for details, then click Try again.")
    build_game(toolchain,env,include_ttt1)
    if not EXE.is_file():raise SetupError('The game executable was not created.')
    if include_ttt1 and not ttt1_ready(BUILD/'mods/ttt1'):raise SetupError('The TTT1 characters are missing from the finished build. Click Try again.')
    save_json(STATE/'ready.json',{'release':RELEASE,'ttt1':include_ttt1,'exe_sha256':digest(EXE)})
    emit('complete',message='Ready to play',detail='Setup is complete.')

def launch_game(settings=False):
    if not ready():raise SetupError('Complete first setup before playing.')
    # Absolute --game and --disc: the runtime looks in the current folder first.
    subprocess.Popen([str(EXE),'--launcher' if settings else '--no-launcher','--game',str(ROOT/'game.toml'),
        '--disc',str(ROOT/'disc/Tekken 3 (USA).cue')],cwd=ROOT)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--disc',required=True,type=Path)
    parser.add_argument('--ttt1',type=Path,default=Path())
    parser.add_argument('--no-ttt1',action='store_true')
    parser.add_argument('--tekken3',type=Path,help='tekken3.zip: the arcade difficulty levels')
    parser.add_argument('--jin-red-lightning',action='store_true')
    parser.add_argument('--wait-for-parent',action='store_true')
    parser.add_argument('--text',action='store_true',help='plain progress lines (terminal setup)')
    parser.add_argument('--play',action='store_true',help='start the game once setup is complete')
    args=parser.parse_args()
    TEXT=args.text
    # Parent assigns the process to a Job before releasing this handshake.
    if args.wait_for_parent and sys.stdin.readline().strip()!='START':sys.exit(1)
    try:prepare(args.disc.resolve(),args.ttt1.resolve(),not args.no_ttt1,
                args.tekken3.resolve() if args.tekken3 else None,args.jin_red_lightning)
    except Exception as error:
        import traceback
        log_line(traceback.format_exc())
        emit('error',message=str(error) if isinstance(error,SetupError) else f'Setup stopped unexpectedly. See {STATE/"setup.log"}.')
        sys.exit(1)
    if args.play:launch_game()
