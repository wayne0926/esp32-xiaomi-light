"""Deploy boot_esp32.py and main_esp32.py to ESP32 via serial raw REPL.

Usage:
    python deploy_serial.py [port]

Deploys both files, verifies MD5 checksums, and reboots only if verified.
"""
import serial
import time
import sys
import os
import hashlib
import base64

PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/cu.SLAB_USBtoUART"
BAUD = 115200

# Files to deploy: (local_path, remote_path)
BASE = os.path.dirname(os.path.abspath(__file__))
DEPLOY_FILES = [
    (os.path.join(BASE, "boot_esp32.py"), "/boot.py"),
    (os.path.join(BASE, "main_esp32.py"), "/main.py"),
]

CTRL_A = b"\x01"
CTRL_B = b"\x02"
CTRL_C = b"\x03"
CTRL_D = b"\x04"


def read_until(ser, marker, timeout=5):
    """Read serial until marker found or timeout."""
    buf = b""
    deadline = time.time() + timeout
    while time.time() < deadline:
        ser.timeout = max(0.05, deadline - time.time())
        chunk = ser.read(256)
        if chunk:
            buf += chunk
            if marker in buf:
                return buf
    return buf


def drain(ser, timeout=0.3):
    """Drain all pending serial data."""
    ser.timeout = timeout
    while True:
        b = ser.read(1024)
        if not b:
            break


def raw_exec(ser, code, timeout=8):
    """Execute code in raw REPL mode, return output string."""
    # Enter raw REPL
    drain(ser)
    ser.write(CTRL_A)
    time.sleep(0.1)
    resp = read_until(ser, b"raw REPL; CTRL-B to exit\r\n>", timeout=2)
    if b"raw REPL" not in resp and b">" not in resp:
        # Try again
        ser.write(CTRL_A)
        time.sleep(0.1)
        drain(ser)

    # Send code
    code_bytes = code.encode() if isinstance(code, str) else code
    # Send in small chunks to avoid serial buffer overflow
    SEND_CHUNK = 256
    for i in range(0, len(code_bytes), SEND_CHUNK):
        ser.write(code_bytes[i:i+SEND_CHUNK])
        time.sleep(0.02)

    # Execute with Ctrl+D
    ser.write(CTRL_D)

    # Read output: format is "OK<stdout>\x04<stderr>\x04>"
    out = read_until(ser, b"\x04>", timeout=timeout)

    # Parse output
    if b"OK" in out:
        out = out.split(b"OK", 1)[1]
    # Split stdout and stderr at \x04
    parts = out.split(b"\x04")
    stdout = parts[0] if len(parts) > 0 else b""
    stderr = parts[1] if len(parts) > 1 else b""

    stderr_str = stderr.strip().decode(errors="replace")
    if stderr_str and stderr_str != ">":
        stderr_clean = stderr_str.rstrip(">").strip()
        if stderr_clean:
            raise RuntimeError("MicroPython error: %s" % stderr_clean)

    return stdout.strip().decode(errors="replace")


def md5_local(filepath):
    """Compute MD5 hex digest of a local file."""
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(4096)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def interrupt_and_get_repl(ser):
    """Interrupt running code and get to REPL prompt."""
    print("Interrupting device...")
    # Send Ctrl+C repeatedly to break out of any running code
    for _ in range(5):
        ser.write(CTRL_C)
        time.sleep(0.2)
    drain(ser)

    # Exit raw REPL if we're in one
    ser.write(CTRL_B)
    time.sleep(0.1)
    drain(ser)

    # Check for REPL prompt
    ser.write(b"\r\n")
    time.sleep(0.3)
    prompt = read_until(ser, b">>>", timeout=2)

    if b">>>" not in prompt:
        print("No REPL prompt. Trying hardware reset + Ctrl+C...")
        # Hardware reset via DTR/RTS
        ser.dtr = False
        ser.rts = True
        time.sleep(0.1)
        ser.dtr = True
        ser.rts = False
        time.sleep(0.1)
        ser.dtr = False

        # Spam Ctrl+C to catch boot.py/main.py
        for _ in range(40):
            ser.write(CTRL_C)
            time.sleep(0.15)

        drain(ser)
        ser.write(b"\r\n")
        time.sleep(0.5)
        prompt = read_until(ser, b">>>", timeout=3)

        if b">>>" not in prompt:
            print("ERROR: Cannot get REPL prompt. Check connection.")
            return False

    print("REPL ready.")
    return True


