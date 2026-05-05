import serial
import time
import sys

PORT = '/dev/cu.SLAB_USBtoUART'
BAUD = 115200

def monitor():
    try:
        ser = serial.Serial(PORT, BAUD, timeout=1)
        print(f"已连接到 {PORT}，正在进入监听模式...")
        
        # Interrupt any running code and enter raw REPL
        ser.write(b'\r\x03\x03')
        time.sleep(0.5)
        ser.write(b'\x01') # Enter raw REPL
        time.sleep(0.1)
        
        code = """
from machine import Pin
import time
d = Pin(4, Pin.IN, Pin.PULL_DOWN)
u = Pin(14, Pin.IN, Pin.PULL_DOWN)

print("开始实时监控电平 (按 Ctrl+C 退出)...")
while True:
    print("楼下(GPIO 4): {}  |  楼上(GPIO 14): {}".format(d.value(), u.value()))
    time.sleep(0.5)
"""
        # Send the code
        ser.write(code.encode('utf-8') + b'\x04')
        
        # Read the output endlessly
        while True:
            if ser.in_waiting:
                data = ser.read(ser.in_waiting)
                text = data.decode(errors='ignore').replace('\r\n', '\n')
                sys.stdout.write(text)
                sys.stdout.flush()
            time.sleep(0.05)
            
    except KeyboardInterrupt:
        print("\n\n监控已手动停止。正在重启 ESP32 恢复正常程序...")
        ser.write(b'\x02') # Exit raw REPL
        ser.write(b'\x04') # Soft reset
        time.sleep(0.5)
        ser.close()
        sys.exit(0)
    except Exception as e:
        print(f"连接串口失败或发生错误: {e}")

if __name__ == '__main__':
    monitor()
