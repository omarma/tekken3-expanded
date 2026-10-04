// toml_depth_guard.h — reject over-nested TOML before toml11 sees it.
//
// toml11 3.7.1 parses arrays and inline tables recursively with no depth
// limit: ~5000 nested `[` (10 KB) or ~3000 nested `{` overflow the stack, a
// SIGSEGV no try/catch can stop. Every TOML read from a file (game.toml,
// settings.toml, mod manifests/state, text translation tables...) goes
// through toml_depth_guard::parse(), which scans the bytes first and throws
// toml::syntax_error — what toml::parse throws on bad input — when `[`/`{`
// nesting exceeds kMaxNesting. Real files nest 2-3 deep ([[table]] headers
// count 2), so the limit never bites legitimate input.
//
// The scanner skips everything toml11 would not read as a bracket: # comments,
// "basic" strings (with backslash escapes), 'literal' strings, and the
// multi-line """...""" / '''...''' forms. When unsure it over-counts, which can
// only reject input that toml11 would also reject or that is absurdly nested.
#pragma once

#include <cstddef>
#include <filesystem>
#include <fstream>
#include <ios>
#include <iterator>
#include <sstream>
#include <string>

#include "toml.hpp"

namespace toml_depth_guard {

constexpr int kMaxNesting = 64;

// Deepest [ / { nesting found in `s` outside strings and comments; returns
// early (with a value > limit) once `limit` is exceeded.
inline int max_nesting(const char* s, std::size_t n, int limit = kMaxNesting) {
    int depth = 0, deepest = 0;
    std::size_t i = 0;
    auto triple = [&](std::size_t at, char q) {
        return at + 2 < n && s[at] == q && s[at + 1] == q && s[at + 2] == q;
    };
    while (i < n) {
        const char c = s[i];
        if (c == '#') {                                   // comment to EOL
            while (i < n && s[i] != '\n') ++i;
        } else if (c == '"' || c == '\'') {
            const bool basic = (c == '"');
            if (triple(i, c)) {                           // multi-line string
                i += 3;
                while (i < n && !triple(i, c)) {
                    if (basic && s[i] == '\\') ++i;       // skip escaped char
                    ++i;
                }
                i += 3;                                   // closing delimiter
                // Up to two quotes right before the delimiter belong to the
                // content (`"""a"""""`); swallow them so they don't open a string.
                for (int k = 0; k < 2 && i < n && s[i] == c; ++k) ++i;
            } else {                                      // single-line string
                ++i;
                while (i < n && s[i] != c && s[i] != '\n') {
                    if (basic && s[i] == '\\' && i + 1 < n && s[i + 1] != '\n') ++i;
                    ++i;
                }
                ++i;                                      // closing quote / EOL
            }
        } else {
            if (c == '[' || c == '{') {
                if (++depth > deepest) deepest = depth;
                if (deepest > limit) return deepest;
            } else if ((c == ']' || c == '}') && depth > 0) {
                --depth;
            }
            ++i;
        }
    }
    return deepest;
}

inline bool nesting_ok(const std::string& s, int limit = kMaxNesting) {
    return max_nesting(s.data(), s.size(), limit) <= limit;
}

// Same contract as toml::parse(filename): throws std::ios_base::failure when
// the file can't be opened, toml::syntax_error on malformed (or over-nested)
// content, and keeps `fname` in error messages.
inline toml::value parse(const std::filesystem::path& fpath) {
    const std::string fname = fpath.string();
    std::ifstream ifs(fpath, std::ios_base::binary);
    if (!ifs.good())
        throw std::ios_base::failure(
            "toml::parse: Error opening file \"" + fname + "\"");
    std::string content((std::istreambuf_iterator<char>(ifs)),
                        std::istreambuf_iterator<char>());
    if (ifs.bad())
        throw std::ios_base::failure(
            "toml::parse: Error reading file \"" + fname + "\"");
    if (!nesting_ok(content)) {
        toml::source_location loc;
        throw toml::syntax_error(
            "[error] toml::parse: " + fname + ": arrays/inline tables nested deeper than " +
                std::to_string(kMaxNesting) + " levels",
            loc);
    }
    std::istringstream iss(std::move(content), std::ios_base::binary);
    return toml::parse(iss, fname);
}

}  // namespace toml_depth_guard
