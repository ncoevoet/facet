# Riconoscimento facciale

> 🌐 [English](../FACE_RECOGNITION.md) · [Français](../fr/FACE_RECOGNITION.md) · [Deutsch](../de/FACE_RECOGNITION.md) · **Italiano** · [Español](../es/FACE_RECOGNITION.md) · [Português](../pt/FACE_RECOGNITION.md) · [简体中文](../zh/FACE_RECOGNITION.md)

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

### Passo 4: Gestione nel visualizzatore

Il lavoro restante avviene nel visualizzatore web, seguendo il flusso **Estrarre → Raggruppare → Unire → Gestire**:

- **Unisci** i cluster duplicati nella pagina Suggerimenti di unione.
- **Gestisci** le persone (unire, unione in blocco, dividere, nascondere, rinominare, eliminare) nella pagina Gestisci persone.

Vedi [Integrazione nel visualizzatore](#integrazione-nel-visualizzatore) per il riferimento completo dell'interfaccia.

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
| `min_face_size` | `20` | Dimensione minima del volto in pixel (solo InsightFace, vedi nota) |
| `blink_ear_threshold` | `0.28` | Eye Aspect Ratio per il rilevamento degli occhi chiusi |

In modalità commerciale il rilevatore YuNet usa valori fissi (confidenza 0,7, 30 px) e ignora `min_confidence_percent` e `min_face_size`.

### Raggruppamento dei volti

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

| Impostazione | Predefinito | Descrizione |
|---------|---------|-------------|
| `min_faces_per_person` | `2` | Numero minimo di foto per creare una persona |
| `min_samples` | `2` | Parametro min_samples di HDBSCAN |
| `thresholds_by_model` | vedi JSON | Per modello: `auto_merge_distance_percent` e `merge_threshold` (ArcFace `15` / `0.6`, SFace `27.5` / `0.65`) |
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

### GPU e CPU non producono gli stessi gruppi

Con gli stessi volti e gli stessi parametri, cuML produce gruppi un po' più numerosi e più piccoli rispetto al raggruppamento su CPU (circa 1,1–1,2 volte tanti). Chi viene raggruppato con chi resta più o meno uguale, ma il *numero* di gruppi differisce tra un'esecuzione su GPU e una su CPU.

**cuML inoltre non è deterministico.** Due esecuzioni su GPU sugli stessi volti danno conteggi di gruppi quasi identici ma etichette diverse.

- **Gli identificatori delle persone non sono riproducibili tra un'esecuzione e l'altra.** Assegna un nome alle persone che ti interessano; le persone con nome restano stabili.
- **Non confrontare due raggruppamenti per etichetta**, confronta l'appartenenza dei volti.

Il raggruppamento su CPU con un `algorithm` fisso è deterministico a parità di input.

### Riraggruppamento e persone già nominate

Tutte le modalità tranne `--cluster-faces-force` conservano i record delle persone, ma tutte ricalcolano la persona di ogni volto.

- **Le interruzioni sono sicure.** Le modifiche vengono scritte in un unico passaggio alla fine; un'esecuzione interrotta prima non cambia nulla.
- **Modifiche nel viewer durante un'esecuzione.** Un volto che riassegni mentre l'esecuzione scrive i risultati (gli ultimi secondi) mantiene la tua scelta, e l'esecuzione registra quanti ne ha saltati. Un salvataggio inviato in quel momento attende l'esecuzione; uno che attende più di 5 s viene rifiutato con «library busy» e va ripetuto. Una modifica fatta prima, mentre i volti vengono ancora raggruppati, viene sovrascritta.

Un gruppo ricostruito viene restituito a una persona esistente quando:

1. il suo embedding medio rientra in `merge_threshold` (0,6 coseno per impostazione predefinita per ArcFace, 0,65 per SFace) rispetto al centroide memorizzato di quella persona, **oppure**
2. almeno metà dei suoi volti apparteneva a quella persona prima dell'esecuzione.

La regola 2 conta per le persone fotografate per molti anni: i loro volti si dividono in sottogruppi compatti lontani dall'unico centroide medio. Senza di essa, la maggior parte dei volti delle persone con nome non tornerebbe a loro.

Poiché la regola 2 segue l'assegnazione precedente, un errore passato viene riportato avanti. Usa `--cluster-faces-force` per ricominciare da zero. Quando i volti di un gruppo si dividono esattamente a metà tra due persone, vince la persona che possiede il volto già assegnato con il numero più basso.

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

## Qualità del volto OFIQ opzionale (modalità commerciale)

In modalità commerciale il modello ristretto di qualità del volto non è disponibile. Come sostituto opzionale, installa `python-ofiq` (binding UNICEF su OFIQ del BSI, ISO/IEC 29794-5; MIT):

```bash
pip install python-ofiq
```

- Offre wheel solo per Linux x86-64 e macOS arm64 (su Windows, usa WSL2 o Docker). Funziona con numpy 2 e OpenCV 4.8+.
- Al primo utilizzo Facet scarica i modelli OFIQ (circa 400 MB, MIT/Apache-2.0, SHA-256 fissato) in `pretrained_models/ofiq/`.
- Il punteggio OFIQ (0-100) viene diviso per 10 e salvato in `face_quality_iqa`. Il valore di una foto è 0,7 x il suo volto peggiore + 0,3 x la media.
- Senza `python-ofiq` la colonna resta NULL e il suo peso viene distribuito sulle altre metriche.

## Segnali di espressione per volto (occhi aperti + sorriso)

Ogni volto memorizza due punteggi 0-10, usati dal pannello volti della selezione e dai punteggi a livello di foto: `eyes_open_score` (10 = completamente aperti, 0 = completamente chiusi) e `smile_score` (5 = neutro, 10 = sorriso ampio, 0 = espressione accigliata).

Due motori li producono sulla stessa scala:

1. **Geometria (sempre disponibile).** Derivata dai 106 punti di riferimento InsightFace
   memorizzati: l'Eye Aspect Ratio per gli occhi, il sollevamento degli angoli della bocca per il
   sorriso. `--recompute-face-signals` può ricalcolarli senza GPU e senza leggere immagini.
2. **Blendshape MediaPipe (opzionale).** Durante la scansione e l'estrazione dei volti, il
   ritaglio di ogni volto viene elaborato dal MediaPipe Face Landmarker, i cui blendshape
   (`eyeBlink*`, `mouthSmile*`, `mouthFrown*`) si mappano sulle stesse scale. Legge meglio occhi
   chiusi, sorrisi sottili e teste girate, quindi il suo valore **sostituisce** quello
   geometrico. Se MediaPipe o il suo modello sono assenti, o il ritaglio è troppo piccolo, viene
   mantenuto il valore geometrico.

### Installare MediaPipe

MediaPipe è opzionale. Installalo **senza** il suo `opencv-contrib-python` incluso,
che andrebbe in conflitto con l'`opencv-python` di Facet (entrambi forniscono `cv2`):

```bash
pip install mediapipe==0.10.35 --no-deps
pip install absl-py flatbuffers
```

Non eseguire mai un semplice `pip install mediapipe`.

### Pacchetto modello

Il pacchetto `face_landmarker.task` (~3,6 MiB, Apache-2.0) viene scaricato al primo utilizzo
in `pretrained_models/face_landmarker.task`. Offline, scaricalo da
`https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task`
e posizionalo lì. Se il download non riesce, Facet avvisa una sola volta e usa la geometria.

### Configurazione

```json
{
  "face_detection": {
    "blendshapes": {
      "enabled": true,
      "min_crop_size": 192,
      "blink_pose_gate_deg": null
    }
  }
}
```

- `enabled` (predefinito `true`): usa i blendshape quando MediaPipe e il modello sono
  disponibili. Imposta `false` per forzare la sola geometria.
- `min_crop_size` (predefinito `192`): i volti il cui ritaglio con padding è più piccolo di questo
  valore (px, lato più corto) usano la geometria invece di un ritaglio ingrandito.
- `blink_pose_gate_deg` (predefinito `null` = disattivato): solo l'analizzatore MediaPipe della modalità commerciale. Un volto girato di più di questi gradi (|yaw| o |pitch|) non riceve verdetto di ammiccamento né punteggio occhi aperti / sorriso, perché una testa girata sembra avere gli occhi chiusi. Nei test nessuna soglia tra 20° e 45° è servita, quindi viene fornito disattivato; impostalo solo se la tua libreria contiene molti volti fortemente girati. Deve essere un numero positivo. Vale per le foto scansionate di nuovo; i valori `is_blink` esistenti cambiano solo con una nuova scansione.

### Ricalcolo

`--recompute-face-signals` usa solo i punti di riferimento memorizzati: è **solo geometria** e
non esegue MediaPipe. Per aggiornare i punteggi MediaPipe, ri-estrai i volti con
`--extract-faces-gpu-force`.

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
- Cliccare su una persona applica alla galleria un filtro `person_id` (non esiste una rotta dedicata per persona)

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

Puoi nominare un volto sfuggito al clusterer direttamente dalla galleria:

1. Su una scheda foto, apri le azioni sulla persona e scegli un volto non assegnato.
2. Nel selettore di persona, scegli **Crea nuova persona** e digita un nome.
3. Il volto viene collegato alla nuova persona (`auto_clustered = 0`).

Un volto che appartiene già a un'altra persona viene spostato, e una persona rimasta senza
volti viene eliminata. In modalità multiutente puoi collegare solo volti di foto delle tue
directory o di quelle condivise. API: `POST /api/persons` (vedi [API.md](../API.md)).

### Da nominare

La pagina Gestisci persone elenca i cluster numerosi senza nome in una scheda **Da nominare**,
ciascuno con un campo nome. Un cluster vi compare quando ha almeno
`viewer.persons.needs_naming_min_faces` volti (predefinito `5`).

Senza nome significa nome assente o vuoto, che il cluster venga dal raggruppamento o da una divisione; le persone nascoste (ignorate) sono escluse. La scheda compare solo in modalità modifica, accanto a **Con nome**, che elenca solo le persone con nome, così ognuna compare una volta; la pagina si apre su **Con nome**.

### Pagina Suggerimenti di unione

Accessibile tramite `/merge-suggestions` o il pulsante "Suggerimenti di unione" nella pagina Gestisci persone:

- Mostra coppie di persone i cui volti si assomigliano
- **Cursore della soglia** — limite di somiglianza (più basso = più suggerimenti)
- **Unione con un clic** — unisci una coppia suggerita
- **Unione in blocco** — unisci più suggerimenti in una volta

### Schede foto

- Piccole miniature dei volti (avatar) mostrate per le persone riconosciute
- Configurabile tramite `viewer.face_thumbnails.output_size_px`

## Marcatore dello spazio degli embedding (sicurezza del modello di riconoscimento)

Ogni volto memorizza in `embedding_model` il modello di riconoscimento che lo ha prodotto (predefinito `arcface_buffalo_l`, il modello InsightFace `buffalo_l` / ArcFace `w600k_r50`). Gli embedding di modelli diversi non sono confrontabili, quindi il raggruppamento usa solo i volti del modello **attivo**. Un tag `NULL` conta come ArcFace. Se sono presenti volti di un altro modello, Facet li esclude e registra un avviso.

### Sostituzione del modello di riconoscimento (es. AdaFace) — piano differito

AdaFace (miglior raggruppamento dei volti sfocati o spontanei) **non è ancora implementato**. Adottarlo richiederebbe una ri-estrazione completa e un nuovo raggruppamento (`--extract-faces-gpu-force` poi `--cluster-faces-force`), perché gli embedding ArcFace e AdaFace non sono confrontabili.

### Librerie miste, ri-estrazione e valori sconosciuti

- **Librerie miste.** Una libreria può contenere insieme volti ArcFace (512-d) e SFace (128-d). Il raggruppamento, i suggerimenti di unione, la ricerca di persona simile e i centroidi usano ciascuno un solo modello alla volta (`persons.centroid_model` lo registra).
  - Le modalità incrementale e «solo persone con nome» non toccano i volti né le persone dell'altro modello.
  - `--cluster-faces-force` azzera ogni assegnazione di volto ed elimina tutte le persone, comprese quelle con nome, qualunque sia il modello.
  - Per portare una libreria sul modello attivo, esegui `--extract-faces-gpu-force` (estrattore permissivo in modalità commerciale; le persone con nome vengono conservate), poi `--cluster-faces-incremental`.
- **Avvisi.** Una scansione avvisa quando i volti salvati usano un modello diverso da quello attivo, e anche `--doctor` lo segnala. In modalità commerciale `--doctor` elenca ciò che una scansione carica davvero (YuNet, SFace, Q-ReAlign, più OFIQ quando `python-ofiq` è installato). Su CUDA, una scansione avvisa una sola volta quando InsightFace gira sulla CPU; vedi la sezione ONNX Runtime di `--doctor` e [Installazione › ONNX Runtime per il rilevamento dei volti](INSTALLATION.md#onnx-runtime-per-il-rilevamento-dei-volti).
- **Le persone con nome sopravvivono alla ri-estrazione.** `--extract-faces-gpu-force` restituisce ogni volto rilevato di nuovo alla persona con nome il cui vecchio riquadro lo sovrappone (IoU >= 0,5, uno a uno). I volti senza corrispondenza attendono il prossimo raggruppamento. Un'esecuzione interrotta riprende all'estrazione successiva. Ri-scansionare una foto conserva allo stesso modo le sue persone con nome.
- **Sconosciuto non è zero.** Senza MediaPipe l'analizzatore permissivo non può misurare occhi, sorriso e ammiccamenti, quindi sono salvati come NULL; i filtri e le penalità di ammiccamento trattano NULL come «non è un ammiccamento». Se la passata sui volti di una foto fallisce, `face_count`, `face_ratio` e `is_group_portrait` sono NULL e i suoi volti salvati vengono mantenuti; il punteggio la tratta come senza volti finché non viene riscansionata.

## Risoluzione dei problemi

| Problema | Soluzione |
|-------|----------|
| Il raggruppamento si blocca | Usa l'algoritmo `boruvka_balltree` |
| Troppi cluster piccoli | Aumenta `min_faces_per_person` |
| I volti non vengono raggruppati | Diminuisci `merge_threshold` |
| Il raggruppamento su GPU fallisce | Verifica l'installazione di cuML, usa `"never"` per forzare la CPU |
| Miniature mancanti | Esegui `--refill-face-thumbnails-incremental` |
| Rilevamento errato degli occhi chiusi | Regola `blink_ear_threshold`, esegui `--recompute-blinks` |
| Avviso "Excluded N faces from non-active embedding space" | Una modifica del modello di riconoscimento ha lasciato embedding misti — esegui `--extract-faces-gpu-force` quindi `--cluster-faces-incremental` |
