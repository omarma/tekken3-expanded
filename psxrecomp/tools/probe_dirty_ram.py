import socket, json, time, sys

port = int(sys.argv[1]) if len(sys.argv) > 1 else 4470

def send_cmd(cmd, **kwargs):
    payload = {'id': 1, 'cmd': cmd}
    payload.update(kwargs)
    s = socket.create_connection(('127.0.0.1', port), timeout=3)
    s.sendall(json.dumps(payload).encode() + b'\n')
    data = b''
    while True:
        chunk = s.recv(4096)
        if not chunk:
            break
        data += chunk
        try:
            json.loads(data.decode())
            break
        except:
            pass
    s.close()
    return json.loads(data.decode())

# Wait for server
for i in range(15):
    try:
        r = send_cmd('ping')
        print(f'Connected. frame={r.get("frame")}, dispatch_miss_total={r.get("dispatch_miss_total")}')
        break
    except Exception as e:
        print(f'  waiting... ({e})')
        time.sleep(2)
else:
    print('Could not connect after 30s')
    sys.exit(1)

# Query dirty_ram stats
try:
    r = send_cmd('dirty_ram_stats')
    print('dirty_ram_stats:', json.dumps(r, indent=2))
except Exception as e:
    print(f'dirty_ram_stats failed: {e}')

# Also try heartbeat
try:
    r = send_cmd('heartbeat')
    print('heartbeat:', json.dumps(r, indent=2))
except Exception as e:
    print(f'heartbeat failed: {e}')
