# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Alex Doss
"""Minimal read-only Compound File Binary (OLE2 / "structured storage") reader.

Written from Microsoft's open specification [MS-CFB]. No dependencies, no bpy, so it runs both in
Blender and in plain Python tools. Softimage .scn/.emdl files are CFB containers.
"""
import struct

SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
FREESECT, ENDOFCHAIN, FATSECT, DIFSECT = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD, 0xFFFFFFFC
NOSTREAM = 0xFFFFFFFF
STORAGE, STREAM, ROOT = 1, 2, 5


class CFBError(Exception):
    pass


class Entry:
    __slots__ = ("sid", "name", "type", "left", "right", "child", "start", "size", "path", "children")

    def __repr__(self):
        return "<Entry %s %s %d>" % ("/".join(self.path), {1: "storage", 2: "stream", 5: "root"}.get(self.type), self.size)


def is_cfb(path):
    with open(path, "rb") as f:
        return f.read(8) == SIGNATURE


class CompoundFile:
    """Opens a whole CFB file in memory. `streams()` lists stream paths, `read(path)` returns bytes."""

    def __init__(self, path_or_bytes):
        if isinstance(path_or_bytes, (bytes, bytearray)):
            self.data = bytes(path_or_bytes)
        else:
            with open(path_or_bytes, "rb") as f:
                self.data = f.read()
        d = self.data
        if d[:8] != SIGNATURE:
            raise CFBError("not a compound file")
        (self.minor, self.major, bom, sshift, mshift) = struct.unpack_from("<HHHHH", d, 24)
        if bom != 0xFFFE:
            raise CFBError("bad byte order mark")
        self.ssize = 1 << sshift
        self.msize = 1 << mshift
        (n_dir, n_fat, dir_start, _tx, self.cutoff, mfat_start, n_mfat, difat_start, n_difat) = \
            struct.unpack_from("<IIIIIIIII", d, 40)
        # FAT sector list: 109 entries in the header, the rest in a DIFAT chain.
        fat_secs = list(struct.unpack_from("<109I", d, 76))
        per = self.ssize // 4
        s, guard = difat_start, 0
        while s not in (ENDOFCHAIN, FREESECT) and guard <= n_difat:
            vals = struct.unpack_from("<%dI" % per, d, self._off(s))
            fat_secs.extend(vals[:-1])
            s = vals[-1]
            guard += 1
        fat_secs = [x for x in fat_secs if x not in (FREESECT, ENDOFCHAIN)][:n_fat]
        fat = []
        for fs in fat_secs:
            fat.extend(struct.unpack_from("<%dI" % per, d, self._off(fs)))
        self.fat = fat
        # MiniFAT
        mfat = []
        if n_mfat and mfat_start not in (ENDOFCHAIN, FREESECT):
            for sec in self._chain(mfat_start):
                mfat.extend(struct.unpack_from("<%dI" % per, d, self._off(sec)))
        self.mfat = mfat
        # Directory
        raw = b"".join(self._sector(s) for s in self._chain(dir_start))
        self.entries = []
        for i in range(len(raw) // 128):
            e = Entry()
            o = i * 128
            nlen = struct.unpack_from("<H", raw, o + 64)[0]
            e.sid = i
            e.name = raw[o:o + max(0, nlen - 2)].decode("utf-16-le", "replace")
            e.type = raw[o + 66]
            e.left, e.right, e.child = struct.unpack_from("<III", raw, o + 68)
            e.start = struct.unpack_from("<I", raw, o + 116)[0]
            size = struct.unpack_from("<Q", raw, o + 120)[0]
            e.size = size & 0xFFFFFFFF if self.major == 3 else size
            e.path, e.children = (), []
            self.entries.append(e)
        root = self.entries[0]
        if root.type != ROOT:
            raise CFBError("first directory entry is not the root")
        self.ministream = self._read_regular(root.start, root.size)
        self._by_path = {}
        self._walk(root, ())

    # -- sectors ---------------------------------------------------------------------------------
    def _off(self, sec):
        return (sec + 1) * self.ssize

    def _sector(self, sec):
        o = self._off(sec)
        return self.data[o:o + self.ssize]

    def _chain(self, start, table=None):
        table = self.fat if table is None else table
        out, s, seen = [], start, set()
        while s not in (ENDOFCHAIN, FREESECT):
            if s in seen or s >= len(table):
                raise CFBError("corrupt sector chain at %d" % s)
            seen.add(s)
            out.append(s)
            s = table[s]
        return out

    def _read_regular(self, start, size):
        if size == 0 or start in (ENDOFCHAIN, FREESECT):
            return b""
        return b"".join(self._sector(s) for s in self._chain(start))[:size]

    def _read_mini(self, start, size):
        m, ms = self.ministream, self.msize
        return b"".join(m[s * ms:(s + 1) * ms] for s in self._chain(start, self.mfat))[:size]

    # -- directory tree --------------------------------------------------------------------------
    def _siblings(self, sid):
        """In-order walk of a red-black sibling tree (iterative: trees can be deep)."""
        out, stack, cur, seen = [], [], sid, set()
        while stack or cur != NOSTREAM:
            while cur != NOSTREAM and cur < len(self.entries) and cur not in seen:
                seen.add(cur)
                stack.append(cur)
                cur = self.entries[cur].left
            if not stack:
                break
            cur = stack.pop()
            out.append(self.entries[cur])
            cur = self.entries[cur].right
        return out

    def _walk(self, entry, path):
        for e in self._siblings(entry.child):
            e.path = path + (e.name,)
            entry.children.append(e)
            self._by_path["/".join(e.path)] = e
            if e.type == STORAGE:
                self._walk(e, e.path)

    # -- public ----------------------------------------------------------------------------------
    def streams(self):
        return sorted(p for p, e in self._by_path.items() if e.type == STREAM)

    def storages(self):
        return sorted(p for p, e in self._by_path.items() if e.type == STORAGE)

    def entry(self, path):
        return self._by_path[path]

    def exists(self, path):
        return path in self._by_path

    def read(self, path):
        e = self._by_path[path]
        if e.type != STREAM:
            raise CFBError("%s is not a stream" % path)
        if e.size < self.cutoff:
            return self._read_mini(e.start, e.size)
        return self._read_regular(e.start, e.size)
