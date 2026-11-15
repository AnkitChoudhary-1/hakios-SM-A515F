"""Strict decoder for the original bounded pre-Linux entry diagnostic."""
import struct
import zlib
from phase3_support import require

MAGIC = 0x315052544e454b48
FOOTER = 0x3158444e45504b48
NAMES = ("magic", "nonce_hi", "nonce_lo", "entry_el", "daif", "sctlr", "cntfrq", "midr",
         "mpidr", "pc", "sp", "x0", "x1", "x2", "x3", "nzcv", "continuation", "bytes", "crc32", "footer")


def decode(raw, nonce):
    if len(raw) >= 172 and struct.unpack_from("<III", raw) == (0x43474244, 160, 160):
        raw = raw[12:172]
    require(len(raw) == 160, "Entry record has wrong original length")
    words = struct.unpack("<20Q", raw)
    require(words[0] == MAGIC and words[19] == FOOTER and words[17] == 160, "Entry delimiters differ")
    require(f"{words[1]:016x}{words[2]:016x}" == nonce, "Entry nonce is not current")
    require(words[18] == zlib.crc32(raw[:144]), "Entry register CRC differs")
    return dict(zip(NAMES, words))
