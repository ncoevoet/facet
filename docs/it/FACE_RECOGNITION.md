# Riconoscimento facciale

> 🌐 [English](../FACE_RECOGNITION.md) · [Français](../fr/FACE_RECOGNITION.md) · [Deutsch](../de/FACE_RECOGNITION.md) · **Italiano** · [Español](../es/FACE_RECOGNITION.md) · [Português](../pt/FACE_RECOGNITION.md)

Facet utilizza InsightFace per il rilevamento dei volti e HDBSCAN per raggruppare i volti in persone.

## Panoramica

1. **Rilevamento** - Il modello InsightFace buffalo_l rileva i volti ed estrae embedding a 512 dimensioni
2. **Raggruppamento** - HDBSCAN raggruppa gli embedding simili in cluster di persone
3. **Gestione** - Visualizzatore web per unire, rinominare e organizzare le persone

## Flusso di lavoro completo

### Passo 1: Estrarre i volti

Durante la scansione delle foto, i volti vengono estratti automaticamente:

```bash
python facet.py /path/to/photos
```

Per le foto esistenti senza volti:

```bash
python facet.py --extract-faces-gpu-incremental  # Solo foto nuove
python facet.py --extract-faces-gpu-force        # Tutte le foto (elimina quelle esistenti)
```

### Passo 2: Raggruppare i volti

Raggruppa i volti simili in persone:

```bash
python facet.py --cluster-faces-incremental  # Mantiene le persone esistenti
```

**Modalità di raggruppamento:**

| Comando | Comportamento |
|---------|----------|
| `--cluster-faces-incremental` | Conserva tutte le persone, abbina le nuove a quelle esistenti |
| `--cluster-faces-incremental-named` | Conserva solo le persone con nome |
| `--cluster-faces-force` | Elimina tutte le persone, raggruppamento completo da zero |

### Passo 3: Esaminare e unire

Trova i cluster di persone duplicati:

```bash
python facet.py --suggest-person-merges
python facet.py --suggest-person-merges --merge-threshold 0.7  # Più restrittivo
```

Apre il browser sulla pagina dei suggerimenti di unione.

### Passo 4: Esaminare i suggerimenti di unione

L'interfaccia web all'indirizzo `/merge-suggestions` mostra coppie di cluster di persone che potrebbero essere lo stesso individuo:

- Regola il **cursore della soglia di somiglianza** per controllare quanto i suggerimenti debbano essere conservativi
- Esamina ciascun suggerimento affiancato alle miniature dei volti
- **Unione con un clic** per combinare due persone, oppure **unione in blocco** per elaborare più suggerimenti contemporaneamente
- Disponibile anche tramite CLI: `python facet.py --suggest-person-merges --merge-threshold 0.7`

### Passo 5: Gestione manuale

