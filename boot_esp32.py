# boot.py — WiFi + WebREPL startup
import esp
esp.osdebug(None)
import network
import time

SSID = "YOUR_WIFI_SSID"
PASSWORD = "YOUR_WIFI_PASSWORD"

wlan = network.WLAN(network.STA_IF)
wlan.active(False)
time.sleep(0.3)
wlan.active(True)
time.sleep(0.3)
wlan.config(pm=network.WLAN.PM_NONE)
wlan.connect(SSID, PASSWORD)

for i in range(30):
    if wlan.isconnected():
        break
    time.sleep(1)

try:
    import webrepl
    webrepl.start()
except Exception as e:
    print("WebREPL failed:", e)
