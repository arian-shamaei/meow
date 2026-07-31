# silly-catui - build and install
#
#   make            build ./meow for this platform
#   make install    install to the best writable prefix
#   make run        build and run
#   make clean      remove build output
#
# Platform is detected, not configured. The two cases that actually differ:
#   Darwin  - cc is clang; the shipped binary is arm64 Mach-O
#   Linux   - cc is gcc; needs _DEFAULT_SOURCE for the ioctl/termios path
# Anything else falls through to a portable build and says so.

UNAME_S := $(shell uname -s)
UNAME_M := $(shell uname -m)

BIN     := meow
SRC     := c/meow.c
HDR     := c/meow_frames.h

BASE_CFLAGS := -O2 -std=c11 -Wall -Wextra

# `CC ?=` cannot work here: make pre-defines CC=cc, so ?= always sees it set.
# Only override when CC came from make's built-in default, never when the
# caller passed one.
ifeq ($(origin CC),default)
  CC_IS_DEFAULT := 1
endif

ifeq ($(UNAME_S),Darwin)
  ifdef CC_IS_DEFAULT
    CC := clang
  endif
  CFLAGS   := $(BASE_CFLAGS)
  PLATFORM := macOS ($(UNAME_M))
else ifeq ($(UNAME_S),Linux)
  ifdef CC_IS_DEFAULT
    CC := gcc
  endif
  # glibc hides some POSIX declarations under strict c11 without this.
  CFLAGS   := $(BASE_CFLAGS) -D_DEFAULT_SOURCE
  PLATFORM := Linux ($(UNAME_M))
else
  CFLAGS   := $(BASE_CFLAGS)
  PLATFORM := $(UNAME_S) ($(UNAME_M)) - untested, building portably
endif

# Install prefix: honour PREFIX, else use /usr/local when it is actually
# writable, else fall back to ~/.local. The fallback is the common case on
# shared machines where nobody has root - a hard-coded /usr/local just fails.
ifdef PREFIX
  INSTALL_PREFIX := $(PREFIX)
else
  INSTALL_PREFIX := $(shell if [ -w /usr/local/bin ]; then echo /usr/local; else echo $$HOME/.local; fi)
endif
BINDIR := $(INSTALL_PREFIX)/bin

.PHONY: all install uninstall run clean info

all: $(BIN)

$(BIN): $(SRC) $(HDR)
	@echo "building for $(PLATFORM) with $(CC)"
	$(CC) $(CFLAGS) -o $@ $(SRC)
	@echo "built ./$(BIN)"

install: $(BIN)
	@mkdir -p $(BINDIR)
	cp $(BIN) $(BINDIR)/$(BIN)
	@chmod 755 $(BINDIR)/$(BIN)
	@echo "installed to $(BINDIR)/$(BIN)"
	@case ":$$PATH:" in \
	  *":$(BINDIR):"*) echo "$(BINDIR) is on PATH - run: $(BIN)" ;; \
	  *) echo "NOTE: $(BINDIR) is not on PATH. Add it:"; \
	     echo "      export PATH=\"$(BINDIR):\$$PATH\"" ;; \
	esac

uninstall:
	rm -f $(BINDIR)/$(BIN)
	@echo "removed $(BINDIR)/$(BIN)"

run: $(BIN)
	./$(BIN)

clean:
	rm -f $(BIN)

info:
	@echo "platform : $(PLATFORM)"
	@echo "compiler : $(CC)"
	@echo "cflags   : $(CFLAGS)"
	@echo "bindir   : $(BINDIR)"
