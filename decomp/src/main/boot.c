#include "common.h"

/* Sound/CD state block at 0x80035F48; fields named by observed use. */
typedef struct {
    /* 0x00 */ s32 seqAccess; /* -1 when no sequence is open */
    /* 0x04 */ s32 cdActive;
    /* 0x08 */ s32 unk8;
    /* 0x0C */ s32 unkC;
    /* 0x10 */ s32 unk10;
    /* 0x14 */ s32 unk14;
} SoundState;

extern s32 D_80027B6C;
extern SoundState D_80035F48;
extern s32 D_80035F58;
extern s32 D_80035F5C;

void SsSeqPause(s16 access_num);
int CdControl(u8 com, u8* param, u8* result);
void func_80011888(void);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80010000);

/* Logic is equivalent, but the original has the load scheduled before the
 * stack adjust, which our cc1 + maspsx pipeline does not reproduce yet.
 *
 * void func_800100C0(void) {
 *     if (D_80035F48.seqAccess != -1) {
 *         SsSeqPause(D_80035F48.seqAccess);
 *     }
 * }
 */
INCLUDE_ASM("asm/main/nonmatchings/boot", func_800100C0);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_800100F4);

INCLUDE_ASM("asm/main/nonmatchings/boot", StSetRing);

void func_80010158(void) {
    D_80035F58 = 0x100;
    D_80035F5C = 0x100;
}

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80010174);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80010380);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_800105B8);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80010614);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_800106F4);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80010844);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80010940);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80010A38);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80010B8C);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80010BD0);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80010C18);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80010D54);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80010D8C);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_800110D0);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80011528);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_800115F8);

void func_80011880(void) {
}

void func_80011888(void) {
}

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80011890);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_800118C0);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80011928);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80011978);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80011A80);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80011A9C);

void func_80011C0C(void) {
    if (D_80035F48.cdActive != 0) {
        CdControl(9, NULL, NULL);
        D_80035F48.cdActive = 0;
        D_80027B6C = 0;
        func_80011888();
    }
}

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80011C64);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80011CE0);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80011CF4);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80011D04);

void func_80011DF0(void) {
}

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80011DF8);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80011E30);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80011E48);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80011F0C);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80011F70);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80012080);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80012180);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80012224);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80012390);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80012424);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80012474);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80012494);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_800126A0);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_800126C0);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80012734);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80012828);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80012900);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80012990);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80012A1C);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80012A34);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80012B08);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80012B64);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80012CC4);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80012E04);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80012EFC);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80012FAC);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80013008);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_800130CC);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80013284);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80013348);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_8001337C);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80013490);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_800134C0);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80013510);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80013568);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_8001359C);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_8001365C);
