import Foundation

public actor LocalEventBuffer {
    private var events: [ArgusEventEnvelope] = []
    private let limit: Int

    public init(limit: Int = 1_000) {
        self.limit = max(1, limit)
    }

    public func append(_ event: ArgusEventEnvelope) {
        events.append(event)
        if events.count > limit {
            events.removeFirst(events.count - limit)
        }
    }

    public func recent(limit requestedLimit: Int = 20) -> [ArgusEventEnvelope] {
        let count = max(0, requestedLimit)
        guard count > 0 else { return [] }
        return Array(events.suffix(count).reversed())
    }

    public func summaries(limit requestedLimit: Int = 5) -> [String] {
        recent(limit: requestedLimit).map(\.summary)
    }

    public func event(id: UUID) -> ArgusEventEnvelope? {
        events.first { $0.id == id }
    }
}
