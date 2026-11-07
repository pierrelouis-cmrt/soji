import Foundation
import CoreServices
import AppKit
import Darwin

final class EventReplayState { var complete = false }

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
                Unmanaged<EventReplayState>.fromOpaque(context).takeUnretainedValue().complete = true
            }
            emit(["path":paths[i],"flags":flags[i],"id":ids[i]])
        }
    }
    let options=FSEventStreamCreateFlags(kFSEventStreamCreateFlagUseCFTypes | kFSEventStreamCreateFlagFileEvents | kFSEventStreamCreateFlagWatchRoot | kFSEventStreamCreateFlagNoDefer)
    guard let stream=FSEventStreamCreate(nil,callback,&ctx,roots as CFArray,since,0.2,options) else { fail("Could not create FSEvents stream") }
    FSEventStreamSetDispatchQueue(stream,DispatchQueue.main)
    guard FSEventStreamStart(stream) else { fail("Could not start FSEvents stream") }
    DispatchQueue.main.asyncAfter(deadline:.now()+max(0.5,seconds)) {
        FSEventStreamFlushSync(stream)
        emit(["checkpoint":FSEventStreamGetLatestEventId(stream),"replayComplete":state.complete] as [String: Any])
        FSEventStreamStop(stream);FSEventStreamInvalidate(stream);FSEventStreamRelease(stream);exit(0)
    }
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
case "apps":
    emit(NSWorkspace.shared.runningApplications.map { ["pid":$0.processIdentifier,"bundleID":$0.bundleIdentifier ?? "","path":$0.bundleURL?.path ?? "","name":$0.localizedName ?? ""] as [String:Any] })
default:fail("Unknown native operation")
}
