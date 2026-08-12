/* Kaleidoscope engine ON the STM32 — mirrored geometric patterns rendered
 * locally at high frame rate. The host sends only a few parameter bytes.
 *
 * Why: Serial.read() costs ~6ms/BYTE on this core, so streaming 104-byte
 * frames caps at ~1.6 fps and backlogs (the panel shows stale frames, which
 * is why the web preview and the board disagreed). Rendering on-board and
 * sending tiny param packets removes that bottleneck entirely.
 *
 * Protocol (every packet acked: 'K' good / 'X' bad checksum):
 *   0xA5 p0..p7 sum   -> set params
 *   0xA6 lvl bass sum -> reactive drive (sensor/audio)
 * checksum = sum(payload) & 0xFF
 */
#include <Arduino_LED_Matrix.h>
#include <math.h>
#include <zephyr/device.h>
#include <zephyr/drivers/adc.h>
#include <zephyr/storage/flash_map.h>
#include <Font.h>
/* ArduinoGraphics ships a hand-designed 5x7 bitmap font; far cleaner than a
 * downscaled system font. Glyph rows are MSB-left (bit7 = leftmost column). */
extern const struct Font Font_5x7;
#define FONT_W 5
#define FONT_H 7

Arduino_LED_Matrix matrix;

/* ---- the board's own sensors -------------------------------------------
 * The Uno Q has no discrete sensors, but the STM32U585 has an internal
 * factory-calibrated die-temperature sensor (ADC1 ch19) and an internal
 * voltage reference (ch0) that yields the real VDDA rail. Zephyr's SENSOR
 * subsystem is not compiled into this core, so we read them via raw ADC and
 * enable the internal analog paths by hand. */
static const struct device *adc1 = DEVICE_DT_GET(DT_NODELABEL(adc1));
#define TS_CAL1 (*(uint16_t *)0x0BFA0710)   /* 30 C  */
#define TS_CAL2 (*(uint16_t *)0x0BFA0742)   /* 130 C */
#define VREF_CAL (*(uint16_t *)0x0BFA07A5)
static int16_t adcbuf;
static struct adc_sequence aseq = {
  .channels = 0, .buffer = &adcbuf, .buffer_size = sizeof(adcbuf), .resolution = 14,
};
static int adc_ch(uint8_t ch) {
  struct adc_channel_cfg cfg = { .gain = ADC_GAIN_1, .reference = ADC_REF_INTERNAL,
    .acquisition_time = ADC_ACQ_TIME_MAX, .channel_id = ch, .differential = 0 };
  if (adc_channel_setup(adc1, &cfg) != 0) return -1;
  aseq.channels = BIT(ch);
  if (adc_read(adc1, &aseq) != 0) return -1;
  return (int)adcbuf;
}
float board_tempC = 0.0f, board_vdda = 0.0f;
static void read_onboard_sensors(void) {
  int traw = adc_ch(19), vraw = adc_ch(0);
  if (traw <= 0 || vraw <= 0) return;
  board_vdda = 3000.0f * (float)VREF_CAL / (float)vraw;
  float adj = (float)traw * board_vdda / 3000.0f;   /* TS_CAL taken at 3.0V */
  board_tempC = (100.0f / (float)(TS_CAL2 - TS_CAL1)) * (adj - (float)TS_CAL1) + 30.0f;
}

/* powf()/fmodf() from newlib-nano reference __errno, which this Zephyr build
 * does not provide (link error), so both are avoided. Gamma is approximated
 * by blending v^0.5 / v / v^2 — visually equivalent for a brightness curve. */
static inline float gpow(float v, float g) {
  if (v <= 0.0f) return 0.0f;
  if (g < 1.0f) {
    float t = (1.0f - g) / 0.6f; if (t > 1) t = 1; if (t < 0) t = 0;
    return v + (sqrtf(v) - v) * t;
  }
  float t = (g - 1.0f) / 0.6f; if (t > 1) t = 1; if (t < 0) t = 0;
  return v + (v * v - v) * t;
}

