import Foundation
import CoreServices
import AppKit
import Darwin

final class EventReplayState { var complete = false; var finished = false; var stream: FSEventStreamRef? = nil }
// Flush and report once: on HistoryDone (replay complete) or at the deadline.
func finishReplay(_ state: EventReplayState) {
    guard !state.finished, let stream = state.stream else { return }
    state.finished = true
    FSEventStreamFlushSync(stream)
    emit(["checkpoint":FSEventStreamGetLatestEventId(stream),"replayComplete":state.complete] as [String: Any])
    FSEventStreamStop(stream);FSEventStreamInvalidate(stream);FSEventStreamRelease(stream);exit(0)
}

func emit(_ value: Any) {
    if let data = try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]), let s=String(data:data,encoding:.utf8) { print(s); fflush(stdout) }
}
// Query one extended attribute at a time; unsupported attributes stay absent.
// ATTR_CMN_RETURNED_ATTRS is 20 bytes after the four-byte result length.
func extendedAttribute(_ path: String, _ attribute: UInt32, width: Int = 8) -> UInt64? {
    var request = attrlist()
    request.bitmapcount = UInt16(ATTR_BIT_MAP_COUNT)
    request.commonattr = attrgroup_t(ATTR_CMN_RETURNED_ATTRS)
    request.forkattr = attribute
    var buffer = [UInt8](repeating: 0, count: 64)
    let status = buffer.withUnsafeMutableBytes { raw in
        path.withCString { getattrlist($0, &request, raw.baseAddress!, raw.count,
            UInt32(FSOPT_NOFOLLOW | FSOPT_ATTR_CMN_EXTENDED)) }
    }
    guard status == 0 else { return nil }
    return buffer.withUnsafeBytes { raw in
        let length = Int(raw.loadUnaligned(as: UInt32.self))
        let returned = raw.loadUnaligned(fromByteOffset: 20, as: UInt32.self)
        guard length >= 24 + width, returned & attribute != 0 else { return nil }
        if width == 4 { return UInt64(raw.loadUnaligned(fromByteOffset: 24, as: UInt32.self)) }
        return raw.loadUnaligned(fromByteOffset: 24, as: UInt64.self)
    }
}
func volumeIdentities(_ paths: [String]) -> [String: Any] {
    var result: [String: Any] = [:]
    for path in paths {
        var info = stat()
        guard lstat(path, &info) == 0 else { continue }
        var identity: [String: Any] = ["device": info.st_dev]
        if let uuid = FSEventsCopyUUIDForDevice(info.st_dev) {
            identity["uuid"] = CFUUIDCreateString(nil, uuid) as String
        }
        result[path] = identity
    }
    return result
}
// Tokens bind the opaque persistent version identity AND its modification date.
// Known Foundation identity classes have canonical representations. Unknown
// identity classes keep the legacy URL interface without claiming stability.
func versionUnit(_ version: NSFileVersion) -> String? {
    let identity: String
    if let data = version.persistentIdentifier as? Data { identity = "data:" + data.base64EncodedString() }
    else if let uuid = version.persistentIdentifier as? UUID { identity = "uuid:" + uuid.uuidString }
    else if let value = version.persistentIdentifier as? String { identity = "string:" + value }
    else { return nil }
    guard let modified = version.modificationDate,
          let data = try? JSONSerialization.data(withJSONObject:["identifier":identity,"modified":modified.timeIntervalSince1970],options:[.sortedKeys]) else { return nil }
    return "soji-version-v1:" + data.base64EncodedString()
}
func versionRow(_ version: NSFileVersion, current: NSFileVersion?) -> [String: Any] {
    var row: [String: Any] = ["url":version.url.path,"modified":version.modificationDate?.timeIntervalSince1970 ?? 0,
        "conflict":version.isConflict,"current":version == current,"identifier":String(describing:version.persistentIdentifier)]
    if let unit = versionUnit(version) { row["unit"] = unit }
    return row
}

// MARK: - Bulk disk walk
//
// `walk` reads a JSON config on stdin and writes a header line plus columnar
// little-endian arrays on stdout (see soji_cli/walker.py). It reproduces
// Scanner.visit exactly: directories are read with getattrlistbulk on parallel
// workers, and any entry whose bulk attributes could differ from lstat
// (compressed, dataless, hard-linked, mount point, missing attributes) is
// re-read with fstatat, the call Scanner.visit uses. Aggregation, hardlink
// de-duplication and output then run sequentially in readdir order.