Nel visualizzatore web:
- Accedi a `/persons` per la gestione delle persone
- Unione: seleziona la persona di origine, clicca su quella di destinazione, conferma
- Unione in blocco: seleziona più persone e uniscile in un'unica destinazione
- Divisione: sposta un sottoinsieme dei volti di una persona in una nuova persona (se l'origine rimane vuota, viene eliminata)
- Nascondi: contrassegna un cluster come `is_hidden` per escluderlo dall'elenco, dai filtri e dai suggerimenti di unione (reversibile)
- Rinomina: clicca sul nome della persona per modificarlo in linea
- Elimina: rimuovi il cluster della persona

## Configurazione

### Rilevamento dei volti

```json
{
  "face_detection": {
    "min_confidence_percent": 65,
    "min_face_size": 20,
    "blink_ear_threshold": 0.28
  }
}
```

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `min_confidence_percent` | `65` | Confidenza minima di rilevamento |
| `min_face_size` | `20` | Dimensione minima del volto in pixel |
| `blink_ear_threshold` | `0.28` | Eye Aspect Ratio per il rilevamento degli occhi chiusi |

### Raggruppamento dei volti

```json
{
  "face_clustering": {
    "enabled": true,
    "min_faces_per_person": 2,
    "min_samples": 2,
    "auto_merge_distance_percent": 15,
    "clustering_algorithm": "best",
    "leaf_size": 40,
    "use_gpu": "auto",
    "merge_threshold": 0.6
  }
}
```

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `min_faces_per_person` | `2` | Numero minimo di foto per creare una persona |
| `min_samples` | `2` | Parametro min_samples di HDBSCAN |
| `merge_threshold` | `0.6` | Somiglianza del centroide per l'abbinamento |
| `use_gpu` | `"auto"` | Modalità GPU: `auto`, `always`, `never` |

### Elaborazione dei volti

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
    "refill_batch_size": 100
  }
}
```

## Algoritmi di raggruppamento

Per il raggruppamento su CPU, scegli l'algoritmo in base alla dimensione del dataset:

| Algoritmo | Complessità | Ideale per |
|-----------|------------|----------|
| `boruvka_balltree` | O(n log n) | Dati ad alta dimensionalità (consigliato per oltre 50.000 volti) |
| `boruvka_kdtree` | O(n log n) | Dati a bassa dimensionalità |
| `prims_balltree` | O(n²) | Dataset piccoli, con memoria limitata |
| `prims_kdtree` | O(n²) | Dataset piccoli |
| `best` | Auto | Lascia decidere a HDBSCAN |

**Nota sulle prestazioni:** per dataset di grandi dimensioni, usa `boruvka_balltree`. Con 80.000 volti viene completato in 2-5 minuti, mentre gli algoritmi esatti possono bloccarsi.

## Raggruppamento su GPU (cuML)

Per dataset di grandi dimensioni (oltre 80.000 volti), il raggruppamento su GPU tramite RAPIDS cuML è più veloce rispetto alla CPU.

### Installazione

```bash
# Conda
conda install -c rapidsai -c conda-forge -c nvidia cuml cuda-version=12.0

