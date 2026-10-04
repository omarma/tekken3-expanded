/* test_apk_slice.c — the placeholder header parser of android_apk_file.c
 * (psx_apk_slice_parse), on the desktop. Built and run by test_apk_slice.py.
 *
 * Each header is put right before an unreadable page: the parser must stay
 * within the bytes it is given (a placeholder's header is read into a buffer
 * that is not NUL-terminated).
 */
#define _DEFAULT_SOURCE
#include "android_apk_file.h"

#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

static int g_failures;
static char* g_page_end;   /* the first unreadable byte */

#define FAIL(...) do { ++g_failures; fprintf(stderr, "FAIL: " __VA_ARGS__); fputc('\n', stderr); } while (0)

static int parse(const char* text, size_t size, char* apk, size_t apk_size,
                 uint64_t* offset, uint64_t* length, int* packed)
{
    char* header = g_page_end - size;
    memcpy(header, text, size);
    return psx_apk_slice_parse(header, size, apk, apk_size, offset, length, packed);
}

static void good(const char* text, uint64_t want_offset, uint64_t want_length, int want_packed,
                 const char* want_apk)
{
    char apk[256];
    uint64_t offset = 0, length = 0;
    int packed = -1;
    if (!parse(text, strlen(text), apk, sizeof(apk), &offset, &length, &packed)) {
        FAIL("refused: %s", text);
    } else if (offset != want_offset || length != want_length || packed != want_packed ||
               strcmp(apk, want_apk) != 0) {
        FAIL("wrong fields for: %s", text);
    }
}

static void bad(const char* text, size_t size)
{
    char apk[256];
    uint64_t offset, length;
    int packed;
    if (parse(text, size, apk, sizeof(apk), &offset, &length, &packed))
        FAIL("accepted: %.*s", (int)size, text);
}

int main(void)
{
    const long page = sysconf(_SC_PAGESIZE);
    char* map = mmap(NULL, (size_t)page * 3, PROT_READ | PROT_WRITE,
                     MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (map == MAP_FAILED || mprotect(map + 2 * page, (size_t)page, PROT_NONE) != 0) {
        perror("mmap");
        return 2;
    }
    g_page_end = map + 2 * page;

    good("psxrecomp-apk-slice\n4096 700000000\n/data/app/x/base.apk\n", 4096, 700000000, 0,
         "/data/app/x/base.apk");
    good("psxrecomp-apk-pack\n0 18446744073709551615\n/a.apk\nrest", 0, UINT64_MAX, 1, "/a.apk");

    /* Ends in the middle of a number: nothing after the header is read. */
    bad("psxrecomp-apk-slice\n1234", 24);
    bad("psxrecomp-apk-slice\n1234 5678", 29);
    bad("psxrecomp-apk-slice\n1 2\n/no/newline", 35);
    /* Signs, spaces, overflow, empty fields. */
    bad("psxrecomp-apk-slice\n-1 2\n/a\n", 28);
    bad("psxrecomp-apk-slice\n+1 2\n/a\n", 28);
    bad("psxrecomp-apk-slice\n 1 2\n/a\n", 28);
    bad("psxrecomp-apk-slice\n1  2\n/a\n", 28);
    bad("psxrecomp-apk-slice\n18446744073709551616 2\n/a\n", 46);
    bad("psxrecomp-apk-slice\n1 2\n\n", 25);
    bad("psxrecomp-apk-slice\n 2\n/a\n", 26);
    bad("psxrecomp-apk-slic\n1 2\n/a\n", 25);
    /* An APK path longer than the caller's buffer. */
    {
        char apk[8];
        uint64_t offset, length;
        int packed;
        const char* text = "psxrecomp-apk-slice\n1 2\n/a/long/path.apk\n";
        if (parse(text, strlen(text), apk, sizeof(apk), &offset, &length, &packed))
            FAIL("accepted a path longer than its buffer");
    }

    printf("%d failures\n", g_failures);
    return g_failures ? 1 : 0;
}
