#ifndef TEKKEN3_JUN_BASIS_H
#define TEKKEN3_JUN_BASIS_H
#include <stdint.h>

/* B maps a native joint's local axes into the arcade model's axes.
 * Shared locomotion poses establish different bases at the root/shoulders,
 * wrists and ankles. In particular, the head and limb hinges share their
 * axes; conjugating every joint by the root's half-turn reverses them.
 *
 * Arcade -> native: inverse(B_parent) M B_joint.
 * Native -> arcade: B_parent M inverse(B_joint).
 * Translations remain the receiving model's bone lengths. */
static inline void tekken3_ttt1_change_basis(int32_t m[9], unsigned bone,
                                           int to_arcade)
{
    static const unsigned char parent[18]={18,0,1,1,3,4,5,1,7,8,9,0,11,12,13,11,15,16};
    static const unsigned char basis[19]={1,0,0,1,0,0,2,1,0,0,2,0,0,0,3,0,0,3,0};
    static const int8_t b[4][9]={
        {1,0,0,0,1,0,0,0,1},
        {1,0,0,0,-1,0,0,0,-1},
        {1,0,0,0,0,1,0,-1,0},
        {-1,0,0,0,-1,0,0,0,1}
    };
    int32_t result[9]={0};
    const int8_t *p=b[basis[parent[bone]]],*j=b[basis[bone]];
    for(unsigned row=0;row<3;row++)for(unsigned col=0;col<3;col++)
        for(unsigned a=0;a<3;a++)for(unsigned c=0;c<3;c++)
            result[row*3+col]+=(to_arcade?p[row*3+a]:p[a*3+row])*
                m[a*3+c]*(to_arcade?j[col*3+c]:j[c*3+col]);
    for(unsigned n=0;n<9;n++)m[n]=result[n];
}
#endif
