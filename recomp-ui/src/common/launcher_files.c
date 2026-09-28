// launcher_files.c — native file/folder pickers.
//
// Windows / macOS: tinyfiledialogs (GetOpenFileName / osascript).
// Linux: posix_spawn of zenity or kdialog (no shell, no popen/vfork).
//   tinyfd's Linux path uses popen/vfork from the UI thread while SDL has
//   already spawned audio/GL threads — that SIGSEGVs in libc on modern
//   Arch/CachyOS/Fedora (Browse BIOS / Change ROM). posix_spawn is safe
//   from a multithreaded process; we also skip zenity --attach=$(xprop…).

#include "launcher_files.h"

#include "third_party/tinyfiledialogs.h"

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* True if path's filename matches any "*.ext" / "*.*" pattern (case-insensitive).
 * Used after native pick so typed paths / residual All-Files bypasses cannot
 * accept a PSX track .bin when the picker asked for *.cue only. */
static int launcher_path_matches_patterns(const char* path,
                                          const char* const* patterns,
                                          int num_patterns) {
    if (!path || !path[0]) return 0;
    if (!patterns || num_patterns <= 0) return 1;
    const char* slash = strrchr(path, '/');
#if defined(_WIN32)
    {
        const char* bslash = strrchr(path, '\\');
        if (!slash || (bslash && bslash > slash)) slash = bslash;
    }
#endif
    const char* name = slash ? slash + 1 : path;
    const char* dot = strrchr(name, '.');
    for (int i = 0; i < num_patterns; i++) {
        const char* pat = patterns[i];
        if (!pat || !pat[0]) continue;
        if (strcmp(pat, "*") == 0 || strcmp(pat, "*.*") == 0) return 1;
        if (pat[0] == '*' && pat[1] == '.' && pat[2] != '\0') {
            if (!dot) continue;
            const char* want = pat + 1; /* ".cue" */
            const char* have = dot;
            int ok = 1;
            while (*want && *have) {
                if (tolower((unsigned char)*want) != tolower((unsigned char)*have)) {
                    ok = 0;
                    break;
                }
                want++;
                have++;
            }
            if (ok && !*want && !*have) return 1;
        }
    }
    return 0;
}

static int launcher_reject_if_pattern_mismatch(const char* title,
                                               const char* const* patterns,
                                               int num_patterns,
                                               char* out_path) {
    if (num_patterns <= 0 || !patterns) return 0;
    if (launcher_path_matches_patterns(out_path, patterns, num_patterns))
        return 0;
    tinyfd_messageBox(
        title && title[0] ? title : "Select file",
        "That file type is not allowed for this picker.\n"
        "Please choose a file matching the filter (for PlayStation discs, "
        "select the .cue sheet).",
        "ok", "warning", 1);
    out_path[0] = '\0';
    return 1;
}

#if defined(__linux__)
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <spawn.h>
#include <sys/wait.h>
#include <unistd.h>

extern char** environ;

static int linux_str_has_ci(const char* hay, const char* needle) {
    if (!hay || !needle || !needle[0]) return 0;
    for (const char* p = hay; *p; p++) {
        const char* a = p;
        const char* b = needle;
        while (*a && *b) {
            const int ca = tolower((unsigned char)*a);
            const int cb = tolower((unsigned char)*b);
            if (ca != cb) break;
            a++;
            b++;
        }
        if (!*b) return 1;
    }
    return 0;
}

static int linux_desktop_prefers_kdialog(void) {
    const char* d = getenv("XDG_SESSION_DESKTOP");
    if (!d || !d[0]) d = getenv("XDG_CURRENT_DESKTOP");
    if (!d) return 0;
    /* Plasma: XDG_SESSION_DESKTOP=KDE|plasma, XDG_CURRENT_DESKTOP=KDE:…. */
    if (linux_str_has_ci(d, "KDE") || linux_str_has_ci(d, "plasma") ||
        linux_str_has_ci(d, "LXQt"))
        return 1;
    return 0;
}

static int linux_have_cmd(const char* name) {
    const char* path = getenv("PATH");
    if (!path || !name || !name[0]) return 0;
    char buf[4096];
    snprintf(buf, sizeof(buf), "%s", path);
    for (char* tok = strtok(buf, ":"); tok; tok = strtok(NULL, ":")) {
        char cand[512];
        int n = snprintf(cand, sizeof(cand), "%s/%s", tok, name);
        if (n <= 0 || (size_t)n >= sizeof(cand)) continue;
        if (access(cand, X_OK) == 0) return 1;
    }
    return 0;
}

