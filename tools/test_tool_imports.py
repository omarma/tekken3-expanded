#!/usr/bin/env python3
"""Every import of the setup's tools resolves (B95).

    python3 tools/test_tool_imports.py [--all] [-v]

A tool's import of a module of this repository works only from the folders
on its sys.path: its own (when run as a script) and the ones it inserts. An
import inside a function only fails when that function runs (B95:
tools/ttt_cinematics.py's t3_music, `from glyphs import data_track`, called
only without a TTT PS2 disc, after 18cbe315 had removed tools/ttt1 from its
path). This reads each tool, statically: the folders it puts on sys.path
(sys.path.insert / append / [:0] = [...], with ROOT, HERE... as the tool
computes them from __file__) and every import statement, at any depth; a
module found neither in those folders nor in the interpreter (stdlib, the
setup's venv) is reported, with its line. Run it with the setup's Python
(.setup/venv) so that numpy, PIL... count as installed.

Checked: the tools the setup runs (launcher/setup_backend.py, ttt1_setup.py)
and everything they import from the repository, transitively, each module
with the sys.path of the script that loads it. --all: every .py under tools/
and launcher/, each as its own script (more noise: bench tools may need
folders outside the repository). Exit status 1 on any unresolved import.
"""
import argparse, ast, importlib.util, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# The setup's entry points: the backend runs these with sys.executable.
ENTRIES = ['launcher/setup_backend.py', 'launcher/easy_launcher.py', 'tools/ttt1_setup.py', 'tools/ttt1_import.py',
           'tools/ttt_cinematics.py', 'tools/ttt1_devil_jin.py', 'tools/ttt1_hitspark.py',
           'tools/arcade_stages/install.py', 'tools/ttt_stages/music_install.py',
           'tools/ttt_stages/ps2_music_install.py', 'tools/ps2/ttt_laser_install.py', 'tools/android/make_apk.py']
# Imports guarded by try/except ImportError are optional by design.
OPTIONAL = (ImportError, ModuleNotFoundError)


def evaluate(node, env, path):
    """A path expression of the forms the tools use, or None."""
    E = lambda n: evaluate(n, env, path)
    if isinstance(node, ast.Constant) and isinstance(node.value, str): return node.value
    if isinstance(node, ast.Name):
        if node.id == '__file__': return path
        return env.get(node.id)
    if isinstance(node, ast.Call):
        f = node.func
        if isinstance(f, ast.Name) and f.id in ('str', 'Path') and len(node.args) == 1: return E(node.args[0])
        if isinstance(f, ast.Attribute):
            if f.attr in ('resolve', 'absolute') and not node.args: return E(f.value)
            if f.attr in ('dirname', 'abspath', 'realpath', 'join') and isinstance(f.value, ast.Attribute) \
                    and f.value.attr == 'path':
                args = [E(a) for a in node.args]
                if None in args: return None
                if f.attr == 'dirname': return Path(args[0]).parent
                if f.attr == 'join': return Path(*args)
                return Path(args[0])
        return None
    if isinstance(node, ast.Attribute) and node.attr == 'parent':
        v = E(node.value); return Path(v).parent if v is not None else None
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) and node.value.attr == 'parents':
        v, i = E(node.value.value), node.slice
        if v is not None and isinstance(i, ast.Constant): return Path(v).parents[i.value]
        return None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        a, b = E(node.left), E(node.right)
        return Path(a) / b if a is not None and b is not None else None
    return None


def path_targets(node):
    """The expressions a statement puts on sys.path."""
    is_path = lambda n: isinstance(n, ast.Attribute) and n.attr == 'path' and isinstance(n.value, ast.Name) \
        and n.value.id == 'sys'
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and is_path(node.func.value):
        if node.func.attr == 'insert' and len(node.args) == 2: return [node.args[1]]
        if node.func.attr == 'append' and len(node.args) == 1: return [node.args[0]]
        if node.func.attr == 'extend' and node.args and isinstance(node.args[0], (ast.List, ast.Tuple)):
            return node.args[0].elts
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        t = node.targets[0]
        if isinstance(t, ast.Subscript) and is_path(t.value) and isinstance(node.value, (ast.List, ast.Tuple)):
            return node.value.elts
        if is_path(t) and isinstance(node.value, ast.BinOp):
            side = node.value.left if isinstance(node.value.left, (ast.List, ast.Tuple)) else node.value.right
            if isinstance(side, (ast.List, ast.Tuple)): return side.elts
    return []