// stopNode: emit a "stopped" row when the budget is spent before this root
// (reconcile's visit); otherwise the root is omitted (Scanner.run's loop).
struct WalkRoot: Decodable { let path: String; let depth: Int; let device: Int64?; let stopNode: Bool }
struct WalkConfig: Decodable {
    let roots: [WalkRoot]
    let protected: [String]; let privateHome: [String]
    let privateNames: [String]; let privateSuffixes: [String]; let cloudNames: [String]
    let secretPrefixes: [String]; let secretSuffixes: [String]; let secretNames: [String]
    let maxFiles: Int; let maxSeconds: Double; let maxDepth: Int; let threads: Int
    let forceStat: Bool?
    let verify: Bool?  // diagnostics: compare every bulk entry with fstatat
}
// Reason codes; the Python side owns the strings (walker.REASONS).
enum Reason: UInt8 { case none = 0, stopped, unreadable, symlink, boundary, userProtected, credentials, personalLibrary, privateHome, cloud, agentMemory, appBundle }
enum Kind: UInt8 { case unreadable = 0, directory, regular, symlink, other }

final class WalkDir {
    let path: [UInt8]; let depth: Int; let device: Int32
    var names: [[UInt8]] = []; var stats: [EntryStat] = []; var subdirs: [Int: WalkDir] = [:]
    var openFailed = false; var stopped = false
    init(path: [UInt8], depth: Int, device: Int32) { self.path = path; self.depth = depth; self.device = device }
}
struct EntryStat {
    var kind: Kind = .unreadable; var reason: Reason = .none
    var dev: Int32 = 0; var ino: UInt64 = 0; var nlink: UInt32 = 0
    var blocksBytes: Int64 = 0; var size: Int64 = 0; var stamp: Double = 0
}
@inline(__always) func timeValue(_ t: timespec) -> Double { Double(t.tv_sec) + Double(t.tv_nsec) * 1e-9 }
func entryFrom(_ s: stat) -> EntryStat {
    var e = EntryStat()
    let fmt = s.st_mode & S_IFMT
    e.kind = fmt == S_IFDIR ? .directory : fmt == S_IFREG ? .regular : fmt == S_IFLNK ? .symlink : .other
    e.dev = s.st_dev; e.ino = s.st_ino; e.nlink = UInt32(s.st_nlink)
    e.blocksBytes = Int64(s.st_blocks) * 512; e.size = Int64(s.st_size)
    e.stamp = max(timeValue(s.st_mtimespec), timeValue(s.st_birthtimespec))
    return e
}

final class Walker {
    let config: WalkConfig
    let lock = NSCondition()
    var queue: [WalkDir] = []; var pending = 0
    var visited = 0; var unreadable = 0; var limited = false; var cancelled = false
    var current: [UInt8] = []
    var verifyCounts: [String: Int] = [:]; var verifySamples: [String] = []
    let deadline: Double
    let protected: [[UInt8]]; let privateHome: [[UInt8]]
    let privateNames: Set<[UInt8]>; let privateSuffixes: [[UInt8]]; let cloudNames: [[UInt8]]
    let secretPrefixes: [[UInt8]]; let secretSuffixes: [[UInt8]]; let secretNames: Set<[UInt8]>
    init(_ c: WalkConfig) {
        config = c
        deadline = Date().timeIntervalSince1970 + c.maxSeconds
        protected = c.protected.map { Array($0.utf8) }; privateHome = c.privateHome.map { Array($0.utf8) }
        privateNames = Set(c.privateNames.map { Array($0.utf8) }); privateSuffixes = c.privateSuffixes.map { Array($0.lowercased().utf8) }
        cloudNames = c.cloudNames.map { Array($0.utf8) }
        secretPrefixes = c.secretPrefixes.map { Array($0.utf8) }; secretSuffixes = c.secretSuffixes.map { Array($0.utf8) }
        secretNames = Set(c.secretNames.map { Array($0.utf8) })
    }
    // Scanner.budget: cancel, file count, elapsed time.
    func budgetLocked() -> Bool {
        if cancelled { return false }
        if visited >= config.maxFiles || Date().timeIntervalSince1970 > deadline { limited = true; return false }
        return true
    }
    // engine.within: path == root or path.startswith(root.rstrip('/') + '/')
    func within(_ path: [UInt8], _ root: [UInt8]) -> Bool {
        if path == root { return true }
        var prefix = root; while prefix.last == 0x2F { prefix.removeLast() }
        prefix.append(0x2F)
        return path.starts(with: prefix)
    }
    func lower(_ bytes: [UInt8]) -> [UInt8] {
        if bytes.allSatisfy({ $0 < 0x80 }) { return bytes.map { $0 >= 0x41 && $0 <= 0x5A ? $0 + 32 : $0 } }
        return Array(String(decoding: bytes, as: UTF8.self).lowercased().utf8)
    }
    // Scanner.private, for directories only (as in visit).
    func privateReason(_ path: [UInt8], _ name: [UInt8]) -> Reason {
        if protected.contains(where: { within(path, $0) }) { return .userProtected }
        if privateNames.contains(name) { return .credentials }
        let low = lower(name)
        if privateSuffixes.contains(where: { low.count >= $0.count && low.suffix($0.count).elementsEqual($0) }) { return .personalLibrary }
        if privateHome.contains(where: { within(path, $0) }) { return .privateHome }
        for cloud in cloudNames {
            if name == cloud { return .cloud }
            if name.count > cloud.count && name.starts(with: cloud) && (name[cloud.count] == 0x20 || name[cloud.count] == 0x2D) { return .cloud }
        }
        if low == Array("memory".utf8) || low == Array("memories".utf8) {
            for marker in ["/.claude/", "/.codex/", "/.cursor/"] {
                let m = Array(marker.utf8)
                if path.count >= m.count && (0...(path.count - m.count)).contains(where: { path[$0..<($0 + m.count)].elementsEqual(m) }) { return .agentMemory }
            }
        }
        if name.count >= 4 && name.suffix(4).elementsEqual(Array(".app".utf8)) { return .appBundle }
        return .none
    }
    func join(_ base: [UInt8], _ name: [UInt8]) -> [UInt8] {
        var p = base; if p.last != 0x2F { p.append(0x2F) }; p.append(contentsOf: name); return p
    }
    func basename(_ path: [UInt8]) -> [UInt8] {
        if let i = path.lastIndex(of: 0x2F) { return Array(path[(i + 1)...]) }; return path
    }
    // Directories to descend: decided exactly where visit() decides them.
    func descend(_ e: inout EntryStat, path: [UInt8], name: [UInt8], depth: Int, parentDevice: Int32?) -> WalkDir? {
        guard e.kind == .directory else { return nil }
        let reason = privateReason(path, name)
        if reason != .none { e.reason = reason; return nil }
        if depth >= config.maxDepth || (parentDevice != nil && e.dev != parentDevice!) { e.reason = .boundary; return nil }
        return WalkDir(path: path, depth: depth, device: e.dev)
    }

