/* Tekken 3 Expanded.exe: the double-click way to play on Windows. The setup
 * builds it (CMake target tekken3-play) and copies it beside Setup Tekken 3.cmd.
 * It does what the .cmd does once setup is done, without a console window:
 * start launcher/easy_launcher.py with the setup's Python, which opens the game,
 * or the setup window when an update needs it. --settings is passed on. */
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#include <windows.h>
#include <wchar.h>

/* WinMain rather than wWinMain: MinGW needs -municode for the latter. */
int WINAPI WinMain(HINSTANCE instance, HINSTANCE previous, LPSTR arguments, int show) {
    (void)instance; (void)previous; (void)arguments; (void)show;
    static wchar_t root[32768], python[32768], script[32768], command[32768];
    if (!GetModuleFileNameW(NULL, root, 32768)) return 1;
    wchar_t *slash = wcsrchr(root, L'\\');
    if (!slash) return 1;
    *slash = 0;
    if (wcslen(root) > 15000) return 1;
    swprintf(python, 32768, L"%ls\\.setup\\venv\\Scripts\\pythonw.exe", root);
    swprintf(script, 32768, L"%ls\\launcher\\easy_launcher.py", root);
    if (GetFileAttributesW(python) == INVALID_FILE_ATTRIBUTES || GetFileAttributesW(script) == INVALID_FILE_ATTRIBUTES) {
        MessageBoxW(NULL, L"The setup's files are missing from this folder. Run Setup Tekken 3.cmd once, then use Tekken 3 Expanded again.",
                    L"Tekken 3 Expanded", MB_OK | MB_ICONINFORMATION);
        return 1;
    }
    const wchar_t *option = wcsstr(GetCommandLineW(), L"--settings") ? L" --settings" : L"";
    swprintf(command, 32768, L"\"%ls\" \"%ls\"%ls", python, script, option);
    STARTUPINFOW startup = {0};
    PROCESS_INFORMATION process = {0};
    startup.cb = sizeof(startup);
    if (!CreateProcessW(python, command, NULL, NULL, FALSE, 0, NULL, root, &startup, &process)) {
        MessageBoxW(NULL, L"Tekken 3 Expanded could not start. Run Setup Tekken 3.cmd instead.",
                    L"Tekken 3 Expanded", MB_OK | MB_ICONERROR);
        return 1;
    }
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    return 0;
}
