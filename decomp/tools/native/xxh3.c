/* Thin shared-library wrapper so Python tools can compute the unseeded
 * XXH3-64 hashes DuckStation-format texture packs are named after.
 * Build: make tools/native/libxxh3.so (uses PSXRecomp's vendored xxhash.h). */
#define XXH_INLINE_ALL
#include "xxhash.h"

unsigned long long xxh3_64(const void* data, unsigned long len) {
    return XXH3_64bits(data, len);
}
