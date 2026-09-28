/* Private fixture: decoded arcade shared poses paired with unblended native
 * locomotion matrices (head tracking disabled for capture). No ROM data is
 * embedded here. Differences from native IK/compression are below 1536/4096;
 * the erroneous whole-skeleton conversion produces half-turns near 8192. */
#include "../../src/tekken3_ttt1_basis.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(int argc,char **argv) {
    assert(argc==2);
    FILE *f=fopen(argv[1],"rb");assert(f);
    int32_t source[18][9],native[18][9],m[9];unsigned frames=0;
    while(fread(source,1,sizeof source,f)==sizeof source) {
        assert(fread(native,1,sizeof native,f)==sizeof native);
        for(unsigned bone=0;bone<18;bone++) {
            memcpy(m,source[bone],sizeof m);
            tekken3_ttt1_change_basis(m,bone,0);
            for(unsigned n=0;n<9;n++)assert(abs(m[n]-native[bone][n])<1536);
            tekken3_ttt1_change_basis(m,bone,1);
            assert(!memcmp(m,source[bone],sizeof m));
            memcpy(m,native[bone],sizeof m);
            tekken3_ttt1_change_basis(m,bone,1);
            for(unsigned n=0;n<9;n++)assert(abs(m[n]-source[bone][n])<1536);
            tekken3_ttt1_change_basis(m,bone,0);
            assert(!memcmp(m,native[bone],sizeof m));
        }
        frames++;
    }
    assert(feof(f) && frames>=8);fclose(f);
    printf("Jun joint bases: %u shared poses, all 18 joints in both directions, exact round trips\n",frames);
    return 0;
}
