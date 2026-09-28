"""Rewrite stale absolute paths inside duckstation's prebuilt deps.

The windows-x64 prebuilt archive ships with CMake-generated Targets files that
have `_IMPORT_PREFIX` baked in as an absolute path from wherever the archive
was originally extracted. When the project root moves (e.g. psxrecomp-projects
-> psxrecomp), CMake can't find the referenced .lib/.dll files even though
they're there.

This script rewrites `OLD_PREFIX` -> `NEW_PREFIX` in every file under
`duckstation/dep/prebuilt/`. Safe to run repeatedly (no-op after first run).
"""
import os, sys

OLD = b"psxrecomp-projects"
NEW = b"psxrecomp"
ROOT = sys.argv[1] if len(sys.argv) > 1 else "duckstation/dep/prebuilt"

n_files = 0
n_rewrites = 0
for base, dirs, files in os.walk(ROOT):
    for name in files:
        p = os.path.join(base, name)
        try:
            with open(p, "rb") as f:
                data = f.read()
        except (OSError, IOError):
            continue
        if OLD not in data:
            continue
        count = data.count(OLD)
        new_data = data.replace(OLD, NEW)
        with open(p, "wb") as f:
            f.write(new_data)
        n_files += 1
        n_rewrites += count
        print(f"  {p}: {count} replacement(s)")

print(f"total: {n_files} files, {n_rewrites} replacements")
