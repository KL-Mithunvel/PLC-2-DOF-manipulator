"""Start the PLC + HMI + arm digital twin.

  python run_twin.py [--port 8765] [--no-browser] [--fresh]
  python run_twin.py --modbus-serve 1502            expose the twin's memory as a Modbus TCP server (reads only)
  python run_twin.py --plc 192.168.0.252[:502]      add the REAL PLC as a read-only live source ("plc", shown as the ghost arm)
  python run_twin.py --sensors udp:9100             add the motor current/voltage sensor feed (see docs/LIVE_DATA_PLAN.md)
"""
import argparse

from twin.server import run

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--host", default="127.0.0.1")
ap.add_argument("--port", type=int, default=8765)
ap.add_argument("--no-browser", action="store_true")
ap.add_argument("--fresh", action="store_true", help="ignore saved retentive data (taught points)")
ap.add_argument("--modbus-serve", type=int, metavar="PORT", help="serve the twin memory over Modbus TCP on this port")
ap.add_argument("--plc", metavar="HOST[:PORT]", help="read-only live feed from the real PLC")
ap.add_argument("--plc-hz", type=float, default=10.0)
ap.add_argument("--sensors", metavar="udp:PORT|serial:COMx[@baud]", help="motor current/voltage sensor input")
a = ap.parse_args()


def setup(hub):
    if a.modbus_serve:
        from twin.modbus_server import TwinModbusServer
        from live.modbus_map import ModbusMap
        srv = TwinModbusServer(hub.twin, ModbusMap.load(), port=a.modbus_serve).start()
        print(f"Modbus TCP server (read-only) on port {srv.port}")
    if a.plc:
        from live.plc_reader import PlcLiveSource
        host, _, port = a.plc.partition(":")
        src = PlcLiveSource(host, int(port or 502), hub.twin.cfg, hz=a.plc_hz).start()
        hub.register("plc", src)
        print(f"Reading PLC {host}:{port or 502} (read-only, {a.plc_hz:g} Hz)")
    if a.sensors:
        try:
            from live.sensors import SensorSource
        except ImportError:
            print("sensor support not available yet")
        else:
            hub.register("sensors", SensorSource.from_spec(a.sensors, hub.twin).start())


run(a.host, a.port, persist=not a.fresh, open_browser=not a.no_browser, hub_setup=setup)