    func read(_ dir: WalkDir) -> [WalkDir] {
        let fd = dir.path.withUnsafeBufferPointer { buf -> Int32 in
            var c = Array(buf); c.append(0)
            return c.withUnsafeBufferPointer { open(UnsafeRawPointer($0.baseAddress!).assumingMemoryBound(to: CChar.self), O_RDONLY | O_DIRECTORY | O_NOFOLLOW) }
        }
        if fd < 0 { dir.openFailed = true; return [] }
        defer { close(fd) }
        let apfs = isAPFS(fd, device: dir.device)
        var list = attrlist()
        list.bitmapcount = UInt16(ATTR_BIT_MAP_COUNT)
        list.commonattr = attrgroup_t(ATTR_CMN_RETURNED_ATTRS) | attrgroup_t(ATTR_CMN_NAME) | attrgroup_t(ATTR_CMN_ERROR) |
            attrgroup_t(ATTR_CMN_DEVID) | attrgroup_t(ATTR_CMN_OBJTYPE) | attrgroup_t(ATTR_CMN_CRTIME) |
            attrgroup_t(ATTR_CMN_MODTIME) | attrgroup_t(ATTR_CMN_FLAGS) | attrgroup_t(ATTR_CMN_FILEID)
        list.dirattr = attrgroup_t(ATTR_DIR_MOUNTSTATUS) | attrgroup_t(ATTR_DIR_ALLOCSIZE) | attrgroup_t(ATTR_DIR_DATALENGTH)
        list.fileattr = attrgroup_t(ATTR_FILE_LINKCOUNT) | attrgroup_t(ATTR_FILE_ALLOCSIZE) | attrgroup_t(ATTR_FILE_DATALENGTH)
        let capacity = 256 * 1024
        let buffer = UnsafeMutableRawPointer.allocate(byteCount: capacity, alignment: 16)
        defer { buffer.deallocate() }
        var children: [WalkDir] = []
        var stopped = false
        loop: while true {
            let count = config.forceStat == true ? -2 : getattrlistbulk(fd, &list, buffer, capacity, 0)
            if count == 0 { break }
            if count < 0 {
                if count == -2 { break }  // forced stat mode: enumerate with readdir below
                dir.openFailed = true; break
            }
            lock.lock(); let ok = !cancelled && visited < config.maxFiles; lock.unlock()
            if !ok { break }  // the per-entry charge below records the stop
            var entry = buffer
            for _ in 0..<count {
                let length = Int(entry.loadUnaligned(as: UInt32.self))
                var cursor = entry + 4
                let returned = cursor.loadUnaligned(as: attribute_set_t.self); cursor += MemoryLayout<attribute_set_t>.size
                var error: UInt32 = 0
                if returned.commonattr & attrgroup_t(ATTR_CMN_ERROR) != 0 { error = cursor.loadUnaligned(as: UInt32.self); cursor += 4 }
                var name: [UInt8] = []
                if returned.commonattr & attrgroup_t(ATTR_CMN_NAME) != 0 {
                    let ref = cursor.loadUnaligned(as: attrreference_t.self)
                    let start = (cursor + Int(ref.attr_dataoffset)).assumingMemoryBound(to: UInt8.self)
                    var n = Int(ref.attr_length); while n > 0 && start[n - 1] == 0 { n -= 1 }
                    name = Array(UnsafeBufferPointer(start: start, count: n))
                    cursor += MemoryLayout<attrreference_t>.size
                }
                var e = EntryStat(); var exact = error == 0 && !name.isEmpty
                var objtype: UInt32 = 0; var flags: UInt32 = 0
                let c = returned.commonattr
                if c & attrgroup_t(ATTR_CMN_DEVID) != 0 { e.dev = cursor.loadUnaligned(as: Int32.self); cursor += 4 } else { exact = false }
                if c & attrgroup_t(ATTR_CMN_OBJTYPE) != 0 { objtype = cursor.loadUnaligned(as: UInt32.self); cursor += 4 } else { exact = false }
                var birth = 0.0, modified = 0.0
                if c & attrgroup_t(ATTR_CMN_CRTIME) != 0 { birth = timeValue(cursor.loadUnaligned(as: timespec.self)); cursor += MemoryLayout<timespec>.size } else { exact = false }
                if c & attrgroup_t(ATTR_CMN_MODTIME) != 0 { modified = timeValue(cursor.loadUnaligned(as: timespec.self)); cursor += MemoryLayout<timespec>.size } else { exact = false }
                if c & attrgroup_t(ATTR_CMN_FLAGS) != 0 { flags = cursor.loadUnaligned(as: UInt32.self); cursor += 4 } else { exact = false }
                if c & attrgroup_t(ATTR_CMN_FILEID) != 0 { e.ino = cursor.loadUnaligned(as: UInt64.self); cursor += 8 } else { exact = false }
                e.stamp = max(modified, birth)
                switch objtype {
                case 2: // VDIR
                    e.kind = .directory
                    let d = returned.dirattr
                    if d & attrgroup_t(ATTR_DIR_MOUNTSTATUS) != 0 {
                        let mount = cursor.loadUnaligned(as: UInt32.self); cursor += 4
                        if mount & UInt32(DIR_MNTSTATUS_MNTPOINT) != 0 { exact = false }
                    } else { exact = false }
                    if d & attrgroup_t(ATTR_DIR_ALLOCSIZE) != 0 { e.blocksBytes = cursor.loadUnaligned(as: Int64.self); cursor += 8 } else { exact = false }
                    if d & attrgroup_t(ATTR_DIR_DATALENGTH) != 0 { e.size = cursor.loadUnaligned(as: Int64.self); cursor += 8 } else { exact = false }
                default:
                    e.kind = objtype == 1 ? .regular : objtype == 5 ? .symlink : .other
                    let f = returned.fileattr
                    if f & attrgroup_t(ATTR_FILE_LINKCOUNT) != 0 { e.nlink = cursor.loadUnaligned(as: UInt32.self); cursor += 4 } else { exact = false }
                    if f & attrgroup_t(ATTR_FILE_ALLOCSIZE) != 0 { e.blocksBytes = cursor.loadUnaligned(as: Int64.self); cursor += 8 } else { exact = false }
                    if f & attrgroup_t(ATTR_FILE_DATALENGTH) != 0 { e.size = cursor.loadUnaligned(as: Int64.self); cursor += 8 } else { exact = false }
                    // Verified equal to lstat on APFS (scripts/walk_parity.py,
                    // verify mode); elsewhere hardlink identity comes from lstat.
                    if e.nlink > 1 && !apfs { exact = false }
                }
                // st_blocks*512 rounds the allocation up to whole 512-byte blocks.
                e.blocksBytes = (e.blocksBytes + 511) / 512 * 512
                if config.verify == true && !name.isEmpty && error == 0 {
                    var s = stat()
                    let rc = name.withUnsafeBufferPointer { buf -> Int32 in
                        var cname = Array(buf); cname.append(0)
                        return cname.withUnsafeBufferPointer { fstatat(fd, UnsafeRawPointer($0.baseAddress!).assumingMemoryBound(to: CChar.self), &s, AT_SYMLINK_NOFOLLOW) }
                    }
                    if rc == 0 {
                        let r = entryFrom(s)
                        let same = r.kind == e.kind && r.dev == e.dev && r.ino == e.ino && r.blocksBytes == e.blocksBytes && r.size == e.size && r.stamp == e.stamp && (e.kind == .directory || r.nlink == e.nlink)
                        let tag = flags & UInt32(UF_COMPRESSED) != 0 ? "compressed" : flags & UInt32(SF_DATALESS) != 0 ? "dataless" : e.nlink > 1 ? "hardlink" : "plain"
                        lock.lock(); verifyCounts[tag + (same ? ":same" : ":diff"), default: 0] += 1
                        if !same && tag == "plain" && verifySamples.count < 10 { verifySamples.append(String(decoding: join(dir.path, name), as: UTF8.self) + " bulk=\(e.blocksBytes),\(e.size),\(e.ino) stat=\(r.blocksBytes),\(r.size),\(r.ino)") }
                        lock.unlock()
                    }
                }
                if (flags & UInt32(UF_COMPRESSED) != 0 && !apfs) || flags & UInt32(SF_DATALESS) != 0 { exact = false }
                if !exact && !name.isEmpty {
                    var s = stat()
                    let rc = name.withUnsafeBufferPointer { buf -> Int32 in
                        var cname = Array(buf); cname.append(0)
                        return cname.withUnsafeBufferPointer { fstatat(fd, UnsafeRawPointer($0.baseAddress!).assumingMemoryBound(to: CChar.self), &s, AT_SYMLINK_NOFOLLOW) }
                    }
                    e = rc == 0 ? entryFrom(s) : EntryStat()
                }
                if !name.isEmpty { dir.names.append(name); dir.stats.append(e) }
                entry += length
            }
        }
        if config.forceStat == true && !dir.openFailed {
            // Reference mode: readdir + fstatat, the syscalls Scanner.visit uses.
            let copy = dup(fd)
            if let stream = fdopendir(copy) {
                while let ent = readdir(stream) {
                    var nameBytes = withUnsafeBytes(of: ent.pointee.d_name) { Array($0.prefix(Int(ent.pointee.d_namlen))) }
                    if nameBytes == [0x2E] || nameBytes == [0x2E, 0x2E] { continue }
                    var s = stat()
                    nameBytes.append(0)
                    let rc = nameBytes.withUnsafeBufferPointer { fstatat(fd, UnsafeRawPointer($0.baseAddress!).assumingMemoryBound(to: CChar.self), &s, AT_SYMLINK_NOFOLLOW) }
                    nameBytes.removeLast()
                    dir.names.append(nameBytes); dir.stats.append(rc == 0 ? entryFrom(s) : EntryStat())
                }
                closedir(stream)
            } else { close(copy); dir.openFailed = true }
        }
        // Budget is charged per entry, in order, like visit's child loop.
        // budget() before each child: cancel/time once per folder (they only
        // move forward), the file count per entry; only readable entries count.
        let now = Date().timeIntervalSince1970
        lock.lock()
        var kept = 0
        if !dir.names.isEmpty {
            if cancelled { stopped = true }
            else if now > deadline { stopped = true; limited = true }
            else {
                for i in 0..<dir.names.count {
                    if visited >= config.maxFiles { stopped = true; limited = true; break }
                    if dir.stats[i].kind != .unreadable { visited += 1 } else { unreadable += 1 }
                    kept += 1
                }
            }
        }
        current = dir.path
        lock.unlock()
        if kept < dir.names.count { dir.names.removeSubrange(kept...); dir.stats.removeSubrange(kept...) }
        dir.stopped = stopped
        for i in 0..<dir.names.count where dir.stats[i].kind == .directory {
            let path = join(dir.path, dir.names[i])
            if let child = descend(&dir.stats[i], path: path, name: dir.names[i], depth: dir.depth + 1, parentDevice: dir.device) {
                dir.subdirs[i] = child; children.append(child)
            }
        }
        return children
    }

