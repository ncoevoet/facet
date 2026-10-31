# Konfigurationsreferenz

> 🌐 [English](../CONFIGURATION.md) · [Français](../fr/CONFIGURATION.md) · **Deutsch** · [Italiano](../it/CONFIGURATION.md) · [Español](../es/CONFIGURATION.md) · [Português](../pt/CONFIGURATION.md) · [简体中文](../zh/CONFIGURATION.md)

Jede Einstellung wird in `config/scoring_config.default.json` ausgeliefert. Ihre eigene `scoring_config.json` überschreibt sie Schlüssel für Schlüssel — siehe [Standardwerte und Ihre Überschreibung](#standardwerte-und-ihre-überschreibung). Führen Sie nach einer Änderung `python facet.py --recompute-average` aus, um die Bewertungen zu aktualisieren (keine GPU erforderlich).

## Inhaltsverzeichnis

- [Standardwerte und Ihre Überschreibung](#standardwerte-und-ihre-überschreibung)
- [Benutzer](#users)
- [Scannen](#scanning)
- [Kategorien](#categories)
- [Bewertungskontexte](#bewertungskontexte)
- [Bewertung](#scoring)
- [Schwellenwerte](#thresholds)
- [Komposition](#composition)
- [EXIF-Anpassungen](#exif-adjustments)
- [Belichtung](#exposure)
- [Abzüge](#penalties)
- [Normalisierung](#normalization)
- [Modelle](#models)
- [Modelle zur Qualitätsbewertung](#quality-assessment-models)
- [Verarbeitung](#processing)
- [RAW-Dekodierung](#raw-dekodierung)
- [HDR-PQ-Tone-Mapping](#hdr-pq-tone-mapping)
- [Serienbild-Erkennung](#burst-detection)
- [Serienbild-Bewertung](#burst-scoring)
- [Duplikat-Erkennung](#duplicate-detection)
- [Gesichtserkennung](#face-detection)
- [Gesichts-Clustering](#face-clustering)
- [Gesichtsverarbeitung](#face-processing)
- [Monochrom-Erkennung](#monochrome-detection)
- [Verschlagwortung](#tagging)
- [Eigenständige Tags](#standalone-tags)
- [Analyse](#analysis)
- [Viewer](#viewer)
- [Performance](#performance)
- [Speicherung](#storage)
- [Plugins](#plugins)
- [Capsules](#capsules)
- [Ähnlichkeitsgruppen](#similarity-groups)
- [Szenen](#scenes)
- [OCR](#ocr)
- [Timeline](#timeline)
- [Karte](#map)
- [Übersetzung](#translation)

---

## Standardwerte und Ihre Überschreibung

`scoring_config.json` enthält **nur das, was Sie geändert haben**. Facet löst sie auf `config/scoring_config.default.json` auf; alles, was Sie weglassen, behält also den ausgelieferten Wert. Eine neue Installation hat keine `scoring_config.json` und läuft auf den Standardwerten.

Um das ästhetische Gewicht für Porträts zu erhöhen und ein Edition-Passwort zu setzen, sieht die gesamte Datei so aus:

```json
{
  "viewer": { "edition_password": "your-password" },
  "categories": [ ... ]
}
```

So werden beide Dateien kombiniert:

- **Objekte werden Schlüssel für Schlüssel zusammengeführt.** `{"performance": {"mmap_size_mb": 4096}}` ändert nur diese eine Einstellung; `cache_size_mb` und jeder andere `performance`-Schlüssel behalten ihre ausgelieferten Werte.
- **Arrays werden vollständig ersetzt.** Ein `categories`-Array in Ihrer Datei ersetzt das ausgelieferte vollständig. Die Reihenfolge zählt (`categories` gilt nach „erster Treffer gewinnt“, `scoring_contexts.*.promote` wird der Reihe nach gelesen), und eine Kategorie, die Sie in Ihrem Array weglassen, wird gelöscht.

Um ein Gewicht in einer Kategorie zu ändern, kopieren Sie das gesamte `categories`-Array aus `config/scoring_config.default.json`, bearbeiten Sie es und behalten Sie es in Ihrer Datei.

### Ein bestehendes Setup aktualisieren

Nichts zu tun: Eine vollständige `scoring_config.json` aus einer früheren Version funktioniert weiterhin. Jeder Facet-Schreibvorgang auf die Datei (Gewichte oder Prioritäten im Viewer speichern, eine Änderung der Panorama-Schwelle, der erste Login, der ein Klartext-Passwort aufwertet, ein Scan, bei dem `validate_weights` Gewichte korrigiert) schreibt sie als Überschreibung um und verwirft jeden Schlüssel, der dem ausgelieferten Standard entspricht.

So verdichten Sie sie auf Abruf, wobei zuvor eine `0600`-Sicherungskopie angelegt wird:

```bash
python database.py --compact-config
```

Das Ergebnis löst sich auf exakt dieselbe Konfiguration auf.

> **Hinweis:** Ein Wert, der dem ausgelieferten Standard entspricht, bleibt nicht in Ihrer Datei. Ändert eine spätere Version diesen Standard, ändert sich auch Ihr Verhalten. Um einen Wert festzunageln, muss er vom Standard abweichen.

## Users

Optionaler Mehrbenutzermodus. Enthält der Schlüssel `users` mindestens einen Benutzer, ersetzt eine benutzerspezifische Anmeldung die Authentifizierung mit einem einzigen Passwort.

```json
{
  "users": {
    "alice": {
      "password_hash": "salt_hex:dk_hex",
      "display_name": "Alice",
      "role": "superadmin",
      "directories": ["/volume1/Photos/Alice"]
    },
    "bob": {
      "password_hash": "salt_hex:dk_hex",
      "display_name": "Bob",
      "role": "user",
      "directories": ["/volume1/Photos/Bob"]
    },
    "shared_directories": [
      "/volume1/Photos/Family",
      "/volume1/Photos/Vacations"
    ]
  }
}
```

### Benutzerfelder

| Feld | Typ | Beschreibung |
|-------|------|-------------|
| `password_hash` | string | PBKDF2-HMAC-SHA256-Hash (`salt_hex:dk_hex`), erzeugt durch `--add-user` |
| `display_name` | string | Wird in der UI-Kopfzeile angezeigt |
| `role` | string | `user`, `admin` oder `superadmin` |
| `directories` | array | Private Fotoverzeichnisse dieses Benutzers (Abgleich: siehe [Geteilte Verzeichnisse](#geteilte-verzeichnisse)) |

### Geteilte Verzeichnisse

`shared_directories` (Geschwisterelement der Benutzerobjekte) listet Verzeichnisse auf, die für alle Benutzer sichtbar sind. Einträge in `directories` und `shared_directories` werden mit den Pfaden verglichen, die der Scanner gespeichert hat:

- Die ASCII-Groß-/Kleinschreibung wird unter Windows und macOS ignoriert, bei UNC- oder Laufwerksbuchstaben-Einträgen auf jedem Host.
- Anderswo (zum Beispiel unter Linux) kommt es auf die Groß-/Kleinschreibung an: Schreiben Sie jeden Eintrag genau so, wie der Scanner ihn gespeichert hat.
- Nicht behandelt: Unterschiede in der Groß-/Kleinschreibung außerhalb von ASCII sowie ein zugeordnetes Laufwerk, das der Host nicht auflösen kann.
- Ein leerer Eintrag gewährt nichts.

### Rollen

| Rolle | Eigene + geteilte ansehen | Bewerten/Favorisieren | Personen/Gesichter verwalten | Scans auslösen |
|------|:-:|:-:|:-:|:-:|
| `user` | ja | ja | nein | nein |
| `admin` | ja | ja | ja | nein |
| `superadmin` | ja | ja | ja | ja |

### Benutzer hinzufügen

Benutzer werden ausschließlich über das CLI erstellt; es gibt keine Registrierungs-UI oder -API:

```bash
python database.py --add-user alice --role superadmin --display-name "Alice"
# Fragt nach dem Passwort und schreibt den Hash in scoring_config.json
```

Bearbeiten Sie anschließend die `scoring_config.json`, um deren `directories` zu setzen.

### Abwärtskompatibilität

- Kein `users`-Schlüssel = Einzelbenutzermodus (unverändertes Verhalten).
- `viewer.password` und `viewer.edition_password` werden im Mehrbenutzermodus ignoriert.
- Vorhandene Bewertungen in der Tabelle `photos` bleiben für den Einzelbenutzermodus erhalten; `--migrate-user-preferences` kopiert sie.

---

## Scanning

Steuert, welche Verzeichnisse der Scan besucht.

```json
{
  "scanning": {
    "skip_hidden_directories": true,
    "skip_directories": ["@eaDir", "#recycle", "#snapshot", "@Recycle"]
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `skip_hidden_directories` | `true` | Überspringt Verzeichnisse, deren Name mit `.` beginnt |
| `skip_directories` | `["@eaDir", "#recycle", "#snapshot", "@Recycle"]` | Ordnernamen-Globs, die in beliebiger Tiefe übersprungen werden |

Hinweise zu `skip_directories`:

- Globs verwenden `fnmatch`, beachten die Groß-/Kleinschreibung und treffen nur den Ordnernamen.
- Die Standardwerte decken Synology `@eaDir` (die `SYNOPHOTO_THUMB_*.jpg`-Vorschaubilder), `#recycle`, `#snapshot` und QNAP `@Recycle` ab.
- Ihre Liste ersetzt den Standard; `[]` deaktiviert das Überspringen nach Namen. Das Scan-Stammverzeichnis wird nie übersprungen.
- Bereits aus diesen Ordnern indizierte Fotos bleiben in der Datenbank.

---

## Categories

Array von Kategoriedefinitionen. Siehe [Bewertung](SCORING.md) für den vollständigen Kategorieleitfaden.

Jede Kategorie hat:
- `name` - Kategoriebezeichner
- `priority` - Niedriger = höhere Priorität (wird zuerst ausgewertet)
- `filters` - Bedingungen für die Zuordnung
- `weights` - Gewichte der Bewertungsmetriken (Summe muss 100 ergeben)
- `modifiers` - Verhaltensanpassungen
- `tags` - CLIP-Vokabular für tagbasierte Zuordnung

> **Form- & Farbharmonie-Gewichte.** Der `weights`-Block jeder Kategorie hat fünf Schlüssel, die `--recompute-form` befüllt: `symmetry_percent`, `balance_percent`, `edge_entropy_percent`, `fractal_percent` und `color_harmony_percent`. Sie werden mit `0` ausgeliefert, sodass sich die Bewertungen nicht ändern, bis Sie einem ein Gewicht geben (führen Sie dann `--recompute-average` aus). Die Gewichte ergeben weiterhin in Summe 100.
> **`quality_percent` zählt zu `aesthetic`.** Die Qualität hat keinen eigenen Wert; deshalb wird `quality_percent` vor der Bewertung zu `aesthetic_percent` addiert. Siehe [SCORING.md](SCORING.md).
> **Die mitgelieferte Kategorie `astro` braucht ein dunkles Bild.** Neben einem ihrer Tags verlangt sie `luminance_max: 0.30` (mittlere Helligkeit höchstens 0.30); eine helle Szene mit dem Tag `aurora` oder `stars` ist also nicht `astro`. Hat Ihre `scoring_config.json` ein eigenes `categories`-Array, erhält dessen `astro`-Eintrag diesen Filter nicht: Tragen Sie `"luminance_max": 0.30` unter `astro.filters` ein oder löschen Sie das Array. `python facet.py --doctor` gibt einen „Config notice“ aus, wenn `astro` kein `luminance_max` hat. Führen Sie danach `--recompute-average` aus (nach einem Upgrade: zuerst `--recompute-silhouette`, dann `--recompute-average` zweimal; siehe [COMMANDS.md](COMMANDS.md)).

---

## Bewertungskontexte

Ein Bewertungskontext ändert, welche Kategorie für ein Album oder Foto gewinnt. Er zieht einige Kategorien an den Anfang der globalen `categories`-Reihenfolge vor und schließt andere aus; die übrigen behalten ihre Prioritätsreihenfolge. Verwenden Sie ihn, wenn die globale Reihenfolge für ein Shooting die falsche Kategorie wählt: Eine gegenlichtige Tanzaufnahme mit dem Tag `sports` wird von `silhouette` (Priorität 42) erfasst, bevor `sports` (Priorität 71) an die Reihe kommt. Gewichtsregler können das nicht beheben, denn sie ändern nur, wie die gewählte Kategorie bewertet.

```json
{
  "scoring_contexts": {
    "default": {
      "label_key": "comparison.context.default",
      "promote": [],
      "excluded": [],
      "suggest_from_moments": []
    },
    "action_stage": {
      "label_key": "comparison.context.action_stage",
      "promote": ["sports", "concert", "candid"],
      "excluded": ["silhouette"],
      "suggest_from_moments": ["sports", "concert", "nightlife"]
    }
  }
}
```

| Feld | Beschreibung |
|-------|-------------|
| `label_key` | i18n-Schlüssel für den Anzeigenamen des Kontexts |
| `promote` | Kategorien, die in der angegebenen Reihenfolge an den Anfang der Auswertungsreihenfolge gestellt werden |
| `excluded` | Kategorien, die unter diesem Kontext nie zugeordnet werden |
| `suggest_from_moments` | `narrative_moment`-Werte, die diesen Kontext für ein Album nahelegen (`GET /api/albums/{id}/suggested_context`, siehe [VIEWER.md](VIEWER.md)) |

**Effektive Reihenfolge** = `promote` (der Reihe nach) → die globale Prioritätsreihenfolge ohne vorgezogene und ausgeschlossene Namen → `default` (die Auffangkategorie, Priorität 999) zuletzt.

- Ein Name in `promote` und `excluded` ist ausgeschlossen.
- `default` kann nie vorgezogen oder ausgeschlossen werden.
- Ohne Kontext oder bei einem unbekannten Namen gilt die einfache globale Reihenfolge (ein unbekannter Name protokolliert eine Warnung).
- `python facet.py --validate-categories` meldet unbekannte Kategorienamen, Namen in beiden Listen und `suggest_from_moments`-Einträge, die kein Schlüssel von `narrative_moments.event_types.<default_event_type>` sind. Tippfehler bleiben sonst unbemerkt.

Mitgelieferte Voreinstellungen (`default` ist leer, sodass sich nichts ändert, bis Sie einen Kontext zuweisen):

| Context | Promotes | Excludes | Suggested from moments |
|---------|----------|----------|------------------------|
| `default` | – | – | – |
| `action_stage` | `sports`, `concert`, `candid` | `silhouette` | `sports`, `concert`, `nightlife` |
| `party_event` | `group_portrait`, `candid`, `food` | – | `celebration`, `group_gathering`, `dining` |
| `portrait_session` | `portrait`, `portrait_bw`, `fashion` | – | `portrait`, `children` |
| `wildlife` | `wildlife` | – | `nature_wildlife`, `pets` |
| `landscape` | `landscape`, `golden_hour`, `blue_hour` | – | `scenic_landscape`, `mountains`, `snow_winter` |
| `motorsport` | `sports`, `vehicle` | `silhouette` | `sports`, `road_vehicle` |

### Einen eigenen Kontext hinzufügen

Fügen Sie einen Schlüssel unter `scoring_contexts` hinzu, und er funktioniert wie eine mitgelieferte Voreinstellung: Sie können ihn einem Album zuweisen und im Tab **Bewertungskontext** bearbeiten.

```json
{
  "scoring_contexts": {
    "dance_comp": {
      "label_key": "comparison.context.dance_comp",
      "promote": ["sports", "concert"],
      "excluded": ["silhouette", "fashion"],
      "suggest_from_moments": ["sports"]
    }
  }
}
```

Hat `label_key` keine Übersetzung, zeigt die Auswahl den **`name`** des Kontexts (z. B. `dance_comp`). Fügen Sie den Schlüssel allen sechs `i18n/translations/*.json`-Paketen hinzu, um eine lokalisierte Bezeichnung zu erhalten.

### Einen Kontext bearbeiten

Ziehen Sie im Tab **Bewertungskontext** des Viewers (Edition-geschützt, `PUT /api/config/scoring_contexts/{name}`) Kategorien in die vorgezogene Liste oder verschieben Sie sie, klicken Sie eine Kategorie an, um ihren Ausschluss umzuschalten, und speichern Sie.

- Nur `promote` und `excluded` sind bearbeitbar; `label_key`, `suggest_from_moments` und andere Kontexte bleiben unverändert.
- Ein Speichern wird abgelehnt, wenn der Kontext nicht existiert, wenn ein Eintrag keine vorhandene Kategorie ist, wenn `default` in einer der beiden Listen steht oder wenn `promote` einen Namen wiederholt. Ein Name in beiden Listen wird akzeptiert (`excluded` gewinnt); eine Wiederholung innerhalb von `excluded` wird zusammengefasst.
- Jedes Speichern behält eine zeitgestempelte Kopie `.backup.<timestamp>` der Konfiguration.
- Das Bearbeiten eines Kontexts kategorisiert Fotos nicht neu: Führen Sie danach eine Neuberechnung aus (siehe [Prioritätsänderungen erfordern eine Neuberechnung](#die-globale-priorität-neu-ordnen)). Der Tab hat eine Schaltfläche **Jetzt neu berechnen**.

### Einen Kontext zuweisen

Weisen Sie einen Kontext **pro Album** mit `PUT /api/albums/{id}/scoring_context` zu (Edition-geschützt).

- Er gilt für jedes Foto, das in diesem Moment im Album ist, außer für Fotos, deren Kontext Sie von Hand gesetzt haben.
- Ein später zu einem manuellen Album hinzugefügtes Foto übernimmt den Kontext. Ein neues Foto, das dem Filter eines intelligenten Albums entspricht, tut das nicht; rufen Sie `PUT` erneut auf, um ihn anzuwenden.
- Ein intelligentes Album verwendet seinen gespeicherten Filter, nicht die Ausblend-Umschalter der Galerie, und kann daher mehr Fotos umfassen, als seine Galerieansicht zeigt.
- `DELETE /api/albums/{id}/scoring_context` entfernt den Kontext von den Fotos, die dieses Album gesetzt hat. Manuelle Entscheidungen bleiben.
- Das Entfernen von Fotos aus einem Album (`DELETE /api/albums/{id}/photos`) entfernt den Kontext dieses Albums von ihnen. Ein Foto, das noch in einem anderen Album mit Kontext ist, übernimmt den Kontext dieses Albums.
- `GET /api/albums/{id}/suggested_context` schlägt über `suggest_from_moments` einen Kontext anhand des vorherrschenden `narrative_moment` des Albums vor. Es ändert nichts.

Für ein einzelnes hartnäckiges Foto verwenden Sie eine **Kategorieüberschreibung**: `POST /api/comparison/override_category` (Edition-geschützt) setzt die Kategorie direkt, und `POST /api/comparison/clear_category_override` entfernt sie. Eine Überschreibung gewinnt gegenüber jedem Kontext.

Überschreibungen und Kontexte überstehen erneutes Scannen. Ein numerischer Filter scheitert unabhängig vom Kontext weiterhin, wenn sein EXIF-Wert fehlt — siehe [Bewertung – die Falle fehlender EXIF-Daten](SCORING.md#die-falle-fehlender-exif-daten).

### Die globale Priorität neu ordnen

`GET|POST /api/config/category_priorities` (Edition-geschützt) liest und speichert die globale Reihenfolge, von der jeder Kontext ausgeht. Der Viewer ordnet die vorhandenen Prioritätszahlen um, statt neu durchzunummerieren.

- `default` (Priorität 999) bleibt am Ende und kann nicht verschoben werden.
- Eine Kategorie mit fehlender oder doppelter Priorität erhält beim Speichern einen neuen Wert oberhalb des aktuellen Maximums.
- Jedes Speichern behält eine zeitgestempelte Kopie `.backup.<timestamp>` von `scoring_config.json`; die 20 neuesten bleiben erhalten.

**Das Ändern von Prioritäten erfordert eine Neuberechnung.** Eine Neuordnung ändert nicht die gespeicherte `category` eines Fotos. Führen Sie `python facet.py --recompute-average` aus oder starten Sie `POST /api/scan/recompute` über den Viewer (Edition-geschützt) und verfolgen Sie `GET /api/scan/recompute_status`.

- Eine Neuberechnung und ein Scan können nicht gleichzeitig laufen: Das CLI verweigert sich, und der Viewer meldet, welcher Job die Bibliothek hält.
- Zwei von einem Terminal gestartete Scans erzeugen nur eine Warnung (`--resume` verweigert sich).
- Ist `normalization.per_category` aktiviert, muss eine Neuberechnung unter Umständen zweimal laufen — siehe [Normalization](#normalization).

---

## Scoring

```json
{
  "scoring": {
    "score_min": 0.0,
    "score_max": 10.0,
    "score_precision": 2
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `score_min` | `0.0` | Minimal mögliche Bewertung |
| `score_max` | `10.0` | Maximal mögliche Bewertung |
| `score_precision` | `2` | Nachkommastellen der Bewertungen |

---

## Thresholds

Bewertungsschwellen. Übrig ist nur `blink_penalty_percent`. Ob ein Foto ein Porträt, eine Nachtaufnahme oder eine Langzeitbelichtung ist, entscheiden die `filters` der jeweiligen Kategorie (siehe [Kategorien](#categories)), nicht dieser Block.

```json
{
  "thresholds": {
    "blink_penalty_percent": 50
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `blink_penalty_percent` | `50` | Bewertungsmultiplikator bei erkanntem Blinzeln (0,5x) |

---

## Composition

Regelbasierte Kompositionsbewertung (verwendet, wenn SAMP-Net nicht aktiv ist).

```json
{
  "composition": {
    "power_point_weight": 2.0,
    "line_weight": 1.0
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `power_point_weight` | `2.0` | Gewicht für die Platzierung nach Drittelregel |
| `line_weight` | `1.0` | Gewicht für Führungslinien |

---

## EXIF Adjustments

Automatische Bewertungsanpassungen basierend auf Kameraeinstellungen.

```json
{
  "exif_adjustments": {
    "iso_sharpness_compensation": true,
    "aperture_isolation_boost": true
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `iso_sharpness_compensation` | `true` | Reduziert den Schärfeabzug bei hohem ISO-Wert |
| `aperture_isolation_boost` | `true` | Verstärkt die Freistellung bei offenen Blenden (f/1.4–f/2.8) |

---

## Exposure

Steuert die Belichtungsanalyse und die Erkennung von Beschnitt (Clipping).

```json
{
  "exposure": {
    "shadow_clip_threshold_percent": 15,
    "highlight_clip_threshold_percent": 10,
    "silhouette_detection": true
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `shadow_clip_threshold_percent` | `15` | Markieren, wenn > 15 % der Pixel reines Schwarz sind |
| `highlight_clip_threshold_percent` | `10` | Markieren, wenn > 10 % der Pixel reines Weiß sind |
| `silhouette_detection` | `true` | Bei `true` überspringt ein Foto mit gesetztem `is_silhouette` die Clipping-Strafe in seiner Gesamtwertung. Das Flag selbst ist nicht konfigurierbar: Es stammt aus einer festen, gesichtsbezogenen Regel (siehe [SCORING.md](SCORING.md)) |

---

## Penalties

Bewertungsabzüge für technische Probleme.

```json
{
  "penalties": {
    "noise_sigma_threshold": 4.0,
    "noise_max_penalty_points": 1.5,
    "noise_penalty_per_sigma": 0.3,
    "leading_lines_blend_percent": 30,
    "oversaturation_threshold": 0.9,
    "oversaturation_penalty_points": 0.5
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `noise_sigma_threshold` | `4.0` | Rauschen oberhalb dieses Werts löst einen Abzug aus |
| `noise_max_penalty_points` | `1.5` | Maximaler Rauschabzug |
| `noise_penalty_per_sigma` | `0.3` | Punkte pro Sigma oberhalb des Schwellenwerts |
| `leading_lines_blend_percent` | `30` | Einmischung in comp_score |
| `oversaturation_threshold` | `0.9` | Schwellenwert für mittlere Sättigung |
| `oversaturation_penalty_points` | `0.5` | Abzug für Übersättigung |

**Formel für den Rauschabzug:**

```
penalty = min(noise_max_penalty_points, (noise_sigma - threshold) * noise_penalty_per_sigma)
```

---

## Normalization

Steuert, wie Rohmetriken auf Bewertungen von 0–10 skaliert werden.

```json
{
  "normalization": {
    "method": "percentile",
    "percentile_target": 90,
    "per_category": true,
    "category_min_samples": 50
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `method` | `"percentile"` | Normalisierungsmethode |
| `percentile_target` | `90` | 90. Perzentil = Bewertung von 10,0 |
| `per_category` | `true` | Kategoriespezifische Normalisierung |
| `category_min_samples` | `50` | Mindestanzahl an Fotos für die kategoriespezifische Normalisierung |

> **Hinweis:** Ist `per_category` aktiviert, pendelt sich eine einzelne Neuberechnung nicht ein. Perzentile werden nach der *gespeicherten* Kategorie jedes Fotos gruppiert, bevor die Neuberechnung sie neu zuweist. Führen Sie nach einer Änderung, die Fotos zwischen Kategorien verschiebt (Prioritäten, ein Bewertungskontext, eine Kategorieüberschreibung), `--recompute-average` zweimal aus.

---

## Models

Wählt aus, welche Modelle je VRAM-Profil verwendet werden.

```json
{
  "models": {
    "vram_profile": "auto",
    "keep_in_ram": "auto",
    "profiles": {
      "legacy": {
        "aesthetic_model": "clip-mlp",
        "clip_config": "clip_legacy",
        "composition_model": "samp-net",
        "tagging_model": "clip",
        "supplementary_pyiqa": ["topiq_iaa", "topiq_nr_face", "liqe"],
        "saliency_enabled": true,
        "description": "CPU: CLIP-MLP aesthetic + SAMP-Net composition + CLIP tagging + TOPIQ IAA/NR-Face/LIQE + BiRefNet saliency (8GB+ RAM; saliency/IQA are slower on CPU)"
      },
      "8gb": {
        "aesthetic_model": "clip-mlp",
        "clip_config": "clip_legacy",
        "composition_model": "samp-net",
        "tagging_model": "clip",
        "supplementary_pyiqa": ["topiq_iaa", "topiq_nr_face", "liqe"],
        "saliency_enabled": true,
        "description": "CLIP-MLP aesthetic + SAMP-Net composition + CLIP tagging + TOPIQ IAA/NR-Face/LIQE + BiRefNet saliency (6-14GB VRAM)"
      },
      "16gb": {
        "aesthetic_model": "topiq",
        "clip_config": "clip",
        "composition_model": "samp-net",
        "tagging_model": "qwen3.5-2b",
        "supplementary_pyiqa": ["topiq_iaa", "topiq_nr_face", "liqe"],
        "saliency_enabled": true,
        "description": "TOPIQ aesthetic + SigLIP 2 embeddings + Qwen3.5-2B tagging (~14GB VRAM)"
      },
      "24gb": {
        "aesthetic_model": "topiq",
        "clip_config": "clip",
        "composition_model": "samp-net",
        "tagging_model": "qwen3.5-4b",
        "supplementary_pyiqa": ["topiq_iaa", "topiq_nr_face", "liqe"],
        "saliency_enabled": true,
        "description": "TOPIQ aesthetic + SigLIP 2 embeddings + Qwen3.5-4B tagging (~18GB VRAM)"
      }
    },
    "clip": {
      "model_name": "google/siglip2-so400m-patch16-naflex",
      "backend": "transformers",
      "embedding_dim": 1152,
      "tag_threshold_percent": 8,
      "search_threshold_percent": 5
    },
    "clip_legacy": {
      "model_name": "ViT-L-14",
      "pretrained": "laion2b_s32b_b82k",
      "embedding_dim": 768,
      "tag_threshold_percent": 8,
      "search_threshold_percent": 15
    },
    "qwen2_vl": {
      "model_path": "Qwen/Qwen2-VL-2B-Instruct",
      "torch_dtype": "bfloat16",
      "max_new_tokens": 256
    },
    "qwen3_5_2b": {
      "model_path": "Qwen/Qwen3.5-2B",
      "torch_dtype": "bfloat16",
      "max_new_tokens": 100,
      "vlm_batch_size": 4
    },
    "qwen3_5_4b": {
      "model_path": "Qwen/Qwen3.5-4B",
      "torch_dtype": "bfloat16",
      "max_new_tokens": 100,
      "vlm_batch_size": 2
    },
    "saliency": {
      "model": "ZhengPeng7/BiRefNet_dynamic",
      "resolution": 1024,
      "mask_threshold": 0.3,
      "min_subject_pixels": 50
    },
    "samp_net": {
      "model_path": "pretrained_models/samp_net.pth"
    }
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `vram_profile` | `"auto"` | Aktives Profil (`auto`, `legacy`, `8gb`, `16gb`, `24gb`); `FACET_VRAM_PROFILE` überschreibt es (siehe unten) |
| `keep_in_ram` | `"auto"` | Modelle zwischen Multi-Pass-Chunks im RAM halten (`"auto"`, `"always"`, `"never"`); `auto` prüft zuerst den freien RAM |
| `ram_cache_reserve_gb` | `4.0` (optional, nicht in der mitgelieferten Datei) | RAM (GB), der unter `"auto"` neben einem gecachten Modell frei bleiben muss |
| `profiles.*.supplementary_pyiqa` | `["topiq_iaa", "topiq_nr_face", "liqe"]` | PyIQA-Modelle, die für dieses Profil ausgeführt werden (alle vier Profile führen den vollständigen Satz aus) |
| `profiles.*.saliency_enabled` | `true` (alle Profile) | BiRefNet-Subjekt-Saliency für dieses Profil ausführen |
| `clip.model_name` | `"google/siglip2-so400m-patch16-naflex"` | SigLIP 2 NaFlex Embedding-Modell (16gb/24gb) |
| `clip.backend` | `"transformers"` | `"transformers"` (SigLIP 2 NaFlex) oder `"open_clip"` (legacy) |
| `clip.embedding_dim` | `1152` | Embedding-Dimensionen (1152 für SigLIP 2) |
| `clip.tag_threshold_percent` | `8` | Minimale Ähnlichkeit für eine **Tag**-Übereinstimmung beim SigLIP-2-Tagger der Profile `16gb`/`24gb` (ersetzt `similarity_threshold_percent`) |
| `clip.search_threshold_percent` | `5` | Minimale Ähnlichkeit für die semantische Suche (`GET /api/search`); ganze Zahl `0-50` |
| `clip_legacy.model_name` | `"ViT-L-14"` | Legacy-CLIP-Modell (Profile legacy/8gb) |
| `clip_legacy.pretrained` | `"laion2b_s32b_b82k"` | Legacy-Pretrained-Gewichte |
| `clip_legacy.embedding_dim` | `768` | Legacy-Embedding-Dimensionen |
| `clip_legacy.tag_threshold_percent` | `8` | Dieselbe Tag-Schwelle für den CLIP-Tagger der Profile `legacy`/`8gb`; `tagging.max_tags` begrenzt die Anzahl |
| `clip_legacy.search_threshold_percent` | `15` | Schwelle der semantischen Suche auf dem Profil `legacy`/`8gb`; ganze Zahl `0-50` |
| `qwen2_vl.model_path` | `"Qwen/Qwen2-VL-2B-Instruct"` | Modell für das manuelle Opt-in `composition_model: "qwen2-vl-2b"` (kein Profil verwendet es) |
| `qwen3_5_2b.model_path` | `"Qwen/Qwen3.5-2B"` | Verschlagwortungsmodell für das Profil 16gb |
| `qwen3_5_2b.vlm_batch_size` | `4` | Bilder pro VLM-Inferenz-Batch |
| `qwen3_5_4b.model_path` | `"Qwen/Qwen3.5-4B"` | Verschlagwortungsmodell für das Profil 24gb |
| `qwen3_5_4b.vlm_batch_size` | `2` | Bilder pro VLM-Inferenz-Batch |
| `saliency.model` | `"ZhengPeng7/BiRefNet_dynamic"` | BiRefNet-Saliency-Modell |
| `saliency.resolution` | `1024` | Inferenzauflösung |
| `saliency.mask_threshold` | `0.3` | Sigmoid-Schwellenwert für die binäre Subjektmaske |
| `saliency.min_subject_pixels` | `50` | Mindestanzahl an Subjektpixeln, um ein Subjekt als erkannt zu werten |

Hinweise:

- **`ram_cache_reserve_gb`:** Ein Modell bleibt nur im RAM, solange der freie RAM seine Größe plus diese Reserve übersteigt. `"always"` überspringt die Prüfung; `"never"` cacht nichts. Es muss eine Zahl >= 0 sein, sonst stoppt der Scan beim Start. Unter Speicherdruck gibt der Cache zuerst das Modell ab, das am spätesten wieder benötigt wird (siehe [Funktionsweise von Multi-Pass](#funktionsweise-von-multi-pass)).
- **Tag- vs. Suchschwellen:** `tag_threshold_percent` steuert das Tagging (Scan, `--recompute-tags`, `tag_existing.py`). `search_threshold_percent` ist der Standardwert des 0-50%-Suchreglers der Galerie (`search_threshold_default` in `/api/config`). Der SigLIP-Standard `5` begünstigt den Recall: Bei einer Stichprobe von 34 Fotos behielt er alle 21 echten Treffer und ließ 3 von 13 Nicht-Treffern durch.

**Semantische Suche und eine unter einem anderen Profil eingebettete Bibliothek:** `GET /api/search` wählt den Text-Encoder und dessen `search_threshold_percent` aus dem Block `clip` bzw. `clip_legacy`, der zur *gespeicherten* Embedding-Dimension passt, nicht zum aktiven `vram_profile`. Eine Bibliothek, die mit 768-dim CLIP eingebettet wurde und auf einem 16gb-Rechner durchsucht wird, sucht daher mit `clip_legacy`. Passt die gespeicherte Dimension zu keinem der beiden Blöcke, wird der Block des aktiven Profils verwendet.

### Automatische VRAM-Erkennung

Ist `vram_profile` auf `"auto"` (Standard) gesetzt, erkennt Facet beim Start den GPU-VRAM und wählt das größte passende Profil:

| Erkannter VRAM | Ausgewähltes Profil |
|---------------|------------------|
| ≥ 20GB | `24gb` |
| ≥ 14GB | `16gb` |
| ≥ 6GB | `8gb` |
| Keine GPU | `legacy` (verwendet System-RAM) |

Eine CUDA-GPU zählt nur, wenn PyTorch sie sehen kann. Ohne sichtbares Gerät (zum Beispiel mit `CUDA_VISIBLE_DEVICES=''`) läuft der Scan auf dem Prozessor, meldet 0 GB VRAM und wählt `legacy`. `FACET_DEVICE=cuda` ohne sichtbares Gerät bricht mit „FACET_DEVICE=cuda was requested, but that device is not available“ ab.

**Karten mit 10-14 GB können sich für den vollen Funktionsumfang entscheiden.** Die automatische Erkennung wählt unterhalb von 14 GB weiterhin `8gb`. Setzen Sie `"vram_profile": "16gb"` oder `FACET_VRAM_PROFILE=16gb`, um SigLIP 2, TOPIQ, Tagging mit Qwen3.5-2B, Q-ReAlign und Salienz auszuführen. Die Modelle laufen dann in vier Durchläufen, bei einer Karte, die 11,8 GiB oder mehr meldet, in drei (siehe [Dynamische Durchlauf-Gruppierung](#dynamische-durchlauf-gruppierung)). Ein Foto, das die Salienz dennoch nicht bewerten kann, speichert NULL und protokolliert einen ERROR.

> **Warnung:** Der Wechsel einer bestehenden `8gb`-Bibliothek zu `16gb` ändert das Embedding-Modell (CLIP ViT-L-14 mit 768 Dimensionen → SigLIP 2 mit 1152 Dimensionen). Scannen Sie erneut oder führen Sie `--recompute-embeddings` aus, sonst mischt die Bibliothek zwei Embedding-Größen. Bis dahin verhält sich die Suche wie unter *Semantische Suche und eine unter einem anderen Profil eingebettete Bibliothek* im Abschnitt [Models](#models) beschrieben.

### Override über die Umgebungsvariable `FACET_VRAM_PROFILE`

`FACET_VRAM_PROFILE` überschreibt `models.vram_profile` beim Laden, sodass eine einzige eingebundene Konfiguration jedes Docker-Profil bedienen kann. Zulässige Werte: `auto`, `legacy`, `8gb`, `16gb`, `24gb`; jeder andere Wert wird mit einer Warnung ignoriert. Die Docker-Compose-Overlays (`docker-compose.{legacy,8gb,16gb,24gb}.yml`) setzen die Variable für Sie.

Das Override wird nie in `scoring_config.json` zurückgeschrieben. Ein `vram_profile`, das Sie selbst in die Datei geschrieben haben, gilt weiterhin, wenn die Variable nicht gesetzt ist.

```bash
FACET_VRAM_PROFILE=8gb python facet.py /path/to/photos
```

---

## Quality Assessment Models

Wählt das Modell aus, das Bildqualität/Ästhetik bewertet, über die Bibliothek [pyiqa](https://github.com/chaofengc/IQA-PyTorch).

```json
{
  "quality": {
    "model": "auto",
    "prefer_llm": false
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `model` | `"auto"` | Qualitätsmodell: `auto`, `topiq`, `hyperiqa`, `dbcnn`, `musiq`, `clip-mlp`. `auto` verwendet `topiq`. |
| `prefer_llm` | `false` | Bevorzugt einen LLM-basierten Bewerter, sofern verfügbar |

### Verfügbare Qualitätsmodelle

SRCC = Spearman-Rangkorrelationskoeffizient auf dem KonIQ-10k-Benchmark (1,0 = perfekt).

| Modell | SRCC | VRAM | Anmerkungen |
|-------|------|------|-------|
| `topiq` | 0.93 | ~2GB | Standard (`auto`); ResNet50-Backbone mit Top-down-Attention |
| `hyperiqa` | 0.90 | ~2GB | Hyper-Netzwerk, inhaltsadaptiv |
| `dbcnn` | 0.90 | ~2GB | Dual-Branch-CNN (synthetische + authentische Störungen) |
| `musiq` | 0.87 | ~2GB | Multi-Scale-Transformer; verarbeitet jede Auflösung |
| `clipiqa+` | 0.86 | ~4GB | CLIP mit gelernten Quality-Prompts |
| `clip-mlp` | 0.76 | ~4GB | Legacy CLIP ViT-L-14 + MLP-Head |

### Qualitätsmodelle wechseln

1. Bearbeiten Sie `scoring_config.json`:
   ```json
   "quality": {
     "model": "topiq"
   }
   ```

2. Vorhandene Fotos neu bewerten (optional):
   ```bash
   python facet.py /path --pass quality
   python facet.py --recompute-average
   ```

---

## Processing

Einstellungen für die GPU-Batch-Verarbeitung und den Multi-Pass-Modus.

```json
{
  "processing": {
    "mode": "auto",
    "gpu_batch_size": 16,
    "ram_chunk_size": 32,
    "num_workers": 4,
    "auto_tuning": {
      "enabled": true,
      "monitor_interval_seconds": 5,
      "tuning_interval_images": 32,
      "min_processing_workers": 1,
      "max_processing_workers": 32,
      "min_gpu_batch_size": 2,
      "max_gpu_batch_size": 32,
      "min_ram_chunk_size": 10,
      "max_ram_chunk_size": 128,
      "memory_limit_percent": 85,
      "cpu_target_percent": 85,
      "metrics_print_interval_seconds": 30
    },
    "thumbnails": {
      "photo_size": 640,
      "photo_quality": 80,
      "face_padding_ratio": 0.3
    }
  }
}
```

### Schlüsselkonzepte

- **`gpu_batch_size`**: Bilder, die zusammen in einem GPU-Forward-Pass verarbeitet werden. Durch den VRAM begrenzt; die automatische Optimierung reduziert den Wert, wenn der GPU-Speicher das Limit überschreitet.
- **`ram_chunk_size`**: Bilder, die zwischen Modelldurchläufen im RAM gehalten werden (nur Multi-Pass), sodass jedes Bild pro Chunk einmal von der Platte gelesen wird. Durch `memory_limit_percent` begrenzt. Die automatische Optimierung senkt den Wert sofort, wenn der Speicher das Limit überschreitet, und erhöht ihn erst nach einem Chunk, dessen *Spitzenauslastung* unter dem Limit blieb.

### Einstellungsreferenz

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `mode` | `"auto"` | Verarbeitungsmodus: `auto`, `multi-pass`, `single-pass`. Nur `single-pass` wählt Single-Pass; `auto` läuft immer als Multi-Pass |
| `gpu_batch_size` | `16` | Bilder pro GPU-Batch (VRAM-begrenzt) |
| `ram_chunk_size` | `32` | Bilder pro RAM-Chunk (Multi-Pass) |
| `num_workers` | `4` | Threads zum Laden von Bildern |
| `load_workers` | `num_workers` | Threads zum Laden von Multi-Pass-Chunks (auf 8 begrenzt, `1` = sequenziell) |
| `raw_decode_concurrency` | `0` (auto) | Maximale gleichzeitige RAW-Dekodierungen; automatisch aus CPU/RAM bemessen (1–4), `1` = vollständig serialisiert |
| `raw_decode_timeout_seconds` | `120` | Abbruch einer hängenden RAW-Dekodierung nach dieser Verzögerung (`0` = deaktiviert); der Scan bricht nach wiederholten Hängern schnell ab |
| `exif_prefetch` | `true` | Single-Pass-Modus: EXIF im Hintergrund vorab laden, statt den GPU-Thread zu blockieren |
| **auto_tuning** | | |
| `enabled` | `true` | Auto-Tuning aktivieren |
| `monitor_interval_seconds` | `5` | Intervall der Ressourcenprüfung |
| `tuning_interval_images` | `32` | Alle N Bilder neu optimieren |
| `min_processing_workers` | `1` | Minimale Lade-Threads |
| `max_processing_workers` | `32` | Maximale Lade-Threads |
| `min_gpu_batch_size` | `2` | Minimale GPU-Batchgröße |
| `max_gpu_batch_size` | `32` | Maximale GPU-Batchgröße |
| `min_ram_chunk_size` | `10` | Minimale RAM-Chunkgröße |
| `max_ram_chunk_size` | `128` | Maximale RAM-Chunkgröße |
| `memory_limit_percent` | `85` | Prozentsatz des effektiven Speicherlimits (cgroup-Limit unter einem Container-Limit, sonst Host-RAM) |
| `cpu_target_percent` | `85` | Zielwert für die CPU-Auslastung |
| `metrics_print_interval_seconds` | `30` | Intervall für die Statistikausgabe |
| **thumbnails** | | |
| `photo_size` | `640` | Größe gespeicherter Thumbnails (Pixel) |
| `photo_quality` | `80` | JPEG-Qualität der Thumbnails |
| `face_padding_ratio` | `0.3` | Rand um Gesichtsausschnitte |

### Verarbeitungsmodi

| Modus | Beschreibung |
|------|-------------|
| `auto` | Läuft immer als Multi-Pass (Standard); nur `single-pass` wählt Single-Pass |
| `multi-pass` | Sequenzielles Laden der Modelle (funktioniert mit begrenztem VRAM) |
| `single-pass` | Alle Modelle gleichzeitig geladen (viel VRAM); nur Profile `legacy`/`8gb` |

Bei `16gb`/`24gb` (Ästhetik mit TOPIQ) protokolliert `single-pass` eine Warnung und läuft als Multi-Pass, außer im kommerziellen Modus (siehe [Lizenzierung](#lizenzierung)).

### Funktionsweise von Multi-Pass

Anstatt alle Modelle gleichzeitig zu laden, geht Multi-Pass wie folgt vor:

1. Lädt Bilder in RAM-Chunks (Standard `ram_chunk_size`: 32)
2. Führt für jeden Chunk die Modelle sequenziell aus: Modell laden → Chunk verarbeiten → Modell entladen
3. Kombiniert die Ergebnisse in einem abschließenden Aggregationsdurchlauf

Jedes Bild wird einmal pro Chunk dekodiert und von allen Durchläufen gemeinsam genutzt. Durchläufe werden so gruppiert, dass sie in den verfügbaren VRAM passen, sodass auch die größeren VLMs auf kleinen Karten laufen.

- Die Loader-Threads berechnen außerdem EXIF, technische Metriken, die regelbasierte Komposition, den Perceptual Hash und eine gemeinsame 1024-px-Kopie für die pyiqa-Modelle und Q-ReAlign.
- Ein Kompositionsfehler lässt nur dieses eine Foto scheitern. Er wird in `scan_failures` unter der Stufe `composition` erfasst; Wiederholung mit `--retry-failed`.
- Auf einer CUDA-GPU wird ein Chunk dekodiert, während die nächsten Modelle laden, sofern der freie Host-Speicher es zulässt und `keep_in_ram` nicht `"never"` ist. Andernfalls (und immer auf CPU und Apple MPS) wird er zuerst dekodiert. Die Ergebnisse sind in beiden Fällen identisch.
- Wird der Speicher vor einem Chunk knapp, gibt der RAM-Cache zuerst das Modell ab, das am spätesten wieder benötigt wird, und hält `ram_cache_reserve_gb` frei.
- Die Scan-Zusammenfassung meldet `Plane rebuilds`, `I/O wait (scan thread blocked on decode)` und `Decode wall`.

### Auto-Tuning-Verhalten

Facet überwacht die Ressourcennutzung und passt wie folgt an. `memory_limit_percent` wird gegen das *effektive* Speicherlimit gemessen: das cgroup-Limit unter einer Container-Begrenzung (Docker `mem_limit`, Podman `--memory`, Kubernetes `resources.limits.memory`), sonst der Host-RAM. `85` gegen eine 8GB-Begrenzung ergibt also ~6,8GB.

| Metrik | Aktion |
|--------|--------|
| GPU-Speicher > Limit | `gpu_batch_size` um 25 % reduzieren |
| Speicherauslastung > Limit | `ram_chunk_size` um 25 % reduzieren (sofort) |
| Ein abgeschlossener Chunk, dessen Spitzenauslastung < (Limit − 20 %) blieb | `ram_chunk_size` um 25 % erhöhen |
| CPU > Ziel | Weniger Worker vorschlagen |
| Queue-Timeouts > 5 % | Mehr Worker vorschlagen |

### Dynamische Durchlauf-Gruppierung

Wenn der VRAM es zulässt, laufen mehrere Modelle im selben Durchlauf:

| VRAM | Durchlauf 1 | Durchlauf 2 | Durchlauf 3 | Durchlauf 4 |
|---|---|---|---|---|
| 8GB (Profil `8gb`) | CLIP | Q-ReAlign + Salienz | TOPIQ IAA + TOPIQ NR-Face + LIQE | SAMP-Net + InsightFace |
| 12GB\* (Profil `16gb`, Opt-in) | Qwen3.5-Tagger + Q-ReAlign | SigLIP + Salienz + TOPIQ IAA | TOPIQ + TOPIQ NR-Face + LIQE + SAMP-Net | InsightFace |
| 16GB (Profil `16gb`) | Qwen3.5-Tagger + SigLIP + TOPIQ | Q-ReAlign + Salienz + TOPIQ IAA + TOPIQ NR-Face + LIQE + SAMP-Net | InsightFace | - |
| 24GB (Profil `24gb`) | Qwen3.5-4B-Tagger + SigLIP + Q-ReAlign + Salienz | TOPIQ + TOPIQ IAA + TOPIQ NR-Face + LIQE + SAMP-Net + InsightFace | - | - |
| 35GB+ (Profil `24gb`) | Alle Modelle zusammen (Single-Pass) | - | - | - |

Die Zeilen sind die Pläne für Karten, die 8,0, 11,7, 15,99 und 23,99 GiB Gesamt-VRAM melden; ab 34,8 GiB wird ein einziger Durchlauf geplant. Der Planer hält 1,3 GiB für CUDA, ONNX Runtime und den Desktop frei. Eine 12-GB-Karte wird nicht automatisch ausgewählt (siehe [Automatische VRAM-Erkennung](#automatische-vram-erkennung)): Setzen Sie `"vram_profile": "16gb"` oder `FACET_VRAM_PROFILE=16gb`.

\* Die Zeile 12GB gilt für eine Karte, die 11,7 GiB meldet. Eine Karte, die 11,8 GiB oder mehr meldet (zum Beispiel 11,99 GiB), plant stattdessen drei Durchläufe: Qwen3.5-Tagger + Q-ReAlign; SigLIP + Salienz + TOPIQ; TOPIQ IAA + TOPIQ NR-Face + LIQE + SAMP-Net + InsightFace.

### CLI-Optionen

```bash
# Standard: automatischer Multi-Pass mit optimaler Gruppierung
python facet.py /path/to/photos

# Single-Pass erzwingen (alle Modelle gleichzeitig geladen; nur Profile legacy/8gb, bei 16gb/24gb Warnung und Multi-Pass)
python facet.py /path --single-pass

# Nur einen bestimmten Durchlauf ausführen
python facet.py /path --pass quality       # nur TOPIQ
python facet.py /path --pass quality-iaa   # TOPIQ IAA (ästhetischer Wert)
python facet.py /path --pass quality-face  # TOPIQ NR-Face
python facet.py /path --pass quality-liqe  # LIQE (Qualität + Verzerrung)
python facet.py /path --pass tags          # nur konfigurierter Tagger
python facet.py /path --pass composition   # nur SAMP-Net
python facet.py /path --pass faces         # nur InsightFace
python facet.py /path --pass embeddings    # nur CLIP/SigLIP-Embeddings
python facet.py /path --pass saliency      # BiRefNet-Subjekt-Saliency

# Verfügbare Modelle auflisten
python facet.py --list-models
```

---

## RAW-Dekodierung

Wie RAW-Dateien in Pixel umgewandelt werden. Facet verwendet zwei Profile:

- **Metrik-Profil**: das Demosaicing, aus dem jede Bewertung berechnet wird (und der Pixelraum von Gesichtsboxen und `image_width`/`image_height`). Ein einziger fester Belichtungsgain für die gesamte Bibliothek, keine Anpassung pro Aufnahme.
- **Anzeige-Profil**: was die gespeicherte Miniaturansicht, die Galerie und `/image` zeigen. Es bevorzugt die in der Kamera eingebettete Vorschau (Tonwertkurve und Belichtung der Kamera selbst) und fällt auf das Demosaicing des Metrik-Profils zurück.

```json
"raw_decode": {
  "bright": 1.62,
  "prefer_embedded_preview": true,
  "preview_min_sensor_ratio": 0.5,
  "viewer_concurrency": 3,
  "faithful_bracket_render": true
}
```

| Einstellung | Standard | Beschreibung |
|-------------|----------|---------------|
| `bright` | `1.62` | Fester Belichtungsgain für jedes Demosaicing (`1.0` = LibRaws eigenes Niveau; `1.62` ≈ darktables +0,7 EV) |
| `prefer_embedded_preview` | `true` | Die Kameravorschau zeigen, wenn eine vorhanden ist; `false` führt für alles ein Demosaicing durch (langsamer, keine Tonwertkurve der Kamera) |
| `preview_min_sensor_ratio` | `0.5` | Anteil des Sensors, den eine Vorschau abdecken muss, damit `/image` sie statt eines Demosaicings verwendet |
| `viewer_concurrency` | `3` | Maximale gleichzeitige RAW-Demosaicings für `/image` und `/thumbnail` des Viewers, getrennt von `processing.raw_decode_concurrency` |
| `faithful_bracket_render` | `true` | Belichtungsreihen-Aufnahmen ganz ohne Korrektur zeigen (keine Vorschau, kein `bright`-Gain); siehe [unten](#belichtungsreihen-werden-unkorrigiert-gerendert) |

Hinweise:

- `bright` ist die einzige willkürliche Konstante hier. Prüfen Sie sie vor einem großen Scan mit `--check-raw-rendering` an Ihrer Bibliothek.
- Nikon, Pentax, Samsung und Canon CR3 betten eine nahezu formatfüllende Vorschau ein (0,98-0,99). Panasonic liegt bei 0,52. Olympus, Fuji, Sony und DNG betten eine kleine Vorschau ein (0,29-0,49) und werden daher demosaict.

### Speicher-Trade-off

`viewer_concurrency` und `processing.raw_decode_concurrency` sind getrennte Budgets. Im schlechtesten Fall laufen beide gleichzeitig, und jedes Demosaicing erreicht eine Spitze von etwa 200-400 MB. Senken Sie `viewer_concurrency` auf einem speicherbeschränkten Host. In der Praxis nutzen nur Sony-, Fuji-, Olympus- und DNG-Dateien das Viewer-Budget, weil die anderen eine ausreichend große Vorschau haben.

### Warum es keine automatische Aufhellung gibt

Die automatische Helligkeit von LibRaw passt sich jeder Aufnahme an, sodass in einer Belichtungsreihe alle Aufnahmen etwa gleich hell herauskommen. Der feste Gain bewahrt die echte Belichtungsleiter zwischen den Aufnahmen.

Ein höherer `bright`-Wert hellt jedes Rendering auf. Belichtungsmetriken bewegen sich mit: Führen Sie nach einer Änderung `--recompute-average` erneut aus und scannen Sie neu, um die Metriken selbst neu zu schreiben.

### Belichtungsreihen werden unkorrigiert gerendert

Ein Foto, dessen `sequence_kind` `bracket` oder `hdr_panorama` ist, wird ohne Kameravorschau und ohne `bright`-Gain angezeigt. Beides würde die Lichter beschneiden, die Sie in einer Belichtungsreihe beurteilen. Ein einfaches `panorama` ist nicht betroffen.

Wo es gilt:

- `/image` (Detailansicht, Vergleichslupe, Culling-Lupe), in Echtzeit gerendert.
- Galerie-Kacheln und das Vergleichsraster, nach `--refresh-thumbnails`.
- `GET /api/download` mit `type=original`.

Nicht betroffen: `type=raw` (das unveränderte RAW), `type=darktable` (der Export im „bearbeiteten Look“), `GET /api/photo/cull_preview` (über darktable-cli gerendert) und die Bewertung.

Die Sequenzerkennung läuft nach einem Scan; führen Sie daher zuerst `--detect-sequences` aus, dann `--refresh-thumbnails`, damit die Kacheln folgen.

Setzen Sie `faithful_bracket_render` auf `false`, um Belichtungsreihen wie jedes andere Foto zu rendern.

### Migration einer vor diesem Profil gescannten Bibliothek

Miniaturansichten und Histogramme werden zur Scanzeit gespeichert, daher ändert ein Profilwechsel nichts an bereits gescannten Fotos. `photos.render_version` verzeichnet, welches Rendering die jeweils gespeicherte Miniaturansicht erzeugt hat:

- `NULL`: älter als der Stempel
- `1`: zuerst die Kameravorschau, `bright`-Gain auf dem Demosaic-Fallback (was jeder Scan speichert)
- `2`: keine Vorschau und kein Gain, für eine Aufnahme einer Belichtungsreihe (nur `--refresh-thumbnails` speichert es)

Nur zwei Dinge aktualisieren gespeicherte Miniaturansichten:

- **Ein erneuter Scan** schreibt Miniaturansicht und Histogramm neu und stempelt immer `1`.
- **`--refresh-thumbnails`** schreibt RAW-Miniaturansichten neu und stempelt `1` oder `2` passend zum aktuellen `sequence_kind`. Es baut jede Zeile neu auf, führen Sie es also nach einer `bright`-Änderung oder einem `--detect-sequences`-Durchlauf erneut aus.

Die Detailansicht (`/image`) ist immer aktuell; das Galerie-Raster ändert sich erst nach einem der beiden oben genannten Wege.

Die Galerie zeigt ein schließbares Banner, das die Fotos zählt, die noch auf dem alten Rendering sind. Es kann bis zu einer Stunde hinterherhinken; `python database.py --refresh-stats` aktualisiert es sofort.

Ein Rendering, das komplett schwarz zurückkommt (zum Beispiel ein abgeschnittenes Panasonic-RW2), wird verweigert, mit dem Dateinamen protokolliert und bei einem späteren Lauf erneut versucht.

---

## HDR-PQ-Tone-Mapping

Canon-HDR-PQ-Standbilder (`.HIF`) tragen die PQ-Transferfunktion (SMPTE ST 2084) auf BT.2020-Primärwerten, bis zu 10.000 Nits. Die Qualitätsmodelle und Miniaturansichten brauchen 8-Bit-SDR-sRGB; Facet dekodiert ein PQ-Bild daher in der nativen Bittiefe der Kamera, konvertiert es nach sRGB und tonemappt es. Dieser Block steuert dieses Tone-Mapping.

Er greift **nur** bei Bildern, deren NCLX-Farbprofil die PQ-Transferfunktion (Kennwert 16) deklariert. SDR-HEIF, HLG und JPEG werden unabhängig von `enabled` unverändert durchgereicht. Gedrehte Aufnahmen (EXIF-Orientierung anders als 1) kommen aufrecht heraus, auch auf dem Pfad nativer Bittiefe: Mit pillow-heif 1.6 und neuer wird die Ebene vor dem Tone-Mapping gedreht.

```json
"hdr_pq_tonemap": {
  "enabled": true,
  "method": "hable",
  "white_point": {
    "mode": "percentile",
    "percentile": 99.99,
    "min_nits": 100.0,
    "max_nits": 1200.0,
    "fixed_nits": 1000.0
  },
  "chroma_preserve": "per_channel"
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `enabled` | `true` | PQ-Bilder nach SDR tonemappen; bei `false` bleiben sie dunkel und ausgewaschen (nur zum Debuggen) |
| `method` | `hable` | Tonwertkurve: `hable` (filmisch, wie im `tonemap`-Filter von ffmpeg) oder `clip` (linear mit hartem Clip, nur als Referenz) |
| `white_point.mode` | `percentile` | Wie der bildabhängige Weißpunkt bestimmt wird: `percentile`, `max` (hellstes Pixel) oder `fixed` (`fixed_nits`) |
| `white_point.percentile` | `99.99` | Perzentil im Modus `percentile` |
| `white_point.min_nits` | `100.0` | Untergrenze für den Weißpunkt; ein dunkles Bild wird niemals unter das SDR-Referenzweiß normalisiert |
| `white_point.max_nits` | `1200.0` | Obergrenze im Modus `percentile`; begrenzt, wie weit ein ungewöhnlich helles Bild die Kurve nach unten zieht |
| `white_point.fixed_nits` | `1000.0` | Vom Modus `fixed` verwendeter Weißpunkt |
| `chroma_preserve` | `per_channel` | `per_channel` (heller, leichte Farbtonverschiebung in den Lichtern) oder `max_channel` (erhält den Farbton, etwas dunkler) |

Im Modus `max` dunkelt ein einzelnes heißes Pixel in einer Nachtszene das ganze Bild ab; `percentile` vermeidet das.

### Warum der Weißpunkt bildabhängig ist

Ein fester Weißpunkt von 100 Nits clippt alles, was heller ist, zu reinem Weiß, und echte HDR-Standbilder erreichen Spitzen von mehreren hundert bis tausend Nits. Facet normalisiert stattdessen auf einen bildabhängigen Weißpunkt, wie ffmpeg (`vf_tonemap.c`). Das Standard-Perzentil p99.99, geklammert auf 100-1200 Nits, erhält die Lichtzeichnung und ignoriert vereinzelte heiße Pixel.

### Warum in der nativen Bittiefe der Kamera dekodiert wird

Das Dekodieren von PQ auf 8 Bit vor dem Tone-Mapping posterisiert weiche Verläufe. Facet fordert vom HEIF-Dekoder die dateieigene Tiefe an (10 Bit bei aktuellen Kameras) und verengt erst nach der Tonwertkurve auf 8 Bit. Der Gewinn zeigt sich bei weichem Inhalt (klarer Himmel, Studiohintergründe, starkes Bokeh); Clipping-Flags und `exposure_score` bleiben bei echten Fotos unverändert. Ein Dekoder, der die native Tiefe nicht liefern kann, fällt auf 8 Bit zurück.

**Referenzen.** PQ-EOTF: SMPTE ST 2084:2014. Hable-Kurve und bildweiser
Spitzenwert: ffmpeg `vf_tonemap.c` (John Hable, „Filmic Tonemapping
Operators", 2010). BT.2020-nach-sRGB-Matrix: BT.2020-2 / IEC 61966-2-1 mit
D65. sRGB-OETF: IEC 61966-2-1. NCLX-Transferkennwert 16: ISO/IEC 23001-8 /
ITU-T H.273.

## Burst Detection

Gruppiert ähnliche Fotos, die in schneller Folge aufgenommen wurden.

```json
{
  "burst_detection": {
    "similarity_threshold_percent": 70,
    "time_window_minutes": 0.8,
    "rapid_burst_seconds": 0.4
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `similarity_threshold_percent` | `70` | Schwellenwert für die Image-Hash-Ähnlichkeit |
| `time_window_minutes` | `0.8` | Maximale Zeit zwischen Fotos |
| `rapid_burst_seconds` | `0.4` | Fotos innerhalb dieser Zeit werden automatisch gruppiert |

---

## Update-Benachrichtigungen

Teilt Edition-Nutzern mit, wann ein neueres Facet veröffentlicht wurde. Das ist getrennt von der Browser-Meldung „Eine neue Version ist verfügbar – Neu laden“.

- Die laufende Version steht unten im Benutzermenü, für alle, die den Viewer öffnen können.
- Ein mit `--build-arg FACET_BUILD=<Branch>@<Commit>` gebautes Image zeigt zusätzlich diese Build-Zeile. `/api/config` liefert beides als `version` und `build`, nur an Aufrufer, die die Bibliothek lesen dürfen.
- Der Server fragt GitHub höchstens einmal pro `interval_days`, ohne Token und ohne Bibliotheksdaten. Eine fehlgeschlagene Prüfung erscheint als „kein Update bekannt“.
- Nur Edition-Nutzer sehen den Hinweis, höchstens einmal pro Woche und Browser.

```json
{
  "updates": {
    "enabled": true,
    "check_url": "https://api.github.com/repos/ncoevoet/facet/releases/latest",
    "interval_days": 7
  }
}
```

| Einstellung | Standard | Beschreibung |
|---|---|---|
| `enabled` | `true` | `false` deaktiviert die Prüfung; es wird nie etwas angefragt |
| `check_url` | GitHub-API für die neueste Version | Wo nach der neuesten veröffentlichten Version gesucht wird |
| `interval_days` | `7` | Wie lange ein Ergebnis zwischengespeichert wird, bevor erneut gefragt wird |

---

## Sequenzerkennung

Benennt Belichtungsreihen, damit sie nicht als konkurrierende Aufnahmen behandelt werden. Die Belichtung jeder Aufnahme stammt aus den gespeicherten Werten `f_stop` / `shutter_speed` / `ISO` (`EV = log2(N^2 / t) - log2(ISO / 100)`); eine bestehende Bibliothek wird also ohne erneuten Scan ausgezeichnet.

Eine Folge ist eine Belichtungsreihe, wenn ihre Aufnahmen:

- von derselben Kamera stammen und jeweils innerhalb von `max_gap_seconds` auf die vorherige folgen;
- denselben Bildausschnitt behalten (`max_hamming` auf dem pHash);
- in beliebiger Aufnahmereihenfolge (eine Folge, die mit der Basisbelichtung beginnt, `0, -, +`, zählt wie von dunkel nach hell) eine gleichmäßige Leiter unterschiedlicher Belichtungen über `min_span_stops` bilden, aus mindestens `min_frames` Aufnahmen.

Jede Aufnahme erhält `sequence_ev_offset`, ihre Belichtung relativ zur Basisaufnahme, vorzeichenrichtig wie die AEB-Bezeichnungen einer Kamera (`-2` dunkel, `+2` hell). Die Basis ist die mittlere Sprosse. Bei gerader Anzahl Aufnahmen ist die Basis die mittlere Aufnahme, die weniger Enden ihres Histogramms beschneidet (bei Gleichstand die frühere); eine ungerade Reihe wie `(-2, 0, +2)` verwendet immer ihre mittlere Aufnahme. Besteht eine Serienbild-Gruppe genau aus einer Belichtungsreihe, zeigt die Galerie deren Basisaufnahme.

Aufruf über `--detect-sequences`; läuft außerdem am Ende jedes Scans, nach der
Serienbildung.

**Manuelle Korrekturen decken auch Belichtungsreihen ab.** Markieren Sie eine übersehene Belichtungsreihe von Hand in der Galerie oder in der Culling-Dunkelkammer („Als Belichtungsreihe markieren“). Sie braucht ≥2 Aufnahmen, jede mit verwertbaren Belichtungsdaten, keine zwei mit derselben Belichtung. Siehe [docs/VIEWER.md — Panoramen und Belichtungsreihen](VIEWER.md#panoramen-und-belichtungsreihen).

```json
{
  "sequence_detection": {
    "enabled": true,
    "max_gap_seconds": 3.0,
    "max_hamming": 10,
    "min_frames": 3,
    "min_step_stops": 0.5,
    "min_span_stops": 1.0,
    "step_tolerance_stops": 0.34
  }
}
```

| Einstellung | Standard | Beschreibung |
|---|---|---|
| `enabled` | `true` | Belichtungsreihen-Erkennung vollständig abschalten |
| `max_gap_seconds` | `3.0` | Größter Abstand zwischen zwei aufeinanderfolgenden Aufnahmen |
| `max_hamming` | `10` | Erlaubter pHash-Abstand zwischen den Aufnahmen (gleicher Bildausschnitt) |
| `min_frames` | `3` | Kürzeste Folge, die als Belichtungsreihe gilt. `2` ist opt-in — siehe Hinweis unten |
| `min_step_stops` | `0.5` | Kleinste LW-Stufe, die als bewusste Änderung zählt |
| `min_span_stops` | `1.0` | Kleinster Gesamtabstand zwischen dunkelster und hellster Aufnahme |
| `step_tolerance_stops` | `0.34` | Zulässige Ungleichmäßigkeit der Stufen (eine Drittelstufe) |

**Warum `min_frames` standardmäßig `3` ist.** Zwei Aufnahmen mit einer Blende Unterschied sehen gleich aus, ob sie eine Zwei-Bild-AEB-Serie oder eine schnelle Belichtungskorrektur sind. Mit `2` waren die meisten zusätzlich gefundenen Serien in einer Testbibliothek keine Belichtungsreihen. Ein Paar kann außerdem der Rest einer Dreier-Reihe sein; dann kann die Basis (`sequence_ev_offset` `0`) auf der falschen Aufnahme landen, während `hide_brackets` (standardmäßig aktiv) die andere ausblendet. Setzen Sie `2` nur, wenn Sie mit Zwei-Bild-AEB fotografieren und einige Fehltreffer in Kauf nehmen.

---

## Panorama-Erkennung

Benennt Panorama-Einzelbilder, die die Serienerkennung sonst als konkurrierende Aufnahmen ausblenden würde. Die Erkennung gleicht SIFT-Merkmale zwischen aufeinanderfolgenden gespeicherten 640px-Vorschaubildern ab; sie braucht kein Dekodieren des Originals, kein Modell und keine zusätzliche Abhängigkeit.

- Ein Schwenk bewegt sich stetig in eine Richtung; eine Serie pendelt um eine Stelle. Einfache und HDR-Schwenks sind getrennte Arten, unterschieden über die Belichtungsspanne.
- Die Genauigkeit lag bei einer Testbibliothek bei rund 96 %. Einige vertikale Panoramen oder solche mit wenigen Positionen werden übersehen.
- Sie können in beide Richtungen mit der Korrektur pro Set nachbessern.

```json
{
  "panorama_detection": {
    "enabled": true,
    "max_gap_seconds": 30.0,
    "min_frames": 8,
    "min_drift": 0.43,
    "min_inliers": 25,
    "hdr_min_span_stops": 1.5,
    "sift_features": 400
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `enabled` | `true` | Panorama-Erkennung vollständig abschalten |
| `max_gap_seconds` | `30.0` | Größter Abstand zwischen aufeinanderfolgenden Bildern eines Schwenks |
| `min_frames` | `8` | Kürzeste Folge, die als Panorama gilt (stärkster Filter; Nicht-Panoramen hatten 6 Bilder oder weniger) |
| `min_drift` | `0.43` | Gesamtschwenk in Bildbreiten, ab dem eine Folge zählt |
| `min_inliers` | `25` | Erforderliche RANSAC-Übereinstimmungen je Bildpaar |
| `max_step` | `0.9` | Größter Einzelschritt in Bildbreiten — darüber ist es ein Szenenwechsel |
| `back_tolerance` | `0.02` | Wie weit ein Schritt zurückgehen darf, bevor die Folge endet |
| `max_ortho` | `0.15` | Seitliche Abweichung über den gesamten Schwenk |
| `ortho_ratio` | `0.25` | Zusätzliches seitliches Budget anteilig zum Schwenk, damit lange Folgen nicht benachteiligt werden |
| `step_ortho_abs` | `0.02` | Seitliche Bewegung in einem Schritt, bevor er als Neuausrichtung gilt |
| `step_ortho_ratio` | `0.5` | Dieselbe Grenze als Anteil der Schrittgröße |
| `hdr_min_span_stops` | `1.5` | Belichtungsspanne, ab der ein Schwenk ein HDR-Panorama ist |
| `sift_features` | `400` | Merkmale je Vorschaubild; der Aufwand wächst mit dem Quadrat dieses Werts |
| `match_ratio` | `0.75` | Lowe-Verhältnis, das eine Übereinstimmung unterschreiten muss |
| `workers` | `0` | Parallele Worker-Prozesse; `0` wählt nach Kernanzahl |
| `probe_stride` | `8` | Bilder zwischen den günstigen Stichproben, die gewöhnliche Serien aussortieren |
| `probe_min_drift` | `0.05` | Bewegung, unterhalb derer eine Stichprobe die Folge als unbewegt einstuft |
| `max_run_frames` | `500` | Längste gemessene Kandidatenfolge (begrenzt den Speicher, ~220 KB pro Bild und Worker) |

Hinweise:

- `sift_features` braucht etwa 2,3 ms pro Bildpaar bei 400 und etwa 0,12 s bei 3000.
- Eine geänderte Einstellung bewirkt nichts, bis die Erkennung erneut läuft: Verwenden Sie `--detect-panoramas` (oder die Neustart-Aktion im Viewer), was die gesamte Bibliothek neu vermisst.
- Der Panorama-Schritt nach einem Scan, `--recompute-average` oder `--recompute-burst` vermisst nur geänderte Folgen neu. Wer eine Einstellung außer `enabled` und `workers` ändert, bewirkt, dass er alles neu vermisst.
- Ihre Korrekturen gelten ab dem nächsten Durchlauf. Zwei Durchläufe über eine unveränderte Bibliothek finden dieselben Sets mit denselben Gruppennummern.

---

## Burst Scoring

Gewichte, die das Serienbild-Culling verwendet, um die beste Aufnahme jeder Serienbildgruppe zu bestimmen. Die Gewichte sollten in der Summe 1,0 ergeben.

```json
{
  "burst_scoring": {
    "weight_aggregate": 0.4,
    "weight_aesthetic": 0.25,
    "weight_sharpness": 0.2,
    "weight_blink": 0.15
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `weight_aggregate` | `0.4` | Gewicht der Gesamtbewertung (Aggregate) |
| `weight_aesthetic` | `0.25` | Gewicht der ästhetischen Qualitätsbewertung |
| `weight_sharpness` | `0.2` | Gewicht der technischen Schärfebewertung |
| `weight_blink` | `0.15` | Abzugsgewicht für erkanntes Blinzeln (höher = stärkerer Abzug) |

---

## Duplicate Detection

Findet Duplikate in der gesamten Bibliothek: lockere pHash-Kandidaten, bestätigt durch eine Embedding-Ähnlichkeitsprüfung.

```json
{
  "duplicate_detection": {
    "similarity_threshold_percent": 90,
    "prefilter_hamming": 12,
    "embedding_cosine_threshold": 0.90
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `similarity_threshold_percent` | `90` | Strikte pHash-Schranke (90 % = Hamming-Distanz <= 6 von 64 Bits); der einzige Test, wenn einem der beiden Fotos ein Embedding fehlt |
| `prefilter_hamming` | `12` | Optional (nicht in der ausgelieferten Datei). Lockere Hamming-Schranke für Kandidaten, wenn beide Fotos Embeddings besitzen (mindestens die strikte Schranke) |
| `embedding_cosine_threshold` | `0.90` | Optional (nicht in der ausgelieferten Datei). Ein Kandidat wird nur zusammengeführt, wenn der SigLIP/CLIP-Kosinus >= diesem Wert ist |

- `python facet.py --detect-duplicates` erkennt und gruppiert Duplikate.
- `python facet.py --sweep-dedup-thresholds [labels.json]` bewertet die Kosinus-Schranke: Mit einer Labels-JSON gibt es eine Precision/Recall-Tabelle aus, andernfalls die Kandidaten-Kosinus-Verteilung und wie viele strikte pHash-Treffer die Schranke verwirft.

---

## Extended IQA tier (optional)

Zusätzliche Qualitätsbewerter, die eigene Spalten schreiben; sie ersetzen nie TOPIQ. Sie laufen während eines normalen Scans. Ein Lade-/VRAM-Fehler wird protokolliert und lässt die Spalte `NULL`; der Scan läuft weiter.

- `qrealign` steht standardmäßig auf `"auto"`: **an** für die Profile `8gb`/`16gb`/`24gb`, **aus** für `legacy`/CPU.
- `aesthetic_v25` und `deqa` sind **standardmäßig AUS**.

```json
{
  "iqa_extended": {
    "qrealign": "auto",
    "qrealign_size": "mini",
    "aesthetic_v25": false,
    "deqa": false
  }
}
```

| Einstellung | Standard | Zulässige Werte | Spalte | Beschreibung |
|---------|---------|-----------------|--------|-------------|
| `qrealign` | `"auto"` | `"auto"` · `true` · `false` | `qrealign_score` | Q-ReAlign-Mini 0.8B Ästhetik-IQA (Apache-2.0, ~2–3GB VRAM/RAM, ohne pyiqa) |
| `qrealign_size` | `"mini"` | `"mini"` · `"lite"` | - | `mini` (0.8B) oder `lite` (4B); bei `licensing.mode: "commercial"` auch das primäre Modell |
| `aesthetic_v25` | `false` | `true` / `false` | `aesthetic_v25` | Aesthetic Predictor V2.5 (SigLIP-Head, ~2GB); **veraltet**, bevorzugen Sie `qrealign` |
| `deqa` | `false` | `true` / `false` | `deqa_score` | DeQA-Score VLM IQA (16GB+ GPU; andernfalls übersprungen & NULL belassen) |

Hinweise:

- **Sortierung:** Jede Metrik erscheint im Sortiermenü des Viewers, sobald mindestens ein Foto einen Wert hat (**Q-ReAlign (Ästhetik)**, **Ästhetik v2.5**, **DeQA**). Unbewertete Fotos stehen am Ende.
- `qrealign_score` enthält die Ästhetik-Aufgabe; die Qualität nutzt `quality_score`.
- `aesthetic_v25` erfordert das Paket `aesthetic-predictor-v2-5`. Es ist AGPL-3.0-lizenziert und seit dem 2024-12-18 upstream unmaintained.

**Installieren Sie die optionalen Abhängigkeiten** für das, was Sie aktivieren: `pip install -e .[iqa-extended]` (fügt `aesthetic-predictor-v2-5` hinzu) oder kommentieren Sie die entsprechende Zeile in `requirements.txt` aus. DeQA-Score wird über `transformers` heruntergeladen.

Jede Metrik steht dem gewichteten Aggregat mit Gewicht 0 zur Verfügung, sodass `--recompute-average` nichts ändert, bis Sie ihr ein Gewicht zuweisen. `python facet.py --eval-iqa-srcc` misst, wie gut jede Metrik Ihre eigenen Sternebewertungen trifft.

**Anzeige im Viewer.** Befüllte Werte erscheinen im **Quality**-Panel der Fotodetailansicht (`Q-ReAlign`, `Aesthetic V2.5`, `DeQA`), mit Bereichsreglern unter **Extended Quality** in den Galeriefiltern (`min_qrealign`/`max_qrealign`, `min_aesthetic_v25`/`max_aesthetic_v25`, `min_deqa`/`max_deqa`).

> **Warnung:** Fotos, die gescannt wurden, bevor Sie eine Metrik aktiviert haben, haben dort `NULL`, und jedes Min oder Max an ihrem Regler blendet sie aus. Scannen Sie neu, bevor Sie nach einer frisch aktivierten Metrik filtern.

**Robustheit.** DeQA-Score führt Remote-Modellcode aus (`trust_remote_code`). Scheitert er bei einem Bild (geänderte Signatur, ungewöhnliche Ausgabe, OOM), bleibt der `deqa_score` dieses Bildes `NULL` und der Scan läuft weiter.

---

## Lizenzierung

Steuert, welche Modellkomponenten Facet laden darf. Die Lizenztabelle pro Komponente steht in [THIRD_PARTY_MODELS.md](THIRD_PARTY_MODELS.md).

```json
{
  "licensing": {
    "mode": "default",
    "allow_unclear": false
  }
}
```

| Einstellung | Standard | Zulässige Werte | Beschreibung |
|---------|---------|-----------------|-------------|
| `mode` | `"default"` | `"default"` · `"commercial"` | `"default"` lädt jedes Modell; `"commercial"` lädt nur kommerziell unbedenkliche Komponenten |
| `allow_unclear` | `false` | `true` / `false` | Im kommerziellen Modus zusätzlich Komponenten mit *unklarer* Lizenz erlauben (SAMP-Net, U2-Net-P, der LAION-CLIP-MLP-Ästhetik-Head); muss ein JSON-Boolean sein |

Im Modus `"commercial"`:

- `pyiqa` (TOPIQ, HyperIQA, LIQE, ...) und InsightFace werden nie importiert oder heruntergeladen.
- Ästhetik und Qualität kommen von Q-ReAlign, die Komposition vom regelbasierten Analysator.
- Gesichter nutzen YuNet-Erkennung, SFace-Embeddings mit 128 Dimensionen und optional MediaPipe für Augen/Lächeln sowie OFIQ-Gesichtsqualität.
- `liqe` und `aesthetic_iaa` bleiben `NULL`. `deqa` (Lizenz *unklar*) braucht `allow_unclear`. `aesthetic_v25` (AGPL) ist nie verfügbar.
- Eine abgelehnte Komponente stoppt den Scan beim Start mit einem `LicenceError`, der sie und ihren Ersatz nennt.
- `--score-topiq`, `--recompute-iqa` (pyiqa-Modelle) und `--recompute-composition-gpu` beenden sich mit dieser Meldung.
- Komponenten mit nichtkommerzieller Lizenz bleiben auch mit `allow_unclear` abgelehnt.

Nichts davon ist Rechtsberatung.

Umgebungsvariablen-Überschreibungen (sie können nur verschärfen; ein ungültiger Wert bricht den Start ab):

| Variable | Wirkung |
|----------|--------|
| `FACET_LICENSING_MODE` | `commercial` erzwingt den kommerziellen Modus; `default` oder leer = keine Überschreibung |
| `FACET_LICENSING_ALLOW_UNCLEAR` | `0`, `false`, `no`, `off` erzwingen `allow_unclear` auf aus; `1`, `true`, `yes`, `on` oder leer = keine Überschreibung |

Der Viewer übergibt `FACET_LICENSING_MODE=commercial` und, wenn seine Richtlinie unklare Komponenten verbietet, `FACET_LICENSING_ALLOW_UNCLEAR=0` an jeden `facet.py`-Prozess, den er startet. Ein String wie `"false"` für `licensing.allow_unclear` wird beim Start abgelehnt.

---

## Face Detection

InsightFace-Einstellungen zur Gesichtserkennung.

```json
{
  "face_detection": {
    "min_confidence_percent": 65,
    "min_face_size": 20,
    "blink_ear_threshold": 0.28,
    "min_faces_for_group": 4,
    "enable_3d_landmarks": false,
    "eyes_closed_max": 4.0,
    "poor_expression_min": 4.0,
    "blendshapes": {
      "enabled": true,
      "min_crop_size": 192,
      "blink_pose_gate_deg": null
    }
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `min_confidence_percent` | `65` | Minimale Erkennungskonfidenz (nur InsightFace) |
| `min_face_size` | `20` | Minimale Gesichtsgröße in Pixeln (nur InsightFace) |
| `blink_ear_threshold` | `0.28` | Eye Aspect Ratio für die Blinzelerkennung |
| `min_faces_for_group` | `4` | Mindestanzahl an Gesichtern für die Klassifizierung als Gruppenporträt (bei `--recompute-average` neu berechnet) |
| `enable_3d_landmarks` | `false` | Optional (nicht in der ausgelieferten Datei). Lädt InsightFace `landmark_3d_68` für die Kopfhaltung (yaw/pitch/roll); ~5MB, nur informativ |
| `eyes_closed_max` | `4.0` | Augen-offen-Score (0–10), bei oder unter dem die Culling-Dunkelkammer ein Blinzeln markiert (Gesichtsringe, Augen-Schieberegler) |
| `poor_expression_min` | `4.0` | Lächel-/Ausdrucks-Score (0–10), unter dem die Dunkelkammer einen schwachen Ausdruck markiert |
| `blendshapes.enabled` | `true` | MediaPipe-Blendshapes für `eyes_open_score` / `smile_score` verwenden, wenn installiert, sonst die Landmark-Geometrie |
| `blendshapes.min_crop_size` | `192` | Gesichter, deren gepolsterter Ausschnitt kleiner als dieser Wert ist (px, kürzere Seite), nutzen den geometrischen Score |
| `blendshapes.blink_pose_gate_deg` | `null` | Nur kommerzieller Modus (MediaPipe): Kopfpose-Grenzwert in Grad; `null` = aus |

Hinweise:

- Der YuNet-Detektor im kommerziellen Modus verwendet feste Werte (0,7 Konfidenz, 30 px) und ignoriert `min_confidence_percent` und `min_face_size`.
- MediaPipe braucht das Bündel `face_landmarker.task`. Installieren Sie es mit `pip install mediapipe==0.10.35 --no-deps`, niemals mit einem einfachen `pip install mediapipe`. Siehe [FACE_RECOGNITION.md](FACE_RECOGNITION.md#ausdruckssignale-pro-gesicht-augen-offen--lächeln).
- `blink_pose_gate_deg`: Ein Gesicht, dessen |Yaw| oder |Pitch| ihn überschreitet, erhält kein Blinzel-Urteil und keinen Augen-offen-/Lächeln-Score (NULL), da ein gedrehter Kopf wie geschlossene Augen wirkt. Kein Grenzwert zwischen 20° und 45° verbesserte die Blinzel-Erkennung in einer Testbibliothek, daher wird er ausgeschaltet ausgeliefert. Er muss eine positive Zahl sein und gilt für neu gescannte Fotos (`is_blink` ändert sich beim erneuten Scan).

---

## Face Clustering

HDBSCAN-Clustering für die Gesichtserkennung.

```json
{
  "face_clustering": {
    "enabled": true,
    "min_faces_per_person": 2,
    "min_samples": 2,
    "clustering_algorithm": "best",
    "leaf_size": 40,
    "use_gpu": "auto",
    "thresholds_by_model": {
      "arcface_buffalo_l": { "auto_merge_distance_percent": 15, "merge_threshold": 0.6 },
      "sface": { "auto_merge_distance_percent": 27.5, "merge_threshold": 0.65 }
    }
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `enabled` | `true` | Gesichts-Clustering aktivieren |
| `min_faces_per_person` | `2` | Mindestanzahl an Fotos pro Person |
| `min_samples` | `2` | HDBSCAN-Parameter min_samples |
| `clustering_algorithm` | `"best"` | HDBSCAN-Algorithmus |
| `leaf_size` | `40` | Blattgröße des Baums (nur CPU) |
| `use_gpu` | `"auto"` | GPU-Modus: `auto`, `always`, `never` |
| `thresholds_by_model` | siehe JSON | Pro Erkennungsmodell: `auto_merge_distance_percent` und `merge_threshold`. Standard: ArcFace `15` / `0.6`, SFace `27.5` / `0.65` |

`merge_threshold` (Zentroid-Ähnlichkeit für den Abgleich) und `auto_merge_distance_percent` (Auto-Merge-Abstand) werden für das **aktive** Erkennungsmodell aus `thresholds_by_model` gelesen (standardmäßig ArcFace, im kommerziellen Modus SFace). Ein Modell ohne Eintrag ist ein Fehler. Dieselben Schlüssel direkt unter `face_clustering` werden nicht mehr gelesen.

**Hinweise zum GPU-Clustering (`use_gpu`):**

- Erfordert die optionalen Pakete `cuml` + `cupy`. Das Docker-GPU-Image enthält cuML.
- Das Profil `legacy` clustert unabhängig von `use_gpu` immer auf der CPU.
- Ohne nutzbares CUDA-Gerät fällt das Clustering auf CPU-HDBSCAN zurück.
- `always` warnt und nutzt die CPU, wenn cuML fehlt; ein GPU-Fehler beim Clustering fällt ebenfalls auf die CPU zurück.

**Clustering-Algorithmen:**

| Algorithmus | Komplexität | Am besten für |
|-----------|------------|----------|
| `boruvka_balltree` | O(n log n) | Hochdimensionale Daten (empfohlen) |
| `boruvka_kdtree` | O(n log n) | Niedrigdimensionale Daten |
| `prims_balltree` | O(n²) | Speicherbeschränkt, hochdimensional |
| `prims_kdtree` | O(n²) | Speicherbeschränkt, niedrigdimensional |
| `best` | Auto | HDBSCAN entscheiden lassen |

---

## Face Processing

Steuert die Gesichtsextraktion und die Thumbnail-Erzeugung.

```json
{
  "face_processing": {
    "crop_padding": 0.3,
    "use_db_thumbnails": true,
    "face_thumbnail_size": 640,
    "face_thumbnail_quality": 90,
    "extract_workers": 2,
    "extract_batch_size": 16,
    "refill_workers": 4,
    "refill_batch_size": 100,
    "auto_tuning": {
      "enabled": true,
      "memory_limit_percent": 80,
      "min_batch_size": 8,
      "monitor_interval_seconds": 5
    }
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `crop_padding` | `0.3` | Randverhältnis für Gesichtsausschnitte |
| `use_db_thumbnails` | `true` | Gespeicherte Thumbnails verwenden |
| `face_thumbnail_size` | `640` | Thumbnail-Größe in Pixeln |
| `face_thumbnail_quality` | `90` | JPEG-Qualität |
| `extract_workers` | `2` | Parallele Extraktions-Worker |
| `extract_batch_size` | `16` | Batchgröße der Extraktion |
| `refill_workers` | `4` | Worker zum Nachfüllen von Thumbnails |
| `refill_batch_size` | `100` | Batchgröße des Nachfüllens |
| **auto_tuning** | | |
| `enabled` | `true` | Speicherbasiertes Tuning aktivieren |
| `memory_limit_percent` | `80` | Prozentsatz des effektiven Speicherlimits (cgroup-Limit unter einem Container-Limit, sonst Host-RAM) |
| `min_batch_size` | `8` | Minimale Batchgröße |
| `monitor_interval_seconds` | `5` | Prüfintervall |

---

## Monochrome Detection

Erkennung von Schwarzweißfotos.

```json
{
  "monochrome_detection": {
    "saturation_threshold_percent": 5
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `saturation_threshold_percent` | `5` | Mittlere Sättigung < 5 % = monochrom |

---

## Tagging

Allgemeine Verschlagwortungseinstellungen. Das Verschlagwortungsmodell wird pro Profil in `models.profiles.*.tagging_model` konfiguriert.

```json
{
  "tagging": {
    "enabled": true,
    "max_tags": 5
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `enabled` | `true` | Verschlagwortung aktivieren |
| `max_tags` | `5` | Maximale Anzahl Tags pro Foto |

**Hinweis:** Die Tag-Schwelle für CLIP/SigLIP ist `tag_threshold_percent` im Block des aktiven Profils: `models.clip` für `16gb`/`24gb`, `models.clip_legacy` für `legacy`/`8gb`. Der alte Schlüssel `similarity_threshold_percent` wird nicht mehr gelesen. Haben Sie ihn angepasst, übernehmen Sie den Wert nach `tag_threshold_percent`; das Laden der Konfiguration und `python facet.py --doctor` weisen auf den alten Schlüssel hin.

Am Ende eines Scans wird der Verschlagwortungsschritt (mit einer Logzeile) übersprungen, wenn `enabled` auf `false` steht oder kein Foto zugleich ein Embedding und eine leere Tag-Liste hat. Fotos, auf die nie ein Tag zutrifft, bleiben ausstehend; das Modell wird daher weiterhin bei jedem Scan geladen. `python tag_existing.py` (mit oder ohne `--force`) und `python facet.py --tag-untagged` laufen immer.

### Verfügbare Verschlagwortungsmodelle

Konfiguriert über `models.profiles.*.tagging_model`:

| Modell | VRAM | Tag-Stil | Anmerkungen |
|-------|------|-----------|-------|
| `clip` | 0 (verwendet Embeddings erneut) | Stimmung/Atmosphäre (dramatic, golden_hour, vintage) | Kein zusätzliches Modell zu laden; weniger wörtliche Objekterkennung |
| `qwen3.5-2b` | ~4GB | Strukturierte Szenen (landscape, architecture, reflection) | Erfordert transformers + zusätzlichen VRAM |
| `qwen3.5-4b` | ~8GB | Detaillierte Szenen mit Nuancen | Höherer VRAM-Bedarf; langsamere Inferenz |

### Standard-Verschlagwortungsmodelle pro Profil

| Profil | Verschlagwortungsmodell | Embedding-Modell |
|---------|---------------|-----------------|
| `legacy` | `clip` | CLIP ViT-L-14 (768-dim) |
| `8gb` | `clip` | CLIP ViT-L-14 (768-dim) |
| `16gb` | `qwen3.5-2b` | SigLIP 2 NaFlex SO400M (1152-dim) |
| `24gb` | `qwen3.5-4b` | SigLIP 2 NaFlex SO400M (1152-dim) |

### Fotos neu verschlagworten

```bash
python facet.py --recompute-tags       # Neu verschlagworten mit dem pro Profil konfigurierten Modell
python facet.py --recompute-tags-vlm   # Neu verschlagworten mit dem VLM-Tagger
```

---

## Standalone Tags

Tags mit Synonymlisten, die an keine bestimmte Kategorie gebunden sind. Diese stehen für alle Fotos unabhängig von der Kategoriezuordnung zur Verfügung. Jeder Schlüssel ist der Tag-Name; der Wert ist eine Liste von Synonymen für die CLIP/VLM-Übereinstimmung.

```json
{
  "standalone_tags": {
    "bokeh": ["bokeh", "shallow depth of field", "background blur", "out of focus"],
    "surreal": ["surreal", "dreamlike", "fantasy", "composite", "double exposure"],
    "flat_lay": ["flat lay", "overhead shot", "top down", "bird's eye product"],
    "golden_hour": ["golden hour", "magic hour", "warm light", "sunset light"],
    "portrait_tag": ["portrait", "headshot", "face portrait", "close-up portrait"]
  }
}
```

Fügen Sie neue eigenständige Tags hinzu, indem Sie einen Schlüssel und eine Liste von Synonymen angeben. Hier definierte Tags werden mit den kategoriespezifischen Tags zusammengeführt, um das vollständige Tag-Vokabular zu bilden.

---

## Analysis

Schwellenwerte für `--compute-recommendations`.

```json
{
  "analysis": {
    "aesthetic_max_threshold": 9.0,
    "aesthetic_target": 9.5,
    "quality_avg_threshold": 7.5,
    "quality_weight_threshold_percent": 10,
    "correlation_dominant_threshold": 0.5,
    "category_min_samples": 50,
    "category_imbalance_threshold": 0.5,
    "score_clustering_std_threshold": 1.0,
    "top_score_threshold": 8.5,
    "exposure_avg_threshold": 8.0
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `aesthetic_max_threshold` | `9.0` | Warnen, wenn die maximale Ästhetik darunter liegt |
| `aesthetic_target` | `9.5` | Zielwert für aesthetic_scale |
| `quality_avg_threshold` | `7.5` | Qualitätsschwelle für „hohen Wert“ |
| `quality_weight_threshold_percent` | `10` | Warnen, wenn das Qualitätsgewicht ≤ diesem Wert ist |
| `correlation_dominant_threshold` | `0.5` | Warnung „dominantes Signal“ |
| `category_min_samples` | `50` | Mindestanzahl an Fotos pro Kategorie |
| `category_imbalance_threshold` | `0.5` | Warnung bei Bewertungsabstand |
| `score_clustering_std_threshold` | `1.0` | Warnen, wenn die Standardabweichung < diesem Wert ist |
| `top_score_threshold` | `8.5` | Warnen, wenn das maximale Aggregate < diesem Wert ist |
| `exposure_avg_threshold` | `8.0` | Warnen, wenn die durchschnittliche Belichtung > diesem Wert ist |

---

## Viewer

Anzeige und Verhalten der Web-Galerie.

```json
{
  "viewer": {
    "default_category": "",
    "edition_password": "",
    "comparison_mode": {
      "min_comparisons_for_optimization": 50,
      "pair_selection_strategy": "learning",
      "candidate_pool_size": 200,
      "show_current_scores": true
    },
    "sort_options": { ... },
    "pagination": {
      "default_per_page": 64
    },
    "dropdowns": {
      "max_cameras": 50,
      "max_lenses": 50,
      "max_persons": 50,
      "max_tags": 20,
      "min_photos_for_person": 10
    },
    "persons": {
      "needs_naming_min_faces": 5
    },
    "raw_processor": {
      "backend": "rawpy",
      "darktable": {
        "executable": "darktable-cli",
        "hq": true,
        "width": null,
        "height": null,
        "extra_args": [],
        "cull_styles": [],
        "preview_max_edge": 1440,
        "preview_timeout_seconds": 60
      }
    },
    "display": {
      "tags_per_photo": 4,
      "card_width_px": 168,
      "image_width_px": 160,
      "image_jpeg_quality": 96,
      "thumbnail_slider": {
        "min_px": 120,
        "max_px": 400,
        "default_px": 168,
        "step_px": 8
      }
    },
    "face_thumbnails": {
      "output_size_px": 64,
      "jpeg_quality": 80,
      "crop_padding_ratio": 0.2,
      "min_crop_size_px": 20
    },
    "quality_thresholds": {
      "good": 6,
      "great": 7,
      "excellent": 8,
      "best": 9
    },
    "photo_types": {
      "top_picks_min_score": 7,
      "top_picks_min_face_ratio": 0.2,
      "top_picks_weights": {
        "aggregate_percent": 30,
        "aesthetic_percent": 28,
        "composition_percent": 18,
        "face_quality_percent": 24
      },
      "low_light_max_luminance": 0.2
    },
    "defaults": {
      "hide_blinks": true,
      "hide_bursts": true,
      "hide_duplicates": true,
      "hide_brackets": true,
      "hide_panoramas": true,
      "hide_details": true,
      "tooltip_mode": "panel",
      "hide_rejected": true,
      "sort": "aggregate",
      "sort_direction": "DESC",
      "type": "",
      "gallery_mode": "mosaic"
    },
    "cache_ttl_seconds": 3600,
    "notification_duration_ms": 2000,
    "moment_confidence_min": 0,
    "path_mapping": {}
  }
}
```

> **Hinweis:** `sort_options` (oben als `{ ... }` ausgelassen) ordnet DB-Spalten Dropdown-Bezeichnungen zu und wird selten bearbeitet. Die **Content**-Gruppe enthält eine Sortierung `{ "column": "narrative_moment_confidence", "label": "Moment Confidence" }` (NULL-Werte werden zuletzt einsortiert).

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `default_category` | `""` | Standard-Kategoriefilter |
| `edition_password` | `""` | Passwort zum Freischalten des Editionsmodus; leer = schreibgeschützt (außer unter `trusted_local_editing`) |
| `trusted_local_editing` | `false` | Gewährt einem Browser auf demselben Rechner Editionsrechte ohne Passwort. Siehe [Vertrauenswürdige lokale Bearbeitung](#vertrauenswürdige-lokale-bearbeitung) |
| `place_search_url` | `"https://photon.komoot.io/api"` | Photon-Endpunkt für die Galerie-Suche **Online suchen**; `""` deaktiviert sie. Siehe [Online-Ortssuche](#online-ortssuche) |
| **comparison_mode** | | |
| `min_comparisons_for_optimization` | `50` | Entscheidende Vergleiche (Gleichstände zählen nicht), die in einer Kategorie nötig sind, bevor Gewichte vorgeschlagen werden |
| `pair_selection_strategy` | `"learning"` | Paarstrategie: `learning`, `uncertainty`, `boundary`, `active`, `random` |
| `candidate_pool_size` | `200` | Zufälliger Kandidatenpool, innerhalb dessen die `learning`-Strategie Paare zieht |
| `show_current_scores` | `true` | Bewertungen während des Vergleichs anzeigen |
| **pagination** | | |
| `default_per_page` | `64` | Fotos pro Seite |
| **dropdowns** | | |
| `max_cameras` | `50` | Maximale Anzahl Kameras im Dropdown |
| `max_lenses` | `50` | Maximale Anzahl Objektive |
| `max_persons` | `50` | Maximale Anzahl Personen |
| `max_tags` | `20` | Maximale Anzahl Tags |
| `min_photos_for_person` | `10` | Personen mit weniger Fotos im Dropdown ausblenden |
| **persons** | | |
| `needs_naming_min_faces` | `5` | Minimale Gesichtsanzahl, damit ein Cluster in `/persons` unter „Needs naming“ erscheint; `1` listet jede unbenannte Person |
| **raw_processor** | | |
| `darktable.executable` | `"darktable-cli"` | Name oder absoluter Pfad der darktable-cli-Binärdatei |
| `darktable.profiles` | `[]` | Array benannter darktable-Exportprofile (siehe unten) |
| `darktable.profiles[].name` | *(erforderlich)* | Anzeigename des Profils (verwendet im Download-Menü und im API-Parameter `profile`) |
| `darktable.profiles[].hq` | `true` | Übergibt `--hq true` für hochwertigen Export |
| `darktable.profiles[].width` | *(weglassen)* | Maximale Ausgabebreite (für volle Auflösung weglassen) |
| `darktable.profiles[].height` | *(weglassen)* | Maximale Ausgabehöhe (für volle Auflösung weglassen) |
| `darktable.profiles[].style` | *(weglassen)* | Name des darktable-Stils, der beim Export angewendet wird (`--style`) |
| `darktable.profiles[].apply_custom_presets` | `true` | `false` übergibt `--apply-custom-presets false`, sodass nur der explizite `style` gilt |
| `darktable.profiles[].extra_args` | `[]` | Zusätzliche CLI-Argumente (z. B. `["--style-overwrite"]`) |
| `darktable.cull_styles` | `[]` | darktable-Stile, die in der Culling-Dunkelkammer als Vorschau im bearbeiteten Look angeboten werden; leer blendet die Auswahl aus |
| `darktable.cull_styles[].name` | *(erforderlich)* | darktable-Stilname (an `--style` übergeben) |
| `darktable.cull_styles[].label_key` | *(name)* | Optionaler i18n-Schlüssel für die Menübeschriftung (Standard: der Stilname) |
| `darktable.preview_max_edge` | `1440` | Maximale Kantenlänge (px) der Aussortier-Vorschau |
| `darktable.preview_timeout_seconds` | `60` | darktable-cli-Zeitlimit pro Vorschau-Render |
| **display** | | |
| `tags_per_photo` | `4` | Auf Karten angezeigte Tags |
| `card_width_px` | `168` | Kartenbreite |
| `image_width_px` | `160` | Bildbreite |
| `image_jpeg_quality` | `96` | JPEG-Qualität für die RAW/HEIF-Konvertierung in `/api/download` und `/api/image` (1–100) |
| `thumbnail_slider.min_px` | `120` | Minimale Thumbnail-Größe (px) |
| `thumbnail_slider.max_px` | `400` | Maximale Thumbnail-Größe (px) |
| `thumbnail_slider.default_px` | `168` | Standard-Thumbnail-Größe (px) |
| `thumbnail_slider.step_px` | `8` | Schrittweite des Reglers (px) |
| **face_thumbnails** | | |
| `output_size_px` | `64` | Thumbnail-Größe |
| `jpeg_quality` | `80` | JPEG-Qualität |
| `crop_padding_ratio` | `0.2` | Gesichtsrand |
| `min_crop_size_px` | `20` | Minimale Ausschnittgröße |
| **quality_thresholds** | | |
| `good` | `6` | Schwelle „Gut“ |
| `great` | `7` | Schwelle „Sehr gut“ |
| `excellent` | `8` | Schwelle „Ausgezeichnet“ |
| `best` | `9` | Schwelle „Beste“ |
| **photo_types** | | |
| `top_picks_min_score` | `7` | Minimum für Top Picks |
| `top_picks_min_face_ratio` | `0.2` | Gesichtsanteil für die Gewichtung |
| `low_light_max_luminance` | `0.2` | Schwelle für wenig Licht |
| **defaults** | | |
| `type` | `""` | Standard-Fototypfilter (z. B. `"portraits"`, `"landscapes"` oder `""` für Alle) |
| `sort` | `"aggregate"` | Standard-Sortierspalte (eine im Browser gemerkte Sortierung hat Vorrang; siehe [Sortierung](VIEWER.md#sortierung)) |
| `sort_direction` | `"DESC"` | Standard-Sortierrichtung (`"ASC"` oder `"DESC"`) |
| `hide_blinks` | `true` | Blinzelfotos standardmäßig ausblenden |
| `hide_bursts` | `true` | Standardmäßig nur das beste Serienbild anzeigen |
| `hide_duplicates` | `true` | Nicht führende Duplikatfotos standardmäßig ausblenden |
| `hide_brackets` | `true` | Standardmäßig nur die Basisbelichtung einer Belichtungsreihe anzeigen |
| `hide_panoramas` | `true` | Standardmäßig nur ein repräsentatives Bild je Panorama zeigen |
| `hide_details` | `true` | Fotodetails auf Karten standardmäßig ausblenden |
| `tooltip_mode` | `"panel"` | Tooltip-Auslöser: `"hover"`, `"click"`, `"off"` oder `"panel"` (angedockte Leiste); ersetzt `hide_tooltip` |
| `panel_activation` | `"both"` | Geste, die im Modus `"panel"` das Foto der angedockten Leiste wechselt: `"hover"`, `"click"` oder `"both"` |
| `hide_rejected` | `true` | Abgelehnte Fotos standardmäßig ausblenden |
| `gallery_mode` | `"mosaic"` | Standard-Galerie-Layout (`"grid"` oder `"mosaic"`) |
| **allowed_origins** | | |
| `allowed_origins` | `["http://localhost:4200", "http://localhost:5000"]` | Per CORS erlaubte Origins; fügen Sie beim Remote-Hosting Ihre Domain oder Reverse-Proxy-URL hinzu |
| **security_headers** | | |
| `security_headers.content_security_policy` | _(SPA-sicherer Standard)_ | Content-Security-Policy-Header; `""` deaktiviert ihn, oder geben Sie eine strengere Policy an |
| `security_headers.hsts` | `false` | `Strict-Transport-Security` senden. Nur aktivieren, wenn der Viewer über HTTPS ausgeliefert wird. |
| **Sonstiges** | | |
| `cache_ttl_seconds` | `3600` | TTL der In-Memory-Statistik-/Abfrage-Caches; halten Sie sie länger als eine vollständige Statistikberechnung (kann Minuten dauern) |
| `notification_duration_ms` | `2000` | Dauer der Toast-Benachrichtigung |
| `moment_confidence_min` | `0` | Moment-Labels unterhalb dieser Konfidenz (0–1) erscheinen abgeblendet mit „(uncertain)“; `0` = nie abblenden |

Hinweise:

- **`trusted_local_editing`** gilt nur, solange `password` und `edition_password` auf einer Einzelbenutzer-Installation beide leer sind. Es umfasst jede editionspflichtige Route einschließlich Scans und lässt den Dialog „Assistent verbinden“ ein Assistenten-Token mit voller Bearbeitung für `/mcp`-Anfragen vom selben Rechner erstellen.

> **Warnung:** Aktivieren Sie `trusted_local_editing` niemals hinter einem Reverse-Proxy auf demselben Host.

- **`pair_selection_strategy`:** `learning` wählt zunächst vielfältige Paare, danach Paare, die das Modell uneinheitlich einordnet.
- **`darktable.cull_styles`** speisen `GET /api/photo/cull_preview`. Jeder Stil **muss bereits** in der darktable-Konfiguration des Benutzers vorhanden sein, der den Viewer ausführt.
- Die Standard-Content-Security-Policy erlaubt die eigenen Ressourcen der SPA: Inline-Theme-Skript/-Stil, Google Fonts, OpenStreetMap-Kacheln und die Same-Origin-API.
- `moment_confidence_min` blendet Labels im Szenen-Header, im Culling-Szenengruppen-Header und im Galerie-Tooltip ab.

### Karten-Badges und Beschnitt

`viewer.badges` schaltet einzelne Badges der Galeriekarte ein und aus. Ältere Badges stehen standardmäßig auf `true`; der Block kann also weggelassen werden, ohne dass sich etwas ändert.

```json
{
  "viewer": {
    "badges": {
      "favorite": true,
      "star_rating": true,
      "rejected": true,
      "sequence_kind": true,
      "sequence_override_pending": true,
      "stack": true,
      "keeper_hint": true,
      "best_of_burst": true,
      "clipping_highlight": true,
      "clipping_shadow": false
    },
    "clipping": {
      "badge_percent": 5,
      "indicator_percent": 1,
      "histogram_mode": "rgb",
      "tooltip_histogram_mode": "luma"
    }
  }
}
```

| Schlüssel | Standard | Beschreibung |
|-----------|----------|--------------|
| `badges.favorite` | `true` | Herz-Badge auf einem Favoriten (Bearbeitungsmodus) |
| `badges.star_rating` | `true` | Stern- und Zähler-Badge auf einem bewerteten Foto (Bearbeitungsmodus) |
| `badges.rejected` | `true` | Daumen-runter-Badge auf einem abgelehnten Foto (Bearbeitungsmodus) |
| `badges.sequence_kind` | `true` | Set-Badge (Serienaufnahme/Belichtungsreihe/Panorama/Duplikat), sichtbar, solange der passende Ausblend-Umschalter das Set zusammenklappt |
| `badges.sequence_override_pending` | `true` | Uhr-Badge für eine Panorama-Korrektur, die auf den nächsten Erkennungslauf wartet |
| `badges.stack` | `true` | Ebenen-Badge mit Mitgliederzahl auf den Karten eines manuellen Fotostapels; ein Klick öffnet den Stapel |
| `badges.keeper_hint` | `true` | Pfeil „in dieser Gruppe gibt es eine bessere Aufnahme" aus dem gelernten Keeper-Modell |
| `badges.best_of_burst` | `true` | „Beste“-Badge auf dem Leitbild einer Serie, nur sichtbar, wenn `hide_bursts` aus ist |
| `badges.clipping_highlight` | `true` | Badge für ein Foto, dessen Lichter `clipping.badge_percent` überschreiten |
| `badges.clipping_shadow` | `false` | Dasselbe für abgesoffene Schatten (aus: oft gewollt bei Silhouetten, Nacht, Low-Key) |

Wird `badges.stack` ausgeschaltet, verschwindet nur das Badge; die Kartenschaltfläche „Fotostapel öffnen“ funktioniert weiter.

`viewer.clipping` definiert „beschnitten“ einmal für das Karten-Badge, die Histogramm-Marker und den Galerie-Filter.

| Schlüssel | Standard | Beschreibung |
|-----------|----------|--------------|
| `badge_percent` | `5` | Prozent der Pixel im schlechtesten R/G/B-Kanal, ab dem die Karte ein Badge erhält (bei einer Stichprobe etwa 1 Foto von 25) |
| `indicator_percent` | `1` | Schwelle für die eigenen R/G/B-Endmarker des Histogramms |
| `histogram_mode` | `"rgb"` | Standard für das Histogramm des **Detailbereichs**: `"luma"`, `"rgb"`, `"r"`, `"g"` oder `"b"` |
| `tooltip_histogram_mode` | `"luma"` | Standard für den Histogramm-Tab der **Seitenleiste** (`tooltip_mode: "panel"`), dieselben fünf Werte |

Hinweise:

- Die eigene Histogramm-Wahl eines Nutzers liegt in `localStorage` (`facet_histogram_mode`, `facet_histogram_mode_tooltip`) und hat Vorrang vor diesen Standardwerten. Die beiden Einstellungen sind unabhängig.
- Die Blasen **Hover** und **Klick** zeigen kein Histogramm.

**Beschnitt wird pro Kanal gemessen, exakt bei Bin 0 und Bin 255.** Er steht in `photos.channel_clip_shadow_pct` / `channel_clip_highlight_pct` als Anteil der Pixel des schlechtesten Kanals. Das unterscheidet sich von den Flags `shadow_clipped` / `highlight_clipped`, die die Luminanzbänder 0–30 und 225–255 abdecken und in `exposure_score` einfließen.

**`NULL` bedeutet unbekannt, niemals sauber.** Ein Foto mit einem älteren gespeicherten Histogramm hat keine Kanaldaten; es erhält daher kein Badge und passt auf keine Seite des Galerie-Filters. `python facet.py --backfill-clipping` füllt die Spalten aus den gespeicherten Histogrammen; es dekodiert keine Bilder und lässt sich fortsetzen.

### Features

Schalten Sie optionale Features um, um den Speicherverbrauch zu senken oder die UI zu vereinfachen:

```json
{
  "viewer": {
    "features": {
      "show_similar_button": true,
      "show_merge_suggestions": true,
      "show_rating_controls": true,
      "show_memories": true,
      "show_captions": true,
      "show_timeline": true,
      "show_map": true,
      "show_scenes": true,
      "show_my_taste": true
    }
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `show_similar_button` | `true` | Schaltfläche „Find Similar“ auf Fotokarten anzeigen (nutzt numpy für CLIP-Ähnlichkeit) |
| `show_merge_suggestions` | `true` | Funktion für Zusammenführungsvorschläge auf der Personenverwaltungsseite aktivieren |
| `show_rating_controls` | `true` | Steuerelemente für Sternebewertung und Favorit anzeigen |
| `show_scan_button` | `false` | Scan-Auslöser-Schaltfläche anzeigen (keine GPU nötig; siehe Hinweise) |
| `metrics_enabled` | `false` | Den öffentlichen Prometheus-Endpunkt `GET /metrics` aktivieren (siehe Warnung unten) |
| `show_semantic_search` | `true` | Semantische Suchleiste anzeigen (Text-zu-Bild-Suche mit CLIP/SigLIP-Embeddings) |
| `show_albums` | `true` | Album-Funktion anzeigen (Fotoalben erstellen, verwalten und durchsuchen) |
| `show_critique` | `true` | Schaltfläche für KI-Kritik auf Fotokarten anzeigen (regelbasierte Bewertungsaufschlüsselung) |
| `show_vlm_critique` | `true` | VLM-Kritik aktivieren (Profil 16gb/24gb); `false`, wenn der Schlüssel fehlt |
| `show_embed_metadata` | `true` | „Write metadata to file“ im Editionsmodus anzeigen (bettet Bewertungen/Schlüsselwörter über exiftool ein) |
| `show_memories` | `true` | Dialog „On This Day“-Erinnerungen anzeigen (Fotos, die am selben Datum in früheren Jahren aufgenommen wurden) |
| `show_captions` | `true` | KI-generierte Bildunterschriften auf Fotokarten anzeigen |
| `show_timeline` | `true` | Timeline-Ansicht für chronologisches Durchsuchen mit Datumsnavigation anzeigen |
| `show_map` | `true` | Die GPS-Kartenansicht anzeigen (erfordert Leaflet); `false`, wenn der Schlüssel fehlt |
| `show_capsules` | `true` | Die Capsules-Ansicht anzeigen (kuratierte Foto-Diaschauen nach Thema gruppiert) |
| `show_folders` | `true` | Ordnerbasiertes Durchsuchen der Fotoverzeichnisstruktur anzeigen |
| `show_scenes` | `true` | Die Szenen-Ansicht (`/scenes`) anzeigen, führende Serienbildfotos in chronologische Szenen gruppiert |
| `show_my_taste` | `true` | Die Sortierung „My Taste“ des persönlichen Rankers anzeigen, mit einem Konfidenz-Badge |
| `show_social_export` | `true` | Das editionsbeschränkte Download-Menü **Social-Zuschnitt** anzeigen. Siehe [Social-Export](#social-export) |
| `show_portfolio_export` | `true` | Die editionsbeschränkte Album-Aktion **Portfolio exportieren** anzeigen. Siehe [Portfolio-Export](#portfolio-export) |
| `show_proofing` | `false` | Client-Proofing für geteilte Alben aktivieren. Siehe [Client-Proofing](#client-proofing) |

Hinweise:

- **`show_scan_button`:** sichtbar für den Superadmin im Mehrbenutzermodus oder für eine entsperrte Edition-Sitzung im Einzelbenutzermodus. Scans laufen mit dem Profil `legacy` nur auf der CPU. Eine vertrauenswürdige lokale Sitzung (`trusted_local_editing`) kann auch ohne ihn scannen.
- **Speicheroptimierung:** `show_similar_button: false` verhindert, dass numpy geladen wird, und senkt so den Speicherbedarf des Viewers.

> **Warnung:** `metrics_enabled` legt Foto-/Personen-/Gesichtszählungen, DB-Größe und Prozessspeicher offen. Aktivieren Sie es nur, wo das Scraper-Netz den Endpunkt erreichen kann, nie im öffentlichen Internet.

### Client-Proofing

`viewer.features.show_proofing` (Standard `false`) verwandelt jedes geteilte Album in eine Client-Proofing-Seite. Ein Client mit dem Freigabelink (und der optionalen `viewer.proofing.pin`) kann ohne Konto Fotos mit einem Herz markieren und Kommentare hinterlassen. Der Besitzer prüft sie in einem editionsbeschränkten Dialog auf der Albumkarte. Client-Auswahlen berühren nie die Bewertungen des Besitzers und trainieren den persönlichen Ranker nicht.

```json
{
  "viewer": {
    "features": { "show_proofing": false },
    "proofing": {
      "pin": "",
      "session_minutes": 1440
    }
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `features.show_proofing` | `false` | Hauptschalter für Client-Proofing auf geteilten Alben |
| `proofing.pin` | `""` | Optionale PIN, die ein Client zusammen mit dem Freigabelink eingeben muss; leer = keine PIN (Versuche sind ratenbegrenzt) |
| `proofing.session_minutes` | `1440` | Lebensdauer der Client-Sitzung in Minuten (24 h); endet sofort, wenn die Albumfreigabe aufgehoben oder Proofing deaktiviert wird |

### Path Mapping

Bildet Datenbankpfade auf lokale Pfade ab, wenn Fotos auf einem Rechner bewertet wurden (z. B. Windows mit UNC-Pfaden), der Viewer aber auf einem anderen läuft (z. B. Linux-NAS).

```json
{
  "viewer": {
    "path_mapping": {
      "\\\\NAS\\Photos": "/mnt/photos",
      "D:\\Pictures": "/volume1/pictures"
    }
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `path_mapping` | `{}` | Quellpräfix → Zielpräfix, angewendet beim Lesen von Dateien von der Festplatte |

**Funktionsweise:**

- Gilt nur beim **Lesen von Dateien von der Festplatte** (Bilder in voller Größe, Downloads, VLM-Kritik). Datenbankpfade werden nie verändert.
- Backslashes und Schrägstriche werden normalisiert: `\\NAS\Photos\img.jpg` und `//NAS/Photos/img.jpg` passen beide.
- Zuordnungen werden der Reihe nach ausgewertet; das erste passende Präfix gewinnt.
- Zuordnungsziele werden automatisch in die Allowlist der Verzeichnisse im Mehrbenutzermodus aufgenommen.

**Beispiel:** Eine unter Windows befüllte Datenbank speichert Pfade wie `\\NAS\Photos\2024\IMG_001.jpg`. Unter Linux ist derselbe Share unter `/mnt/nas/Photos` eingebunden. Konfigurieren Sie:

```json
"path_mapping": {"\\\\NAS\\Photos": "/mnt/nas/Photos"}
```

### Passwortschutz

Optionaler Passwortschutz für den Viewer:

```json
{
  "viewer": {
    "password": "your-password-here"
  }
}
```

Wenn gesetzt, müssen sich Benutzer anmelden, bevor sie den Viewer verwenden.

### Vertrauenswürdige lokale Bearbeitung

Lässt einen Einzelbenutzer-Viewer, der nur aus einem Browser auf demselben Rechner genutzt wird, ohne Editionspasswort bearbeiten:

```json
{
  "viewer": {
    "trusted_local_editing": true
  }
}
```

Die Option gilt nur, solange **sowohl** `viewer.password` als auch `viewer.edition_password` leer sind, der Mehrbenutzermodus aus ist und die Konfiguration fehlerfrei geladen wurde. Ein gesetztes Editionspasswort schaltet sie ab. Sie setzt oder verrät kein Passwort, ändert keine Tokens und aktiviert keine Mehrbenutzer-Verwaltung.

Facet prüft jede Anfrage. Eine Anfrage gilt nur als vertrauenswürdig, wenn alle folgenden Bedingungen erfüllt sind:

- der TCP-Peer ist eine Loopback-Adresse (ein IPv4-gemappter Peer wie `::ffff:127.0.0.1` zählt nach seiner IPv4-Adresse);
- es gibt genau einen `Host`-Header, und er lautet `localhost`, `127.0.0.1` oder `[::1]`, mit optionalem Port;
- die Anfrage trägt keinen `Forwarded`-, `Via`-, `X-Real-IP`-, `X-Client-IP`-, `True-Client-IP`-, `CF-Connecting-IP`-, `X-Original-Forwarded-For`- oder `X-Forwarded-*`-Header;
- ein vorhandener `Origin` oder `Referer` nennt genau Schema, Host und Port, ohne Zugangsdaten (ein `Origin` mit Pfad, Query oder Fragment wird abgelehnt); ein vorhandener `Sec-Fetch-Site` lautet `same-origin` oder `none`.

Jede andere Anfrage wird behandelt, als wäre die Option aus, GET-Anfragen eingeschlossen.

Eine vertrauenswürdige Anfrage hat volle Editionsrechte auf jeder editionspflichtigen Route: Bewertungen, Vergleiche, Aussortieren (einschließlich **In Ordner aussortieren**, das Dateien verschiebt oder in den Papierkorb legt, und das Löschen einzelner Fotos), Alben, Personen und Gesichter, Gewichte, Prioritäten und Bewertungskontexte, das Einbetten von Metadaten und Exporte, Neuberechnungs- und Panoramaerkennungs-Jobs sowie die Erzeugung von Bildbeschreibungen und Kritiken. Sie kann auch ohne `viewer.features.show_scan_button` scannen. Der Scan-Fortschrittsstrom akzeptiert ein vertrauenswürdiges lokales Stream-Token nur vom selben lokalen Rechner.

**Assistenten.** Der Dialog „Assistent verbinden“ kann dann ein Token mit **Voller Bearbeitung** erstellen (`viewer.mcp.enabled` ist weiterhin erforderlich).

- Das Token wirkt nur für `/mcp`-Anfragen, die die obigen Prüfungen bestehen, als `edition`: `http://localhost:<port>` oder `127.0.0.1`, auf `:5000` oder über den `ng serve`-Dev-Proxy `:4200`.
- Von einem LAN-Client, bei einer URL mit Hostnamen oder `0.0.0.0` oder in einem Docker-Deployment wirkt es als `readonly`. Auch jedes gesetzte Passwort macht es `readonly`; das Entfernen des Passworts belebt es wieder.
- Löschwerkzeuge benötigen weiterhin `viewer.mcp.allow_destructive`. Siehe [KI-Agenten (MCP)](AGENTS.md).
- Auf einer offenen Installation geht das Erstellen, Auflisten und Widerrufen von Assistenten-Tokens, unabhängig von `trusted_local_editing`, nur mit einer Anfrage, die diese Prüfungen besteht (oder in einer Bearbeitungssitzung, wenn `viewer.edition_password` gesetzt ist).
- `ng serve --host 0.0.0.0` oder ein Proxy auf demselben Host, der keinen Weiterleitungs-Header hinzufügt, lässt einen LAN-Client mit `Host: localhost` passieren. Ein Reverse-Proxy muss `X-Forwarded-For` oder `Forwarded` senden.

> **Warnung:** Nur die Loopback-Prüfung ist eine echte Grenze; die übrigen Header setzt der Client. Ein Reverse-Proxy, Tunnel oder Port-Forward auf demselben Host, der keinen der obigen Header hinzufügt, sieht genau wie Ihr Browser aus. Aktivieren Sie diese Option nie hinter einem Reverse-Proxy auf demselben Host. Solange sie aktiv ist, kann jeder lokale Prozess und jedes Konto auf dem Rechner bearbeiten.

### Online-Ortssuche

`viewer.place_search_url` ist standardmäßig `https://photon.komoot.io/api`.

- Setzen Sie `""`, um die Adress- und Geschäftssuche zu deaktivieren, oder verweisen Sie auf einen selbst gehosteten Photon-HTTP(S)-Endpunkt (ohne Zugangsdaten, Query-Parameter oder Fragmente).
- Der Browser erfährt nur `place_search_enabled`, nie die URL.
- Suchen erfordern Edition-Zugriff und einen ausdrücklichen Klick auf **Online suchen**. Es gibt keine Wiederholungen und keine Weiterleitungen.
- Eine Anfrage läuft nach fünf Sekunden ab; die DNS-Auflösung folgt dem Betriebssystem-Resolver und kann länger dauern.

Datenschutz, Cache und Grenzen siehe [Online-Ortssuche](VIEWER.md#online-ortssuche). Die [Photon-Demo-Richtlinie](https://github.com/komoot/photon#demo-server) erlaubt eine angemessene Projektnutzung ohne Verfügbarkeitsgarantie; die [Photon-API-Dokumentation](https://github.com/komoot/photon/blob/master/docs/api-v1.md) definiert das GeoJSON-Format.

### Viewer-Performance

Überschreibt die globalen `performance`-Einstellungen nur für den Viewer, z. B. auf einem NAS mit wenig Speicher.

```json
{
  "viewer": {
    "performance": {
      "mmap_size_mb": 0,
      "cache_size_mb": 4,
      "pool_size": 2,
      "thumbnail_cache_size": 200
    }
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `mmap_size_mb` | *(global)* | Überschreibung der SQLite-mmap-Größe für Viewer-Verbindungen. `0` deaktiviert mmap. |
| `cache_size_mb` | *(global)* | Überschreibung der SQLite-Cache-Größe für Viewer-Verbindungen |
| `pool_size` | `5` | Größe des Verbindungspools (für speicherarme Systeme reduzieren) |
| `thumbnail_cache_size` | `2000` | Maximale Einträge im In-Memory-Cache für die Thumbnail-Skalierung |

Wenn nicht gesetzt, verwendet der Viewer die globalen `performance`-Werte. Siehe [Deployment](DEPLOYMENT.md) für empfohlene NAS-Einstellungen.

---

## Performance

Performance-Einstellungen der Datenbank.

```json
{
  "performance": {
    "mmap_size_mb": 2048,
    "cache_size_mb": 128,
    "slow_request_ms": 1000
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `mmap_size_mb` | `2048` | Größe des speicher-gemappten I/O von SQLite |
| `cache_size_mb` | `128` | SQLite-Cache-Größe |
| `wal_checkpoint_minutes` | `30` | Optional (nicht in der ausgelieferten Datei). Minuten zwischen den Hintergrund-WAL-Checkpoints des Viewers; `0` deaktiviert sie |
| `slow_request_ms` | `1000` | Viewer-API-Anfragen protokollieren, die langsamer als dieser Wert sind (WARNING, `SLOW`-Marker); `0` deaktiviert |

Der periodische Checkpoint (`PRAGMA wal_checkpoint(TRUNCATE)`) hält die WAL-Datei bei langlaufenden Installationen klein; ein Checkpoint läuft auch beim sauberen Herunterfahren.

---

## Storage

Wo Thumbnails und Embeddings gespeichert werden: in BLOB-Spalten der SQLite-Datenbank (Standard) oder als Dateien auf der Festplatte, um die Datenbank kleiner zu halten.

```json
{
  "storage": {
    "mode": "database",
    "filesystem_path": "./storage"
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `mode` | `"database"` | Speicher-Backend: `"database"` (SQLite-BLOBs) oder `"filesystem"` (Dateien auf der Festplatte) |
| `filesystem_path` | `"./storage"` | Basisverzeichnis für den Filesystem-Modus (`<path>/thumbnails/` und `<path>/embeddings/`) |

**Details zum Filesystem-Modus:**

- Dateien werden nach dem SHA-256-Hash des Fotopfads benannt, in zweistelligen Unterverzeichnissen (z. B. `thumbnails/a3/a3f8..._640.jpg`).
- Das Löschen eines Fotos entfernt alle zugehörigen Thumbnail-Größen und Embedding-Dateien.
- Das Verzeichnis wird bei der ersten Verwendung automatisch erstellt.

---

## Plugins

Ereignisgesteuertes Plugin-System zum Reagieren auf Bewertungsereignisse. Plugins können Python-Module, Webhooks oder integrierte Aktionen sein.

### Konfiguration

```json
{
  "plugins": {
    "enabled": true,
    "high_score_threshold": 8.0,
    "webhooks": [
      {
        "url": "https://example.com/hook",
        "events": ["on_score_complete", "on_high_score"],
        "min_score": 8.0
      }
    ],
    "actions": {
      "copy_high_scores": {
        "event": "on_high_score",
        "action": "copy_to_folder",
        "folder": "/path/to/best-photos",
        "min_score": 9.0
      }
    }
  }
}
```

| Schlüssel | Standard | Beschreibung |
|-----|---------|-------------|
| `enabled` | `false` | Hauptschalter — wenn false, werden keine Ereignisse ausgelöst |
| `high_score_threshold` | `8.0` | Minimale Gesamtbewertung, um `on_high_score`-Ereignisse auszulösen |
| `webhooks` | `[]` | Liste von Webhook-Endpunkten, die JSON-POST-Payloads empfangen |
| `actions` | `{}` | Benannte integrierte Aktionen, die durch Ereignisse ausgelöst werden |

### Unterstützte Ereignisse

| Ereignis | Auslöser | Payload |
|-------|---------|---------|
| `on_score_complete` | Nachdem jedes Foto bewertet wurde | `path`, `filename`, `aggregate`, `aesthetic`, `comp_score`, `category`, `tags` |
| `on_new_photo` | Wenn ein Foto in die Datenbank aufgenommen wird | Wie `on_score_complete` |
| `on_high_score` | Wenn aggregate ≥ `high_score_threshold` | Wie `on_score_complete` |
| `on_burst_detected` | Wenn eine Serienbildgruppe erkannt wird | `burst_group_id`, `photo_count`, `best_path`, `paths` |

### Ein Plugin schreiben

Legen Sie eine `.py`-Datei im Verzeichnis `plugins/` ab. Definieren Sie Funktionen, die nach den Ereignissen benannt sind, die Sie behandeln möchten:

```python
def on_score_complete(data: dict) -> None:
    print(f"Scored: {data['path']} — {data['aggregate']:.1f}")

def on_high_score(data: dict) -> None:
    print(f"High score! {data['path']} — {data['aggregate']:.1f}")
```

Siehe `plugins/example_plugin.py.example` für die vollständige Schnittstelle.

### Webhooks

Jeder Webhook erhält einen JSON-POST. Private und Loopback-Adressen werden blockiert:

```json
{
  "event": "on_high_score",
  "data": {
    "path": "/photos/IMG_001.jpg",
    "aggregate": 9.2,
    "aesthetic": 9.5,
    "comp_score": 8.8,
    "category": "portrait",
    "tags": "person, outdoor"
  }
}
```

Webhook-Optionen: `url` (erforderlich), `events` (Liste von Ereignisnamen), `min_score` (minimale Gesamtbewertung zum Auslösen).

### Integrierte Aktionen

| Aktion | Beschreibung | Optionen |
|--------|-------------|---------|
| `copy_to_folder` | Foto in einen Ordner kopieren | `folder`, `min_score` |
| `send_notification` | Eine Benachrichtigung protokollieren | `min_score` |

### API-Endpunkte

| Methode | Pfad | Beschreibung |
|--------|------|-------------|
| `GET` | `/api/plugins` | Geladene Plugins, Webhooks und Aktionen auflisten |
| `POST` | `/api/plugins/test-webhook` | Eine Test-Payload an eine Webhook-URL senden |

---

## Capsules

Kuratierte Foto-Diaschauen (Slideshows), nach Thema gruppiert, aus Ihrer Bibliothek erzeugt und für `freshness_hours` zwischengespeichert.

```json
{
  "capsules": {
    "min_aggregate": 6.0,
    "max_photos_per_capsule": 40,
    "max_photo_overlap": 0.2,
    "mmr_lambda": 0.5,
    "mmr_moment_weight": 0.0,
    "freshness_hours": 24,
    "reverse_geocoding": true,
    "journey": {
      "min_distance_km": 50,
      "min_photos": 8,
      "time_gap_hours": 24
    },
    "faces_of": { "min_photos": 10 },
    "seasonal": { "min_photos": 10 },
    "golden": { "percentile": 99, "max_photos": 50 },
    "color_story": { "embedding_threshold": 0.75, "min_group_size": 8, "max_groups": 5 },
    "this_week_years_ago": { "min_photos_per_year": 3 },
    "monthly": { "min_photos": 8 },
    "yearly": { "min_photos": 20, "max_photos": 60 },
    "camera": { "min_photos": 15 },
    "tag_collection": { "min_photos": 15 },
    "seeded": {
      "num_seeds": 10,
      "min_photos": 8,
      "seed_lifetime_minutes": 1440,
      "time_window_days": 7,
      "embedding_threshold": 0.7,
      "location_radius_km": 30
    },
    "progress": { "min_improvement_pct": 5, "min_photos": 10, "period_months": 3 },
    "color_palette": { "min_photos": 8 },
    "rare_pair": { "max_shared_photos": 5, "min_score": 7.0, "min_photos": 3 }
  }
}
```

### Globale Einstellungen

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `min_aggregate` | `6.0` | Minimale Gesamtbewertung, damit Fotos in Capsules aufgenommen werden |
| `max_photos_per_capsule` | `40` | Maximale Anzahl Fotos pro Capsule (MMR-Diversität wird ab 5 angewendet) |
| `max_photo_overlap` | `0.2` | Maximaler Anteil gemeinsamer Fotos zwischen zwei Capsules, bevor die Deduplizierung eine entfernt |
| `mmr_lambda` | `0.5` | MMR-Diversitätsgewicht: 0 = Diversität maximieren, 1 = Qualität maximieren |
| `mmr_moment_weight` | `0.0` | Optionales Gewicht, das die `narrative_moment_confidence` jedes Fotos in die MMR-Auswahl der Capsules einfließen lässt. `0.0` = unverändertes Verhalten |
| `freshness_hours` | `24` | Cache-TTL und Rotationsperiode für Titelbilder und Seeded-Capsules |
| `reverse_geocoding` | `true` | Offline-Reverse-Geocoding für Titel von Location-/Journey-Capsules aktivieren (erfordert das Paket `reverse_geocoder`) |

### Capsule-Typen

| Typ | Beschreibung |
|------|-------------|
| `journey` | Reisen, erkannt über GPS-Clustering + zeitliche Lücken. Titel enthalten den Zielnamen, wenn Geocoding aktiviert ist. |
| `faces_of` | Beste Fotos jeder erkannten Person |
| `seasonal` | Fotos gruppiert nach Jahreszeit + Jahr |
| `golden` | Top 1 % nach Gesamtbewertung |
| `color_story` | Visuell ähnliche Gruppen über CLIP-Embedding-Clustering |
| `this_week` | „This Week, Years Ago“ — erweitertes „On This Day“ über ±3 Tage |
| `location` | Geotagged-Fotocluster mit reverse-geocodierten Ortsnamen |
| `person_pair` | Paare benannter Personen, die zusammen erscheinen |
| `seeded` | Seed-basierte Entdeckung über Zeit, Ähnlichkeit, Person, Tag, Ort, Stimmung |
| `progress` | „Your Photography is Improving“ aus vierteljährlichen Bewertungstrends |
| `color_palette` | „Color of the Month“ aus Sättigungs-/Monochrom-Profilen |
| `rare_pair` | Seltene Personenpaare in hoch bewerteten Fotos |
| `favorites` | Favorisierte Fotos gruppiert nach Jahr und Jahreszeit |

### Dimensionsbasierte Capsules

Automatisch aus Datenbankspalten generiert:

| Dimension | Gruppiert nach |
|-----------|-----------|
| `year` | Aus date_taken extrahiertes Jahr |
| `month` | Aus date_taken extrahiertes Jahr-Monat |
| `week` | Aus date_taken extrahierte Jahr-Woche |
| `camera` | Kameramodell |
| `lens` | Objektivmodell |
| `tag` | Foto-Tags (erfordert die Tabelle `photo_tags`) |
| `day_of_week` | Wochentag (Sonntag–Samstag) |
| `composition` | SAMP-Net-Kompositionsmuster (rule_of_thirds, horizontal usw.) |
| `focal_range` | Brennweiten-Klassen: Ultraweitwinkel (<24mm), Weitwinkel (24–35mm), Standard (36–70mm), Porträt (71–135mm), Tele (136–300mm), Supertele (300mm+) |
| `category` | Inhaltskategorie des Fotos (portrait, landscape, street usw.) |
| `time_of_day` | Zeit-Klassen: goldener Morgen, Morgen, Mittag, Nachmittag, goldener Abend, Nacht |
| `star_rating` | Sternebewertungen der Benutzer (1–5 Sterne) |

Es werden auch dimensionsübergreifende Kombinationen generiert (z. B. camera × year, focal_range × category, category × year).

### Slideshow-Übergänge

Jeder Capsule-Typ wird auf einen thematischen Folienübergang abgebildet:

| Übergang | Verwendet von | Effekt |
|-----------|---------|--------|
| `crossfade` | Standard | 300ms Deckkraft-Wechsel |
| `slide` | journey, location, this_week | Von rechts hereingleiten (500ms) |
| `zoom` | faces_of, color_story | Skalierung 1.05→1.0 mit Überblendung (400ms) |
| `kenburns` | golden, seasonal, star_rating, favorites | Langsamer Zoom 1.0→1.08 über die Foliendauer |

### Reverse Geocoding

Location- und Journey-Capsules verwenden Offline-Reverse-Geocoding über das Paket `reverse_geocoder` (lokaler GeoNames-Datensatz, ~30MB, keine API-Aufrufe). Ergebnisse werden bei einer Rasterauflösung von 0,1° (~11km) zwischengespeichert.

Installation: `pip install reverse_geocoder`

Setzen Sie `"reverse_geocoding": false`, um es zu deaktivieren und auf die Koordinatenanzeige zurückzufallen.

## Similarity Groups

Einstellungen für das Culling ähnlicher Fotos, das visuell ähnliche Fotos anhand von CLIP/SigLIP-Embeddings gruppiert:

```json
{
  "similarity_groups": {
    "default_threshold": 0.85,
    "min_group_size": 2,
    "max_photos": 10000,
    "max_group_size": 50
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `default_threshold` | `0.85` | Minimale Kosinusähnlichkeit (0,0–1,0), damit zwei Fotos als ähnlich gelten; niedriger = größere, lockerere Gruppen |
| `min_group_size` | `2` | Minimale Anzahl an Fotos, um eine Ähnlichkeitsgruppe zu bilden |
| `max_photos` | `10000` | Maximale Anzahl an Fotos, die für den Vergleich geladen werden (der Aufwand wächst mit O(n²)) |
| `max_group_size` | `50` | Maximale Anzahl an Fotos pro Gruppe; größere Gruppen werden aufgeteilt |

## Auto-Cull

Ein-Knopf-Auto-Cull für die Culling-Dunkelkammer (`POST /api/culling/auto`, editionsbeschränkt). Es culled einen ganzen Bereich in einem Durchgang: alle Gruppen oder nur Serienbilder / Ähnliche / Szenen, optional auf ein Album oder ein Datumsfenster eingegrenzt. Jede Gruppe behält ihr bestes Foto plus alles innerhalb einer durch die Strenge bestimmten Marge (wie beim Schieberegler der Dunkelkammer), mindestens ein Minimum pro Gruppe, und lehnt den Rest ab.

```json
{
  "auto_cull": {
    "default_strictness": 50,
    "highlights_min": 8.0
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `default_strictness` | `50` | Behalte-Budget (0–100), wenn die Anfrage `strictness` auslässt; höher behält weniger Fotos pro Gruppe |
| `highlights_min` | `8.0` | Minimaler Aggregat-Score für das beste Foto einer Gruppe, damit es beim Anwenden in das optionale **Highlights**-Album aufgenommen wird |

- `dry_run` ist standardmäßig aktiv und liefert eine Behalte-/Ablehnen-Vorschau pro Gruppe.
- Ein Anwenden zeichnet `source='culling'`-Vergleiche auf und zählt für ein automatisches Nachtrainieren. Siehe [Web-Viewer — Auto-Cull](VIEWER.md#auto-cull).
- Dieselben Einstellungen speisen `python facet.py --auto-cull` (siehe [Culling](COMMANDS.md#culling)); seine Regeln werden aus der Server-Konfiguration gelesen, nicht aus `--config`.

## Automatisches Nachtrainieren

Steuert, wann sich der persönliche Ranker („Mein Geschmack“) neu trainiert. Jede Aussortier-Bestätigung und jede Bewertungsänderung erhöht einen Zähler pro Benutzer. Das Überschreiten von `threshold` bewaffnet das Nachtrainieren, das startet, sobald Sie `idle_seconds` lang inaktiv waren, damit es Ihr Bewerten nicht verlangsamt.

```json
{
  "auto_retrain": {
    "threshold": 25,
    "idle_seconds": 60,
    "backend": "native"
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `threshold` | `25` | Neue Vergleiche, die nötig sind, bevor ein Nachtrainieren bewaffnet wird; erhöhen Sie den Wert, wenn Sie sehr große Stapel bewerten |
| `idle_seconds` | `60` | Sekunden ohne Bewertungs-/Aussortier-Aktivität, bevor das bewaffnete Nachtrainieren startet; `0` startet es sofort |
| `backend` | `"native"` | `"native"` trainiert lokal; `"external"` behält nur Präferenzen und Zähler. Siehe [Externes Lern-Backend](#externes-lern-backend) |

Umgebungsvariablen überschreiben `threshold` und `idle_seconds` (praktisch unter Docker):

```bash
FACET_RETRAIN_THRESHOLD=100 FACET_RETRAIN_IDLE_S=300 python viewer.py
```

| Variable | Überschreibt |
|----------|--------------|
| `FACET_RETRAIN_THRESHOLD` | `auto_retrain.threshold` |
| `FACET_RETRAIN_IDLE_S` | `auto_retrain.idle_seconds` |

- Ein ungültiges `threshold` oder `idle_seconds` fällt auf den JSON-Wert zurück, dann auf den eingebauten Standard. Beide werden beim Start gelesen; Änderungen erfordern einen Neustart.
- Ein ungültiges `auto_retrain.backend` fällt auf `"external"` zurück (siehe unten).
- Ein Nachtrainieren, das das aktuelle Modell auf zurückgehaltenen Daten nicht schlägt, speichert nichts.

### Externes Lern-Backend

`"backend": "external"` behält Bewertungen, Vergleiche und ausstehende Zähler, trainiert oder bewertet aber den persönlichen Ranker, den Keeper-Head und die gelernten Gewichte nie lokal. Verwenden Sie es, wenn ein separater, vom Betreiber geführter Workflow die Scores trainiert und veröffentlicht. Facet startet keinen externen Worker.

Im externen Modus:

- Manuelle Befehle für persönlichen Ranker, Keeper-Head und Gewichtslernen melden, dass das Training zurückgestellt ist.
- Keeper-Wahrscheinlichkeiten sind nicht verfügbar; die Antworten von Vergleichen (gelernte Gewichte und Konfidenz) melden `available: false`.
- Die normale Foto-Bewertung und Stimmen bleiben unberührt.

Ein fehlerhafter `auto_retrain`-Block, ein anderes `backend` als `"native"` oder `"external"` oder eine nicht lesbare Konfiguration wählt den externen Modus und protokolliert eine Warnung. Eine gültige Konfiguration ohne `backend`-Schlüssel verwendet den nativen Modus.

## Genre-spezifische Aussortier-Profile

Genre-Vorlagen, die alle Aussortier-Regler in einem Klick setzen, über eine Auswahl in der Culling-Dunkelkammer. Sport behält nur das schärfste Bild einer langen Serie; Hochzeiten behalten mehr Varianten und verlangen offene Augen; Konzerte lockern die Augen-/Ausdruck-Schwellen; Tierwelt entfernt den Gesichtsfilter.

```json
{
  "cull_profiles": {
    "default": "balanced",
    "profiles": {
      "balanced": { "label_key": "culling.profiles.balanced", "strictness": 50, "eyes_closed_max": 4.0, "poor_expression_min": 4.0, "keep_min_per_group": 1, "similarity_threshold": 85 },
      "wedding":  { "label_key": "culling.profiles.wedding",  "strictness": 35, "eyes_closed_max": 5.0, "poor_expression_min": 5.0, "keep_min_per_group": 2, "similarity_threshold": 90 },
      "sports":   { "label_key": "culling.profiles.sports",   "strictness": 85, "eyes_closed_max": 2.0, "poor_expression_min": 0.0, "keep_min_per_group": 1, "similarity_threshold": 80 },
      "concert":  { "label_key": "culling.profiles.concert",  "strictness": 55, "eyes_closed_max": 2.0, "poor_expression_min": 0.0, "keep_min_per_group": 1, "similarity_threshold": 85 },
      "wildlife": { "label_key": "culling.profiles.wildlife", "strictness": 70, "eyes_closed_max": 0.0, "poor_expression_min": 0.0, "keep_min_per_group": 1, "similarity_threshold": 82 }
    }
  }
}
```

| Einstellung | Beschreibung |
|---|---|
| `default` | Profil-ID, wenn clientseitig keine gespeichert ist |
| `profiles.<id>.label_key` | i18n-Pfad für den Anzeigenamen der Vorlage (`culling.profiles.*`) |
| `profiles.<id>.strictness` | Behalte-Budget (0–100) für das Auto-Aussortieren mit dieser Vorlage |
| `profiles.<id>.eyes_closed_max` | Augen-offen-Wert (0–10), bei oder unter dem ein Gesicht als geschlossen gilt (überschreibt `face_detection.eyes_closed_max`) |
| `profiles.<id>.poor_expression_min` | Ausdrucks-/Lächeln-Wert (0–10), unter dem ein Gesicht als schlecht gilt (überschreibt `face_detection.poor_expression_min`) |
| `profiles.<id>.keep_min_per_group` | Untergrenze pro Gruppe für die Behalte-Menge der Auto-Aussortierung |
| `profiles.<id>.similarity_threshold` | Ähnlichkeits-Gruppierungsschwelle (Prozent), die bei aktiver Vorlage angewandt wird |

`GET /api/culling/profiles` liefert die geordnete Vorlagenliste und den Standard. `POST /api/culling/auto` und `POST /api/culling-group/faces` akzeptieren eine optionale `profile`-ID; ein explizites `strictness`/`min_keep_per_group` in der Anfrage hat Vorrang vor der Vorlage.

## Scenes

Einstellungen für die Szenen-Ansicht, die führende Serienbildfotos in chronologische Szenen gruppiert (aufgeteilt nach Lücken in der Aufnahmezeit) für ein Culling in Erzählreihenfolge:

```json
{
  "scenes": {
    "gap_minutes": 20.0,
    "min_size": 2,
    "max_photos": 5000,
    "max_scene_size": 60,
    "adaptive": true,
    "adaptive_k": 6.0
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `gap_minutes` | `20.0` | Lücke zwischen aufeinanderfolgenden führenden Serienbildfotos, die eine neue Szene beginnt (die Untergrenze, wenn `adaptive` aktiv ist) |
| `min_size` | `2` | Mindestanzahl an Fotos, damit eine Szene angezeigt wird |
| `max_photos` | `5000` | Maximale Anzahl führender Serienbildfotos, die für die Szenengruppierung geladen werden |
| `max_scene_size` | `60` | Größere Szenen werden an ihren größten internen Lücken erneut aufgeteilt |
| `adaptive` | `true` | Weitet die Lücke auf `adaptive_k × Median` der Lücken der Aufnahme (enger bei schnellem Fotografieren, lockerer bei spärlichen Urlauben) |
| `adaptive_k` | `6.0` | Multiplikator, der auf die Median-Lücke angewendet wird, wenn `adaptive` aktiv ist |
| `split_on_moment_change` | `false` | Sind narrative Momente berechnet, wird zusätzlich dort aufgeteilt, wo sich der dominante Moment für `moment_split_min_run` Frames ändert |
| `moment_split_min_run` | `4` | Aufeinanderfolgende Frames, die ein neuer Moment bestehen muss, um eine Szenengrenze zu erzwingen |

## Narrative Moments

Labelt den Szenen-/Aktivitäts-„Moment“ jedes Fotos ohne Training. Das standardmäßige **general**-Vokabular umfasst `celebration`, `dining`, `beach`, `water_activity`, `mountains`, `nature_wildlife`, `cityscape`, `travel_landmark`, `concert`, `sports`, `group_gathering`, `portrait`, `children`, `pets`, `nightlife`, `ceremony`, `scenic_landscape`, `snow_winter`, `home_indoor`, `road_vehicle` oder `other`. `wedding` wird als optionales Genre mitgeliefert. `--detect-moments` befüllt sie (läuft auch am Ende jedes Scans); sie erscheinen als Szenennamen und als Galeriefilter.

Facet vergleicht die einmal kodierte und gespeicherte KI-Bildunterschrift jedes Fotos (`caption_embedding`) mit Text-Prompts für jeden Moment und behält die beste Übereinstimmung. Ohne Bildunterschrift wird das Bild-Embedding verwendet. Bildunterschriften passen sauberer, weshalb das `caption`-Signal höhere Schwellen trägt als die `image`-Rückfalloption, abgestimmt pro Backend. Die `transformers`-Werte (SigLIP) sind konservative Standardwerte; stimmen Sie sie neu ab, wenn Sie ein SigLIP-Profil verwenden.

```json
{
  "narrative_moments": {
    "enabled": true,
    "prompt_template": "a photo of {desc}",
    "default_event_type": "general",
    "pooling": "max",
    "caption_min_confidence": 0,
    "thresholds": {
      "caption": {
        "open_clip": { "min_confidence": 0.30, "min_margin": 0.02 },
        "transformers": { "min_confidence": 0.12, "min_margin": 0.01 }
      },
      "image": {
        "open_clip": { "min_confidence": 0.20, "min_margin": 0.01 },
        "transformers": { "min_confidence": 0.10, "min_margin": 0.01 }
      }
    },
    "priors": {
      "enabled": true, "weight": 0.04, "caption_tag_scale": 0.25,
      "rules": [
        { "kind": "structural", "when": { "is_group_portrait": true, "face_count_min": 4 }, "boost": { "group_gathering": 1.0 } },
        { "kind": "tag", "when": { "tags_any": ["beach", "ocean", "sand"] }, "boost": { "beach": 0.8 } }
      ],
      "event_types": { "wedding": { "rules": [ { "kind": "tag", "when": { "tags_any": ["cake"] }, "boost": { "cake_cutting": 1.0 } } ] } }
    },
    "vlm_tiebreak": { "enabled": false, "min_confidence": 0.0, "min_margin": 0.04 },
    "transitions": { "stay_prob": 0.7, "forward_bias": 0.0, "weight": 0.3 },
    "event_types": { "general": { "beach": ["people at a sandy beach by the sea", "..."], "...": [] }, "wedding": { "vows": ["the couple exchanging vows at the altar", "..."] } }
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `enabled` | `true` | Hauptschalter; wenn aus, tun `--detect-moments` und der Scan-Hook nichts |
| `prompt_template` | `"a photo of {desc}"` | Wrapper, der vor dem Encoding auf jeden Prompt angewendet wird |
| `default_event_type` | `"general"` | Aktives `event_types`-Vokabular (`general` = 20 Momente; `wedding` optional) |
| `pooling` | `"max"` | Score pro Moment = die beste einzelne Prompt-Übereinstimmung |
| `caption_min_confidence` | `0` | Wenn > 0, überspringt die Bildunterschriften-Erzeugung Fotos, die ungelabelt, `other` oder unterhalb dieser Konfidenz sind; `0` = kein Gate |
| `thresholds.<signal>.<backend>.min_confidence` | caption `0.30`/`0.12`, image `0.20`/`0.10` | Liegt der Top-1-Kosinus darunter, ist ein Foto `other` (aufgeschlüsselt nach Signal, dann Backend) |
| `thresholds.<signal>.<backend>.min_margin` | caption `0.02`/`0.01`, image `0.01`/`0.01` | Minimaler Kosinusabstand zwischen Top-1 und Top-2; darunter ist der Frame `other` |
| `priors.enabled` / `priors.weight` | `true` / `0.04` | Kleine Anstöße aus Gesicht/Tag, die nur knappe Gleichstände auflösen; `weight` begrenzt jeden Boost |
| `priors.caption_tag_scale` | `0.25` | Dämpft **tag**-Regeln beim Caption-Signal; strukturelle Regeln behalten ihr volles Gewicht |
| `priors.rules` | (allgemeines Set) | Liste von `{kind, when, boost}`-Regeln (siehe unten) |
| `priors.event_types.<et>.rules` | `wedding`-Override | Regeln, die die globalen `rules` **ersetzen**, solange dieses Vokabular aktiv ist |
| `transitions.stay_prob` / `forward_bias` / `weight` | `0.7` / `0.0` / `0.3` | Timeline-Glättung zwischen benachbarten Frames (`weight=0` = keine) |
| `vlm_tiebreak.enabled` / `min_confidence` / `min_margin` | `false` / `0.0` / `0.04` | Auf 16gb/24gb nur Frames mit geringer Konfidenz oder geringem Abstand vom Profil-VLM neu klassifizieren |
| `event_types` | `general` + `wedding` | Pro Ereignistyp `{moment: [Prompt-Synonyme]}`; setzen Sie `default_event_type`, um das Genre zu wechseln, oder fügen Sie Ihr eigenes hinzu |

Format von `priors.rules`:

- `kind`: `structural` (Gesichtsgeometrie) oder `tag`.
- `when` (alle müssen zutreffen): `is_group_portrait`, `face_count_min`/`face_count_max`, `face_ratio_min`/`face_ratio_max`, `tags_any`, `tags_all`.
- `boost`: `{moment: Betrag}`. Ein im aktiven Vokabular fehlender Moment wird übersprungen.

Der VLM-Tie-Break läuft während `--detect-moments` / `--recompute-moments`.

> **Kosten des Caption-Backfills.** Bildunterschrift-Embeddings werden einmal berechnet und gespeichert. Ein Scan kodiert nur seine neuen Bildunterschriften, aber der erste Durchlauf über eine bestehende Bibliothek kodiert jede: schnell auf der GPU, Stunden auf der CPU. Führen Sie `python facet.py --detect-moments` einmal aus (GPU empfohlen); fügen Sie `--limit N` hinzu, um es zuerst an einer Stichprobe zu prüfen.

**Ein bibliotheksspezifisches Vokabular entdecken.** `python facet.py --discover-moments` clustert die gespeicherten `caption_embedding`-Vektoren, benennt jedes Cluster anhand seiner Bildunterschriften und schreibt einen Block `event_types.discovered` in `scoring_config.discovered.json`. Die aktive Konfiguration ändert es nie. Um es zu übernehmen, kopieren Sie `discovered` in `event_types`, setzen Sie `default_event_type` auf `discovered` und führen Sie `--recompute-moments` aus. `--discover-min-cluster-size N` steuert die Granularität (kleiner = mehr, feinere Momente).

## OCR

Textsuche in Fotos: liest die Wörter *innerhalb* Ihrer Fotos (Straßenschilder, Ladenfronten, Startnummern, Buchrücken, Dias, Whiteboards, gescannte Dokumente) in `photos.ocr_text`. Dieser Text ist dann über die Suchleiste der Galerie durchsuchbar wie jede Bildunterschrift oder jeder Tag; `GET /api/search?scope=text` durchsucht nur Textfelder.

**Standardmäßig deaktiviert**, und benötigt eine installierte Engine:

```bash
pip install easyocr           # oder: pip install -e .[ocr]
```

Dann aktivieren und den Durchlauf starten:

```json
{
  "ocr": {
    "enabled": false,
    "languages": ["en", "fr"],
    "min_confidence": 0.4,
    "full_resolution": false
  }
}
```

```bash
python facet.py --detect-text      # nur nie ausgewertete Fotos
python facet.py --recompute-text   # liest die gesamte Bibliothek neu
```

| Schlüssel | Standard | Beschreibung |
|-----|---------|-------------|
| `enabled` | `false` | Hauptschalter; `--detect-text` verweigert die Ausführung, solange er `false` ist |
| `languages` | `["en", "fr"]` | An die Engine übergebene Sprachcodes; eine Schriftfamilie pro Lauf (easyocr lehnt z. B. `en` + `ja` ab) |
| `min_confidence` | `0.4` | Verwirft Erkennungen, die unter diesem Wert (0–1) bewertet werden; erhöhen Sie ihn gegen Rauschen, senken Sie ihn für schwachen Text |
| `full_resolution` | `false` | OCR am Original statt am 640px-Thumbnail (deutlich langsamer; fällt auf das Thumbnail zurück, wenn offline) |

Hinweise:

- `ocr_text` ist `NULL`, bis ein Foto ausgewertet wurde, und `''`, wenn es keinen Text hat. `--detect-text` liest nur `NULL`-Fotos; `--recompute-text` liest alles neu.
- **Kein `--rebuild-fts` nötig:** Der Durchlauf aktualisiert den Suchindex beim Schreiben. `python database.py --rebuild-fts` ist nur für eine Datenbank nötig, die erstellt wurde, bevor es OCR gab, und `init_database` erledigt das für Sie.
- Das 640px-Thumbnail löst Schilder, Poster und Dokumentüberschriften bereits auf.

**Engines.** `easyocr` (Apache-2.0, PyTorch) ist der Standard und nutzt den bestehenden Stack von Facet. Seine Gewichte (~113MB) werden beim ersten Lauf von den projekteigenen GitHub-Releases heruntergeladen. Die `tesseract`-Binary plus `pytesseract` wird verwendet, wenn easyocr fehlt, liest Szenentext aber schlechter. Ist keines von beiden installiert, bricht der Durchlauf mit einem Fehler ab.

**Kosten.** Rund 0,4s pro Thumbnail auf der CPU, sodass eine Bibliothek mit 50.000 Fotos ein einmaliger Job über Nacht ist; spätere Scans fügen nur neue Fotos hinzu. Eine GPU wird automatisch verwendet, wenn torch eine meldet.

## Ziele für Export und Aussortierung

Album-Export (`POST /api/albums/{id}/export`, Modi `copy`/`symlink`) und In-Ordner-aussortieren (`POST /api/cull/apply`, Aktionen `copy_keeps` / `move_rejects`) schreiben in ein `target_dir`. Es muss unter einer erlaubten Wurzel liegen, sonst wird die Anfrage abgelehnt, bevor irgendeine Datei berührt wird.

```json
{
  "viewer": {
    "export": {
      "allowed_target_dirs": ["/data/exports"]
    },
    "cull": {
      "allow_trash": false
    }
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `allowed_target_dirs` | *(Schlüssel fehlt)* | Zusätzliche Wurzeln, in die Export und In-Ordner-aussortieren schreiben dürfen, neben den Scan-Verzeichnissen (immer erlaubt) |
| `cull.allow_trash` | `false` | Die Aktion `trash_rejects` von „In Ordner aussortieren“ erlauben (System-Papierkorb über `send2trash`, wiederherstellbar); aus blendet die Option aus |

**Mehrbild-Sets und Sammelaktionen.** Sind `hide_brackets` / `hide_panoramas` aktiv (Standard, siehe [Web-Viewer — Standardfilter](VIEWER.md#standardfilter)), enthält eine Auswahl nur das repräsentative Bild jedes Sets, sodass Sammelaktionen nur auf dieses Bild wirken. Das Opt-in `include_sequence_siblings` von In-Ordner-aussortieren weitet ein getroffenes Foto auf sein gesamtes Set aus; siehe [Web-Viewer — In Ordner aussortieren § Mehrbild-Sets](VIEWER.md#in-ordner-aussortieren).

**Auflösungsreihenfolge.** Erlaubte Wurzeln sind `allowed_target_dirs`, dann jedes Scan-Verzeichnis (pro Benutzer, gemeinsam und `path_mapping`-Ziele). Exportieren innerhalb des Fotobaums braucht keine Einrichtung; ein Ziel außerhalb davon braucht hier einen Eintrag. Symlinks und `..` werden vor der Prüfung aufgelöst (`os.path.realpath()`), sodass ein Link, der außerhalb einer erlaubten Wurzel zeigt, abgelehnt wird.

**Standardmäßig geschlossen (fail-closed).** Ohne `allowed_target_dirs` und ohne Scan-Verzeichnisse wird Kopier-/Symlink-/Verschiebe-Export verweigert.

**Fehlersuche bei „Zugriff verweigert“.** Die Web-Oberfläche zeigt einen allgemeinen „Zugriff verweigert“-Hinweis. Um den Grund zu sehen, öffnen Sie den Netzwerk-Tab des Browsers, suchen die fehlgeschlagene Anfrage an `/api/cull/apply` oder `/api/albums/{id}/export` und lesen das Feld `detail`: entweder diese Allowlist oder eine abgelaufene Bearbeitungssitzung. Ein echter Dateisystem-Rechtefehler sieht anders aus: Die Anfrage gelingt, die `errors`-Anzahl in der Antwort ist ungleich null, und das Server-Log enthält einen Traceback pro Datei. Siehe [Deployment — Pfadsemantik im Container](DEPLOYMENT.md#pfadsemantik-im-container) für den Container-Fall.

Siehe [Web-Viewer — In Ordner aussortieren](VIEWER.md#in-ordner-aussortieren) und [Web-Viewer — Editor-Export](VIEWER.md#editor-export).

## Social-Export

Zuschneide-Vorlagen für Social-Media-Seitenverhältnisse, auf das Motiv gerahmt (`GET /api/photo/social_crop`, editionsbeschränkt). Jede Vorlage schneidet das Original in voller Auflösung auf das größte Rechteck dieses Seitenverhältnisses, zentriert auf dem Motiv. Das Motiv ist die BiRefNet-Motivbox (`photos.subject_bbox`), sonst die Vereinigung der Gesichtsboxen, sonst die Bildmitte. Siehe [Web-Viewer — Download](VIEWER.md#download).

```json
{
  "social_export": {
    "presets": {
      "square":       { "label_key": "social_export.presets.square",       "aspect": "1:1" },
      "portrait_4x5": { "label_key": "social_export.presets.portrait_4x5", "aspect": "4:5" },
      "story_9x16":   { "label_key": "social_export.presets.story_9x16",   "aspect": "9:16" }
    },
    "jpeg_quality": 92
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `presets.<id>.label_key` | — | i18n-Punktpfad für den Anzeigenamen der Vorlage (`social_export.presets.*`) |
| `presets.<id>.aspect` | — | Zielseitenverhältnis als `"b:h"` (z. B. `1:1`, `4:5`, `9:16`) |
| `jpeg_quality` | `92` | JPEG-Qualität des exportierten Zuschnitts |

Gesteuert durch `viewer.features.show_social_export` (Standard `true`). Die Motivbox wird vom Saliency-Durchlauf beim Scannen und von `--recompute-saliency` geschrieben; ältere Fotos nutzen den Gesichts- oder zentrierten Zuschnitt.

## Portfolio-Export

Exportiert ein Album als eigenständige statische HTML-Galerie, die Sie auf jedem Webhoster ablegen können (`POST /api/albums/{album_id}/export-portfolio`, editionsbeschränkt).

- Das Ausgabeverzeichnis enthält `index.html` (Miniaturraster und Lightbox, keine externen oder CDN-Verweise), einen Ordner `assets/` mit fortlaufend benannten JPEGs (keine Bibliothekspfade) und eine `manifest.json`.
- Jedes Foto nutzt das **Original**, auf `max_edge` verkleinert, oder das gespeicherte 640-px-Thumbnail, wenn das Original nicht erreichbar ist. Das Manifest hält fest, was verwendet wurde.
- Ein erneuter Export überschreibt nur seine eigenen Dateien.

```json
{
  "portfolio": {
    "max_photos": 500,
    "max_edge": 2048,
    "jpeg_quality": 88
  }
}
```

| Einstellung | Standard | Beschreibung |
|-------------|----------|--------------|
| `max_photos` | `500` | Größere Alben werden abgelehnt (der Export läuft synchron) |
| `max_edge` | `2048` | Obergrenze der langen Kante (px) für exportierte Originale; die Anfrage kann sie überschreiben (auf 256–8000 begrenzt) |
| `jpeg_quality` | `88` | JPEG-Qualität der exportierten Bilder |

Das `target_dir` nutzt dieselbe Allowlist wie die anderen Exporte (`viewer.export.allowed_target_dirs` plus die Scan-Verzeichnisse — siehe [Ziele für Export und Aussortierung](#ziele-für-export-und-aussortierung)). Gesteuert durch `viewer.features.show_portfolio_export` (Standard `true`). Siehe [Web-Viewer — Portfolio-Export](VIEWER.md#portfolio-export).

## Agent-Endpunkt (MCP)

Stellt die in [KI-Agenten (MCP)](AGENTS.md) beschriebenen Werkzeuge unter `POST /mcp` bereit: Lesen, Steuern des geöffneten Tabs und, je nach Token-Stufe, Ändern von Bewertungen, Tags und Alben sowie Aussortieren und Löschen. Er ist standardmäßig aktiv.

Bei einer offenen Installation (ohne `viewer.password`):

- `/mcp` liefert nur einen schreibgeschützten anonymen Schlüssel, der nichts zeigt, was die offene `/api` nicht ohnehin zeigt.
- Ein neues Token ist `readonly`, außer `viewer.trusted_local_editing` ist aktiv oder die Sitzung ist mit `viewer.edition_password` angemeldet: Beide können ein Token mit voller Bearbeitung erzeugen, das nur bei Anfragen vom selben Rechner bearbeitet.
- Tokens lassen sich nur auf dem Rechner erstellen, auflisten und widerrufen, auf dem Facet läuft (oder in einer Bearbeitungssitzung, wenn `viewer.edition_password` gesetzt ist).

```json
{
  "viewer": {
    "mcp": {
      "enabled": true,
      "bridge": true,
      "max_rows": 100,
      "max_bytes": 60000,
      "max_image_bytes": 262144,
      "call_timeout_s": 30,
      "semantic_timeout_s": 120,
      "rate_per_min": 120,
      "write_rate_per_min": 30,
      "tool_profile": "full",
      "allow_destructive": false,
      "inpage_tools": true,
      "allowed_origins": []
    }
  }
}
```

| Schlüssel | Standard | Beschreibung |
|-----|---------|-------------|
| `enabled` | `true` | Hauptschalter für `/mcp` und `/api/mcp/*` |
| `bridge` | `true` | Erlaubt die Brücke zum Browser-Tab (`/api/mcp/bridge`), damit `ui_*`-Werkzeuge einen Tab erreichen können; erfordert einen einzigen Worker |
| `max_rows` | `100` | Höchstzahl an Zeilen in einem Werkzeug-Ergebnis (1 bis 500); überzählige Zeilen setzen `truncated: true` |
| `max_bytes` | `60000` | Maximale serialisierte Größe eines Werkzeug-Ergebnisses in Bytes (4000 bis 500000). |
| `max_image_bytes` | `262144` | Maximale Bildgröße von `get_thumbnail` oder `contact_sheet` (32768 bis 2097152); nicht in `max_bytes` eingerechnet |
| `call_timeout_s` | `30` | Zeitlimit für einen Werkzeugaufruf in Sekunden (1 bis 300), zugleich das Warten von `ui_*` auf den Tab (`tab_timeout`) |
| `semantic_timeout_s` | `120` | Zeitlimit für `semantic_search` in Sekunden (1 bis 300); es lädt das Embedding-Modell und braucht daher mehr. |
| `rate_per_min` | `120` | Werkzeugaufrufe pro Minute und Token (mindestens 1). |
| `write_rate_per_min` | `30` | Schreibende Aufrufe pro Minute und Token (mindestens 1), getrennt geführt, damit Lesezugriffe Schreibzugriffe nicht aushungern |
| `tool_profile` | `"full"` | `"full"` listet jedes erlaubte Werkzeug; `"core"` listet einen Satz von 11 Werkzeugen für kleine Modelle |
| `allow_destructive` | `false` | Erlaubt `delete_photos`, die Aktionen `move_rejects`/`trash_rejects` von `cull_apply` und `assign_faces` mit `allow_reassign` |
| `inpage_tools` | `true` | Erlaubt einem angemeldeten Tab, die Werkzeuge des Servers aus der Seite aufzurufen (`GET /api/mcp/inpage_tools`, `POST /api/mcp/call`) |
| `allowed_origins` | `[]` | Zusätzliche Browser-Ursprünge (z. B. `["https://photos.example.com"]`), die hinter einem `Host`-umschreibenden Proxy die Tab-Brücke öffnen dürfen; nicht der CORS-Schlüssel `viewer.allowed_origins` |

Hinweise:

- **`enabled: false`** schaltet `/mcp` und `/api/mcp/*` ab (die Brücke schließt mit Code 4404). **`bridge: false`** lehnt die Brücke ab und lässt `ui_*`-Werkzeuge einen Fehler zurückgeben.
- **`write_rate_per_min`** gilt für die Schreibwerkzeuge, einschließlich des Probelaufs von `cull_apply` und `delete_photos`; siehe [KI-Agenten](AGENTS.md#änderungen-vornehmen).
- **`"core"`** listet `status`, `search_photos`, `semantic_search`, `get_photo`, `filter_options`, `library_stats`, `ui_show_photos`, `set_rating`, `set_favorite`, `set_rejected`, `album_add_photos`. Nur die Liste ändert sich; andere Werkzeuge können weiter aufgerufen werden, wenn die Stufe des Schlüssels es erlaubt. Jeder andere Wert bedeutet `"full"`. Siehe [KI-Agenten](AGENTS.md#berechtigungsstufen).
- **`allow_destructive: false`** blendet `delete_photos` aus; die beiden anderen antworten `feature_disabled` mit Nennung dieses Schlüssels. Siehe [KI-Agenten](AGENTS.md#destruktive-aktionen-vorschau-dann-bestätigung).
- **`inpage_tools`** führt Werkzeuge als die Sitzung aus, mit deren aktueller Stufe. Aus, ist `features.mcp_inpage` in `/api/auth/status` falsch. Siehe [KI-Agenten](AGENTS.md#webmcp-im-tab-browser-agenten).
- Zahlen außerhalb des Bereichs werden begrenzt; ein Wert des falschen Typs verwendet den Standard. Änderungen gelten beim Neuladen der Konfiguration, ohne Neustart.

## Bilderrahmen / Kiosk

Liefert kuratierte beste Aufnahmen an Kiosk-Geräte ohne Anmeldung: smarte Bilderrahmen, Home-Assistant-Dashboards, Anzeigen im Stil von ImmichFrame / Immich-Kiosk. Drei Endpunkte verwenden ein statisches Token: `GET /api/frame/photos`, `GET /api/frame/image/{id}`, `GET /api/frame/next`. Eine leere `tokens`-Liste deaktiviert die Funktion (die Endpunkte antworten 404). Antworten enthalten niemals Dateipfade; Fotos werden über eine signierte Kennung adressiert.

```json
{
  "frame": {
    "tokens": [],
    "count": 20,
    "max_count": 100,
    "min_aggregate": 7.0,
    "max_edge": 1920,
    "favorites_only": false,
    "categories": []
  }
}
```

| Einstellung | Standard | Beschreibung |
|-------------|----------|--------------|
| `tokens` | `[]` | Rahmen-Tokens, eine lange Zufallszeichenkette pro Gerät; entfernen Sie eines, um es zu widerrufen. **Leer = Funktion deaktiviert.** |
| `count` | `20` | Standardanzahl der von `/api/frame/photos` zurückgegebenen Fotos |
| `max_count` | `100` | Harte Obergrenze für den Abfrageparameter `count` |
| `min_aggregate` | `7.0` | Mindest-Aggregatwert, damit ein Foto kuratiert wird |
| `max_edge` | `1920` | Obergrenze der langen Kante (px) für ausgelieferte JPEGs; der Abfrageparameter `max_edge` kann sie nur senken |
| `favorites_only` | `false` | Wenn `true`, werden nur favorisierte Fotos kuratiert |
| `categories` | `[]` | Positivliste von Kategorienamen (leer = alle) |

Erzeugen Sie ein Token mit `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

Die Kuratierung überspringt abgelehnte, Junk- (`junk_kind`) und Blinzel-Fotos, wendet die Filter für Score, Favoriten und Kategorien an und wählt dann eine score-gewichtete Zufallsstichprobe. Das Home-Assistant-Rezept steht unter [Web-Viewer — Bilderrahmen / Kiosk](VIEWER.md#bilderrahmen--kiosk).

> **Warnung:** Ein Rahmen-Token ist keine Benutzeranmeldung. Im [Mehrbenutzermodus](#users) ignoriert es die privaten `directories` jedes Benutzers und kann die Fotos aller Benutzer lesen, nicht nur `shared_directories`. Geben Sie Rahmen-Tokens nur aus, wo jeder Benutzer damit einverstanden ist.

## Automatischer Upload vom Telefon

Ein minimaler **WebDAV**-Endpunkt unter `/dav` lässt Foto-Auto-Upload-Apps (PhotoSync u. a.) Fotos in ein **Eingangsverzeichnis** (Inbox) hochladen, das `facet.py --watch` anschließend bewertet. Der Zugriff erfolgt per HTTP Basic mit **Zugangsdaten für gemeinsam genutzte Geräte** (`username` / `password`), nicht mit einem Benutzerkonto.

- `/dav` liefert **404**, bis `username`, `password` und `inbox_dir` alle gesetzt sind.
- Jede Operation bleibt innerhalb von `inbox_dir`; Pfad-Traversal, absolute Pfade und Symlink-Ausbrüche werden abgewiesen.
- Uploads werden atomar geschrieben und durch `max_file_mb` begrenzt.

```json
{
  "upload": {
    "username": "",
    "password": "",
    "inbox_dir": "",
    "max_file_mb": 500
  }
}
```

| Einstellung | Standard | Beschreibung |
|-------------|----------|--------------|
| `username` | `""` | HTTP-Basic-Benutzername (Zugangsdaten für gemeinsam genutztes Gerät). **Leer = Funktion deaktiviert.** |
| `password` | `""` | HTTP-Basic-Passwort; verwenden Sie eine lange Zufallszeichenfolge. **Leer = Funktion deaktiviert.** |
| `inbox_dir` | `""` | Absoluter Pfad des Upload-Eingangsverzeichnisses, bei Bedarf angelegt. **Leer = Funktion deaktiviert.** |
| `max_file_mb` | `500` | Größenlimit pro Datei (MB); ein größerer Upload wird abgebrochen und hinterlässt keine Teildatei |

Richten Sie `inbox_dir` auf eines der gescannten Verzeichnisse (oder ein Unterverzeichnis), damit `facet.py --watch` Uploads beim Eintreffen bewertet.

Unterstützte Methoden: `OPTIONS`, `PROPFIND` (Tiefe 0/1), `MKCOL`, `PUT`, `MOVE`, `DELETE`, `GET`, `HEAD` (kein `LOCK`/`UNLOCK`). Ein fehlender oder falscher `Authorization`-Header ergibt `WWW-Authenticate: Basic realm="Facet upload"`. Das PhotoSync-Rezept und einen `curl`-Schnelltest finden Sie unter [Web-Viewer — Automatischer Upload vom Telefon](VIEWER.md#automatischer-upload-vom-telefon).

## Junk Sweep

Markiert nicht-fotografischen „Müll“ (Screenshots, gescannte Dokumente, Belege, Memes, Präsentationsfolien) anhand des **gespeicherten Bild-Embeddings**, ohne Bild zu dekodieren. Jede Art hat eine Liste von Text-Prompts, und der am besten passende Prompt zählt für diese Art.

- Ein Foto wird nur markiert, wenn seine beste Müll-Art `min_confidence` erreicht **und** den besten `not_junk`-Prompt um `min_margin` schlägt.
- Andernfalls wird es als `not_junk` gespeichert (bewertet, sauber). `NULL` bedeutet noch nicht bewertet.
- `--detect-junk` beschriftet nur `NULL`-Fotos (und läuft am Ende jedes Scans); `--recompute-junk` prüft die gesamte Bibliothek neu.
- Die Ergebnisse landen in `photos.junk_kind` und werden in der **Junk-Sweep**-Warteschlange des Viewers ([VIEWER.md](VIEWER.md#müll-aufräumen)) geprüft.

```json
{
  "junk_sweep": {
    "enabled": true,
    "prompt_template": "{desc}",
    "pooling": "max",
    "thresholds": {
      "open_clip": { "min_confidence": 0.2, "min_margin": 0.06 },
      "transformers": { "min_confidence": 0.1, "min_margin": 0.02 }
    },
    "kinds": {
      "screenshot": ["a screenshot of a phone user interface", "..."],
      "document": ["a scanned document", "..."],
      "receipt": ["a close-up photo of a paper receipt", "..."],
      "meme": ["a meme with overlaid text", "..."],
      "slide": ["a presentation slide", "..."]
    },
    "not_junk_prompts": ["a natural photograph", "a candid photo of people", "..."]
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `enabled` | `true` | Führt die Müllerkennung während `--detect-junk` / `--recompute-junk` und am Scan-Ende aus |
| `prompt_template` | `"{desc}"` | Formatstring, der auf jeden Prompt angewendet wird (`{desc}` = der Prompt); standardmäßig unverändert |
| `pooling` | `"max"` | Kombiniert die Prompt-Werte pro Art per `max` (bester einzelner Prompt) oder `mean` |
| `thresholds.<backend>.min_confidence` | open_clip `0.2`, transformers `0.1` | Minimaler Wert für die beste Müll-Art (pro Backend; CLIP/`open_clip`-Werte liegen niedriger als SigLIP/`transformers`) |
| `thresholds.<backend>.min_margin` | open_clip `0.06`, transformers `0.02` | Wie weit die beste Müll-Art den besten `not_junk`-Kontrast-Prompt schlagen muss, bevor das Foto markiert wird |
| `kinds` | screenshot/document/receipt/meme/slide | `{Art: [Prompt-Synonyme]}`; fügen Sie Arten frei hinzu, entfernen oder benennen Sie sie um |
| `not_junk_prompts` | 8 Foto-Prompts | Prompts, die echte Fotografien beschreiben und echte Fotos aus der Warteschlange heraushalten |

## AI Critique

Prompt-Einstellungen für die VLM-Kritik (Profile 16gb/24gb). Die Kritik speist Regelaufschlüsselung, Strafen und EXIF in das VLM ein und zeigt dessen Antwort als Observation / Assessment / Suggestions.

- Das Assessment behandelt Komposition, Farbe & Licht, Fokus/Schärfentiefe & technische Ausführung sowie Motiv & Moment, abgeglichen mit den Metriken.
- Es wird pro Foto zwischengespeichert (`photos.vlm_critique`, Übersetzungen in `vlm_critique_translated`); `refresh` erzeugt es neu.
- Es läuft gegen das gespeicherte Thumbnail, sodass RAW-Dateien funktionieren.

```json
{
  "critique": {
    "vlm": {
      "max_new_tokens": 320
    }
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `critique.vlm.max_new_tokens` | `320` | Token-Budget für die Generierung der strukturierten VLM-Kritik |

Siehe [Web-Viewer — KI-Kritik](VIEWER.md#ki-kritik).

## VLM Backend

Wählt, wo das Vision-Language-Modell für Bildunterschriften/Tags läuft. `local` (Standard) verwendet das eingebaute Qwen-Modell der Profile 16gb/24gb. Die beiden entfernten Backends nutzen einen externen Server, sodass Bildbeschreibung und VLM-Tagging auch auf den **Profilen legacy/8gb ohne lokales VLM** funktionieren.

```json
{
  "vlm_backend": {
    "type": "local",
    "ollama": {
      "base_url": "http://localhost:11434",
      "model": "qwen2.5vl:7b",
      "timeout_seconds": 120
    },
    "openai_compatible": {
      "base_url": "http://localhost:1234/v1",
      "api_key": "",
      "model": "qwen2.5-vl-7b",
      "timeout_seconds": 120
    }
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `type` | `"local"` | `local` (eingebautes Qwen), `ollama` (Ollama-REST-API) oder `openai_compatible` (LM Studio, vLLM, OpenRouter, …) |
| `ollama.base_url` | `"http://localhost:11434"` | Basis-URL des Ollama-Servers (Bilder gehen an `POST /api/generate`) |
| `ollama.model` | `"qwen2.5vl:7b"` | Ollama-Modell-Tag (muss ein Vision-Modell sein, das auf dem Server bereits geladen wurde) |
| `ollama.timeout_seconds` | `120` | Timeout pro Anfrage für Ollama-Aufrufe |
| `openai_compatible.base_url` | `"http://localhost:1234/v1"` | Basis-URL **einschließlich des `/v1`-Suffixes** (Anfragen gehen an `{base_url}/chat/completions`, das Bild als `image_url`-Daten-URI) |
| `openai_compatible.api_key` | `""` | Gesendet als `Authorization: Bearer <schlüssel>`; für schlüssellose lokale Server leer lassen |
| `openai_compatible.model` | `"qwen2.5-vl-7b"` | An den Endpunkt übergebener Modellname |
| `openai_compatible.timeout_seconds` | `120` | Timeout pro Anfrage für OpenAI-kompatible Aufrufe |

Das Backend steuert die Bildbeschreibung (`--generate-captions` und `/api/caption`), die VLM-Kritik (`/api/critique?mode=vlm`), das VLM-Re-Tagging (`--recompute-tags-vlm`) und den Tie-Break für narrative Momente. Eine fehlgeschlagene entfernte Anfrage lässt nur dieses Foto scheitern (protokolliert, keine Tags oder Bildunterschrift). Das In-Scan-Tagging verwendet weiterhin den Tagger des Profils; führen Sie `--recompute-tags-vlm` aus, um ein entferntes Backend auf eine bestehende Bibliothek anzuwenden.

## Distortion Attributes

Beratende Verzerrungs-Labels. `--recompute-distortions` vergleicht das gespeicherte CLIP/SigLIP-Embedding jedes Fotos mit Prompts für häufige Defekte (Bewegungsunschärfe, Farbstich, Überschärfung, …) und speichert die wahrscheinlichen. Sie beeinflussen nie den Score; sie erscheinen als Warnungs-Chips im Kritik-Dialog.

```json
{
  "distortion_attributes": {
    "enabled": true,
    "top_n": 5,
    "thresholds": {
      "open_clip":    { "temperature": 0.02, "min_confidence": 0.6 },
      "transformers": { "temperature": 0.05, "min_confidence": 0.6 }
    },
    "vocabulary": {}
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `enabled` | `true` | Verzerrungsattribute während `--recompute-distortions` berechnen |
| `top_n` | `5` | Maximale Anzahl an Verzerrungs-Labels, die pro Foto behalten werden |
| `thresholds.<backend>.temperature` | open_clip `0.02`, transformers `0.05` | Softmax-Temperatur über die Prompt-Scores, pro Embedding-Backend (die Skalen unterscheiden sich, wie bei `narrative_moments`) |
| `thresholds.<backend>.min_confidence` | `0.6` | Minimale Wahrscheinlichkeit, damit ein Verzerrungs-Label behalten wird |
| `vocabulary` | `{}` | Optionale Überschreibung der integrierten Prompts (`{attribute: [prompt synonyms]}`); leer = Standardwerte |

## Skin Tone

Beratende Prüfung des Porträt-Hauttons. `--recompute-skin-tone` misst die Wangenfarbe auf den gespeicherten Gesichts-Thumbnails und markiert Porträts, deren Haut ins Grüne, Magenta, Blaue oder Gelbe driftet. Es beeinflusst nie den Score; das Ergebnis erscheint als Hinweis im Kritik-Dialog.

```json
{
  "skin_tone": {
    "cast_delta_threshold": 12.0
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `cast_delta_threshold` | `12.0` | Minimale CIEDE2000-Distanz zu natürlichen Hauttönen, bevor ein Farbstich markiert wird |

## Immich Sync

Einweg-Synchronisierung von Facet-Sternebewertungen und -Favoriten zu einem [Immich](https://immich.app/)-Server über dessen REST-API. Assets werden anhand von `originalPath` über `path_map` zugeordnet. Führen Sie `--immich-sync` aus (prüfen Sie zuerst mit `--immich-test`); siehe [Befehle — Immich-Synchronisierung](COMMANDS.md#immich-synchronisierung).

```json
{
  "immich": {
    "url": "",
    "api_key": "",
    "path_map": [
      { "facet_prefix": "", "immich_prefix": "" }
    ],
    "push": {
      "ratings": true,
      "favorites": true,
      "rejected": false,
      "top_picks_album": "",
      "top_picks_min_rating": 4
    },
    "webhook": {
      "token_env": "",
      "header": "x-facet-token",
      "max_pending": 500
    },
    "timeout_seconds": 30
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `url` | `""` | Basis-URL des Immich-Servers (z. B. `http://nas:2283`) |
| `api_key` | `""` | Immich-API-Schlüssel, gesendet als `x-api-key`-Header |
| `owner_id` | `""` | Optionale exakte Eigentümer-ID; Assets ohne sie oder im Besitz eines anderen werden übersprungen |
| `library_id` | `""` | Optionale exakte Bibliotheks-ID; leer = kein Bibliotheksfilter |
| `path_map` | `[{facet_prefix, immich_prefix}]` | Präfix-Umschreibungen von Facet-Pfaden zu Immich-`originalPath`; das erste passende `facet_prefix` gewinnt |
| `push.ratings` | `true` | Sternebewertungen übertragen (nur 1–5 wird geschrieben, nie 0/−1) |
| `push.favorites` | `true` | Das Favoriten-Flag übertragen |
| `push.rejected` | `false` | `rating: -1` für in Facet abgelehnte Fotos übertragen. Erfordert `push.ratings` |
| `push.top_picks_album` | `""` | Optionaler Immich-Albumname, der übertragene Fotos oberhalb des Bewertungsschwellenwerts sammelt. Leer = kein Album |
| `push.top_picks_min_rating` | `4` | Minimale Sternebewertung, damit ein Foto zu `top_picks_album` hinzugefügt wird |
| `webhook.token_env` | `""` | Umgebungsvariable, die das gemeinsame Geheimnis des eingehenden Webhooks hält; leer oder nicht gesetzt deaktiviert den Webhook |
| `webhook.header` | `"x-facet-token"` | Header, in dem der Immich-Workflow das Token sendet |
| `webhook.max_pending` | `500` | Obergrenze für die vermerkte, aber unbewertete Pfadliste, die der nächste Sync meldet |
| `timeout_seconds` | `30` | REST-Timeout pro Anfrage |

`--immich-sync` unterstützt `--dry-run` (ordnet jedes Asset zu, schreibt aber nichts) und `--user` (überträgt die `user_preferences`-Bewertungen dieses Benutzers im Mehrbenutzermodus). Facet nutzt nur die REST-API und berührt nie die Immich-Datenbank.

## Timeline

Einstellungen für die chronologische Timeline-Ansicht:

```json
{
  "timeline": {
    "photos_per_group": 30
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `photos_per_group` | `30` | Pro Datumsgruppe geladene Fotos; höhere Werte zeigen mehr pro Datum, machen die Seiten aber schwerer |

## Map

Einstellungen für die interaktive Kartenansicht:

```json
{
  "map": {
    "cluster_zoom_threshold": 10
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `cluster_zoom_threshold` | `10` | Zoomstufe, ab der einzelne Marker die Cluster ersetzen; 1 (Welt) bis 18 (Straße) |

## Translation

Einstellungen für die KI-Übersetzung von Bildunterschriften über MarianMT:

```json
{
  "translation": {
    "target_language": "fr"
  }
}
```

| Einstellung | Standard | Beschreibung |
|---------|---------|-------------|
| `target_language` | `"fr"` | Zielsprache für `--translate-captions`: `fr`, `de`, `es`, `it`, `pt` (brasilianisches Portugiesisch) |

Die Übersetzung nutzt Helsinki-NLP-MarianMT-Modelle auf der CPU; eine GPU ist nicht nötig.

## Aesthetic CLIP (R2)

Ein zusätzlicher Ästhetik-Score, berechnet aus den zwischengespeicherten CLIP/SigLIP-Embeddings und Text-Prompts. Mit `scripts/benchmark_aesthetic.py` messen Sie die Auswirkung einer Prompt-Änderung auf AVA.

```json
{
  "aesthetic_clip": {
    "positive_prompts": [
      "a professional, high-quality photograph",
      "an aesthetically beautiful image",
      "a masterful, award-winning photograph",
      "a sharp, well-composed photograph",
      "a stunning, visually striking image"
    ],
    "negative_prompts": [
      "a low-quality, amateur photograph",
      "a blurry, poorly composed photograph",
      "an unattractive, mundane snapshot",
      "a noisy, badly lit photograph",
      "a boring, forgettable image"
    ]
  }
}
```

Leere Arrays verwenden die Standardwerte in `analyzers/aesthetic_clip.py`. Führen Sie den AVA-Benchmark erneut aus, bevor Sie sie ändern: Die Standardwerte erreichen SRCC ~0,52 auf `ava_test/`, und Änderungen lassen ihn leicht auf ~0,30 fallen.

## Adding alternative VLM tagger / critique models (R3)

Der `tagging_model` jedes Profils (z. B. `qwen3.5-2b`) nennt einen Modelleintrag im selben `models`-Abschnitt. Um ein anderes VLM auszuprobieren (Pixtral-12B, InternVL-2.5 usw.):

1. Fügen Sie einen Modelleintrag unter `models` hinzu:
   ```json
   "pixtral_12b": {
     "model_path": "mistralai/Pixtral-12B-2409",
     "torch_dtype": "bfloat16",
     "max_new_tokens": 100,
     "vlm_batch_size": 1
   }
   ```
2. Verweisen Sie ein Profil darauf:
   ```json
   "profiles": {
     "24gb": { "tagging_model": "pixtral_12b", ... }
   }
   ```
3. Führen Sie `python facet.py --recompute-tags-vlm` aus, um neu zu verschlagworten.

Keine Codeänderungen erforderlich. Prüfen Sie ~30 Fotos nebeneinander, bevor Sie es zum Standard machen.

## Server-Secret

Das Secret, das Session-Tokens und Fotorahmen-Links signiert, ist **kein** Schlüssel in dieser Datei. Es liegt in `.facet_secret` neben `scoring_config.json` (Modus `0600`, von git ignoriert) und wird beim ersten Start erzeugt.

- Überschreiben: die Umgebungsvariable `FACET_JWT_SECRET`.
- Rotation: `python database.py --rotate-secret`.

Ein `share_secret` aus einer älteren Installation wird beim nächsten Start in diese Datei verschoben und aus `scoring_config.json` entfernt. Siehe [Speicherung und Rotation des Secrets](DEPLOYMENT.md#speicherung-und-rotation-des-secrets).
