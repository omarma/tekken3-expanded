/*
 * test_toolchain_health.c — the setup host's portable-toolchain health check.
 *
 * Regression test for the macOS quarantine bug (2026-10-18): the macOS
 * cmake-clang-v1 pack ships cmake, ninja and ccache only (builds use the Xcode
 * clang and Apple ld), but the check required clang + ld.lld inside the pack.
 * Opening the launcher then deleted `latest` and renamed the healthy pack to
 * `<tag>.broken`, and every later check picked the renamed dir again and
 * stacked another suffix (`1.0.14.broken.broken.broken`).
 *
 * Builds fake packs (shell-script tools) under a temporary HOME and runs the
 * real host code: the test #includes psxrecomp_codegen_host.c. POSIX only.
 * Build: `ctest -R toolchain_health_test` (recipe in runtime/CMakeLists.txt).
 */
#include "../../host/psxrecomp_codegen_host.c"

#include <stdio.h>
#include <sys/stat.h>

/* The only symbol the host takes from recomp-ui at link time. */
int recomp_launcher_relaunch_exe(char* out, size_t out_cap) {
    (void)out;
    (void)out_cap;
    return 0;
}

static int failures = 0;
#define CHECK(cond, msg) do { \
    if (!(cond)) { printf("FAIL: %s\n", msg); failures++; } \
    else         { printf("ok:   %s\n", msg); } \
} while (0)

static char g_tmp[512];
static char g_cache[1024];

static void write_script(const char* path, int exit_code) {
    FILE* f = fopen(path, "w");
    if (!f) {
        perror(path);
        exit(2);
    }
    fprintf(f, "#!/bin/sh\nexit %d\n", exit_code);
    fclose(f);
    chmod(path, 0755);
}

/* <cache>/<tag>/bin/{cmake,ninja,ccache} plus retcomm-toolchain.json. */
static void make_pack(const char* tag, int cmake_exit) {
    char pack[1200], bin[1300], path[1400];
    snprintf(pack, sizeof(pack), "%s/%s", g_cache, tag);
    snprintf(bin, sizeof(bin), "%s/bin", pack);
    if (!mkdir_p(bin)) {
        perror(bin);
        exit(2);
    }
    snprintf(path, sizeof(path), "%s/cmake", bin);
    write_script(path, cmake_exit);
    snprintf(path, sizeof(path), "%s/ninja", bin);
    write_script(path, 0);
    snprintf(path, sizeof(path), "%s/ccache", bin);
    write_script(path, 0);
    snprintf(path, sizeof(path), "%s/retcomm-toolchain.json", pack);
    FILE* f = fopen(path, "w");
    if (f) {
        fprintf(f, "{\"id\": \"cmake-clang-v1\", \"version\": \"%s\"}\n", tag);
        fclose(f);
    }
}

static void reset_cache(void) {
    char cmd[1200];
    snprintf(cmd, sizeof(cmd), "rm -rf \"%s\"", g_cache);
    if (system(cmd) != 0)
        exit(2);
    mkdir_p(g_cache);
    g_toolchain_bin[0] = '\0';
    g_cli_toolchain_bin[0] = '\0';
    g_cmake[0] = '\0';
    g_tc_repair_note[0] = '\0';
}

static int cache_has(const char* name) {
    char path[1200];
    struct stat st;
    snprintf(path, sizeof(path), "%s/%s", g_cache, name);
    return lstat(path, &st) == 0;
}

/* Number of cache entries whose name contains ".broken". */
static int count_broken(void) {
    int n = 0;
    DIR* d = opendir(g_cache);
    struct dirent* ent;
    if (!d)
        return -1;
    while ((ent = readdir(d)) != NULL) {
        if (strstr(ent->d_name, ".broken"))
            ++n;
    }
    closedir(d);
    return n;
}

static void link_latest(const char* tag) {
    char latest[1200];
    snprintf(latest, sizeof(latest), "%s/latest", g_cache);
    if (symlink(tag, latest) != 0) {
        perror(latest);
        exit(2);
    }
}

