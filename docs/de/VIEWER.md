# Web-Galerie

> 🌐 [English](../VIEWER.md) · [Français](../fr/VIEWER.md) · **Deutsch** · [Italiano](../it/VIEWER.md) · [Español](../es/VIEWER.md) · [Português](../pt/VIEWER.md) · [简体中文](../zh/VIEWER.md)

Die Galerie ist eine Web-App aus FastAPI und Angular zum Durchsuchen, Filtern, Aussortieren und Verwalten Ihrer Fotos.

## Inhalt

- [Galerie starten](#galerie-starten) · [Authentifizierung](#authentifizierung) · [Filteroptionen](#filteroptionen) · [Sortierung](#sortierung) · [Sichtungsentscheidungen](#sichtungsentscheidungen) · [Galeriefunktionen](#galeriefunktionen)
- [Panoramen und Belichtungsreihen](#panoramen-und-belichtungsreihen)
- [Personenverwaltung](#personenverwaltung) · [Scan auslösen](#scan-auslösen) · [Semantische Suche](#semantische-suche) · [Alben](#alben)
- [KI-Kritik](#ki-kritik) · [KI-Bildbeschreibung](#ki-bildbeschreibung-gpu-16gb24gb-edition) · [Erinnerungen ("Heute vor Jahren")](#erinnerungen-heute-vor-jahren) · [Zeitleisten-Ansicht](#zeitleisten-ansicht) · [Kartenansicht](#kartenansicht) · [Kapseln](#kapseln)
- [Ordner-Ansicht](#ordner-ansicht) · [GPS-Filterdialog](#gps-filterdialog) · [Zusammenführungsvorschläge](#zusammenführungsvorschläge) · [Editor-Export](#editor-export) · [Download](#download) · [Auswahl](#auswahl) · [Müll aufräumen](#müll-aufräumen) · [Paarweiser Vergleichsmodus](#paarweiser-vergleichsmodus)
- [EXIF-Statistiken](#exif-statistiken) · [Tastenkürzel](#tastenkürzel-galerie) · [Rückgängig](#rückgängig) · [Progressive Web App](#progressive-web-app) · [Mobil](#mobil) · [Bilderrahmen / Kiosk](#bilderrahmen--kiosk) · [Automatischer Upload vom Telefon](#automatischer-upload-vom-telefon)
- [Konfiguration](#konfiguration-2) · [Performance](#performance) · [API-Endpunkte](#api-endpunkte) · [JPEG-XL-Fotos](#jpeg-xl-fotos) · [Fehlerbehebung](#fehlerbehebung)

> **Funktionsanforderungen** sind inline gekennzeichnet: `[GPU]` · `[16gb/24gb]` (VRAM-Profil) · `[Edition]` (Bearbeitungspasswort) · `[Superadmin]`. Siehe die [Funktionsmatrix](INSTALLATION.md#funktionsanforderungen).

> **KI-Assistenten**: Facet kann seine Werkzeuge MCP-fähigen Assistenten bereitstellen. Mit der passenden Token-Stufe können sie die Bibliothek durchsuchen, ändern und aussortieren. Siehe [KI-Agenten (MCP)](AGENTS.md).

## Galerie starten

### Produktion

```bash
python viewer.py
# http://localhost:5000 öffnen
```

Das stellt die API und die vorgebaute Angular-App über einen Port bereit.

Für höheren Durchsatz verwenden Sie den Produktionsmodus (Uvicorn, ohne Auto-Reload). Mit `--workers N` skalieren Sie (Standard 1):

```bash
python viewer.py --production --workers 4
```

### Entwicklung

API-Server und Angular-Dev-Server getrennt starten:

```bash
# Terminal 1: API-Server
python viewer.py
# API verfügbar unter http://localhost:5000

# Terminal 2: Angular-Dev-Server mit Hot Reload
cd client && npx ng serve
# http://localhost:4200 öffnen (leitet API-Aufrufe an :5000 weiter)
```

## Authentifizierung

### Einzelbenutzermodus (Standard)

Schützen Sie die Galerie mit einem optionalen Passwort:

```json
{
  "viewer": {
    "password": "your-password-here"
  }
}
```

Zwei Passwörter steuern den Zugriff:

- **`viewer.password`** entscheidet, wer *stöbern* darf. Leer heißt: Jeder kann die gesamte Bibliothek durchsuchen. Ist es gesetzt, müssen sich Benutzer zuerst anmelden.
- **`viewer.edition_password`** ist für jede Bearbeitung erforderlich: Bewertungen, Favoriten und Ablehnungen, Aussortieren, Alben, Personen- und Gesichtsverwaltung, Vergleichsmodus, Gewichts- und Prioritätsänderungen sowie Exporte. Leer (der ausgelieferte Standard) macht die Installation **schreibgeschützt**: Bearbeitungen werden mit `403` abgelehnt („Set viewer.edition_password to enable editing“).

KI-Erzeugung auf Anfrage (Bildbeschreibungen, VLM-Kritiken) braucht ebenfalls das Bearbeitungspasswort. Ohne es erhalten Sie nur, was bereits im Cache liegt (`source: "none"` oder `vlm_available: false`). Ohne Bearbeitungspasswort blendet die Galerie zudem vorhandene Sterne-, Favoriten- und Ablehnungs-Badges aus, wie bei Betrachtern ohne Edition auf einer passwortgeschützten Installation.

Starten Sie den Viewer nach dem Setzen von `viewer.edition_password` neu: Die Konfiguration wird nicht im laufenden Betrieb neu geladen.

> **Warnung:** Bei leerem `viewer.password` (Standardwert) kann jeder, der den Port des Viewers erreicht, die Bibliothek durchsuchen und die Originale herunterladen. `viewer.py` lauscht standardmäßig auf allen Schnittstellen (`--host 0.0.0.0`, worauf sich das Docker-Image stützt). Setzen Sie `viewer.password`, bevor Sie den Viewer über den eigenen Rechner hinaus erreichbar machen, oder binden Sie ihn an Loopback mit `--host 127.0.0.1`. Unter Docker veröffentlichen Sie den Port als `127.0.0.1:5000:5000`. Der Viewer protokolliert beim Start eine Warnung, solange `viewer.password` leer ist (außer er wird an Loopback gebunden).

Die Anmeldung setzt das Sitzungstoken zusätzlich in einem `HttpOnly`-`SameSite=Lax`-Cookie, damit Vorschaubilder und der Scan-Fortschrittsstrom auf passwortgeschützten Installationen laden. Das Cookie gilt nur für lesende Anfragen (GET/HEAD); Bearbeitungen brauchen weiterhin das Bearer-Token. Die Abmeldung (`POST /api/auth/logout`) löscht es.

### Mehrbenutzermodus

Für ein Familien-NAS, auf dem jedes Mitglied eigene private Fotoverzeichnisse hat. Fügen Sie der `scoring_config.json` einen `users`-Abschnitt hinzu:

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

Schreiben Sie jeden Eintrag in `directories` und `shared_directories` genau so, wie der Scanner den Pfad gespeichert hat. Unter Windows, unter macOS sowie bei UNC- oder Laufwerksbuchstaben-Einträgen ignoriert der Vergleich die ASCII-Groß-/Kleinschreibung. Überall sonst (zum Beispiel unter Linux) unterscheidet er zwischen Groß- und Kleinschreibung. Unterschiede in der Groß-/Kleinschreibung außerhalb von ASCII sowie ein zugeordnetes Laufwerk, das der Host nicht auflösen kann, passen nicht.

Benutzer legen Sie über die CLI an (es gibt keine Registrierungsseite):

```bash
python database.py --add-user alice --role superadmin --display-name "Alice"
```

Siehe [Konfiguration](CONFIGURATION.md#users) für die vollständige Referenz.

### Rollen

| Rolle | Eigene + geteilte ansehen | Bewerten/Favorisieren | Personen/Gesichter verwalten | Scans auslösen |
|------|:-:|:-:|:-:|:-:|
| `user` | ja | ja | nein | nein |
| `admin` | ja | ja | ja | nein |
| `superadmin` | ja | ja | ja | ja |

### Fotosichtbarkeit

Jeder Benutzer sieht Fotos aus seinen eigenen Verzeichnissen sowie aus den geteilten Verzeichnissen. Das gilt überall: Galerie, Vorschaubilder, Downloads, Statistiken, Filteroptionen und Personenseiten.

### Benutzerspezifische Bewertungen

Im Mehrbenutzermodus werden Sternebewertungen, Favoriten und Ablehnungen pro Benutzer in der Tabelle `user_preferences` gespeichert. Alices Favoriten beeinflussen Bobs Ansicht nicht.

So migrieren Sie bestehende Einzelbenutzer-Bewertungen:

```bash
python database.py --migrate-user-preferences --user alice
```

## Filteroptionen

Die Textsuche der Galerie behält Unicode-Wörter bei und behandelt Satzzeichen in Dateinamen als Wortgrenzen. So sucht `IMG_0042.JPG` gemeinsam nach den Präfixen `IMG`, `0042` und `JPG`. Kyrillische und CJK-Begriffe funktionieren. FTS-Operatoren wie `OR` werden als wörtliche Begriffe behandelt.

### Tabs der Seitenleiste

Die Filter-Seitenleiste gruppiert ihre Abschnitte in fünf Tabs, die als Symbole angezeigt werden (Name per Mouseover). Ein kleines Abzeichen am Symbol zählt die aktiven Filter im Tab, und der Tab behält seinen Namen für Screenreader („Durchsuchen, 2 aktiv“). Der zuletzt verwendete Tab wird in diesem Browser gespeichert (`facet_sidebar_tab`). Durchsuchen, Qualität und Motiv haben einklappbare Bereiche, die sich jeweils merken, ob sie geöffnet sind; Prüfen und Anzeige haben keine.

| Tab | Abschnitte |
|-----|-----------|
| **Durchsuchen** | Semantische Suche, Personen, Zeitraum, Inhalt, Alben, Standort, Ordner, Ausrüstung |
| **Prüfen** | Je eine Menüzeile für die Entscheidung, dann für Serien, Duplikate, Blinzler, Belichtungsreihen, Panoramen und Abgelehnte, eine Sternebewertung, die Schalter Favoriten und Monochrom und für Editoren *Manuelle Gesichter prüfen* und *Panorama-Korrekturen* |
| **Qualität** | Qualität, Farbe & Qualität, Erweiterte Qualität, Technik, Belichtung & Bereich (wie gut das Bild ist) |
| **Motiv** | Gesichtsmetriken, Komposition, Motiverkennung, Momente (was im Bild zu sehen ist) |
| **Anzeige** | Ansicht (Kartengröße, Layout, schnelles Scrollen, Kartenaktionen) |

Kopfzeile, **Filter suchen**, der Hinweis für Smart-Alben und die Dateinamensuche bleiben auf jedem Tab über den Tabs, daher funktioniert `/` von jedem aus. Eine Eingabe in **Filter suchen** blendet die Tabs aus und listet die passenden Regler aus allen Tabs.

Die Zahl neben **Filter** ist die Summe aller aktiven Filter. Ein Min/Max-Bereich zählt einmal, ebenso der Ortsfilter. Die Dateinamensuche und *Ähnlich zu* haben keinen Abschnitt und werden nur in dieser Summe gezählt, ebenso ein Filter auf eine Metrik, die diese Installation ausblendet, damit **Filter zurücksetzen** ihn trotzdem löschen kann. **Filter zurücksetzen** (mit Tooltip) erscheint neben der Zahl, solange mindestens ein Filter aktiv ist; das schlichte **X** ganz rechts schließt die Seitenleiste nur auf schmalen Bildschirmen.

Im Tab Prüfen sind die Entscheidung und jede Gruppe (zum Beispiel Duplikate) eine Zeile mit ihrem aktuellen Wert (etwa Ausgeblendet, Eingeblendet oder Nur diese), die ein Menü mit Auswahlmöglichkeiten samt einzeiliger Erklärung öffnet. Eine Zeile mit ihrem Standardwert zählt nicht zum Abzeichen des Tabs oder der Kopfzeile. *Nur* und *Ausgeblendet* schließen sich gegenseitig aus. Solange eine Entscheidung gewählt ist, ist Abgelehnt gesperrt, und sein Tooltip nennt den Grund. Die Sterne-Schaltfläche setzt eine Mindestbewertung: Jeder Klick erhöht sie um eins, und der Klick nach 5 oder nach einem aus einem Link übernommenen Maximum löscht sie. Sie teilt sich eine Zeile mit den reinen Symbol-Schaltern Favoriten und Monochrom, die Tooltips haben. In den Tabs Qualität und Motiv erklärt das Überfahren des Namens einer Einstellung, was bewertet wird und von welchem Modell, und auch die Steuerelemente im Tab Prüfen haben Tooltips.

<details><summary>Filter-Seitenleiste — alle Abschnitte aufgeklappt (zum Anzeigen klicken)</summary>
<p align="center"><img src="../screenshots/filter-sidebar-full.jpg" alt="Die fünf Tabs der Filter-Seitenleiste nebeneinander: Durchsuchen, Prüfen, Qualität, Motiv und Anzeige" width="900"></p>
</details>

### Primärfilter

| Filter | Optionen |
|--------|---------|
| **Fototyp** | Beste Auswahl, Porträts, Personen in Szene, Landschaften, Architektur, Natur, Tiere, Kunst & Statuen, Schwarzweiß, Schwaches Licht, Silhouetten, Makro, Astrofotografie, Straßenfotografie, Langzeitbelichtung, Luftaufnahmen & Drohne, Konzerte |
| **Qualitätsstufe** | Gut (6+), Sehr gut (7+), Hervorragend (8+), Beste (9+) |
| **Kamera & Objektiv** | Filterung nach Ausrüstung |
| **Person** | Nach erkannter Person filtern |
| **Kategorie** | Nach Fotokategorie filtern |

### Erweiterte Filter

| Kategorie | Filter |
|----------|---------|
| **Datum** | Start- und Enddatum |
| **Wertungen** | Gesamtwertung, Ästhetik, TOPIQ-Wert, Qualitätswert |
| **Erweiterte Qualität** | Ästhetik IAA (künstlerischer Wert), Gesichtsqualität IQA, LIQE-Wert |
| **Gesichtsmetriken** | Gesichtsqualität, Augenschärfe, Gesichtsschärfe, Gesichtsanteil, Gesichtskonfidenz, Gesichteranzahl |
| **Komposition** | Kompositionswert, Kraftpunkte, Führungslinien, Freistellung, Kompositionsmuster |
| **Motiverkennung** | Motivschärfe, Motivhervorhebung, Motivplatzierung, Hintergrundtrennung |
| **Technik** | Schärfe, Kontrast, Dynamikumfang, Rauschniveau |
| **Farbe** | Farbwert, Sättigung, Helligkeit, Histogrammbreite; Farbtemperatur und Farbtongruppe (erfordern `--recompute-colors`) |
| **Belichtung** | Belichtungswert |
| **Benutzerbewertungen** | Sternebewertung |
| **Kameraeinstellungen** | ISO, Blende (F-Stop-Bereichsregler), Brennweite (Bereichsregler) |
| **Inhalt** | Tags, Monochrom-Umschalter |
| **Momente** | Narrative-Moment-Konfidenz (0–1-Bereichsregler: `min_moment_confidence` / `max_moment_confidence`) |

Manche Bereichsfilter treffen nur auf Fotos mit einem Wert zu, daher schließt selbst ein Filter, der bei 0 beginnt, nicht bewertete Fotos aus:

- **Ästhetik IAA, Gesichtsqualität IQA, LIQE, Aesthetic V2.5, Q-ReAlign, DeQA**: Ein Foto, das das Modell nicht bewerten konnte, hat keinen Wert. Eine aufsteigende Sortierung nach diesen Werten stellt es in der Galerie und in Alben ans Ende. Siehe [Ergänzende IQA-Dimensionen](SCORING.md#ergänzende-iqa-dimensionen).
- **Motivschärfe, Motivplatzierung, Hintergrundtrennung, Kraftpunkte**: Ein Foto ohne erkennbares Motiv hat keinen Wert, und der Detailbereich lässt die Zeile weg. Die Motivprominenz ist für ein solches Foto 0.0. Siehe [SCORING.md](SCORING.md).

### Kompositionsmuster

Nach den 8 von SAMP-Net erkannten Mustern filtern (aus `models/samp_net.py`):
- global, horizontal, vertical, triangular
- surround, quarter, cross, rule_of_thirds

## Sortierung

Die Sortierschaltfläche in der Kopfzeile (und der mobilen Werkzeugleiste) zeigt das Symbol der aktuellen Sortierung; ihr Tooltip lautet `Sortieren nach: <aktuelle Sortierung>`. Sie öffnet ein gruppiertes Menü mit allen Sortierungen. Der Umschalter für aufsteigend/absteigend sitzt daneben. Alternative Bewertungsmodelle verwenden kurze Bezeichnungen (IAA, 2.5, Q-R, DeQA, LIQE und IQA).

**Gemerkte Sortierung.** Die Galerie öffnet mit der Sortierung, die Sie zuletzt gewählt haben, und diese Wahl hat Vorrang vor `viewer.defaults.sort`. Sie wird pro Browser im `localStorage` gespeichert, nicht pro Benutzerkonto.

- Nur eine Wahl im Sortiermenü wird gemerkt. Eine Sortierung aus einem geteilten Link oder von einem Assistenten wird es nicht, und das eigene `sort` eines Links hat Vorrang.
- Wählen Sie erneut den konfigurierten Standard oder setzen Sie die Filter zurück, wird die Wahl vergessen.
- **Relevanz** wird nie gemerkt, da sie eine Suchanfrage voraussetzt.

Verschlusszeiten werden nach Dauer sortiert, daher sind `1/250` und `0.004` gleich. Fehlende oder ungültige Werte erscheinen in beiden Richtungen zuletzt.

Sortierbare Spalten nach Gruppe (aus `viewer.sort_options`):

| Gruppe | Spalten |
|-------|---------|
| **Allgemein** | Gesamtwertung, Ästhetik, Qualitätswert, Aufnahmedatum, Sternebewertung, Ästhetik (IAA), LIQE-Wert, Q-ReAlign (Ästhetik), DeQA, Ästhetik v2.5 (die letzten drei erscheinen, sobald ein Foto diesen Wert hat) |
| **Gesichtsmetriken** | Gesichtsqualität, Gesichtsqualität (IQA), Augenschärfe, Gesichtsschärfe, Gesichtsanteil, Gesichteranzahl |
| **Technik** | Techn. Schärfe, Kontrast, Rauschniveau |
| **Farbe** | Farbwert, Sättigung |
| **Belichtung** | Belichtungswert, Mittlere Helligkeit, Histogrammbreite, Dynamikumfang |
| **Komposition** | Kompositionswert, Kraftpunktwert, Führungslinien, Freistellungsbonus, Kompositionsmuster |
| **Motiverkennung** | Motivschärfe, Motivhervorhebung, Motivplatzierung, Hintergrundtrennung |
| **Inhalt** | Moment-Konfidenz (NULL-Werte ans Ende) |

### Mein Geschmack

Sortiert nach dem `learned_score` des persönlichen Rankers: was er aus Ihren A/B-Vergleichen, Bewertungen und Auswahlentscheidungen gelernt hat. Ein Abzeichen neben der Sortierung zeigt die Abdeckung (% der Fotos mit gelerntem Wert) und die Held-out-Genauigkeit des Rankers, sodass Sie einschätzen können, wie sehr Sie ihm vertrauen können. Trainieren oder aktualisieren Sie den Ranker mit `python facet.py --train-ranker`.

Gesteuert über `viewer.features.show_my_taste` (Standard: `true`). Ranker-Status: `GET /api/ranker/status`.

### Im kommerziellen Modus ausgeblendete Metriken

Ist `licensing.mode` auf `commercial` gesetzt, blendet der Viewer die Metriken aus, deren Modelle nicht kommerziell genutzt werden dürfen: LIQE, Aesthetic IAA, Face Quality IQA (sofern OFIQ nicht installiert ist), DeQA (sofern `licensing.allow_unclear` nicht gesetzt ist) und Aesthetic V2.5. Ihre Filter, Chips und Sortieroptionen verschwinden; `/api/config` listet sie in `unavailable_metrics`. Auf der Gewichtungsseite bleiben ihre Regler sichtbar, sind aber deaktiviert, und die Bewertung lässt diese Gewichte aus und normalisiert neu. Starten Sie den Viewer nach einer Änderung des Lizenzmodus neu.

## Sichtungsentscheidungen

Wählen Sie in der Galerie **Auswahlstatus → Zu prüfen**, um unentschiedene Fotos zu bearbeiten. Diese Ansicht sortiert nach **Aufnahmedatum, älteste zuerst**; Sie können die Reihenfolge umkehren oder nach Datum, Ordner oder Album eingrenzen. Die Wahl eines Auswahlstatus beendet eine semantische Suche und die Suche nach ähnlichen Fotos.

- Mit **Behalten** markieren Sie ein gewünschtes Foto, mit **Ablehnen** ein unerwünschtes. Beides nimmt es aus „Zu prüfen“. Behaltene Fotos finden Sie mit dem Statusfilter **Behalten**.
- Behalten ist unabhängig von Favoriten und Sternebewertungen.
- Behalten und **Entscheidung zurücksetzen** stehen in der Detailansicht, im Kontextmenü und in den Sammelaktionen bereit. **K** (umbelegbar, siehe [Tastenkürzel](#tastenkürzel-galerie)) behält das aktuelle Foto. In der Detailansicht ist Behalten ein Umschalter.
- **Entscheidung zurücksetzen** löscht Behalten und Ablehnen, ohne Sterne oder Favorit zu ändern.
- Entscheidungen überstehen Neuladen, Neustarts und erneute Scans. Bei Mehrbenutzer-Installationen gehören sie dem aktuellen Benutzer.
- Das Bestätigen einer Auswahlgruppe markiert deren behaltene Fotos als Behalten. Bestehende Bewertungen und Favoriten werden nicht in Behalten-Entscheidungen umgewandelt.

**Fortschrittszahlen.** Die Galerie zeigt die Anzahl **unentschiedener**, **behaltener** und **abgelehnter** Fotos für den gesamten sichtbaren Ordner, das Album oder den gefilterten Bereich, nicht nur für die geladene Seite. Der Prozentsatz ist `(behalten + abgelehnt) / gesamt`. Der Auswahlstatus und der Schalter „Abgelehnte ausblenden“ verkleinern die Gesamtzahl nicht; andere Filter tun es.

**Eine Warteschlange fortsetzen.** **Unentschiedene sichten** beginnt eine Warteschlange. **Sichtung fortsetzen** öffnet in diesem Browser Ihre letzte Warteschlange „Zu prüfen“ erneut bei ihrem ersten noch unentschiedenen Foto.

- Das Lesezeichen gilt pro Browser und pro angemeldeter Identität (bis zu 20 Identitäten). Es wird nicht zwischen Geräten synchronisiert.
- Geänderte Filter ersetzen es nicht, solange Sie keine andere Warteschlange „Zu prüfen“ öffnen.
- Album-Warteschlangen verwenden die aktuell gespeicherten Kriterien des Albums.
- Temporäre Serien-/Sequenzgruppen werden nicht gemerkt, da ein erneuter Scan sie neu nummerieren kann.
- Das Abmelden löscht alle Warteschlangen-Lesezeichen in diesem Browser.

**Schwebende Hinweise.** Bewertungsfortschritt, **Sichtung fortsetzen**, der Hinweis zu ausgeblendeten Fotos, der Hinweis zu aktiven Filtern (mit **Alle Filter zurücksetzen**) und der Hinweis zur Vorschaubild-Migration stapeln sich unten rechts.

- Das × jeder Karte blendet sie für den aktuellen Browser-Tab aus. Sie kehrt in einem neuen Tab zurück oder wenn sich der Hinweis ändert (anderer Bereich, geänderte Zahl ausgeblendeter Fotos, hinzugefügter oder entfernter Filter).
- Um den Bewertungsfortschritt dauerhaft auszublenden, nutzen Sie im Benutzermenü **Bewertungsfortschritt ausblenden** / **Bewertungsfortschritt anzeigen**. Das wird pro Browser gespeichert und blendet auch die Schaltfläche **Unentschiedene sichten** aus.
- Nach einigen Sekunden ohne Interaktion faltet sich der Stapel zu einer kleinen Zählpille zusammen. Zeiger darüber oder ein Klick darauf entfaltet ihn.

## Galeriefunktionen

### Manuelle Fotostapel

Wählen Sie **2–1000 konkrete Fotos**, dann **Fotos stapeln** in der Auswahlleiste oder drücken Sie **S**, um den ganzseitigen Editor unter `/stacks/edit` zu öffnen. Eine Gesamtauswahl der Ansicht erstellt keinen Stapel. S öffnet nur die Vorschau und speichert nicht. Benutzermenü → **Tastenkürzel anpassen** ändert die Galeriebelegung; Tooltip, Hilfe und `?` zeigen die aktuelle Taste. Belegt eine ältere gespeicherte Einstellung bereits S, bleibt sie erhalten und Stapeln ist **Nicht zugewiesen**, bis Sie eine freie Taste wählen. Bearbeitungsrechte sind erforderlich. Jedes Foto gehört je Eigentümer höchstens einem Stapel. Die Seite zeigt mittig eine zoombare Vorschau über einem dauerhaften Miniaturstreifen. Klicken Sie auf eine Miniatur oder verwenden Sie `←`/`→`, um ein Foto zu fokussieren; die zugehörigen Schaltflächen wählen das Titelbild, ändern die Reihenfolge oder entfernen es. Zoomtaste, Mausrad oder Doppelklick zeigen Details.

Mit **Cmd+Umschalt+S** oder **Strg+Umschalt+S** stapeln Sie ausdrücklich ausgewählte, ungestapelte Fotos sofort in Auswahlreihenfolge; das erste wird Titelbild. Vorhandene Stapelmitglieder öffnen den Editor. Erfolg hebt die gespeicherte Auswahl auf, Rückgängig stellt sie wieder her; Abbruch oder Fehler behalten sie. Escape im Editor kehrt ohne Speichern zur ursprünglichen Galerie zurück.

**Beim Stapeln ablehnen.** Fokussieren Sie im Seiteneditor oder Stapeldialog ein Foto und wählen Sie **Ablehnen** oder **R**. Das aktive Foto in der Dunkelkammer der Stapelvorschläge bietet dieselbe Aktion; öffnen Sie diese zuerst zur Auswahl. Ablehnen speichert sofort die gewöhnliche Sichtungsentscheidung, löscht Behalten, Favorit und Sterne und schließt nur dieses Foto aus dem vorgeschlagenen Stapel aus. Originaldateien werden weder gelöscht noch verändert. Zähler und abgedunkelte Miniaturen zeigen Ausschlüsse. Rückgängig stellt vorherige Werte und weiterhin relevante Entwurfsmitgliedschaft wieder her, ohne spätere Reihenfolge oder Titelbildwahl zu ersetzen; spätere Sichtungsänderungen können Rückgängig verhindern. Bereits abgelehnte Fotos bleiben bis zum ausdrücklichen Ausschluss enthalten, ohne weitere Sichtungsentscheidung. Gruppierung wartet auf Speichern; Verlassen ohne Speichern macht Ablehnen nicht rückgängig.

Gehören ausgewählte Fotos bereits zu Stapeln, ist **Stapel zusammenführen** die Vorgabe: Die Vorschau nimmt deren übrige Mitglieder hinzu. **Nur ausgewählte Fotos** verschiebt nur die konkrete Auswahl. Der Editor zeigt Auswahl- und Ergebnisanzahl, zusätzliche Mitglieder und eine Zusammenfassung der Folgen; klappen Sie die Details für jeden Quellstapel auf. Mindestens zwei zurückbleibende Mitglieder behalten ihren Stapel; ein einzelnes wird unabhängig und eine leere Quelle verschwindet. Aus dem neuen Stapel ausgeschlossene Fotos bleiben nach denselben Regeln in ihrer Quelle. Zielstapel und insgesamt betroffene Fotos sind jeweils auf 1000 begrenzt; nicht verfügbare oder teilweise sichtbare Quellen werden abgelehnt. Beim Moduswechsel bleiben weiterhin passende Reihenfolge, Titelbild und Ausschlüsse erhalten.

Prüfen Sie die vom Server aktualisierte Vorschau und speichern Sie mit **Fotos stapeln**. Die Seite bleibt zur Ergebniskontrolle offen; die Benachrichtigung bietet **Rückgängig**, solange sie verfügbar ist und die Revisionen passen. **Weiter bearbeiten** lädt vor erneutem Speichern eine frische Vorschau. **Zurück zur Galerie** führt zur ursprünglichen Galerie oder zum Album mit der genauen URL zurück und beendet das bisherige Rückgängig. Verlassen ohne Speichern verwirft die Gruppierung; ausdrückliches Ablehnen bleibt gespeichert. Neuladen im Browser stellt die Auswahl nur für dasselbe Konto und nach erneuter Autorisierung her; eine URL ohne gültigen Auswahlzustand bietet einen Rückweg.

Das Zählabzeichen oder ein gestapeltes Foto öffnet die Fotoansicht mit Vorschaustreifen, Vor-/Zurück-Schaltflächen und Positionsanzeige in gespeicherter Reihenfolge. Pfeiltasten bleiben im Stapel. **Stapel verwalten** öffnet einen zusätzlichen Dialog: Klicken Sie auf eine Miniatur oder nutzen Sie Links/Rechts für die große Vorschau, wählen Sie **Titelbild**, ändern Sie die Reihenfolge mit den Pfeilschaltflächen oder entfernen Sie Mitglieder. Allein das Öffnen behält die normale Bearbeitung bei: Entfernte Mitglieder werden unabhängig, nach Entfernen des Titelbilds wird das erste verbleibende gewählt, und unter zwei Mitgliedern oder mit **Stapel auflösen** wird die Gruppe aufgelöst. Das ausdrückliche **Hinzufügen ausgewählter Fotos** aus einem anderen Stapel wechselt zur Gruppierungsvorschau mit beiden Modi. Gruppierungsänderungen bewahren Dateien und Sichtungswerte; ausdrückliches Ablehnen ändert Sichtungswerte sofort.

- Aktionen für Bewertung, Behalten/Ablehnen, Metadaten, Download, Album und Löschen erweitern einen Stapel nie implizit.

**In der Galerie.** Ein Stapel klappt zu einer Kachel zusammen; **Alle Stapel aufklappen** ist eine gemerkte Einstellung. Filter und Albummitgliedschaft gelten für einzelne Fotos: Das Titelbild erscheint, wenn es passt, sonst das erste passende Mitglied. Das Durchblättern eines Stapels umgeht das automatische Ausblenden von Serien/Duplikaten. Zeitleiste und Karte zeigen einzelne Fotos.

**Auswählen.** Eine eingeklappte Kachel wählt nur das angezeigte Foto. Öffnen Sie den Stapel und nutzen Sie **Alle N Mitglieder auswählen**, um alle zu wählen. **Alle in der Ansicht auswählen**, die Prozent-Auswahl und `target:view` des Assistenten umfassen jedes passende Foto, auch eingeklappte Mitglieder, und Aktionen für die ganze Ansicht zeigen vorher die tatsächliche Fotozahl. In API-/Assistenten-Zusammenfassungen zählt `total` angezeigte Kacheln und `photo_total` Fotos.

**Datenschutz und Persistenz.**

- Stapel sind privat für ihren Eigentümer (im Einzelbenutzermodus die Installation). Das Bearbeiten erfordert Edition.
- Sie fehlen in öffentlichen Freigaben und Viewer-Exporten. Ein teilweise sichtbarer Stapel ist schreibgeschützt.
- Erneute Scans behalten Titelbild, Reihenfolge und Mitgliedschaft. Normale Datenbanksicherungen bewahren Stapel.
- Vollständige Viewer-Datenbankexporte lassen Stapel und intelligente Alben weg, deren Filter einen privaten Stapel nennen, sowie intelligente Alben mit unlesbaren Filtern (ungültiges JSON, zu tiefe Verschachtelung oder über 1 MiB). Inkrementelle Aktualisierungen bewahren die eigenen Alben und Stapel des Ziels.
- [Immich-Import/Übertragung von Stapeln](IMMICH.md#manuelle-stapel-importieren-und-übertragen) ist ein getrennter CLI-Vorgang.

**Vorgeschlagene Stapel** öffnet die ganzseitige Prüfung unter `/culling?mode=stacks` mit den aktuellen Galeriefiltern und einem Rückweg zur ursprünglichen Galerie oder zum Album. Bearbeitungsrechte sind erforderlich. Vorhandene Duplikat- und Seriengruppen werden ohne Ausblenden ihrer Mitglieder geprüft.

- Im Raster wählen `↑`/`↓` eine Gruppe, **Enter** öffnet ihre Dunkelkammer und **S** stapelt sie mit dem vorgeschlagenen Titelbild. In der Dunkelkammer fokussieren `←`/`→` ein Bild; **S** oder **Enter** stapelt mit diesem Titelbild. **X** überspringt; Stapeln und Überspringen bieten Rückgängig.
- **Ablehnen** oder **R** in der Dunkelkammer schließt das aktive Foto aus. Stapeln speichert verbleibende Fotos und erfordert mindestens zwei. Überspringen verwirft den ursprünglichen Vorschlag. Bei zu wenigen Fotos können Sie ausgeschlossene Fotos prüfen, Gruppen wechseln, rückgängig machen, überspringen oder zurückgehen. Die Ablehnung bleibt nach Abschluss eines Vorschlags gespeichert. Rückgängig für Stapeln oder Überspringen stellt dessen Ausschlüsse wieder her; ein späterer Vorschlag beginnt als neuer Entwurf.
- Die Dunkelkammer behält große zoombare Vorschau, Lupe, Vergleich und Miniaturstreifen. **Z** schaltet Zoom, **P** Fokus-Peaking, **F** Vollbild um; **G** wechselt das Kompositionsraster; **Escape** führt zum Gruppenraster zurück. **Mitglieder bearbeiten** öffnet einen zusätzlichen Dialog; bei nur noch einem Foto bietet er **Diesen Stapel überspringen**.
- Übersprungene Gruppen werden je Konto bis zur Änderung ihrer Mitglieder gespeichert. Gruppen mit bereits gestapelten Fotos oder Belichtungsreihen-/Panoramabildern werden ausgeschlossen; überlappende Gruppen werden ganz ausgeschlossen, mit Vorrang für Duplikate.
- Die Kopfzeile zählt geladene Vorschläge, nicht die gesamte Bibliothek. Ein Durchgang umfasst höchstens 20 Vorschläge und 2000 Fotos (1000 je Gruppe). Der nächste lädt erst automatisch, wenn alle geladenen Vorschläge gestapelt oder übersprungen wurden. **Vorschläge neu laden** lädt denselben Bereich erneut; **Zurück zur Galerie** führt zum Ursprung.
- Nicht in angehefteten Listen, Ähnliche Fotos oder der semantischen Suche verfügbar. Stapeln und Überspringen ändern weder Sichtungsentscheidungen noch Originale. Nur ausdrückliches Ablehnen ändert die Sichtungswerte.

### Fotokarten

- Vorschaubild mit Wertungsabzeichen. Fahren Sie darüber, um zu sehen, wo der Wert in Ihrer Bibliothek liegt („Top 18 % der Bibliothek“).
- Anklickbare Tags zum schnellen Filtern
- Personen-Avatare für erkannte Gesichter
- Kategorieabzeichen
- Rechtsklick (oder Shift+F10) öffnet das [Kontextmenü](#mehrfachauswahl--sammelaktionen)

In der Fotodetailansicht liegen die Messwerte in Symbol-Tabs: EXIF-Daten (sofern vorhanden), Qualität, Komposition (mit Motiv-Salienz), Technik und Histogramm. Der zuletzt geöffnete Tab wird gemerkt. Jeder Wert steht neben seiner Verteilung über die Bibliothek, mit hervorgehobenem Balken des Fotos; fahren Sie über einen Balken für den Rang des Fotos und den Bereich der Bibliothek. Die Einordnung wird über die gesamte Bibliothek berechnet, nicht über die aktuellen Filter, auf einen von 20 Balken genau.

### Mehrfachauswahl & Sammelaktionen

Klicken Sie Fotos zum Auswählen an; Umschalt+Klick wählt einen Bereich. Unten links erscheint eine Aktionsleiste mit Symbolschaltflächen (Maus darüber für die Beschriftung). Sammelaktionen erfordern den Bearbeitungsmodus.

- **Favorit** — Alle als Favorit markieren (hebt Ablehnung auf)
- **Ablehnen** — Alle als abgelehnt markieren (hebt Favorit und Bewertung auf)
- **Bewerten** — Sternebewertung (1–5) setzen oder löschen
- **Zu Album hinzufügen** — Zu einem bestehenden oder neuen Album hinzufügen
- **Schlagwörter bearbeiten** — Ein [manuelles Tag](#manuelle-tags) zu jedem ausgewählten Foto hinzufügen oder daraus entfernen
- **Alle auswählen** — Bei leerer Auswahl wird jedes Foto gewählt, auf das die Filter zutreffen, nicht nur die geladenen Seiten. Sind bereits Fotos gewählt, kommen die geladenen Fotos hinzu, und es wird angeboten, auf die ganze Ansicht zu erweitern. Aktionen für die ganze Ansicht bestätigen zuerst die genaue Fotozahl.
- **Umkehren** — Die Auswahl gegen ihr Komplement tauschen. Bei leerer Auswahl ist das die ganze Ansicht. Bei nicht leerer Auswahl bleibt es auf geladene Fotos begrenzt: erst die Behalte-Kandidaten wählen, umkehren, ablehnen.
- **Vergleichen** — 2–4 Fotos nebeneinander öffnen, mit synchronisiertem Schwenken und Zoomen (Scrollen zum Zoomen, Ziehen zum Schwenken, Doppelklick zum Zurücksetzen). Beim Zoomen wechseln die Fenster auf volle Auflösung.
- **Dateinamen kopieren** — Dateinamen in die Zwischenablage kopieren. Ein Kopieren der ganzen Ansicht bestätigt zuerst; über 10 000 Fotos wird abgelehnt.
- **Exportieren** — XMP-Sidecars neben die Dateien schreiben (siehe [Editor-Export](#editor-export))
- **In Ordner aussortieren** — Behaltene kopieren oder Abgelehnte in einen Ordner verschieben/in den Papierkorb legen (siehe [In Ordner aussortieren](#in-ordner-aussortieren))
- **Löschen** — Fotos in den Systempapierkorb legen (siehe [Löschen](#löschen)). Nur sichtbar, wenn `viewer.cull.allow_trash` an ist. Deaktiviert bei einer Auswahl „Alle in der Ansicht“: wählen Sie Fotos ausdrücklich aus.
- **Herunterladen** — Die ausgewählten Fotos herunterladen
- Heben Sie die Auswahl mit Escape oder der Schaltfläche „Löschen“ auf.

Doppelklicken Sie ein Foto, um es zu öffnen.

**Kontextmenü.** Klicken Sie mit der rechten Maustaste auf ein Foto, oder fokussieren Sie es und drücken Sie Shift+F10 bzw. die Menütaste.

- Bei einem Foto innerhalb einer Auswahl mehrerer Fotos wirkt es auf die gesamte Auswahl mit den Aktionen der Leiste (außer Umkehren und Alle auswählen), einschließlich **Schlagwörter bearbeiten**.
- Bei jedem anderen Foto wirkt es nur auf dieses und bietet zusätzlich Foto öffnen, Ähnliche finden, Warum diese Bewertung?, Metadaten in Datei schreiben und Gesicht einer Person zuweisen (wenn das Foto nicht zugewiesene Gesichter hat), jeweils unter ihren Bedingungen.
- Das Aussortieren eines einzelnen Fotos aus dem Menü nimmt nur dieses Foto aus der Auswahl.
- Auf Geräten mit Touch-Bedienung (`hover: none` und `pointer: coarse`) nicht angeboten; nutzen Sie dort das Aktionsblatt.

### Top N% behalten

Das Steuerelement **Top % behalten** in der Symbolleiste (Bearbeitungsmodus) sortiert die gesamte gefilterte Ansicht in einem Schritt aus. Legen Sie einen Prozentsatz fest. Facet ordnet die Ansicht nach der **aktuellen Sortierung** (Gesamtwertung, Mein Geschmack, Beste Auswahl, Schärfe, …), behält den oberen Anteil und **wählt den Rest aus**. Lehnen Sie ihn über die Aktionsleiste ab, nachdem Sie einzelne Fotos abgewählt haben, die Sie verschonen möchten.

- Es wird nichts verschoben oder gelöscht; es befüllt nur die Auswahl. Ablehnungen trainieren weiterhin „Mein Geschmack“.
- Die Auswahl ist auf 5000 Fotos begrenzt. Grenzen Sie bei einer größeren Ansicht den Filter ein (Album, Datum, Person…).
- Unter den Standardwerten `hide_brackets` / `hide_panoramas` zählt eine Belichtungsreihe oder ein Panorama als **ein** Foto.

### Vom Assistenten angeheftete Liste

Zeigt Ihnen ein über [KI-Agenten (MCP)](AGENTS.md) verbundener Assistent eine exakte Fotoliste, zeigt die Galerie sie in der Reihenfolge des Assistenten. Eine Statuszeile nennt die Zahl der gewählten Fotos; **Zur üblichen Ansicht zurück** stellt Ihre Filter wieder her.

- Solange die Liste gezeigt wird, sind die Filterleiste, Tag-Chips, Personen-Avatare, **Ähnliche finden** und filterbezogene Aktionen (etwa **Top N % behalten**) ausgeblendet. Ein Albumwechsel ersetzt die Liste weiterhin.
- Das Anzeigen einer Liste hebt Ihre Auswahl und die Seitenleiste auf.
- Schreibvorgänge des Assistenten erscheinen ohne Neuladen: Geänderte Karten aktualisieren sich, gelöschte Fotos verlassen die Liste. Ein von `cull_apply` verschobenes oder in den Papierkorb gelegtes Foto bleibt. Pro Schub erscheint eine Meldung „Der Assistent hat N Fotos geändert“. Siehe [Live-Aktualisierung](AGENTS.md#live-aktualisierung).

**Chip „Assistent aktiv“.** Solange ein Assistent in Ihrem Tab arbeitet, zeigt die Kopfzeile nach jedem Schreibvorgang oder Befehl einige Sekunden lang einen Chip **Assistent aktiv**. Ein Klick öffnet **Assistenten-Aktivität**: die letzten 50 Aktionen dieser Sitzung (beim Neuladen verloren) mit Tool, Anzahl der Fotos und Uhrzeit. Aktionen, die Fotos benannten, haben **Fotos anzeigen**. Auf Anfrage teilt der Tab dem Assistenten mit, auf welchem Foto Ihr Cursor steht (`focused`) und was Sie seit seinem letzten Blick getan haben (`user_activity`). Von selbst wird nichts gesendet. Siehe [Den geöffneten Tab steuern](AGENTS.md#den-geöffneten-tab-steuern).

### In Ordner aussortieren

**In Ordner aussortieren…** in der Sammelaktionsleiste (Bearbeitungsmodus) kopiert Behaltene oder verschiebt/entsorgt Abgelehnte in einen Zielordner. Papierkorb bedeutet den Systempapierkorb, nie ein endgültiges Löschen, und erfordert `viewer.cull.allow_trash`.

- **Jeder Lauf beginnt als Trockenlauf.** Sie sehen eine Vorschau, bevor etwas geschrieben wird; Verschieben/Papierkorb laufen nur mit einem ausdrücklichen `dry_run=false`.
- **Der Server wählt die Dateien anhand des Status jedes Fotos.** Kopieren wirkt nur auf Behaltene, Verschieben/Papierkorb nur auf Abgelehnte. Alles andere wird als `excluded_by_state` gemeldet. Der Client kann keine Liste zu löschender Dateien übergeben.
- **Begleitdateien sind optional.** Das Ablehnen eines JPEGs nimmt sein RAW nicht mit, solange Sie nicht **RAW/XMP-Begleitdatei einbeziehen** (`include_companions`) ankreuzen.
- Unter macOS und Windows behalten RAW-Begleitdateien ihre Dateinamen auf dem Datenträger, einschließlich großgeschriebener Erweiterungen; unter Windows gilt das auch für `.xmp`-Sidecars.

**Verfügbarkeit von „Abgelehnte in den Papierkorb“.** Die Option erscheint nur, wenn `viewer.cull.allow_trash` an ist *und* das Paket `send2trash` installiert ist (`/api/config` meldet `cull.trash_available: true`). Andernfalls nennt der Dialog den Grund: „das Paket `send2trash` ist nicht installiert“ oder „ein Administrator hat den Papierkorb deaktiviert“.

**Mehrbild-Sets.** Unter den Standardwerten `hide_brackets` / `hide_panoramas` enthält die Auswahl nur die Basisbelichtung einer Belichtungsreihe oder das mittlere Bild eines Panoramas. Standardmäßig wirkt das Aussortieren eines Sets daher auf diese **eine** Datei. Zwei Kontrollkästchen weiten es aus:

- **RAW/XMP-Begleitdatei einbeziehen** (`include_companions`) fügt das RAW und das `.xmp`-Sidecar derselben Aufnahme hinzu.
- **Sequenzgeschwister einbeziehen** (`include_sequence_siblings`) fügt die anderen Aufnahmen des Sets hinzu, aber nur jene, deren eigener Behalten-/Ablehnen-Status zur Aktion passt. Behaltene Aufnahmen werden nie entsorgt, weil ein Geschwister abgelehnt wurde. Eine Aufnahme, die Sie abgewählt haben, wird nie wieder hinzugezogen.
- Die Vorschau meldet immer, wie viele Geschwister-Aufnahmen existieren (`sequence_siblings`). `matched` unterscheidet „nichts kam infrage“ von einem leeren Ergebnis.
- Wird das Leitfoto eines Sets verschoben oder entsorgt, rückt ein überlebendes Geschwister nach, sodass das Set sichtbar bleibt.
- Um eine genaue Teilmenge eines Sets zu wählen, öffnen Sie es zuerst über die Aktion „dieses Set in der Galerie öffnen“ der Fotodetailansicht. Diese Ansicht zeigt jede Aufnahme.

Ein filterbasiertes Aussortieren folgt denselben Filterregeln wie die Galerie, den Fototyp eingeschlossen. Eine Ansicht mit über 10 000 Fotos wird abgelehnt statt abgeschnitten, auch bei einem Trockenlauf: Grenzen Sie sie ein (Album, Datum, Person…) und versuchen Sie es erneut. Details: [API.md](../API.md).

**Wohin Sie schreiben können.** Ohne `viewer.export.allowed_target_dirs` schreibt Facet nur in Ihre Scan-Verzeichnisse. Ein Unterordner des Fotobaums (z. B. `_rejected`) funktioniert ohne Einrichtung. Für einen Ordner anderswo fügen Sie ihn zu `viewer.export.allowed_target_dirs` hinzu. Siehe [Konfiguration — Ziele für Export und Aussortierung](CONFIGURATION.md#ziele-für-export-und-aussortierung). Unter Docker/Podman werden Pfade **innerhalb des Containers** aufgelöst — siehe [Deployment — Pfadsemantik im Container](DEPLOYMENT.md#pfadsemantik-im-container).

**„Zugriff verweigert“ bei jeder Aktion.** Das ist eine bewusste Ablehnung: Der Zielordner ist nicht erlaubt, oder Ihre Bearbeitungssitzung ist abgelaufen. Prüfen Sie im Netzwerk-Tab des Browsers das Feld `detail` der fehlgeschlagenen Anfrage. Ein echtes Dateisystemproblem sieht anders aus: Teilerfolg mit einer von null verschiedenen `errors`-Anzahl und der Betriebssystemfehler im Server-Log.

### Löschen

**Löschen** in der Fotodetailansicht und der Auswahlleiste schickt Dateien direkt in den Systempapierkorb (wiederherstellbar, über `send2trash`). Es ist getrennt von „In Ordner aussortieren“ und von der `/culling`-Dunkelkammer. Es nutzt dasselbe Flag `viewer.cull.allow_trash`.

- **Der Bibliothekseintrag verschwindet sofort.** Anders als bei „In Ordner aussortieren“ wird die Zeile des Fotos entfernt, sobald seine Datei im Papierkorb ist; kein `--cleanup-missing-photos` nötig. Eine einbezogene Begleit-RAW, die als eigenes Foto gescannt wurde, verschwindet ebenfalls.
- **Nur ausdrückliche Auswahl.** Bis zu 10000 Pfade; „Alle in der Ansicht auswählen“ ist deaktiviert.
- **Umfang.** Standardmäßig nur die benannte Datei. **RAW/XMP-Begleitdatei einbeziehen** (`include_companions`) und **Sequenzgeschwister einbeziehen** (`include_sequence_siblings`) weiten es aus, wie bei „In Ordner aussortieren“. Beide sind standardmäßig aus.
- **Basisbelichtungen von Belichtungsreihen sind geschützt.** Die Basisaufnahme einer Belichtungsreihe (`sequence_ev_offset = 0`) wird abgelehnt (`refused_bracket_lead`), außer Sie beziehen Geschwister ein; dann geht die ganze Reihe zusammen. Ein gelöschtes Panorama-Leitbild lässt ein überlebendes Geschwister nachrücken.
- **Teilergebnisse.** Jeder Pfad wird einzeln gemeldet. Eine abgelehnte Bracket-Leitaufnahme stoppt den Rest nicht. Eine Datei, deren Papierkorb-Versuch fehlschlug (`errors`), behält ihre Zeile.
- **Dateien, die auf der Platte bereits fehlen.** **Bibliothekseinträge ebenfalls entfernen, deren Datei auf der Platte bereits fehlt** (standardmäßig an) entfernt auch diese Zeilen, gemeldet als `removed_missing`. Ohne Häkchen kommen sie in `skipped` zurück und behalten ihre Zeilen. Ein Pfad außerhalb der Scan-Verzeichnisse oder in einem fehlenden oder leeren Ordner (ein getrenntes Laufwerk) bleibt immer in `skipped`. Für die ganze Bibliothek nutzen Sie `--cleanup-missing-photos`.

Antwortfelder und Statuscodes: [API.md](../API.md).

### Anzeigeoptionen

- **Layout-Modus** — **Raster** (einheitliche Karten) oder **Mosaik** (justierte Zeilen, die Seitenverhältnisse beibehalten), bei jeder Bildschirmbreite.
- **Vorschaubildgröße** — Regler für die Karten-/Zeilenhöhe (120–400px, in localStorage gespeichert)
- **Details ausblenden** — Metadaten auf Karten ausblenden (nur im Rastermodus)
- **Tooltip** — Wie Fotodetails erscheinen: **Seitenleiste** (Standard), **Hover**, **Klick** oder **Aus**.
  - Die Seitenleiste zeigt alle Details in der rechten Schublade, angeordnet wie in der Fotodetailansicht. Sie folgt Hover und Klick und funktioniert so auch auf Touch-Bildschirmen. Sie behält das letzte Foto, wenn der Zeiger das Raster verlässt.
  - Ein Klick auf ein Foto hält die Leiste darauf fest, bis Sie **Auswahl aufheben** drücken (das auch das Foto abwählt). **Escape** wirkt genauso und hebt die Auswahl auf.
  - Die Leiste teilt sich die Schublade mit den Filtern; das Öffnen der Filter blendet sie aus. Erfordert ein Fenster von mindestens 1280px.
  - **Hover** und **Klick** zeigen eine kurze Blase: Kategorie, Gesamtwertung und Rang, Ästhetik, Komposition, Schärfe, Belichtung und eine EXIF-Zeile.
- **Kartenknöpfe anpassen** — Knöpfe in der Hover-Zeile einer Karte umsortieren und ein-/ausblenden. Neun Aktionen stehen bereit: Ähnliche finden, Warum diese Bewertung, Metadaten schreiben, Gesicht zuweisen, die Duplikatgruppe, Seriengruppe, Belichtungsreihe/das Panorama oder den Fotostapel öffnen und die Fotoseite öffnen. Gruppenknöpfe erscheinen nur bei Fotos in einer solchen Gruppe. Die Knöpfe für Duplikatgruppe und Fotostapel sind standardmäßig an; die übrigen müssen Sie einschalten. Pro Browser gespeichert.
- **Blinzler ausblenden** — Fotos mit erkanntem Blinzeln ausblenden
- **Nur Blinker / Nur Duplikate** — Nur Fotos mit Blinzeln bzw. jedes Mitglied jeder Duplikatgruppe zeigen. Die Ausblend-Schalter ruhen für diese Ansicht.
- **Nur Abgelehnte anzeigen** — Nur Ihre abgelehnten Fotos auflisten. Bearbeiten Sie sie mit „Alle auswählen“ und **In Ordner aussortieren** oder mit **Alle abgelehnten Fotos in den Papierkorb** im Aussortieren. Beide begrenzen den Filterbereich auf 10.000 Fotos; grenzen Sie für mehr nach Datum oder Album ein und schalten Sie die Gruppen-Ausblendfilter aus, um jede abgelehnte Aufnahme einzubeziehen. Deaktiviert, solange ein Auswahlstatus gewählt ist.
- **Beste aus Serie** — Nur das am höchsten bewertete Foto jedes Serienbilds anzeigen
- **Beste der Belichtungsreihe** — Nur die Basisbelichtung jeder Belichtungsreihe anzeigen. **Standardmäßig an.** Unabhängig von „Beste aus Serie“, da das Serien-Leitfoto einer Reihe nicht immer ihre Basisbelichtung ist.
- **Beste des Panoramas** — Nur das mittlere Bild jedes Panoramas oder HDR-Panoramas anzeigen. **Standardmäßig an.**
- **Endloses Scrollen** — Fotos werden beim Scrollen geladen
- **Schnelles Scrollen (virtualisiert)** — Rendert nur Zeilen nahe dem Sichtbereich, sodass tiefes Scrollen schnell bleibt. Standardmäßig an. Schalten Sie es im Tab „Anzeige“ der Seitenleiste aus, falls Layoutprobleme auftreten. Der Rastermodus mit angezeigten Details rendert stets vollständig. In localStorage gespeichert (`facet_virtual_scroll`).

### Ähnliche Fotos

Klicken Sie bei einem Foto auf **Ähnliche** und wählen Sie einen Modus:

- **Visuell** (Standard) — pHash-Ähnlichkeit (70%) + CLIP/SigLIP-Ähnlichkeit (30%). Teilen zwei Fotos nur eines der beiden Signale, zählt es voll; Fotos ohne eines davon werden nie aufgeführt. Alle Treffer über dem Schwellenwert werden seitenweise geliefert. Hat das Foto keines von beiden, scannen Sie es mit `--force` neu (ein einfaches `python facet.py <dir>` überspringt bereits verarbeitete Dateien).
- **Farbe** — Histogrammschnittmenge (70%) + Sättigungsdistanz (10%) + Helligkeitsdistanz (10%) + Monochrom-Bonus (10%). Vorfilterung nach Monochrom-Flag und Sättigungsbereich.
- **Person** — Fotos mit derselben Person bzw. denselben Personen, über `person_id`, wenn verfügbar, sonst über die Ähnlichkeit der Gesichts-Embeddings.

Der **Ähnlichkeitsschwellen-Regler** (0–90%) legt fest, wie streng der Abgleich ist (nicht im Personenmodus). Die Ergebnisse scrollen endlos.

### Filter-Chips

Aktive Filter erscheinen als entfernbare Chips mit Zählern oben in der Galerie.

### Manuelle Tags

Manuelle Tags sind Tags, die Sie selbst eingeben und die neben den KI-Tags stehen. Sie werden getrennt gespeichert (`photo_manual_tags`, nicht die Spalte `tags` des Fotos), sodass erneute Scans und erneutes Tagging sie nie löschen.

- **Wo sie erscheinen.** Nur in der **Detailansicht**, als Chips, die sich von KI-Tags unterscheiden. Karten und Tooltips zeigen KI-Tags.
- **Wer sie bearbeiten kann.** Benutzer mit Edition. Auf einer Installation ohne `viewer.edition_password` sind sie schreibgeschützt. KI-Tags lassen sich nicht entfernen.
- **Sammelbearbeitung.** Wählen Sie Fotos aus und nutzen Sie **Schlagwörter bearbeiten** (Auswahlleiste, mobiles Aktionsblatt oder Kontextmenü), um ein Tag hinzuzufügen oder zu entfernen. Auswahlen der ganzen Ansicht funktionieren. Fotos mit bereits 50 manuellen Tags werden übersprungen; `count` meldet die tatsächlich geänderten Fotos.
- **Format.** Tags werden getrimmt, kleingeschrieben und von mehrfachem Leerraum befreit (NFC). Höchstens 64 Zeichen, höchstens 50 pro Foto. Leere Tags, Kommas und Steuerzeichen werden abgelehnt. Ein Tag, das einem KI-Tag des Fotos entspricht, wird nicht gespeichert.
- **Suche und Filter erfassen sie.** Der Tag-Filter, die Textsuche, die semantische Suche (`/api/search`, außer dem reinen Bildunterschrift-Bereich), die Tag-Auswahlliste, die Statistiken und die Exporte von Sidecars, eingebetteten Metadaten und Lightroom nutzen KI- plus manuelle Tags. Die Textsuche findet ein manuelles Tag als ganze Wendung.
- **Ausnahmen.** Kapseln zählen nur KI-Tags. Manuelle Tags beeinflussen nie Bewertungen, Kategorien oder narrative Momente.
- **Für Freigabelinks verborgen.** Betrachter über Freigabelinks sehen sie nie. Ein freigegebenes intelligentes Album wendet weiterhin den gespeicherten Filter des Eigentümers an.
- **Von allen Benutzern geteilt.** Im Mehrbenutzermodus kann jeder Benutzer mit Edition ein Tag entfernen, das ein anderer hinzugefügt hat.
- **Nicht rückgängig zu machen.** [Rückgängig](#rückgängig) deckt sie nicht ab. Ein entferntes Tag kann aus einem Sidecar zurückkehren; siehe [Konfliktregeln](INTEROP.md#konfliktregeln).
- **Importierte Tags.** `--import-sidecars` speichert unbekannte Sidecar-Stichwörter (keine KI-Tags, keine Personennamen) als manuelle Tags mit der Quelle `xmp`.
- **An den Dateipfad gebunden.** Eine verschobene oder umbenannte Datei verliert ihre manuellen Tags.

## Panoramen und Belichtungsreihen

Die Aufnahmen eines Panoramas sollen zusammengefügt und die einer Belichtungsreihe verschmolzen werden; sie sind keine konkurrierenden Versionen. Allein die Serienbild-Erkennung würde sie gruppieren und alle bis auf eine ausblenden, daher erkennt Facet diese Sets getrennt.

**In der Galerie.** `Beste der Belichtungsreihe` und `Beste des Panoramas` (beide standardmäßig an) zeigen eine Aufnahme pro Set: die Basisbelichtung einer Reihe, das mittlere Bild eines Panoramas. Diese Aufnahme trägt neben Stern und Herz ein kleines Symbol: einfacher Schwenk, HDR-Schwenk oder Belichtungsreihe. Das Symbol erscheint nur, solange der Schalter den Rest des Sets ausblendet.

**Im Aussortieren.** Das Granularitätsmenü bietet `Belichtungsreihen`, `Panoramen` und `HDR-Panoramen` als eigene Feeds an, nie in `Alle` zusammengeführt. Jede Aufnahme beginnt als behalten, und das Bestätigen eines Sets erfasst keine Vergleichspaare, sodass der Ranker nicht darauf trainiert wird, wie ein Set aufgenommen wurde.

**Ein Set korrigieren.** Die Erkennung liegt bei etwa 4 % der Sets falsch. Korrekturen sind dauerhaft: Sie überstehen jeden späteren Erkennungslauf. Beide erfordern den Bearbeitungsmodus, mindestens zwei Aufnahmen und lassen sich über die Snackbar rückgängig machen.

- **Falsch erkannt** (kein Panorama, oder schlicht vs. HDR): Nutzen Sie das Korrekturmenü in der Aktionsleiste der Gruppe im Aussortieren.
- **Übersehenes Panorama**: Wählen Sie seine Aufnahmen in der Galerie und dann *Als Set markieren* → *Als ein Panorama markieren*.

**Eine übersehene Belichtungsreihe markieren.** Für eine Belichtungsleiter, die als gewöhnliche Serie erkannt wurde:

- In der Dunkelkammer bietet eine einfache Serien-Gruppe (keine Aufnahme gehört schon zu einer Belichtungsreihe oder einem Panorama) *Als Belichtungsreihe markieren*.
- In der Auswahlleiste der Galerie nutzen Sie *Als Set markieren* → *Als eine Belichtungsreihe markieren*.
- Die Aufnahmen müssen eine echte Leiter bilden: mindestens 2 Aufnahmen, jede mit Belichtungsdaten (Blende, Verschlusszeit, ISO) und Aufnahmedatum, und keine zwei mit demselben Belichtungswert. Andernfalls wird die Markierung mit einer Meldung abgelehnt und nichts gespeichert.
- Das Markieren von Aufnahmen, die sich mit einer bereits markierten Belichtungsreihe überschneiden, erweitert sie. Das kombinierte Set muss weiterhin eine gültige Leiter sein.
- Der Dunkelkammer-Feed blendet abgelehnte Aufnahmen aus, daher enthält eine Markierung dort nie eine abgelehnte Sprosse.
- Eine `bracket`-Gruppe bietet stattdessen *Korrektur verwerfen*.
- Verschwindet eine markierte Aufnahme oder verliert ihre Belichtungs- oder Datumsdaten, wartet das ganze Set, bis jedes Mitglied wieder die Voraussetzungen erfüllt.
- **Markieren hat Vorrang vor der Panorama-Erkennung**: Ein erkanntes Panorama, das markierte Aufnahmen enthält, wird beim nächsten Lauf verworfen.

**Korrekturen gelten beim nächsten Erkennungslauf.** Eine Korrektur wird sofort gespeichert und als ausstehend angezeigt: ein Uhr-Abzeichen auf der Galeriekachel, ein Chip *Korrektur ausstehend* im Aussortieren. Die Auswahlseite zeigt ein Banner mit der Schaltfläche **Erkennung erneut ausführen**. Der Filter *Panorama-Korrekturen* der Seitenleiste (nur Edition, im Tab Prüfen) listet ausstehende Korrekturen bibliotheksweit auf. *Korrektur verwerfen* entfernt eine später wieder.

**Einstellen.** Der Tab Panoramen unter Vergleichen enthält die kalibrierten Schwellenwerte: Mindestanzahl Aufnahmen, minimaler Schwenk, längste Lücke und HDR-Belichtungsspanne. Das Speichern ändert nichts, bis Sie die Erkennung erneut ausführen (die Schaltfläche steht neben Speichern). Siehe [CONFIGURATION.md](CONFIGURATION.md#panorama-erkennung).

## Personenverwaltung

> Das Durchsuchen von Personen steht allen Betrachtern offen; Umbenennen, Zusammenführen, Avatar-Änderungen und Gesichtszuweisung erfordern `[Edition]`.

### Personenfilter

Die Auswahlliste zeigt Personen mit Gesichts-Thumbnails. Ein Klick filtert die Galerie.

### Personengalerie

Klicken Sie auf den Namen einer Person, um alle ihre Fotos unter `/person/<id>` zu sehen. Auf der Seite „Personen verwalten“ öffnet ein Doppelklick auf eine Personenkarte (benannt, unbenannt in „Zu benennen“ oder ignoriert) die Galerie mit den Fotos dieser Person; Doppelklicks auf Namensfeld, Kontrollkästchen und Schaltflächen bleiben diesen vorbehalten.

**Aus der Galerie benennen.** Ist die Galerie nach einer Person gefiltert (`?person_id=95`), zeigt deren Chip in der Zeile der aktiven Filter ihr Gesicht und ihren Namen, oder **Unbenannt**, als Hinweis umrandet; sein × (**Aus dem Filter entfernen**) nimmt die Person aus dem Filter. Für Bearbeitungsbenutzer stehen vor dem × zwei Schaltflächen. **Umbenennen** (der Stift) benennt die Person direkt um: Das Namensfeld zeigt „Wer ist das? Namen eingeben oder wählen“ bei einer unbenannten und „Umbenennen oder zusammenführen mit…“ bei einer benannten Person, seine Vorschläge zeigen zu jeder Person Gesicht, Namen und Fotoanzahl, und **Speichern** oder **Abbrechen** schließt es (Escape bricht ebenfalls ab). Der Name wird immer zuerst gespeichert (`POST /api/persons/{id}/rename`); tragen andere Gruppen ihn bereits (Groß-/Kleinschreibung und Leerzeichen werden ignoriert, ob sie unter den Vorschlägen sind oder nicht), bietet der Chip anschließend dieselbe Zusammenführung an wie die Seite „Personen verwalten“ (siehe **Umbenennen** unten), und nach einer Zusammenführung wechselt die Galerie zur verbleibenden Person. **Mehr** (⋮) öffnet das Personenmenü: **Alle Fotos von {name} ansehen**, **Weitere Gesichter von {name} finden** und **Ignorieren** (**Wiederherstellen** bei einer ignorierten Person). Halten die Ausblendoptionen der Galerie einige Fotos der Person verborgen, nennen die Hinweise der Galerie deren Zahl, aufgeschlüsselt nach Serienbild-, Blinzel-, Duplikat-, Belichtungsreihen- und Panoramafotos, damit Sie sie vor dem Benennen einblenden.

### Seite „Personen verwalten“

Im Bearbeitungsmodus hat die Seite zwei Reiter, **Benannt (N)** und **Zu benennen (N)**, und öffnet immer auf **Benannt**. **Zu benennen** listet die unbenannten Cluster, jeweils mit einem Namensfeld; **Benannt** enthält die benannten Personen, mit den ignorierten in einem einklappbaren Abschnitt **Ignoriert** am Ende. Schreibgeschützte Benutzer sehen nur das Raster der benannten Personen. Namensvorschläge zeigen hier wie am Personen-Chip der Galerie und im Gesichtsmenü des Fotos zu jeder Person Gesicht, Namen und Fotoanzahl. Auf **Zu benennen** bietet das Sortiermenü **Gesichteranzahl** und **Neueste**. Ist niemand mehr zu benennen, zeigt der Reiter „Alle sind benannt. Neue Gesichter, die einen Namen brauchen, erscheinen hier.“

Öffnen Sie sie über die Schaltfläche in der Kopfzeile oder `/persons`:

| Aktion | Vorgehen |
|--------|--------|
| **Zusammenführen** | Quellperson wählen, Zielperson anklicken, bestätigen |
| **Löschen** | Auf die Löschen-Schaltfläche der Personenkarte klicken |
| **Umbenennen** | Auf den Namen der Person klicken, um ihn direkt zu bearbeiten. Tragen andere Gruppen den Namen bereits (Groß-/Kleinschreibung und umgebende Leerzeichen ignoriert), zeigt eine Bestätigung je Person eine Kachel (Gesicht, Name, Gesichterzahl), alle ausgewählt, und markiert die Person, die bestehen bleibt: die größte der ausgewählten, die ihre Schreibweise behält. Heben Sie die Auswahl eines Namensvetters auf oder brechen Sie ab, um ihn getrennt zu halten. Eine Zusammenführung lässt sich nicht rückgängig machen |
| **Aufteilen** | Die Gesichter einer Person öffnen, eine Teilmenge wählen und als neue Person abspalten |
| **Weitere Gesichter finden** | Die Suchschaltfläche auf einer Personenkarte oder **Weitere Gesichter von {name} finden** in einem Personenmenü listet Gesichter, die dieser Person ähneln, beste Treffer zuerst, verglichen mit dem Zentroid der Person (`GET /api/person/{id}/possible_faces`). Unter **Welche Gesichter einbeziehen** zeigen drei Chips jeweils ihre Anzahl: **Ohne Gruppe** und **Unbenannte Gruppen**, standardmäßig an, und **Benannte Personen**, aus. Ein Gesicht, das einer benannten Person gehört, trägt ein Abzeichen **von {name}**, und wird eines angehakt, warnt der Dialog, dass Hinzufügen es zu dieser Person verschiebt. Über den Gesichtern listet **Ähnliche Gruppen** andere Cluster, deren Zentroid dem dieser Person ähnelt (die unbenannten, dazu die benannten, solange **Benannte Personen** an ist); jede zeigt ihr Bild, ihren Namen oder **Unbenannte Gruppe**, ihre Gesichterzahl und **{percent} % ähnlich**, mit **Alle zusammenführen**, um die ganze Gruppe in diese Person zu übernehmen. Bei einer benannten Gruppe wird zuerst nachgefragt, und eine Zusammenführung lässt sich nicht rückgängig machen. Jedes Gesicht trägt **Stark** (ab 50 % Ähnlichkeit) oder **Möglich** samt Prozentwert, und **Wie ähnlich** setzt die Schwelle: eine Signalbalken-Schaltfläche mit `≥NN%`, die das Stufenmenü öffnet, mit fünf Stufen, **Sehr streng** 60 %, **Streng** 50 %, **Normal** 35 % (Standard), **Locker** 25 % und **Sehr locker** 20 %. Erfüllt kein Gesicht die Schwelle, zeigt der Dialog „Keine Gesichter ähneln {name} (am nächsten: N %).“ und bietet **Locker versuchen** oder **Benannte Personen einbeziehen** an. Müsste eine Suche zu viele Gesichter vergleichen, durchsucht sie nur Gesichter ohne Gruppe; sind es dann noch zu viele, fragt sie nach einem **Jahr** für die Suche. **Alle starken auswählen**, Umschalt-Klick für einen Bereich und die Leertaste auf einem fokussierten Gesicht beschleunigen das Anhaken; die Schaltfläche Hinzufügen zeigt, wie viele angehakt sind. Das Hinzufügen berechnet den Zentroid neu, sodass die nächste Runde nach dem gerade Bestätigten sortiert wird; nicht angehakte Gesichter werden nicht erneut angeboten, solange der Dialog offen ist |
| **Ignorieren** | Ein Cluster ignorieren (Personal, Fremde): die ⊘-Schaltfläche einer Karte, auch auf „Zu benennen“-Karten. Ignorierte Personen verschwinden aus Liste, „Zu benennen“, Filtern, Zusammenführungsvorschlägen und Gesichtersuche und stehen im einklappbaren Abschnitt **Ignoriert** am Ende des Reiters **Benannt**, mit **Wiederherstellen** (`GET /api/persons?hidden_only=true`). Es nutzt dasselbe `is_hidden`-Flag wie bisher. Ignorieren wirkt sofort und zeigt 10 Sekunden lang eine Benachrichtigung mit **Rückgängig**, hier und in jedem Personenmenü. |

### Gesichter auf dem Foto

In der Fotoansicht erscheint ein Rahmen um jedes erkannte Gesicht, solange der Zeiger über dem Foto ist; beim Überfahren eines Gesichts erscheint dessen Name (roter Rahmen: noch unbenannt). Die Rahmen folgen Zoom und Verschieben, und Ziehen oder Doppelklicken auf einem Gesicht verschiebt weiterhin bzw. setzt den Zoom zurück. Der Rahmen eines unbenannten Gesichts ist zusätzlich gestrichelt, damit er nicht allein über die Farbe erkennbar ist, und jeder Rahmen hat eine dunkle Kontur, damit er auf jedem Hintergrund sichtbar bleibt. Sofern die Rahmen nicht auf **Aus** stehen, wechseln Sie mit der Tastatur per Tab zwischen den Gesichtern, die jeweils mit ihrem Namen (oder als unbekanntes Gesicht) angesagt werden, und öffnen mit Eingabe oder Leertaste deren Menü. Auf einem Touchscreen öffnet ein Tippen das Menü eines Gesichts nur, während die Rahmen angezeigt werden (die Rahmen stehen auf **Immer**, oder, sofern sie nicht auf **Aus** stehen, das Gesicht gehört der Person, auf die die Galerie gefiltert ist); sonst bewirkt ein Tippen auf das Foto beim Gesicht nichts. Im Bearbeitungsmodus öffnet ein Klick auf ein Gesicht ein Menü: **Person ändern…** (oder **Dieses Gesicht benennen…**), um eine vorhandene Person zu wählen oder einen neuen Namen einzugeben, **Weitere Gesichter von … finden** für diese Person und **Nicht …**, um genau dieses Gesicht von der Person zu lösen (`POST /api/face/{id}/unassign`); ihre übrigen Gesichter im Foto bleiben ihr zugeordnet. Gesichter, deren gespeicherte Abmessungen nicht vertrauenswürdig sind, werden nicht gezeichnet. Die Rahmen stammen aus `GET /api/photo/faces`, das für jedes Gesicht ein auf das Bild normiertes `box` liefert. Jedes Gesicht, das zu einer Person gehört, ob benannt oder nicht, bietet außerdem **Alle Fotos von … ansehen** (oder **Alle Fotos dieser Gruppe ansehen**), das die Galerie auf diese Person gefiltert öffnet; das funktioniert auch schreibgeschützt. Eine Schaltfläche in der Werkzeugleiste schaltet die Gesichtsrahmen reihum durch drei Zustände, pro Browser gespeichert: **Aus** (keine Rahmen, Gesichter lassen sich weder anklicken noch fokussieren), **Beim Überfahren** (die Voreinstellung, wie oben beschrieben) und **Immer** (alle Rahmen und Namen bleiben sichtbar). Ist die Galerie auf eine Person gefiltert, bleiben deren Gesichter mit dickerer Linie umrahmt, außer die Rahmen stehen auf **Aus**. **Als Bild von … verwenden** macht das angeklickte Gesicht zum Kartenbild; eine Person, die Gesichter ohne Bild erhält, bekommt automatisch das sicherste. Ist die Galerie auf eine Person gefiltert, umrahmt jedes Vorschaubild deren Gesicht rot, damit vor dem Benennen klar ist, welches Gesicht ein Cluster meint. Ein Klick auf den Avatar einer Person in der Liste **Personen** der rechten Leiste öffnet dasselbe Menü wie ein Klick auf den Rahmen dieses Gesichts, auch wenn die Rahmen auf **Aus** stehen; **Alle Fotos von … ansehen** in diesem Menü öffnet die Galerie.

### Ein übersehenes Gesicht markieren

Öffnen Sie im Bearbeitungsmodus ein Foto und wählen Sie **Fehlendes Gesicht markieren**, auch wenn keine Gesichter erkannt wurden. Zeichnen Sie ein Rechteck (oder geben Sie die Koordinaten ein), wählen Sie eine bestehende Person oder geben Sie einen neuen Namen ein und wählen Sie dann **Speichern**. Abbrechen speichert nichts.

Beim Speichern, Bearbeiten oder Entfernen eines manuellen Gesichts werden die Gesichtsrahmen und Personen aktualisiert, ohne das Foto erneut zu öffnen.

- Mit demselben Editor passen Sie eine manuelle Markierung an, weisen sie neu zu oder entfernen sie.
- Manuelle Markierungen bleiben über erneute Scans und die Viewer-Synchronisierung mit ihrer Person verknüpft. Sie trainieren die Erkennung nicht und ändern keine Gesichtsqualitätswerte.
- Der Editor arbeitet mit dem Originalbild, sodass RAW- und gedrehte Fotos passen. Ohne das Original können Sie Markierungen auflisten und entfernen, aber nicht zeichnen.
- Eine Markierung, die sich nicht verifizieren lässt, erscheint als **Prüfung nötig**. Markierungen aus früheren Vorschau-Builds brauchen eine Prüfung: Öffnen Sie das Original, bearbeiten Sie die Markierung und speichern Sie sie.
- Ein ersetztes Bild kennzeichnet seine Markierungen. Eine feine Retusche oder ein kleiner Neuzuschnitt gleicher Größe bleibt womöglich unbemerkt. Metadaten-Schreibvorgänge, erneutes Einhängen und andere Hosts halten Markierungen aktuell.
- Der Editor verwendet einen dekodierten Frame von bis zu 128 MiB wieder; größere Frames brauchen womöglich eine erneute Dekodierung. Das Limit ist fest.
- Gelöschte Markierungen bleiben bei späteren Synchronisierungen gelöscht.
- Änderungen liegen in der Bibliotheksdatenbank; Originale und Sidecars werden nicht berührt.

> **Warnung:** Ein erzwungener Neuaufbau der Viewer-Datenbank ersetzt reine Viewer-Änderungen, manuelle Markierungen eingeschlossen, durch die Quelldatenbank. Exportieren oder sichern Sie sie zuvor. Die normale inkrementelle Synchronisierung bewahrt sie.

Die veraltete Einstellung `viewer.performance.face_cache_size` wird ignoriert und kann entfernt werden.

## Scan auslösen

Starten Sie einen Scan im Browser. Die Scan-Schaltfläche erscheint, wenn **beides** zutrifft:

- `viewer.features.show_scan_button` ist `true` (ausgeliefert mit **`false`**).
- Sie haben Scan-Zugriff: die Rolle `superadmin` im Mehrbenutzermodus oder eine Bearbeitungssitzung bei einer Einzelbenutzer-Installation mit nicht leerem `viewer.edition_password`.

Auf einer offenen Einzelbenutzer-Installation (leeres `viewer.edition_password`, der Standard) kann niemand im Browser scannen. Ausnahme: Unter `viewer.trusted_local_editing` kann eine vertrauenswürdige lokale Browsersitzung oder ein lokaler Assistent mit Token für volle Bearbeitung ohne `show_scan_button` oder Bearbeitungspasswort scannen.

Die Schaltfläche sitzt in der leeren Galerie (**Fotos scannen, um zu beginnen**) und am Ende der Kopfzeile (**Nach neuen Fotos suchen**; untere Leiste auf kleinen Bildschirmen). Beide öffnen den Scan-Starter:

- Wählen Sie ein Verzeichnis aus der Liste und starten Sie den Scan.
- Live-Fortschritt und Ausgabezeilen erscheinen im Dialog. Die Galerie aktualisiert sich, wenn der Scan endet.
- Der Scan führt `facet.py` im Hintergrund aus; es läuft jeweils nur ein Scan.
- Die Verzeichnisliste kombiniert die `directories` jedes Benutzers, geteilte Verzeichnisse, `path_mapping`-Ziele und `viewer.scan_directories`. Füllen Sie `viewer.scan_directories` (z. B. `/data/photos`), damit Einzelbenutzer- und Docker-Installationen ein Ziel haben.

Es ist keine GPU nötig — siehe [Welches Profil passt zu meiner Hardware?](INSTALLATION.md#welches-profil-passt-zu-meiner-hardware) und [Keine Grafikkarte](INSTALLATION.md#keine-grafikkarte). Der Scan läuft auf dem Rechner des Viewers und ist daher am schnellsten, wenn dieser eine GPU hat.

Um vorhandene Fotos ohne Scan neuer Dateien neu zu bewerten, nutzen Sie `POST /api/scan/recompute` (nur Edition) — siehe [Kategoriepriorität & Bewertungskontexte](#kategoriepriorität--bewertungskontexte).

## Semantische Suche

Geben Sie eine Anfrage wie „Sonnenuntergang über Bergen“ ein und erhalten Sie passende Fotos. Die Rangfolge mischt die Ähnlichkeit der CLIP/SigLIP-Embeddings (70 %) mit FTS5-BM25-Textabgleich auf Bildunterschriften und Tags (30 %).

- **Voraussetzungen.** Fotos brauchen gespeicherte `clip_embedding`-Daten (beim Bewerten berechnet). Führen Sie `database.py --rebuild-fts` aus, um den Text-Teil für Bildunterschriften/Tags zu aktivieren.
- **Modell.** Verwendet das Embedding-Modell des aktiven VRAM-Profils (SigLIP 2 für 16gb/24gb, CLIP ViT-L-14 für legacy/8gb) oder dasjenige von `models.clip`/`clip_legacy`, das zu den gespeicherten Embeddings passt (siehe [CONFIGURATION.md](CONFIGURATION.md)).
- **Geschwindigkeit.** Die Installation von sqlite-vec beschleunigt die Suche; sonst hält Facet eine Matrix im Arbeitsspeicher. Die erste Anfrage bei einer großen Bibliothek kann einige Sekunden dauern.
- **Schwellenwert.** Der Trefferschwellenwert ist standardmäßig `models.clip.search_threshold_percent` (`5%`) bzw. `models.clip_legacy.search_threshold_percent` (15%), getrennt von `tag_threshold_percent`. Der Galerie-Regler reicht von 0–50 %; `search_threshold_default` aus `/api/config` legt seinen Start fest. Selbst `0%` lehnt negative Ähnlichkeit ab. Der SigLIP-Standard von 5 % bevorzugt den Recall — siehe `clip.search_threshold_percent` in [CONFIGURATION.md](CONFIGURATION.md).
- **Nur Text.** `scope=text` beschränkt die Anfrage auf wörtliche FTS5-Treffer in OCR-/Bildunterschrifttext.
- **Funktioniert mit jedem Galeriefilter**, den Ausblend-Schaltern eingeschlossen. Mit den Standardwerten bleiben ausgeblendete Serien-, Duplikat-, Belichtungsreihen- und Panoramamitglieder, Blinzler und Abgelehnte ausgeblendet.
- **Keine Ergebnisobergrenze.** Die Galerie blättert die Ergebnisse seitenweise und zeigt die tatsächliche Gesamtzahl.
- **Relevanz-Sortierung.** Bei aktiver Anfrage ist **Relevanz** (bester Treffer zuerst) die Standardsortierung. Das Leeren der Anfrage stellt die Standardsortierung wieder her.
- **Auswahl.** „Alle auswählen“ umfasst nur die geladenen Fotos; die Auswahl der ganzen Ansicht ist hier nicht verfügbar.
- Gesteuert über `viewer.features.show_semantic_search` (Standard: `true`).

Ergebnisse melden `similarity` (die gemischte Wertung) und `embedding_similarity` (der rohe Kosinus, der gegen den Schwellenwert geprüft wird; bei reinen Texttreffern nicht vorhanden). Die Galerieparameter `semantic_q`, `semantic_threshold` und `sort=relevance` sind in [API.md](../API.md) dokumentiert.

## Alben

Organisieren Sie Fotos in benannten Alben unter `/albums`. Gesteuert über `viewer.features.show_albums` (Standard: `true`).

### Manuelle Alben

Erstellen Sie Alben und fügen Sie Fotos aus der Galerie per Mehrfachauswahl hinzu. Alben unterstützen:
- Name und Beschreibung
- Eigenes Titelbild
- Eigene Reihenfolge
- Albuminhalt unter `/album/:albumId` durchsuchen

### Intelligente Alben

Speichern Sie eine Filterkombination (Kamera, Tag, Person, Daten, Wertungsschwellen…) als intelligentes Album. Es aktualisiert sich, sobald neue Fotos passen. Die Filter werden als JSON in `smart_filter_json` gespeichert.

### Bewertungskontext

Ein Album kann einen Bewertungskontext tragen, der unabhängig von der globalen Priorität entscheidet, welche Kategorie für seine Fotos gewinnt — siehe [Bewertungskontexte](CONFIGURATION.md#bewertungskontexte). Legen Sie ihn im Dialog des Albums fest (Bearbeitungsmodus).

- Das Festlegen stempelt den Kontext auf die **aktuellen** Mitglieder des Albums. Ein Foto mit eigener manueller Überschreibung bleibt unberührt.
- Die Mitglieder eines intelligenten Albums stammen aus seinem gespeicherten Filter und ignorieren die Ausblend-Schalter der Galerie, daher kann die Zahl höher sein als die der Albumansicht.
- Fotos, die später zu einem manuellen Album hinzukommen, erben den Kontext. Neue Treffer eines intelligenten Albums nicht; legen Sie den Kontext erneut fest.
- **Kontext löschen** (nicht dasselbe wie die Wahl von `default`) entfernt den Stempel. Ein Foto, das noch in einem anderen Album mit Kontext liegt, erhält stattdessen diesen Kontext.
- Facet kann einen Kontext anhand des vorherrschenden narrativen Moments des Albums vorschlagen (über `suggest_from_moments` jedes Kontexts). Es schreibt nichts, bis Sie bestätigen.
- Führen Sie eine Neuberechnung aus (`POST /api/scan/recompute`), damit der neue Kontext gespeicherte Kategorien ändert.

Endpunkte und Antwortzähler: [API.md](../API.md#albums).

### Portfolio-Export

Verwandeln Sie ein manuelles Album in eine eigenständige statische HTML-Galerie. Ist `viewer.features.show_portfolio_export` an (Standard `true`) und Edition freigeschaltet, hat jede Karte eines manuellen Albums **Portfolio exportieren**. Wählen Sie Titel, Zielordner und ob Bildunterschriften enthalten sein sollen.

- Die Ausgabe enthält `index.html` (ein Vorschaubildraster mit eingebauter Lightbox, ohne externe oder CDN-Verweise, funktioniert offline), einen Ordner `assets/` mit fortlaufend benannten JPEGs (keine Bibliothekspfade preisgegeben) und eine `manifest.json`.
- Jedes Foto nutzt das Original, verkleinert auf `portfolio.max_edge`, oder das gespeicherte 640px-Vorschaubild, falls das Original nicht erreichbar ist.
- Der Zielordner muss in der Export-Positivliste stehen (`viewer.export.allowed_target_dirs` plus Scan-Verzeichnisse, siehe [Konfiguration — Ziele für Export und Aussortierung](CONFIGURATION.md#ziele-für-export-und-aussortierung)).
- Alben mit mehr als `portfolio.max_photos` Fotos (Standard 500) werden abgelehnt.
- Ein erneuter Export überschreibt nur die eigenen Dateien des Exports.

Siehe [Konfiguration des Portfolio-Exports](CONFIGURATION.md#portfolio-export). Endpunkt: `POST /api/albums/{album_id}/export-portfolio`.

### Fotofreigabe

Geben Sie Alben über tokenisierte Links frei. Das Ansehen eines freigegebenen Albums erfordert keine Anmeldung.

| Aktion | Vorgehen |
|--------|--------|
| **Freigeben** | Album öffnen, auf „Freigeben“ klicken, um einen Freigabelink zu erzeugen |
| **Widerrufen** | Auf „Freigabe aufheben“ klicken, um das Freigabe-Token ungültig zu machen |
| **Ansehen** | Empfänger öffnen den Link, um das freigegebene Album unter `/shared/album/:id` zu durchsuchen |

### Client-Proofing

Lassen Sie einen Kunden Favoriten aus einer Lieferung wählen. Ist `viewer.features.show_proofing` an (Standard `false`), kann ein Freigabelink im **Proofing-Modus** laufen: Der Kunde öffnet ihn, gibt eine PIN ein, falls gesetzt (`viewer.proofing.pin`), und vergibt dann **Herzen** und hinterlässt **Kommentare**.

- Kundenauswahlen werden getrennt gespeichert (`album_client_picks`) und berühren nie Ihre Favoriten oder Bewertungen und trainieren den Ranker nicht.
- Lesen Sie die Auswahlen in einem `[Edition]`-Dialog auf der Albumkarte.
- Sitzungen dauern `viewer.proofing.session_minutes` (Standard 24 h) und enden, wenn die Freigabe des Albums aufgehoben oder das Proofing ausgeschaltet wird.

Siehe [Konfiguration — Client-Proofing](CONFIGURATION.md#client-proofing).

## KI-Kritik

Erklärt die Wertung eines Fotos als Stärken, Schwächen und Verbesserungsvorschläge. Gesteuert über `viewer.features.show_critique` (Standard: `true`).

### Regelbasierte Kritik

Auf jedem VRAM-Profil verfügbar. Facet berechnet die Wertung aus den gespeicherten Metriken des Fotos und der aktuellen Konfiguration neu und zeigt die Berechnung.

- Die **Kategorie** ist diejenige, die die aktuelle Formel zuweist (mit Berücksichtigung einer Kategorieüberschreibung und eines Bewertungskontexts). Sie kann bis zum nächsten `--recompute-average` von der gespeicherten Kategorie abweichen.
- **Aufschlüsselungszeilen** zeigen jeden 0–10-Eingangswert, den die Bewertung gewichtet (höher ist besser, daher lesen sich Rauschen und Dynamikumfang als Qualität), mit Gewicht und Beitrag.
- **Netto-Anpassungen und Rundung** (Bonus, Blinzel-Multiplikator, Clipping-, Rausch- und Übersättigungsabzüge, Begrenzung) gleichen die Zeilen mit der Summe der **Aktuellen Berechnung** ab, die neben der **Gespeicherten Wertung** steht.
- **Erkannte Bedingungen** listet Blinzeln und einen Hautton-Stich auf.
- Schärfe, Farbe und Augenschärfe nutzen den Perzentil-Snapshot des letzten `--recompute-average`. Eine Bibliothek, die nur gescannt wurde, verwendet die Werte des Scans.
- **Beratende Zeilen**, nur wenn berechnet: Form und Farbharmonie (Symmetrie, Balance, Kantenorientierungs-Entropie, fraktale Komplexität, Matsuda-Farbharmonie; `--recompute-form`), Verzerrungs-Chips (Bewegungsunschärfe, Farbstich, Überschärfung…; `--recompute-distortions`) und ein Hautton-Hinweis für Porträts (`--recompute-skin-tone`). Sie erklären das Foto, ändern aber den Gesamtwert nicht.

Ist die Berechnung nicht verfügbar, wird nur die gespeicherte Wertung samt Abhilfe gezeigt:

| Grund | Abhilfe |
|--------|-----|
| Veraltetes Schema | `python database.py` |
| Normalisierungs-Snapshot nicht verfügbar | Erneut versuchen, dann `python facet.py --recompute-average` |
| Ungültige gespeicherte Metriken | Mit `--force` neu scannen |

Der Dialog unterscheidet außerdem ein Foto, das *noch nicht bewertet* ist, von einem, dessen *gespeicherte Wertung unbrauchbar* ist.

### VLM-Kritik `[GPU]` `[16gb/24gb]`

Nutzt das konfigurierte VLM (Qwen3.5-2B oder Qwen3.5-4B) für eine kontextbezogene Kritik. Erfordert das Profil 16gb oder 24gb, `viewer.features.show_vlm_critique` auf `true` (der Standard) und eine Bearbeitungssitzung zum Erzeugen. Ohne Edition wird nur eine zwischengespeicherte Kritik gezeigt, und `vlm_available` ist `false`. Der Dialog erzeugt über `POST /api/critique/vlm` (nur Edition; gleichzeitige Anfragen für ein Foto teilen sich eine einzige Erzeugung); `GET /api/critique` liest nur den Cache und erzeugt, übersetzt oder schreibt nie.

- Der Prompt (`critique.vlm`) enthält die Wertungsaufschlüsselung, gespeicherte und neu berechnete Wertungen, erkannte Bedingungen und EXIF.
- Die Antwort lautet **Beobachtung / Bewertung / Vorschläge**. Sie wird pro Foto zwischengespeichert (`photos.vlm_critique`), übersetzt, wenn eine Bearbeitungssitzung sie in der Zielsprache öffnet (dann gespeichert und danach unverändert ausgeliefert), und **Neu erzeugen** berechnet sie neu. Ohne Bearbeitungssitzung sehen Sie den unübersetzten Text, es sei denn, es liegt bereits eine gespeicherte Übersetzung vor.
- Sie läuft auf dem gespeicherten Vorschaubild, daher funktionieren RAW-Dateien.

**Visuelles „Warum diese Bewertung“-Overlay.** Ist `viewer.features.show_saliency_overlay` an (Standard `true`), hat der Kritikdialog **Overlay anzeigen**. Es zeichnet die BiRefNet-Salienzkarte als Heatmap (`GET /api/saliency_overlay`) sowie Gesichtsrahmen und Augenmarker aus gespeicherten Landmarken (`GET /api/photo/face_markers`). Rahmen sind grün bei offenen Augen, bernsteinfarben bei einem Blinzeln. Die Heatmap hat Vorschaubild-Auflösung und ist daher ungefähr. Der Schalter ist bei Profilen ausgeblendet, die keine Salienzmaske erzeugen können.

## KI-Bildbeschreibung `[GPU]` `[16gb/24gb]` `[Edition]`

Erhalten Sie für jedes Foto eine Bildunterschrift in natürlicher Sprache. Eine Bearbeitungssitzung erzeugt sie bei der ersten Anfrage; danach liegt sie in der Spalte `caption` im Cache. Bearbeiten Sie Bildunterschriften in der Fotodetailansicht (Bearbeitungsmodus). Eine offene, schreibgeschützte Installation erzeugt nie eine. `POST /api/caption` erzeugt (und übersetzt) sie; `GET /api/caption` liefert nur die gespeicherte Bildunterschrift oder Übersetzung und erzeugt, übersetzt oder schreibt nie.

Massenerzeugung und Übersetzung über die CLI:

```bash
python facet.py --generate-captions      # Bildunterschriften für alle Fotos ohne erzeugen
python facet.py --translate-captions     # Bildunterschriften in die konfigurierte Zielsprache übersetzen
```

Die Übersetzung nutzt MarianMT auf der CPU (keine GPU nötig). Legen Sie die Sprache mit `translation.target_language` fest (Standard: `"fr"`). Unterstützt: Französisch, Deutsch, Spanisch, Italienisch.

Gesteuert über `viewer.features.show_captions` (Standard: `true`). Ohne das Profil 16gb/24gb oder ein entferntes `vlm_backend` ist die Schaltfläche „Bildunterschrift erzeugen“ ausgeblendet, und Kritiken bleiben regelbasiert.

## Erinnerungen ("Heute vor Jahren")

Sehen Sie Fotos, die an einem heutigen Datum in früheren Jahren aufgenommen wurden. Erinnerungen öffnet eine zufällig gemischte Vollbild-Diashow.

Gesteuert über `viewer.features.show_memories` (Standard: `true`).

## Häufige Arbeitsabläufe

- **Einen Urlaub aussortieren** — Öffnen Sie Kapseln und suchen Sie die `journey`-Kapsel der Reise. Jede Kapsel lässt sich als Album speichern.
- **Tag für Tag sichten** — Öffnen Sie die Zeitleiste und gehen Sie über Jahre → Monate → Tage in die Tiefe. Ein Klick auf einen Tag öffnet die darauf gefilterte Galerie.
- **Ausgeblendetes zeigen** — Die Galerie blendet standardmäßig Blinzler sowie Serien- und Duplikatmitglieder ohne Leitbild aus. Ist etwas ausgeblendet, erscheint unten rechts der Hinweis „N Fotos durch aktuelle Filter ausgeblendet · Alle anzeigen“.
- **Zu Ihren Filtern zurückkehren** — Das Fotos-Symbol der Kopfzeile führt zur Galerie mit den Filtern, der Sortierung und der Position zurück, die Sie verlassen haben. Doppeltippen Sie darauf oder setzen Sie die Filter zurück, um mit den Standardwerten zu beginnen.

## Zeitleisten-Ansicht

Durchsuchen Sie chronologisch: Jahre führen zu Monaten, dann zu einem Kalender der Tage. Jede Kachel zeigt eine Fotozahl und ein Titelfoto. Ein Klick auf einen Tag öffnet die auf dieses Datum gefilterte Galerie; sortieren Sie dort.

Die fünf Ausblend-Schalter der Galerie (`hide_blinks`, `hide_bursts`, `hide_duplicates`, `hide_brackets`, `hide_panoramas`) gelten und stehen standardmäßig auf `viewer.defaults`, sodass die Kachelzahlen mit der Galerie übereinstimmen. Ist etwas ausgeblendet, erscheint in der Symbolleiste eine `visibility_off`-Schaltfläche („Einige Fotos sind durch Ihre Filter ausgeblendet“); ein Klick setzt alle fünf zurück.

Öffnen Sie `/timeline`. Gesteuert über `viewer.features.show_timeline` (Standard: `true`).

## Kartenansicht

Sehen Sie Fotos auf einer interaktiven Leaflet-Karte, nach Zoomstufe gruppiert, anhand ihrer EXIF-GPS-Koordinaten.

### Einrichtung

GPS-Koordinaten aus vorhandenen Fotos extrahieren:

```bash
python facet.py --extract-gps    # GPS-Breite/Länge aus EXIF in die Datenbank extrahieren
```

Neue Fotos erhalten ihre Koordinaten beim Bewerten.

Öffnen Sie `/map`. Gesteuert über `viewer.features.show_map` (Standard: `true`). Kartenhintergründe stammen von OpenStreetMap und benötigen eine Internetverbindung, auch in der installierten App.

### Gespeicherte Orte und manuelles GPS

**Fotos ohne Ort finden.** Öffnen Sie in den Filtern **Ort** und aktivieren Sie **Keine Geolokalisierung**. Das lässt sich in einem intelligenten Album speichern. Es schaltet sich aus, wenn Sie eine semantische/Ähnlichkeitssuche starten oder einen Kartenradius wählen.

**Den Ort eines Fotos festlegen.** Öffnen Sie im Bearbeitungsmodus bei einem Foto **Ort hinzufügen** oder **Ort bearbeiten**. Suchen Sie unter **Gespeicherte Orte**, wählen Sie einen **Letzten Ort**, setzen Sie eine Nadel oder geben Sie Koordinaten ein. **Speichern** wendet ihn an.

**Viele auf einmal festlegen.** Wählen Sie Fotos aus und wählen Sie **Ort festlegen** (Auswahlleiste, mobile Aktionen oder Kontextmenü).

- **Nur Fotos ohne Ort** ist standardmäßig an; schalten Sie es aus, um vorhandene Orte zu ersetzen.
- **Ortsänderungen vorab anzeigen** zeigt, wie viele geändert oder übersprungen werden. Ändert sich dazwischen etwas, zeigen Sie erneut vorab an.
- Bis zu 1000 sichtbare Fotos pro Stapel, Auswahlen der ganzen Ansicht eingeschlossen.

**Gespeicherte Orte.** Wählen Sie einen Punkt und nutzen Sie **Diesen Ort speichern** mit einem Namen (z. B. „Arbeit“), oder setzen Sie ein Lesezeichen auf den Punkt eines mit Geodaten versehenen Fotos. Benennen Sie in der Liste um oder löschen Sie; bereits zugewiesene Fotos verschiebt das nicht. Jeder Editor hat eine private Liste: bis zu 100 gespeicherte Orte und 20 letzte Punkte.

**Manuelle Orte bleiben.** Ein im Viewer gesetzter Ort übersteht erneute Scans und die erneute EXIF-Extraktion, auch ein gelöschter. **Ort der Datei verwenden** verwirft die Überschreibung und liest das GPS der Datei neu ein (oder löscht es, falls die Datei keines hat).

**In Dateien schreiben.** Das Speichern schreibt nie in die Bilddatei. Ein ausdrücklicher Metadatenexport schreibt manuelle Orte (und ausdrückliche Löschungen) in die XMP-Sidecar: im Viewer oder mit `--export-sidecars`. Das Einbetten (**Metadaten in Datei schreiben** oder `--embed-originals`) schreibt außerdem EXIF-GPS in unterstützte Originale. Siehe [INTEROP](INTEROP.md).

### Online-Ortssuche

Nutzen Sie **Adresse oder Geschäft → Online suchen**, um einen Ort über Photon (OpenStreetMap-Daten, © OpenStreetMap-Mitwirkende) nachzuschlagen. Die Anfrage wird nur gesendet, wenn Sie auf **Online suchen** klicken oder Enter drücken. Wählen Sie ein Ergebnis für die Vorschau und dann **Speichern**. Gespeicherte Orte und Koordinaten funktionieren offline.

- `viewer.place_search_url` (Standard `https://photon.komoot.io/api`) verweist auf den Anbieter. Nutzen Sie ein selbst gehostetes Photon oder `""`, um die Suche zu deaktivieren.
- Die öffentliche Demo hat keine Verfügbarkeitsgarantie. Verwenden Sie damit einen Viewer-Worker, da jeder Worker sein eigenes Ratenlimit hat.
- Anfragen umfassen 3–200 Unicode-Codepunkte und liefern bis zu fünf Ergebnisse innerhalb von fünf Sekunden, in einer Antwort von höchstens 64 KiB. Ergebnisbezeichnungen sind auf 600 Unicode-Zeichen begrenzt.
- Ein Cache pro Prozess hält 128 Suchen 15 Minuten lang. Im Mehrbenutzermodus sieht jedes Konto nur seine eigenen Einträge, aber die Kapazität von 128 Einträgen und die Drosselung beim Anbieter werden im ganzen Prozess geteilt.
- Facet wartet zwischen Anbieteraufrufen mindestens eine Sekunde und sendet nie zwei gleichzeitig.
- Facet protokolliert keine Anfragen. Konfigurieren Sie Ihren Reverse-Proxy so, dass er keine Query-Strings protokolliert.

## Kapseln

Thematische Diashows, nach Thema, Ort, Personen und Zeit gruppiert. Öffnen Sie `/capsules` und klicken Sie auf eine Kapsel, um sie abzuspielen.

### Kapseltypen

Facet erzeugt Kapseln aus Ihrer Bibliothek:

- **Reise** — per GPS-Clustering erkannte Reisen, mit rückwärts geocodierten Zielnamen („Reise nach Rom — März 2025“)
- **Momente mit [Person]** — die besten Fotos jeder erkannten Person
- **Saisonale Palette** — nach Jahreszeit + Jahr gruppierte Fotos
- **Goldene Sammlung** — die besten 1 % nach Gesamtwertung
- **Farbgeschichte** — visuell ähnliche Gruppen per CLIP-Embedding-Clustering
- **Diese Woche, vor Jahren** — erweitertes „Heute vor Jahren“ über ±3 Tage
- **Ort** — mit Geodaten versehene Fotocluster mit Ortsnamen
- **Favoriten** — Favoriten, nach Jahr und Jahreszeit gruppiert
- **Dimensionsbasiert** — nach Kamera, Objektiv, Kategorie, Kompositionsmuster, Brennweitenbereich, Tageszeit, Sternebewertung und Kombinationen

### Slideshow

Klicken Sie auf eine Kapselkarte, um eine Diashow zu starten:
- **Thematische Übergänge** — Slide (Reisen), Zoom (Porträts), Kenburns (golden/saisonal), Überblendung (Standard)
- **Automatische Verkettung** — Endet eine Kapsel, zeigt eine Karte die nächste vorab
- **Mischen & Fortsetzen** — Fotos werden gemischt; Ihre Position wird pro Kapsel gemerkt
- **Adaptive Gruppierung** — Hochformatfotos werden nebeneinander gezeigt, um den Bildschirm zu füllen
- **Als Album speichern** — Jede Kapsel als Album behalten

### Aktualität

Kapseln rotieren nach einem Zeitplan (Standard: 24 Stunden). **Neu erzeugen** in der Kopfzeile aktualisiert sie sofort.

### Umgekehrte Geocodierung

Orts- und Reisekapseln zeigen Ortsnamen (z. B. „Paris, Frankreich“) über das Offline-Paket `reverse_geocoder`. Keine API-Aufrufe; die Ergebnisse werden in der Datenbank zwischengespeichert.

Installation: `pip install reverse_geocoder`

### Konfiguration

Alle Einstellungen siehe [Konfiguration — Kapseln](CONFIGURATION.md#capsules).

## Ordner-Ansicht

Durchsuchen Sie nach Verzeichnis unter `/folders`.

- Brotkrumen führen den Baum nach oben.
- Jeder Ordner zeigt sein am höchsten bewertetes Foto als Titelbild.
- Klicken Sie auf einen Ordner, um ihn zu öffnen, oder auf ein Foto, um es in der Galerie zu öffnen.
- Jede Ordnerkarte hat eine Filteraktion, die die Galerie auf diesen Ordner beschränkt öffnet.
- Im Mehrbenutzermodus sehen Sie nur Ihre Verzeichnisse.

### Ordnerfilter

Der Abschnitt **Ordner** der Filter-Seitenleiste hat **Ordner wählen…**, eine Auswahl, die den Baum durchläuft. Das Anwenden beschränkt die Galerie auf diesen Ordner **und seine Unterordner**. Er erscheint als Chip, lässt sich mit anderen Filtern kombinieren, übersteht ein Neuladen (URL-Parameter `path_prefix`) und wird in intelligenten Alben gespeichert.

Er grenzt nur das Fotoraster ein. Auswahllisten der Seitenleiste, Typzähler, Statistiken, Zeitleiste, Karte und Suche bleiben bibliotheksweit.

## GPS-Filterdialog

Filtern Sie Fotos nach Ort mit einer Kartenauswahl:

- Klicken Sie auf die Ortsfilter-Schaltfläche, um die Karte zu öffnen.
- Klicken oder ziehen Sie, um einen Mittelpunkt zu setzen.
- Passen Sie den Radius-Regler an.
- Fotos innerhalb des Radius erscheinen in der Galerie.
- Erfordert GPS-Koordinaten (führen Sie `--extract-gps` aus, wenn Fotos EXIF-GPS-Daten haben).

## Zusammenführungsvorschläge

Finden Sie Personen-Cluster, die dieselbe Person sein könnten. Öffnen Sie `/merge-suggestions` oder gehen Sie über die Seite „Personen verwalten“.

- **Ähnlichkeitsschwellen-Regler** — niedriger zeigt mehr Vorschläge, höher weniger
- **Zusammenführen** — einen Vorschlag annehmen
- **Sammel-Zusammenführung** — mehrere Vorschläge auf einmal zusammenführen
- Verworfene Vorschläge werden nicht erneut vorgeschlagen
- CLI: `python facet.py --suggest-person-merges`

## Editor-Export

Schreiben Sie Bewertungen, Favoriten und Ablehnungen in XMP-Sidecars, damit darktable, Lightroom und andere Editoren sie übernehmen. Erfordert den Bearbeitungsmodus.

- **Aus der Galerie** — Fotos auswählen, dann schreibt **Aktionen → Exportieren** neben jede Datei eine Sidecar.
- **Aus einem Album** — Exportieren Sie das ganze Album als Sidecars oder kopieren/verlinken Sie seine Dateien in einen Ordner (dieselbe Positivliste wie bei [In Ordner aussortieren](#in-ordner-aussortieren)). Alben verwenden ihre gespeicherte Mitgliedschaft, intelligente Alben eingeschlossen.
- **Metadaten in Datei schreiben** — In der Fotodetailansicht bettet es Bewertung und Stichwörter in das Original ein (JPEG/HEIC/TIFF/PNG/DNG über exiftool) und schreibt zusätzlich die Sidecar. Proprietäre RAW-Dateien werden nie verändert. Gesteuert über `viewer.features.show_embed_metadata` (Standard: `true`).
- **Lightroom** (Bearbeitungsmodus) — **Lightroom-Manifest herunterladen** speichert `facet_manifest.json` für die Auswahl des Dialogs, für den Schritt **Facet: Apply ratings and flags...** von `facet.lrplugin`. **Lightroom-Status importieren…** liest die `facet_lightroom_state.json` aus dem Menü **Facet: Export Lightroom State to Facet...** des Zusatzmoduls (Lightroom gewinnt bei Bewertung und Pick/Ablehnung) und meldet die Zähler für zugeordnet/nicht zugeordnet/geändert. Ein Lauf von `--import-lightroom` ist nicht nötig. Siehe [Lightroom Classic](INTEROP.md#lightroom-classic).

**Grenzen und Fortschritt.**

- Exporte sind auf 10.000 Fotos begrenzt, für Auswahlen, gefilterte Ansichten und Alben gleichermaßen. Eine größere Menge wird abgelehnt, bevor etwas geschrieben wird; grenzen Sie die Filter ein und versuchen Sie es erneut.
- Exporte laufen im Hintergrund, mit Fortschritt und Zählern für geschrieben/übersprungen/Fehler. **Nach aktueller Datei stoppen** bricht zwischen Dateien ab; fertige Sidecars bleiben.
- Es läuft jeweils nur ein Bibliotheksauftrag. Während ein Export läuft, warten Scans, Neuberechnungen und automatisches Nachtrainieren oder werden abgelehnt, und ein Export wird abgelehnt, solange eines davon läuft.
- Das Schließen des Dialogs beendet nur die Fortschrittsanzeige, nicht den Export.
- Öffnen Sie „In Editor exportieren“ erneut, um Ihre 20 letzten Exporte zu sehen. **Unfertige Dateien erneut versuchen** startet einen neuen Auftrag für fehlgeschlagene, übersprungene und unverarbeitete Dateien. Eine mitten im Schreiben unterbrochene Datei kann erneut geschrieben werden.

## Download

Laden Sie Fotos aus der Fotodetailansicht oder der Auswahlleiste herunter. Das Download-Menü pro Foto listet die für dieses Foto verfügbaren Typen, einschließlich konfigurierter darktable-Profile:

- **Original** (`original`) — die Datei unverändert (JPG/HEIF) oder ein RAW, in JPEG konvertiert mit demselben Rendering, das der Viewer zeigt. Eine Aufnahme einer Belichtungsreihe wird daher ohne Belichtungskorrektur heruntergeladen — siehe [CONFIGURATION.md](CONFIGURATION.md#belichtungsreihen-werden-unkorrigiert-gerendert).
- **darktable** (`darktable`) — das Begleit-RAW, mit einem benannten darktable-Profil konvertiert. Fällt auf das Original zurück, wenn es kein Begleit-RAW gibt.
- **RAW** (`raw`) — die Begleit-RAW-Datei unverändert. In freigegebenen Alben nicht verfügbar.

**Salienzbewusster Social-Zuschnitt.** Ist `viewer.features.show_social_export` an (Standard `true`) und Edition freigeschaltet, hat die Download-Leiste der Fotodetailansicht ein Menü **Social-Zuschnitt**. Es listet `social_export.presets` (standardmäßig quadratisch 1:1, Hochformat 4:5, Story 9:16). Die Wahl lädt ein JPEG in voller Auflösung herunter, auf dieses Seitenverhältnis zugeschnitten und auf das Motiv zentriert. Das Motiv stammt aus dem BiRefNet-Motivrahmen (`photos.subject_bbox`, von `--recompute-saliency`), sonst aus den erkannten Gesichtern, sonst aus der Mitte. Der Tooltip des Menüs zeigt, was verwendet wurde (`saliency` / `faces` / `center`).

Endpunkte: [API.md — Download](../API.md#download).

## Auswahl

Die Auswahlseite (`/culling`, Bearbeitungsmodus) gruppiert beinahe identische Aufnahmen, sodass Sie von jeder das Beste behalten und den Rest ablehnen. Wählen Sie in jeder Gruppe die Behaltenen; das Bestätigen lehnt die anderen ab. Bestätigungen sind verzögert und lassen sich rückgängig machen (siehe [Rückgängig](#rückgängig)).

**Granularität** (das erste Steuerelement der Symbolleiste) legt fest, wie Fotos gruppiert werden:

- **Alle** (Standard) — Serien und Ähnlichkeitsgruppen zusammengeführt.
- **Serien** — zeitlich dicht aufeinander aufgenommene Fotos.
- **Ähnliche** — Fotos, die unabhängig von der Zeit gleich aussehen, nach CLIP/SigLIP-Ähnlichkeit. Ein Regler legt die Strenge fest.
- **Szenen** — chronologische Aufnahmezeit-Abschnitte, jeweils mit Zeitspanne und wichtigstem narrativem Moment als Überschrift. Erfordert `viewer.features.show_scenes`.
- **Belichtungsreihen** — von [`--detect-sequences`](COMMANDS.md) gefundene Sets, Basisbelichtung zuerst, jede Aufnahme mit ihrer Korrektur gekennzeichnet (`-2 EV` … `+2 EV`).
- **Panoramen** — von [`--detect-panoramas`](COMMANDS.md) gefundene Schwenks in Aufnahmereihenfolge, mittleres Bild markiert.
- **HDR-Panoramen** — Panorama-Schwenks mit einer Belichtungsspanne über `hdr_min_span_stops`. Ein HDR-Satz vom Stativ erscheint zuerst unter **Belichtungsreihen** und wechselt (als `hdr_panorama`) hierher, sobald der Panorama-Durchlauf den Schwenk erkennt. Tut er das nie, bleibt er eine Belichtungsreihe.

**Sets, die ganz behalten werden.** Belichtungsreihen, Panoramen und HDR-Panoramen gehören nicht zu **Alle**. Jede Aufnahme beginnt als behalten, und das Bestätigen erfasst keine Vergleichspaare. Ein Doppelklick („nur dieses behalten“) bewirkt dort nichts. Diese Feeds ignorieren die `hide_*`-Schalter der Galerie und zeigen jede Aufnahme. Um flankierende Belichtungen zu verwerfen, nutzen Sie das Bracket-Trimmen des Auto-Culls (unten).

Eine Gruppe, die nach dem Entfernen bereits abgelehnter Fotos weniger als 2 Aufnahmen hat, wird aus dem Feed genommen.

**Sortierung.** Der **Sortiermodus** (am einfachsten zuerst, am redundantesten, beste, neueste, braucht Vergleiche, **älteste zuerst**) sitzt neben der Granularität, mit einer Pfeilschaltfläche, die ihn umkehrt. „Älteste zuerst“ ordnet auch die Fotos *innerhalb* jeder Gruppe nach Aufnahmezeit, was zu Belichtungsreihen und Schwenks passt.

Granularität, Sortierung und Kategorie bleiben im `localStorage` erhalten. Nicht zutreffende Steuerelemente sind ausgeblendet (keine Sortierung oder kein Schwellenwert im Szenenmodus; keine Bereichsschaltfläche ohne manuelle Alben). Auf kleinen Bildschirmen wird die Symbolleiste zu einer scrollbaren unteren Leiste.

**Alle abgelehnten Fotos in den Papierkorb.** Diese Schaltfläche der Symbolleiste zeigt jedes für Sie sichtbare abgelehnte Foto der Bibliothek vorab an, ausgeblendete Aufnahmen eingeschlossen. Sie ignoriert Album-, Datums- und Galeriefilter. **Anwenden** schickt die Dateien in den Systempapierkorb des Facet-Rechners. Anders als **Löschen** bleiben Bibliothekszeilen und Entscheidungen erhalten, für „Mein Geschmack“.

- Erfordert Bearbeitungszugriff, `viewer.cull.allow_trash` und Papierkorb-Unterstützung.
- Auf 10.000 Fotos begrenzt. Für mehr nutzen Sie „Nur Abgelehnte anzeigen“ in der Galerie, grenzen nach Datum oder Album ein und verwenden In Ordner aussortieren → Abgelehnte in den Papierkorb in Stapeln. Schalten Sie die Gruppen-Ausblendfilter aus, um jede abgelehnte Aufnahme einzubeziehen.
- Begleit-RAW/XMP-Dateien sind optional.
- Haben sich die aufgelösten Dateien, Optionen oder das Ziel seit der Vorschau geändert, wird Anwenden abgelehnt; zeigen Sie erneut vorab an. Die Prüfung vergleicht Dateinamen und Einstellungen, nicht Dateiinhalte, und sperrt die Dateien nicht.
- Ein Dateisystemfehler mittendrin lässt fertige Dateien im Papierkorb; der Dialog bleibt für eine neue Vorschau offen.
- In Containern hängen Papierkorb und Wiederherstellung vom Dateisystem des Servers ab.

> **Warnung:** In einer geteilten Bibliothek verwendet „Alle abgelehnten Fotos in den Papierkorb“ nur *Ihre* Ablehnungen. Es legt die geteilten Dateien auch dann in den Papierkorb, wenn ein anderer Benutzer sie behalten, favorisiert oder bewertet hat. Prüfen Sie die Vorschau.

**Eingegrenztes Aussortieren.** Grenzen Sie die Dunkelkammer mit URL-Parametern ein: `?group_by=scene` für Szenen, `?album=<id>` für ein Album, `?from=&to=` für ein Aufnahmezeit-Fenster (EXIF-Text oder ISO-Daten wie `2026-06-01`). Ein Banner zeigt den Bereich mit **Szene verlassen**. Serien, die über den Fensterrand hinausreichen, zeigen weiterhin alle ihre Aufnahmen.

**Datumsbereich.** Die Schaltfläche **Datumsbereich** (Symbol `date_range`) bietet **Letzte 7 Tage**, **Letzte 30 Tage**, **Dieses Jahr**, **Letztes Jahr**, **Eigener Bereich...** und **Alle Daten**. Daten erscheinen als dd/MM/yyyy.

- Er lässt sich mit dem Albumbereich kombinieren. Fotos ohne Aufnahmedatum fallen aus einem datierten Bereich heraus.
- Voreinstellungen werden bei der Wahl aufgelöst, daher ist ein mit Lesezeichen versehenes „Letzte 7 Tage“ ein festes Fenster.
- Der Bereich liegt nur in der URL (`?from=2026-07-01&to=2026-07-31`), nicht im `localStorage`.
- Eine Änderung lädt den Feed neu: Eine ausstehende Bestätigung wird übernommen, unbestätigte Auswahlen und Überspringungen entfallen.

**Zeile „Mein Geschmack“.** Jede Bestätigung erfasst `source='culling'`-Vergleiche, die den persönlichen Ranker trainieren. Der Hilfedialog (Benutzermenü → Hilfe) zeigt „Mein Geschmack · N Vergleiche“ (`GET /api/ranker/status`) und listet die Tastenkürzel der Auswahl.

**Genre-Profile.** Die Auswahl **Profil** wendet eine Genre-Voreinstellung an, die Strenge, Behalte-Budget, Ähnlichkeitsschwelle und die Grenzwerte für geschlossene Augen / schlechten Ausdruck auf einmal setzt. Sport behält nur das schärfste Foto einer Serie, Hochzeiten behalten mehr Varianten mit offenen Augen, Konzerte und Wildtiere lockern die Gesichtsgrenzen. Die Wahl und der Strenge-Regler bleiben im `localStorage` erhalten. Das manuelle Ändern eines Reglers zeigt „Benutzerdefiniert“. Die Voreinstellungen stehen in [`cull_profiles`](CONFIGURATION.md#genre-spezifische-aussortier-profile) (`GET /api/culling/profiles`).

### Auto-Cull

**Auto-Cull** in der Symbolleiste sortiert einen ganzen Bereich in einem Durchgang aus.

1. Wählen Sie den Bereich: alle Gruppen oder nur Serien / Ähnliche / Szenen, optional ein Album oder Datumsfenster.
2. Legen Sie die **Strenge** fest (höher behält weniger pro Gruppe).
3. Zeigen Sie vorab an. Jede Gruppe behält ihr bestes Foto plus alles innerhalb der Strenge-Marge (mindestens ein Minimum pro Gruppe) und lehnt den Rest ab.
4. Bestätigen. Ablehnungen werden erfasst, behaltene Fotos als **Behalten** markiert, und „Mein Geschmack“ lernt daraus.

- Die Vorschau ist ein **Trockenlauf**: Es wird nichts geschrieben.
- Ein optionales Album **Highlights** sammelt das beste Foto jeder Gruppe mit mindestens `auto_cull.highlights_min`.
- Ein Abzeichen „besseres Foto in dieser Gruppe“ kennzeichnet Gruppen, in denen Auto-Cull eine andere Aufnahme behielte als das aktuelle Leitbild.
- Ist ein Keeper-Ranking-Head trainiert und besteht seine Genauigkeitsschwelle, wählt er das Behaltene (`keeper_prob`). Sonst wählt die übliche Heuristik.
- Die Schaltfläche ist in den Granularitäten ausgeblendet, die Sets ganz behalten. In einem gemischten Bereich werden Belichtungsreihen zuerst entschieden.
- Konfigurieren Sie mit dem Block [`auto_cull`](CONFIGURATION.md#auto-cull) (`POST /api/culling/auto`). Im Terminal führen Sie es mit `python facet.py --auto-cull` aus — siehe [Culling](COMMANDS.md#culling).

**Das Trimmen redundanter Belichtungsreihen** (`trim_brackets`, standardmäßig aus) ist der einzige Weg, wie Auto-Cull je ein Set verkleinert. Beschneidet die Basisbelichtung einer Reihe weder Schatten noch Lichter, bringen die flankierenden Aufnahmen nichts, daher wird nur die Basisaufnahme behalten. Sets, deren Basis-Beschnitt nie gemessen wurde, bleiben unberührt.

### Plan-Modus des Assistenten

Zeigt ein über [KI-Agenten (MCP)](AGENTS.md) verbundener Assistent einen Auto-Cull vorab an (`auto_cull` oder `ui_show_culling_plan`), lädt Ihr offener Tab diesen Plan auf `/culling`. Es ist die normale Dunkelkammer (Lupe `Z`, Vergleich 2-fach / 4-fach, Peaking), wobei die Behaltenen des Plans vorausgewählt sind.

- Ein Banner lautet **Assistenten-Plan · x/y bestätigt · Beenden**.
- Jede Gruppe hat einen Chip wie **#3 · Grund · Vorschlag: 2 behalten / 1 ablehnen**. Ein blauer Chip in der Kopfzeile ist die Notiz des Assistenten zur Gruppe.
- Ein Punkt auf einer Aufnahme bedeutet, dass Sie sie gegenüber dem Plan geändert haben.
- Ein gestricheltes Abzeichen **Assistent: behalten** / **Assistent: ablehnen** ist der Vorschlag des Assistenten, mit seinem Grund im Tooltip. Klicken Sie darauf (oder Enter/Leertaste), um ihn anzuwenden; Sie bestätigen die Gruppe weiterhin.
- Bestätigen Sie wie gewohnt Gruppe für Gruppe, mit Countdown und **Rückgängig**. Bestätigungen im Plan-Modus fügen nie einem Highlights-Album etwas hinzu.
- Eine bestätigte Serien- oder Ähnlichkeitsgruppe verlässt den Plan. Eine bestätigte Szenengruppe wird nicht erfasst, daher kann die nächste Vorschau sie erneut vorschlagen.
- Das Bestätigen einer Serie lehnt nur die gezeigten Mitglieder ab; Mitglieder außerhalb des Album- oder Datumsfensters bleiben unberührt.
- Sortierung und Schwellenwert sind gesperrt. Das Bewegen des Strenge-Reglers oder eine Änderung des **Datumsbereichs** plant neu; Ihre Änderungen und bestätigten Gruppen bleiben erhalten. **Alle Daten** kann die Plan-Obergrenze erreichen (`plan_truncated`).
- **Beenden** oder eine Änderung von Gruppierung, Bereich oder Sortierung verlässt den Plan-Modus. Verlassen Sie `/culling` und kehren zurück, wird er wiederhergestellt; Neuladen verwirft ihn.
- Hat sich die Bibliothek seit der Vorschau geändert, weist ein Hinweis darauf hin, dass der Plan veraltet ist. Übergroße Gruppen werden ausgelassen und in einem Hinweis gezählt.

Der Assistent liest Ihren Fortschritt mit `ui_get_context` (`culling`: bestätigte, ausstehende und geänderte Gruppen) und wendet aus dem Tab selbst nichts an. Siehe [Plan-Modus auf `/culling`](AGENTS.md#ergebnisse-erscheinen-in-ihrem-tab).

### Vollbild

Drücken Sie **`F`** (oder den Umschalter in der Kopfzeile), um im Vollbild ohne App-Oberfläche zu sichten. Mit `F` oder `Esc` verlassen Sie es.

Drücken Sie **`S`** (oder die Stapel-Schaltfläche der Kopfzeile), um die geöffnete Gruppe mit der fokussierten Aufnahme als Titelbild zu stapeln. Entscheidungen bleiben unberührt, und Rückgängig wird angeboten. Nicht angeboten für Gruppen mit Belichtungsreihen- oder Panoramabildern oder mit einem Foto, das bereits in einem Stapel liegt.

### Lupe / Z-Tasten-Zoom

Drücken Sie **`Z`** in der Einzelansicht, um eine Lupe umzuschalten (Einpassen ↔ 2×; Mausrad oder `+`/`-` bis 800 %). Ist über die Einpassung hinaus gezoomt, lädt das Fenster das `/image` in voller Auflösung, sodass Sie die Schärfe an echten Pixeln beurteilen. Vorschaubilder haben 640px, und die Einpassungsansicht ist ein Rendering mit bis zu 1920px; die Lupe geht darüber hinaus.

- Auf dem Kontaktstreifen der Szenen schaltet `Z` eine Hover-Lupe mit Zoom-Regler um.
- Fenster zeigen zuerst das gespeicherte Vorschaubild und wechseln dann zum scharfen Rendering. Die nächste und vorherige Aufnahme werden vorab geladen (außer bei aktivem Datensparmodus).
- Ein Rendering, das nicht innerhalb von 5 s starten kann, wird für 60 Sekunden durch das Vorschaubild ersetzt.

**Hover-Lupe der Dunkelkammer.** Eine runde Lupe folgt dem Cursor über dem Hauptbild, jedem Vergleichsfenster und den Gesichts-Nahaufnahmen und zeigt Pixel in voller Auflösung. Ein Umschalter in der Symbolleiste schaltet sie ein oder aus (standardmäßig an, pro Browser gespeichert). Sie pausiert, solange das Bild über die Einpassung hinaus gezoomt ist, funktioniert im Vollbild und folgt `←`/`→`.

### Abzeichen pro Gesicht

In der Lightbox der Auswahl trägt jedes Gesicht eigene Abzeichen: Augen offen/geschlossen, schlechter Ausdruck und Erkennungskonfidenz. So sehen Sie, welches Gesicht auf einem Gruppenfoto geschlossene Augen hat. Pro Gruppe abgerufen mit `POST /api/culling-group/faces`.

**Gesichtspanel.** Gesichtsausschnitte sind je nach Augen-offen- und Lächel-Wert grün / orange / rot gefärbt.

- Die Regler **Augen** und **Lächeln** stimmen ab, was als Blinzeln oder schwacher Ausdruck zählt. Sie beginnen bei `face_detection.eyes_closed_max` und `face_detection.poor_expression_min` (beide standardmäßig `4.0`).
- **Größe** (64–256 px, Schritte von 16, Standard `112px`) ändert die Ausschnittgröße. Reglerwerte werden pro Browser gespeichert.
- Nach der Bedienung eines Reglers mit der Maus gehen die Pfeiltasten zurück zur Dunkelkammer (`←`/`→` Aufnahme, `↑`/`↓` behalten/ablehnen). Mit Tab gelangen Sie auf einen Regler, um ihn per Tastatur anzupassen.

**Motiv-Nahaufnahmestreifen (Gruppen ohne Gesichter).** Für Gruppen ohne nennenswerte Gesichter (Wildtiere, Makro, Produkte) zeigt die Dunkelkammer das Hauptmotiv jeder Aufnahme nebeneinander, aus dem BiRefNet-Motivrahmen ausgeschnitten. Jeder Ausschnitt hat ein Schärfe-Abzeichen (10 = schärfste der Gruppe) und einen grünen / bernsteinfarbenen / roten Ring. Ein Klick auf einen Ausschnitt springt zu diesem Foto. Es läuft kein Modell (`POST /api/culling-group/subjects`). Führen Sie bei einer bestehenden Bibliothek zuerst `python facet.py --recompute-saliency` (GPU) aus; bis dahin erscheint der Streifen nicht.

**Schlüsselmotiv (Zoomziel + Schlüsselperson).** Das Zoomen (**`Z`**, Doppelklick oder der erste Mausradschritt) landet auf dem Schlüsselmotiv der Aufnahme statt in der Mitte: ihr bestes Gesicht, oder der Motivrahmen, falls es keines gibt. Sobald Sie eine Aufnahme selbst schwenken oder zoomen, richtet Facet sie nicht mehr neu aus. Eine benannte Person, die gewinnt, erhält im Gesichtsstreifen eine bernsteinfarbene Namenspille. Benannte Personen im Mittelgrund schlagen größere Fremde; ein winziges Hintergrundgesicht gewinnt nicht. Es wird nichts gespeichert. Rahmen sind Bruchteile des ganzen Bildes (`normalized_frame_xyxy`). Endpunkte: `POST /api/photos/key_subjects`, `GET /api/photo/key_subject`.

**Synchronisierter Vergleich (2-fach / 4-fach).** Die Schaltflächen Einzeln / Vergleich 2 / Vergleich 4 der Kopfzeile wechseln die Ansichten. Im Vergleichsmodus teilen alle Fenster ein Schwenken/Zoomen, sodass Sie denselben Ausschnitt vergleichen. Ein Doppelklick schaltet Einpassen ↔ Zoom um. Beim Einpassen zeigt jedes Fenster `/thumbnail?size=1920`; gezoomt lädt es das `/image` in voller Auflösung. Das Pinch-Zoomen per Touch ist noch nicht angebunden; nutzen Sie das Mausrad.

**Wischen zum Behalten oder Ablehnen (Touch).** Ziehen Sie auf einem Touch-Gerät die Aufnahme nach rechts zum Behalten oder nach links zum Ablehnen. Sie neigt sich und färbt sich grün (BEHALTEN) oder rot (ABLEHNEN).

- Über 35 % der Breite (mindestens 48px) hinaus erfasst das Loslassen dieselbe Entscheidung wie `↑` / `↓` und geht zur nächsten Aufnahme. Davor federt sie zurück.
- Ein vertikales Ziehen wird ignoriert.
- Jedes Wischen zeigt **Rückgängig**, das die Entscheidung wiederherstellt und zu dieser Aufnahme zurückkehrt.
- Nur in der Einzelansicht, bei Einpassungsskala, mit Finger oder Stift. Ein einzeiliger Hinweis erscheint, bis er geschlossen wird.

**Vorschau des bearbeiteten Looks.** In der Einzelansicht listet das **Paletten**-Menü „Original“ plus jeden konfigurierten darktable-Stil, sodass Sie am entwickelten Look aussortieren können.

- Facet rendert das Original über darktable-cli (`--style`, begrenzt auf `preview_max_edge`). Bei einem Fehler kehrt es zu Original zurück.
- Der Stil bleibt für die aktuelle Gruppe und wird zurückgesetzt, wenn Sie die Dunkelkammer erneut öffnen.
- Nur sichtbar, wenn ein Stil konfiguriert ist **und** darktable-cli gefunden wird. Stile müssen in der darktable-Konfiguration des Benutzers existieren, der den Viewer ausführt.
- Renderings werden auf der Platte zwischengespeichert.
- Endpunkt: `GET /api/photo/cull_preview?path=&style=` (Edition). Konfigurieren über [`raw_processor.darktable.cull_styles`](CONFIGURATION.md#raw-dekodierung).

## Szenen-Ansicht

Eine **schreibgeschützte** Ansicht der Bibliothek als chronologische Szenen, in Erzählreihenfolge mit Datums-/Moment-Überschriften und einer Hover-Lupe. Offen für **alle authentifizierten Benutzer**.

- Eine neue Szene beginnt, wenn mehr als `scenes.gap_minutes` zwischen Aufnahmen liegen (bei spärlichen Shootings erweitert). Sehr lange Abschnitte werden geteilt.
- Öffnen Sie sie über die Aktion **Szenen dieses Albums anzeigen** im Albumraster; eine Auswahl wechselt zwischen Alben. Es gibt keinen Szenen-Eintrag in der Hauptnavigation.
- Jede Szene hat eine nur für Edition verfügbare Schaltfläche **Diese Szene aussortieren**, die [Auswahl](#auswahl) für diese Szene öffnet (`/culling?group_by=scene&album=&from=&to=`).
- Sind narrative Momente berechnet, trägt jede Szene den Titel ihres wichtigsten Moments, und `scenes.split_on_moment_change` kann einen Abschnitt teilen, wo der Moment wechselt.
- Szenen kleiner als `scenes.min_size` werden ausgelassen; es werden höchstens `scenes.max_photos` Fotos geladen.

Gesteuert über `viewer.features.show_scenes` (Standard: `true`). Siehe [Konfiguration — Szenen](CONFIGURATION.md#scenes) für `gap_minutes`, `min_size`, `max_photos`, `max_scene_size`, `adaptive` und `adaptive_k`.

## Narrative Momente

Facet kennzeichnet jedes Foto mit der Aktivität, die es zeigt. Das **allgemeine** Standardvokabular: Feier, Essen, Strand, Wasseraktivität, Berge, Natur & Wildtiere, Stadtansicht, Reisesehenswürdigkeit, Konzert, Sport, Gruppentreffen, Porträt, Kinder, Haustiere, Nachtleben, Zeremonie, Landschaft, Schnee & Winter, Wohnen drinnen, Straße & Fahrzeug oder `other`. Ein `wedding`-Vokabular steht als optionales Genre bereit.

- Es läuft lokal, ohne zusätzlichen Modelldurchlauf: Die KI-Bildunterschrift jedes Fotos wird mit den Text-Prompts jedes Moments abgeglichen (das Bild-Embedding dient, wenn es keine Bildunterschrift gibt). Eine zeitliche Glättung behebt vereinzelte Fehllesungen.
- Ein optionaler VLM-Tiebreaker (16gb/24gb) prüft Frames mit niedriger Konfidenz erneut.
- Er **läuft automatisch am Ende jedes Scans**. Der erste Durchlauf über eine bestehende Bibliothek kodiert jede Bildunterschrift (GPU empfohlen). Alles neu kennzeichnen mit `python facet.py --recompute-moments`.
- Momente erscheinen als Szenentitel und als Galeriefilter (`GET /api/photos?narrative_moment=beach`, Optionen aus `GET /api/filter_options/narrative_moments`).
- Das Vokabular ist konfigurierbar — siehe [Konfiguration — Narrative Momente](CONFIGURATION.md#narrative-moments).

**Moment-Konfidenz.** Jedes Label hat eine Konfidenz (`narrative_moment_confidence`). Labels unter `viewer.moment_confidence_min` (Standard `0` = nie abdunkeln) erscheinen abgedunkelt mit „(unsicher)“ in den Kopfzeilen von Szenen und Auswahl und im Tooltip. Die Konfidenz ist auch eine Sortierung (**Moment-Konfidenz**, unter Inhalt) und ein 0–1-Bereichsfilter (`min_moment_confidence` / `max_moment_confidence`, Abschnitt **Momente** der Seitenleiste).

## Müll aufräumen

Eine schnelle Prüfwarteschlange für Screenshots, gescannte Dokumente, Belege, Memes und Folien. Führen Sie `python facet.py --detect-junk` aus (es läuft auch nach jedem Scan), um `junk_kind` zu füllen. Siehe [Konfiguration — Müll aufräumen](CONFIGURATION.md#junk-sweep).

Öffnen Sie **Müll aufräumen** in der Navigation (`/junk`, nur Edition):

- **Chips zum Filtern nach Art** — „Alle Arten“ plus ein Chip pro Art mit ihrer Anzahl (`GET /api/filter_options/junk_kinds`).
- **Kandidatenanzahl** — zählt herunter, während Sie entscheiden.
- **Behalten** — nimmt das Foto **endgültig** aus der Warteschlange (`not_junk`); spätere `--detect-junk`-Läufe überspringen es.
- **Ablehnen** — markiert das Foto als abgelehnt (nichts wird gelöscht).
- **Alle angezeigten ablehnen** — lehnt nach Bestätigung jeden geladenen Kandidaten ab.
- **Lupe** — drücken Sie **`Z`** (oder den Umschalter der Symbolleiste), um feinen Text zu vergrößern.

Müll-Fotos bleiben in der normalen Galerie sichtbar. Filtern Sie sie mit `?junk_kind=<kind>` oder `?junk_kind=any` (schließt `not_junk` aus).

Gesteuert über `viewer.features.show_junk_sweep` (Standard: `true`).

## Paarweiser Vergleichsmodus

Ordnen Sie Fotos, indem Sie jeweils zwei beurteilen; die Stimmen fließen in die Gewichtsabstimmung ein. Öffnen Sie `/compare` (Schaltfläche Vergleichen in der Kopfzeile). Erfordert ein nicht leeres `edition_password` (Einzelbenutzer) oder die Rolle `admin`/`superadmin` (Mehrbenutzer).

### Tab „A/B-Vergleich“

Wählen Sie einen Gewinner, markieren Sie ein Unentschieden oder überspringen Sie. Ein Fortschrittsbalken zählt bis 50 Stimmen, mit Summen für A gewinnt/B gewinnt/Unentschieden. Ein Kategoriefilter begrenzt die Sitzung; eine Strategie-Auswahl wählt die Paare:

| Strategie | Beschreibung |
|----------|-------------|
| `learning` | Standard. Zuerst vielfältige Paare, dann Paare, bei denen der persönliche Ranker am stärksten abweicht (am aufschlussreichsten) |
| `uncertainty` | Fotos mit ähnlichen Wertungen (am aufschlussreichsten) |
| `boundary` | Wertungsbereich 6–8 (mehrdeutige Zone) |
| `active` | Fotos mit den wenigsten Vergleichen (stellt Abdeckung sicher) |
| `random` | Zufällige Paare (Basislinie) |

**Tastenkürzel:**

| Taste | Aktion |
|-----|--------|
| `A` | Linkes Foto gewinnt |
| `B` | Rechtes Foto gewinnt |
| `T` | Unentschieden |
| `S` | Paar überspringen |
| `Escape` | Dialog zur Kategorieüberschreibung schließen |

### Tab „Gewichtsvorschläge“

Vergleicht die aus Ihren Stimmen gelernten Gewichte mit den aktuellen, mit Modellgenauigkeit vorher/nachher und den Top-10-Fotos jetzt vs. nach der Neuberechnung.

- **Anwenden** schreibt die vorgeschlagenen Gewichte; **Neu berechnen** bewertet die Kategorie neu (beides im Bearbeitungsmodus).
- **Anwenden** erscheint nur, wenn der Vorschlag die aktuellen Gewichte bei zurückgehaltenen Vergleichen schlägt (`suggest_changes`, derselbe Test wie `--optimize-weights`, siehe [COMMANDS.md](COMMANDS.md)).
- Anders als `--optimize-weights` zentriert **Anwenden** den Bonus der Kategorie nicht neu, sodass sich ihre mittlere Wertung verschieben kann.

### Tab „Gewichte“

Ein Regler pro Metrik für die gewählte Kategorie, mit Live-Vorschau der Wertung. **Speichern** schreibt `scoring_config.json` (mit Sicherung); **Wertungen neu berechnen** wendet es an; **Zurücksetzen** lädt die gespeicherten Gewichte neu.

### Tab „Snapshots“

Speichern Sie die aktuellen Gewichte als benannten Snapshot und stellen Sie einen früheren wieder her. Ein Snapshot stellt auch den Bonus der Kategorie wieder her (`modifiers.bonus`). Snapshots von vor 1.21, von `calibrate.py` oder für `others` tragen keinen Bonus und lassen ihn unverändert.

### Kategoriepriorität & Bewertungskontexte

Kategorien werden in aufsteigender `priority`-Reihenfolge geprüft; die erste Übereinstimmung gewinnt. Siehe [Filterauswertung](SCORING.md#so-funktioniert-die-bewertung) und [Bewertungskontexte](CONFIGURATION.md#bewertungskontexte). Zwei Werkzeuge nur für Edition ändern dies, ohne `scoring_config.json` zu bearbeiten:

- **Globale Priorität** — die Basis-Auswertungsreihenfolge umordnen.
- **Bewertungskontexte** — Voreinstellungen (`default`, `action_stage`, `party_event`, `portrait_session`, `wildlife`, `landscape`, `motorsport`), die einige Kategorien vorziehen und andere ausschließen, ohne die globale Reihenfolge zu ändern. Bearbeiten Sie jede Voreinstellung außer `default` im Tab **Bewertungskontext**: Ziehen Sie die vorgezogenen Kategorien (oder verschieben Sie sie nach oben/unten), schalten Sie Ausschlüsse um, speichern Sie. Eine in beiden aufgeführte Kategorie gilt als ausgeschlossen. `label_key` und `suggest_from_moments` sind hier nicht bearbeitbar. Weisen Sie einen Kontext pro Album (siehe [Bewertungskontext](#bewertungskontext)) oder pro Foto (unten) zu.

Keines von beiden bewertet Fotos von selbst neu. Führen Sie danach eine Neuberechnung aus (`POST /api/scan/recompute`) und beobachten Sie `GET /api/scan/recompute_status`. Ein bereits laufender Scan oder eine Neuberechnung aus einem Terminal blockiert einen neuen aus dem Viewer. Bei aktivem `normalization.per_category` konvergiert eine Neuberechnung womöglich nicht vollständig — siehe [Normalisierung](CONFIGURATION.md#normalization) und [Die globale Priorität umordnen](CONFIGURATION.md#die-globale-priorität-neu-ordnen).

**Kategoriekollisionen** (`GET /api/stats/categories/overlap`) zeigt, welche Kategorie höherer Priorität die Fotos einer Kategorie an sich zieht. Pro Kategorie listet es **Zugewiesen**, **Passt zu Filtern** (bei alleiniger Auswertung) und **Von höherer Priorität erfasst** (`matched - assigned`, mindestens 0). **Häufigste kollidierende Paare** ordnet Kategorien nach gemeinsamen Fotos. Der Auffangwert `default` bleibt außen vor, da er alles trifft.

### Kategorieüberschreibung

Weisen Sie die Kategorie eines Fotos in der Vergleichsansicht neu zu: Bearbeiten Sie das Kategorieabzeichen, wählen Sie eine Kategorie, führen Sie „Filterkonflikte analysieren“ aus, um zu sehen, welche Filter sie ausschließen, und wenden Sie dann an. Die Überschreibung ist dauerhaft: Sie übersteht Neuberechnungen, bis Sie sie löschen (`POST /api/comparison/override_category`, `POST /api/comparison/clear_category_override`).

Die Foto-Lightbox hat dieselben Aktionen unter **Bewertungskategorie festlegen…** / **Überschreibung löschen** (nur Edition). Der Pfeil im Kategorie-Chip öffnet **warum ist das keine andere Kategorie?**: Wählen Sie eine Kategorie, und es listet die Filter, die das Foto ausschließen, und was jeder bräuchte, z. B. *„shutter_speed_max von 0.02 auf 0.033 anheben“*. Das zeigt, wann eine Kategorie für ein Foto unerreichbar ist, was ein Umordnen nicht beheben kann (`POST /api/comparison/suggest_filters`).

## EXIF-Statistiken

Die Statistikseite (`/stats`) hat 5 Tabs. Die Auswahl für **Kategorie** und **Datumsbereich** filtert jedes Diagramm. Im Mehrbenutzermodus sieht jeder Benutzer Statistiken für seine eigenen sichtbaren Fotos.

### Tabs

| Tab | Beschreibung |
|-----|-------------|
| **Ausrüstung** | Kameragehäuse, Objektive und Kombinationen (jeweils die Top 20) |
| **Aufnahmeeinstellungen** | Verteilungen von ISO, Blende, Brennweite und Verschlusszeit |
| **Zeitleiste** | Fotos im Zeitverlauf |
| **Kategorien** | Kategorieanalysen, Gewichtsverwaltung und Wertungskorrelationen |
| **Korrelationen** | Eigene X/Y-Metrikkorrelationsdiagramme mit Gruppierung |

### Tab „Kategorien“

Vier Untertabs:

| Untertab | Beschreibung |
|---------|-------------|
| **Aufschlüsselung** | Fotozahlen pro Kategorie, Durchschnittswertungen, Histogramme der Wertungsverteilung |
| **Gewichte** | Radardiagramm-Vergleich (bis zu 5 Kategorien), Gewichts-Heatmap und Gewichtseditor (Bearbeitungsmodus) |
| **Korrelationen** | Pearson-Korrelations-Heatmap, die zeigt, wie jede Dimension den Gesamtwert beeinflusst, mit Detailansicht per Klick |
| **Überlappung** | Filterüberlappungsanalyse, die zeigt, welche Kategorien passende Fotos teilen |

Jedes Diagramm hat eine Schaltfläche `?`, die erklärt, wie es zu lesen ist; ein Umschalter in der Untertab-Leiste zeigt alle Erklärungen.

### Gewichtseditor (Bearbeitungsmodus)

Im Untertab Gewichte, bei aktivem Bearbeitungsmodus:

1. Eine Kategorie aus der Auswahlliste wählen
2. Die Gewichtsregler anpassen (einer pro Metrik, Summe sollte 100 % ergeben)
3. Mit „Auf 100 normalisieren“ automatisch ausgleichen
4. Den Abschnitt Modifikatoren aufklappen, um Boni/Abzüge anzupassen
5. Die **Vorschau der Wertungsverteilung** zeigt ein Live-Histogramm vorher/nachher
6. Auf **Speichern** klicken, um `scoring_config.json` zu aktualisieren (legt eine Sicherung mit Zeitstempel an)
7. Auf **Wertungen neu berechnen** klicken (erscheint nach dem Speichern), um die Gewichte auf diese Kategorie anzuwenden

## Tastenkürzel (Galerie)

Einzeltasten-Kürzel sind inaktiv, solange der Fokus in einem Textfeld, Menü oder einer Liste liegt.

| Taste | Aktion |
|-----|--------|
| `←` `→` `↑` `↓` | Die Markierung des aktuellen Fotos zwischen Fotokarten bewegen (Rasterspalten und Mosaikzeilen) |
| `Enter` | Das fokussierte Foto öffnen |
| `Space` | Das fokussierte Foto auswählen / abwählen |
| `Ctrl+A` / `Cmd+A` | Alle auswählen — bei leerer Auswahl die ganze gefilterte Ansicht, sonst die geladenen Fotos |
| `Escape` | Auswahl aufheben (im Seitenleistenmodus auch das gehaltene Foto freigeben) / Filterschublade schließen |
| `Shift+Click` | Fotos zwischen zuletzt ausgewähltem und angeklicktem als Bereich auswählen |
| `Double-click` | Foto öffnen |
| `Shift+F10` / `Menu` | Das Kontextmenü der fokussierten Fotokarte öffnen (Rechtsklick tut dasselbe) |
| `1`–`5` | Das fokussierte Foto mit 1–5 Sternen bewerten (Bearbeitungsmodus; springt automatisch zum nächsten Foto) |
| `K` | Das fokussierte Foto behalten (Bearbeitungsmodus) |
| `F` | Das fokussierte Foto favorisieren / Favorit aufheben (Bearbeitungsmodus) |
| `X` oder `0` | Das fokussierte Foto ablehnen / Ablehnung aufheben (Bearbeitungsmodus; springt automatisch weiter) |
| `/` | Die Suche der Symbolleiste fokussieren (ab 1360 px Breite sichtbar); schmaler öffnet es die Suche der Filter-Seitenleiste |
| `S` | Den Stapel-Editor für die ausdrückliche Auswahl öffnen (Bearbeitungsmodus; umbelegbar, kann unbelegt bleiben) |
| `Strg+Umschalt+S` / `Cmd+Umschalt+S` | Die ausdrückliche, ungestapelte Auswahl sofort in Auswahlreihenfolge stapeln, das erste Foto als Titelbild (Bearbeitungsmodus; vorhandene Stapelmitglieder öffnen den Editor) |
| `B` | Die Filter-Seitenleiste ein-/ausblenden |
| `V` | Zwischen Raster- und Mosaiklayout wechseln |
| `?` | Die Tastenkürzel-Referenz anzeigen (auf jeder Seite; auch unter Benutzermenü → Hilfe) |

**Tasten umbelegen.** `K`, `F`, `X`, `/`, `B`, `V` und `S` sind Standardwerte. Unter Benutzermenü → **Tastenkürzel anpassen** klicken Sie eine Aktion an und drücken eine neue Taste (`Esc` oder `Tab` bricht ab). Ziffern, `Space` und `?` sind reserviert, und eine bereits verwendete Taste wird abgelehnt. **Alle zurücksetzen** stellt die Standardwerte wieder her. Die Belegung wird pro Browser gespeichert (`localStorage`). Die Fotoseite verwendet dieselben Tasten, und die Referenz unter `?` zeigt immer die geltenden Tasten.

**Aktuelles Foto.** Das Foto, auf das die Tasten für Bewertung, Favorit und Ablehnung wirken, hat eine 4px-Kontur; andere Karten werden auf 50 % abgedunkelt. Nichts ist markiert, bis Sie sich auf ein Foto bewegen. Ein Klick auf ein Foto verschiebt die Markierung darauf. Die Rückkehr von einem Foto lässt die Markierung auf dem zuletzt betrachteten. Der Hinweis zur fokussierten Karte erscheint nur im Bearbeitungsmodus bei aktivem `viewer.features.show_rating_controls`.

**Auf der Fotoseite** wirken `1`–`5`, die Favoriten-Taste und die Ablehnen-Taste (standardmäßig `F` und `X`; `0` lehnt ebenfalls ab) auf das geöffnete Foto, im Bearbeitungsmodus bei aktivem `viewer.features.show_rating_controls`. Sie springen nicht weiter; nutzen Sie `←` `→`. Die Referenz unter `?` listet sie unter *Fotoansicht*.

## Rückgängig

Sammeländerungen an Favorit/Ablehnung/Bewertung und Auswahl-Bestätigungen zeigen etwa 7 Sekunden lang eine Snackbar mit **Rückgängig**.

- Sammeländerungen von Markierungen gelten sofort und werden durch Umkehren rückgängig gemacht (bis zu 500 Fotos).
- Auswahl-Bestätigungen sind verzögert: Die Gruppe verschwindet sofort, aber nichts wird gespeichert, bis das Rückgängig-Fenster endet.
- Änderungen an [manuellen Tags](#manuelle-tags) lassen sich nicht rückgängig machen.

Für ältere Änderungen siehe [Änderungsverlauf](#änderungsverlauf).

## Progressive Web App

Produktions-Builds lassen sich auf dem Startbildschirm installieren. Die App-Hülle lädt offline, und bis zu 1000 Vorschaubilder werden 7 Tage lang zwischengespeichert (größere Größen, etwa die 1920px-Renderings der Dunkelkammer, verlassen sich auf den Browser-Cache). API-Antworten werden nie zwischengespeichert, außer Übersetzungspaketen. Eine Snackbar bietet ein Neuladen an, wenn eine neue Version bereitgestellt wird.

> **Warnung:** Die Abmeldung leert den Vorschaubild-Cache der App, nicht aber den HTTP-Cache des Browsers, der angesehene Bilder (Vorschaubilder, Renderings, Bilder in voller Auflösung) bis zu einem Jahr behalten kann. Konten, die die Fotos der anderen nicht sehen dürfen, sollten kein Browserprofil teilen.

## Mobil

Auf kleinen Bildschirmen behält die schwebende Auswahlkarte die Anzahl und die Schaltflächen Aufheben, Alle auswählen und Umkehren sowie eine Schaltfläche **Aktionen**. Sie öffnet ein unteres Blatt mit jeder Sammeloperation (Favorit, Ablehnen, Bewerten, Alben, Kopieren, Herunterladen). Eine Vergleichsschaltfläche erscheint, wenn die Auswahl in die Vergleichsansicht passt.

## Bilderrahmen / Kiosk

Smarte Bilderrahmen, Home-Assistant-Dashboards und Anzeigen im Stil von ImmichFrame / Immich-Kiosk können Ihre besten Aufnahmen ohne Anmeldung abrufen. Es gibt **keine Client-Oberfläche**: Geräte rufen die Endpunkte mit einem langlebigen **Rahmen-Token** aus dem `frame`-Konfigurationsblock auf. Bei leerem `frame.tokens` (der Standard) ist die Funktion aus, und jeder Endpunkt liefert 404.

- **Was gezeigt wird.** Fotos stammen aus der gesamten Bibliothek, nicht aus den Ordnern eines Benutzers. Abgelehnte, Müll- und Blinzel-Fotos sind ausgeschlossen. `frame.min_aggregate` (Standard 7.0) legt die Wertungsuntergrenze fest; `frame.favorites_only` und `frame.categories` grenzen weiter ein.
- **Abwechslung.** Fotos sind eine nach Wertung gewichtete Zufallsstichprobe, sodass Sie verschiedene gute Aufnahmen sehen statt immer derselben wenigen.
- **Keine Dateipfade.** Jedes Foto wird über eine undurchsichtige signierte ID angesprochen, sodass ein Token-Inhaber nicht erfahren kann, wo Ihre Dateien liegen, oder andere Zeilen durchsuchen kann.

| Endpunkt | Liefert | Cache |
|----------|---------|-------|
| `GET /api/frame/photos?token=&count=` | `{photos: [{id, caption?, date_taken?, width, height}]}` — `count` begrenzt auf `frame.max_count` (Standard 100), Vorgabe `frame.count` (20) | — |
| `GET /api/frame/image/{id}?token=&max_edge=` | das Foto-JPEG — Original, verkleinert auf `max_edge` (begrenzt durch `frame.max_edge`, Standard 1920), oder das gespeicherte Vorschaubild, falls das Original nicht erreichbar ist | lang, unveränderlich |
| `GET /api/frame/next?token=` | ein zufälliges kuratiertes JPEG, bei jedem Aufruf ein anderes — für einfache Rahmen und Home Assistant | `no-store` |

### Token generieren

Ein Token ist eine beliebige Zeichenfolge Ihrer Wahl. Verwenden Sie eine lange zufällige und behandeln Sie sie wie ein Passwort:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Tragen Sie es in `frame.tokens` in `scoring_config.json` ein. Führen Sie eines pro Gerät auf; entfernen Sie eines, um es zu widerrufen:

```json
"frame": {
  "tokens": ["Xu8w…your-random-token…"],
  "count": 20,
  "min_aggregate": 7.0,
  "max_edge": 1920,
  "favorites_only": false,
  "categories": []
}
```

### Home-Assistant-Rezept

`/api/frame/next` funktioniert als [generische Kamera](https://www.home-assistant.io/integrations/generic/) von Home Assistant; jede Aktualisierung holt eine neue Aufnahme:

```yaml
camera:
  - platform: generic
    name: Facet Frame
    still_image_url: "http://facet.local:5000/api/frame/next?token=Xu8w…your-random-token…"
    verify_ssl: false
    framerate: 0.05  # alle ~20 s aktualisieren
```

Fügen Sie die Kamera einer Karte „Picture Glance / Picture Entity“ hinzu, um einen sich selbst aktualisierenden Bilderrahmen zu erhalten.

Für einen Client im **ImmichFrame-Stil**, der eine eigene Diashow abspielt, rufen Sie `GET /api/frame/photos?token=…&count=30` für IDs ab und holen dann jedes `GET /api/frame/image/{id}?token=…&max_edge=1920`. IDs sind stabil und Bilder werden langfristig zwischengespeichert, sodass jedes Foto nur einmal geladen wird.

## Automatischer Upload vom Telefon

Schieben Sie Fotos von Ihrem Telefon in Facet. Ein kleiner **WebDAV**-Server unter `/dav` lässt PhotoSync (oder jeden WebDAV-Client) in ein **Eingangsverzeichnis** hochladen. Legen Sie das Eingangsverzeichnis in ein gescanntes Verzeichnis und führen Sie dafür `facet.py --watch` aus: Jedes Foto wird beim Eintreffen bewertet.

- **Getrennte Zugangsdaten.** Der Zugriff nutzt HTTP Basic mit einem geteilten Geräte-Login aus dem Block `upload` (`upload.username` / `upload.password`), nicht mit einem Benutzerkonto.
- **Standardmäßig aus.** `/dav` liefert **404**, bis `upload.username`, `upload.password` und `upload.inbox_dir` alle gesetzt sind.
- **Auf das Eingangsverzeichnis beschränkt.** Nichts außerhalb von `upload.inbox_dir` ist erreichbar. Dateien sind auf `upload.max_file_mb` begrenzt (Standard 500).
- **Methoden:** `OPTIONS`, `PROPFIND` (Tiefe 0/1), `MKCOL`, `PUT`, `MOVE`, `DELETE`, `GET`, `HEAD`. `LOCK`/`UNLOCK` sind nicht implementiert; Upload-Apps funktionieren ohne sie.

### Konfiguration

```json
"upload": {
  "username": "phone",
  "password": "…a-long-random-shared-secret…",
  "inbox_dir": "/photos/inbox",
  "max_file_mb": 500
}
```

Halten Sie `inbox_dir` unter einem gescannten Verzeichnis, damit `--watch` Uploads sieht:

```bash
python facet.py /photos --watch
```

### PhotoSync-Rezept

1. Fügen Sie in PhotoSync eine **WebDAV**-Konfiguration hinzu (Configure → Add Configuration → WebDAV).
2. **URL / Server**: `http://<host>:5000/dav/` (`https://` hinter einem Reverse-Proxy).
3. **Benutzername / Passwort**: Ihr `upload.username` / `upload.password`.
4. **Zielordner**: das Stammverzeichnis (`/`) des Eingangsverzeichnisses oder ein Unterordner.
5. Überwachen Sie auf dem Facet-Host das Eingangsverzeichnis, damit Uploads bewertet werden:

   ```bash
   python facet.py /photos --watch
   ```

### Curl-Schnelltest

```bash
curl -T photo.jpg -u phone:'…a-long-random-shared-secret…' http://<host>:5000/dav/photo.jpg
```

`201 Created` (oder `204 No Content` beim Überschreiben) bedeutet, dass die Datei das Eingangsverzeichnis erreicht hat; `--watch` bewertet sie kurz darauf.

## Konfiguration

### Anzeigeeinstellungen

```json
{
  "viewer": {
    "display": {
      "tags_per_photo": 4,
      "card_width_px": 168,
      "image_width_px": 160,
      "image_jpeg_quality": 96
    }
  }
}
```

### Paginierung

```json
{
  "viewer": {
    "pagination": {
      "default_per_page": 64
    }
  }
}
```

### Dropdown-Limits

```json
{
  "viewer": {
    "dropdowns": {
      "max_cameras": 50,
      "max_lenses": 50,
      "max_persons": 50,
      "max_tags": 20,
      "min_photos_for_person": 10
    }
  }
}
```

Erhöhen Sie `min_photos_for_person`, um Personen mit wenigen Fotos aus der Filter-Auswahlliste auszublenden.

### Qualitätsschwellen

```json
{
  "viewer": {
    "quality_thresholds": {
      "good": 6,
      "great": 7,
      "excellent": 8,
      "best": 9
    }
  }
}
```

### Standardfilter

```json
{
  "viewer": {
    "defaults": {
      "hide_blinks": true,
      "hide_bursts": true,
      "hide_duplicates": true,
      "hide_brackets": true,
      "hide_panoramas": true,
      "hide_details": true,
      "hide_rejected": true,
      "sort": "aggregate",
      "sort_direction": "DESC",
      "type": ""
    },
    "default_category": ""
  }
}
```

### Gewichte für „Beste Auswahl“

```json
{
  "viewer": {
    "photo_types": {
      "top_picks_min_score": 7,
      "top_picks_min_face_ratio": 0.2,
      "top_picks_weights": {
        "aggregate_percent": 30,
        "aesthetic_percent": 28,
        "composition_percent": 18,
        "face_quality_percent": 24
      }
    }
  }
}
```

## Performance

### Große Datenbanken (50k+ Fotos)

Führen Sie diese für bessere Performance aus:

```bash
python database.py --migrate-tags    # 10-50x schnellere Tag-Abfragen
python database.py --refresh-stats   # Aggregationen vorberechnen
python database.py --optimize        # Datenbank defragmentieren
```

`--migrate-tags` ist nur einmal nötig. Danach halten Scans, `--recompute-tags`, `--recompute-tags-vlm` und `tag_existing.py` die Tag-Tabelle aktuell. Bis Sie es ausführen, nutzen Tag-Filter einen langsameren Ersatzweg.

Prüfen Sie den Statistik-Cache (5 Minuten Lebensdauer) mit:

```bash
python database.py --stats-info
```

### Galerie-Indizes und Zähler-Cache

Facet legt Indizes an, die Galerieseiten und Zähler bei großen Bibliotheken schnell halten. Bei einer Bibliothek mit 130.000 Fotos senkten sie die Standardseite von etwa 1,2 s auf 26 bis 38 ms bei zwischengespeichertem Zähler und auf etwa 104 ms direkt nach einer Datenbankänderung.

- **Einmal im Hintergrund gebaut.** Der erste Viewer-Start nach einem Upgrade baut fehlende Indizes, während der Viewer bereits arbeitet. Bei einer Bibliothek mit 130.000 Fotos brauchte der größte Index 45 bis 55 s zum Bauen und etwa 106 bis 111 MB zusätzliche Datenbankgröße. Während ein Index geschrieben wird, wird das Speichern kurz mit der Meldung „gleich nochmal versuchen“ abgelehnt. Ein Scan mit `python facet.py` oder ein Lauf von `python database.py` baut sie stattdessen zuerst. Siehe [DEPLOYMENT.md](DEPLOYMENT.md#viewer-start-und-die-galerie-indizes) für Schreibvorgänge während des Aufbaus, Herunterfahren, `--workers N` und Docker.
- **Schreiben wird etwas langsamer**: etwa 0,5 bis 0,7 ms mehr pro Zeile, wenn sich eine von diesen Indizes getragene Spalte ändert.
- **Zähler-Cache.** Galerie-Zähler werden 5 Minuten zwischengespeichert. Jede Änderung durch einen Prozess auf demselben Host (auch `--detect-junk` und `--recompute-*`) aktualisiert sie. Eine Änderung von einem anderen Rechner über eine Netzwerkfreigabe zeigt sich, wenn der Cache abläuft.

## API-Endpunkte

Die Referenz der HTTP-API steht in [API.md](../API.md). Interaktive Dokumentation liefert `/api/docs`.

## JPEG-XL-Fotos

Facet scannt JPEG XL (`.jxl`) mit der Kernabhängigkeit `imagecodecs`, die in Standardinstallationen und Docker enthalten ist. Es ist kein Zusatzpaket nötig; Scans überspringen `.jxl` nur, wenn dieser Codec fehlt.

- **Anzeige.** Browser, die `image/jxl` akzeptieren, erhalten die Originaldatei, andere ein JPEG. Galerie-Vorschaubilder sind JPEGs.
- **Metadaten.** Originale bleiben `.jxl`. Bewertungsänderungen gehen in Sidecars, nicht in die Datei.
- **Animationen.** Nur das erste Bild wird verwendet.
- **Farbe.** Eine JXL, die ein JPEG rekonstruiert, behält ihr ICC-Profil, und Vorschauen werden nach sRGB konvertiert. Bei nativem JXL ist das eingebettete Farbprofil nicht verfügbar, sodass Bewertungen und Vorschauen von Wide-Gamut- oder HDR-Dateien farblich ungenau sein können. Original-Downloads behalten Bittiefe und Profil.
- **Grenzen.** Die Dekodierung prüft das Pillow-Pixellimit, bevor Pixel angelegt werden, und die Prüfung des Container-Headers stoppt bei 4.096 Boxen. Kodiertes und entpacktes EXIF sind jeweils auf 16 MiB begrenzt; zu großes EXIF wird verworfen, das Bild bleibt lesbar. Es werden höchstens fünf JPEG-Konvertierungen zwischengespeichert. Dateien mit nicht unterstützten Zusatzkanal-Layouts werden abgelehnt.

## Fehlerbehebung

| Problem | Lösung |
|-------|----------|
| Langsames Laden der Seite | `--migrate-tags` und `--optimize` ausführen |
| Filter werden nicht angezeigt | `--stats-info` prüfen, `--refresh-stats` ausführen |
| Personenfilter leer | `--cluster-faces-incremental` ausführen |
| Vergleichen-Schaltfläche fehlt | Ein nicht leeres `edition_password` setzen (Einzelbenutzer) oder die Rolle `admin`/`superadmin` verwenden (Mehrbenutzer) |
| Passwort funktioniert nicht | `viewer.password` prüfen (Einzelbenutzer) oder Passwort-Hash verifizieren (Mehrbenutzer) |
| Benutzer sieht keine Fotos | `directories` in seiner Benutzerkonfiguration und `shared_directories` prüfen |
| Scan-Schaltfläche fehlt | Erfordert `viewer.features.show_scan_button: true` plus Scan-Zugriff — siehe [Scan auslösen](#scan-auslösen) |
| Suche liefert keine Ergebnisse | Sicherstellen, dass Fotos `clip_embedding`-Daten haben (zuerst Bewertung ausführen) |
| Suche meldet, die Apple-Silicon-Beschleunigung sei ausgelastet | Erneut versuchen, sobald die aktuelle Modellaufgabe endet |
| VLM-Kritik nicht verfügbar | Erfordert das Profil 16gb/24gb, `viewer.features.show_vlm_critique: true` und eine Bearbeitungssitzung |
| Karte zeigt keine Fotos | `--extract-gps` ausführen; prüfen, ob Fotos EXIF-GPS-Daten haben |
| Bildunterschriften werden nicht erzeugt | Erfordert das VRAM-Profil 16gb/24gb für VLM-Bildbeschreibung |
| Zeitleiste leer | Sicherstellen, dass Fotos `date_taken`-Werte haben |
| Port 5000 belegt | `python viewer.py --port 5001` ausführen (oder `PORT=5001` setzen). Unter macOS belegt der AirPlay-Empfänger 5000: Wählen Sie einen anderen Port oder schalten Sie ihn unter Systemeinstellungen → Allgemein → AirDrop & Handoff aus. |

### Gespeicherte manuelle Gesichtsmarkierungen prüfen

Finden Sie Fotos, deren gespeicherte Gesichtsrechtecke eine Prüfung brauchen. Aktivieren Sie im Tab Prüfen der Galerie-Seitenleiste **Manuelle Gesichter prüfen** (Editoren). Öffnen Sie den Gesichtseditor eines Fotos und passen Sie jedes markierte Rechteck an und speichern Sie es, oder löschen Sie es. Das Foto verlässt dann die Liste. Der Filter funktioniert in intelligenten Alben und bei Auswahlen der ganzen Ansicht und erscheint als entfernbarer Chip.

- Die Liste spiegelt den letzten Scan oder die letzte Editor-Prüfung, keine Live-Dateiüberwachung. Scans prüfen Fotos mit manuellen Markierungen auch bei ausgeschalteter Gesichtserkennung.
- Das Öffnen des Editors prüft das Original erneut und ist maßgeblich.
- Durch ein Neuverknüpfen übernommene Markierungen (`relink_unverified`) bleiben markiert, bis sie im Editor erneut gespeichert werden.
- Das Prüfen ändert nie Originaldateien. Exporte und Aktualisierungen der Viewer-Datenbank behalten den Prüfstatus.

## Aufnahmedatum korrigieren

Beheben Sie eine falsch gehende Kamerauhr. Wählen Sie im Bearbeitungsmodus **Aufnahmedatum korrigieren** über das Kalendersymbol neben dem Datum des Fotos oder über die Auswahlleiste der Galerie. Bis zu 1000 sichtbare Fotos, „Alle in der Ansicht auswählen“ eingeschlossen.

- **Verschieben um** (Standard): Wählen Sie **Früher** oder **Später** und geben Sie Tage, Stunden, Minuten und Sekunden ein. Standard: 1 Stunde später. Die Schnellschaltflächen −1 h, +1 h, −1 d und +1 d addieren sich zur Verschiebung.
- **Genaue Zeit festlegen**: Geben Sie Datum und Uhrzeit eines Referenzfotos ein (das geöffnete Foto oder das erste datierte Foto der Auswahl; nicht bei „Alle in der Ansicht auswählen“). Die Verschiebung wird daraus abgeleitet.
- Die Verschiebung muss ungleich null und höchstens ±366 Tage sein.
- Eine Zusammenfassung nennt die Verschiebung („1 h 30 min später“), und die Vorschau zeigt die Zähler für geändert/übersprungen und die ersten 20 alten/neuen Zeitstempel.
- **Korrektur anwenden (N)** wendet sie an. Hat sich zwischenzeitlich etwas geändert, bietet ein Fehler **Vorschau** zum Aktualisieren an.

**Was sich ändert.**

- Die Kamerazeit wird unverändert verschoben: keine Zeitzonen- oder Sommerzeitlogik.
- Nur vollständige Daten der Form `YYYY:MM:DD HH:MM:SS` oder `YYYY-MM-DD[T oder Leerzeichen]HH:MM:SS` werden unterstützt. Unbekannte, reine Datums-, Zeitzonen-/Subsekunden- und ungültige Daten werden übersprungen.
- Korrigierte Daten überstehen erneute Scans und inkrementelle Exporte der Viewer-Datenbank.
- **Dateidatum verwenden** entfernt die Korrektur und liest die Datei neu ein. Kein Dateidatum bedeutet ein unbekanntes Aufnahmedatum.
- Das Anwenden einer Korrektur schreibt nie das Original und ändert nicht dessen Dateizeit. Der XMP-Export schreibt `exif:DateTimeOriginal`; **Metadaten in Datei schreiben** aktualisiert in unterstützten Formaten auch EXIF `DateTimeOriginal`.
- Serien- und Sequenzgruppen werden nicht neu berechnet; führen Sie die Erkennung erneut aus, wenn Sie eine neue Gruppierung brauchen.

Endpunkte: `POST /api/photos/capture_date/preview`, `POST /api/photos/capture_date/apply`, `DELETE /api/photo/capture_date?path=` — siehe [API.md](../API.md).

## Änderungsverlauf

Prüfen und widerrufen Sie Ihre letzten Änderungen in der gesamten Bibliothek. Öffnen Sie im Bearbeitungsmodus **Änderungsverlauf** über das Uhrsymbol in der Hauptnavigation (nach „Heute vor Jahren“). Klappen Sie einen Eintrag auf, um die genauen Werte vorher/nachher zu sehen, und wählen Sie dann **Diesen Eintrag zurücksetzen**.

- **Was erfasst wird:** GPS, Aufnahmedaten, Sichtungsentscheidungen, Sterne, Favoriten und manuelle Stapel. Nicht Dateien oder Gesichtserkennung.
- GPS und Aufnahmedaten sind geteilte Bibliothekswerte. Sichtungsentscheidungen, Sterne und Favoriten gehören Ihnen.
- Das kurze Rückgängig und die Assistenten-Aktivitätsliste sind davon getrennt.
- **Grenzen.** Die letzten **50 Einträge pro Konto**, jeder mit bis zu **1000 Fotos und 1 MiB** an Werten. Größere gefilterte Sichtungsaktionen werden in Teile aufgeteilt; das Zurücksetzen stellt einen Teil wieder her. Ein Ersatz eines Stapels kann in einem Eintrag bis zu 2000 Fotos umfassen.
- Der Verlauf übersteht Neustarts und inkrementelle Aktualisierungen der Viewer-Datenbank. Ein frischer/vollständiger Viewer-Export beginnt leer. Er wird nicht mit einer anderen Datenbank synchronisiert.
- **Das Zurücksetzen gilt ganz oder gar nicht.** Es wird abgelehnt, wenn sich der Wert irgendeines Fotos seither geändert hat, auch wenn er zurückgeändert wurde. Die private Sichtungsänderung eines anderen Kontos blockiert Ihre nicht. Erneute Scans, Importe und Rückgängig können ältere Einträge ebenfalls ungültig machen.
- Ein Eintrag wird ausgeblendet, wenn eines seiner Fotos gelöscht wurde oder für Sie nicht mehr sichtbar ist.
- Ein Zurücksetzen fügt einen eigenen Eintrag hinzu und markiert das Original als zurückgesetzt.

## Gesichter ohne Namen

Finden Sie nicht zugewiesene Gesichter und unbenannte Personengruppen: `Filter → Personen → Gesichter ohne Namen` (`faces_need_names=true`). Mit + weisen Sie ein Gesicht zu, oder benennen Sie eine Gruppe unter Personen. Fotos ohne erkannte Gesichter sind ausgeschlossen.

Nur-Lese-Benutzer können diesen Filter durchsuchen; Zuweisen oder Benennen erfordert Bearbeitungszugriff.

## Personen zuweisen

Die Auswahl **Gesicht einer Person zuweisen** listet zuerst bis zu 12 Personen, die Sie in diesem Browser zuletzt zugewiesen haben (pro angemeldeter Identität). Andere benannte Personen folgen nach Gesichtsanzahl in Fotos, die Sie sehen können. Suche und Blättern umfassen alle.

- Eine Person gilt erst nach einer erfolgreichen Zuweisung oder dem Speichern eines manuellen Gesichts als zuletzt verwendet.
- Lokal werden nur Personen-IDs gespeichert. Das Abmelden leert die Liste.

## Metadaten und Vorschau aktualisieren

Lesen Sie die Metadaten eines Fotos neu ein und bauen Sie seine Vorschau ohne vollständigen erneuten Scan neu auf. Manuelle Anmerkungen, Bewertungen, Gesichter und KI-Wertungen bleiben. Originale werden nie beschrieben. Scannen Sie neu, wenn geänderte Pixel neue Wertungen oder eine neue Gesichtserkennung brauchen.

- Bis zu 100 ausgewählte Fotos; Auswahlen der ganzen Ansicht werden nicht unterstützt.
- Fehlende Quellwerte löschen gespeicherte nicht. Ohne `exiftool` wird nur die Vorschau aktualisiert.
- Manuelles GPS und manuelle Daten bleiben erhalten.
- Es wird abgelehnt, solange ein anderer Bibliotheksauftrag läuft; versuchen Sie es später erneut.
- Jedes Foto wird einzeln gespeichert; ein erneuter Versuch verarbeitet die Fehlschläge.
- Bis zum nächsten erneuten Scan verwenden Histogramme die neue Vorschau, und die Farbähnlichkeitssuche überspringt das Foto.