/* Read one line (path) from fd; strips trailing newline. */
static int linux_read_path_line(int fd, char* out, size_t out_cap) {
    if (!out || out_cap == 0) return 0;
    out[0] = '\0';
    size_t n = 0;
    while (n + 1 < out_cap) {
        char c;
        ssize_t r = read(fd, &c, 1);
        if (r == 0) break;
        if (r < 0) {
            if (errno == EINTR) continue;
            return 0;
        }
        if (c == '\n' || c == '\r') break;
        out[n++] = c;
    }
    out[n] = '\0';
    return n > 0;
}

/* Spawn argv[0] via posix_spawnp, capture stdout line.
 * Returns: 1 = path selected, 0 = dialog ran but cancelled, -1 = spawn/wait fail
 * (only -1 should fall through to another backend). */
static int linux_spawn_capture(char* const argv[], char* out, size_t out_cap) {
    int pipefd[2];
    if (pipe(pipefd) != 0) return -1;

    posix_spawn_file_actions_t actions;
    if (posix_spawn_file_actions_init(&actions) != 0) {
        close(pipefd[0]);
        close(pipefd[1]);
        return -1;
    }
    posix_spawn_file_actions_adddup2(&actions, pipefd[1], STDOUT_FILENO);
    posix_spawn_file_actions_addopen(&actions, STDERR_FILENO, "/dev/null",
                                     O_WRONLY, 0);
    posix_spawn_file_actions_addclose(&actions, pipefd[0]);
    posix_spawn_file_actions_addclose(&actions, pipefd[1]);

    pid_t pid = 0;
    const int rc = posix_spawnp(&pid, argv[0], &actions, NULL, argv, environ);
    posix_spawn_file_actions_destroy(&actions);
    close(pipefd[1]);

    if (rc != 0) {
        close(pipefd[0]);
        return -1;
    }

    const int got = linux_read_path_line(pipefd[0], out, out_cap);
    close(pipefd[0]);

    int status = 0;
    while (waitpid(pid, &status, 0) < 0) {
        if (errno != EINTR) return -1;
    }
    /* Dialog process ran. Non-zero exit or empty path = user cancel — stop. */
    if (!WIFEXITED(status)) return -1;
    if (WEXITSTATUS(status) != 0 || !got) {
        if (out && out_cap) out[0] = '\0';
        return 0;
    }
    return 1;
}

static void linux_append_patterns(char* dst, size_t dst_cap,
                                  const char* const* patterns, int num_patterns) {
    dst[0] = '\0';
    if (!patterns || num_patterns <= 0) {
        snprintf(dst, dst_cap, "*");
        return;
    }
    size_t used = 0;
    for (int i = 0; i < num_patterns; i++) {
        if (!patterns[i] || !patterns[i][0]) continue;
        const int n = snprintf(dst + used, dst_cap - used, "%s%s",
                               used ? " " : "", patterns[i]);
        if (n < 0 || (size_t)n >= dst_cap - used) break;
        used += (size_t)n;
    }
    if (!dst[0]) snprintf(dst, dst_cap, "*");
}

static int linux_pick_open_zenity(const char* title, const char* const* patterns,
                                  int num_patterns, const char* desc,
                                  char* out, size_t out_cap) {
    char title_arg[640];
    char filter_arg[768];
    char pats[256];
    linux_append_patterns(pats, sizeof(pats), patterns, num_patterns);
    snprintf(title_arg, sizeof(title_arg), "--title=%s",
             title && title[0] ? title : "Select file");
    if (desc && desc[0])
        snprintf(filter_arg, sizeof(filter_arg), "--file-filter=%s | %s", desc, pats);
    else
        snprintf(filter_arg, sizeof(filter_arg), "--file-filter=%s", pats);

    /* When the caller supplies patterns (e.g. PSX *.cue only), do not offer
     * "All files" — that undoes the filter in the native dialog. */
    if (patterns && num_patterns > 0) {
        char* argv[] = {
            "zenity",
            "--file-selection",
            title_arg,
            filter_arg,
            NULL
        };
        return linux_spawn_capture(argv, out, out_cap);
    }
    char* argv[] = {
        "zenity",
        "--file-selection",
        title_arg,
        filter_arg,
        "--file-filter=All files | *",
        NULL
    };
    return linux_spawn_capture(argv, out, out_cap);
}

static int linux_pick_open_kdialog(const char* title, const char* const* patterns,
                                   int num_patterns, const char* desc,
                                   char* out, size_t out_cap) {
    char filter[768];
    char pats[256];
    char title_buf[512];
    linux_append_patterns(pats, sizeof(pats), patterns, num_patterns);
    if (desc && desc[0])
        snprintf(filter, sizeof(filter), "%s | %s", pats, desc);
    else
        snprintf(filter, sizeof(filter), "%s", pats);
    snprintf(title_buf, sizeof(title_buf), "%s",
             title && title[0] ? title : "Select file");

    char* argv[] = {
        "kdialog",
        "--getopenfilename",
        ".",
        filter,
        "--title",
        title_buf,
        NULL
    };
    return linux_spawn_capture(argv, out, out_cap);
}

