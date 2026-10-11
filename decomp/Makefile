TOOLS     := ../tools
PYTHON    := ../.venv/bin/python
CROSS     := mips64-linux-gnu-
AS        := $(CROSS)as
LD        := $(CROSS)ld
OBJCOPY   := $(CROSS)objcopy
CPP       := cpp
GCC_VER   ?= 2.7.2-psx
ASPSX_VER ?= 2.34
CC1       := $(TOOLS)/gcc/$(GCC_VER)/cc1
MASPSX    := $(PYTHON) $(TOOLS)/maspsx/maspsx.py

BUILD     := build
TARGET    := sces_008.93
CONFIG    := $(TARGET).yaml
LD_SCRIPT := $(BUILD)/$(TARGET).ld
ELF       := $(BUILD)/$(TARGET).elf
EXE       := $(BUILD)/SCES_008.93
ORIGINAL  := files/SCES_008.93

AS_FLAGS  := -EL -march=r3000 -mtune=r3000 -mabi=32 -G0 -no-pad-sections -Iinclude
CPP_FLAGS := -undef -Wall -fno-builtin -Iinclude -Iinclude/psyq \
             -D__GNUC__=2 -D__OPTIMIZE__ -DMIPSEL -D_LANGUAGE_C -DLANGUAGE_C -DNON_MATCHING=0
CC1_FLAGS := -G0 -O2 -funsigned-char -w -fpeephole -ffunction-cse -fpcc-struct-return \
             -fcommon -fverbose-asm -msoft-float -mgas -fgnu-linker -quiet
LD_FLAGS  := -EL -m elf32ltsmip --no-check-sections -nostdlib \
             -T config/undefined_syms_auto.main.txt -T config/undefined_funcs_auto.main.txt \
             -T config/undefined_syms.main.txt

# Objects are listed by the splat-generated linker script.
O_FILES = $(shell grep -o 'build/[^ ()]*\.o' $(LD_SCRIPT) 2>/dev/null | sort -u)

.PHONY: all split check clean

all: check

split:
	rm -rf asm/main $(LD_SCRIPT)
	$(PYTHON) -m splat split $(CONFIG)

$(LD_SCRIPT): $(CONFIG)
	$(PYTHON) -m splat split $(CONFIG)

$(BUILD)/asm/%.o: asm/%.s
	@mkdir -p $(dir $@)
	$(AS) $(AS_FLAGS) -o $@ $<

# C: cpp -> PsyQ cc1 -> maspsx -> gas
$(BUILD)/src/%.o: src/%.c $(wildcard include/*.h) $(shell find asm -path "*nonmatchings*" -name "*.s" 2>/dev/null)
	@mkdir -p $(dir $@)
	$(CPP) $(CPP_FLAGS) $< | $(CC1) $(CC1_FLAGS) | $(MASPSX) --aspsx-version=$(ASPSX_VER) | $(AS) $(AS_FLAGS) -o $@

$(ELF): $(LD_SCRIPT) $(O_FILES) config/undefined_syms.main.txt
	$(LD) $(LD_FLAGS) -T $(LD_SCRIPT) -Map $(BUILD)/$(TARGET).map -o $@

$(EXE): $(ELF)
	$(OBJCOPY) -O binary $< $@

check: $(EXE)
	@if cmp -s $(EXE) $(ORIGINAL); then echo "OK: $(EXE) matches the original"; \
	else echo "MISMATCH: $(EXE) differs from the original"; cmp $(EXE) $(ORIGINAL) | head -5; exit 1; fi

clean:
	rm -rf $(BUILD)/asm $(BUILD)/src $(ELF) $(EXE) $(BUILD)/$(TARGET).map
