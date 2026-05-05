# miio_test.py - Quick miio protocol test for ESP32
import usocket, time, uhashlib
from cryptolib import aes

TOKEN = bytes.fromhex("YOUR_DEVICE_TOKEN_HEX")
LIGHT_IP = "192.168.x.x"
LIGHT_PORT = 54321

def md5(data):
    return uhashlib.md5(data).digest()

key = md5(TOKEN)
iv = md5(key + TOKEN)

# JSON + trailing \x00 (matches python-miio behavior)
payload = '{"id":1,"method":"get_properties","params":[{"siid":2,"piid":1}]}'
payload_b = payload.encode() + b"\x00"

# PKCS7 pad
pad = 16 - len(payload_b) % 16
padded = payload_b + bytes([pad]) * pad

c = aes(key, 2, iv)
encrypted = c.encrypt(padded)

total_len = 32 + len(encrypted)
stamp = int(time.time())

header = bytearray(32)
header[0] = 0x21
header[1] = 0x31
header[2] = (total_len >> 8) & 0xFF
header[3] = total_len & 0xFF
# unknown=0, dev_id=0, bytes 4-11 already zero
header[12] = (stamp >> 24) & 0xFF
header[13] = (stamp >> 16) & 0xFF
header[14] = (stamp >> 8) & 0xFF
header[15] = stamp & 0xFF

# Checksum: MD5(header[0:16] + token + encrypted)
cksum = md5(bytes(header[:16]) + TOKEN + encrypted)
header[16:32] = cksum

packet = bytes(header) + encrypted
print("Packet size:", len(packet))

s = usocket.socket(usocket.AF_INET, usocket.SOCK_DGRAM)
s.settimeout(3)
s.sendto(packet, (LIGHT_IP, LIGHT_PORT))
try:
    resp, addr = s.recvfrom(1024)
    print("Response:", len(resp), "bytes from", addr)
    print("Hex:", resp[:80].hex())
except OSError as e:
    print("No response:", e)
s.close()
