# sensor_light.py — ESP32 直控米家灯 (miio protocol)
# GPIO4=楼下, GPIO14=楼上 (NO型, HIGH=触发)
# 零桥接 — ESP32 → UDP → Light

import gc
import network
import time
import machine
from machine import Pin
import usocket as socket

# ==================== 配置 ====================
SSID = "YOUR_WIFI_SSID"
PASSWORD = "YOUR_WIFI_PASSWORD"

LIGHT_IP = "192.168.x.x"
LIGHT_PORT = 54321
LIGHT_TOKEN_HEX = "YOUR_DEVICE_TOKEN_HEX"

SENSOR_DOWN = 4
SENSOR_UP = 14
ON_BRIGHTNESS = 7       # 0-100
OFF_DELAY_SEC = 5       # 两传感器同时 LOW N 秒后关灯
FORCE_OFF_SEC = 300     # 安全兜底超时
DEBOUNCE_MS = 200
LOOP_DELAY_MS = 100
UDP_TIMEOUT = 3
SEND_RETRIES = 2

# ==================== 全局状态 ====================
light_on = False
clear_since = 0
on_since = 0
wlan = None
msg_id = 0

# ==================== 硬件 ====================
sensor_down = Pin(SENSOR_DOWN, Pin.IN, Pin.PULL_DOWN)
sensor_up = Pin(SENSOR_UP, Pin.IN, Pin.PULL_DOWN)
wdt = machine.WDT(timeout=90000)
machine.freq(240000000)


def log(msg):
    t = time.ticks_ms() // 1000
    print(f"[{t:05d}] {msg}")


# ==================== WiFi ====================

def connect_wifi():
    global wlan
    wlan = network.WLAN(network.STA_IF)
    wlan.active(False)
    time.sleep(0.3)
    wlan.active(True)
    time.sleep(0.3)
    wlan.config(pm=network.WLAN.PM_NONE)
    wlan.connect(SSID, PASSWORD)
    for i in range(30):
        if wlan.isconnected():
            log(f"WiFi OK {wlan.ifconfig()[0]} RSSI={wlan.status('rssi')}")
            return True
        time.sleep(1)
    log("WiFi FAILED")
    return False


# ==================== 工具函数 ====================

def hex2b(s):
    n = len(s)
    b = bytearray(n // 2)
    for i in range(0, n, 2):
        b[i // 2] = int(s[i:i+2], 16)
    return bytes(b)


def md5b(data):
    import uhashlib
    return uhashlib.md5(data).digest()


def aes_cbc_enc(key, iv, data):
    from cryptolib import aes
    c = aes(key, 2, iv)
    return c.encrypt(data)


def pkcs7_pad(data, bs=16):
    pad = bs - len(data) % bs
    return data + bytes([pad]) * pad


def p16(buf, off, val):
    buf[off] = (val >> 8) & 0xFF
    buf[off + 1] = val & 0xFF


def p32(buf, off, val):
    buf[off] = (val >> 24) & 0xFF
    buf[off + 1] = (val >> 16) & 0xFF
    buf[off + 2] = (val >> 8) & 0xFF
    buf[off + 3] = val & 0xFF


# ==================== miio ====================

def build_miio_packet(payload_json):
    gc.collect()
    token = hex2b(LIGHT_TOKEN_HEX)
    key = md5b(token)
    iv = md5b(key + token)

    plb = payload_json.encode() + b"\x00"
    padded = pkcs7_pad(plb, 16)
    encrypted = aes_cbc_enc(key, iv, padded)

    total_len = 32 + len(encrypted)
    stamp = int(time.time())

    header = bytearray(32)
    header[0] = 0x21
    header[1] = 0x31
    p16(header, 2, total_len)
    p32(header, 12, stamp)

    cksum = md5b(bytes(header[:16]) + token + encrypted)
    header[16:32] = cksum

    return bytes(header) + encrypted


def send_miio(siid, piid, value):
    global msg_id
    msg_id += 1

    if isinstance(value, bool):
        vs = "true" if value else "false"
    elif isinstance(value, int):
        vs = str(value)
    else:
        vs = '"%s"' % str(value)

    js = '{"id":%d,"method":"set_properties","params":[{"siid":%d,"piid":%d,"value":%s}]}' % (msg_id, siid, piid, vs)

    try:
        packet = build_miio_packet(js)
    except Exception as e:
        log("build err: %s" % e)
        return False

    for attempt in range(SEND_RETRIES):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(UDP_TIMEOUT)
            s.sendto(packet, (LIGHT_IP, LIGHT_PORT))
            try:
                s.recvfrom(1024)
            except OSError:
                pass
            s.close()
            return True
        except Exception as e:
            log("udp err: %s" % e)
            try:
                s.close()
            except:
                pass
        if attempt < SEND_RETRIES - 1:
            time.sleep_ms(500)

    return False


# ==================== 灯光控制 ====================

def light_on_cmd():
    ok = send_miio(2, 1, True)
    if ok:
        time.sleep_ms(200)
        send_miio(2, 2, ON_BRIGHTNESS)
    return ok


def light_off_cmd():
    return send_miio(2, 1, False)


# ==================== 传感器 ====================

def read_sensors():
    d1 = sensor_down.value()
    u1 = sensor_up.value()
    time.sleep_ms(DEBOUNCE_MS)
    d2 = sensor_down.value()
    u2 = sensor_up.value()
    return (d1 if d1 == d2 else sensor_down.value(),
            u1 if u1 == u2 else sensor_up.value())


# ==================== 主循环 ====================

def main():
    global light_on, clear_since, on_since

    log("=== SensorLight v2 (miio direct) ===")
    log("Sensors: D=%d U=%d  Light: %s:%d" % (SENSOR_DOWN, SENSOR_UP, LIGHT_IP, LIGHT_PORT))

    if not connect_wifi():
        machine.reset()

    log("Ready. Monitoring...")

    while True:
        wdt.feed()

        if wlan is None or not wlan.isconnected():
            log("WiFi lost")
            if not connect_wifi():
                time.sleep(5)
                machine.reset()

        try:
            down, up = read_sensors()
        except:
            down, up = 0, 0

        triggered = down or up
        both_clear = not down and not up
        now = time.ticks_ms()

        if not light_on:
            if triggered:
                log("Trig! D=%d U=%d" % (down, up))
                if light_on_cmd():
                    light_on = True
                    on_since = now
                    clear_since = 0
                    log("ON")
        else:
            elapsed = time.ticks_diff(now, on_since) // 1000

            if triggered:
                clear_since = 0
            elif both_clear:
                if clear_since == 0:
                    clear_since = now
                else:
                    cleared = time.ticks_diff(now, clear_since) // 1000
                    if cleared >= OFF_DELAY_SEC:
                        log("Clear %ds -> OFF" % cleared)
                        light_off_cmd()
                        light_on = False
                        clear_since = 0
                        on_since = 0

            if light_on and elapsed >= FORCE_OFF_SEC:
                log("Force OFF (%ds)" % elapsed)
                light_off_cmd()
                light_on = False
                clear_since = 0
                on_since = 0

        gc.collect()
        time.sleep_ms(LOOP_DELAY_MS)


if __name__ == "__main__":
    while True:
        try:
            main()
        except Exception as e:
            log("CRASH: %s" % e)
            time.sleep(3)
            machine.reset()
