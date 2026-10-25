"""ROM-free checks for setup integrity, archive boundaries and cancellation."""
from pathlib import Path
import contextlib,hashlib,io,json,os,re,shutil,subprocess,sys,tempfile,time,unittest,zipfile
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import setup_backend as backend
from easy_launcher import ProcessJob
TTT_DISC_SUPPORTED=backend.ttt_disc_supported   # the real check, which UpdateTests replaces

class SetupTests(unittest.TestCase):
    def test_a_bin_chosen_alone_goes_through_the_cue_beside_it(self):
        # A single-file dump: the verified track 1 ends where its .cue says.
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);image=root/'Tekken 3.bin';image.write_bytes(b'x')
            (root/'Tekken 3.cue').write_text('FILE "tekken 3.BIN" BINARY\n  TRACK 01 MODE2/2352\n')
            self.assertEqual(backend.cue_for(image),root/'Tekken 3.cue')
            other=root/'other.bin';other.write_bytes(b'x')
            self.assertEqual(backend.cue_for(other),other)

    @unittest.skipUnless(os.environ.get('PSXRECOMP_TEST_TOOLCHAIN'),'Set PSXRECOMP_TEST_TOOLCHAIN to run real CMake/Ninja regression')
    def test_future_timestamp_build_loop_and_retry(self):
        toolchain=Path(os.environ['PSXRECOMP_TEST_TOOLCHAIN']).resolve()
        cmake=toolchain/'bin/cmake.exe'
        env=dict(os.environ,PATH=str(toolchain/'bin')+os.pathsep+os.environ.get('PATH',''),CMAKE_BUILD_PARALLEL_LEVEL='2')
        with tempfile.TemporaryDirectory(prefix='tekken-setup-loop-') as temp:
            root=Path(temp);build=root/'build-release';state=root/'.setup'
            source=root/'CMakeLists.txt'
            template=('cmake_minimum_required(VERSION 3.20)\n'
                      'project(SetupRegression NONE)\n'
                      'file(WRITE "${CMAKE_BINARY_DIR}/configured.txt" "REVISION:${TEKKEN3_TTT1_CHARACTERS}")\n'
                      'add_custom_target(psx-runtime COMMAND "${CMAKE_COMMAND}" -E copy '
                      '"${CMAKE_BINARY_DIR}/configured.txt" "${CMAKE_BINARY_DIR}/built.txt")\n')
            def write_revision(revision):
                source.write_text(template.replace('REVISION',revision),encoding='utf-8')
                future=time.time()+86400
                os.utime(source,(future,future))
                return source.stat().st_mtime_ns
            timestamp=write_revision('first')
            configured=subprocess.run([str(cmake),'-S',str(root),'-B',str(build),'-G','Ninja',
                '-DCMAKE_MAKE_PROGRAM='+str(toolchain/'bin/ninja.exe')],env=env,capture_output=True,text=True,timeout=30)
            self.assertEqual(configured.returncode,0,configured.stdout+configured.stderr)
            failed=subprocess.run([str(cmake),'--build',str(build),'--target','psx-runtime'],env=env,capture_output=True,text=True,timeout=90)
            self.assertNotEqual(failed.returncode,0)
            self.assertIn("manifest 'build.ninja' still dirty after 100 tries",failed.stdout+failed.stderr)
            sentinel=build/'completed-work.txt';sentinel.write_text('keep')
            with patch.object(backend,'ROOT',root),patch.object(backend,'BUILD',build),patch.object(backend,'STATE',state),patch.object(backend,'emit'):
                backend.build_game(toolchain,env,True)
                self.assertEqual((build/'built.txt').read_text(),'first:ON')
                self.assertEqual(source.stat().st_mtime_ns,timestamp)
                # Suppression must not prevent explicit configuration on retry,
                # including source changes and switching the TTT1 characters option.
                timestamp=write_revision('second')
                backend.build_game(toolchain,env,False)
            self.assertEqual((build/'built.txt').read_text(),'second:OFF')
            self.assertEqual(source.stat().st_mtime_ns,timestamp)
            self.assertEqual(sentinel.read_text(),'keep')
            self.assertNotIn('Re-running CMake',(state/'setup.log').read_text())

    def update_over_a_later_build(self,root,files,hours=1):
        """A release ZIP copied over the folder: its files dated as its commit,
        `hours` before the objects of the install's last build."""
        old=time.time()-hours*3600
        for name,text in files.items():
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text);os.utime(path,(old,old))

    def test_an_update_over_a_later_build_dates_only_the_changed_files(self):
        # B97: 1.4.0 copied over a 1.3.0 built after 1.4.0's commit: the new
        # sources older than the objects, Ninja compiled none of them again.
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);state=root/'.setup'
            self.update_over_a_later_build(root,{'src/a.c':'1.3.0','src/b.c':'same','CMakeLists.txt':'cmake'},hours=48)
            for made in ('build-release/a.obj','build-android/a.o','workspace/pack.bin','generated/game.c','src/__pycache__/x.pyc',
                         'Tekken 3 Expanded.exe','Tekken3Expanded.apk','.git/HEAD','tektagt.zip','roms/Tekken 3.cue'):
                (root/made).parent.mkdir(parents=True,exist_ok=True);(root/made).write_text('made')
            with patch.object(backend,'ROOT',root),patch.object(backend,'STATE',state):
                start=time.time()-1
                backend.date_changed_sources()   # no record: all of them
                self.assertTrue(all((root/n).stat().st_mtime>=start for n in ('src/a.c','src/b.c','CMakeLists.txt')))
                self.assertEqual(sorted(backend.load_json(state/'sources.json')),['CMakeLists.txt','src/a.c','src/b.c'])
                built=time.time();os.utime(root/'build-release/a.obj',(built,built))
                self.update_over_a_later_build(root,{'src/a.c':'1.4.0','src/b.c':'same','src/new.c':'new'})
                old=(root/'src/b.c').stat().st_mtime_ns
                backend.date_changed_sources()
                self.assertGreaterEqual((root/'src/a.c').stat().st_mtime,built)
                self.assertGreaterEqual((root/'src/new.c').stat().st_mtime,built)
                self.assertEqual((root/'src/b.c').stat().st_mtime_ns,old)      # same content: left as unpacked
                self.assertIn('2 changed file(s): src/a.c, src/new.c',(state/'setup.log').read_text())
                # Nothing changed since: nothing dated again.
                dates={n:(root/n).stat().st_mtime_ns for n in ('src/a.c','src/b.c','src/new.c')}
                backend.date_changed_sources()
                self.assertEqual({n:(root/n).stat().st_mtime_ns for n in dates},dates)

    def test_ninja_compiles_again_what_an_update_changed(self):
        # The same with Ninja deciding: the stale object linked before, the new source compiled after.
        ninja=shutil.which('ninja')
        if os.environ.get('PSXRECOMP_TEST_TOOLCHAIN'):ninja=str(Path(os.environ['PSXRECOMP_TEST_TOOLCHAIN'])/'bin/ninja.exe')
        if not ninja:self.skipTest('ninja not found (PATH or PSXRECOMP_TEST_TOOLCHAIN)')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);state=root/'.setup';build=root/'build-release';build.mkdir()
            compile_=f'"{sys.executable}" -c "import shutil,sys;shutil.copyfile(sys.argv[1],sys.argv[2])"'
            (build/'build.ninja').write_text(f'rule cc\n  command = {compile_} $in $out\nbuild game.obj: cc ../src/game.c\n')
            make=lambda:subprocess.run([ninja,'-C',str(build)],capture_output=True,text=True,timeout=60,check=True).stdout
            self.update_over_a_later_build(root,{'src/game.c':'1.3.0'},hours=48)
            with patch.object(backend,'ROOT',root),patch.object(backend,'STATE',state):
                backend.date_changed_sources();make()
                self.update_over_a_later_build(root,{'src/game.c':'1.4.0'})
                self.assertIn('no work to do',make())                    # the bug, without the setup's check
                self.assertEqual((build/'game.obj').read_text(),'1.3.0')
                backend.date_changed_sources();make()
            self.assertEqual((build/'game.obj').read_text(),'1.4.0')

    def test_archive_traversal_rejected_before_any_write(self):
        for name in ('../escape','C:/escape','safe/../../escape','safe\\..\\..\\escape','file:stream'):
            with self.subTest(name=name),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);archive=root/'bad.zip'
                with zipfile.ZipFile(archive,'w') as z:z.writestr('good','okay');z.writestr(name,'bad')
                with self.assertRaises(backend.SetupError):backend.safe_extract(archive,root/'out')
                self.assertFalse((root/'out/good').exists())

    def test_valid_archive_and_case_collision(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);archive=root/'tools.zip'
            with zipfile.ZipFile(archive,'w') as z:z.writestr('bin/','');z.writestr('bin/tool.exe','synthetic')
            backend.safe_extract(archive,root/'out')
            self.assertEqual((root/'out/bin/tool.exe').read_text(),'synthetic')
            with zipfile.ZipFile(archive,'w') as z:z.writestr('A','1');z.writestr('a','2')
            with self.assertRaises(backend.SetupError):backend.safe_extract(archive,root/'bad')

    def test_cached_tool_requires_its_digest(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'downloads').mkdir();path=root/'downloads/tool.zip';path.write_bytes(b'tool')
            spec={'filename':'tool.zip','sha256':hashlib.sha256(b'tool').hexdigest(),'url':'https://invalid.example/tool.zip','size':4}
            with patch.object(backend,'STATE',root),patch.object(backend.urllib.request,'urlopen',side_effect=OSError('offline')) as network:
                self.assertEqual(backend.download(spec),path);network.assert_not_called()
                path.write_bytes(b'bad')
                with self.assertRaises(backend.SetupError):backend.download(spec)
                network.assert_called_once()

    def test_missing_or_changed_game_is_not_marked_ready(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);exe=root/'build/game.exe';exe.parent.mkdir();exe.write_bytes(b'game')
            (root/'disc').mkdir();(root/'disc/Tekken 3 (USA).cue').write_text('synthetic')
            state=root/'.setup';backend.save_json(state/'ready.json',{'release':backend.RELEASE,'ttt1':False,'exe_sha256':backend.digest(exe)})
            with patch.object(backend,'ROOT',root),patch.object(backend,'STATE',state),patch.object(backend,'EXE',exe):
                self.assertTrue(backend.ready());exe.write_bytes(b'changed');self.assertFalse(backend.ready())

    def test_game_opens_on_its_launcher(self):
        # No --no-launcher: the game's own "Skip launcher on boot" decides;
        # --settings forces the launcher back on.
        with patch.object(backend,'ready',return_value=True),patch.object(backend.subprocess,'Popen') as popen:
            backend.launch_game();command=popen.call_args[0][0]
            self.assertNotIn('--no-launcher',command);self.assertNotIn('--launcher',command)
            backend.launch_game(settings=True);command=popen.call_args[0][0]
            self.assertIn('--launcher',command);self.assertNotIn('--no-launcher',command)

    def test_free_space_keeps_what_the_game_reads(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);build=root/'build-release';state=root/'.setup'
            spare=[root/'.setup/tools/mame/mame.exe',root/'.setup/downloads/tools.zip',root/'workspace/ttt1-import/roster/guests.txt',
                   build/'CMakeFiles/psx-runtime.dir/main.cpp.obj',build/'psxrecomp/CMakeFiles/x.dir/a.c.o']
            kept=[build/'Tekken_3_Expanded.exe',build/'mods/ttt1/guests.txt',root/'generated/SLUS_004.02_dispatch.c',
                  root/'disc/Tekken 3 (USA).cue',root/'saves/card1.mcd',state/'venv/pyvenv.cfg',state/'ready.json']
            for path in spare+kept:path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'x'*10)
            with patch.object(backend,'ROOT',root),patch.object(backend,'BUILD',build),patch.object(backend,'STATE',state):
                self.assertEqual(sorted(backend.spare_files()),sorted(spare))
                self.assertEqual(backend.spare_size(),50)
                self.assertFalse(backend.offer_free_space(50))
                self.assertTrue(backend.offer_free_space(1024**3))
                backend.free_space()
                self.assertEqual([p for p in spare if p.exists()],[]);self.assertEqual([p for p in kept if not p.exists()],[])
                backend.decline_free_space();self.assertFalse(backend.offer_free_space(1024**3))

    @unittest.skipIf(os.name=='nt','POSIX paths and modes')
    def test_linux_script_and_menu_entry_start_the_game_or_the_setup(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'tekken 3 $expanded';root.mkdir();script=root/'Tekken 3 Expanded.sh'
            with patch.object(backend,'ROOT',root),patch.object(backend,'PLAY_SH',script),\
                 patch.dict(os.environ,{'XDG_DATA_HOME':str(Path(temp)/'data')}):
                backend.play_linux();entry=backend.desktop_entry()
            self.assertEqual(entry,Path(temp)/'data/applications/tekken3-expanded.desktop')
            text=script.read_text()
            self.assertIn('sys.exit(0 if b.ready() else 3)',text);self.assertIn('[ $? -eq 3 ]',text);self.assertIn('exec ./"Setup Tekken 3.sh"',text)
            self.assertIn('exec build-release/Tekken_3_Expanded',text)
            desktop=entry.read_text()
            self.assertIn('Name=Tekken 3 Expanded\n',desktop);self.assertIn(f'Path={root}\n',desktop)
            self.assertIn('Exec="'+str(script).replace('$','\\$')+'"\n',desktop)
            self.assertTrue(os.access(script,os.X_OK))

    def test_macos_app_starts_the_game_or_the_setup(self):
        with tempfile.TemporaryDirectory() as temp:
            app=Path(temp)/'Tekken 3 Expanded.app'
            with patch.object(backend,'PLAY_APP',app):backend.play_app()
            script=app/'Contents/MacOS/Tekken 3 Expanded'
            self.assertTrue(os.access(script,os.X_OK));self.assertIn('launch_game()',script.read_text())
            self.assertIn('<string>Tekken 3 Expanded</string>',(app/'Contents/Info.plist').read_text())

    def test_android_apk_reports_its_path_and_its_problems(self):
        sys.path.insert(0,str(backend.ROOT/'tools/android'))
        import make_apk
        events=[]
        def fake_build(out,say,run,toolchain,env):
            say('Downloading the Android tools: ndk','10% of 700 MB');return out
        with patch.object(backend,'emit',lambda event='status',**data:events.append((event,data))),\
             patch.object(backend,'log_line'),patch.object(make_apk,'build',side_effect=fake_build) as build:
            self.assertEqual(backend.android_apk(toolchain=Path('tools')),backend.APK)
            self.assertEqual(build.call_args.kwargs['toolchain'],Path('tools'))
            self.assertIn(('status',{'message':'Downloading the Android tools: ndk','detail':'10% of 700 MB'}),events)
            kind,data=events[-1]
            self.assertEqual((kind,data['apk']),('apk',str(backend.APK)));self.assertIn('install -r',data['detail'])
            build.side_effect=make_apk.Stop('Java is missing')
            with self.assertRaisesRegex(backend.SetupError,'Java is missing'):backend.android_apk()

    def test_android_alone_needs_a_finished_setup(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(backend,'STATE',Path(temp)),patch.object(backend,'emit'),\
             patch.object(backend,'tools',return_value=None),patch.object(backend,'date_changed_sources'),\
             patch.object(backend,'android_apk') as android:
            with patch.object(backend,'ready',return_value=False):
                with self.assertRaises(backend.SetupError):backend.android_only()
                android.assert_not_called()
            with patch.object(backend,'ready',return_value=True):backend.android_only()
            android.assert_called_once_with(None)

    def test_android_alone_sets_up_without_the_pc_game(self):
        # Build Android APK with no game yet: the files, the generation and the
        # TTT1 import as for the PC, then the APK, and no PC build.
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);state=root/'.setup'
            roster=root/'workspace/ttt1-import/roster'
            def fake_import(command,**_):
                if any('ttt1_setup.py' in str(c) for c in command):
                    roster.mkdir(parents=True);(roster/'guests.txt').write_text('kuma 0 0\n')
                    (roster/'Kuma-TTT1-combat.jmv').write_bytes(b'x')
                    V=backend.import_version();(roster/V.STAMP).write_text(f'{V.TTT1_IMPORT_VERSION}\n')
            disc=root/'disc.cue';disc.write_text('FILE "disc.bin" BINARY\n')
            with patch.object(backend,'ROOT',root),patch.object(backend,'STATE',state),\
                 patch.object(backend,'WORK',root/'workspace/ttt1-import'),patch.object(backend,'ROSTER',roster),\
                 patch.object(backend,'INSTALLED',root/'build-release/mods/ttt1'),\
                 patch.multiple(backend,TTT_PS2_MUSIC_PACK=root/'workspace/ttt-stages/ps2-music-pack',
                                TTT_PS2_MUSIC_INSTALLED=root/'build-release/mods/ttt-ps2-music',
                                TTT_PS2_LASER_PACK=root/'workspace/ttt-ps2/laser-pack',
                                TTT_PS2_LASER_INSTALLED=root/'build-release/mods/ttt-ps2-laser'),\
                 patch.object(backend,'emit'),patch.object(backend,'complete'),\
                 patch.object(backend,'validate_disc'),patch.object(backend,'validate_ttt1'),patch.object(backend,'tools',return_value=None),\
                 patch.object(backend,'prepare_textures'),\
                 patch.object(backend,'run',side_effect=fake_import) as run,\
                 patch.object(backend,'single_bin',side_effect=lambda d:d),\
                 patch.object(backend.shutil,'disk_usage',return_value=type('U',(),{'free':8*1024**3})()),\
                 patch.object(backend,'build_game') as build,patch.object(backend,'android_apk') as android:
                backend.prepare(disc,Path('tektagt.zip'),True,android=True,pc=False)
                build.assert_not_called()
                android.assert_called_once_with(None,unittest.mock.ANY)
                self.assertTrue(any('ttt1_setup.py' in str(c) for call in run.call_args_list for c in call.args[0]))
                self.assertFalse((state/'ready.json').exists())
                self.assertEqual(backend.load_json(state/'android.json')['release'],backend.RELEASE)
                # Build again later: the APK alone, from what was prepared.
                (root/'generated').mkdir();(root/'generated/SLUS_004.02_dispatch.c').write_text('')
                (root/'disc').mkdir();(root/'disc/Tekken 3 (USA).cue').write_text('')
                android.reset_mock()
                with patch.object(backend,'ready',return_value=False):backend.android_only()
                android.assert_called_once_with(None)

    def test_android_downloads_are_spare_but_the_signing_key_is_kept(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);build=root/'build-release';state=root/'.setup'
            spare=root/'.setup/android/downloads/android-ndk-r28c-linux.zip'
            kept=[root/'.setup/android/release.keystore',root/'.setup/android/release.password',
                  root/'.setup/android/android-ndk-r28c/.sha1']
            for path in [spare,*kept]:path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'x')
            with patch.object(backend,'ROOT',root),patch.object(backend,'BUILD',build),patch.object(backend,'STATE',state):
                self.assertEqual(list(backend.spare_files()),[spare])
                backend.free_space()
            self.assertFalse(spare.exists());self.assertTrue(all(p.exists() for p in kept))

    @unittest.skipUnless(os.name=='nt','Windows process ownership')
    def test_window_asks_before_starting_with_an_unusable_optional_file(self):
        try:import tkinter;tkinter.Tk().destroy()
        except Exception:self.skipTest('no Tk window here')
        import easy_launcher
        seen=[]
        with tempfile.TemporaryDirectory() as temp:
            bad=Path(temp)/'tekken3.zip'
            with zipfile.ZipFile(bad,'w') as z:z.writestr('tet1vere.2e','not a ROM')
            def hook(app):
                app.ttt1.set(True);app.tekken3.set(str(bad));app.ttt_disc.set('')
                with patch.object(backend,'needs',return_value=(False,False)),patch.object(app,'ask_optional',side_effect=[False,True]) as ask,\
                     patch.object(easy_launcher.subprocess,'Popen') as popen,patch.object(easy_launcher,'ProcessJob'):
                    app.start();seen.append((ask.call_args[0][0][0]['key'],popen.called,app.status.get()))   # back to the files
                    app.start();seen.append(popen.call_args[0][0])                                          # on without it
                    app.cancel()
                app.window.after(0,app.window.destroy)
            with patch.object(backend,'STATE',Path(temp)/'.setup'):easy_launcher.gui(test_hook=hook)   # nothing of this checkout's
        self.assertEqual(seen[0],('tekken3',False,'Choose another tekken3.zip'))
        self.assertEqual(seen[1][seen[1].index('--tekken3')+1],str(bad))   # the backend logs it and goes on

    def test_cancel_closes_owned_worker(self):
        job=ProcessJob()
        child=subprocess.Popen([sys.executable,'-c','import sys,time;sys.stdin.readline();time.sleep(120)'],stdin=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            job.assign(child);child.stdin.write(b'START\n');child.stdin.flush()
            job.close();self.assertIsNotNone(child.wait(timeout=5))
        finally:
            job.close();child.stdin.close()
            if child.poll() is None:child.terminate();child.wait()

class UpdateTests(unittest.TestCase):
    """An existing install after a git pull or a new release zip: the setup
    brings it to the current TTT1 import version with the least work. The
    steps are mocked: no ROM, MAME or compiler."""
    def setUp(self):
        self.V=backend.import_version()
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        root=self.root=Path(temp.name);build=root/'build-release';state=root/'.setup';work=root/'workspace/ttt1-import'
        self.rom=root/'roms/tektagt.zip';self.disc=root/'roms/Tekken 3.cue'
        self.paths=dict(ROOT=root,STATE=state,BUILD=build,EXE=build/'game',WORK=work,ROSTER=work/'roster',INSTALLED=build/'mods/ttt1',
                        ARCADE_STAGES_PACKS=root/'workspace/arcade-stages/pack',ARCADE_STAGES_INSTALLED=build/'mods/arcade-stages',
                        TTT_STAGES_PACKS=root/'workspace/ttt-stages/pack',TTT_STAGES_INSTALLED=build/'mods/ttt-stages',
                        TTT_MUSIC_PACK=root/'workspace/ttt-stages/music-pack',TTT_MUSIC_INSTALLED=build/'mods/ttt-music',
                        TTT_PS2_MUSIC_PACK=root/'workspace/ttt-stages/ps2-music-pack',TTT_PS2_MUSIC_INSTALLED=build/'mods/ttt-ps2-music',
                        TTT_PS2_LASER_PACK=root/'workspace/ttt-ps2/laser-pack',TTT_PS2_LASER_INSTALLED=build/'mods/ttt-ps2-laser',
                        MODS_KEPT=build/'mods.kept',CINEMATICS=build/'mods/ttt-cinematics',ANDROID_CINEMATICS=root/'workspace/ttt-cinematics')
        self.commands=[]
        # TEXT: make_apk.up_to_date() leaves the terminal setup's on.
        for name,value in dict(self.paths,TEXT=False).items():
            patcher=patch.object(backend,name,value);patcher.start();self.addCleanup(patcher.stop)
        for name,value in dict(emit=None,complete=None,tools=None,prepare_textures=None,ttt_disc_supported=True,
                               validate_disc=None,run=self.fake_run,build_game=self.fake_build).items():
            patcher=patch.object(backend,name,side_effect=value) if callable(value) else patch.object(backend,name,return_value=value)
            patcher.start();self.addCleanup(patcher.stop)
        patcher=patch.object(backend.shutil,'disk_usage',return_value=shutil_usage(free=100*1024**3))
        patcher.start();self.addCleanup(patcher.stop)

    def catalogue(self,folder,stamp):
        folder.mkdir(parents=True,exist_ok=True)
        (folder/'guests.txt').write_text('jun 1 - --\n');(folder/'Jun-TTT1-combat.jmv').write_bytes(b'moves')
        if stamp:self.V.write_stamp(folder,stamp)

    def install(self,stamp,workspace=True,work_files=False,release=backend.RELEASE,ttt_stages=True):
        """A finished setup whose TTT1 import has version `stamp`; ttt_stages:
        with TTT's stages and music of this version beside the game (False:
        set up before TTT Stages, as 1.3.0)."""
        p=self.paths
        self.catalogue(p['INSTALLED'],stamp)
        if ttt_stages:
            self.ttt_packs(p['TTT_STAGES_INSTALLED'],self.A.TTT_STAGES_VERSION)
            self.ttt_music(p['TTT_MUSIC_INSTALLED'],self.M.MUSIC_VERSION)
        if workspace:self.catalogue(p['ROSTER'],stamp)
        if work_files:
            (p['WORK']/'ttt1').mkdir(parents=True);(p['WORK']/'ttt1/bankedroms.bin').write_bytes(b'rom');(p['WORK']/'captures').mkdir()
        p['EXE'].write_bytes(b'game');(self.root/'generated').mkdir();(self.root/'disc').mkdir()
        (self.root/'disc/Tekken 3 (USA).cue').write_text('cue')
        backend.save_json(p['STATE']/'ready.json',{'release':release,'ttt1':True,'exe_sha256':backend.digest(p['EXE'])})
        backend.save_json(p['STATE']/'last-inputs.json',{'disc':str(self.disc),'ttt1':str(self.rom),'include_ttt1':True,'tekken3':'','jin_red':False})

    def fake_run(self,command,**kwargs):
        """ttt1_setup.py as the real one leaves the roster: stamped."""
        command=[str(x) for x in command];self.commands.append(command)
        if command[1].endswith('ttt1_setup.py'):
            roster=self.paths['ROSTER']
            if '--update' not in command:self.catalogue(roster,None)
            self.V.write_stamp(roster)
        out=Path(command[command.index('--out')+1]) if '--out' in command else None
        if Path(command[1]).name=='install.py':
            if '--ttt1' in command:self.ttt_packs(out,self.A.TTT_STAGES_VERSION)
            else:self.packs(out,self.A.ARCADE_STAGES_VERSION)
        if Path(command[1]).name=='music_install.py':self.ttt_music(out,self.M.MUSIC_VERSION)
        if Path(command[1]).name=='ps2_music_install.py':self.ps2_music(out,self.M.PS2_VERSION)
        if Path(command[1]).name=='ttt_laser_install.py':
            if getattr(self,'laser_fails',False):raise backend.SetupError("The TTT PS2 effects could not be prepared.")
            self.laser(out,self.L.LASER_VERSION)

    def fake_build(self,toolchain,env,include_ttt1):
        self.commands.append(['build']);self.paths['EXE'].write_bytes(b'rebuilt game')
        # psxrecomp/runtime/runtime.cmake: the link empties mods/ first.
        shutil.rmtree(self.paths['BUILD']/'mods',ignore_errors=True)
        # CMakeLists.txt: the stage packs of workspace/ staged beside the game.
        for packs,installed in (('ARCADE_STAGES_PACKS','ARCADE_STAGES_INSTALLED'),('TTT_STAGES_PACKS','TTT_STAGES_INSTALLED'),
                                ('TTT_MUSIC_PACK','TTT_MUSIC_INSTALLED'),('TTT_PS2_MUSIC_PACK','TTT_PS2_MUSIC_INSTALLED'),
                                ('TTT_PS2_LASER_PACK','TTT_PS2_LASER_INSTALLED')):
            packs,installed=self.paths[packs],self.paths[installed]
            if (packs/'version.txt').is_file():
                shutil.rmtree(installed,ignore_errors=True)
                shutil.copytree(packs,installed)

    @property
    def A(self):return backend.arcade_stages_version()

    @property
    def M(self):return backend.ttt_music_version()

    @property
    def L(self):return backend.laser_version()

    def ttt_packs(self,folder,stamp):
        folder.mkdir(parents=True,exist_ok=True)
        for s in self.A.TTT_STAGES:(folder/self.A.pack_name(s)).write_bytes(b'ASTG')
        (folder/'version.txt').write_text(f'{stamp}\n')

    def ttt_music(self,folder,stamp):
        folder.mkdir(parents=True,exist_ok=True)
        (folder/self.M.FILE).write_bytes(b'TTTM');(folder/'version.txt').write_text(f'{stamp}\n')

    def ps2_music(self,folder,stamp):
        folder.mkdir(parents=True,exist_ok=True)
        (folder/self.M.PS2_FILE).write_bytes(b'TTP2');(folder/'version.txt').write_text(f'{stamp}\n')

    def laser(self,folder,stamp):
        folder.mkdir(parents=True,exist_ok=True)
        (folder/self.L.FILE).write_bytes(b'TIM');(folder/self.L.ANGEL_FILE).write_bytes(b'TIM')
        for name in self.L.HITSPARK_FILES:(folder/name).write_bytes(b'HFX6')
        (folder/'version.txt').write_text(f'{stamp}\n')

    def packs(self,folder,stamp):
        folder.mkdir(parents=True,exist_ok=True)
        for s in self.A.STAGES:(folder/self.A.pack_name(s)).write_bytes(b'ASTG')
        (folder/'version.txt').write_text(f'{stamp}\n')

    def with_tekken3(self,**ready):
        """A current install that was given tekken3.zip (difficulty levels made)."""
        self.install(self.V.TTT1_IMPORT_VERSION)
        zip_path=self.root/'roms/tekken3.zip';zip_path.parent.mkdir(exist_ok=True);zip_path.write_bytes(b'zip')
        (self.root/'workspace/difficulty').mkdir(parents=True);(self.root/'workspace/difficulty/levels.bin').write_bytes(b'T3DF')
        inputs=backend.load_json(self.paths['STATE']/'last-inputs.json');inputs['tekken3']=str(zip_path)
        backend.save_json(self.paths['STATE']/'last-inputs.json',inputs)
        state=backend.load_json(self.paths['STATE']/'ready.json');state.update(ready)
        backend.save_json(self.paths['STATE']/'ready.json',state)
        patcher=patch.object(backend,'tekken3_supported',return_value=True);patcher.start();self.addCleanup(patcher.stop)
        return zip_path

    def stage_runs(self):return [c for c in self.commands if c[1:2] and Path(c[1]).name=='install.py' and '--tekken3' in c]
    def ttt_runs(self):return [c for c in self.commands if c[1:2] and Path(c[1]).name=='install.py' and '--ttt1' in c]
    def music_runs(self):return [c for c in self.commands if c[1:2] and Path(c[1]).name=='music_install.py']
    def ps2_runs(self):return [c for c in self.commands if c[1:2] and Path(c[1]).name=='ps2_music_install.py']
    def laser_runs(self):return [c for c in self.commands if c[1:2] and Path(c[1]).name=='ttt_laser_install.py']

    def later(self):
        """Versions after 1 without steps, so a test's UPDATES[1] alone decides."""
        return {v:() for v in range(2,self.V.TTT1_IMPORT_VERSION+1)}

    def setup_runs(self):return [c for c in self.commands if c[1:2] and c[1].endswith('ttt1_setup.py')]
    def imports(self):return [c for c in self.setup_runs() if '--update' not in c]
    def updates(self):return [c for c in self.setup_runs() if '--update' in c]
    def generates(self):return [c for c in self.commands if 'generate' in c]

    def assert_updated(self):
        self.assertTrue(backend.ready())
        self.assertEqual(self.V.read_stamp(self.paths['INSTALLED']),self.V.TTT1_IMPORT_VERSION)
        self.assertEqual(backend.load_json(self.paths['STATE']/'ready.json')['ttt1_import'],self.V.TTT1_IMPORT_VERSION)

    def test_current_install_does_nothing_again(self):
        self.install(self.V.TTT1_IMPORT_VERSION)
        self.assertTrue(backend.ready())
        self.assertEqual(backend.ttt1_plan(),('current',[]))
        backend.update_install()
        self.assertEqual((self.imports(),self.updates(),self.generates()),([],[],[]))
        self.assert_updated()

    def test_older_import_runs_only_its_update_steps_then_builds(self):
        self.install(0,work_files=True)
        self.assertFalse(backend.ready())     # Play opens the setup, not the older game
        with patch.dict(self.V.UPDATES,{1:('hands','panda-tiger'),**self.later()}):
            self.assertEqual(backend.ttt1_plan(),('update',['hands','panda-tiger']))
            backend.update_install()           # no ROM, no disc: neither is read
        self.assertEqual(self.imports(),[]);self.assertEqual(self.generates(),[])
        self.assertEqual(len(self.updates()),1);self.assertEqual(self.commands[-1],['build'])
        self.assertIn('hands (',(self.paths['STATE']/'setup.log').read_text())
        self.assert_updated()

    def test_older_import_that_needs_a_new_import_uses_the_remembered_rom(self):
        self.install(0);self.rom.parent.mkdir();self.rom.write_bytes(b'zip')
        self.assertEqual(backend.ttt1_plan(),('import',[]))   # UPDATES[1] is None
        with patch.object(backend,'validate_ttt1') as validate:backend.update_install()
        validate.assert_called_once_with(self.rom,True)
        self.assertEqual(len(self.imports()),1);self.assertEqual(self.updates(),[])
        command=self.imports()[0];self.assertEqual(command[command.index('--ttt1')+1],str(self.rom))
        self.assertNotIn('--mame',command)   # TTT1 comes from the ROM alone
        self.assert_updated()

    def test_missing_rom_is_asked_for_again(self):
        self.install(0)
        with self.assertRaisesRegex(backend.SetupError,'needs your tektagt.zip again.*'+re.escape(str(self.rom))):
            backend.update_install()
        self.assertEqual(self.imports(),[]);self.assertFalse(backend.ready())
        self.assertEqual(backend.needs(True),(False,True))   # the window asks for the ROM, not the disc

    def test_deleted_workspace_updates_a_copy_of_the_installed_roster(self):
        self.install(0,workspace=False)
        with patch.dict(self.V.UPDATES,{1:('hands',),**self.later()}):
            self.assertEqual(backend.ttt1_plan(),('update',['hands']))
            backend.update_install()
        self.assertEqual(self.imports(),[]);self.assertEqual(len(self.updates()),1)
        self.assertTrue((self.paths['ROSTER']/'Jun-TTT1-combat.jmv').is_file())
        self.assert_updated()

    def test_deleted_workspace_and_a_step_that_needs_it_asks_for_the_rom(self):
        self.install(0,workspace=False)
        with patch.dict(self.V.UPDATES,{1:('devil-jin',),**self.later()}):
            self.assertEqual(backend.ttt1_plan(),('import',[]))
            with self.assertRaisesRegex(backend.SetupError,'tektagt.zip'):backend.update_install()

    def test_new_release_rebuilds_without_importing_again(self):
        self.install(self.V.TTT1_IMPORT_VERSION,workspace=False,release='0.0.0-older')
        self.disc.parent.mkdir();self.disc.write_text('cue')
        self.assertFalse(backend.ready())
        backend.update_install()
        self.assertEqual(len(self.generates()),1);self.assertEqual((self.imports(),self.updates()),([],[]))
        self.assert_updated()

    def test_update_step_on_a_roster_copy(self):
        """tools/ttt1_setup.py --update itself, on a roster without the work files."""
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
        import ttt1_setup
        roster=self.root/'roster';self.catalogue(roster,None)
        (roster/'guests.txt').write_text('jun 1 -\n')                 # before the grip column
        with patch.object(ttt1_setup,'WORK',self.paths['WORK']),patch.dict(self.V.UPDATES,{1:('hands',),**self.later()}):
            with contextlib.redirect_stdout(io.StringIO()):ttt1_setup.update(roster);ttt1_setup.update(roster)   # idempotent
        self.assertEqual((roster/'guests.txt').read_text(),'jun 1 - '+ttt1_setup.TABLE['jun'].get('hands','--')+'\n')
        self.assertEqual(self.V.read_stamp(roster),self.V.TTT1_IMPORT_VERSION)

    def test_android_apk_of_an_older_install_updates_it_first(self):
        self.install(0,work_files=True)
        order=[]
        with patch.object(backend,'android_apk',side_effect=lambda *a:order.append('apk')),\
             patch.dict(self.V.UPDATES,{1:('hands',)}):
            backend.run.side_effect=lambda command,**k:(order.append('update'),self.fake_run(command,**k))
            backend.android_only()
        self.assertEqual(order,['update','apk']);self.assertEqual(self.commands[-1],['build'])
        self.assert_updated()

    def test_android_apk_never_built_from_an_older_import(self):
        self.install(0)                           # a new import is needed, and the ROM has moved
        with patch.object(backend,'android_apk') as android:
            with self.assertRaisesRegex(backend.SetupError,'tektagt.zip'):backend.android_only()
        android.assert_not_called()

    def test_build_android_apk_script_updates_an_older_install_first(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools/android'))
        import make_apk
        self.install(0,work_files=True)
        with patch.dict(self.V.UPDATES,{1:('hands',)}),patch.object(make_apk,'report'):
            make_apk.up_to_date()
        self.assertEqual(len(self.updates()),1);self.assert_updated()
        for folder in ('INSTALLED','ROSTER'):self.V.write_stamp(self.paths[folder],0)   # a new import needed, the ROM moved
        with patch.object(make_apk,'report'),self.assertRaisesRegex(make_apk.Stop,'tektagt.zip'):make_apk.up_to_date()

    def test_tekken3_makes_the_arcade_stages_before_the_build(self):
        zip_path=self.with_tekken3()            # set up with tekken3.zip before the arcade stages existed
        self.assertFalse(backend.ready())
        backend.update_install()
        self.assertEqual(len(self.stage_runs()),1);self.assertEqual(self.commands[-1],['build'])
        command=self.stage_runs()[0];self.assertEqual(command[command.index('--tekken3')+1],str(zip_path))
        self.assertEqual(self.imports(),[])
        self.assertTrue(self.A.current(self.paths['ARCADE_STAGES_INSTALLED']))
        self.assertTrue(backend.load_json(self.paths['STATE']/'ready.json')['arcade_stages'])
        self.assertTrue(backend.ready())
        self.commands.clear();backend.update_install()      # current: not made again
        self.assertEqual(self.stage_runs(),[])

    def test_older_arcade_stages_are_made_again(self):
        self.with_tekken3(arcade_stages=True)
        self.packs(self.paths['ARCADE_STAGES_INSTALLED'],self.A.ARCADE_STAGES_VERSION-1)
        self.assertFalse(backend.ready())
        backend.update_install()
        self.assertEqual(len(self.stage_runs()),1);self.assertTrue(backend.ready())

    def test_freed_workspace_keeps_the_installed_arcade_stages(self):
        self.with_tekken3(arcade_stages=True)
        self.packs(self.paths['ARCADE_STAGES_INSTALLED'],self.A.ARCADE_STAGES_VERSION)
        self.assertTrue(backend.ready())
        backend.update_install()
        self.assertEqual(self.stage_runs(),[]);self.assertTrue(backend.ready())

    def test_arcade_stages_that_fail_keep_the_ps1_stages(self):
        self.with_tekken3()
        def fail(command,**k):
            if str(command[1]).endswith('install.py'):raise backend.SetupError('no')
            self.fake_run(command,**k)
        backend.run.side_effect=fail
        backend.update_install()                 # the setup still finishes
        self.assertFalse(backend.load_json(self.paths['STATE']/'ready.json')['arcade_stages'])
        self.assertTrue(backend.ready())

    def test_no_tekken3_no_arcade_stages(self):
        self.install(self.V.TTT1_IMPORT_VERSION)
        self.assertTrue(backend.ready())
        backend.update_install()
        self.assertEqual(self.stage_runs(),[])
        self.assertFalse(backend.load_json(self.paths['STATE']/'ready.json')['arcade_stages'])

    def test_arcade_stages_version_stamp(self):
        folder=self.root/'packs'
        self.assertFalse(self.A.current(folder))
        self.packs(folder,self.A.ARCADE_STAGES_VERSION);self.assertTrue(self.A.current(folder))
        (folder/'stage12.ast').unlink();self.assertFalse(self.A.current(folder))

    def test_mod_settings_survive_the_rebuild(self):
        self.install(self.V.TTT1_IMPORT_VERSION,ttt_stages=False)
        settings=self.paths['BUILD']/'mods/state.toml'
        player='format_version = 2 # the player'
        settings.write_text(player)
        backend.update_install()
        self.assertEqual(self.commands[-1],['build'])          # which emptied mods/
        self.assertEqual(settings.read_text(),player)
        self.assertFalse(self.paths['MODS_KEPT'].exists())
        self.assertTrue(backend.ready())

    def test_an_update_unpacked_over_an_older_folder_drops_the_retired_mods(self):
        # B86 (GH#108, GH#137): 1.3.0 unpacked over 1.2.1 kept Yoshimitsu Forest HD,
        # enabled, its plugin no longer built: the launcher's Play did nothing.
        self.install(self.V.TTT1_IMPORT_VERSION)
        root,build=self.root,self.paths['BUILD']
        left=[root/p/'1.0.0' for p in backend.RETIRED_SOURCES]+[build/p for p in backend.RETIRED_STAGED]
        for folder in left:folder.mkdir(parents=True,exist_ok=True);(folder/'manifest.toml').write_text('old')
        kept=root/'mods/preloaded/packages/tekken3.skin.julia-blue/1.0.0/manifest.toml'
        kept.parent.mkdir(parents=True);kept.write_text('current')
        backend.update_install()
        self.assertEqual([p for p in left if p.exists()],[])
        self.assertEqual(kept.read_text(),'current')
        self.assertIn('Removed, no longer part of the game: mods/preloaded/packages/tekken3.visual.forest-hd',
                      (self.paths['STATE']/'setup.log').read_text())

    def test_the_build_never_stages_a_retired_mod(self):
        # CMakeLists.txt's built-in catalog step, its commands run as written on
        # a folder whose mods/preloaded still holds a retired package.
        text=(Path(__file__).resolve().parents[1]/'CMakeLists.txt').read_text(encoding='utf-8')
        end=text.index('COMMENT "Staging Tekken 3 built-in mod catalog"')
        step=[l for l in text[text.rindex('add_custom_command(',0,end):end].splitlines() if not l.strip().startswith('#')]
        with tempfile.TemporaryDirectory() as temp:
            source,game=Path(temp)/'source',Path(temp)/'build'
            for package in ('tekken3.visual.forest-hd','tekken3.skin.julia-blue'):
                manifest=source/'mods/preloaded/packages'/package/'1.0.0/manifest.toml'
                manifest.parent.mkdir(parents=True);manifest.write_text(package)
            (game/'mods/packages/psx.enhancement.fast-loading').mkdir(parents=True)   # the framework's catalog
            for command in '\n'.join(step).split('COMMAND ${CMAKE_COMMAND} -E ')[1:]:
                args=[a.replace('${CMAKE_CURRENT_SOURCE_DIR}',str(source)).replace('$<TARGET_FILE_DIR:psx-runtime>',str(game))
                      for a in re.findall(r'"([^"]*)"',command)]
                verb=command.split()[0]
                if verb=='rm':
                    for path in args:shutil.rmtree(path,ignore_errors=True)
                elif verb=='copy_directory':shutil.copytree(args[0],args[1],dirs_exist_ok=True)
                else:self.fail(f'unexpected command in the catalog step: {verb}')
            staged=sorted(p.name for p in (game/'mods/packages').iterdir())
            self.assertEqual(staged,['psx.enhancement.fast-loading','tekken3.skin.julia-blue'])
            self.assertEqual([p for p in backend.RETIRED_STAGED if (game/p).exists()],[])

    def test_freed_workspace_keeps_what_the_setup_made_across_the_rebuild(self):
        self.install(self.V.TTT1_IMPORT_VERSION,workspace=False,release='0.0.0-older')   # a rebuild, workspace/ freed
        self.disc.parent.mkdir();self.disc.write_text('cue')
        backend.update_install()
        self.assertEqual(self.commands[-1],['build'])
        self.assertTrue(backend.ttt1_current(self.paths['INSTALLED']))
        self.assertTrue(self.A.ttt_current(self.paths['TTT_STAGES_INSTALLED']))
        self.assertTrue(self.M.current(self.paths['TTT_MUSIC_INSTALLED']))
        self.assertTrue(backend.ready())

    def test_a_build_cut_short_keeps_the_mod_settings_for_the_next_one(self):
        self.install(self.V.TTT1_IMPORT_VERSION)
        settings=self.paths['BUILD']/'mods/state.toml';settings.write_text('player')
        with self.assertRaises(KeyboardInterrupt):
            with backend.kept_mods():
                shutil.rmtree(self.paths['BUILD']/'mods');raise KeyboardInterrupt   # the window closed mid-link
        # __exit__ ran: back already. Killed instead (no __exit__): mods.kept waits for the next build.
        self.assertEqual(settings.read_text(),'player')
        backend.kept_mods().__enter__();shutil.rmtree(self.paths['BUILD']/'mods')
        self.assertEqual((self.paths['MODS_KEPT']/'state.toml').read_text(),'player')
        with backend.kept_mods():self.fake_build(None,None,True)
        self.assertEqual(settings.read_text(),'player');self.assertFalse(self.paths['MODS_KEPT'].exists())

    def with_tektagt(self):
        """An install set up with the TTT1 characters before TTT Stages (1.3.0), its tektagt.zip still there."""
        self.install(self.V.TTT1_IMPORT_VERSION,ttt_stages=False)
        self.rom.parent.mkdir(exist_ok=True);self.rom.write_bytes(b'zip')

    def test_ttt1_install_gets_the_ttt_stages_and_music_at_its_update(self):
        self.with_tektagt()
        self.assertFalse(backend.ready())          # Play opens the setup: Update & play
        backend.update_install()
        self.assertEqual(self.imports(),[])
        self.assertEqual((len(self.ttt_runs()),len(self.music_runs())),(1,1))
        for command in self.ttt_runs()+self.music_runs():self.assertEqual(command[command.index('--ttt1')+1],str(self.rom))
        self.assertEqual(self.commands[-1],['build'])   # made before the build, which stages them
        self.assertTrue(self.A.ttt_current(self.paths['TTT_STAGES_INSTALLED']))
        self.assertTrue(self.M.current(self.paths['TTT_MUSIC_INSTALLED']))
        state=backend.load_json(self.paths['STATE']/'ready.json')
        self.assertEqual((state['ttt_stages'],state['ttt_music']),(True,True))
        self.assertTrue(backend.ready())
        self.commands.clear();backend.update_install()      # current: not made again
        self.assertEqual((self.ttt_runs(),self.music_runs()),([],[]))

    def test_older_ttt_stages_or_music_are_made_again(self):
        self.install(self.V.TTT1_IMPORT_VERSION);self.rom.parent.mkdir();self.rom.write_bytes(b'zip')
        self.assertTrue(backend.ready())
        self.ttt_packs(self.paths['TTT_STAGES_INSTALLED'],self.A.TTT_STAGES_VERSION-1)
        self.assertFalse(backend.ready())
        backend.update_install()
        self.assertEqual((len(self.ttt_runs()),self.music_runs()),(1,[]));self.assertTrue(backend.ready())
        self.ttt_music(self.paths['TTT_MUSIC_INSTALLED'],self.M.MUSIC_VERSION-1)
        shutil.rmtree(self.paths['TTT_STAGES_PACKS'].parent)   # workspace/ freed since
        self.assertFalse(backend.ready())
        self.commands.clear();backend.update_install()
        self.assertEqual((self.ttt_runs(),len(self.music_runs())),([],1))   # the stages beside the game are current
        self.assertTrue(backend.ready())

    def test_ttt_stages_without_tektagt_keep_tekken3s(self):
        self.install(self.V.TTT1_IMPORT_VERSION,ttt_stages=False)   # the ROM has moved
        self.assertFalse(backend.ready())
        backend.update_install()                 # the setup still finishes, no new import needed
        self.assertEqual((self.ttt_runs(),self.music_runs()),([],[]))
        state=backend.load_json(self.paths['STATE']/'ready.json')
        self.assertEqual((state['ttt_stages'],state['ttt_music']),(False,False))
        self.assertTrue(backend.ready())         # and does not ask again at each start

    def test_ttt_stages_that_fail_keep_tekken3s(self):
        self.with_tektagt()
        def fail(command,**k):
            if '--ttt1' in [str(x) for x in command] and Path(command[1]).name=='install.py':raise backend.SetupError('no')
            self.fake_run(command,**k)
        backend.run.side_effect=fail
        backend.update_install()
        state=backend.load_json(self.paths['STATE']/'ready.json')
        self.assertEqual((state['ttt_stages'],state['ttt_music']),(False,True))   # the music is made all the same
        self.assertTrue(backend.ready())

    def test_no_ttt1_no_ttt_stages(self):
        self.install(self.V.TTT1_IMPORT_VERSION,ttt_stages=False);self.rom.parent.mkdir();self.rom.write_bytes(b'zip')
        inputs=backend.load_json(self.paths['STATE']/'last-inputs.json');inputs['include_ttt1']=False
        backend.save_json(self.paths['STATE']/'last-inputs.json',inputs)
        backend.update_install()
        self.assertEqual((self.ttt_runs(),self.music_runs()),([],[]))
        self.assertFalse(backend.load_json(self.paths['STATE']/'ready.json')['ttt_stages'])

    def test_android_alone_needs_current_ttt_stages(self):
        self.with_tektagt()
        self.ttt_packs(self.paths['TTT_STAGES_PACKS'],self.A.TTT_STAGES_VERSION)
        backend.save_json(self.paths['STATE']/'android.json',{'release':backend.RELEASE,'ttt1':False,'ttt_stages':True})
        (self.root/'generated/SLUS_004.02_dispatch.c').write_text('')
        self.assertTrue(backend.android_ready())
        self.ttt_packs(self.paths['TTT_STAGES_PACKS'],self.A.TTT_STAGES_VERSION-1)
        self.assertFalse(backend.android_ready())

    def with_ttt_disc(self,exists=True):
        """A current install from before the stages' PS2 music that was given the TTT PS2 disc (for the endings)."""
        self.install(self.V.TTT1_IMPORT_VERSION)
        self.ttt_disc=self.root/'roms/TTT PS2.cue';self.ttt_disc.parent.mkdir(exist_ok=True)
        if exists:self.ttt_disc.write_text('cue')
        inputs=backend.load_json(self.paths['STATE']/'last-inputs.json');inputs['ttt_disc']=str(self.ttt_disc)
        backend.save_json(self.paths['STATE']/'last-inputs.json',inputs)

    def test_ttt_disc_install_gets_the_ps2_music_at_its_update(self):
        self.with_ttt_disc()
        self.assertFalse(backend.ready())          # Play opens the setup: Update & play
        backend.update_install()
        self.assertEqual([c[c.index('--ttt-disc')+1] for c in self.ps2_runs()],[str(self.ttt_disc)])
        self.assertEqual(self.commands[-1],['build'])   # made before the build, which stages it
        self.assertTrue(self.M.ps2_current(self.paths['TTT_PS2_MUSIC_INSTALLED']))
        self.assertTrue(backend.load_json(self.paths['STATE']/'ready.json')['ttt_ps2_music'])
        self.assertTrue(backend.ready())
        self.commands.clear();backend.update_install()      # current: not made again
        self.assertEqual(self.ps2_runs(),[])
        self.ps2_music(self.paths['TTT_PS2_MUSIC_INSTALLED'],self.M.PS2_VERSION-1)
        shutil.rmtree(self.paths['TTT_PS2_MUSIC_PACK'])      # older, workspace/ freed since: made again
        self.assertFalse(backend.ready())
        backend.update_install()
        self.assertEqual(len(self.ps2_runs()),1);self.assertTrue(backend.ready())

    def test_no_ttt_disc_no_ps2_music(self):
        self.install(self.V.TTT1_IMPORT_VERSION)
        self.assertTrue(backend.ready())           # an install without the disc is not asked for it
        self.ps2_music(self.paths['TTT_PS2_MUSIC_PACK'],self.M.PS2_VERSION)   # given once, the field cleared since
        self.ps2_music(self.paths['TTT_PS2_MUSIC_INSTALLED'],self.M.PS2_VERSION)
        backend.update_install()
        self.assertEqual(self.ps2_runs(),[])
        self.assertFalse(self.paths['TTT_PS2_MUSIC_PACK'].exists() or self.paths['TTT_PS2_MUSIC_INSTALLED'].exists())
        self.assertFalse(backend.load_json(self.paths['STATE']/'ready.json')['ttt_ps2_music'])
        self.assertTrue(backend.ready())

    def test_another_disc_keeps_the_arcade_music(self):
        self.with_ttt_disc()
        backend.ttt_disc_supported.return_value=False
        backend.update_install()
        self.assertEqual(self.ps2_runs(),[])
        self.assertFalse(backend.load_json(self.paths['STATE']/'ready.json')['ttt_ps2_music'])
        self.assertTrue(backend.ready())         # and does not ask again at each start

    def test_moved_ttt_disc_keeps_a_current_copy(self):
        self.with_ttt_disc(exists=False)
        self.ps2_music(self.paths['TTT_PS2_MUSIC_INSTALLED'],self.M.PS2_VERSION)
        self.laser(self.paths['TTT_PS2_LASER_INSTALLED'],self.L.LASER_VERSION)
        backend.update_install()
        self.assertEqual(self.ps2_runs(),[])
        self.assertTrue(self.M.ps2_current(self.paths['TTT_PS2_MUSIC_INSTALLED']))   # kept across the build
        self.assertTrue(backend.load_json(self.paths['STATE']/'ready.json')['ttt_ps2_music'])
        self.assertEqual(self.laser_runs(),[])
        self.assertTrue(self.L.current(self.paths['TTT_PS2_LASER_INSTALLED']))
        self.assertTrue(backend.load_json(self.paths['STATE']/'ready.json')['ttt_ps2_laser'])

    # Devil's and Angel's PS2 laser textures, read on the same disc.
    def test_ttt_disc_install_gets_the_ps2_laser_at_its_update(self):
        self.with_ttt_disc()
        self.ps2_music(self.paths['TTT_PS2_MUSIC_INSTALLED'],self.M.PS2_VERSION)   # an install from before the laser
        state=backend.load_json(self.paths['STATE']/'ready.json');state['ttt_ps2_music']=True
        backend.save_json(self.paths['STATE']/'ready.json',state)
        self.assertFalse(backend.ready())          # Play opens the setup: Update & play
        backend.update_install()
        self.assertEqual([c[c.index('--ttt-disc')+1] for c in self.laser_runs()],[str(self.ttt_disc)])
        self.assertEqual(self.ps2_runs(),[])        # the music was current
        self.assertEqual(self.commands[-1],['build'])
        self.assertTrue(self.L.current(self.paths['TTT_PS2_LASER_INSTALLED']))
        self.assertTrue(backend.load_json(self.paths['STATE']/'ready.json')['ttt_ps2_laser'])
        self.assertTrue(backend.ready())
        self.commands.clear();backend.update_install()      # current: not made again
        self.assertEqual(self.laser_runs(),[])
        self.laser(self.paths['TTT_PS2_LASER_INSTALLED'],self.L.LASER_VERSION-1)
        shutil.rmtree(self.paths['TTT_PS2_LASER_PACK'])      # older, workspace/ freed since: made again
        self.assertFalse(backend.ready())
        backend.update_install()
        self.assertEqual(len(self.laser_runs()),1);self.assertTrue(backend.ready())

    def test_no_ttt_disc_no_ps2_laser(self):
        self.install(self.V.TTT1_IMPORT_VERSION)
        self.assertTrue(backend.ready())           # an install without the disc is not asked for it
        self.laser(self.paths['TTT_PS2_LASER_PACK'],self.L.LASER_VERSION)   # given once, the field cleared since
        self.laser(self.paths['TTT_PS2_LASER_INSTALLED'],self.L.LASER_VERSION)
        backend.update_install()
        self.assertEqual(self.laser_runs(),[]);self.assertEqual(self.commands[-1],['build'])
        self.assertFalse(self.paths['TTT_PS2_LASER_PACK'].exists() or self.paths['TTT_PS2_LASER_INSTALLED'].exists())
        self.assertFalse(backend.load_json(self.paths['STATE']/'ready.json')['ttt_ps2_laser'])
        self.assertTrue(backend.ready())

    def test_a_laser_that_fails_keeps_the_yellow_beam(self):
        self.with_ttt_disc();self.laser_fails=True
        backend.update_install()
        self.assertEqual(len(self.laser_runs()),1);self.assertEqual(self.commands[-1],['build'])
        self.assertTrue(backend.load_json(self.paths['STATE']/'ready.json')['ttt_ps2_music'])   # the rest goes on
        self.assertFalse(backend.load_json(self.paths['STATE']/'ready.json')['ttt_ps2_laser'])
        self.assertIn("Skipping the TTT PS2 effects",[c.kwargs.get('message') for c in backend.emit.call_args_list])
        self.assertTrue(backend.ready())         # and does not ask again at each start

    def test_a_disc_set_aside_keeps_what_it_made(self):
        # Moved: the laser needs it, the terminal setup goes on without it; the PS2 music made before stays.
        self.with_ttt_disc(exists=False)
        self.ps2_music(self.paths['TTT_PS2_MUSIC_INSTALLED'],self.M.PS2_VERSION)
        self.assertIn('no longer there',backend.optional_problems(True,None,self.ttt_disc)[0]['reason'])
        backend.update_install()
        self.assertEqual(self.laser_runs(),[])
        self.assertTrue(self.M.ps2_current(self.paths['TTT_PS2_MUSIC_INSTALLED']))
        state=backend.load_json(self.paths['STATE']/'ready.json')
        self.assertTrue(state['ttt_ps2_music']);self.assertFalse(state['ttt_ps2_laser'])
        self.assertTrue(backend.ready())

    # B85: an optional file the setup reads but cannot use is said, not only logged.
    def bad_tekken3(self):
        """A current install given a tekken3.zip of the TET1 revision (made up: its names only)."""
        self.install(self.V.TTT1_IMPORT_VERSION)
        zip_path=self.root/'roms/tekken3.zip';zip_path.parent.mkdir(exist_ok=True)
        with zipfile.ZipFile(zip_path,'w') as z:z.writestr('tet1vere.2e','not a ROM');z.writestr('tet1vere.2j','not a ROM')
        inputs=backend.load_json(self.paths['STATE']/'last-inputs.json');inputs['tekken3']=str(zip_path)
        backend.save_json(self.paths['STATE']/'last-inputs.json',inputs)
        return zip_path

    def test_unsupported_tekken3_is_said_then_skipped(self):
        zip_path=self.bad_tekken3()
        problems=backend.optional_problems(True,zip_path)
        self.assertEqual([p['key'] for p in problems],['tekken3'])
        self.assertIn('TET1',problems[0]['reason']);self.assertIn('3a5638c6ad40bfde6e12fdfd6d469f6ea5e9f4fb',problems[0]['expected'])
        backend.update_install()                 # the window asked before it started: on without it
        self.assertEqual(self.stage_runs(),[]);self.assertEqual(self.commands[-1],['build'])
        self.assertFalse(backend.load_json(self.paths['STATE']/'ready.json')['arcade_stages'])
        self.assertIn(f'{zip_path}: It is the TET1 revision',(self.paths['STATE']/'setup.log').read_text())
        self.assertIn('Going on without your tekken3.zip',[c.kwargs.get('message') for c in backend.emit.call_args_list])
        self.assertTrue(backend.ready())         # and does not ask again at each start

    def test_why_tekken3_is_not_supported(self):
        folder=self.root/'zips';folder.mkdir()
        other=folder/'other.zip'
        with zipfile.ZipFile(other,'w') as z:z.writestr('tet2vere1.2e','not the ROM');z.writestr('tet3.3b','x')
        (folder/'damaged.zip').write_bytes(b'PK not a zip')
        for path,reason in ((other,'not those of'),(folder/'damaged.zip','cannot be read'),(folder/'gone.zip','no longer there')):
            self.assertFalse(backend.tekken3_supported(path));self.assertIn(reason,backend.tekken3_problem(path))

    def test_terminal_setup_asks_before_going_on_without(self):
        self.bad_tekken3()
        with patch.object(backend,'TEXT',True),patch.object(backend.sys,'stdin') as stdin,\
             patch('builtins.input',return_value='n') as asked,contextlib.redirect_stdout(io.StringIO()) as shown:
            stdin.isatty.return_value=True
            with self.assertRaisesRegex(backend.SetupError,'another tekken3.zip'):backend.update_install()
            self.assertIn('Continue without it?',asked.call_args[0][0]);self.assertIn('tet2vere1.2j',shown.getvalue())
            self.assertEqual(self.commands,[]);self.assertFalse(backend.ready())   # stopped before any work
            asked.return_value='y';backend.update_install()
        self.assertEqual(self.stage_runs(),[]);self.assertEqual(self.commands[-1],['build']);self.assertTrue(backend.ready())

    def test_unsupported_ttt_disc_is_said_then_skipped(self):
        self.with_ttt_disc()                     # a .cue naming no image: not SLUS-20001
        with patch.object(backend,'ttt_disc_supported',side_effect=TTT_DISC_SUPPORTED):
            problems=backend.optional_problems(True,None,self.ttt_disc,cinematics=True)
            self.assertEqual([p['key'] for p in problems],['ttt_disc'])
            self.assertIn('SLUS-20001',problems[0]['reason']);self.assertIn("Cinematics' endings",problems[0]['without'])
            backend.update_install()
        self.assertEqual(self.ps2_runs(),[])
        self.assertFalse(backend.load_json(self.paths['STATE']/'ready.json')['ttt_ps2_music'])
        self.assertIn(f'{self.ttt_disc}: It is not Tekken Tag Tournament USA',(self.paths['STATE']/'setup.log').read_text())
        self.assertIn('Going on without your TTT PS2 disc',[c.kwargs.get('message') for c in backend.emit.call_args_list])

    def test_both_unsupported_are_asked_once(self):
        zip_path=self.bad_tekken3();self.ttt_disc=self.root/'roms/TTT PS2.iso';self.ttt_disc.write_bytes(bytes(4096))
        with patch.object(backend,'ttt_disc_supported',side_effect=TTT_DISC_SUPPORTED),patch.object(backend,'TEXT',True),\
             patch.object(backend.sys,'stdin') as stdin,patch('builtins.input',return_value='') as asked,\
             contextlib.redirect_stdout(io.StringIO()):
            stdin.isatty.return_value=True
            self.assertEqual(len(backend.optional_problems(True,zip_path,self.ttt_disc)),2)
            with self.assertRaisesRegex(backend.SetupError,'another tekken3.zip and TTT PS2 disc'):
                backend.prepare(self.disc,self.rom,True,zip_path,ttt_disc=self.ttt_disc)
        asked.assert_called_once();self.assertIn('Continue without them?',asked.call_args[0][0])

    def test_no_optional_file_asks_nothing(self):
        self.install(self.V.TTT1_IMPORT_VERSION)
        self.assertEqual(backend.optional_problems(True),[])
        with patch.object(backend,'TEXT',True),patch.object(backend.sys,'stdin') as stdin,patch('builtins.input') as asked,\
             contextlib.redirect_stdout(io.StringIO()):
            stdin.isatty.return_value=True;backend.update_install()
        asked.assert_not_called();self.assertTrue(backend.ready())

    def test_an_optional_file_not_read_is_not_checked(self):
        self.with_ttt_disc(exists=False)         # moved, its music and laser already current beside the game
        self.ps2_music(self.paths['TTT_PS2_MUSIC_INSTALLED'],self.M.PS2_VERSION)
        self.laser(self.paths['TTT_PS2_LASER_INSTALLED'],self.L.LASER_VERSION)
        self.assertEqual(backend.optional_problems(True,None,self.ttt_disc),[])
        # TTT Cinematics read it at every setup: then asked for.
        self.assertIn('no longer there',backend.optional_problems(True,None,self.ttt_disc,cinematics=True)[0]['reason'])
        self.assertEqual(backend.optional_problems(False,None,self.ttt_disc,cinematics=True),[])   # without the TTT content

    def test_ttt_stages_and_music_version_stamps(self):
        folder=self.root/'ttt'
        self.assertFalse(self.A.ttt_current(folder))
        self.ttt_packs(folder,self.A.TTT_STAGES_VERSION);self.assertTrue(self.A.ttt_current(folder))
        (folder/'stage14.ast').unlink();self.assertFalse(self.A.ttt_current(folder))
        self.assertFalse(self.M.current(folder))
        self.ttt_music(folder,self.M.MUSIC_VERSION);self.assertTrue(self.M.current(folder))
        self.assertFalse(self.M.ps2_current(folder))
        self.ps2_music(folder,self.M.PS2_VERSION);self.assertTrue(self.M.ps2_current(folder))

    def test_update_steps_chain_versions(self):
        steps=self.V.update_steps
        self.assertEqual(steps(2,current=2,updates={}),[])
        self.assertEqual(steps(0,current=3,updates={1:('hands',),2:('panda-tiger','hands'),3:()}),['hands','panda-tiger'])
        self.assertIsNone(steps(0,current=2,updates={1:('hands',),2:None}))
        self.assertTrue(all(s in self.V.STEPS for v in self.V.UPDATES.values() if v for s in v))

def shutil_usage(free):
    import collections
    return collections.namedtuple('usage','total used free')(free,0,free)

if __name__=='__main__':unittest.main()