// ---- parameters ----
uint8_t P_pattern = 0, P_speed = 100, P_segments = 6, P_scale = 85;
uint8_t P_bright = 170, P_gamma = 85, P_react = 0, P_flags = 0;
uint8_t R_level = 0, R_bass = 0;
uint8_t saved_ok = 0;      /* 0=nothing saved 1=saved/restored 2=save failed */

uint8_t fb[104];
float phase = 0.0f;

/* ---- scrolling text marquee -------------------------------------------
 * Text is uploaded into STAGE and only swapped into TXT on an explicit
 * commit, so appending chunks never disturbs what is currently scrolling
 * (that was the source of the glitching on long uploads).
 * Motion is sub-pixel: each output column blends the two neighbouring source
 * columns by the fractional scroll offset, so it glides instead of stepping
 * one whole LED at a time. */
#define TXT_MAX 4096
char    TXT[TXT_MAX];     int TXT_LEN = 0;
char    STAGE[TXT_MAX];   int STAGE_LEN = 0;
float   scroll_x = 0.0f;
#define ADVANCE (FONT_W + 1)          /* glyph cell = 5 cols + 1 space */

/* Is the pixel at absolute source column i, row r, lit? */
static inline int text_pixel(int i, int r, int total, int cycle) {
  if (cycle <= 0) return 0;
  i %= cycle; if (i < 0) i += cycle;
  if (i >= total) return 0;           /* trailing gap before it repeats */
  int gi = i / ADVANCE, gc = i % ADVANCE;
  if (gc >= FONT_W) return 0;         /* inter-character space */
  unsigned char ch = (unsigned char)TXT[gi];
  const uint8_t *g = Font_5x7.data[ch];
  if (g == NULL) return 0;                 /* undefined glyph -> blank */
  if (r >= Font_5x7.height) return 0;
  return (g[r] >> (7 - gc)) & 1;           /* MSB is the leftmost column */
}

void render_text(void) {
  float br = u8f(P_bright, 0.0f, 1.5f);
  if (P_react & 1) br *= (0.35f + 1.1f * (R_level / 255.0f));
  for (int i = 0; i < 104; i++) fb[i] = 0;

  int total = TXT_LEN * ADVANCE;
  int cycle = total + 13;
  if (total <= 0) { matrix.draw(fb); return; }

  int   base = (int)floorf(scroll_x);
  float frac = scroll_x - (float)base;      /* 0..1 sub-pixel offset */

  for (int c = 0; c < 13; c++) {
    for (int r = 0; r < FONT_H; r++) {
      float a = (float)text_pixel(base + c,     r, total, cycle);
      float b = (float)text_pixel(base + c + 1, r, total, cycle);
      float v = a * (1.0f - frac) + b * frac; /* anti-aliased motion */
      if (v <= 0.0f) continue;
      float o = v * 255.0f * br;
      if (o > 255) o = 255; if (o < 0) o = 0;
      fb[r * 13 + c] = (uint8_t)o;
    }
  }
  matrix.draw(fb);
}

static inline float u8f(uint8_t v, float lo, float hi) {
  return lo + (hi - lo) * (v / 255.0f);
}

