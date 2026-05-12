import Foundation
import Security

public enum ArgusKeychainError: Error, Equatable {
    case encodeFailed
    case decodeFailed
    case itemNotFound
    case securityStatus(OSStatus)
}

public struct ArgusKeychain: Sendable {
    private let service: String

    public init(service: String = "com.argus.sensor") {
        self.service = service
    }

    public func save(_ secret: String, account: String) throws {
        guard let data = secret.data(using: .utf8) else {
            throw ArgusKeychainError.encodeFailed
        }

        let query = baseQuery(account: account)
        SecItemDelete(query as CFDictionary)

        var attributes = query
        attributes[kSecValueData as String] = data
        attributes[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly

        let status = SecItemAdd(attributes as CFDictionary, nil)
        guard status == errSecSuccess else {
            throw ArgusKeychainError.securityStatus(status)
        }
    }

    public func read(account: String) throws -> String {
        var query = baseQuery(account: account)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne

        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        if status == errSecItemNotFound {
            throw ArgusKeychainError.itemNotFound
        }
        guard status == errSecSuccess else {
            throw ArgusKeychainError.securityStatus(status)
        }
        guard let data = result as? Data,
              let secret = String(data: data, encoding: .utf8) else {
            throw ArgusKeychainError.decodeFailed
        }
        return secret
    }

    public func delete(account: String) throws {
        let status = SecItemDelete(baseQuery(account: account) as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw ArgusKeychainError.securityStatus(status)
        }
    }

    private func baseQuery(account: String) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account
        ]
    }
}
