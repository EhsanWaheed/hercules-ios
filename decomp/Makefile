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

# Raw byte blobs (splat `bin` subsegments)
$(BUILD)/assets/%.o: assets/%.bin
	@mkdir -p $(dir $@)
	$(LD) -EL -m elf32ltsmip -r -b binary -o $@ $<
	$(OBJCOPY) --rename-section .data=.data,alloc,load,data,contents $@

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

# --- Other executables and level overlays (assembly only for now) ---------
# make check-engine1, check-ov3, ... or check-all. Each has <name>.yaml.
SUBTARGETS := engine1 engine3 title ov0 ov1 ov2 ov3 ov4 ov5 ov6 ov7 ov8 ov9 ov10 ov11
target_of   = $(shell sed -n 's/^  target_path: //p' $(1).yaml)
sub_objs    = $(shell grep -o 'build/[^ ()]*\.o' $(BUILD)/$(1).ld 2>/dev/null | sort -u)

.PHONY: check-all $(addprefix check-,$(SUBTARGETS)) $(addprefix split-,$(SUBTARGETS))

check-all: check $(addprefix check-,$(SUBTARGETS))

$(addprefix split-,$(SUBTARGETS)): split-%:
	rm -rf asm/$* $(BUILD)/$*.ld
	$(PYTHON) -m splat split $*.yaml

$(BUILD)/%.ld: %.yaml
	$(PYTHON) -m splat split $<

.SECONDEXPANSION:
$(BUILD)/%.bin: $(BUILD)/%.ld $$(call sub_objs,$$*)
	$(LD) -EL -m elf32ltsmip --no-check-sections -nostdlib \
	  -T config/undefined_syms_auto.$*.txt -T config/undefined_funcs_auto.$*.txt \
	  -T $< -Map $(BUILD)/$*.map -o $(BUILD)/$*.elf
	$(OBJCOPY) -O binary $(BUILD)/$*.elf $@

$(addprefix check-,$(SUBTARGETS)): check-%: $(BUILD)/%.bin
	@if cmp -s $< $(call target_of,$*); then echo "OK: $* matches $(call target_of,$*)"; \
	else echo "MISMATCH: $* differs from $(call target_of,$*)"; cmp $< $(call target_of,$*) | head -3; exit 1; fi

clean:
	rm -rf $(BUILD)/asm $(BUILD)/src $(ELF) $(EXE) $(BUILD)/$(TARGET).map \
	  $(foreach t,$(SUBTARGETS),$(BUILD)/$(t).elf $(BUILD)/$(t).bin $(BUILD)/$(t).map)

# XXH3 for tools/sprite_texpack.py (header vendored by PSXRecomp).
# psxrecomp's vendored xxhash.h: the combined repo (../port) or the local layout
XXHASH_DIR ?= $(firstword $(wildcard ../port/psxrecomp/runtime/third_party) \
                          $(HOME)/psx-decomp/HerculesRecomp/psxrecomp/runtime/third_party)
tools/native/libxxh3.so: tools/native/xxh3.c
	gcc -O2 -shared -fPIC -I$(XXHASH_DIR) -o $@ $<
