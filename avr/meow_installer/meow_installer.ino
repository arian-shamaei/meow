/*
 * meow_installer.ino -- the USB stick that installs meow.
 *
 * On plug-in (no gate, no button), the Arduino Micro acts as a USB HID
 * keyboard and types the keystrokes to: open a terminal, run the meow
 * installer, and (the installer then) add meow to PATH. That is all it does.
 *
 * This is a HID keystroke-injection ("BadUSB"/Rubber-Ducky) technique used
 * here for its benign purpose: auto-installing a harmless program on machines
 * you own. It contains no stealth and hides nothing.
 *
 * Two compile-time settings, because a USB keyboard cannot detect which
 * computer it is plugged into and cannot fetch anything itself:
 *
 *   TARGET_OS    which terminal-open sequence to type (WIN / MAC / LINUX)
 *   INSTALL_CMD  the one line run in that terminal (your real installer)
 *
 *   arduino-cli compile --fqbn arduino:avr:micro \
 *     --build-property compiler.cpp.extra_flags="-DTARGET_OS=OS_WIN -DINSTALL_CMD=\"...\""
 */

#include <Keyboard.h>

#define OS_WIN   1
#define OS_MAC   2
#define OS_LINUX 3

#ifndef TARGET_OS
#define TARGET_OS OS_WIN
#endif

/* The install one-liner, per OS. Each fetches a hosted installer and runs it;
 * install.sh / install.ps1 add meow to PATH themselves. Set MEOW_URL to wherever
 * you host them (the board cannot fetch on its own, so the command must). */
#ifndef MEOW_URL
#define MEOW_URL "https://github.com/arian-shamaei/meow/releases/latest/download"
#endif
/* Each command ends with `; exit` so the terminal window closes once the
 * install finishes (on success; an error leaves it open to read). */
#ifndef INSTALL_CMD
#  if defined(MEOW_DIAG)
#    define INSTALL_CMD "printf 'meow-stick-ok ' > ~/meow_stick_worked; date >> ~/meow_stick_worked; exit"
#  elif TARGET_OS == OS_WIN
#    define INSTALL_CMD "iwr -useb " MEOW_URL "/install.ps1 | iex; exit"
#  else
#    define INSTALL_CMD "curl -fsSL " MEOW_URL "/install.sh | sh; exit"
#  endif
#endif

/* ---- keystroke helpers ------------------------------------------------- */
static void combo(uint8_t mod, uint8_t key)
{
    Keyboard.press(mod);
    delay(50);
    Keyboard.press(key);
    delay(80);
    Keyboard.releaseAll();
}

static void combo3(uint8_t m1, uint8_t m2, uint8_t key)
{
    Keyboard.press(m1);
    Keyboard.press(m2);
    delay(50);
    Keyboard.press(key);
    delay(80);
    Keyboard.releaseAll();
}

static void tap(uint8_t key)
{
    Keyboard.press(key);
    delay(40);
    Keyboard.release(key);
}

static void run_line(const char *s)
{
    Keyboard.print(s);
    delay(80);
    Keyboard.write(KEY_RETURN);
}

/* Type text without pressing Return (for Finder type-select). */
static void type_str(const char *s)
{
    Keyboard.print(s);
    delay(80);
}

/* ---- open a terminal on the target OS ---------------------------------- */
static void open_terminal(void)
{
#if TARGET_OS == OS_WIN
    combo(KEY_LEFT_GUI, 'r');       /* Run dialog */
    delay(700);
    run_line("powershell");
    delay(1600);                    /* PowerShell window appears */
#elif TARGET_OS == OS_MAC
    /* macOS Terminal.app and a Parallels-published Windows "Terminal" share the
     * exact name, so NO Spotlight query can tell them apart, and the VM app can
     * rank first. Launch by LOCATION instead: open Finder's Utilities folder
     * (Cmd+Shift+U -- semantic, version-independent) where only the real
     * Terminal.app lives, type-select it, and open it with Cmd+O. */
    tap(KEY_ESC);                        delay(200);
    combo(KEY_LEFT_GUI, ' ');            delay(900);   /* Spotlight (global) */
    run_line("Finder");                  delay(1300);  /* activate Finder */
    combo3(KEY_LEFT_GUI, KEY_LEFT_SHIFT, 'u'); delay(1600);  /* Go -> Utilities */
    type_str("Terminal");                delay(700);   /* type-select Terminal.app */
    combo(KEY_LEFT_GUI, 'o');            delay(3500);  /* Cmd+O launches it */
#elif TARGET_OS == OS_LINUX
    combo3(KEY_LEFT_CTRL, KEY_LEFT_ALT, 't');   /* common, not universal */
    delay(1600);
#endif
}

void setup(void)
{
    Keyboard.begin();
    delay(3000);            /* let USB enumerate and the desktop settle */
    open_terminal();
    run_line(INSTALL_CMD);  /* the installer; it adds meow to PATH itself */

#if TARGET_OS == OS_MAC
    /* Clean up BOTH windows this opened. macOS Terminal ignores `exit` for
     * closing, so once the install has finished (the shell exited via `; exit`)
     * Cmd+W closes the Terminal window with no prompt. Focus then falls back to
     * the Finder Utilities window we opened to launch Terminal, so a second
     * Cmd+W closes that one too. */
    delay(12000);                 /* wait for the install + shell exit */
    combo(KEY_LEFT_GUI, 'w');     /* close the Terminal window */
    delay(800);
    /* Closing Terminal's last window leaves Terminal frontmost but windowless,
     * so a second Cmd+W would hit nothing. Switch to Finder first (Cmd+Tab ->
     * previous app), then close its Utilities window. */
    combo(KEY_LEFT_GUI, KEY_TAB); delay(800);   /* Cmd+Tab -> Finder */
    combo(KEY_LEFT_GUI, 'w');     /* close the Finder Utilities window */
#endif
    /* one-shot: never types again until re-plugged */
}

void loop(void)
{
}
