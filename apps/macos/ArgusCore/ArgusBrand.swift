public enum ArgusBrand {
    public static let suiteName = "Argus"
    public static let coreName = "Argus Core"
    public static let sensorName = "Argus Sensor"
    public static let meshName = "Argus Mesh"
    public static let osName = "ArgusOS"

    public static let localEventStream = "stream:raw:macos"
    public static let perceptionConsumerGroup = "argus-perception"

    public static var productLine: [String] {
        [coreName, sensorName, meshName, osName]
    }
}
