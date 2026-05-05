from miio.miioprotocol import MiIOProtocol
import hashlib
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

LIGHT_TOKEN_HEX = "YOUR_DEVICE_TOKEN_HEX"
token = bytes.fromhex(LIGHT_TOKEN_HEX)
key = hashlib.md5(token).digest()
iv = hashlib.md5(key + token).digest()

payload = b'{"id":1,"method":"set_properties","params":[{"siid":2,"piid":1,"value":true}]}\x00'
padded = pad(payload, 16)
cipher = AES.new(key, AES.MODE_CBC, iv)
encrypted = cipher.encrypt(padded)

dev_id = bytes.fromhex("1b785c86")
dev_ts = 15704854
stamp = dev_ts + 1

header = bytearray(32)
header[0] = 0x21
header[1] = 0x31
total_len = 32 + len(encrypted)
header[2] = (total_len >> 8) & 0xFF
header[3] = total_len & 0xFF
header[8:12] = dev_id
header[12] = (stamp >> 24) & 0xFF
header[13] = (stamp >> 16) & 0xFF
header[14] = (stamp >> 8) & 0xFF
header[15] = stamp & 0xFF

cksum = hashlib.md5(header[:16] + token + encrypted).digest()
header[16:32] = cksum

packet = bytes(header) + encrypted

print("My packet: ", packet.hex())

# Let's use miio to generate
from miio.utils import int_to_bytes
p = MiIOProtocol("192.168.x.x", LIGHT_TOKEN_HEX)
# Need a way to construct the raw message...