class Module:
    def __init__(self, path):
        self.path = path
        self.tree = ast.parse(path.read_text(encoding='utf-8-sig'), str(path))
        # Module-level names first (ROOT, HERE, TOOLS...), in order.
        env = {}
        for st in self.tree.body:
            if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name):
                v = evaluate(st.value, env, path)
                if v is not None: env[st.targets[0].id] = v
        self.env = env
        # Folders it adds, anywhere in the file (an insert in a function
        # counts for the whole file: lenient, B95's kind is no insert at all).
        self.adds = []
        for n in ast.walk(self.tree):
            for e in path_targets(n.value if isinstance(n, ast.Expr) else n):
                v = evaluate(e, env, path)
                if v is not None: self.adds.append(Path(v).resolve())

    def imports(self):
        """(line, module name, optional) of every import, at any depth."""
        guarded = set()
        for n in ast.walk(self.tree):
            if isinstance(n, ast.Try):
                names = set()
                for h in n.handlers:
                    t = h.type
                    for x in (t.elts if isinstance(t, ast.Tuple) else [t] if t else []):
                        if isinstance(x, ast.Name): names.add(x.id)
                    if t is None or names & {'ImportError', 'ModuleNotFoundError', 'Exception'}:
                        for b in n.body:
                            for m in ast.walk(b): guarded.add(id(m))
        for n in ast.walk(self.tree):
            if isinstance(n, ast.Import):
                for a in n.names: yield n.lineno, a.name, id(n) in guarded
            elif isinstance(n, ast.ImportFrom) and not n.level and n.module:
                yield n.lineno, n.module, id(n) in guarded


def find(name, folders):
    """The file of module `name` (dotted) in `folders`, 'installed', or None."""
    top = name.split('.')[0]
    for d in folders:
        for c in (d / f'{top}.py', d / top / '__init__.py', d / top):
            if c.exists():
                return c if c.suffix == '.py' else (c / '__init__.py' if (c / '__init__.py').is_file() else c)
    if top in sys.stdlib_module_names or top in sys.builtin_module_names: return 'installed'
    try:
        if importlib.util.find_spec(top) is not None: return 'installed'
    except (ImportError, ValueError):
        pass
    return None


def check(entries, verbose):
    """[(file, line, module, script)] unresolved, following the repository's modules."""
    bad, cache = {}, {}
    def module(p):
        if p not in cache: cache[p] = Module(p)
        return cache[p]
    for entry in entries:
        script = (ROOT / entry).resolve()
        if not script.is_file(): continue
        # The script's sys.path: its folder and the inserts of every module
        # it loads (their module level has run by the time a function
        # imports), grown until no new module is reached.
        folders, reached = [script.parent], None
        while True:
            seen, todo = [], [script]
            while todo:
                p = todo.pop(0)
                if p in seen: continue
                seen.append(p)
                for line, name, optional in module(p).imports():
                    found = find(name, folders)
                    if isinstance(found, Path) and found.suffix == '.py' and ROOT in found.resolve().parents:
                        todo.append(found.resolve())
            grown = folders + [f for p in seen for f in module(p).adds]
            grown = list(dict.fromkeys(grown))
            if grown == folders and seen == reached: break
            folders, reached = grown, seen
        for p in seen:
            for line, name, optional in module(p).imports():
                if find(name, folders) is not None: continue
                if not optional:
                    if p == script or (p, line, name) not in bad: bad[(p, line, name)] = script
                elif verbose: print(f'  optional: {p.relative_to(ROOT)}:{line} {name}')
        if verbose: print(f'{entry}: {len(folders)} folders, {len(seen)} modules')
    return [(p, line, name, script) for (p, line, name), script in bad.items()]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--all', action='store_true', help='every .py under tools/ and launcher/, each as a script')
    ap.add_argument('-v', '--verbose', action='store_true')
    a = ap.parse_args()
    entries = ENTRIES
    if a.all:
        entries = sorted(str(p.relative_to(ROOT)) for d in ('tools', 'launcher') for p in (ROOT / d).rglob('*.py'))
    bad = check(entries, a.verbose)
    for p, line, name, script in bad:
        via = '' if p == script else f' (loaded by {script.relative_to(ROOT)})'
        print(f'FAIL {p.relative_to(ROOT)}:{line}: no module {name!r}{via}')
    print(f"{'FAIL' if bad else 'OK'}: {len(entries)} tools checked, {len(bad)} unresolved imports")
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
