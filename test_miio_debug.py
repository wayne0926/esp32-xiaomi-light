import logging
from miio import MiotDevice
logging.basicConfig(level=logging.DEBUG)
device = MiotDevice("192.168.x.x", "YOUR_DEVICE_TOKEN_HEX")
device.send("set_properties", [{"siid": 2, "piid": 1, "value": True}])
