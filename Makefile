PKG_CONFIG ?= pkg-config
RUN        ?= uv run
TMP        ?= /tmp
CC         ?= cc
CFLAGS     ?= -O2 -Wall
BIN         = bin/assprobe
SRC         = native/assprobe.c

ASS_CFLAGS := $(shell $(PKG_CONFIG) --cflags libass 2>/dev/null)
ASS_LIBS   := $(shell $(PKG_CONFIG) --libs libass 2>/dev/null)
ifeq ($(strip $(ASS_LIBS)),)
ASS_LIBS := -lass
endif

ifeq ($(OS),Windows_NT)
BIN = bin/assprobe.exe
endif

all: $(BIN)

$(BIN): $(SRC)
	@mkdir -p bin
	$(CC) $(CFLAGS) $(ASS_CFLAGS) -o $@ $< $(ASS_LIBS)

check: $(BIN)
	@for f in examples/*.ass; do \
		echo "== $$f"; \
		$(RUN) karaoke-ass apply "$$f" "$(TMP)/kara-check.ass" || exit 1; \
		$(RUN) karaoke-ass check "$$f" "$(TMP)/kara-check.ass" || exit 1; \
	done

# Release packaging. Depends on check, so an unverified template cannot ship.
VERSION := $(shell sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)
PACK     = karaoke-ass-template-v$(VERSION)

# The template carries its own version string for when the file is copied out
# of the repository, so it must not drift from pyproject.toml.
version-check:
	@grep -q "TWO-ROW KARAOKE TEMPLATE  v$(VERSION)$$" template/two-row-karaoke.ass \
		|| { echo "template/two-row-karaoke.ass version does not match pyproject.toml ($(VERSION))"; exit 1; }
	@for f in examples/*.ass; do \
		grep -q "TWO-ROW KARAOKE TEMPLATE  v$(VERSION)$$" "$$f" \
			|| { echo "$$f version does not match pyproject.toml ($(VERSION))"; exit 1; }; \
	done

dist: version-check check
	rm -rf dist build/$(PACK)
	uv build --wheel
	mkdir -p build/$(PACK)/karaoke-ass-template
	cp -R template examples LICENSE README.md build/$(PACK)/karaoke-ass-template/
	cd build/$(PACK) && zip -qr ../../dist/$(PACK).zip karaoke-ass-template
	@echo
	@ls -l dist

clean:
	rm -f bin/assprobe bin/assprobe.exe bin/.extents-cache-*.tsv
	rm -rf src/karaoke_ass/__pycache__ build dist

.PHONY: all check clean dist version-check
