# main.py — ESP32 直控米家灯
# GPIO4=楼下, GPIO14=楼上 (NO型, HIGH=触发)
# 部署: esp32 put main_esp32.py /main.py

import gc
import network
import time
import machine
import usocket as socket
import uhashlib
from cryptolib import aes

try:
    import _webrepl
except ImportError:
    _webrepl = None

# ==================== 配置 ====================
SSID = "YOUR_WIFI_SSID"
PASSWORD = "YOUR_WIFI_PASSWORD"
LIGHT_IP = "192.168.x.x"
LIGHT_PORT = 54321
# !!! 从 xiaomi_light_control.py 确认的 token，旧版有错 !!!
LIGHT_TOKEN_HEX = "YOUR_DEVICE_TOKEN_HEX"

SENSOR_DOWN = 4
SENSOR_UP = 14
ON_BRIGHTNESS = 7
OFF_DELAY_SEC = 5
FORCE_OFF_SEC = 300
DEBOUNCE_MS = 200
LOOP_DELAY_MS = 100
UDP_TIMEOUT = 3
SEND_RETRIES = 2

# ==================== 工具函数 ====================

def log(msg):
    print("[%05d] %s" % (time.ticks_ms() // 1000, msg))

def hex2b(s):
    n = len(s)
    b = bytearray(n // 2)
    for i in range(0, n, 2):
        b[i // 2] = int(s[i:i+2], 16)
    return bytes(b)

def md5b(data):
    return uhashlib.md5(data).digest()

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

# ==================== miio 协议 ====================

def do_handshake():
    """发送 hello 握手包并获取设备 device_id 和 timestamp。
    返回 (device_id_bytes, device_ts)，失败返回 (None, None)。
    """
    # 标准 miIO hello 包：magic(2) + len(2) + 28字节 0xFF
    hello = b"\x21\x31\x00\x20" + b"\xff" * 28
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(1.0)
    for _ in range(3):
        try:
            s.sendto(hello, (LIGHT_IP, LIGHT_PORT))
            data, addr = s.recvfrom(1024)
            s.close()
            dev_id = data[8:12]
            dev_ts = int.from_bytes(data[12:16], 'big')
            log("Handshake OK: dev_id=%s ts=%d" % (''.join('%02x' % b for b in dev_id), dev_ts))
            return dev_id, dev_ts
        except OSError:
            pass
    s.close()
    return None, None


def build_miio_packet(payload_json, device_id, device_ts):
    """构建完整的 miIO 加密包。
    device_id: 握手获得的 4 字节设备 ID
    device_ts: 握手获得的设备内部 timestamp（秒），包头用 device_ts+1
    """
    gc.collect()
    token = hex2b(LIGHT_TOKEN_HEX)
    key = md5b(token)
    iv = md5b(key + token)

    plb = payload_json.encode()
    padded = pkcs7_pad(plb, 16)

    c = aes(key, 2, iv)  # MODE_CBC = 2
    encrypted = c.encrypt(padded)

    total_len = 32 + len(encrypted)
    stamp = device_ts + 1  # 设备时间 + 1 秒，不是 Unix 时间！

    header = bytearray(32)
    header[0] = 0x21
    header[1] = 0x31
    p16(header, 2, total_len)
    header[4:8] = b"\x00\x00\x00\x00"  # unknown
    header[8:12] = device_id           # 来自握手，不能为 0！
    p32(header, 12, stamp)             # 设备内部 timestamp + 1

    cksum = md5b(bytes(header[:16]) + token + encrypted)
    header[16:32] = cksum

    return bytes(header) + encrypted


def send_miio(siid, piid, value, mid, device_id, device_ts):
    """发送 miio set_properties 命令并等待响应。"""
    if isinstance(value, bool):
        vs = "true" if value else "false"
    elif isinstance(value, int):
        vs = str(value)
    else:
        vs = '"%s"' % str(value)

    js = '{"id":%d,"method":"set_properties","params":[{"siid":%d,"piid":%d,"value":%s}]}' % (mid, siid, piid, vs)

    try:
        packet = build_miio_packet(js, device_id, device_ts)
    except Exception as e:
        log("Build error: %s" % e)
        return False

    for _ in range(SEND_RETRIES):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(UDP_TIMEOUT)
        try:
            s.sendto(packet, (LIGHT_IP, LIGHT_PORT))
            try:
                s.recvfrom(1024)
            except OSError:
                pass
            s.close()
            return True
        except:
            pass
        finally:
            try:
                s.close()
            except:
                pass
        time.sleep_ms(500)
    return False


# ==================== 主程序 ====================

def main():
    from machine import Pin

    sensor_down = Pin(SENSOR_DOWN, Pin.IN, Pin.PULL_DOWN)
    sensor_up = Pin(SENSOR_UP, Pin.IN, Pin.PULL_DOWN)
    wdt = machine.WDT(timeout=90000)
    machine.freq(240000000)

    msg_id = 0
    light_on = False
    clear_since = 0
    on_since = 0
    wlan = None
    led = Pin(2, Pin.OUT)

    def connect_wifi():
        nonlocal wlan
        wlan = network.WLAN(network.STA_IF)
        if wlan.isconnected():
            log("WiFi OK %s RSSI=%s" % (wlan.ifconfig()[0], wlan.status('rssi')))
            return True
        wlan.active(False)
        time.sleep_ms(300)
        wlan.active(True)
        time.sleep_ms(300)
        wlan.config(pm=network.WLAN.PM_NONE)
        wlan.connect(SSID, PASSWORD)
        for i in range(30):
            wdt.feed()
            if wlan.isconnected():
                log("WiFi OK %s RSSI=%s" % (wlan.ifconfig()[0], wlan.status('rssi')))
                return True
            time.sleep(1)
        return False

    def read_sensors():
        d1 = sensor_down.value()
        u1 = sensor_up.value()
        time.sleep_ms(DEBOUNCE_MS)
        d2 = sensor_down.value()
        u2 = sensor_up.value()
        return (d1 if d1 == d2 else sensor_down.value(),
                u1 if u1 == u2 else sensor_up.value())

    def light_on_cmd():
        """做一次握手，然后开灯 + 调亮度。
        两次命令使用同一个握手值（200ms 内设备时间变化极小）。
        """
        nonlocal msg_id
        dev_id, dev_ts = do_handshake()
        if dev_id is None:
            return False
        msg_id += 1
        ok = send_miio(2, 1, True, msg_id, dev_id, dev_ts)
        if ok:
            time.sleep_ms(200)
            msg_id += 1
            send_miio(2, 2, ON_BRIGHTNESS, msg_id, dev_id, dev_ts)
        return ok

    def light_off_cmd():
        nonlocal msg_id
        dev_id, dev_ts = do_handshake()
        if dev_id is None:
            return False
        msg_id += 1
        return send_miio(2, 1, False, msg_id, dev_id, dev_ts)

    log("=== SensorLight v7 ===")
    log("Sensors: D=%d U=%d  Light: %s:%d" % (SENSOR_DOWN, SENSOR_UP, LIGHT_IP, LIGHT_PORT))

    for attempt in range(5):
        wdt.feed()
        if connect_wifi():
            break
        log("WiFi attempt %d failed, retry..." % (attempt + 1))
        time.sleep(3)
    else:
        log("WiFi failed after 5 attempts, resetting")
        time.sleep(3)
        machine.reset()

    dev_id, dev_ts = do_handshake()
    if dev_id is None:
        log("Light not reachable, will retry on trigger")
    else:
        log("Light reachable: dev_id=%s ts=%d" % (''.join('%02x' % b for b in dev_id), dev_ts))

    led.on()
    time.sleep_ms(200)
    led.off()

    log("Monitoring...")

    while True:
        wdt.feed()

        if wlan is None or not wlan.isconnected():
            log("WiFi lost")
            for attempt in range(10):
                wdt.feed()
                if connect_wifi():
                    log("WiFi reconnected")
                    break
                log("WiFi retry %d..." % (attempt + 1))
                time.sleep(5)
            else:
                log("WiFi lost, resetting")
                time.sleep(3)
                machine.reset()

        try:
            down, up = read_sensors()
        except Exception:
            down, up = 0, 0

        triggered = down or up
        both_clear = not down and not up
        now = time.ticks_ms()

        if not light_on:
            if triggered:
                log("Trig! D=%d U=%d" % (down, up))
                ok = light_on_cmd()
                if ok:
                    light_on = True
                    on_since = now
                    clear_since = 0
                    led.value(1)
                else:
                    log("Light ON failed, will retry next loop")
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
                        led.off()

            if light_on and elapsed >= FORCE_OFF_SEC:
                log("Force OFF (%ds)" % elapsed)
                light_off_cmd()
                light_on = False
                clear_since = 0
                on_since = 0
                led.off()

        if _webrepl:
            try:
                _webrepl._webrepl()
            except Exception:
                pass
        gc.collect()
        time.sleep_ms(LOOP_DELAY_MS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Interrupted, back to REPL")
    except Exception as e:
        log("CRASH: %s" % e)
        time.sleep(3)
        machine.reset()
