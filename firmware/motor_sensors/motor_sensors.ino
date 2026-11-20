// Motor current / voltage logger for the 2-DOF arm twin.   *** NOT TESTED ON HARDWARE ***
// (its arithmetic is checked against a register-level INA226 model: live/ina226.py, tests/test_ina226.py, docs/FIRMWARE.md)
//
// Board:   ESP32 (any), I2C on GPIO21 (SDA) / GPIO22 (SCL)
// Sensors: 2 x INA226 with the shunt in the +24 V supply line of each motor drive
//            INA226 #0 address 0x40 = base motor, INA226 #1 address 0x41 = shoulder motor (A0 tied to VS)
// Output:  ASCII lines, one per line:
//            S,<millis>,<ch>,<mA>,<mV>     a sample; ch 0 = base, 1 = shoulder
//            H,<fw>,<shunt_mOhm>,<max_mA>,<cal>,<avg>,<period_ms>   header, sent once at start-up
//            E,<millis>,<text>             an error (chip missing, I2C failure), at most one per second
//          over USB serial (921600 baud) and, if WIFI_SSID is set, as UDP datagrams to PC_IP:PC_PORT (both channels in one datagram)
//          matches live/sensors.py on the PC:  python run_twin.py --sensors udp:9100   or   serial:COM5@921600
//
// CHECK BEFORE USE:
//  * SHUNT_OHMS must be the resistance really fitted. Most cheap INA226 breakouts carry a 0.1 ohm shunt (R100): that clips at
//    81.92 mV / 0.1 ohm = 0.8 A. The motors draw several amps, so replace it (for example 5 mOhm) or use a board built for 20 A.
//  * MAX_CURRENT: the largest current you expect; it sets the current register's resolution. SHUNT_OHMS x MAX_CURRENT must stay
//    below 0.08192 V or readings clip at full scale.
//  * supply range: INA226 bus limit is 36 V, the motors are fed 24 V.
//  * the shunt goes in the supply line only, never in the CAN or signal wiring; fuse the supply; common ground with the PC USB only if
//    the 24 V supply is isolated from mains earth (otherwise use the Wi-Fi/UDP output with the ESP32 powered separately).

#include <Wire.h>
#ifdef WIFI_SSID
#include <WiFi.h>
#include <WiFiUdp.h>
#endif

const char*    FW_VERSION = "1";
const float    SHUNT_OHMS = 0.005f;   // [assumed] 5 mOhm: the value that is really fitted decides every reading
const float    MAX_CURRENT = 10.0f;   // [assumed] A, full scale for the calibration register
const uint8_t  ADDR[2]    = {0x40, 0x41};
const uint32_t PERIOD_MS  = 10;       // 100 samples/s per channel
const uint8_t  AVG_BITS   = 0b010;    // averaging: 000=1 001=4 010=16 011=64 ...  16 x (1.1 + 1.1 ms) = 35 ms per result
const uint8_t  CT_BITS    = 0b100;    // conversion time for shunt and bus: 100 = 1.1 ms

// INA226 registers
const uint8_t REG_CONFIG = 0x00, REG_BUS = 0x02, REG_CURRENT = 0x04, REG_CAL = 0x05, REG_MANUF = 0xFE;
float currentLsb;
uint16_t calValue;
uint32_t lastErrMs = 0;

#ifdef WIFI_SSID
WiFiUDP udp;
const char* PC_IP = "192.168.0.10";   // [set me]
const uint16_t PC_PORT = 9100;
#endif

void emit(const char* s, int n) {
  Serial.write((const uint8_t*)s, n);
#ifdef WIFI_SSID
  if (WiFi.status() == WL_CONNECTED) {
    udp.beginPacket(PC_IP, PC_PORT);
    udp.write((const uint8_t*)s, n);
    udp.endPacket();
  }
#endif
}

void reportError(const char* what, int ch) {
  uint32_t now = millis();
  if (now - lastErrMs < 1000) return;
  lastErrMs = now;
  char line[80];
  int n = snprintf(line, sizeof line, "E,%lu,%s %d\n", (unsigned long)now, what, ch);
  emit(line, n);
}

void writeReg(uint8_t addr, uint8_t reg, uint16_t val) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  Wire.write(val >> 8);
  Wire.write(val & 0xFF);
  Wire.endTransmission();
}

// Returns false when the chip does not answer. The two bytes are read into separate variables on purpose:
// (Wire.read() << 8) | Wire.read() would evaluate the two reads in an unspecified order and could swap high and low byte.
bool readReg(uint8_t addr, uint8_t reg, uint16_t &out) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(addr, (uint8_t)2) != 2) return false;
  uint8_t hi = Wire.read();
  uint8_t lo = Wire.read();
  out = ((uint16_t)hi << 8) | lo;
  return true;
}

void setup() {
  Serial.begin(921600);
  Wire.begin(21, 22);
  Wire.setClock(400000);
  currentLsb = MAX_CURRENT / 32768.0f;
  calValue = (uint16_t)(0.00512f / (currentLsb * SHUNT_OHMS));
  for (int i = 0; i < 2; i++) {
    uint16_t id = 0;
    if (!readReg(ADDR[i], REG_MANUF, id) || id != 0x5449) {   // 0x5449 = "TI": is an INA226 really there?
      reportError("ina226 not found, channel", i);
      continue;
    }
    // continuous shunt + bus conversion, averaged: AVG_BITS in bits 11:9, bus CT in 8:6, shunt CT in 5:3, mode 111 in 2:0
    writeReg(ADDR[i], REG_CONFIG, 0x4000 | ((uint16_t)AVG_BITS << 9) | ((uint16_t)CT_BITS << 6) | ((uint16_t)CT_BITS << 3) | 0b111);
    writeReg(ADDR[i], REG_CAL, calValue);
  }
  char head[96];
  int n = snprintf(head, sizeof head, "H,%s,%.1f,%.0f,%u,%u,%lu\n", FW_VERSION, SHUNT_OHMS * 1000.0f, MAX_CURRENT * 1000.0f,
                   (unsigned)calValue, (unsigned)AVG_BITS, (unsigned long)PERIOD_MS);
  Serial.write((const uint8_t*)head, n);
#ifdef WIFI_SSID
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 20000) delay(200);   // give up after 20 s: keep logging over USB
#endif
}

void loop() {
  static uint32_t next = 0;
  uint32_t now = millis();
  if ((int32_t)(now - next) < 0) return;                       // wrap-safe
  next = now + PERIOD_MS;
  char buf[128];
  int len = 0;
  for (int ch = 0; ch < 2; ch++) {
    uint16_t rawI, rawV;
    if (!readReg(ADDR[ch], REG_CURRENT, rawI) || !readReg(ADDR[ch], REG_BUS, rawV)) {
      reportError("i2c read failed, channel", ch);
      continue;
    }
    float mA = (int16_t)rawI * currentLsb * 1000.0f;           // the current register is signed
    float mV = rawV * 1.25f;                                   // bus voltage LSB = 1.25 mV
    len += snprintf(buf + len, sizeof buf - len, "S,%lu,%d,%.0f,%.0f\n", (unsigned long)now, ch, mA, mV);
  }
  if (len > 0) emit(buf, len);                                 // both channels in one datagram
}