    var filesystems: [Int32: Bool] = [:]
    func isAPFS(_ fd: Int32, device: Int32) -> Bool {
        lock.lock(); if let known = filesystems[device] { lock.unlock(); return known }; lock.unlock()
        var info = statfs()
        let value = fstatfs(fd, &info) == 0 && withUnsafeBytes(of: info.f_fstypename) { String(decoding: $0.prefix(while: { $0 != 0 }), as: UTF8.self) } == "apfs"
        lock.lock(); filesystems[device] = value; lock.unlock()
        return value
    }
    func worker() {
        while true {
            lock.lock()
            while queue.isEmpty && pending > 0 { lock.wait() }
            if queue.isEmpty { lock.unlock(); return }
            let dir = queue.removeLast()
            lock.unlock()
            let children = read(dir)
            lock.lock()
            queue.append(contentsOf: children.reversed())
            pending += children.count - 1
            lock.broadcast(); lock.unlock()
        }
    }

    func run(_ dirs: [WalkDir]) {
        guard !dirs.isEmpty else { return }
        lock.lock(); queue = dirs.reversed(); pending = dirs.count; lock.unlock()
        let threads = (0..<max(1, config.threads)).map { _ in Thread { self.worker() } }
        for t in threads { t.stackSize = 1 << 20; t.start() }
        // Progress for the TUI: "visited<TAB>path" on stderr.
        while true {
            lock.lock()
            let done = pending == 0
            let line = "\(visited)\t" + String(decoding: current, as: UTF8.self) + "\n"
            if !done { _ = lock.wait(until: Date().addingTimeInterval(0.1)) }
            lock.unlock()
            FileHandle.standardError.write(line.data(using: .utf8)!)
            if done { break }
        }
    }
}

