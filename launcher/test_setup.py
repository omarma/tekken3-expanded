"""ROM-free checks for setup integrity, archive boundaries and cancellation."""
from pathlib import Path
import contextlib,hashlib,io,json,os,re,subprocess,sys,tempfile,time,unittest,zipfile
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import setup_backend as backend
from easy_launcher import ProcessJob

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
             patch.object(backend,'tools',return_value=None),patch.object(backend,'android_apk') as android:
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
        self.paths=dict(ROOT=root,STATE=state,BUILD=build,EXE=build/'game',WORK=work,ROSTER=work/'roster',INSTALLED=build/'mods/ttt1')
        self.commands=[]
        for name,value in self.paths.items():
            patcher=patch.object(backend,name,value);patcher.start();self.addCleanup(patcher.stop)
        for name,value in dict(emit=None,complete=None,tools=None,prepare_textures=None,
                               validate_disc=None,run=self.fake_run,build_game=self.fake_build).items():
            patcher=patch.object(backend,name,side_effect=value) if callable(value) else patch.object(backend,name,return_value=value)
            patcher.start();self.addCleanup(patcher.stop)
        patcher=patch.object(backend.shutil,'disk_usage',return_value=shutil_usage(free=100*1024**3))
        patcher.start();self.addCleanup(patcher.stop)

    def catalogue(self,folder,stamp):
        folder.mkdir(parents=True,exist_ok=True)
        (folder/'guests.txt').write_text('jun 1 - --\n');(folder/'Jun-TTT1-combat.jmv').write_bytes(b'moves')
        if stamp:self.V.write_stamp(folder,stamp)

    def install(self,stamp,workspace=True,work_files=False,release=backend.RELEASE):
        """A finished setup whose TTT1 import has version `stamp`."""
        p=self.paths
        self.catalogue(p['INSTALLED'],stamp)
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

    def fake_build(self,toolchain,env,include_ttt1):
        self.commands.append(['build']);self.paths['EXE'].write_bytes(b'rebuilt game')

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