# Pip
pip install --extra-index-url https://pypi.nvidia.com/ "cuml-cu12"
```

### Configurazione

```json
{
  "face_clustering": {
    "use_gpu": "auto"
  }
}
```

| Modalità | Comportamento |
|------|----------|
| `"auto"` | Usa la GPU se cuML è disponibile, altrimenti ripiega sulla CPU |
| `"always"` | Tenta la GPU, avvisa e ripiega se non disponibile |
| `"never"` | Usa sempre la CPU |

**Nota:** cuML utilizza la propria implementazione di HDBSCAN. I parametri `algorithm` e `leaf_size` si applicano solo al raggruppamento su CPU.

## Rilevamento degli occhi chiusi

Utilizza l'Eye Aspect Ratio (EAR) dai 106 punti di riferimento di InsightFace.

### Come funziona

L'EAR misura il rapporto tra l'altezza e la larghezza dell'occhio. Quando gli occhi si chiudono, l'EAR scende al di sotto della soglia.

### Configurazione

```json
{
  "face_detection": {
    "blink_ear_threshold": 0.28
  }
}
```

Soglia più bassa = rilevamento più rigoroso (più foto contrassegnate come occhi chiusi).

### Ricalcolo dopo una modifica della soglia

```bash
python facet.py --recompute-blinks
```

Elabora solo le foto con volti, senza bisogno di GPU.

## Segnali di espressione per volto (occhi aperti + sorriso)

Ogni riga di volto memorizza due segnali continui su scala 0-10 usati dal pannello volti della
selezione e dagli aggregati a livello di foto: `eyes_open_score` (10 = completamente aperti, 0 =
completamente chiusi) e `smile_score` (5 = neutro, 10 = sorriso ampio, 0 = espressione accigliata).

Due motori li producono, sulla stessa scala 0-10:

1. **Geometria (sempre disponibile).** Derivato dai 106 punti di riferimento InsightFace
   memorizzati: l'Eye Aspect Ratio per gli occhi aperti, il sollevamento degli angoli della bocca
   per il sorriso. Pura geometria, quindi `--recompute-face-signals` può ricalcolarli dai punti di
   riferimento memorizzati senza pixel e senza GPU.
2. **Blendshape MediaPipe (opzionale, basato sull'aspetto).** Durante la scansione / l'estrazione
   dei volti, un ritaglio generoso di ogni volto viene elaborato dal MediaPipe Face Landmarker, i
   cui blendshape in stile ARKit (`eyeBlink*`, `mouthSmile*`, `mouthFrown*`) si mappano sulle
   stesse scale. L'aspetto batte la geometria dei punti di riferimento su occhi chiusi, sorrisi
   sottili e teste non frontali, quindi quando un volto viene valutato tramite MediaPipe
   **sostituisce** il valore geometrico. Se MediaPipe o il suo pacchetto modello sono assenti, o il
   ritaglio del volto è troppo piccolo / non rilevato, viene mantenuto il valore geometrico — il
   comportamento è identico a un'installazione solo geometria.

### Installare MediaPipe

MediaPipe è opzionale e **deve** essere installato senza il suo `opencv-contrib-python` incluso,
che installerebbe un secondo namespace `cv2` accanto a quello di Facet (`opencv-python`):

```bash
pip install mediapipe==0.10.35 --no-deps
pip install absl-py flatbuffers
```

Non eseguire mai un semplice `pip install mediapipe`.

### Pacchetto modello

Il pacchetto `face_landmarker.task` (~3,6 MiB, Apache-2.0) viene scaricato automaticamente al primo
utilizzo in `pretrained_models/face_landmarker.task`. Se la macchina è offline, scaricalo
manualmente da
`https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task`
e posizionalo in quel percorso. Un download non riuscito registra un avviso una sola volta e
ripiega sui punteggi geometrici.

### Configurazione

```json
{
  "face_detection": {
    "blendshapes": {
      "enabled": true,
      "min_crop_size": 192
    }
  }
}
```

- `enabled` (predefinito `true`): usa i punteggi blendshape ogni volta che MediaPipe e il pacchetto
  modello sono disponibili; altrimenti il fallback geometrico si attiva automaticamente. Impostare
  su `false` per forzare la sola geometria.
- `min_crop_size` (predefinito `192`): i volti il cui ritaglio con padding è più piccolo di questo
  valore (px, lato più corto) ripiegano sulla geometria invece di ingrandire un volto minuscolo.

### Ricalcolo

`--recompute-face-signals` ricalcola i segnali per volto solo dai punti di riferimento memorizzati
— è **solo geometria** e non esegue MediaPipe (non viene letto alcun pixel). Per aggiornare i
punteggi basati sull'aspetto, ri-estrarre i volti (`--extract-faces-gpu-force`) in modo che i
ritagli a piena risoluzione vengano rianalizzati.

## Miniature dei volti

Le miniature sono archiviate nel database per una visualizzazione rapida.

### Archiviazione

- Generate durante la scansione a partire dalle immagini a piena risoluzione
- Archiviate nella colonna `faces.face_thumbnail` come BLOB JPEG (~5-10KB ciascuna)
- Utilizzate dal raggruppamento e dal visualizzatore invece di essere rigenerate

### Rigenerazione

```bash
# Genera le miniature mancanti
python facet.py --refill-face-thumbnails-incremental