void render(float t) {
  float sc = u8f(P_scale, 0.4f, 2.5f);
  float br = u8f(P_bright, 0.0f, 1.5f);
  float gm = u8f(P_gamma, 0.4f, 1.6f);
  int   seg = P_segments; if (seg < 2) seg = 2; if (seg > 12) seg = 12;

  float lvl = R_level / 255.0f;
  if (P_react & 1) br *= (0.35f + 1.1f * lvl);
  if (P_react & 2) sc *= (0.60f + 1.2f * lvl);
  if (P_react & 8) { seg = 2 + (int)(lvl * 10.0f); if (seg < 2) seg = 2; if (seg > 12) seg = 12; }

  float wseg = 6.28318530718f / (float)seg;

  for (int row = 0; row < 8; row++) {
    float y = (float)row - 3.5f, fy = fabsf(y);
    for (int col = 0; col < 13; col++) {
      float x = (float)col - 6.0f, fx = fabsf(x);   // mirror L/R and T/B
      float r = sqrtf(x*x + y*y) * sc;
      float ang = atan2f(y, x);
      float m = ang + 3.14159265f;                  // [0,2PI]
      int   k = (int)(m / wseg);
      m -= (float)k * wseg;                         // fold into one wedge
      float wedge = fabsf(m - wseg * 0.5f);

      float v;
      switch (P_pattern) {
        case 1: v = 0.5f + 0.5f * sinf(r * 1.4f - t * 3.0f); break;
        case 2: v = 0.5f + 0.5f * sinf(r * 1.2f - t * 2.0f) * cosf(wedge * seg); break;
        case 3: v = 0.5f + 0.5f * sinf(wedge * seg * 1.5f + t * 2.0f); break;
        case 4: v = 0.5f + 0.5f * sinf((fx + fy) * 1.05f * sc - t * 3.0f); break;
        case 5: v = 0.5f + 0.25f * (sinf(fx * 1.3f - t * 2.0f) + sinf(fy * 1.3f + t * 2.0f)); break;
        case 6: v = 0.5f + 0.5f * ((sinf(fx * 0.8f * sc + t)
                                  + sinf(fy * 1.1f * sc - t)
                                  + sinf((fx + fy) * 0.6f * sc + t * 0.7f)) / 3.0f); break;
        default: v = 0.5f + 0.5f * sinf(r * 1.5f - t * 2.0f + wedge * 4.0f);
      }
      if (v < 0) v = 0; if (v > 1) v = 1;
      float o = gpow(v, gm) * 255.0f * br;
      if (o < 0) o = 0; if (o > 255) o = 255;
      fb[row * 13 + col] = (uint8_t)o;
    }
  }
  matrix.draw(fb);
}

/* ---- persistence: save text + settings to on-board flash ---------------
 * The sketch itself already lives in flash (user_sketch @0x100000), so the
 * PROGRAM is non-volatile. This stores the *content* — uploaded text and the
 * current parameters — in the dedicated 256KB storage_partition @0x1C0000,
 * so the board restores its display on power-up with no computer attached. */
#define SAVE_MAGIC 0x3157464BUL          /* "KFW1" */
#define SAVE_ALIGN 16                    /* STM32U5 writes 16-byte quad-words */
#define SAVE_ERASE 16384

static uint8_t savebuf[SAVE_ALIGN * 2 + TXT_MAX + SAVE_ALIGN];

int save_to_flash(void) {
  const struct flash_area *fa;
  if (flash_area_open(FIXED_PARTITION_ID(storage_partition), &fa) != 0) return -1;
  int rc = flash_area_erase(fa, 0, SAVE_ERASE);
  if (rc == 0) {
    uint32_t magic = SAVE_MAGIC;
    memcpy(savebuf + 0, &magic, 4);
    savebuf[4] = P_pattern; savebuf[5] = P_speed;  savebuf[6] = P_segments;
    savebuf[7] = P_scale;   savebuf[8] = P_bright; savebuf[9] = P_gamma;
    savebuf[10] = P_react;  savebuf[11] = P_flags;
    uint16_t n = (uint16_t)TXT_LEN;
    memcpy(savebuf + 12, &n, 2);
    savebuf[14] = 0; savebuf[15] = 0;
    for (int i = 0; i < TXT_LEN; i++) savebuf[16 + i] = (uint8_t)TXT[i];
    int total = 16 + TXT_LEN;
    while (total % SAVE_ALIGN) savebuf[total++] = 0;     /* pad to write block */
    rc = flash_area_write(fa, 0, savebuf, total);
  }
  flash_area_close(fa);
  return rc;
}

