// toml11 3.7.1 recurses once per nested array / inline table with no limit,
// so a ~10 KB file of `[` overflows the stack (SIGSEGV, not an exception).
// toml_depth_guard::parse must turn that into a toml::syntax_error, without
// counting brackets that sit inside strings or comments, and must accept every
// TOML file the repo actually ships.
#include "toml_depth_guard.h"

#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>

namespace fs = std::filesystem;

static int failures;

static void check(bool value, const std::string& message) {
    if (!value) {
        std::cerr << "FAIL: " << message << "\n";
        failures++;
    }
}

static fs::path g_tmp;

static fs::path write_tmp(const std::string& name, const std::string& text) {
    const fs::path p = g_tmp / name;
    std::ofstream out(p, std::ios::binary);
    out << text;
    return p;
}

static std::string repeat(const std::string& s, int n) {
    std::string out;
    for (int i = 0; i < n; ++i) out += s;
    return out;
}

enum class Outcome { Ok, SyntaxError, OtherError };

static Outcome parse_file(const fs::path& p, std::string* what = nullptr) {
    try {
        (void)toml_depth_guard::parse(p);
        return Outcome::Ok;
    } catch (const toml::syntax_error& e) {
        if (what) *what = e.what();
        return Outcome::SyntaxError;
    } catch (const std::exception& e) {
        if (what) *what = e.what();
        return Outcome::OtherError;
    }
}

static void test_deep_input_rejected() {
    // Same shape as the audit reproducer: 5000 nested arrays.
    std::string what;
    const fs::path arrays =
        write_tmp("deep_arrays.toml", "a = " + repeat("[", 5000) + repeat("]", 5000) + "\n");
    check(parse_file(arrays, &what) == Outcome::SyntaxError, "5000 nested arrays rejected");
    check(what.find("deep_arrays.toml") != std::string::npos, "rejection names the file");

    const fs::path tables =
        write_tmp("deep_tables.toml", "a = " + repeat("{b = ", 3000) + "1" + repeat("}", 3000) + "\n");
    check(parse_file(tables) == Outcome::SyntaxError, "3000 nested inline tables rejected");

    // Unbalanced (never closed) nesting is just as deep for the parser.
    const fs::path open_only = write_tmp("open_only.toml", "a = " + repeat("[{x=", 4000) + "\n");
    check(parse_file(open_only) == Outcome::SyntaxError, "unclosed deep nesting rejected");

    // Leading closers must not buy extra depth.
    const fs::path closers = write_tmp(
        "closers.toml", repeat("]", 200) + "\na = " + repeat("[", 5000) + "\n");
    check(parse_file(closers) == Outcome::SyntaxError, "leading ] does not offset depth");

    // An escaped backslash ends the string: brackets after it count.
    const fs::path esc = write_tmp(
        "escaped_backslash.toml", "s = \"\\\\\"\na = " + repeat("[", 5000) + repeat("]", 5000) + "\n");
    check(parse_file(esc) == Outcome::SyntaxError, "brackets after \"\\\\\" are counted");
}

static void test_limit_boundary() {
    const int lim = toml_depth_guard::kMaxNesting;
    const std::string at = "a = " + repeat("[", lim) + "1" + repeat("]", lim) + "\n";
    const std::string over = "a = " + repeat("[", lim + 1) + "1" + repeat("]", lim + 1) + "\n";
    check(toml_depth_guard::nesting_ok(at), "nesting at the limit is accepted by the scanner");
    check(!toml_depth_guard::nesting_ok(over), "nesting one past the limit is rejected");
    check(parse_file(write_tmp("at_limit.toml", at)) == Outcome::Ok, "nesting at the limit parses");
    check(parse_file(write_tmp("over_limit.toml", over)) == Outcome::SyntaxError,
          "nesting past the limit throws syntax_error");
    // Table headers nest at most 2 and close immediately.
    check(toml_depth_guard::max_nesting("[a]\n[[b]]\n[[b]]\n", 15) == 2,
          "table headers count as depth 1/2");
}

static void test_strings_and_comments_skipped() {
    const std::string deep = repeat("[", 500) + repeat("{", 500);
    const std::string text =
        "# comment " + deep + "\n"
        "basic = \"" + deep + " \\\" " + deep + "\"\n"
        "literal = '" + deep + " \\'\n"
        "ml_basic = \"\"\"\n" + deep + "\n \\\"\"\" still inside " + deep + "\n\"\"\"\n"
        "ml_basic_q = \"\"\"" + deep + "\"\"\"\"\"\n"
        "ml_literal = '''\n" + deep + " '' ' \n" + deep + "'''\n"
        "ml_literal_q = '''" + deep + "'''''\n"
        "arr = [ \"]\", '[', \"\"\"{\"\"\", # " + deep + "\n  [1, 2] ] # trailing " + deep + "\n"
        "[\"quoted [ key\".sub]\n"
        "x = { y = \"{\", z = [ '}' ] }\n";
    check(toml_depth_guard::max_nesting(text.data(), text.size()) == 2,
          "brackets inside strings/comments are not counted (max depth 2)");
    std::string what;
    const Outcome o = parse_file(write_tmp("strings.toml", text), &what);
    check(o == Outcome::Ok, "string/comment-heavy document parses: " + what);
}

static void test_missing_file_still_io_error() {
    const Outcome o = parse_file(g_tmp / "does_not_exist.toml");
    check(o == Outcome::OtherError, "missing file still reports an I/O error");
}

static void test_repo_files_accepted(const fs::path& repo) {
    int count = 0;
    auto accept = [&](const fs::path& p) {
        std::string what;
        const Outcome o = parse_file(p, &what);
        check(o == Outcome::Ok, "repo file accepted: " + p.string() + " " + what);
        ++count;
    };
    const fs::path game = repo / "game.toml";
    check(fs::is_regular_file(game), "repo game.toml exists: " + game.string());
    if (fs::is_regular_file(game)) accept(game);
    int manifests = 0;
    std::error_code ec;
    for (auto it = fs::recursive_directory_iterator(repo / "mods", ec);
         !ec && it != fs::recursive_directory_iterator(); it.increment(ec)) {
        if (it->is_regular_file() && it->path().extension() == ".toml") {
            accept(it->path());
            if (it->path().filename() == "manifest.toml") ++manifests;
        }
    }
    check(manifests > 0, "found mods/**/manifest.toml files");
    std::cout << "accepted " << count << " repo TOML files (" << manifests << " manifests)\n";
}

int main(int argc, char** argv) {
    g_tmp = fs::temp_directory_path() / "psx_toml_depth_guard_test";
    fs::remove_all(g_tmp);
    fs::create_directories(g_tmp);

    const fs::path repo = argc > 1 ? fs::path(argv[1]) : fs::path(TOML_GUARD_REPO_ROOT);

    test_deep_input_rejected();
    test_limit_boundary();
    test_strings_and_comments_skipped();
    test_missing_file_still_io_error();
    test_repo_files_accepted(repo);

    fs::remove_all(g_tmp);
    if (failures) {
        std::cerr << failures << " failure(s)\n";
        return EXIT_FAILURE;
    }
    std::cout << "toml_depth_guard_test: OK\n";
    return EXIT_SUCCESS;
}
