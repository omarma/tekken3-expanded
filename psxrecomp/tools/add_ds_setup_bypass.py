"""Mark DuckStation's setup wizard as completed so -nogui -bios can run headless."""
import sys
p = sys.argv[1]
with open(p, 'r', encoding='utf-8') as f:
    s = f.read()
# Inject into [Main] section
if "SettingsVersion" not in s:
    s = s.replace("[Main]\n", "[Main]\nSettingsVersion = 3\nSetupWizardIncomplete = false\n", 1)
with open(p, 'w', encoding='utf-8') as f:
    f.write(s)
print('OK')