static int linux_pick_save_zenity(const char* title, const char* const* patterns,
                                  int num_patterns, const char* desc,
                                  char* out, size_t out_cap) {
    char title_arg[640];
    char filter_arg[768];
    char pats[256];
    linux_append_patterns(pats, sizeof(pats), patterns, num_patterns);
    snprintf(title_arg, sizeof(title_arg), "--title=%s",
             title && title[0] ? title : "Save file");
    if (desc && desc[0])
        snprintf(filter_arg, sizeof(filter_arg), "--file-filter=%s | %s", desc, pats);
    else
        snprintf(filter_arg, sizeof(filter_arg), "--file-filter=%s", pats);

    if (patterns && num_patterns > 0) {
        char* argv[] = {
            "zenity",
            "--file-selection",
            "--save",
            "--confirm-overwrite",
            title_arg,
            filter_arg,
            NULL
        };
        return linux_spawn_capture(argv, out, out_cap);
    }
    char* argv[] = {
        "zenity",
        "--file-selection",
        "--save",
        "--confirm-overwrite",
        title_arg,
        filter_arg,
        "--file-filter=All files | *",
        NULL
    };
    return linux_spawn_capture(argv, out, out_cap);
}

static int linux_pick_save_kdialog(const char* title, const char* const* patterns,
                                   int num_patterns, const char* desc,
                                   char* out, size_t out_cap) {
    char filter[768];
    char pats[256];
    char title_buf[512];
    linux_append_patterns(pats, sizeof(pats), patterns, num_patterns);
    if (desc && desc[0])
        snprintf(filter, sizeof(filter), "%s | %s", pats, desc);
    else
        snprintf(filter, sizeof(filter), "%s", pats);
    snprintf(title_buf, sizeof(title_buf), "%s",
             title && title[0] ? title : "Save file");

    char* argv[] = {
        "kdialog",
        "--getsavefilename",
        ".",
        filter,
        "--title",
        title_buf,
        NULL
    };
    return linux_spawn_capture(argv, out, out_cap);
}

static int linux_pick_folder_zenity(const char* title, char* out, size_t out_cap) {
    char title_arg[640];
    snprintf(title_arg, sizeof(title_arg), "--title=%s",
             title && title[0] ? title : "Select folder");
    char* argv[] = {
        "zenity",
        "--file-selection",
        "--directory",
        title_arg,
        NULL
    };
    return linux_spawn_capture(argv, out, out_cap);
}

static int linux_pick_folder_kdialog(const char* title, char* out, size_t out_cap) {
    char title_buf[512];
    snprintf(title_buf, sizeof(title_buf), "%s",
             title && title[0] ? title : "Select folder");
    char* argv[] = {
        "kdialog",
        "--getexistingdirectory",
        ".",
        "--title",
        title_buf,
        NULL
    };
    return linux_spawn_capture(argv, out, out_cap);
}

/* Returns 1=ok, 0=cancel (dialog ran), -1=no usable backend (try tinyfd). */
static int linux_pick_open(const char* title, const char* const* patterns,
                           int num_patterns, const char* desc,
                           char* out, size_t out_cap) {
    const int want_kd = linux_desktop_prefers_kdialog();
    const int have_kd = linux_have_cmd("kdialog");
    const int have_zn = linux_have_cmd("zenity");
    int r;
    if (want_kd && have_kd) {
        r = linux_pick_open_kdialog(title, patterns, num_patterns, desc, out, out_cap);
        if (r >= 0) return r;
    }
    if (have_zn) {
        r = linux_pick_open_zenity(title, patterns, num_patterns, desc, out, out_cap);
        if (r >= 0) return r;
    }
    if (!want_kd && have_kd) {
        r = linux_pick_open_kdialog(title, patterns, num_patterns, desc, out, out_cap);
        if (r >= 0) return r;
    }
    return -1;
}

static int linux_pick_save(const char* title, const char* const* patterns,
                           int num_patterns, const char* desc,
                           char* out, size_t out_cap) {
    const int want_kd = linux_desktop_prefers_kdialog();
    const int have_kd = linux_have_cmd("kdialog");
    const int have_zn = linux_have_cmd("zenity");
    int r;
    if (want_kd && have_kd) {
        r = linux_pick_save_kdialog(title, patterns, num_patterns, desc, out, out_cap);
        if (r >= 0) return r;
    }
    if (have_zn) {
        r = linux_pick_save_zenity(title, patterns, num_patterns, desc, out, out_cap);
        if (r >= 0) return r;
    }
    if (!want_kd && have_kd) {
        r = linux_pick_save_kdialog(title, patterns, num_patterns, desc, out, out_cap);
        if (r >= 0) return r;
    }
    return -1;
}

