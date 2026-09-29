"""ROM-free checks for setup integrity, archive boundaries and cancellation."""
from pathlib import Path
import hashlib,json,os,subprocess,sys,tempfile,time,unittest,zipfile
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import setup_backend as backend
from easy_launcher import ProcessJob

class SetupTests(unittest.TestCase):
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
            kept=[build/'Tekken_3_Recompiled.exe',build/'mods/ttt1/guests.txt',root/'generated/SLUS_004.02_dispatch.c',
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

if __name__=='__main__':unittest.main()
