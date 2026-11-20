"""Start the PLC + HMI + arm digital twin.

  python run_twin.py [--port 8765] [--no-browser] [--fresh]
  python run_twin.py --demo                         showcase: loops the auto cycle by itself, no hardware
  python run_twin.py --modbus-serve 1502            expose the twin's memory as a Modbus TCP server (reads only)
  python run_twin.py --plc 192.168.0.252[:502]      add the REAL PLC as a read-only live source ("plc", shown as the ghost arm)
  python run_twin.py --hmi-vnc 192.168.0.253[:5900]   show the REAL HMI (view-only VNC) next to the replica; password via HMI_VNC_PASSWORD
  python run_twin.py --mocap 0 --mocap-calib mocap/camera.json   camera tracking of the AprilTags (docs/MOCAP_PLAN.md)
  python run_twin.py --sensors udp:9100             add the motor current/voltage sensor feed (see docs/LIVE_DATA_PLAN.md)
"""
import argparse
import os

from twin.server import run

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--host", default="127.0.0.1")
ap.add_argument("--port", type=int, default=8765)
ap.add_argument("--demo", action="store_true", help="showcase mode: the page runs the 3-cycle program in a loop by itself (no hardware needed)")
ap.add_argument("--no-browser", action="store_true")
ap.add_argument("--fresh", action="store_true", help="ignore saved retentive data (taught points)")
ap.add_argument("--modbus-serve", type=int, metavar="PORT", help="serve the twin memory over Modbus TCP on this port")
ap.add_argument("--plc", metavar="HOST[:PORT]", help="read-only live feed from the real PLC")
ap.add_argument("--plc-hz", type=float, default=10.0)
ap.add_argument("--hmi-vnc", metavar="HOST[:PORT]", help="view-only VNC grab of the real HMI panel, shown in the GUI")
ap.add_argument("--hmi-vnc-password", default=os.environ.get("HMI_VNC_PASSWORD"), help="VNC password (default: env HMI_VNC_PASSWORD)")
ap.add_argument("--mocap", metavar="CAM_INDEX|VIDEO", help="motion capture from a camera index or video file (needs --mocap-calib)")
ap.add_argument("--mocap-calib", default="mocap/camera.json", help="camera calibration json from python -m mocap.calibrate")
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
    if a.hmi_vnc:
        from live.hmi_vnc import HmiVnc
        host, _, port = a.hmi_vnc.partition(":")
        hub.hmi_vnc = HmiVnc(host, int(port or 5900), a.hmi_vnc_password).start()
        print(f"Real HMI view (VNC, view only) from {host}:{port or 5900}")
    if a.mocap:
        from mocap.source import MocapSource
        from mocap.tracker import Camera
        hub.register("mocap", MocapSource.from_spec(a.mocap, Camera.load(a.mocap_calib), hub.twin.cfg).start())
        print(f"Motion capture from {a.mocap}")
    if a.sensors:
        try:
            from live.sensors import SensorSource
        except ImportError:
            print("sensor support not available yet")
        else:
            hub.register("sensors", SensorSource.from_spec(a.sensors, hub.twin).start())


run(a.host, a.port, persist=not a.fresh, open_browser=not a.no_browser, hub_setup=setup, query="?demo=1" if a.demo else "")