int load_from_flash(void) {
  const struct flash_area *fa;
  if (flash_area_open(FIXED_PARTITION_ID(storage_partition), &fa) != 0) return -1;
  int rc = flash_area_read(fa, 0, savebuf, 16);
  if (rc == 0) {
    uint32_t magic; memcpy(&magic, savebuf, 4);
    if (magic != SAVE_MAGIC) { flash_area_close(fa); return 1; }   /* nothing saved */
    P_pattern = savebuf[4]; P_speed  = savebuf[5]; P_segments = savebuf[6];
    P_scale   = savebuf[7]; P_bright = savebuf[8]; P_gamma    = savebuf[9];
    P_react   = savebuf[10]; P_flags = savebuf[11];
    uint16_t n; memcpy(&n, savebuf + 12, 2);
    if (n > TXT_MAX) n = TXT_MAX;
    if (n > 0) rc = flash_area_read(fa, 16, savebuf, n);
    if (rc == 0) { for (int i = 0; i < n; i++) TXT[i] = (char)savebuf[i]; TXT_LEN = n; }
    scroll_x = 0.0f;
  }
  flash_area_close(fa);
  return rc;
}

/* ---- packet parser -----------------------------------------------------
 *   0xA5 <8 bytes> sum        set params
 *   0xA6 <2 bytes> sum        reactive level
 *   0xA7 len <len bytes> sum  append text (len <= 64)
 *   0xA9 sum(=0)              clear text + reset scroll
 * Bounded work per call so it can never spin. */
uint8_t pkt[80];
int need = 0, got = 0;
bool want_len = false;
uint8_t cmd = 0;

void handle_serial() {
  for (int guard = 0; guard < 200; guard++) {
    if (!Serial.available()) return;
    int ci = Serial.read();
    if (ci < 0) return;
    uint8_t b = (uint8_t)ci;

    if (need == 0 && !want_len) {
      if      (b == 0xA5) { cmd = b; need = 9; got = 0; }
      else if (b == 0xA6) { cmd = b; need = 3; got = 0; }
      else if (b == 0xA7) { cmd = b; want_len = true; got = 0; }
      else if (b == 0xA8) { cmd = b; need = 1; got = 0; }
      else if (b == 0xAA) { cmd = b; need = 1; got = 0; }
      else if (b == 0xAB) { cmd = b; need = 1; got = 0; }
      else if (b == 0xA9) { cmd = b; need = 1; got = 0; }
      continue;
    }
    if (want_len) {                       // length byte of a text chunk
      want_len = false;
      pkt[0] = b;                         // stash len at pkt[0]
      need = (int)b + 2;                  // len byte + payload + checksum
      got = 1;
      if (b > 64) { need = 0; got = 0; }  // reject oversize
      continue;
    }

    pkt[got++] = b;
    if (got < need) continue;

    int n = need - 1;                     // bytes covered by the checksum
    uint8_t sum = 0;
    for (int i = 0; i < n; i++) sum += pkt[i];
    if (sum == pkt[n]) {
      if (cmd == 0xA5) {
        P_pattern = pkt[0]; P_speed = pkt[1]; P_segments = pkt[2]; P_scale = pkt[3];
        P_bright  = pkt[4]; P_gamma = pkt[5]; P_react   = pkt[6]; P_flags = pkt[7];
      } else if (cmd == 0xA6) {
        R_level = pkt[0]; R_bass = pkt[1];
      } else if (cmd == 0xA7) {                 // append into the staging buffer
        int len = pkt[0];
        for (int i = 0; i < len && STAGE_LEN < TXT_MAX; i++) STAGE[STAGE_LEN++] = (char)pkt[1 + i];
      } else if (cmd == 0xA8) {                 // commit: swap in atomically
        for (int i = 0; i < STAGE_LEN; i++) TXT[i] = STAGE[i];
        TXT_LEN = STAGE_LEN;
        scroll_x = 0.0f;
      } else if (cmd == 0xA9) {                 // clear staging only
        STAGE_LEN = 0;
      } else if (cmd == 0xAA) {                 // persist to flash
        saved_ok = (save_to_flash() == 0) ? 1 : 2;
      } else if (cmd == 0xAB) {                 // forget saved content
        const struct flash_area *fa;
        if (flash_area_open(FIXED_PARTITION_ID(storage_partition), &fa) == 0) {
          flash_area_erase(fa, 0, SAVE_ERASE); flash_area_close(fa);
        }
        saved_ok = 0;
      }
      Serial.write('K');
    } else {
      Serial.write('X');
    }
    need = 0; got = 0; want_len = false;
  }
}

