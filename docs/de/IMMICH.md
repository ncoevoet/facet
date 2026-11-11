# Immich-Integration

> 🌐 [English](../IMMICH.md) · [Français](../fr/IMMICH.md) · **Deutsch** · [Italiano](../it/IMMICH.md) · [Español](../es/IMMICH.md) · [Português](../pt/IMMICH.md) · [简体中文](../zh/IMMICH.md)

[Immich](https://immich.app/) speichert, sichert und liefert Ihre Fotos aus. Facet bewertet, rankt und sortiert sie aus. Diese Seite verbindet die beiden:

- Facets Bewertungen und Favoriten erscheinen in Immich.
- Ein Upload nach Immich teilt Facet mit, dass neue Arbeit wartet.

Beide Richtungen verwenden ausschließlich Immichs REST-API. Keines der Werkzeuge rührt die Datenbank des anderen an.

**Facet erfordert Immich ≥ 3.0.** Facet löscht eine Bewertung mit `null` und markiert eine Ablehnung mit `-1`. Ein 2.x-Server verweigert das Löschen, sodass veraltete Bewertungen an Ihren Assets hängen bleiben.

---

## Inhaltsverzeichnis

- [Wie beide dieselbe Datei sehen](#wie-beide-dieselbe-datei-sehen)
- [Schritt 1 — die Bibliothek mit Immich teilen](#schritt-1--die-bibliothek-mit-immich-teilen)
- [Schritt 2 — einen API-Schlüssel erstellen](#schritt-2--einen-api-schlüssel-erstellen)
- [Schritt 3 — die Pfade zuordnen](#schritt-3--die-pfade-zuordnen)
- [Schritt 4 — testen, dann übertragen](#schritt-4--testen-dann-übertragen)
- [Ablehnungen übertragen](#ablehnungen-übertragen)
- [Manuelle Stapel importieren und übertragen](#manuelle-stapel-importieren-und-übertragen)
- [Der eingehende Webhook](#der-eingehende-webhook)
- [Diagnose im Viewer](#diagnose-im-viewer)
- [Konfigurationsreferenz](#konfigurationsreferenz)
- [Fehlerbehebung](#fehlerbehebung)

---

## Wie beide dieselbe Datei sehen

Facet und Immich sehen dieselbe Datei auf der Festplatte unter unterschiedlichen Pfaden:

- **Facet** verwendet den absoluten Pfad auf der Maschine, die den Scan ausführt, z. B. `/mnt/photos/2026/07/IMG_1234.jpg`.
- **Immich** verwendet seinen `originalPath`: den Pfad, wie er *von innerhalb des Immich-Containers* aussieht. Das ist bei Uploads oft `/usr/src/app/upload/…` oder der Einhängepunkt einer externen Bibliothek.

Die Präfix-Umschreibung teilen Sie Facet einmal in `immich.path_map` mit. Jede Nachschlage-Operation läuft darüber. Ist sie falsch, meldet alles „unmatched“ — siehe [Fehlerbehebung](#fehlerbehebung).

```
Facet path                              Immich originalPath
/mnt/photos/2026/07/IMG_1234.jpg   <->  /usr/src/app/external/2026/07/IMG_1234.jpg
└──── facet_prefix ────┘                └────── immich_prefix ──────┘
```

Die Zuordnung funktioniert in beide Richtungen. `--immich-sync` findet damit das Immich-Asset zu einem Facet-Pfad. Der Webhook findet damit das Facet-Foto zu einem Immich-`originalPath`.

## Schritt 1 — die Bibliothek mit Immich teilen

Die einfachste Anordnung ist eine **externe Bibliothek** in Immich: Immich liest die Fotos dort, wo sie bereits liegen, und Facet scannt dasselbe Verzeichnis.

1. Gehen Sie in Immich zu **Administration → External Libraries → Create Library**, wählen Sie den Besitzer aus und fügen Sie einen Importpfad für das Verzeichnis hinzu, wie es der Immich-Container sieht.
2. Hängen Sie dieses Verzeichnis schreibgeschützt per Bind-Mount in den Immich-Container ein. In `docker-compose.yml`:

   ```yaml
   services:
     immich-server:
       volumes:
         - /mnt/photos:/usr/src/app/external:ro
   ```

3. Scannen Sie die Bibliothek in Immich (**Scan All Libraries**) und scannen Sie dasselbe Verzeichnis mit Facet:

   ```bash
   python facet.py /mnt/photos
   ```

Es wird keine Datei auf der Festplatte dupliziert.

Sie können auch wie gewohnt nach Immich hochladen (mobiles Backup, Web-Uploader) und Facet auf Immichs Upload-Verzeichnis richten. Nur die Präfixe ändern sich. Führen Sie den Facet-Scan nach Uploads erneut aus oder verwenden Sie `--watch`.

## Schritt 2 — einen API-Schlüssel erstellen

In Immich: **Klicken Sie auf Ihren Avatar → Account Settings → API Keys → New API Key**.

Immich ≥ 3.0 erlaubt es, einen Schlüssel auf einzelne Scopes zu beschränken. Bewertungs- und Favoritensynchronisierung benötigen diese (manuelle Stapel brauchen mehr, siehe unten):

| Scope | Wofür Facet ihn verwendet |
|-------|-------------------------|
| `server.about` | Konnektivitäts-/Auth-Prüfung durch `--immich-test` |
| `asset.read` | Assets anhand von `originalPath` auflösen |
| `asset.update` | `rating` und `isFavorite` schreiben |
| `album.read` | Das Top-Picks-Album anhand des Namens finden und seine Mitglieder lesen |
| `album.create` | Das Top-Picks-Album beim ersten Mal erstellen |
| `albumAsset.create` | Fotos zum Top-Picks-Album hinzufügen |
| `albumAsset.delete` | Fotos entfernen, die unter die Top-Picks-Schwelle gefallen sind |

Die vier Album-Scopes können Sie weglassen, wenn `push.top_picks_album` leer ist. Facet rührt Alben nur an, wenn dieser Name gesetzt ist.

Facet sendet den Schlüssel im Header `x-api-key`. Tragen Sie ihn in `scoring_config.json` ein:

```json
"immich": {
  "url": "http://immich.local:2283",
  "api_key": "paste-the-key-here"
}
```

> **Hinweis:** Facet schreibt Bewertungen mit `PUT /api/assets`. Immich markiert ihn als veraltet (*deprecated*), aber sein Ersatz ist noch nicht veröffentlicht, daher verwendet Facet ihn weiterhin.

## Schritt 3 — die Pfade zuordnen

Fügen Sie ein Paar pro geteilter Wurzel hinzu. Regeln:

- Das erste passende Präfix gewinnt. Es ist ein reiner Zeichenkettenvergleich, kein Verzeichnisvergleich.
- Beenden Sie Verzeichnis-Präfixe mit `/`.
- Setzen Sie engere Zuordnungen vor breitere.

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

Der mitgelieferte Platzhalter (`{"facet_prefix": "", "immich_prefix": ""}`) reicht Pfade unverändert durch. Das funktioniert nur, wenn Facet und Immich identische absolute Pfade sehen, was selten der Fall ist, außer Facet läuft im Immich-Container.

Um den echten Wert zu finden, öffnen Sie ein Foto in Immich und drücken Sie `i` für das Info-Panel. Vergleichen Sie den dortigen Dateipfad mit dem Pfad, den Facet für dasselbe Foto zeigt.

## Schritt 4 — testen, dann übertragen

```bash
# Connectivity + authentication only. No writes.
python facet.py --immich-test

# Resolve every asset and report what WOULD change. Still no writes.
python facet.py --immich-sync --dry-run

# For real.
python facet.py --immich-sync
```

Die Synchronisierung meldet `matched` / `unmatched` / `updated` / `skipped (unrated)` / `identity_conflicts` / erstellte Alben. Im Probelauf zählt `updated` die Assets, die sich ändern würden, und es wird nichts geschrieben. Eine hohe `unmatched`-Zahl im ersten Lauf bedeutet fast immer, dass die Pfadzuordnung falsch ist — siehe [Fehlerbehebung](#fehlerbehebung).

Was übertragen wird:

- **Sternebewertungen 1–5** → Immichs `rating`. Ein unbewertetes Foto überträgt nichts.
- **Favoriten** → Immichs `isFavorite`.
- **Löschungen.** Wenn Sie ein Foto bewertet, synchronisiert und dann auf unbewertet zurückgesetzt haben, sendet die nächste Synchronisierung `rating: null`, damit Immich es ebenfalls löscht. Facet merkt sich dafür, was es zuletzt übertragen hat (in `stats_cache`). Es sendet `null`, nie `0`: Immich v3 lehnt `0` ab, und ein abgelehnter Batch bricht die gesamte Synchronisierung ab.
- **Ein Top-Picks-Album** (optional), wenn `push.top_picks_album` gesetzt ist: Fotos ab `push.top_picks_min_rating` sind Mitglieder, und ein Mitglied unter der Schwelle wird bei einer globalen Synchronisation wieder entfernt, solange Facet es zuordnen kann (ein gelöschtes Foto oder der Asset einer anderen App bleibt unangetastet); ein bestehendes Mitglied wird nie neu hinzugefügt.

Im Mehrbenutzermodus überträgt `--immich-sync --user alice` Alices eigene Bewertungen (`user_preferences`) statt der globalen und verfolgt ihren Synchronisierungszustand getrennt.

## Ablehnungen übertragen

Standardmäßig deaktiviert. Aktiviert, erhält ein Foto, das Sie in Facets Culling-Ansicht ablehnen, Immichs Ablehnungsmarker:

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

- Ein abgelehntes Foto überträgt `rating: -1`, Immich v3s Wert für „abgelehnt“.
- **Ablehnung schlägt Sterne.** Ein abgelehntes 5-Sterne-Foto überträgt `-1`, nicht `5`.
- **Das Aufheben der Ablehnung löscht sie.** Das Foto überträgt dann seine aktuelle Sternebewertung oder `rating: null`, wenn es keine hat.
- Ein abgelehntes Foto tritt nie dem Top-Picks-Album bei.
- `push.ratings: false` schaltet dies ebenfalls ab, da `-1` eine Bewertung ist.

Lassen Sie es deaktiviert, wenn andere Personen (oder Ihr Telefon) die Immich-Bibliothek betrachten: Sie sehen das `-1`.

## Manuelle Stapel importieren und übertragen

Manuelle Stapel haben einen eigenen **lokalen CLI-Ablauf aus Plan und Anwenden**, mit den üblichen Optionen `--config`, `--db` und `--user`. Die Bewertungs- und Favoritensynchronisierung bleibt unberührt.

Voraussetzungen:

- Immich **≥ 3.0** (Facet prüft die Stapel-Unterstützung außerdem zur Laufzeit).
- Schlüsselrechte: `user.read` und `stack.read` zusätzlich zu `asset.read`; zum Übertragen auch `stack.create` und `asset.update`. `stack.update` und `stack.delete` werden nicht benötigt.
- Mehrbenutzerinstallationen müssen einen bestehenden Benutzer angeben.
- Der Immich-Schlüssel wird von Stapel-Operationen aus dem Web-Viewer, von Assistenten (MCP) oder vom Upload-Webhook nie verwendet.

Ablauf:

1. Vorschau. Sie ist auf beiden Seiten schreibgeschützt und migriert die Datenbank nicht.
2. Prüfen Sie den Plan und seinen SHA-256-Digest.
3. Wenden Sie ausdrücklich an.

Optionen und Grenzen:

- `--stack-id UUID` (wiederholbar) begrenzt den Lauf auf diese Quellstapel.
- `--stack-plan-out` schreibt eine neue private JSON-Datei (POSIX-Modus `0600`) und überschreibt nie.
- Ein Plan enthält höchstens **1000 Gruppen, 1000 Mitglieder je Gruppe, 20000 Mitglieder insgesamt und 16 MiB**. Grenzen Sie ihn mit `--stack-id` ein.
- Wählen Sie unter Windows einen Ausgabeordner, dessen ACL den Zugriff auf Ihr Konto beschränkt; POSIX-Modusbits schützen die Datei dort nicht.

Zuordnungsregeln:

- Jedes Mitglied muss genau einem indexierten, sichtbaren, verfügbaren Foto zugeordnet sein, dessen Eigentümer das entfernte Konto ist. Ein fehlendes oder mehrdeutiges Mitglied überspringt die ganze Gruppe.
- Das Übertragen erstellt nur dann einen Stapel, wenn die entfernten Assets noch nicht gestapelt sind.
- Eine exakte Übereinstimmung von Mitgliedern und Titelbild verknüpft beim Anwenden die beiden Stapel.
- Teilüberschneidungen, andere Titelbilder, geänderte Mitglieder und Fälle, in denen nur eine Seite aufgelöst ist, werden als Konflikte übersprungen. Bestehende Stapel werden nie aktualisiert.
- Nur das Titelbild wird übertragen; die Reihenfolge der übrigen Mitglieder nicht.
- Es gibt keine automatische bidirektionale Synchronisierung, Abfrage oder Weitergabe des Auflösens.

Pläne, Verknüpfungen und Belege gelten nur für Server, entferntes Konto, lokalen Eigentümer und Pfadzuordnung. Ändert sich eines davon, gilt der alte Plan nicht mehr. Belege speichern Ergebnisse und entfernte Asset-IDs, nie Zugangsdaten.

Anwenden prüft jede Gruppe vor dem Schreiben neu und liest sie danach zurück. Geht eine Erstellungsantwort verloren, gleicht Facet sie vor jedem erneuten Versuch ab, statt sie nochmals zu senden. Abbrechen stoppt zwischen Gruppen; ein späteres Anwenden setzt anhand der Belege fort.

> **Warnung:** Immich kann einen Stapel nicht bedingt erstellen. Ein anderer Client kann die Assets zwischen Facets letzter Prüfung und dem Schreiben ändern, und Facet kann das nicht zurückrollen.

## Der eingehende Webhook

Der Webhook arbeitet in die andere Richtung: Immich teilt Facet mit, dass sich ein Asset geändert hat, und Facet antwortet mit dem, was es weiß.

**Er ist standardmäßig deaktiviert und startet niemals einen Scan.** Stattdessen:

- **Foto bekannt und bewertet** → Facet überträgt seine Bewertung und seinen Favoriten sofort zurück an Immich. Ein Foto bewerten, es hochladen, und die Bewertung landet in Immich, ohne auf `--immich-sync` zu warten.
- **Foto unbekannt oder noch nicht bewertet** → Facet fügt den Pfad einer begrenzten Warteliste hinzu, und die nächste `--immich-sync` protokolliert ihn.

### Aktivieren

Das Token ist ein Geheimnis und lebt daher in einer Umgebungsvariable, nicht in `scoring_config.json` (diese Datei ist auf den meisten Installationen für jeden lesbar). Die Konfiguration benennt die Variable; die Variable hält den Wert.

1. Erzeugen Sie ein Token und exportieren Sie es dort, wo der Viewer startet — systemd-Unit, `docker-compose.yml` oder Shell-Profil:

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

Ist `token_env` leer oder die Variable nicht gesetzt oder leer, ist der Endpunkt deaktiviert und liefert **404** (wie `frame.tokens` und `upload.username`).

### Immich darauf richten

In Immich ≥ 3.0: **Administration → Workflows → Create Workflow**.

1. **Trigger** — `Asset uploaded`. Fügen Sie `Asset updated` hinzu, wenn auch Bearbeitungen auslösen sollen.
2. **Action** — **Webhook**.
3. **URL** — `http://facet.local:5000/api/immich/webhook`, unter einer Adresse, die der Immich-Container erreichen kann. Laufen beide in Docker auf einem Host, verwenden Sie den Dienstnamen (`http://facet:5000/…`), nicht `localhost`.
4. **Header** — Name `x-facet-token`, Wert Ihr Token. Der Name muss zu `webhook.header` passen. `Authorization: Bearer <token>` wird ebenfalls akzeptiert, für Proxys, die nur das anbieten.
5. Speichern, dann ein Foto hochladen, um es zu prüfen.

### Was der Endpunkt antwortet

| Status | Bedeutung |
|--------|---------|
| `202` | Angenommen. Das JSON zählt die Assets dieser Zustellung: `received` / `pushed` / `skipped` / `pending` / `unmatched` / `failed`. |
| `204` | Gültiges JSON, aber kein Asset, das Facet erkannt hat. Protokolliert, kein Fehler. |
| `400` | Der Body war kein JSON. |
| `401` | Kein Token in der Anfrage. |
| `403` | Falsches Token. |
| `404` | Das Feature ist deaktiviert (kein Token konfiguriert). |

Facet liest `originalPath` aus der Payload, wo auch immer er steht: ein nacktes Asset, `{"asset": {…}}`, eine Liste oder eines davon unter `data` / `items` / `assets`. Enthält die Payload die Asset-`id`, ruft Facet dieses Asset von Immich ab und prüft vor dem Aktualisieren Pfad und Eigentümer/Bibliothek. Eine Abweichung zählt als `failed`.

Die nächste Synchronisierung protokolliert ausstehende Pfade:

```
WARNING  Immich webhook saw an asset Facet has not scored: /mnt/photos/2026/08/IMG_9999.jpg
```

Scannen Sie diese Fotos (`python facet.py /mnt/photos`), und sie verlassen die Liste bei der folgenden Synchronisierung. Die Liste hält höchstens `max_pending` Einträge und verwirft die ältesten zuerst.

### Sicherheitshinweise

- Das Token wird in konstanter Zeit verglichen; ein falsches Token ergibt ein glattes `403` ohne Timing-Signal.
- Betreiben Sie den Viewer über HTTPS, außer Immich erreicht ihn über ein privates Netzwerk: Das Token reist bei jeder Zustellung in einem Header mit.
- Zum Rotieren ändern Sie die Umgebungsvariable und den Immich-Workflow-Header gemeinsam und starten dann den Viewer neu.
- Der Webhook überträgt die globale Bewertung, nicht die eines einzelnen Benutzers. Für benutzerspezifische Bewertungen in Immich lassen Sie den Webhook deaktiviert und führen `--immich-sync --user <name>` nach Zeitplan aus.

## Diagnose im Viewer

Öffnen Sie im Untermenü **Aufgaben & Diagnose** des Benutzermenüs **Immich-Diagnose**. Im Mehrbenutzermodus benötigt sie Superadmin-Zugriff, im Einzelbenutzermodus Editionszugriff (oder vertrauenswürdige lokale Bearbeitung).

- Aus Immich wird nichts gelesen, bis Sie auf **Verbindung testen** klicken. Der Test liest Serverversion und Kontozugriff und schreibt nichts.
- Die Pfadabdeckung prüft höchstens 200 indexierte Fotos. Sie bestätigt nicht, dass jedes zu einem Immich-Asset passt.
- Der Zeitpunkt der letzten Synchronisierung kann vor einer Änderung des konfigurierten Servers liegen.
- Die Versionsprüfung verifiziert keine Stapelrechte.
- Zugangsdaten und Serverpfade werden nie angezeigt.

## Konfigurationsreferenz

Der vollständige `immich`-Block, mit den mitgelieferten Standardwerten:

```json
"immich": {
  "url": "",
  "api_key": "",
  "owner_id": "",
  "library_id": "",
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
| `owner_id` | `""` | Nur Assets mit genau dieser Immich-`ownerId` zuordnen. |
| `library_id` | `""` | Nur Assets in genau dieser Immich-`libraryId` zuordnen. Leer bedeutet jede Bibliothek. |
| `path_map` | ein leeres Paar | Präfix-Umschreibungen zwischen Facet-Pfaden und Immich-`originalPath`. Der erste Treffer gewinnt; in beide Richtungen verwendet. |
| `push.ratings` | `true` | Sternebewertungen 1–5 übertragen (und ihre Löschungen). |
| `push.favorites` | `true` | `isFavorite` übertragen (und dessen Löschungen). |
| `push.rejected` | `false` | `rating: -1` für in Facet abgelehnte Fotos übertragen. Erfordert `push.ratings`. |
| `push.top_picks_album` | `""` | Albumname, der befüllt gehalten wird: Mitglieder unter `push.top_picks_min_rating` werden bei einer globalen Synchronisation entfernt, solange Facet sie zuordnen kann. Leer bedeutet, dass Facet Alben nie anrührt. |
| `push.top_picks_min_rating` | `4` | Minimale Sternebewertung für dieses Album. |
| `webhook.token_env` | `""` | Umgebungsvariable, die das Webhook-Geheimnis hält. Leer deaktiviert den Endpunkt. |
| `webhook.header` | `"x-facet-token"` | Header, in dem Immich das Token sendet. |
| `webhook.max_pending` | `500` | Maximale Länge der Liste ausstehender (unbewerteter) Pfade. |
| `timeout_seconds` | `30` | HTTP-Timeout pro Anfrage. |

## Fehlerbehebung

### Alles kommt als `unmatched` zurück

Die Pfadzuordnung ist falsch. Das ist mit Abstand die häufigste Ursache.

1. Öffnen Sie ein Foto in Immich und drücken Sie `i`. Notieren Sie den Pfad im Info-Panel.
2. Finden Sie den Pfad desselben Fotos in Facet (das Galerie-Detailpanel, oder `sqlite3 photos.db "SELECT path FROM photos LIMIT 5"`).
3. Die beiden Pfade enden gleich. Die abweichenden Teile sind Ihr `facet_prefix` und Ihr `immich_prefix`.

Häufige Fallstricke:

- **Ein fehlender abschließender Schrägstrich.** `"/mnt/photos"` → `"/usr/src/app/external"` schreibt auch `/mnt/photosXYZ/a.jpg` um. Beenden Sie beide Präfixe mit `/`.
- **Host-Pfad vs. Container-Pfad.** Der Immich-Pfad ist das, was der *Container* sieht. Prüfen Sie mit `docker compose exec immich-server ls /usr/src/app/external`.
- **Symlinks und Bind-Mounts.** Immich speichert den Pfad, den es durchlaufen hat. Ein Symlink auf einer Seite lässt die Zeichenketten abweichen.
- **Groß-/Kleinschreibung und Unicode.** Der Vergleich ist exakt. Auf einer Freigabe ohne Beachtung der Groß-/Kleinschreibung passen `/Photos/` und `/photos/` nicht zueinander.
- **Immich hat die Datei noch nicht indiziert.** Führen Sie **Scan All Libraries** aus und prüfen Sie, ob das Asset in Immich existiert.

`--immich-sync --dry-run` protokolliert die ersten 20 nicht zugeordneten Pfade, was meist das falsche Präfix zeigt.

### `--immich-test` schlägt fehl

- `Unsupported Immich URL scheme` — `url` benötigt `http://` oder `https://`.
- `HTTP 401` — der API-Schlüssel ist falsch oder wurde widerrufen.
- `HTTP 403` — dem Schlüssel fehlt `server.about`. Erstellen Sie ihn mit den sieben Scopes oben neu.
- Verbindung verweigert / Timeout — der Port ist falsch, oder Facet kann den Container nicht erreichen. Testen Sie mit `curl -H "x-api-key: …" http://immich.local:2283/api/server/about` von der Facet-Maschine aus.

### Der Webhook liefert 404

Das Feature ist deaktiviert: `webhook.token_env` ist leer, oder die benannte Variable ist *in der Umgebung des Viewers* nicht gesetzt oder leer. Sie in Ihrer Shell zu exportieren erreicht keinen von systemd oder Docker gestarteten Viewer. Setzen Sie sie in der Unit- oder Compose-Datei und starten Sie neu.

### Der Webhook liefert 401 oder 403

`401`: Es kam kein Token an, der von Immich gesendete Header-Name passt also nicht zu `webhook.header`. `403`: Das Token ist falsch. Vergleichen Sie den Header-Wert des Workflows mit der Umgebungsvariable.

### `ModuleNotFoundError: No module named 'sync'`

Der Server wirkt gesund, aber der Webhook schlägt fehl, wenn Immich ihn aufruft, und `--immich-sync` schlägt von vornherein fehl. Prüfen Sie mit:

```bash
docker run --rm --entrypoint python ghcr.io/ncoevoet/facet:latest -c "import sync.immich"
```

Erhalten Sie `ModuleNotFoundError: No module named 'sync'`, ist Ihr Docker-Image zu alt. Ziehen Sie das aktuelle Image oder bauen Sie es aus einem aktuellen Checkout neu.

### Bewertungen werden übertragen, aber die Löschungen nicht

Facet löscht nur eine Bewertung, die es zuvor übertragen hat, und merkt sich diese in `stats_cache` in der Facet-Datenbank. Das Wiederherstellen einer älteren Datenbank oder die Verwendung einer neuen verliert dieses Gedächtnis: Eine in der Lücke gelöschte Bewertung bleibt in Immich. Bewerten und löschen Sie das Foto erneut, oder korrigieren Sie es in Immich.

### Bewertungen erscheinen bei den falschen Fotos

Facet überspringt mehrdeutige Zuordnungen und meldet sie als `identity_conflicts`:

- ein Facet-Pfad, der zu mehreren Immich-Assets passt
- mehrere Facet-Pfade, die auf denselben Immich-Pfad abgebildet werden

Für diese Pfade wird nichts geschrieben; andere Fotos synchronisieren weiter.

Ein Webhook-Batch ist strenger: Beanspruchen mehrere Facet-Pfade dasselbe Ziel oder dieselbe Asset-ID, wird jeder berechtigte Eintrag des Batches abgelehnt und als `failed` gezählt. Korrigieren Sie überlappende Wurzeln in `path_map` oder setzen Sie `owner_id` und `library_id`, und versuchen Sie es erneut. Raten Sie den Eigentümer nicht anhand eines Personennamens oder des Pfads.

Immich-Antworten müssen `id` und `originalPath` enthalten und zu einem konfigurierten Eigentümer und einer Bibliothek passen. Eine erfolgreiche Aktualisierung bedeutet, dass Immich sie angenommen hat; seine eigenen Metadatenaufträge können noch laufen.

### `rating: 0 is not valid`

Der Immich-Server ist älter als 3.0. Führen Sie ein Upgrade durch: Facet braucht `null` zum Löschen und `-1` für `push.rejected`, und auf 2.x gibt es keinen Ausweg.

---

**Siehe auch:** [Befehle — Immich-Synchronisierung](COMMANDS.md#immich-synchronisierung) · [Konfiguration](CONFIGURATION.md) · [Editor-Interop-Rezepte](INTEROP.md) für XMP-Roundtripping mit Lightroom, darktable und digiKam.