// Columnar output in preorder, matching visit's node insertion order.
final class WalkOutput {
    var parent: [Int32] = []; var size: [Int64] = []; var apparent: [Int64] = []; var files: [Int64] = []
    var newest: [Double] = []; var ownNewest: [Double] = []; var errors: [Int64] = []; var ownErrors: [Int32] = []
    var flags: [UInt8] = []; var reason: [UInt8] = []; var device: [Int64] = []; var inode: [UInt64] = []
    var ownSize: [Int64] = []; var ownApparent: [Int64] = []; var linkCount: [Int32] = []
    var names: [UInt8] = []
    var bytes: Int64 = 0; var skipped = 0; var openFailures = 0
    struct InodeKey: Hashable { let dev: Int32; let ino: UInt64 }
    var seen = Set<InodeKey>()
    let secretPrefixes: [[UInt8]]; let secretSuffixes: [[UInt8]]; let secretNames: Set<[UInt8]>
    init(_ w: Walker) { secretPrefixes = w.secretPrefixes; secretSuffixes = w.secretSuffixes; secretNames = w.secretNames }
    func add(_ name: [UInt8], parent p: Int32) -> Int {
        parent.append(p); size.append(0); apparent.append(0); files.append(0); newest.append(0); ownNewest.append(0)
        errors.append(0); ownErrors.append(0); flags.append(0); reason.append(0); device.append(0); inode.append(0)
        ownSize.append(0); ownApparent.append(0); linkCount.append(0)
        if !names.isEmpty || parent.count > 1 { names.append(0) }
        names.append(contentsOf: name)
        return parent.count - 1
    }
    // flags: 1 secret, 2 skipped, 4 directory, 8 regular file
    func emitEntry(_ e: EntryStat, name: [UInt8], parent p: Int32, dir: WalkDir?) {
        let i = add(name, parent: p)
        if e.kind == .unreadable { errors[i] = 1; ownErrors[i] = 1; reason[i] = Reason.unreadable.rawValue; flags[i] = 4; return }
        device[i] = Int64(e.dev); inode[i] = e.ino; newest[i] = e.stamp; ownNewest[i] = e.stamp
        switch e.kind {
        case .symlink:
            reason[i] = Reason.symlink.rawValue; files[i] = 1; size[i] = e.blocksBytes; apparent[i] = e.size
            ownSize[i] = e.blocksBytes; ownApparent[i] = e.size; bytes += e.blocksBytes; skipped += 1
        case .regular:
            let links = Int64(max(1, e.nlink))
            files[i] = 1; linkCount[i] = Int32(links); ownSize[i] = e.blocksBytes / links; ownApparent[i] = e.size
            size[i] = ownSize[i]; bytes += size[i]
            if seen.insert(InodeKey(dev: e.dev, ino: e.ino)).inserted { apparent[i] = e.size }
            var f: UInt8 = 8
            if name.starts(with: [0x2E, 0x65, 0x6E, 0x76]) || secretPrefixes.contains(where: { name.starts(with: $0) }) ||
                secretSuffixes.contains(where: { name.count >= $0.count && name.suffix($0.count).elementsEqual($0) }) || secretNames.contains(name) { f |= 1 }
            flags[i] = f
        case .other:
            break
        case .directory:
            flags[i] = 4
            if e.reason != .none { reason[i] = e.reason.rawValue; flags[i] |= 2; skipped += 1; return }
            size[i] = e.blocksBytes; apparent[i] = e.size; ownSize[i] = e.blocksBytes; ownApparent[i] = e.size; bytes += e.blocksBytes
            guard let dir = dir else { return }
            for k in 0..<dir.names.count {
                let before = parent.count
                emitEntry(dir.stats[k], name: dir.names[k], parent: Int32(i), dir: dir.subdirs[k])
                size[i] += size[before]; apparent[i] += apparent[before]; files[i] += files[before]
                newest[i] = max(newest[i], newest[before]); errors[i] += errors[before]
                if flags[before] & 1 != 0 { flags[i] |= 1 }
                if flags[before] & 2 != 0 { flags[i] |= 2 }
            }
            if dir.stopped { errors[i] += 1; ownErrors[i] += 1 }
            if dir.openFailed { errors[i] += 1; ownErrors[i] += 1; openFailures += 1 }
        case .unreadable: break
        }
    }
}

