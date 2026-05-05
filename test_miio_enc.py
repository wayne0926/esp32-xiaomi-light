from miio.miioprotocol import MiIOProtocol
p = MiIOProtocol("192.168.x.x", "YOUR_DEVICE_TOKEN_HEX")
print("Key:", p.key.hex())
print("IV:", p.iv.hex())
js = '{"id":1,"method":"set_properties","params":[{"siid":2,"piid":1,"value":true}]}'
print("Plaintext padded:", p._encrypt(js.encode()).hex())
