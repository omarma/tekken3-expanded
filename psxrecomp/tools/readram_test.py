import socket, json, sys

s = socket.socket(); s.connect(("127.0.0.1", 4370))
addr_str = sys.argv[1] if len(sys.argv) > 1 else "0x80007568"
req = {"id": 1, "cmd": "read_ram", "addr": addr_str, "len": 16}
line = json.dumps(req) + "\n"
print("SEND:", line.strip())
s.sendall(line.encode())
import time; time.sleep(0.3)
buf = s.recv(8192)
print("RECV:", buf.decode())