#if defined(__APPLE__)
/* The shipped macOS pack: cmake, ninja, ccache; compiler from Xcode CLT. */
static void test_macos_pack_is_ready(void) {
    reset_cache();
    make_pack("1.0.14", 0);
    link_latest("1.0.14");
    CHECK(host_toolchain_is_ready() == 1,
          "macOS pack without clang/ld.lld is ready (system clang links)");
    host_toolchain_is_ready(); /* a second launcher open */
    CHECK(cache_has("1.0.14"), "macOS pack keeps its versioned dir");
    CHECK(cache_has("latest"), "macOS pack keeps its latest pointer");
    CHECK(count_broken() == 0, "macOS pack is never quarantined");
}

/* A failing system compiler is not the pack's fault: keep the pack. */
static void test_macos_bad_system_compiler_keeps_pack(void) {
    char cc[1200];
    reset_cache();
    make_pack("1.0.14", 0);
    link_latest("1.0.14");
    snprintf(cc, sizeof(cc), "%s/failing-cc", g_tmp);
    write_script(cc, 1);
    setenv("CC", cc, 1);
    CHECK(host_toolchain_is_ready() == 0,
          "macOS pack with a failing system compiler is not ready");
    unsetenv("CC");
    CHECK(cache_has("1.0.14") && cache_has("latest") && count_broken() == 0,
          "failing system compiler leaves the pack and latest untouched");
    CHECK(strstr(g_tc_repair_note, "Command Line Tools") != NULL,
          "repair note points at the Xcode Command Line Tools");
}
#endif

/* A really broken pack is quarantined once, never re-suffixed. */
static void test_broken_pack_quarantined_once(void) {
    reset_cache();
    make_pack("1.0.14", 1); /* cmake --version fails */
    link_latest("1.0.14");
    CHECK(host_toolchain_is_ready() == 0, "pack whose cmake fails is not ready");
    CHECK(!cache_has("latest"), "broken latest pointer is removed");
    CHECK(!cache_has("1.0.14") && cache_has("1.0.14.broken"),
          "broken pack is quarantined as <tag>.broken");
    host_toolchain_is_ready();
    host_toolchain_is_ready();
    CHECK(cache_has("1.0.14.broken") && count_broken() == 1,
          "later checks do not stack another .broken suffix");
}

int main(void) {
    char project[600], tmpl[512];
    const char* tmpdir = getenv("TMPDIR");
    snprintf(tmpl, sizeof(tmpl), "%s/psxrecomp-tc-health-XXXXXX",
             (tmpdir && tmpdir[0]) ? tmpdir : "/tmp");
    if (!mkdtemp(tmpl)) {
        perror("mkdtemp");
        return 2;
    }
    snprintf(g_tmp, sizeof(g_tmp), "%s", tmpl);
    snprintf(g_cache, sizeof(g_cache),
             "%s/.local/share/retcomm/toolchains/cmake-clang-v1", g_tmp);
    snprintf(project, sizeof(project), "%s/project", g_tmp);
    mkdir_p(project);

    /* Only the temporary HOME may be searched (never the real cache). */
    setenv("HOME", g_tmp, 1);
    unsetenv("XDG_DATA_HOME");
    unsetenv("RETCOMM_TOOLCHAIN_CACHE");
    unsetenv("RETCOMM_DATA_HOME");
    unsetenv("RETCOMM_TOOLCHAIN_DIR");
    unsetenv("PSXRECOMP_TOOLCHAIN_DIR");
    unsetenv("TOOLCHAIN_DIR");
    unsetenv("BPE_TOOLCHAIN_DIR");
    unsetenv("RETCOMM_TOOLCHAIN_MIN_VERSION");
    unsetenv("CMAKE");
    unsetenv("CC");
    snprintf(g_project_root, sizeof(g_project_root), "%s", project);

#if defined(__APPLE__)
    test_macos_pack_is_ready();
    test_macos_bad_system_compiler_keeps_pack();
#endif
    test_broken_pack_quarantined_once();

    {
        char cmd[700];
        snprintf(cmd, sizeof(cmd), "rm -rf \"%s\"", g_tmp);
        (void)system(cmd);
    }
    printf("%s (%d failure%s)\n", failures ? "FAILED" : "PASSED", failures,
           failures == 1 ? "" : "s");
    return failures ? 1 : 0;
}
