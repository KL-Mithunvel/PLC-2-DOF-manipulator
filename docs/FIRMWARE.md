# ESP32 + INA226 motor current logger (firmware and its simulation)

The route chosen on 2026-11-20 for per-motor power: an ESP32 reading two INA226 current/power monitors, one per motor supply line, and streaming samples to the PC. Sketch: `firmware/motor_sensors/motor_sensors.ino`. **It has never run on hardware.** What exists is a register-level model of the chip and a line-for-line Python port of the sketch, so its arithmetic, its failure modes and the whole path to the host are tested first. Background and the alternative (PZEM-017 Modbus meters): [POWER_METER_PLAN.md](POWER_METER_PLAN.md).

## What it does
Two INA226 chips (I2C 0x40 = base motor, 0x41 = shoulder motor), each with a shunt resistor in the +24 V supply line of that motor's drive. Every 10 ms the ESP32 reads current and bus voltage of both and sends text lines (USB serial 921600 baud, and UDP datagrams if Wi-Fi is configured):
```
H,1,5.0,10000,3355,2,10        header once at start-up: firmware version, shunt mOhm, full scale mA, calibration register, AVG bits, period ms
S,1230,0,1520,23950            sample: ms since boot, channel (0 base, 1 shoulder), mA, mV
E,5000,i2c read failed, channel 1   error (at most one per second)
```
The PC side already exists (`live/sensors.py`): `python run_twin.py --sensors udp:9100` or `--sensors serial:COM5@921600`. Samples land in the `sensors` slot, so the GUI, the calibration fit (`tools/fit_motor_params.py --smooth N`), the recorder and the shadow tools use them like any other source. Header and error lines are kept, not counted as bad samples.

## Run it without hardware
`python run_twin.py --sensors esp-sim` runs the simulated logger driven by the twin: the twin's torque becomes the supply current, the INA226 model measures it (averaging, quantisation, saturation), the firmware port turns register values into lines at 100 Hz, and they enter the same `SensorSource` as real lines would. The GUI then shows measured current, voltage and power per motor.

## Findings from reading and simulating the sketch (all fixed in the file)
1. **Unspecified read order (a real bug).** `(Wire.read() << 8) | Wire.read()` evaluates the two reads in an unspecified order in C++; on some compilers the high and low byte swap and every register comes back wrong. Now two separate variables. A test fails if the pattern returns.
2. **Averaging comment and code disagreed.** The comment said AVG=16 (35 ms per result) but the code set AVG=4 (8.8 ms). Now named constants `AVG_BITS = 0b010` (16) and `CT_BITS = 0b100` (1.1 ms), config register 0x4527; the simulation checks the window (35.2 ms). The registers update once per averaged result, so at 100 samples/s about three samples in a row repeat the same value: that is the chip, not a bug.
3. **No check that a chip answers.** A missing or mis-addressed INA226 gave silent zeros. Now the manufacturer ID (0x5449) is checked at start-up and an `E,` line says which channel failed; a failed I2C read skips that sample and reports it.
4. **Wi-Fi could block forever** at start-up; now it gives up after 20 s and keeps logging over USB. The two channels go out in one datagram.
5. **A wrong `SHUNT_OHMS` is a silent scale error, not an error.** Cheap INA226 breakouts carry a **0.1 ohm** shunt (marked R100). With the sketch's 5 mOhm assumption every reading is 20 times too big, and above 0.82 A the chip clips (81.92 mV across the shunt) and the value pins at full scale. The simulation shows both. **Check the resistor on the board you buy**, and set `SHUNT_OHMS` and `MAX_CURRENT` to match; `SHUNT_OHMS x MAX_CURRENT` must stay below 0.08192 V. The motors draw up to several amps, so a 0.1 ohm board must have its shunt replaced (for example 5 mOhm, 2 W or more) or be a 20 A variant.

## Choosing the shunt
Peak current `I`, shunt `R`: shunt voltage `I x R` must stay under 81.92 mV (for 10 A: R at most 8 mOhm), and larger R gives finer resolution. With 5 mOhm and `MAX_CURRENT` 10 A the current register has a 0.3 mA step and the shunt register 0.5 mA per count. Power in the shunt `I^2 R` (10 A: 0.5 W) sets the resistor rating. Find the motors' real peak current first: log `%VW1022` for the base motor during tomorrow's session ([HARDWARE_TEST_PLAN.md](HARDWARE_TEST_PLAN.md)).

## Wiring (to be checked against the real drive wiring)
- Shunt in the **+24 V supply line** of each motor drive (high-side), IN+ on the supply side, IN- on the drive side; the bus-voltage pin reads the drive side. Never in the CAN or signal wiring. Fuse each supply.
- Both INA226 on the same I2C bus (GPIO21 SDA, GPIO22 SCL), addresses 0x40 and 0x41 (A0 tied to VS on the second). Short I2C leads (30 cm) away from the motor cables; the PWM-fed drives are electrically noisy.
- Power the ESP32 from USB or a separate 5 V; INA226 bus limit is 36 V (the 24 V supply is fine, a 36 V supply is not).
- Ground: do not tie the ESP32 USB ground to a mains-earthed PC and a non-isolated 24 V negative at the same time without checking: use the Wi-Fi/UDP output with the ESP32 on its own supply if the 24 V supply is not isolated.

## Build and flash
Arduino IDE or PlatformIO, board "ESP32 Dev Module", no extra libraries (only `Wire`, and `WiFi`/`WiFiUdp` if you define `WIFI_SSID`/`WIFI_PASS` and set `PC_IP`). Open the serial monitor at 921600 baud: the `H,` line must appear, then `S,` lines. Before connecting the motors, check with a known load (a power resistor and a bench supply, a multimeter in series) that the mA value is right.

## Tests (no hardware)
`tests/test_ina226.py`: the chip model against datasheet values (shunt, bus, current, calibration 3355, signed current, saturation, averaging window and step lag, registers held for a window); the **contract test** parses the constants out of the real `.ino` and checks the Python port uses the same, and checks the sketch text for the fixes above; the firmware loop (100 Hz cadence, parseable lines, header, missing-chip error line); the whole chain from the twin to the host (the calibration fit recovers the torque constant through the simulated logger within 10 %); the Hub integration.

## Limits of the simulation
It models the chip's registers, averaging window, quantisation and saturation, not I2C bus errors, bus-voltage drop across the shunt's wiring, temperature drift, or the electrical noise of PWM-fed drives. Reading the chip when a conversion finishes is modelled at the 0.5 ms level. The ESP32 timing (`millis()`, Wi-Fi jitter, packet loss) is not modelled beyond the 10 ms cadence; the host side already tolerates lost datagrams.
