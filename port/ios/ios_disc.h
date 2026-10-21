// ios_disc.h - the player's disc on iOS: finding and checking it, importing
// it from a folder or a ZIP, and the saves beside it (ios_disc.mm). No UI:
// the launcher (ios_launcher.mm) runs these and shows the outcome.
#pragma once

#include <atomic>
#include <cstdint>
#include <functional>
#include <string>

namespace herc {

enum class State { NotFound, WrongVersion, Incomplete, Ready };

struct DiscStatus {
    State state = State::NotFound;
    std::string root;      // the folder checked
    std::string cue;       // its .cue, when there is one
    std::string found_id;  // WrongVersion: the release it is (SCES-0089x), "" when unknown
    std::string missing;   // Incomplete: the files the .cue names that are not there
};

struct Progress {
    uint64_t files_done = 0, files_total = 0, bytes_done = 0, bytes_total = 0;
    std::string current;  // the file being copied, or "Checking ..."
};
using ProgressFn = std::function<void(const Progress &)>;

enum class ImportResult { Ok, Cancelled, NoDisc, WrongVersion, Incomplete, NoSpace, Failed };

// The disc in `dir`. Hashes the data track the first time (a few seconds for
// a whole CD); later checks of the same file reuse the cached digest.
DiscStatus check_disc(const std::string &dir, const ProgressFn &progress = nullptr);

// Copies the disc (.cue and the .bin files it names) from a folder or a ZIP
// into `dest`, checks it, and only then replaces what `dest` held. Blocking:
// run it off the main thread. `status` is the imported disc's on success or
// WrongVersion.
ImportResult import_disc(const std::string &source, bool zip, const std::string &dest,
                         const std::atomic<bool> &cancel, const ProgressFn &progress, DiscStatus *status,
                         std::string *error);

bool export_saves(const std::string &saves_dir, const std::string &zip_path, std::string *error);
bool import_saves(const std::string &zip_path, const std::string &saves_dir, std::string *error);

const char *release_name(const std::string &id);  // "English (SCES-00891)"
std::string human_bytes(uint64_t bytes);

}  // namespace herc