void setup() {
  Serial.begin(115200);
  matrix.begin();
  matrix.setGrayscaleBits(8);

  /* adc1 is zephyr,deferred-init: touching it via the Arduino API brings the
   * device up. Then enable VREFEN(22)/VSENSESEL(23) in the ADC common CCR
   * (STM32U5 RM0456, ADC12_COMMON = ADC1_BASE+0x300, CCR at +0x08) so the
   * internal temperature/reference channels are actually connected. */
  analogReadResolution(14);
  (void)analogRead(A0);
  volatile uint32_t *ccr = (volatile uint32_t *)(0x42028000UL + 0x308UL);
  *ccr |= (1UL << 22) | (1UL << 23);
  delay(10);
  read_onboard_sensors();

  /* restore whatever was last saved, so the board comes up showing it
   * with no host attached */
  if (load_from_flash() == 0) saved_ok = 1;
}

unsigned long hb = 0;
unsigned long last_us = 0;
unsigned long fps_count = 0, fps_t0 = 0;
float fps_now = 0;

void loop() {
  handle_serial();

  /* Use the REAL elapsed time, not an assumed 16ms frame. Serial work makes
   * the loop period vary, and a fixed step turned that variation into
   * visible stutter regardless of text length. */
  unsigned long now_us = micros();
  float dt = (float)(now_us - last_us) * 1e-6f;
  last_us = now_us;
  if (dt < 0.0f || dt > 0.25f) dt = 0.016f;   // clamp across pauses/wrap

  float sp = u8f(P_speed, 0.0f, 3.0f);
  if (P_react & 4) sp *= (0.3f + 1.8f * (R_level / 255.0f));

  fps_count++;
  if (P_flags & 2) {                    // ---- text marquee mode ----
    scroll_x += dt * sp * 12.0f;        // columns per second
    int cycle = TXT_LEN * ADVANCE + 13;
    if (cycle > 0) {
      while (scroll_x >= (float)cycle) scroll_x -= (float)cycle;
      if (scroll_x < 0) scroll_x = 0;
    }
    render_text();
  } else {                              // ---- kaleidoscope mode ----
    phase += dt * sp * 2.0f;
    if (phase > 6283.0f) phase -= 6283.0f;
    render(phase);
  }

  if (millis() - hb > 500) {           // liveness beacon + sensor telemetry
    hb = millis();
    read_onboard_sensors();
    /* P_flags bit0: drive the pattern from the board's OWN temperature
     * sensor, mapping 25..45 C onto the full level range. No host needed. */
    if (P_flags & 1) {
      float t = (board_tempC - 25.0f) / 20.0f;
      if (t < 0) t = 0; if (t > 1) t = 1;
      R_level = (uint8_t)(t * 255.0f);
    }
    Serial.print("KFW lvl="); Serial.print(R_level);
    Serial.print(" t="); Serial.print(board_tempC, 1);
    Serial.print(" v="); Serial.print(board_vdda, 0);
    Serial.print(" n="); Serial.print(TXT_LEN);
    unsigned long el = millis() - fps_t0;
    if (el > 0) fps_now = (float)fps_count * 1000.0f / (float)el;
    fps_count = 0; fps_t0 = millis();
    Serial.print(" fps="); Serial.print(fps_now, 1);
    Serial.print(" saved="); Serial.println(saved_ok);
  }

  /* Poll serial continuously for the frame interval instead of delay()ing.
   * Serial is only serviced when we ask, so sleeping 16ms made a 4-byte
   * packet take ~800ms; busy-polling drops that to a few ms. */
  unsigned long t_end = millis() + 6;    // serial-poll window
  while ((long)(millis() - t_end) < 0) handle_serial();
}