func runWalk() {
    let input = FileHandle.standardInput.readDataToEndOfFile()
    guard let config = try? JSONDecoder().decode(WalkConfig.self, from: input) else { fail("walk: invalid config") }
    let walker = Walker(config)
    let term = DispatchSource.makeSignalSource(signal: SIGTERM, queue: DispatchQueue.global())
    signal(SIGTERM, SIG_IGN)
    term.setEventHandler { walker.lock.lock(); walker.cancelled = true; walker.lock.unlock() }
    term.resume()
    var tops: [(EntryStat, WalkDir?, Bool)] = []  // stat, dir, stoppedBeforeMeasuring
    var dirs: [WalkDir] = []
    for root in config.roots {
        walker.lock.lock(); let ok = walker.budgetLocked(); walker.lock.unlock()
        if !ok { tops.append((EntryStat(), nil, true)); continue }
        var s = stat()
        let bytes = Array(root.path.utf8)
        guard lstat(root.path, &s) == 0 else { walker.unreadable += 1; tops.append((EntryStat(), nil, false)); continue }
        walker.visited += 1
        var e = entryFrom(s)
        let dir = walker.descend(&e, path: bytes, name: walker.basename(bytes), depth: root.depth, parentDevice: root.device.map { Int32(truncatingIfNeeded: $0) })
        if let dir = dir { dirs.append(dir) }
        tops.append((e, dir, false))
    }
    walker.run(dirs)
    let out = WalkOutput(walker)
    for (k, root) in config.roots.enumerated() {
        let (e, dir, stopped) = tops[k]
        if stopped && !root.stopNode { continue }
        if stopped {
            let i = out.add(Array(root.path.utf8), parent: -1)
            out.errors[i] = 1; out.ownErrors[i] = 1; out.reason[i] = Reason.stopped.rawValue; out.flags[i] = 4
        } else { out.emitEntry(e, name: Array(root.path.utf8), parent: -1, dir: dir) }
    }
    let header: [String: Any] = ["count": out.parent.count, "namesBytes": out.names.count, "visited": walker.visited,
        "bytes": out.bytes, "unreadable": walker.unreadable + out.ownErrorsFromOpen(), "skipped": out.skipped,
        "limited": walker.limited, "cancelled": walker.cancelled,
        "verify": walker.verifyCounts, "verifySamples": walker.verifySamples]
    var data = try! JSONSerialization.data(withJSONObject: header, options: [.sortedKeys]); data.append(0x0A)
    func append<T>(_ array: [T]) { array.withUnsafeBytes { data.append(contentsOf: $0) } }
    append(out.parent); append(out.size); append(out.apparent); append(out.files); append(out.newest); append(out.ownNewest)
    append(out.errors); append(out.ownErrors); append(out.flags); append(out.reason); append(out.device); append(out.inode)
    append(out.ownSize); append(out.ownApparent); append(out.linkCount); data.append(contentsOf: out.names)
    FileHandle.standardOutput.write(data)
    exit(0)
}
extension WalkOutput {
    // visit() counts a failed directory open as unreadable; budget stops are not.
    func ownErrorsFromOpen() -> Int { openFailures }
}

