import subprocess
import re

from pathlib import Path

relative_path = Path(__file__).parent.parents[1]
ADB_PATH = f"{str(relative_path)}\\adb-bin\\adb.exe"

def find_port_adb(target_ip):
    try:
        result = subprocess.run(
            [ADB_PATH, "mdns", "services"],
            capture_output=True,
            text=True,
            check=True
        )
    except FileNotFoundError:
        raise RuntimeError("adb.exe not found. Check ADB_PATH.")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"adb command failed: {e}")

    text = result.stdout
    if not text:
        return None

    matches = re.findall(
        r'((?:\d{1,3}\.){3}\d{1,3}):(\d{2,5})',
        text
    )

    for ip, port in matches:
        if ip == target_ip:
            return int(port)

    return None


# example usage
if __name__ == "__main__":
    ip = "192.168.31.34"
    try:
        port = find_port_adb(ip)
        print(port if port else "IP not found")
    except RuntimeError as err:
        print("Error:", err)
