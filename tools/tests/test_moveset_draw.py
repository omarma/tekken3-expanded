#!/usr/bin/env python3
"""The CPU's draw gives each choice the same chance (src/tekken3_moveset_draw.h).

    python3 tools/tests/test_moveset_draw.py

Compiles the header into a small program, draws 100000 times for 2, 3, 4 and 5
choices and checks each count against the chi-square limit (p = 0.001), then
checks that a seed gives the same sequence twice.
"""
import subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = r'''
#include <stdio.h>
#include <stdlib.h>
#include "tekken3_moveset_draw.h"
int main(int argc,char **argv){
    unsigned n=(unsigned)atoi(argv[1]),draws=(unsigned)atoi(argv[2]);
    uint64_t state;tekken3_moveset_seed(&state,strtoull(argv[3],NULL,0));
    unsigned count[16]={0};
    for(unsigned i=0;i<draws;i++)count[tekken3_moveset_draw(n,&state)]++;
    for(unsigned i=0;i<n;i++)printf("%u ",count[i]);
    printf("\n");
}
'''
# Chi-square critical values, p = 0.001, for 1..4 degrees of freedom.
LIMIT = {2: 10.83, 3: 13.82, 4: 16.27, 5: 18.47}

def run_first(exe, seed):
    out = subprocess.run([str(exe), '2', '1', str(seed)], check=True, capture_output=True, text=True).stdout.split()
    return int(out[1])

def main():
    with tempfile.TemporaryDirectory() as tmp:
        c, exe = Path(tmp) / 'draw.c', Path(tmp) / 'draw'
        c.write_text(SOURCE)
        subprocess.run(['cc', '-O2', '-I', str(ROOT / 'src'), str(c), '-o', str(exe)], check=True)
        run = lambda n, seed: list(map(int, subprocess.run([str(exe), str(n), '100000', str(seed)], check=True,
                                                          capture_output=True, text=True).stdout.split()))
        for n, limit in LIMIT.items():
            counts = run(n, 12345)
            expected = sum(counts) / n
            chi = sum((x - expected) ** 2 / expected for x in counts)
            print(f'{n} choices: {counts} chi-square {chi:.2f} (limit {limit})')
            assert chi < limit, f'{n} choices are not even'
        # The first draw of two choices over 2000 clock-like seeds (one per game).
        first = sum(run_first(exe, 1700000000 + i) for i in range(2000))
        print(f'first draw of 2000 close seeds: {first} ones (expect 1000 +- 45)')
        assert abs(first - 1000) < 4 * 22.4 * 1.0, 'close seeds give a biased first draw'
        assert run(3, 7) == run(3, 7), 'a seed does not repeat'
        assert run(3, 0) == run(3, 0), 'seed 0 does not repeat'
    print('OK')

if __name__ == '__main__': main()
