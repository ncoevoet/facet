import FacetCore
import Foundation

/// The launcher's text comes from Facet's own i18n/translations/*.json (the `macos_app`
/// section), so the seven languages and scripts/audit_i18n.py cover it like the viewer.
enum L10n {
    private static func table(_ language: String) -> [String: Any] {
        let url = Helper.resources.appendingPathComponent("app/i18n/translations/\(language).json")
        guard let data = try? Data(contentsOf: url),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return [:] }
        return object
    }

    private static let current = table(Translations.language(preferred: Locale.preferredLanguages))
    private static let english = table("en")

    /// `key` is relative to `macos_app`; `{name}` placeholders are filled from `args`.
    static func t(_ key: String, _ args: [String: String] = [:]) -> String {
        let path = "macos_app." + key
        let text = Translations.lookup(path, in: current) ?? Translations.lookup(path, in: english) ?? path
        return Translations.fill(text, args)
    }
}
