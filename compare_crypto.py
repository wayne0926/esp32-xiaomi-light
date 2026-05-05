import hashlib
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import json

LIGHT_TOKEN_HEX = "YOUR_DEVICE_TOKEN_HEX"

def hex2b(s):
    n = len(s)
    b = bytearray(n // 2)
    for i in range(0, n, 2):
        b[i // 2] = int(s[i:i+2], 16)
    return bytes(b)

def md5b(data):
    return hashlib.md5(data).digest()

def pkcs7_pad(data, bs=16):
    pad_len = bs - len(data) % bs
    return data + bytes([pad_len]) * pad_len

def build_esp32_payload(payload_json):
    token = hex2b(LIGHT_TOKEN_HEX)
    key = md5b(token)
    iv = md5b(key + token)

    plb = payload_json.encode() + b"\x00"
    padded = pkcs7_pad(plb, 16)

    c = AES.new(key, AES.MODE_CBC, iv)
    encrypted = c.encrypt(padded)
    return encrypted

# Now using python-miio internals
from miio.miioprotocol import MiIOProtocol
import binascii

p = MiIOProtocol("192.168.x.x", LIGHT_TOKEN_HEX)

# The payload
js = '{"id":1,"method":"set_properties","params":[{"siid":2,"piid":1,"value":true}]}'
# python-miio's json construction:
payload_bytes = js.encode("utf-8") + b"\x00"

print("ESP32 encrypt:    ", build_esp32_payload(js).hex())
# Need to see if python-miio has access to encryption, usually it's in p._device._crypto or something
# We can just check the library's cryptography usage
