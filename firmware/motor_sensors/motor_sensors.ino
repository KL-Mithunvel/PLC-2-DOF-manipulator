// Motor current / voltage logger for the 2-DOF arm twin.   *** NOT TESTED ON HARDWARE ***
//
// Board:   ESP32 (any), I2C on GPIO21 (SDA) / GPIO22 (SCL)
// Sensors: 2 x INA226 breakouts with the shunt in the +24 V supply line of each motor drive
//            INA226 #0 address 0x40 = base motor, INA226 #1 address 0x41 = shoulder motor (A0 tied to VS)
// Output:  ASCII lines "S,<millis>,<ch>,<mA>,<mV>\n"   ch 0 = base, 1 = shoulder
//            over USB serial (921600 baud) and, if WIFI_SSID is set, as UDP datagrams to PC_IP:PC_PORT
//          matches live/sensors.py on the PC:  python run_twin.py --sensors udp:9100   or   serial:COM5@921600
//
// CHECK BEFORE USE: shunt value / maximum current below, supply range (INA226 bus limit 36 V, the motors are fed 24 V),
// and that the shunt is in the supply line, never in the CAN or signal wiring.

#include <Wire.h>
#ifdef WIFI_SSID
#include <WiFi.h>
#include <WiFiUdp.h>
#endif

const float SHUNT_OHMS   = 0.005f;   // [assumed] 5 mOhm
const float MAX_CURRENT  = 10.0f;    // [assumed] A, full scale for the calibration register
const uint8_t ADDR[2]    = {0x40, 0x41};
const uint32_t PERIOD_MS = 10;       // 100 samples/s per channel

// INA226 registers
const uint8_t REG_CONFIG = 0x00, REG_BUS = 0x02, REG_CURRENT = 0x04, REG_CAL = 0x05;
float currentLsb;

#ifdef WIFI_SSID
WiFiUDP udp;
const char* PC_IP = "192.168.0.10";   // [set me]
const uint16_t PC_PORT = 9100;
#endif

void writeReg(uint8_t addr, uint8_t reg, uint16_t val) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  Wire.write(val >> 8);
  Wire.write(val & 0xFF);
  Wire.endTransmission();
}

int16_t readReg(uint8_t addr, uint8_t reg) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  Wire.endTransmission(false);
  Wire.requestFrom(addr, (uint8_t)2);
  int16_t v = (Wire.read() << 8) | Wire.read();
  return v;
}

void setup() {
  Serial.begin(921600);
  Wire.begin(21, 22);
  Wire.setClock(400000);
  currentLsb = MAX_CURRENT / 32768.0f;
  uint16_t cal = (uint16_t)(0.00512f / (currentLsb * SHUNT_OHMS));
  for (int i = 0; i < 2; i++) {
    // AVG=16, VBUSCT=VSHCT=1.1 ms, continuous shunt+bus -> ~35 ms per averaged result; use AVG=4 for faster updates
    writeReg(ADDR[i], REG_CONFIG, 0x4000 | (0b001 << 9) | (0b100 << 6) | (0b100 << 3) | 0b111);
    writeReg(ADDR[i], REG_CAL, cal);
  }
#ifdef WIFI_SSID
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) delay(200);
#endif
}

void loop() {
  static uint32_t next = 0;
  uint32_t now = millis();
  if (now < next) return;
  next = now + PERIOD_MS;
  for (int ch = 0; ch < 2; ch++) {
    float mA = readReg(ADDR[ch], REG_CURRENT) * currentLsb * 1000.0f;
    float mV = (uint16_t)readReg(ADDR[ch], REG_BUS) * 1.25f;          // bus voltage LSB = 1.25 mV
    char line[64];
    int n = snprintf(line, sizeof line, "S,%lu,%d,%.0f,%.0f\n", (unsigned long)now, ch, mA, mV);
    Serial.write((const uint8_t*)line, n);
#ifdef WIFI_SSID
    udp.beginPacket(PC_IP, PC_PORT);
    udp.write((const uint8_t*)line, n);
    udp.endPacket();
#endif
  }
}
