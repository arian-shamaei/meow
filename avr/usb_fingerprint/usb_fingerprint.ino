/*
 * usb_fingerprint.ino -- capture the host's USB enumeration fingerprint.
 *
 * Records every descriptor request (and class request) the host makes during
 * enumeration into a buffer, then dumps it over serial. Same composite device
 * shape as meow_auto (CDC + HID keyboard) so the fingerprint matches.
 *
 * Use it to find a request that Linux makes but macOS does not, the way 0xEE
 * uniquely identifies Windows.
 */
#include <Keyboard.h>
#include <PluggableUSB.h>

#define NREC 64
static volatile uint8_t r_kind[NREC];   /* 'D' = GET_DESCRIPTOR, 'C' = class setup */
static volatile uint8_t r_a[NREC];      /* D: wValueH (desc type) | C: bmRequestType */
static volatile uint8_t r_b[NREC];      /* D: wValueL (index)     | C: bRequest      */
static volatile uint8_t r_len[NREC];    /* wLength low byte */
static volatile uint8_t r_n = 0;

class Sniffer : public PluggableUSBModule {
public:
    Sniffer() : PluggableUSBModule(0, 0, NULL) { PluggableUSB().plug(this); }
protected:
    bool setup(USBSetup& s) {
        if (r_n < NREC) { r_kind[r_n]='C'; r_a[r_n]=s.bmRequestType; r_b[r_n]=s.bRequest; r_len[r_n]=s.wLength; r_n++; }
        return false;
    }
    int getInterface(uint8_t*) { return 0; }
    int getDescriptor(USBSetup& s) {
        if (r_n < NREC) { r_kind[r_n]='D'; r_a[r_n]=s.wValueH; r_b[r_n]=s.wValueL; r_len[r_n]=s.wLength; r_n++; }
        return 0;   /* observe only */
    }
};
static Sniffer sniffer;

void setup(void)
{
    Serial.begin(115200);
    Keyboard.begin();
    delay(3500);            /* enumeration finished; buffer holds the requests */

    for (;;) {              /* dump forever so it can be read any time */
        Serial.print(F("=== enumeration fingerprint, n="));
        Serial.print(r_n);
        Serial.println(F(" ==="));
        for (uint8_t i = 0; i < r_n; i++) {
            Serial.print(i); Serial.print(':');
            if (r_kind[i] == 'D') {
                Serial.print(F(" GET_DESC type=0x")); Serial.print(r_a[i], HEX);
                Serial.print(F(" idx=0x"));           Serial.print(r_b[i], HEX);
                Serial.print(F(" len="));             Serial.println(r_len[i]);
            } else {
                Serial.print(F(" CLASS bmReq=0x")); Serial.print(r_a[i], HEX);
                Serial.print(F(" bReq=0x"));         Serial.print(r_b[i], HEX);
                Serial.print(F(" len="));            Serial.println(r_len[i]);
            }
        }
        Serial.println();
        delay(4000);
    }
}

void loop(void) { }
