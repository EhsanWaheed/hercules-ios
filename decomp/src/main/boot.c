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

/* --- declarations (auto_m2c appends here) --- */
void SsSeqReplay(s16 access_num);
extern s16 D_8002AEE2;
extern s8 D_80035048;
s32 GetSp(void);
void SetSp(s32 sp);
void func_80012494(s32 arg0, s32 arg1);
M2C_UNK CdRead(s32, s32, M2C_UNK);                  /* extern */
M2C_UNK CdReadSync(M2C_UNK, M2C_UNK);               /* extern */
extern u8 D_80035108;
extern s32 D_80027B6C;
extern SoundState D_80035F48;
extern s32 D_80035F58;
extern s32 D_80035F5C;
void SsSeqPause(s16 access_num);
int CdControl(u8 com, u8* param, u8* result);
void func_80011888(void);
M2C_UNK func_80010000();                            /* extern */
extern s32 D_80035F50;
extern s32 D_80035F54;
M2C_UNK SsSetMVol(M2C_UNK, M2C_UNK);                /* extern */
extern s32 D_80035F74;
extern s32 D_80035F78;
extern s32 D_80035F7C;
M2C_UNK DrawSync(M2C_UNK);                          /* extern */
M2C_UNK VSyncCallback(M2C_UNK);                     /* extern */
extern s8 D_80035175;
M2C_UNK CdControlF(s32, M2C_UNK *);                 /* extern */
M2C_UNK CdIntToPos(s32, M2C_UNK *);                 /* extern */
extern s32 D_80034F7C;
extern s32 D_80035FE4;
extern s32 D_80035F4C;
extern s32 D_80027B64;
extern s32 D_80035FB8;
extern s32 D_80035FBC;
extern s16 D_800350E4;
extern s32 D_800350F4;
M2C_UNK func_80012180(s32);                         /* extern */
M2C_UNK func_80012B08();                            /* extern */
extern s32 D_800350F8;
extern s32 D_800350FC;
extern s16 D_80035124;
extern s8 D_80035128;
extern s32 D_80035130;
M2C_UNK InitPAD(M2C_UNK *, M2C_UNK, M2C_UNK *, M2C_UNK); /* extern */
extern M2C_UNK D_800382C0;
extern M2C_UNK D_800382E4;
M2C_UNK PutDispEnv(s32);                            /* extern */
M2C_UNK PutDrawEnv();                               /* extern */
M2C_UNK SetDispMask(s32);                           /* extern */
M2C_UNK VSync(M2C_UNK);                             /* extern */

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80010000);

/* The do/while (0) is what puts the load ahead of the stack adjust; the
 * original was most likely written with a statement macro here. */
void func_800100C0(void) {
    s16 seq = D_80035F48.seqAccess;

    do {
        if (D_80035F48.seqAccess != -1) {
            SsSeqPause(seq);
        }
    } while (0);
}

/* The do/while (0) is what puts the load ahead of the stack adjust; the
 * original was most likely written with a statement macro here. */
void func_800100F4(void) {
    s16 seq = D_80035F48.seqAccess;

    do {
        if (D_80035F48.seqAccess != -1) {
            SsSeqReplay(seq);
        }
    } while (0);
}

void StSetRing(s32 arg0, s32 arg1) {
    D_80035F50 = arg0;
    D_80035F54 = arg1;
    func_80010000();
}

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

void func_80010B8C(void) {
    D_80035F78 = 0x69;
    D_80035F74 = 0x69;
    D_80035F7C = 1;
    SsSetMVol(0x69, 0x69);
}

void func_80010BD0(s32 arg0) {
    s32 seq = D_80035F48.seqAccess;
    /* do/while (0): the original likely used a statement macro here */
    do {
        D_80035F7C = 1;
    } while (0);
    if (seq != -1) {
        if (arg0 == 0) {
            D_80035F78 = 0x69;
        } else {
            D_80035F78 = 0;
        }
    }
}

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80010C18);

void func_80010D54(void) {
    VSyncCallback(0);
    DrawSync(0);
    VSync(0);
    D_80035175 = 0;
}

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80010D8C);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_800110D0);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80011528);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_800115F8);

void func_80011880(void) {
}

void func_80011888(void) {
}

void func_80011890(void) {
    func_80011888();
    D_80035F4C = 0;
    D_80027B6C = 0;
}

INCLUDE_ASM("asm/main/nonmatchings/boot", func_800118C0);

void func_80011928(s32 arg0) {
    M2C_UNK sp10;

    CdIntToPos(D_80035FE4, &sp10);
    CdControlF(arg0 & 0xFF, &sp10);
    D_80034F7C = D_80035FE4;
}

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80011978);

void func_80011A80(s32 arg0) {
    if (arg0 == 1) {
        D_80035F4C = 2;
    }
}

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

void func_80011CE0(void) {
    D_80027B64 = 0x100;
}

void func_80011CF4(void) {
    D_80027B64 = 0;
}

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80011D04);

void func_80011DF0(void) {
}

void func_80011DF8(void)
{
  s16 *new_var2;
  s32 new_var;
  new_var2 = &D_8002AEE2;
  new_var = GetSp();
  SetSp(new_var);
  D_80035048 = (s8) (new_var = *new_var2);
}

void func_80011E30(s32 arg0, s32 arg1) {
    D_80035FB8 = arg0;
    D_80035FBC = arg1;
}

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80011E48);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80011F0C);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80011F70);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80012080);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80012180);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80012224);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80012390);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80012424);

void func_80012474(s32 arg0) {
    func_80012494(arg0, 0);
}

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80012494);

void func_800126A0(void **arg0, void **arg1) {
    M2C_FIELD(*arg1, void ***, -4) = arg0;
    *arg0 = *arg1;
    *arg1 = NULL;
}

INCLUDE_ASM("asm/main/nonmatchings/boot", func_800126C0);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80012734);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80012828);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80012900);

void func_80012990(s32 arg0, s32 arg1) {
    s32 temp_a0;

    CdControl(2U, &D_80035108, NULL);
    CdReadSync(0, 0);
    CdRead(arg1, arg0, 0x80);
    temp_a0 = D_800350F4 + arg1;
    D_800350F4 = temp_a0;
    CdIntToPos(temp_a0, (s32 *) &D_80035108);
}

s32 func_80012A1C(void) {
    D_800350E4 = 0;
    D_800350F4 = 0;
    return 1;
}

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80012A34);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80012B08);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80012B64);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80012CC4);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80012E04);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80012EFC);

void func_80012FAC(void) {
    func_80012B08();
    if (D_80035130 != 0) {
        func_80012180(D_80035130);
    }
    D_80035128 = 0;
    D_80035124 = 0;
    D_800350F8 = 0;
    D_800350FC = 0;
}

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80013008);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_800130CC);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80013284);

void func_80013348(void) {
    InitPAD(&D_800382C0, 0x22, &D_800382E4, 0x22);
}

INCLUDE_ASM("asm/main/nonmatchings/boot", func_8001337C);

void func_80013490(s32 arg0) {
    PutDrawEnv();
    PutDispEnv(arg0 + 0x5C);
}

INCLUDE_ASM("asm/main/nonmatchings/boot", func_800134C0);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_80013510);

void func_80013568(s32 arg0) {
    VSync(0);
    SetDispMask(arg0);
}

INCLUDE_ASM("asm/main/nonmatchings/boot", func_8001359C);

INCLUDE_ASM("asm/main/nonmatchings/boot", func_8001365C);