def upload_file(ser, local_path, remote_path):
    """Upload a file to ESP32 via raw REPL with base64 chunks."""
    with open(local_path, "rb") as f:
        content = f.read()

    local_size = len(content)
    local_md5 = md5_local(local_path)
    basename = os.path.basename(local_path)
    print("\nUploading %s → %s (%d bytes, md5=%s)" % (basename, remote_path, local_size, local_md5[:8]))

    # Delete old file first (ignore errors if not exist)
    try:
        raw_exec(ser, "import os\ntry:\n os.remove('%s')\nexcept:\n pass" % remote_path)
    except RuntimeError:
        pass

    # Create empty file
    raw_exec(ser, "f=open('%s','wb')\nf.close()" % remote_path)

    # Upload in chunks via base64
    CHUNK = 192  # bytes per chunk → 256 base64 chars
    total_chunks = (local_size + CHUNK - 1) // CHUNK
    written = 0

    for i in range(0, local_size, CHUNK):
        chunk = content[i:i+CHUNK]
        b64 = base64.b64encode(chunk).decode()
        code = "import ubinascii\nf=open('%s','ab')\nf.write(ubinascii.a2b_base64('%s'))\nf.close()" % (remote_path, b64)
        try:
            raw_exec(ser, code)
            written += len(chunk)
            chunk_num = i // CHUNK + 1
            pct = written * 100 // local_size
            print("\r  [%3d%%] chunk %d/%d (%d/%d bytes)" % (pct, chunk_num, total_chunks, written, local_size), end="", flush=True)
        except RuntimeError as e:
            print("\nERROR at chunk %d: %s" % (i // CHUNK + 1, e))
            return False

    print()  # newline after progress

    # Verify size
    result = raw_exec(ser, "import os\nprint(os.stat('%s')[6])" % remote_path)
    try:
        remote_size = int(result.strip())
    except ValueError:
        print("ERROR: Cannot read remote file size (got: %r)" % result)
        return False

    if remote_size != local_size:
        print("ERROR: Size mismatch! local=%d remote=%d" % (local_size, remote_size))
        return False
    print("  Size OK: %d bytes" % remote_size)

    # Verify MD5
    md5_code = (
        "import uhashlib\n"
        "h=uhashlib.md5()\n"
        "f=open('%s','rb')\n"
        "while True:\n"
        " d=f.read(512)\n"
        " if not d:\n"
        "  break\n"
        " h.update(d)\n"
        "f.close()\n"
        "d=h.digest()\n"
        "print(''.join('%%02x'%%b for b in d))"
    ) % remote_path
    result = raw_exec(ser, md5_code, timeout=10)
    remote_md5 = result.strip()

    if remote_md5 != local_md5:
        print("ERROR: MD5 mismatch! local=%s remote=%s" % (local_md5, remote_md5))
        return False
    print("  MD5 OK: %s" % remote_md5)

    return True


def main():
    # Verify local files exist
    for local_path, remote_path in DEPLOY_FILES:
        if not os.path.isfile(local_path):
            print("ERROR: Local file not found: %s" % local_path)
            sys.exit(1)

    print("=" * 50)
    print("ESP32 Deployment Tool")
    print("=" * 50)
    print("Port: %s @ %d baud" % (PORT, BAUD))
    for local_path, remote_path in DEPLOY_FILES:
        print("  %s → %s (%d bytes)" % (os.path.basename(local_path), remote_path, os.path.getsize(local_path)))
    print()

    ser = serial.Serial(PORT, BAUD, timeout=1)

    if not interrupt_and_get_repl(ser):
        ser.close()
        sys.exit(1)

    # Deploy each file
    all_ok = True
    for local_path, remote_path in DEPLOY_FILES:
        if not upload_file(ser, local_path, remote_path):
            all_ok = False
            break

    if not all_ok:
        print("\n!!! DEPLOYMENT FAILED - device NOT rebooted !!!")
        ser.close()
        sys.exit(1)

    # List final filesystem
    print("\nDevice filesystem:")
    result = raw_exec(ser, "import os\nfor f in os.listdir('/'):\n print(' ',f)")
    print(result)

    # Reboot
    print("\nAll verified. Rebooting...")
    ser.write(b"import machine\r\nmachine.reset()\r\n")
    time.sleep(0.5)

    # Monitor boot output for 15 seconds
    print("\n--- Boot output (15s) ---")
    deadline = time.time() + 15
    ser.timeout = 0.1
    while time.time() < deadline:
        data = ser.read(512)
        if data:
            try:
                text = data.decode(errors="replace")
                print(text, end="", flush=True)
            except:
                pass

    print("\n--- End of boot monitor ---")
    ser.close()
    print("\nDone!")


if __name__ == "__main__":
    main()
