import Foundation

public protocol ArgusEventSink: Sendable {
    func append(_ event: ArgusEventEnvelope) async throws
}

public actor CompositeEventSink: ArgusEventSink {
    private let sinks: [any ArgusEventSink]

    public init(_ sinks: [any ArgusEventSink]) {
        self.sinks = sinks
    }

    public func append(_ event: ArgusEventEnvelope) async throws {
        for sink in sinks {
            try await sink.append(event)
        }
    }
}

public actor LocalEventSpool: ArgusEventSink {
    public let fileURL: URL
    private let encoder: JSONEncoder

    public init(fileURL: URL) {
        self.fileURL = fileURL
        self.encoder = JSONEncoder()
        self.encoder.dateEncodingStrategy = .iso8601
        self.encoder.outputFormatting = [.sortedKeys]
    }

    public static func defaultMacSpool() throws -> LocalEventSpool {
        let baseURL = try FileManager.default.url(
            for: .applicationSupportDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        )
        let directory = baseURL.appendingPathComponent("Argus/Sensor", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return LocalEventSpool(fileURL: directory.appendingPathComponent("events.jsonl"))
    }

    public func append(_ event: ArgusEventEnvelope) async throws {
        try ensureParentDirectory()
        var data = try encoder.encode(event)
        data.append(0x0A)

        if FileManager.default.fileExists(atPath: fileURL.path) {
            let handle = try FileHandle(forWritingTo: fileURL)
            defer { try? handle.close() }
            try handle.seekToEnd()
            try handle.write(contentsOf: data)
        } else {
            try data.write(to: fileURL, options: [.atomic])
        }
    }

    public func readAll() throws -> [ArgusEventEnvelope] {
        guard FileManager.default.fileExists(atPath: fileURL.path) else {
            return []
        }

        let data = try Data(contentsOf: fileURL)
        guard let text = String(data: data, encoding: .utf8) else {
            return []
        }

        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return try text
            .split(separator: "\n")
            .map { line in
                try decoder.decode(
                    ArgusEventEnvelope.self,
                    from: Data(line.utf8)
                )
            }
    }

    public func truncate() throws {
        try ensureParentDirectory()
        try Data().write(to: fileURL, options: [.atomic])
    }

    private func ensureParentDirectory() throws {
        let directory = fileURL.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    }
}

public actor LoopbackEventGatewaySink: ArgusEventSink {
    public enum GatewayError: Error, Equatable {
        case nonLoopbackURL(URL)
        case invalidResponse
        case rejected(statusCode: Int)
    }

    private let endpoint: URL
    private let session: URLSession
    private let encoder: JSONEncoder

    public init(endpoint: URL, session: URLSession = .shared) throws {
        guard endpoint.isLoopbackHTTP else {
            throw GatewayError.nonLoopbackURL(endpoint)
        }
        self.endpoint = endpoint
        self.session = session
        self.encoder = JSONEncoder()
        self.encoder.dateEncodingStrategy = .iso8601
        self.encoder.outputFormatting = [.sortedKeys]
    }

    public static func defaultLocalGateway() throws -> LoopbackEventGatewaySink {
        try LoopbackEventGatewaySink(endpoint: URL(string: "http://127.0.0.1:8765/events")!)
    }

    public func append(_ event: ArgusEventEnvelope) async throws {
        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try encoder.encode(event.gatewayEnvelope())

        let (_, response) = try await session.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw GatewayError.invalidResponse
        }
        guard (200..<300).contains(httpResponse.statusCode) else {
            throw GatewayError.rejected(statusCode: httpResponse.statusCode)
        }
    }
}

extension URL {
    public var isLoopbackHTTP: Bool {
        guard scheme == "http", let host else {
            return false
        }
        return host == "localhost"
            || host == "127.0.0.1"
            || host == "::1"
            || host == "[::1]"
    }
}
