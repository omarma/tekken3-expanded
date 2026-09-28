import json
d = json.load(open("dtail.json"))
a = {}
for x in d.get("addrs", []):
    a[x] = a.get(x, 0) + 1
for k, v in sorted(a.items(), key=lambda x: -x[1])[:30]:
    print(f"{k}: {v}x")
print(f"Total unique: {len(a)}")
print(f"Has 1FC3F4F0: {'0x1FC3F4F0' in a}")
