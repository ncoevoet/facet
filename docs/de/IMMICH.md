# Immich-Integration

> 🌐 [English](../IMMICH.md) · [Français](../fr/IMMICH.md) · **Deutsch** · [Italiano](../it/IMMICH.md) · [Español](../es/IMMICH.md) · [Português](../pt/IMMICH.md)

Facet und [Immich](https://immich.app/) erledigen unterschiedliche Aufgaben an denselben Fotos. Immich ist die Bibliothek: Es nimmt Fotos auf, sichert sie und liefert sie an Ihr Telefon aus. Facet ist das Urteil: Es bewertet, rankt und sortiert sie aus. Diese Seite verbindet die beiden, sodass die Urteile, zu denen Facet kommt, als Bewertungen und Favoriten in Immich erscheinen — und ein Upload nach Immich Facet mitteilt, dass neue Arbeit wartet.

Die Verbindung läuft in beide Richtungen ausschließlich über REST. Facet rührt nie an Immichs Datenbank, und Immich nie an der von Facet.

**Facet erfordert Immich ≥ 3.0.** Ältere Server lehnen die Bewertungssemantik ab, auf die Facet angewiesen ist: `null` zum Löschen einer Bewertung und `-1`, um eine als abgelehnt zu markieren. Auf einem 2.x-Server wird das Löschen verweigert, und veraltete Bewertungen bleiben für immer an Ihren Assets hängen.

---

## Inhaltsverzeichnis

- [Wie beide dieselbe Datei sehen](#wie-beide-dieselbe-datei-sehen)
- [Schritt 1 — die Bibliothek mit Immich teilen](#schritt-1--die-bibliothek-mit-immich-teilen)
- [Schritt 2 — einen API-Schlüssel erstellen](#schritt-2--einen-api-schlüssel-erstellen)
- [Schritt 3 — die Pfade zuordnen](#schritt-3--die-pfade-zuordnen)
- [Schritt 4 — testen, dann übertragen](#schritt-4--testen-dann-übertragen)
- [Ablehnungen übertragen](#ablehnungen-übertragen)
- [Der eingehende Webhook](#der-eingehende-webhook)
- [Konfigurationsreferenz](#konfigurationsreferenz)
- [Fehlerbehebung](#fehlerbehebung)

---

## Wie beide dieselbe Datei sehen

Alles hier beruht auf einer Idee: **dasselbe Foto auf der Festplatte, gesehen aus zwei Containern**.

Facet kennt ein Foto anhand seines absoluten Pfads auf der Maschine, die den Scan ausführt — `/mnt/photos/2026/07/IMG_1234.jpg`. Immich kennt dieselbe Datei anhand seines eigenen `originalPath`, also wie diese Datei *von innerhalb des Immich-Containers* aussieht — für hochgeladene Assets oft `/usr/src/app/upload/…`, oder der Einhängepunkt, den Sie einer externen Bibliothek gegeben haben.

Keine Seite kann die Sicht der anderen erraten, daher teilen Sie Facet die Präfix-Umschreibung einmal mit (`immich.path_map`), und jede Nachschlage-Operation in beide Richtungen läuft darüber. Machen Sie das richtig, und der Rest ist mechanisch; machen Sie es falsch, und alles meldet stillschweigend „unmatched" — siehe [Fehlerbehebung](#fehlerbehebung).

```
Facet path                              Immich originalPath
/mnt/photos/2026/07/IMG_1234.jpg   <->  /usr/src/app/external/2026/07/IMG_1234.jpg
└──── facet_prefix ────┘                └────── immich_prefix ──────┘
```

Die Zuordnung wird in beide Richtungen verwendet: ausgehend (`--immich-sync` übersetzt einen Facet-Pfad, um das Asset zu finden) und eingehend (der Webhook übersetzt Immichs `originalPath` zurück, um das Foto zu finden).

## Schritt 1 — die Bibliothek mit Immich teilen

Die sauberste Anordnung ist eine **externe Bibliothek**: Immich liest die Fotos dort, wo sie bereits liegen, statt eine zweite Kopie zu besitzen. Facet scannt dasselbe Verzeichnis von seiner eigenen Seite aus.

1. Gehen Sie in Immich zu **Administration → External Libraries → Create Library**, wählen Sie den Besitzer aus und fügen Sie einen Importpfad hinzu, der auf das Verzeichnis zeigt, wie es der Immich-Container sieht.
2. Stellen Sie sicher, dass dieses Verzeichnis schreibgeschützt in den Immich-Container eingehängt (Bind-Mount) ist. In `docker-compose.yml`:

   ```yaml
   services:
     immich-server:
       volumes:
         - /mnt/photos:/usr/src/app/external:ro
   ```

3. Scannen Sie die Bibliothek über Immichs Oberfläche (**Scan All Libraries**) und scannen Sie dasselbe Verzeichnis mit Facet:

   ```bash
   python facet.py /mnt/photos
   ```

   Beide Werkzeuge halten nun eine Zeile pro Datei. Nichts wird auf der Festplatte dupliziert.

Wenn Sie stattdessen normal in Immich hochladen (mobiles Auto-Backup, der Web-Uploader) und Facet auf Immichs eigenes Upload-Verzeichnis richten, funktioniert die Integration genauso — nur die Präfixe unterscheiden sich. In diesem Fall besitzt Immich das Datei-Layout, führen Sie den Facet-Scan also nach Uploads erneut aus (oder verwenden Sie `--watch`).

## Schritt 2 — einen API-Schlüssel erstellen

In Immich: **Klicken Sie auf Ihren Avatar → Account Settings → API Keys → New API Key**.

Immich ≥ 3.0 erlaubt es, einen Schlüssel einzugrenzen, statt ihm alles zu gewähren. Facet benötigt genau sechs Scopes:

| Scope | Wofür Facet ihn verwendet |
|-------|-------------------------|
| `server.about` | Konnektivitäts-/Auth-Prüfung durch `--immich-test` |
| `asset.read` | Assets anhand von `originalPath` auflösen |
| `asset.update` | `rating` und `isFavorite` schreiben |
| `album.read` | Ein bestehendes Top-Picks-Album anhand des Namens finden |
| `album.create` | Das Top-Picks-Album beim ersten Mal erstellen |
| `albumAsset.create` | Fotos zum Top-Picks-Album hinzufügen |

Lassen Sie die letzten drei weg, wenn Sie `push.top_picks_album` leer lassen — Facet rührt Alben nur an, wenn dieser Name gesetzt ist.

Der Schlüssel wird als `x-api-key`-Header bei jeder Anfrage gesendet. Tragen Sie ihn in `scoring_config.json` ein:

```json
"immich": {
  "url": "http://immich.local:2283",
  "api_key": "paste-the-key-here"
}
```

> **Ein Hinweis zu `PUT /api/assets`.** Facet schreibt Bewertungen mit `PUT /api/assets`, was Immichs OpenAPI-Dokument als *deprecated* markiert. Die Ersatz-`PATCH`-Aliase sind angekündigt, aber **in der veröffentlichten Spezifikation nicht vorhanden**, daher gibt es noch nichts, wohin migriert werden könnte — `PUT` bleibt der einzige Endpunkt, der tatsächlich existiert, und Facet verwendet ihn weiterhin. Jeder Immich-Pfad, den Facet berührt, lebt in `ImmichClient` (`sync/immich.py`), sodass die Änderung an dem Tag, an dem die `PATCH`-Routen ausgeliefert werden, nur eine Klasse betrifft.

## Schritt 3 — die Pfade zuordnen

Fügen Sie ein Paar pro geteilter Wurzel hinzu. Das erste Paar, dessen `facet_prefix` auf ein Foto passt, gewinnt:

```json
"immich": {
  "path_map": [
    { "facet_prefix": "/mnt/photos/", "immich_prefix": "/usr/src/app/external/" }
  ]
}
```

Zwei Wurzeln, zwei Paare:

```json
"path_map": [
  { "facet_prefix": "/mnt/photos/",  "immich_prefix": "/usr/src/app/external/" },
  { "facet_prefix": "/mnt/archive/", "immich_prefix": "/usr/src/app/archive/" }
]
```

Lassen Sie den mitgelieferten Platzhalter (`{"facet_prefix": "", "immich_prefix": ""}`) unangetastet, und Pfade werden unverändert durchgereicht — korrekt nur, wenn Facet und Immich wirklich identische absolute Pfade sehen, was der Fall ist, wenn Sie Facet innerhalb des Namespaces des Immich-Containers ausführen, und fast nie sonst.

Um den echten Wert abzulesen, öffnen Sie ein beliebiges Foto in Immich, drücken Sie `i` für das Info-Panel und vergleichen Sie den dort angezeigten Dateipfad mit dem Pfad, den Facet für dasselbe Foto meldet.

## Schritt 4 — testen, dann übertragen

```bash
# Nur Konnektivität + Authentifizierung. Keine Schreibvorgänge.
python facet.py --immich-test

# Jedes Asset auflösen und melden, was sich ändern WÜRDE. Immer noch keine Schreibvorgänge.
python facet.py --immich-sync --dry-run

# Im Ernst.
python facet.py --immich-sync
```

Die Synchronisierung meldet `matched` / `unmatched` / `updated` / `skipped (unrated)` / erstellte Alben. Ein erster Lauf mit einer hohen `unmatched`-Zahl bedeutet fast immer, dass die Pfadzuordnung falsch ist — siehe [Fehlerbehebung](#fehlerbehebung).

Was übertragen wird:

- **Sternebewertungen 1–5** → Immichs `rating`. Ein Foto, das Sie nie bewertet haben, überträgt nichts.
- **Favoriten** → Immichs `isFavorite`.
- **Löschungen.** Wenn Sie ein Foto mit 5 bewertet, synchronisiert und dann auf unbewertet zurückgesetzt haben, sendet die nächste Synchronisierung `rating: null`, damit Immich es ebenfalls vergisst. Facet merkt sich, was es zuletzt übertragen hat (in der Nebentabelle `stats_cache`), genau damit dieser Übergang nicht verloren geht. Es ist `null` und niemals `0` — Immich v3 lehnt `0` rundweg ab, und ein abgelehnter Batch bricht die gesamte Synchronisierung ab.
- **Ein optionales Top-Picks-Album**, befüllt aus `push.top_picks_min_rating`, wenn `push.top_picks_album` einen Namen nennt.

Im Mehrbenutzermodus überträgt `--immich-sync --user alice` Alices `user_preferences`-Bewertungen statt der globalen Spalten und verfolgt seinen Zustand unter ihrem eigenen Scope.

## Ablehnungen übertragen

Standardmäßig deaktiviert. Aktivieren Sie es, und ein Foto, das Sie in Facets Culling-Dunkelkammer abgelehnt haben, erhält Immichs eigenen Ablehnungsmarker:

```json
"immich": {
  "push": {
    "ratings": true,
    "favorites": true,
    "rejected": true
  }
}
```

Mit aktiviertem `push.rejected`:

- Ein abgelehntes Foto überträgt `rating: -1`, Immich v3s Wert für „abgelehnt".
- **Ablehnung schlägt Sterne.** Ein abgelehntes 5-Sterne-Foto überträgt `-1`, nicht `5` — Sie haben es weggeworfen, und das ist die Tatsache, die es wert ist, gespiegelt zu werden.
- **Das Aufheben der Ablehnung löscht sie.** Ein Foto, das `-1` übertragen hat und später wieder freigegeben wird, überträgt stattdessen seine aktuelle Sternebewertung, oder `rating: null`, wenn es keine hat. Derselbe Mechanismus für nachverfolgten Zustand wie bei jeder anderen Löschung.
- Ein abgelehntes Foto tritt nie dem Top-Picks-Album bei.
- `push.ratings: false` unterdrückt es. `-1` ist ein Bewertungs-Schreibvorgang, daher schmuggelt sich bei einer Konfiguration, die Bewertungsübertragungen deaktiviert hat, keiner zurück.

Lassen Sie es deaktiviert, wenn andere Personen (oder Ihr Telefon) die Immich-Bibliothek betrachten: Ein `-1` ist dort sichtbar, und „in Facet abgelehnt" ist ein Arbeitsurteil, das Sie vielleicht nicht öffentlich machen möchten.

## Der eingehende Webhook

Alles oben ist Facet → Immich. Der Webhook ist die andere Richtung: Immich teilt Facet mit, dass sich gerade ein Asset geändert hat, und Facet antwortet sofort mit dem, was es darüber weiß.

**Er ist standardmäßig deaktiviert und startet niemals einen Scan.** Ein Webhook ist ein nicht über eine Sitzung authentifizierter Aufruf von einem anderen Daemon; würde man einen davon GPU-Arbeit auslösen lassen, hätte jeder Token-Inhaber eine Möglichkeit, Ihre Maschine lahmzulegen. Was stattdessen passiert:

- **Foto bekannt und bewertet** → Seine Bewertung/Favorit wird sofort, in Echtzeit, als Einzel-Asset-Update zurück an Immich übertragen. Das schließt den Kreis nach einem Scan: Ein Foto bewerten, es hochladen, und die Bewertung landet in Immich, ohne auf die nächste `--immich-sync` zu warten.
- **Foto unbekannt oder noch nicht bewertet** → Der Pfad wird in einer begrenzten, deduplizierten Warteliste vermerkt, und die nächste `--immich-sync` protokolliert ihn. Es wird nichts gescannt.

### Aktivieren

Der Token ist ein gemeinsames Geheimnis und lebt daher in der Umgebung, niemals in `scoring_config.json` (diese Datei wird von mehreren Endpunkten an Ort und Stelle neu geschrieben und ist auf den meisten Installationen für jeden lesbar). Die Konfiguration benennt die *Variable*; die Variable hält den *Wert*.

1. Erzeugen Sie ein Token und exportieren Sie es dort, wo der Viewer startet — Ihre systemd-Unit, `docker-compose.yml` oder Shell-Profil:

   ```bash
   export FACET_IMMICH_WEBHOOK_TOKEN="$(openssl rand -hex 32)"
   ```

2. Benennen Sie diese Variable in `scoring_config.json`:

   ```json
   "immich": {
     "webhook": {
       "token_env": "FACET_IMMICH_WEBHOOK_TOKEN",
       "header": "x-facet-token",
       "max_pending": 500
     }
   }
   ```

3. Starten Sie den Viewer neu (`python viewer.py`).

Ein leeres `token_env`, oder eine Variable, die nicht gesetzt oder leer ist, deaktiviert den Endpunkt vollständig — er liefert **404**, genau wie `frame.tokens` und `upload.username`. Es gibt keinen halboffenen Zustand.

### Immich darauf richten

In Immich ≥ 3.0: **Administration → Workflows → Create Workflow**.

1. **Trigger** — wählen Sie das Asset-Ereignis, das gespiegelt werden soll. `Asset uploaded` ist das nützliche; fügen Sie `Asset updated` hinzu, wenn auch Bearbeitungen erneut auslösen sollen.
2. **Action** — wählen Sie **Webhook**.
3. **URL** — `http://facet.local:5000/api/immich/webhook`, mit einer Adresse, die der Immich-Container tatsächlich erreichen kann. Wenn beide auf einem Host in Docker laufen, ist das der Dienstname (`http://facet:5000/…`), nicht `localhost`.
4. **Header** — Name `x-facet-token`, Wert das erzeugte Token. Der Name muss zu `webhook.header` passen; benennen Sie beide gemeinsam um, wenn Ihr Setup einen anderen benötigt. `Authorization: Bearer <token>` wird ebenfalls akzeptiert, für Proxys, die nur das anbieten.
5. Speichern, dann ein Foto hochladen, um es zu bestätigen.

### Was der Endpunkt antwortet

| Status | Bedeutung |
|--------|---------|
| `202` | Body verstanden. Die JSON-Zusammenfassung meldet `received` / `pushed` / `skipped` / `pending` / `unmatched` / `failed`. |
| `204` | Gültiges JSON, aber kein Asset, das Facet erkannt hat. Protokolliert, kein Fehler — die Payload-Form gehört Immich, das sie ändern kann. |
| `400` | Der Body war überhaupt kein JSON. |
| `401` | Kein Token in der Anfrage. |
| `403` | Falsches Token. |
| `404` | Das Feature ist deaktiviert (kein Token konfiguriert). |

Facet liest `originalPath` aus der Payload heraus und ist bewusst großzügig darin, wo es sitzt — ein blankes Asset-Objekt, `{"asset": {…}}`, eine Liste, oder jedes davon verschachtelt unter `data` / `items` / `assets` funktioniert. Wenn die Payload die Asset-`id` trägt, verwendet Facet sie und überspringt einen Nachschlage-Umweg.

Ausstehende Pfade werden von der nächsten Synchronisierung gemeldet:

```
WARNING  Immich webhook saw an asset Facet has not scored: /mnt/photos/2026/08/IMG_9999.jpg
```

Scannen Sie diese Fotos (`python facet.py /mnt/photos`), und sie fallen bei der nächsten Synchronisierung aus der Liste. Die Liste ist auf `max_pending`-Einträge begrenzt, älteste zuerst verworfen, sodass ein geschwätziges Immich sie nie unbegrenzt wachsen lassen kann.

### Sicherheitshinweise

- Das Token wird konstantzeitlich verglichen. Ein falsches Token ergibt ein glattes `403` ohne Timing-Signal.
- Betreiben Sie den Viewer über HTTPS, wenn Immich ihn über etwas weniger Vertrauenswürdiges als ein privates Bridge-Netzwerk erreicht — das Token reist bei jeder Zustellung in einem Header mit.
- Rotieren Sie, indem Sie die Umgebungsvariable und den Immich-Workflow-Header gemeinsam ändern und dann den Viewer neu starten.
- Der Webhook liest die globalen Bewertungsspalten, sodass er im Mehrbenutzermodus die gemeinsame/globale Bewertung spiegelt, nicht das Overlay eines einzelnen Benutzers. Wenn Sie benutzerspezifische Bewertungen in Immich wünschen, lassen Sie den Webhook deaktiviert und verwenden Sie `--immich-sync --user <name>` nach Zeitplan.

## Konfigurationsreferenz

Der vollständige `immich`-Block, mit den mitgelieferten Standardwerten:

```json
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
```

| Einstellung | Standard | Beschreibung |
|-----|---------|---------|
| `url` | `""` | Immich-Basis-URL, `http` oder `https`. Ein abschließender Schrägstrich wird entfernt. |
| `api_key` | `""` | API-Schlüssel, gesendet als `x-api-key`. Leer bricht jede Synchronisierung mit einer klaren Fehlermeldung ab. |
| `path_map` | ein leeres Paar | Präfix-Umschreibungen zwischen Facet-Pfaden und Immich-`originalPath`-Werten. Der erste Treffer gewinnt; verwendet in beide Richtungen. |
| `push.ratings` | `true` | Sternebewertungen 1–5 übertragen (und ihre Löschungen). |
| `push.favorites` | `true` | `isFavorite` übertragen (und dessen Löschungen). |
| `push.rejected` | `false` | `rating: -1` für in Facet abgelehnte Fotos übertragen. Erfordert `push.ratings`. |
| `push.top_picks_album` | `""` | Zu befüllender Albumname. Leer bedeutet, dass Facet Alben nie anrührt. |
| `push.top_picks_min_rating` | `4` | Minimale Sternebewertung für dieses Album. |
| `webhook.token_env` | `""` | Name der Umgebungsvariable, die das Webhook-Geheimnis hält. Leer ⇒ der Endpunkt liefert 404. |
| `webhook.header` | `"x-facet-token"` | Header, in dem Immich das Token sendet. |
| `webhook.max_pending` | `500` | Obergrenze für die vermerkte, aber unbewertete Pfadliste. |
| `timeout_seconds` | `30` | HTTP-Timeout pro Anfrage. |

## Fehlerbehebung

### Alles kommt als `unmatched` zurück

Die Pfadzuordnung ist falsch — das ist mit weitem Abstand die häufigste Ursache.

1. Öffnen Sie ein Foto in Immich und drücken Sie `i`. Notieren Sie sich den Pfad im Info-Panel.
2. Finden Sie den Pfad desselben Fotos in Facet (das Galerie-Detailpanel, oder `sqlite3 photos.db "SELECT path FROM photos LIMIT 5"`).
3. Die beiden teilen sich ein *Suffix*. Was sich unterscheidet, ist das Präfix, und diese beiden Präfixe sind genau `facet_prefix` und `immich_prefix`.

Häufige Fallstricke:

- **Ein fehlender abschließender Schrägstrich.** `"/mnt/photos"` → `"/usr/src/app/external"` schreibt auch `/mnt/photosXYZ/a.jpg` um. Beenden Sie beide Präfixe immer mit `/`.
- **Host-Pfad vs. Container-Pfad.** Der Immich-Pfad ist das, was der *Container* sieht. `docker compose exec immich-server ls /usr/src/app/external` klärt das.
- **Symlinks und Bind-Mounts.** Immich speichert den Pfad, den es durchlaufen hat. Wenn Ihre Bibliothek auf einer Seite über einen Symlink erreicht wird, unterscheiden sich die Zeichenketten, obwohl die Datei dieselbe ist.
- **Groß-/Kleinschreibung und Unicode.** Der Vergleich ist exakt. Eine Bibliothek auf einer Freigabe ohne Beachtung der Groß-/Kleinschreibung kann sowohl `/Photos/` als auch `/photos/` enthalten; nur die gespeicherte Schreibweise passt.
- **Immich hat die Datei noch nicht indiziert.** Führen Sie **Scan All Libraries** aus und prüfen Sie, dass das Asset in Immich tatsächlich existiert, bevor Sie die Zuordnung verdächtigen.

`--immich-sync --dry-run` nennt die ersten 20 nicht zugeordneten Pfade im Protokoll; diese Liste identifiziert das falsche Präfix meist auf den ersten Blick.

### `--immich-test` schlägt fehl

- `Unsupported Immich URL scheme` — `url` benötigt `http://` oder `https://`.
- `HTTP 401` — der API-Schlüssel ist falsch oder wurde widerrufen.
- `HTTP 403` — der Schlüssel ist gültig, hat aber nicht `server.about`. Erstellen Sie ihn mit den sechs Scopes oben neu.
- Verbindung verweigert / Timeout — der Port ist falsch, oder Facet kann den Container nicht erreichen. Testen Sie mit `curl -H "x-api-key: …" http://immich.local:2283/api/server/about` von der Maschine aus, die Facet ausführt.

### Der Webhook liefert 404

Das Feature ist deaktiviert. Entweder ist `webhook.token_env` leer, oder die benannte Variable ist *in der eigenen Umgebung des Viewers* nicht gesetzt oder leer. Sie in Ihrer interaktiven Shell zu exportieren bewirkt nichts für einen von systemd oder Docker verwalteten Viewer — setzen Sie sie in der Unit-Datei oder Compose-Datei und starten Sie neu.

### Der Webhook liefert 401 oder 403

`401` bedeutet, dass kein Token ankam: Der Header-Name, den Immich sendet, passt nicht zu `webhook.header`. `403` bedeutet, dass ein Token ankam und falsch war — vergleichen Sie den Header-Wert des Workflows Zeichen für Zeichen mit der Umgebungsvariable.

### Bewertungen werden übertragen, aber die Löschungen nicht

Facet sendet eine Löschung nur für ein Foto, das es tatsächlich zuvor übertragen hat; dieses Gedächtnis lebt in `stats_cache` in der Facet-Datenbank. Das Wiederherstellen einer älteren Datenbank (oder der Lauf gegen eine neue) verliert es, und eine während der Lücke gelöschte Bewertung wird in Immich nicht zurückgesetzt. Bewerten und löschen Sie das Foto erneut, oder korrigieren Sie es direkt in Immich.

### Bewertungen erscheinen bei den falschen Fotos

Zwei Dateien mit demselben `originalPath` können innerhalb von Immich nicht vorkommen, aber zwei *Facet*-Wurzeln, die auf ein Immich-Präfix abgebildet werden, können kollidieren. Prüfen Sie, dass sich Ihre `path_map`-Paare nicht überlappen: Das erste passende Paar gewinnt, sodass ein breites Paar, das vor einem engeren aufgeführt ist, dieses verschluckt.

### `rating: 0 is not valid`

Der Immich-Server ist älter als 3.0. Führen Sie ein Upgrade durch — Facets Löschsemantik benötigt `null`, und `push.rejected` benötigt `-1`; es gibt keinen Fallback, der auf 2.x funktioniert.

---

**Siehe auch:** [Befehle — Immich-Synchronisierung](COMMANDS.md#immich-synchronisierung) · [Konfiguration](CONFIGURATION.md) · [Editor-Interop-Rezepte](INTEROP.md) für XMP-Roundtripping mit Lightroom, darktable und digiKam.
