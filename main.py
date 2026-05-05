import network, time, machine

SSID = "YOUR_WIFI_SSID"
PASSWORD = "YOUR_WIFI_PASSWORD"

wlan = network.WLAN(network.STA_IF)
wlan.active(False)
time.sleep(0.3)
wlan.active(True)
time.sleep(0.3)
wlan.config(pm=network.WLAN.PM_NONE)
machine.freq(240000000)

print("Connecting to", SSID)
wlan.connect(SSID, PASSWORD)
for _ in range(20):
    if wlan.isconnected():
        break
    time.sleep(1)

if wlan.isconnected():
    print("✓ ESP32 online -", wlan.ifconfig()[0])
    print("  RSSI:", wlan.status('rssi'), "dBm")
    print("  USB:", "NOT connected" if len([p for p in (__import__('os').listdir('/')) if p == 'usb']) == 0 else "connected")
else:
    print("✗ WiFi failed")
