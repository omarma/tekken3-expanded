#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#include <windows.h>
#include <wchar.h>

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR arguments, int show) {
    (void)instance; (void)previous; (void)show;
    wchar_t root[32768], python[32768], script[32768], command[32768];
    if (!GetModuleFileNameW(NULL, root, 32768)) return 1;
    wchar_t *slash = wcsrchr(root, L'\\');
    if (!slash) return 1;
    *slash = 0;
    if (wcslen(root) > 15000) return 1;
    swprintf(python, 32768, L"%ls\\.runtime\\python\\pythonw.exe", root);
    swprintf(script, 32768, L"%ls\\launcher\\easy_launcher.py", root);
    if (GetFileAttributesW(python) == INVALID_FILE_ATTRIBUTES || GetFileAttributesW(script) == INVALID_FILE_ATTRIBUTES) {
        MessageBoxW(NULL, L"Extract the entire download first, then open Play Tekken 3.exe from that folder.", L"Tekken 3", MB_OK | MB_ICONINFORMATION);
        return 1;
    }
    const wchar_t *option = wcsstr(arguments, L"--settings") ? L" --settings" : L"";
    swprintf(command, 32768, L"\"%ls\" -I \"%ls\"%ls", python, script, option);
    STARTUPINFOW startup = {0};
    PROCESS_INFORMATION process = {0};
    startup.cb = sizeof(startup);
    if (!CreateProcessW(python, command, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, root, &startup, &process)) {
        MessageBoxW(NULL, L"The launcher could not start. Extract the ZIP again into a writable folder.", L"Tekken 3", MB_OK | MB_ICONERROR);
        return 1;
    }
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    return 0;
}