let args=Array(CommandLine.arguments.dropFirst())
func fail(_ message:String) -> Never { emit(["error":message]); exit(1) }
guard let action=args.first else { fail("Expected events, event-id, trash, versions, remove-version, or apps") }
switch action {
case "event-id":
    var result: [String: Any] = ["eventID": FSEventsGetCurrentEventId()]
    if args.count > 1 { result["volumes"] = volumeIdentities(Array(args.dropFirst())) }
    emit(result)
case "events":
    guard args.count>=4, let since=UInt64(args[1]), let seconds=Double(args[2]) else { fail("events SINCE SECONDS ROOT...") }
    let roots=Array(args.dropFirst(3))
    let state = EventReplayState()
    var ctx=FSEventStreamContext(version:0,info:Unmanaged.passUnretained(state).toOpaque(),retain:nil,release:nil,copyDescription:nil)
    let callback:FSEventStreamCallback = { _,context,count,raw,flags,ids in
        let paths=unsafeBitCast(raw,to:NSArray.self)
        for i in 0..<count {
            if flags[i] & FSEventStreamEventFlags(kFSEventStreamEventFlagHistoryDone) != 0, let context = context {
                let state = Unmanaged<EventReplayState>.fromOpaque(context).takeUnretainedValue()
                state.complete = true
                // Every historical event precedes HistoryDone; no need to wait out the window.
                DispatchQueue.main.async { finishReplay(state) }
            }
            emit(["path":paths[i],"flags":flags[i],"id":ids[i]])
        }
    }
    let options=FSEventStreamCreateFlags(kFSEventStreamCreateFlagUseCFTypes | kFSEventStreamCreateFlagFileEvents | kFSEventStreamCreateFlagWatchRoot | kFSEventStreamCreateFlagNoDefer)
    guard let stream=FSEventStreamCreate(nil,callback,&ctx,roots as CFArray,since,0.2,options) else { fail("Could not create FSEvents stream") }
    FSEventStreamSetDispatchQueue(stream,DispatchQueue.main)
    state.stream = stream
    guard FSEventStreamStart(stream) else { fail("Could not start FSEvents stream") }
    DispatchQueue.main.asyncAfter(deadline:.now()+max(0.5,seconds)) { finishReplay(state) }
    dispatchMain()
case "trash":
    guard args.count==2 else { fail("trash PATH") }
    var destination:NSURL?
    do { try FileManager.default.trashItem(at:URL(fileURLWithPath:args[1]),resultingItemURL:&destination);emit(["trashedTo":destination?.path ?? ""]) }
    catch { fail(error.localizedDescription) }
case "metadata":
    var result:[[String:Any]]=[]
    for path in args.dropFirst() {
        let url=URL(fileURLWithPath:path)
        var info = stat()
        guard lstat(path, &info) == 0 else { continue }
        let symlink = (info.st_mode & S_IFMT) == S_IFLNK
        // Never resolve an untrusted symlink to gather resource metadata.
        let values = symlink ? nil : try? url.resourceValues(forKeys:[.addedToDirectoryDateKey,.isUbiquitousItemKey,.ubiquitousItemDownloadingStatusKey,.fileAllocatedSizeKey,.totalFileAllocatedSizeKey,.fileSizeKey,.isPackageKey])
        var row: [String: Any] = [
            "path":path, "added":values?.addedToDirectoryDate?.timeIntervalSince1970 ?? 0,
            "cloud":values?.isUbiquitousItem ?? false,
            "downloadingStatus":values?.ubiquitousItemDownloadingStatus?.rawValue ?? "",
            "allocatedBytes":values?.fileAllocatedSize ?? Int(info.st_blocks) * 512,
            "logicalBytes":info.st_size, "statAllocatedBytes":Int64(info.st_blocks) * 512,
            "device":info.st_dev, "inode":info.st_ino, "linkCount":info.st_nlink,
            "flags":info.st_flags, "compressed":(info.st_flags & UInt32(UF_COMPRESSED)) != 0,
            "dataless":(info.st_flags & UInt32(SF_DATALESS)) != 0,
            "symlink":symlink, "package":values?.isPackage ?? false,
        ]
        if let total = values?.totalFileAllocatedSize { row["totalAllocatedBytes"] = total }
        if let size = extendedAttribute(path, UInt32(ATTR_CMNEXT_PRIVATESIZE)) { row["privateBytes"] = size }
        if let clone = extendedAttribute(path, UInt32(ATTR_CMNEXT_CLONEID)) { row["cloneID"] = clone }
        if let refs = extendedAttribute(path, UInt32(ATTR_CMNEXT_CLONE_REFCNT), width: 4) { row["cloneRefs"] = refs }
        if let flags = extendedAttribute(path, UInt32(ATTR_CMNEXT_EXT_FLAGS)) {
            row["extendedFlags"] = flags
            row["purgeable"] = flags & UInt64(EF_IS_PURGEABLE) != 0
            row["mayShareBlocks"] = flags & UInt64(EF_MAY_SHARE_BLOCKS) != 0
            row["sharesAllBlocks"] = flags & UInt64(EF_SHARES_ALL_BLOCKS) != 0
            row["sparse"] = flags & UInt64(EF_IS_SPARSE) != 0
        }
        result.append(row)
    }
    emit(result)
case "versions":
    guard args.count==2 else { fail("versions PATH") }
    let coordinator = NSFileCoordinator(filePresenter:nil)
    var coordinationError: NSError?
    var rows: [[String: Any]]?
    coordinator.coordinate(readingItemAt:URL(fileURLWithPath:args[1]),options:[],error:&coordinationError) { url in
        guard (try? url.checkResourceIsReachable()) == true,
              let versions = NSFileVersion.otherVersionsOfItem(at:url) else { return }
        let current = NSFileVersion.currentVersionOfItem(at:url)
        rows = versions.map { versionRow($0,current:current) }
    }
    if let error = coordinationError { fail("Document versions unavailable: " + error.localizedDescription) }
    guard let rows = rows else { fail("Document versions unavailable") }
    emit(rows)
case "remove-version":
    guard args.count==3 else { fail("remove-version DOCUMENT VERSION_URL") }
    let coordinator = NSFileCoordinator(filePresenter:nil)
    var coordinationError: NSError?
    var operationError: String?
    var removed: [String: Any]?
    // Enumeration, current/conflict/retention checks and removal are one
    // coordinated write. There is no pre-lock NSFileVersion snapshot to reuse.
    coordinator.coordinate(writingItemAt:URL(fileURLWithPath:args[1]),options:[],error:&coordinationError) { url in
        guard (try? url.checkResourceIsReachable()) == true,
              let versions = NSFileVersion.otherVersionsOfItem(at:url) else {
            operationError = "Document versions unavailable"; return
        }
        let current = NSFileVersion.currentVersionOfItem(at:url)
        let selector = args[2]
        guard let version = versions.first(where: { candidate in
            selector.hasPrefix("soji-version-v1:") ? versionUnit(candidate) == selector : candidate.url.path == selector
        }) else { operationError = "Version absent or changed"; return }
        guard !version.isConflict, version != current else { operationError = "Current or conflicted version is retained"; return }
        guard let modified = version.modificationDate,
              let newest = versions.compactMap({ $0.modificationDate }).max(), modified < newest else {
            operationError = "Newest older version or unknown modification date is retained"; return
        }
        let row = versionRow(version,current:current)
        do {
            try version.remove()
            var result = row; result["removed"] = true; removed = result
        } catch { operationError = error.localizedDescription }
    }
    if let error = coordinationError { fail("Document versions unavailable: " + error.localizedDescription) }
    if let error = operationError { fail(error) }
    guard let removed = removed else { fail("Document versions unavailable") }
    emit(removed)
case "walk":
    runWalk()
case "apps":
    emit(NSWorkspace.shared.runningApplications.map { ["pid":$0.processIdentifier,"bundleID":$0.bundleIdentifier ?? "","path":$0.bundleURL?.path ?? "","name":$0.localizedName ?? ""] as [String:Any] })
default:fail("Unknown native operation")
}
