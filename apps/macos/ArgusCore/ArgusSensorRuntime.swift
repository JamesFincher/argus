import Foundation

public protocol ArgusRuntimeTimerToken: AnyObject, Sendable {
    func invalidate()
}

@MainActor
public protocol ArgusRuntimeTimerScheduling: AnyObject {
    func scheduleTimer(
        intervalSeconds: Int,
        repeats: Bool,
        _ fire: @escaping @MainActor () -> Void
    ) -> any ArgusRuntimeTimerToken
}

@MainActor
public protocol ArgusRuntimeLifecycleObserving: AnyObject {
    func start(emit: @escaping @MainActor (ArgusEventEnvelope) -> Void)
    func stop()
}

public struct ArgusRuntimeEventRecordResult: Equatable, Sendable {
    public var sinkErrorMessage: String?

    public var hasSinkError: Bool {
        sinkErrorMessage != nil
    }

    public init(sinkErrorMessage: String? = nil) {
        self.sinkErrorMessage = sinkErrorMessage
    }
}

public actor ArgusRuntimeEventRecorder {
    private let buffer: LocalEventBuffer
    private let sink: (any ArgusEventSink)?

    public init(
        buffer: LocalEventBuffer = LocalEventBuffer(limit: 250),
        sink: (any ArgusEventSink)?
    ) {
        self.buffer = buffer
        self.sink = sink
    }

    public func append(_ event: ArgusEventEnvelope) async -> ArgusRuntimeEventRecordResult {
        await buffer.append(event)

        do {
            try await sink?.append(event)
            return ArgusRuntimeEventRecordResult()
        } catch {
            let message = String(describing: error)
            let errorEvent = ArgusEventFactory.systemError(message: message, stage: "event_sink")
            await buffer.append(errorEvent)
            try? await sink?.append(errorEvent)
            return ArgusRuntimeEventRecordResult(sinkErrorMessage: message)
        }
    }

    public func recent(limit: Int = 12) async -> [ArgusEventEnvelope] {
        await buffer.recent(limit: limit)
    }
}

@MainActor
public final class ArgusSensorRuntimeController {
    public let heartbeatIntervalSeconds: Int
    public let captureIntervalSeconds: Int

    private let timerScheduler: any ArgusRuntimeTimerScheduling
    private let lifecycleObserver: any ArgusRuntimeLifecycleObserving
    private let emit: @MainActor (ArgusEventEnvelope) -> Void
    private let captureSnapshot: @MainActor () -> Void
    private var heartbeatTimer: (any ArgusRuntimeTimerToken)?
    private var captureTimer: (any ArgusRuntimeTimerToken)?

    public init(
        heartbeatIntervalSeconds: Int = 30,
        captureIntervalSeconds: Int = 5,
        timerScheduler: any ArgusRuntimeTimerScheduling = FoundationArgusRuntimeTimerScheduler(),
        lifecycleObserver: any ArgusRuntimeLifecycleObserving,
        emit: @escaping @MainActor (ArgusEventEnvelope) -> Void,
        captureSnapshot: @escaping @MainActor () -> Void
    ) {
        self.heartbeatIntervalSeconds = heartbeatIntervalSeconds
        self.captureIntervalSeconds = captureIntervalSeconds
        self.timerScheduler = timerScheduler
        self.lifecycleObserver = lifecycleObserver
        self.emit = emit
        self.captureSnapshot = captureSnapshot
    }

    public func resume() {
        stopTimers()
        lifecycleObserver.start(emit: emit)
        emitHeartbeat(status: "ok", mode: "active")
        heartbeatTimer = timerScheduler.scheduleTimer(
            intervalSeconds: heartbeatIntervalSeconds,
            repeats: true
        ) { [weak self] in
            self?.emitHeartbeat(status: "ok", mode: "active")
        }
        captureTimer = timerScheduler.scheduleTimer(
            intervalSeconds: captureIntervalSeconds,
            repeats: true
        ) { [weak self] in
            self?.captureSnapshot()
        }
        captureSnapshot()
    }

    public func pause() {
        stopTimers()
        lifecycleObserver.stop()
        emitHeartbeat(status: "paused", mode: "paused")
    }

    public func stopTimers() {
        heartbeatTimer?.invalidate()
        captureTimer?.invalidate()
        heartbeatTimer = nil
        captureTimer = nil
    }

    private func emitHeartbeat(status: String, mode: String) {
        emit(
            ArgusEventFactory.sensorHeartbeat(
                status: status,
                intervalSeconds: heartbeatIntervalSeconds,
                mode: mode
            )
        )
    }
}

public final class FoundationArgusRuntimeTimerToken: ArgusRuntimeTimerToken, @unchecked Sendable {
    private let timer: Timer

    init(_ timer: Timer) {
        self.timer = timer
    }

    public func invalidate() {
        timer.invalidate()
    }
}

@MainActor
public final class FoundationArgusRuntimeTimerScheduler: ArgusRuntimeTimerScheduling {
    public init() {}

    public func scheduleTimer(
        intervalSeconds: Int,
        repeats: Bool,
        _ fire: @escaping @MainActor () -> Void
    ) -> any ArgusRuntimeTimerToken {
        let timer = Timer.scheduledTimer(
            withTimeInterval: TimeInterval(intervalSeconds),
            repeats: repeats
        ) { _ in
            Task { @MainActor in
                fire()
            }
        }
        return FoundationArgusRuntimeTimerToken(timer)
    }
}
