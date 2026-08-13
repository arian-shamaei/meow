/*
 * meow_auto.ino -- the auto-detecting installer stick.
 *
 * One firmware, any OS. On plug-in the board detects which OS enumerated it and
 * runs that OS's terminal-open + meow install. No selector, no per-OS flashing.
 *
 * Detection: during USB enumeration, WINDOWS uniquely requests the "Microsoft OS
 * String Descriptor" at string index 0xEE. macOS and Linux never do. We sniff
 * that request through the PluggableUSB getDescriptor() hook (no core patch).
 *
 * Why this is exactly right: whoever ENUMERATES the USB device is also whoever
 * RECEIVES its keystrokes. So the detected OS is always the one the keys will
 * reach -- including a Parallels VM that has grabbed the device (Windows
 * enumerates it, sees 0xEE, and the Windows sequence runs inside the VM).
 *
 * Windows -> Win+R -> powershell -> install.ps1
 * else    -> macOS Spotlight -> Finder Utilities -> Terminal -> install.sh
 * (Linux is treated as "else"; its sequence is a separate future branch.)
 */

#include <Keyboard.h>
#include <PluggableUSB.h>

/* ---- OS sniffer: catches the Windows 0xEE descriptor request --------- */
class OSDetect : public PluggableUSBModule {
public:
    volatile bool windows = false;
    OSDetect() : PluggableUSBModule(0, 0, NULL) { PluggableUSB().plug(this); }
protected:
    bool setup(USBSetup&) { return false; }
    int  getInterface(uint8_t*) { return 0; }
    int  getDescriptor(USBSetup& s) {
        /* Two Windows tells, either one is enough:
         *  - STRING 0xEE (MS OS String Descriptor): only on the FIRST enumeration
         *    of a given VID/PID/bcdDevice -- Windows caches the result and never
         *    re-requests it, so this alone fails on re-plug.
         *  - DEVICE_QUALIFIER (type 0x06): Windows requests it on EVERY
         *    enumeration; macOS never does (both confirmed empirically -- the
         *    board reads MAC on macOS and WINDOWS on Windows). This is what makes
         *    Windows detection survive the 0xEE cache on re-plug. */
        if (s.wValueH == 3 && s.wValueL == 0xEE) windows = true;
        if (s.wValueH == 6)                      windows = true;
        return 0;   /* not handled -- let the core continue normally */
    }
};
static OSDetect osdetect;

/* ---- install commands ------------------------------------------------- */
#define MEOW_URL "https://github.com/arian-shamaei/meow/releases/latest/download"
#define WIN_CMD  "iwr -useb " MEOW_URL "/install.ps1 | iex; exit"
#define NIX_CMD  "curl -fsSL " MEOW_URL "/install.sh | sh; exit"

/* ---- keystroke helpers ------------------------------------------------ */
static void combo(uint8_t mod, uint8_t key)
{ Keyboard.press(mod); delay(50); Keyboard.press(key); delay(80); Keyboard.releaseAll(); }
static void combo3(uint8_t m1, uint8_t m2, uint8_t key)
{ Keyboard.press(m1); Keyboard.press(m2); delay(50); Keyboard.press(key); delay(80); Keyboard.releaseAll(); }
static void tap(uint8_t key)
{ Keyboard.press(key); delay(40); Keyboard.release(key); }
static void run_line(const char *s)
{ Keyboard.print(s); delay(80); Keyboard.write(KEY_RETURN); }
static void type_str(const char *s)
{ Keyboard.print(s); delay(80); }

/* ---- per-OS flows ----------------------------------------------------- */
static void do_windows(void)
{
    /* Type the WHOLE command into the Run dialog: powershell -Command "<installer>".
     * Run launches PowerShell already carrying the command, so there is no
     * fragile second typing into a not-yet-ready console (that race left an
     * empty PowerShell window). PowerShell runs -Command and the window closes
     * on its own when it finishes. */
    combo(KEY_LEFT_GUI, 'r');   delay(1500);   /* Run dialog (auto-selects old text) */
    run_line("powershell -NoProfile -Command \"iwr -useb " MEOW_URL "/install.ps1 | iex\"");
}

static void do_mac(void)
{
    /* Launch macOS Terminal by LOCATION (Spotlight name-search collides with a
     * Parallels-published Windows "Terminal"): Utilities folder -> type-select. */
    tap(KEY_ESC);                        delay(200);
    combo(KEY_LEFT_GUI, ' ');            delay(900);   /* Spotlight */
    run_line("Finder");                  delay(1300);  /* activate Finder */
    combo3(KEY_LEFT_GUI, KEY_LEFT_SHIFT, 'u'); delay(1600);  /* Go -> Utilities */
    type_str("Terminal");                delay(700);   /* type-select Terminal.app */
    combo(KEY_LEFT_GUI, 'o');            delay(3500);  /* Cmd+O launches it */
    run_line(NIX_CMD);                                 /* installs; adds to PATH */
    /* close the Terminal window, then the Finder Utilities window */
    delay(12000);
    combo(KEY_LEFT_GUI, 'w');            delay(800);
    combo(KEY_LEFT_GUI, KEY_TAB);        delay(800);   /* -> Finder */
    combo(KEY_LEFT_GUI, 'w');
}

static const __FlashStringHelper* detected_os(void)
{
    return osdetect.windows ? F("WINDOWS") : F("MAC/other");
}

void setup(void)
{
    Serial.begin(115200);
    Keyboard.begin();
    delay(3000);           /* enumeration completes here; 0xEE seen if Windows */

#ifdef MEOW_PROBE
    /* Probe mode: report the RAW flags forever and NEVER install. Raw (not just
     * the winner) so a real-Linux test through WSL/usbipd is visible even when
     * Windows enumerated the device first and set the Windows flag: watch the
     * LINUX flag flip 0->1 when the Linux kernel enumerates it. */
    for (;;) {
        Serial.print(F("meow-auto WIN=")); Serial.print(osdetect.windows);
        Serial.print(F(" LINUX="));        Serial.print(osdetect.linux);
        Serial.print(F(" -> "));            Serial.println(detected_os());
        delay(300);
    }
#endif

    /* telemetry so the detection is verifiable over serial before it fires */
    for (uint8_t i = 0; i < 5; i++) {
        Serial.print(F("meow-auto OS=")); Serial.println(detected_os());
        delay(400);
    }

    if (osdetect.windows) do_windows();
    else                  do_mac();
}

void loop(void) { }
