"""Enable LogToFile in duckstation settings.ini."""
import re, sys
p = sys.argv[1]
with open(p, 'r', encoding='utf-8') as f:
    s = f.read()
s = re.sub(r'LogToFile\s*=\s*false', 'LogToFile = true', s)
with open(p, 'w', encoding='utf-8') as f:
    f.write(s)
print('done')
