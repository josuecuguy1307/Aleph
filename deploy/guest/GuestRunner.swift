import Foundation
import Virtualization

guard CommandLine.arguments.count == 3, VZVirtualMachine.isSupported else {
    fputs("usage: GuestProbe kernel initramfs (Virtualization.framework required)\n", stderr)
    exit(2)
}

let config = VZVirtualMachineConfiguration()
config.platform = VZGenericPlatformConfiguration()
config.cpuCount = 2
config.memorySize = 4 * 1024 * 1024 * 1024
let loader = VZLinuxBootLoader(kernelURL: URL(fileURLWithPath: CommandLine.arguments[1]))
loader.initialRamdiskURL = URL(fileURLWithPath: CommandLine.arguments[2])
loader.commandLine = "console=hvc0 modules=virtio_console quiet"
config.bootLoader = loader
let serial = VZVirtioConsoleDeviceSerialPortConfiguration()
serial.attachment = VZFileHandleSerialPortAttachment(
    fileHandleForReading: FileHandle(forReadingAtPath: "/dev/null")!,
    fileHandleForWriting: .standardError)
let hostToGuest = Pipe()
let guestToHost = Pipe()
let ipc = VZVirtioConsoleDeviceSerialPortConfiguration()
ipc.attachment = VZFileHandleSerialPortAttachment(
    fileHandleForReading: hostToGuest.fileHandleForReading,
    fileHandleForWriting: guestToHost.fileHandleForWriting)
config.serialPorts = [serial, ipc]
config.entropyDevices = [VZVirtioEntropyDeviceConfiguration()]
config.socketDevices = []
config.networkDevices = []
config.directorySharingDevices = []
config.storageDevices = []

do { try config.validate() } catch {
    fputs("VM configuration rejected: \(error)\n", stderr)
    exit(3)
}

let vm = VZVirtualMachine(configuration: config)
func readFrame(_ handle: FileHandle, maxBytes: Int) throws -> Data {
    var data = Data()
    while data.count <= maxBytes {
        guard let byte = try handle.read(upToCount: 1), !byte.isEmpty else {
            throw NSError(domain: "AlephGuest", code: 1)
        }
        data.append(byte)
        if byte == Data([10]) { return data }
    }
    throw NSError(domain: "AlephGuest", code: 2)
}

let request: Data
do { request = try readFrame(.standardInput, maxBytes: 1024 * 1024) }
catch { fputs("invalid framed request\n", stderr); exit(7) }

vm.start { result in
    if case .failure(let error) = result {
        fputs("VM start failed: \(error)\n", stderr)
        exit(4)
    }
    DispatchQueue.global().async {
        do {
            let ready = try readFrame(guestToHost.fileHandleForReading, maxBytes: 64)
            guard ready == Data("ALEPH_GUEST_READY\n".utf8) else {
                throw NSError(domain: "AlephGuest", code: 3)
            }
            hostToGuest.fileHandleForWriting.write(request)
            while true {
                let response = try readFrame(guestToHost.fileHandleForReading, maxBytes: 65536)
                guard let object = try JSONSerialization.jsonObject(with: response) as? [String: Any] else {
                    throw NSError(domain: "AlephGuest", code: 9)
                }
                FileHandle.standardOutput.write(response)
                if object["kind"] as? String == "tool" {
                    let reply = try readFrame(.standardInput, maxBytes: 65536)
                    guard let parsed = try JSONSerialization.jsonObject(with: reply) as? [String: Any],
                          parsed["ok"] is Bool else {
                        throw NSError(domain: "AlephGuest", code: 10)
                    }
                    hostToGuest.fileHandleForWriting.write(reply)
                    continue
                }
                guard object["kind"] == nil, object["ok"] is Bool else {
                    throw NSError(domain: "AlephGuest", code: 11)
                }
                break
            }
            DispatchQueue.main.async {
                vm.stop { error in
                    if let error { fputs("VM stop failed: \(error)\n", stderr) }
                    exit(error == nil ? 0 : 5)
                }
            }
        } catch {
            fputs("guest IPC failed: \(error)\n", stderr)
            DispatchQueue.main.async { vm.stop { _ in exit(8) } }
        }
    }
}
DispatchQueue.main.asyncAfter(deadline: .now() + 90) {
    if vm.canStop {
        vm.stop { _ in fputs("guest hard timeout\n", stderr); exit(124) }
    } else {
        exit(6)
    }
}
dispatchMain()
