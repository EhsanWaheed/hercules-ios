"""XXH3-64 (seed 0), the hash DuckStation texture packs name files by.

The pip package xxhash when installed (Windows and the launcher's HD build),
else tools/native/libxxh3.so (`make tools/native/libxxh3.so`).
"""
try:
    from xxhash import xxh3_64_intdigest as xxh3
except ImportError:
    import ctypes
    from pathlib import Path

    _lib = ctypes.CDLL(str(Path(__file__).resolve().parent / "native/libxxh3.so"))
    _lib.xxh3_64.restype = ctypes.c_ulonglong
    _lib.xxh3_64.argtypes = (ctypes.c_char_p, ctypes.c_ulong)

    def xxh3(data):
        return _lib.xxh3_64(data, len(data))