static int linux_pick_folder(const char* title, char* out, size_t out_cap) {
    const int want_kd = linux_desktop_prefers_kdialog();
    const int have_kd = linux_have_cmd("kdialog");
    const int have_zn = linux_have_cmd("zenity");
    int r;
    if (want_kd && have_kd) {
        r = linux_pick_folder_kdialog(title, out, out_cap);
        if (r >= 0) return r;
    }
    if (have_zn) {
        r = linux_pick_folder_zenity(title, out, out_cap);
        if (r >= 0) return r;
    }
    if (!want_kd && have_kd) {
        r = linux_pick_folder_kdialog(title, out, out_cap);
        if (r >= 0) return r;
    }
    return -1;
}
#endif /* __linux__ */

bool launcher_native_file_picker_available(void) {
#if defined(__linux__)
    return linux_have_cmd("zenity") || linux_have_cmd("kdialog");
#else
    return true;
#endif
}

bool launcher_pick_rom(char* out_path, size_t out_cap) {
    if (!out_path || out_cap == 0) return false;
    out_path[0] = '\0';

#if defined(__linux__)
    {
        const int r = linux_pick_open("Select game file", NULL, 0, NULL,
                                      out_path, out_cap);
        return r == 1;
    }
#else
    // No filter: this fallback runs only when the active console's profile
    // supplied no rom_filter, and it cannot know what that console accepts.
    // Offering "All files" is honest; naming one system's extensions here is
    // how a PSX build ended up asking players for a SNES cartridge.
    const char* sel = tinyfd_openFileDialog(
        "Select game file",
        "",       // default path/file
        0, NULL,  // no patterns -> all files
        NULL,     // no filter description
        0);       // single select
    if (!sel || !sel[0]) return false;

    snprintf(out_path, out_cap, "%s", sel);
    return true;
#endif
}

bool launcher_pick_folder(const char* title, char* out_path, size_t out_cap) {
    if (!out_path || out_cap == 0) return false;
    out_path[0] = '\0';

#if defined(__linux__)
    {
        const int r = linux_pick_folder(title, out_path, out_cap);
        if (r >= 0) return r == 1; /* ok or cancel — never fall through to tinyfd */
        return false;
    }
#endif

    const char* sel = tinyfd_selectFolderDialog(title ? title : "Select folder", "");
    if (!sel || !sel[0]) return false;
    snprintf(out_path, out_cap, "%s", sel);
    return true;
}

int launcher_try_pick_file(const char* title, const char* const* patterns,
                           int num_patterns, const char* desc,
                           char* out_path, size_t out_cap) {
    if (!out_path || out_cap == 0) return -1;
    out_path[0] = '\0';

#if defined(__linux__)
    {
        const int r = linux_pick_open(title, patterns, num_patterns, desc,
                                      out_path, out_cap);
        if (r != 1) return r;
        if (launcher_reject_if_pattern_mismatch(title, patterns, num_patterns,
                                                out_path))
            return 0;
        return 1;
    }
#else
    const char* sel = tinyfd_openFileDialog(
        title ? title : "Select file",
        "",
        num_patterns > 0 ? num_patterns : 0,
        num_patterns > 0 ? patterns : NULL,
        desc,
        0);
    if (!sel || !sel[0]) return 0;
    snprintf(out_path, out_cap, "%s", sel);
    if (launcher_reject_if_pattern_mismatch(title, patterns, num_patterns,
                                            out_path))
        return 0;
    return 1;
#endif
}

bool launcher_pick_file(const char* title, const char* const* patterns, int num_patterns,
                        const char* desc, char* out_path, size_t out_cap) {
    const int r = launcher_try_pick_file(title, patterns, num_patterns, desc,
                                         out_path, out_cap);
    return r == 1;
}

bool launcher_pick_save_file(const char* title, const char* const* patterns, int num_patterns,
                             const char* desc, char* out_path, size_t out_cap) {
    if (!out_path || out_cap == 0) return false;
    out_path[0] = '\0';

#if defined(__linux__)
    {
        const int r = linux_pick_save(title, patterns, num_patterns, desc,
                                      out_path, out_cap);
        if (r >= 0) return r == 1; /* ok or cancel — never fall through to tinyfd */
        return false;
    }
#endif

    const char* sel = tinyfd_saveFileDialog(
        title ? title : "Save file",
        "",
        num_patterns > 0 ? num_patterns : 0,
        num_patterns > 0 ? patterns : NULL,
        desc);
    if (!sel || !sel[0]) return false;
    snprintf(out_path, out_cap, "%s", sel);
    return true;
}