# Rigenera TUTTE le miniature
python facet.py --refill-face-thumbnails-force
```

Entrambi i comandi utilizzano l'elaborazione parallela per velocizzare le operazioni.

## Schema del database

### Tabella faces

| Colonna | Tipo | Descrizione |
|--------|------|-------------|
| `id` | INTEGER | Chiave primaria |
| `photo_path` | TEXT | Chiave esterna verso photos |
| `face_index` | INTEGER | Indice all'interno della foto |
| `embedding` | BLOB | Embedding del volto a 512 dimensioni |
| `bbox_x1`, `bbox_y1`, `bbox_x2`, `bbox_y2` | INTEGER | Angoli del riquadro di delimitazione |
| `confidence` | REAL | Confidenza del rilevamento |
| `person_id` | INTEGER | Chiave esterna verso persons |
| `face_thumbnail` | BLOB | Miniatura JPEG |
| `landmark_2d_106` | BLOB | 106 punti di riferimento (rilevamento degli occhi chiusi) |
| `embedding_model` | TEXT | Tag del modello di riconoscimento (predefinito `arcface_buffalo_l`) |

### Tabella persons

| Colonna | Tipo | Descrizione |
|--------|------|-------------|
| `id` | INTEGER | Chiave primaria |
| `name` | TEXT | Nome della persona (NULL = raggruppata automaticamente) |
| `representative_face_id` | INTEGER | Volto migliore per l'avatar |
| `face_count` | INTEGER | Numero di volti |
| `centroid` | BLOB | Embedding del centroide del cluster |
| `auto_clustered` | INTEGER | 1 se generata automaticamente |
| `face_thumbnail` | BLOB | Miniatura avatar della persona |
| `is_hidden` | INTEGER | 1 = esclusa da filtri/suggerimenti |

## Modalità incrementale e forzata

### Raggruppamento incrementale

- Conserva tutte le persone esistenti (con nome e raggruppate automaticamente)
- Raggruppa solo i volti nuovi e non assegnati
- Abbina i nuovi cluster alle persone esistenti tramite la somiglianza del centroide
- Aggiorna i centroidi dopo l'unione

**Usare quando:** si aggiungono nuove foto a una raccolta esistente

### Raggruppamento forzato

- Elimina TUTTE le persone, comprese quelle con nome
- Raggruppamento completo da zero

**Usare quando:** si ricomincia da capo o si apportano modifiche importanti all'algoritmo

### Raggruppamento incrementale-con nomi

- Conserva solo le persone con nome
- Elimina le persone raggruppate automaticamente
- Raggruppa nuovamente tutti i volti senza nome

**Usare quando:** si mantengono i nomi curati aggiornando i cluster rilevati automaticamente

## Integrazione nel visualizzatore

### Filtro per persona

- Il menu a tendina mostra le persone con le miniature dei volti
- Filtra la galleria per persona

### Galleria della persona

- Clicca su una persona nel menu a tendina per visualizzare tutte le sue foto
- URL: `/person/<id>`

### Pagina Gestisci persone

Accessibile tramite il pulsante nell'intestazione o `/persons`:

- **Vista a griglia** - Tutte le persone riconosciute
- **Unione** - Seleziona l'origine, clicca sulla destinazione, conferma
- **Unione in blocco** - Seleziona più persone e uniscile in un'unica destinazione
- **Divisione** - Sposta i volti selezionati in una nuova persona
- **Nascondi** - Escludi un cluster dall'elenco, dai filtri e dai suggerimenti di unione
- **Elimina** - Rimuovi il cluster della persona
- **Rinomina** - Clicca sul nome per modificarlo in linea

### Creare una persona

Le persone non derivano più solo dal clustering — puoi nominare un volto sfuggito al clusterer
direttamente dalla galleria:

1. Su una scheda foto, apri le azioni sulla persona e scegli un volto non assegnato.
2. Nel selettore di persona, scegli **Crea nuova persona** e digita un nome.
3. Il volto viene collegato alla nuova persona (creata manualmente, `auto_clustered = 0`) in
   un'unica chiamata.

Endpoint: `POST /api/persons` (riservato all'edizione), corpo
`{ "name": "<nome>", "face_ids": [<id>, ...] }`. Il nome è obbligatorio (non vuoto dopo il trim). I
volti già appartenenti a un'altra persona vengono riassegnati, e qualsiasi vecchia persona rimasta
senza volti viene eliminata — la stessa semantica dell'assegnazione dei volti. In modalità
multiutente, chi effettua la chiamata può collegare solo volti provenienti da foto all'interno
delle proprie directory (o condivise); un volto al di fuori di questo ambito viene rifiutato come
non trovato.

### Da nominare

La pagina Gestisci persone mostra le persone raggruppate automaticamente che meritano di essere
nominate in una sezione **Da nominare**: cluster senza nome (`name IS NULL`, `auto_clustered = 1`)
con almeno `viewer.persons.needs_naming_min_faces` volti (predefinito `5`), ciascuno con un campo
nome in linea in modo che i cluster numerosi possano essere nominati senza doverli cercare. Servito
da `GET /api/persons/needs_naming?min_faces=N`.

### Pagina Suggerimenti di unione

Accessibile tramite `/merge-suggestions` o il pulsante "Suggerimenti di unione" nella pagina Gestisci persone:

- Mostra coppie di persone con embedding facciali simili che potrebbero essere lo stesso individuo
- **Cursore della soglia** — controlla il limite di somiglianza (più basso = più suggerimenti)
- **Unione con un clic** — unisci immediatamente una coppia suggerita
- **Unione in blocco** — seleziona più suggerimenti e uniscili tutti in una volta

### Schede foto

- Piccole miniature dei volti (avatar) mostrate per le persone riconosciute
- Configurabile tramite `viewer.face_thumbnails.output_size_px`

## Marcatore dello spazio degli embedding (sicurezza del modello di riconoscimento)

Ogni riga di volto porta con sé un tag `embedding_model` (colonna nella tabella `faces`, predefinito
`arcface_buffalo_l` — l'attuale modello di riconoscimento InsightFace `buffalo_l` / ArcFace `w600k_r50`).
Gli embedding prodotti da modelli di riconoscimento **diversi** vivono
in **spazi vettoriali incompatibili** e non devono mai essere raggruppati insieme — farlo
produce silenziosamente persone errate senza alcun errore.

`FaceClusterer.load_embeddings()` carica quindi solo lo spazio di embedding **attivo**
(`ACTIVE_EMBEDDING_MODEL` in `faces/clusterer.py`; un tag `NULL` viene trattato
come lo spazio ArcFace legacy) e registra un avviso ben visibile se sono presenti
volti di qualsiasi altro spazio, che vengono esclusi. Si tratta di una protezione per la compatibilità futura:
rende sicura per costruzione una futura sostituzione del modello di riconoscimento.

### Sostituzione del modello di riconoscimento (es. AdaFace) — piano differito

Un aggiornamento qualitativo come **AdaFace** (margine adattivo alla qualità, miglior raggruppamento
dei volti sfocati/spontanei) è integrabile come backend opzionale a 512 dimensioni (stesso percorso
di archiviazione, stesso HDBSCAN), ma **non è ancora implementato** perché non può essere
validato senza dati reali. Per farlo correttamente è necessario:

1. **Pesi + backbone** — un checkpoint AdaFace (es. `adaface_ir101_webface12m`)
   più il relativo backbone IResNet; un nuovo download nella cache dei modelli.
2. **Ritagli allineati** — calcolare l'embedding a partire da un ritaglio allineato
   `norm_crop(img, face.kps, 112)` 112×112 al momento dell'estrazione (i kps esistono sull'oggetto
   `face` di InsightFace ma non vengono persistiti, quindi AdaFace non può essere applicato retroattivamente offline —
   deve essere eseguito durante l'estrazione). Verificare che BGR/normalizzazione corrispondano al checkpoint.
3. **Interruttore di configurazione** — aggiungere `face_detection.recognition_model: arcface|adaface`
   e risolvere `ACTIVE_EMBEDDING_MODEL` da esso; taggare di conseguenza i nuovi volti.
4. **Ri-estrazione completa + ri-raggruppamento** — `--extract-faces-gpu-force` quindi
   `--cluster-faces-force`, perché gli embedding ArcFace e AdaFace non sono
   confrontabili. Il marcatore dello spazio degli embedding descritto sopra impedisce a un database parzialmente migrato di
   raggruppare silenziosamente insieme i due spazi (avvisa ed esclude invece).
5. **Validazione della qualità** — misurare la qualità dei cluster rispetto a identità etichettate;
   "viene eseguito ed emette vettori a 512 dimensioni" non dimostra che il preprocessing sia corretto.

## Risoluzione dei problemi

| Problema | Soluzione |
|-------|----------|
| Il raggruppamento si blocca | Usa l'algoritmo `boruvka_balltree` |
| Troppi cluster piccoli | Aumenta `min_faces_per_person` |
| I volti non vengono raggruppati | Diminuisci `merge_threshold` |
| Il raggruppamento su GPU fallisce | Verifica l'installazione di cuML, usa `"never"` per forzare la CPU |
| Miniature mancanti | Esegui `--refill-face-thumbnails-incremental` |
| Rilevamento errato degli occhi chiusi | Regola `blink_ear_threshold`, esegui `--recompute-blinks` |
| Avviso "Excluded N faces from non-active embedding space" | Una modifica del modello di riconoscimento ha lasciato embedding misti — esegui `--extract-faces-gpu-force` quindi `--cluster-faces-force` |
