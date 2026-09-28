#!/usr/bin/env python3
import json, sys
path = sys.argv[1] if len(sys.argv) > 1 else '/tmp/wtrace_xpress.json'
data = json.load(open(path))
entries = data.get('entries', [])
print("Total:", len(entries))
for e in entries[:50]:
    print("  f=%s %s %s->%s func=%s ra=%s" % (e['frame'], e['addr'], e['old'], e['new'], e['func'], e['ra']))
