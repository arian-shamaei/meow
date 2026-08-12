/* Uno Q 8x13 matrix as a LIVE serial display.
 * Protocol: magic {0xFE,0xED,0xBE,0xEF} then 104 grayscale bytes (row-major
 * 8 rows x 13 cols, 0..255). Draws each frame and acks with 'K'.
 * Drive it from board_server.py. */
#include <Arduino_LED_Matrix.h>
Arduino_LED_Matrix matrix;

uint8_t buf[104];

// idle splash so the panel isn't blank before the server connects
static const uint8_t idle_frame[104] = {
  0,0,0,0,0,0,0,0,0,0,0,0,0,
  0,40,0,0,0,0,0,0,0,0,0,40,0,
  0,40,40,0,0,0,0,0,0,0,40,40,0,
  0,40,40,40,40,40,40,40,40,40,40,40,0,
  0,40,0,40,40,0,40,40,0,40,0,40,0,
  0,40,40,40,40,40,40,40,40,40,40,40,0,
  0,40,40,40,0,40,0,40,0,40,40,40,0,
  0,0,0,0,0,0,0,0,0,0,0,0,0,
};

void setup() {
  Serial.begin(115200);
  matrix.begin();
  matrix.setGrayscaleBits(8);
  matrix.draw(idle_frame);
}

void loop() {
  static int state = 0;   // magic-scan state
  while (Serial.available()) {
    int b = Serial.read();
    switch (state) {
      case 0: state = (b == 0xFE) ? 1 : 0; break;
      case 1: state = (b == 0xED) ? 2 : (b == 0xFE ? 1 : 0); break;
      case 2: state = (b == 0xBE) ? 3 : (b == 0xFE ? 1 : 0); break;
      case 3:
        if (b == 0xEF) {
          int n = 0; unsigned long t0 = millis();
          while (n < 104) {
            if (Serial.available()) { buf[n++] = (uint8_t)Serial.read(); }
            else if (millis() - t0 > 250) break;
          }
          if (n == 104) { matrix.draw(buf); Serial.write('K'); }
          state = 0;
        } else {
          state = (b == 0xFE ? 1 : 0);
        }
        break;
    }
  }
}
