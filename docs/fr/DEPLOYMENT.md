# Guide de déploiement

> 🌐 [English](../DEPLOYMENT.md) · **Français** · [Deutsch](../de/DEPLOYMENT.md) · [Italiano](../it/DEPLOYMENT.md) · [Español](../es/DEPLOYMENT.md)

Exécutez la galerie web Facet sur un serveur distant ou un NAS.

## Vue d'ensemble

Facet comporte deux charges de travail :

| Composant | Matériel | Rôle |
|-----------|----------|---------|
| **Scoring** (`facet.py`) | GPU (6-24 Go VRAM) ou CPU (8 Go+ RAM) | Analyser et noter les photos |
| **Galerie web** (`viewer.py`) | Toute machine (peu de ressources) | Servir la galerie web |

Seule la galerie web doit tourner sur le serveur. Notez les photos sur un poste de travail, puis synchronisez la base de données.

## Mappage des chemins

Lorsque la machine de scoring et le serveur de la galerie accèdent aux photos depuis des points de montage différents, configurez `viewer.path_mapping` dans `scoring_config.json` pour traduire les chemins de la base de données en chemins de disque local.

**Exemple :** photos notées sous Windows via UNC/NFS, servies depuis un NAS Linux :

```json
{
  "viewer": {
    "path_mapping": {
      "//NAS/share/Photos": "/volume1/Photos"
    }
  }
}
```

Utilisez des **barres obliques** (forward slashes) dans les clés de configuration pour la lisibilité — les barres obliques inverses sont normalisées automatiquement. Cela mappe des chemins de base de données comme `\\NAS\share\Photos\2024\IMG_001.jpg` vers `/volume1/Photos/2024/IMG_001.jpg`.

Plusieurs mappages sont pris en charge (la première correspondance l'emporte) :

```json
{
  "viewer": {
    "path_mapping": {
      "//NAS/share/Photos": "/volume1/Photos",
      "//NAS/share/Archive": "/volume1/Archive"
    }
  }
}
```

**Fonctionnement :**
- La base de données stocke les chemins de scan d'origine (par ex. `\\NAS\share\Photos\2024\IMG_001.jpg`)
- Les miniatures sont stockées comme BLOB dans la base de données, donc la navigation ne nécessite aucun accès disque
- Le mappage des chemins s'applique chaque fois que la galerie ouvre un fichier original : téléchargements, vue pleine résolution, génération de légendes et critique
- Les chemins UNC (`\\server\share`) comme les lettres de lecteur (`Z:\`) sont pris en charge
- Le premier préfixe correspondant l'emporte

## Compilation du client Angular

Le serveur FastAPI sert la SPA pré-compilée depuis `client/dist/client/browser/`. Compilez-la avant le déploiement :

```bash
cd client && npm install && npx ng build && cd ..
```

Cela nécessite Node.js 20+ uniquement au moment de la compilation. Les fichiers compilés sont des ressources statiques — Node.js n'est pas requis sur le serveur à l'exécution.

## NAS Synology (DS420j / série J)

La série J possède un processeur ARM, 1 Go de RAM et ne prend pas en charge Docker. La galerie web tourne directement avec Python.

### Prérequis

1. **Activer SSH :** DSM > Panneau de configuration > Terminal & SNMP > Activer SSH
2. **Installer Python3 :** Centre de paquets DSM, ou via SSH :
   ```bash
   # Vérifier la disponibilité
   python3 --version
   pip3 --version
   ```

### Installation

```bash
ssh admin@your-synology-ip

# Créer le répertoire
mkdir -p /volume1/facet

# Installer les dépendances (galerie web uniquement)
pip3 install fastapi uvicorn pyjwt pillow
```

### Exporter une base de données allégée

Sur votre poste de travail de scoring, exportez une base de données réduite pour le déploiement sur NAS :

```bash
python database.py --export-viewer-db
```

Cela crée `photo_scores_viewer.db`, qui :
- Supprime les embeddings CLIP, les données d'histogramme et les embeddings de visage
- Réduit les miniatures de 640 px à 320 px
- Fait généralement passer une base de données de 14 Go à environ 4-5 Go

Les exports sont incrémentaux : si `photo_scores_viewer.db` existe déjà, seules les photos nouvelles et modifiées sont synchronisées. Utilisez `--force-export` pour une reconstruction complète :

```bash
python database.py --export-viewer-db --force-export
```

La fonctionnalité « Photos similaires » ne fonctionnera pas sur la base de données exportée (les embeddings CLIP sont supprimés). Utilisez la machine de scoring pour cela.

### Synchroniser les fichiers

Sur la machine de scoring, compilez d'abord le client Angular :

```bash
cd client && npm install && npx ng build && cd ..
```

Puis synchronisez la galerie web et la base de données exportée vers le NAS :

```bash
rsync -avz \
  viewer.py config.py database.py tagger.py \
  scoring_config.json photo_scores_viewer.db \
  api/ client/dist/ db/ i18n/ \
  admin@your-synology-ip:/volume1/facet/
```

La galerie web ouvre `photo_scores_pro.db` par défaut (modifiable via la variable d'environnement `DB_PATH`). Sur le NAS, définissez soit `DB_PATH=/volume1/facet/photo_scores_viewer.db`, soit créez un lien symbolique :
```bash
cd /volume1/facet
ln -sf photo_scores_viewer.db photo_scores_pro.db
```

Les photos originales doivent être accessibles sur le NAS au chemin configuré dans `path_mapping` pour que les téléchargements fonctionnent.

### Configuration à faible mémoire

Ajoutez `viewer.performance` à `scoring_config.json` sur le NAS pour réduire l'utilisation de la mémoire :

```json
{
  "viewer": {
    "performance": {
      "mmap_size_mb": 0,
      "cache_size_mb": 4,
      "pool_size": 2,
      "thumbnail_cache_size": 200,
      "face_cache_size": 50
    }
  }
}
```

Cela remplace les paramètres globaux de `performance` (optimisés pour le scoring) par des valeurs adaptées à 1 Go de RAM. Voir [Configuration](CONFIGURATION.md#viewer-performance) pour plus de détails.

### Exécution

```bash
cd /volume1/facet

# Test
python3 viewer.py

# Production (1 worker pour 1 Go de RAM)
uvicorn api:create_app --factory --host 0.0.0.0 --port 5000 --workers 1
```

Accès à `http://your-synology-ip:5000`

### Démarrage automatique

DSM > Panneau de configuration > Planificateur de tâches > Créer > Tâche déclenchée > Script défini par l'utilisateur :

- **Événement :** Démarrage
- **Utilisateur :** root
- **Script :**
  ```bash
  cd /volume1/facet
  /usr/local/bin/uvicorn api:create_app --factory --host 0.0.0.0 --port 5000 --workers 1 >> /var/log/facet.log 2>&1 &
  ```

### HTTPS

Utilisez le proxy inverse intégré de Synology :

DSM > Panneau de configuration > Portail de connexion > Avancé > Proxy inversé :

| Source | Destination |
|--------|-------------|
| `https://photos.yourdomain.com:443` | `http://localhost:5000` |

Associez-le à un certificat Let's Encrypt depuis DSM > Panneau de configuration > Sécurité > Certificat.

## NAS Synology (Plus / série x86)

Les NAS de la série Plus prennent en charge Docker (Container Manager).

Le dépôt fournit un `Dockerfile`, un `docker-compose.yml` et un `docker-compose.gpu.yml` à la racine. L'image regroupe l'ensemble de la pile scoring + galerie web sur une base CUDA PyTorch, compile le client Angular et expose le port 5000. La galerie web tourne en mode CPU par défaut ; la surcharge GPU est optionnelle.

```bash
# Galerie web uniquement (CPU)
docker compose up -d

# Avec un GPU NVIDIA pour la notation (nécessite le NVIDIA Container Toolkit)
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

`scoring_config.json` est monté comme volume (et non intégré à l'image), vous pouvez donc le modifier sur l'hôte puis redémarrer. Le chemin de la base de données est défini par `DB_PATH` (par défaut `/app/data/photo_scores_pro.db`). Les caches de modèles persistent sous `./model-cache/` pour survivre aux redémarrages.

Pour un NAS dédié à la galerie web où l'image doit rester légère (sans CUDA), compilez plutôt une image allégée. Notez que le garde-fou de la CI exige que chaque source `COPY` soit suivie par git, donc le contexte de compilation doit inclure les fichiers listés :

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN pip install fastapi uvicorn pyjwt pillow
COPY viewer.py config.py database.py tagger.py scoring_config.json ./
COPY api/ api/
COPY client/dist/ client/dist/
COPY db/ db/
COPY i18n/ i18n/
EXPOSE 5000
CMD ["uvicorn", "api:create_app", "--factory", "--host", "0.0.0.0", "--port", "5000", "--workers", "4"]
```

```yaml
services:
  facet:
    build: .
    ports:
      - "5000:5000"
    volumes:
      - ./photo_scores_pro.db:/app/photo_scores_pro.db
      - /volume1/Photos:/volume1/Photos:ro  # Monter les photos pour les téléchargements
    restart: always
```

## Serveur Linux générique

### Uvicorn

```bash
pip install fastapi uvicorn pyjwt pillow
uvicorn api:create_app --factory --host 0.0.0.0 --port 5000 --workers 4
```

Ou utilisez le wrapper (par défaut 1 worker ; passez `--workers N` pour davantage) :

```bash
python viewer.py --production --workers 4
```

### Uvicorn + Nginx

```nginx
server {
    listen 80;
    server_name photos.yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        client_max_body_size 50M;
    }
}
```

Ajouter HTTPS :
```bash
sudo certbot --nginx -d photos.yourdomain.com
```

### Service systemd

```ini
# /etc/systemd/system/facet.service
[Unit]
Description=Facet Viewer
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/facet
ExecStart=/usr/local/bin/uvicorn api:create_app --factory --host 127.0.0.1 --port 5000 --workers 4
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now facet
```

### Caddy (HTTPS automatique)

```
photos.yourdomain.com {
    reverse_proxy localhost:5000
}
```

## Flux de travail

```
 Scoring Machine (GPU)                      Server / NAS
 ─────────────────────                      ─────────────
 python facet.py /photos
         │
         ├─ database.py --export-viewer-db
         │       │
         │       └─ photo_scores_viewer.db ──rsync──▶ viewer.py serves gallery
         └─ scoring_config.json ────────────────────▶ (with path_mapping +
                                                       viewer.performance)
                                                        │
                                                 http://nas:5000
```

Relancez l'export et `rsync` après chaque session de scoring pour mettre à jour la base de données sur le serveur. Pour les serveurs dotés de beaucoup de mémoire, vous pouvez synchroniser directement la base complète `photo_scores_pro.db` au lieu de l'exporter.

## Configuration multi-utilisateur

Pour attribuer à chaque utilisateur un ensemble privé de répertoires de photos, ajoutez une section `users` à `scoring_config.json`. Voir [Configuration](CONFIGURATION.md#users) pour la référence complète.

### Démarrage rapide

```bash
# Sur la machine de notation, ajouter des utilisateurs
python database.py --add-user alice --role superadmin --display-name "Alice"
python database.py --add-user bob --role user --display-name "Bob"
```

Puis modifiez `scoring_config.json` :

```json
{
  "users": {
    "alice": {
      "password_hash": "...",
      "display_name": "Alice",
      "role": "superadmin",
      "directories": ["/volume1/Photos/Alice"]
    },
    "bob": {
      "password_hash": "...",
      "display_name": "Bob",
      "role": "user",
      "directories": ["/volume1/Photos/Bob"]
    },
    "shared_directories": [
      "/volume1/Photos/Family"
    ]
  }
}
```

Les chemins des répertoires doivent correspondre aux chemins de photos stockés dans la base de données. Si vous utilisez `viewer.path_mapping`, les répertoires doivent employer les chemins **mappés** (tels qu'ils apparaissent sur l'hôte de la galerie web).

### Migration des notes existantes

Si vous aviez des notes en mode mono-utilisateur, migrez-les vers un utilisateur :

```bash
python database.py --migrate-user-preferences --user alice
```

### Bouton de scan

Pour permettre au superadmin de déclencher des scans de photos depuis l'interface de la galerie web (utile uniquement lorsque la galerie tourne sur la machine GPU) :

```json
{
  "viewer": {
    "features": {
      "show_scan_button": true
    }
  }
}
```

## Sauvegardes continues avec Litestream

La base de données SQLite peut atteindre plusieurs dizaines de gigaoctets (`photo_scores_pro.db` atteint environ 14 Go après le scoring de plus de 20 000 photos), et un re-scan coûte du temps GPU. [Litestream](https://litestream.io/) diffuse en continu le WAL vers S3, B2, GCS, SFTP ou un autre disque local, avec restauration à un instant précis à quelques secondes près.

Facet ne fournit pas Litestream. Installez-le une fois sur l'hôte exécutant la galerie web/le scoring ; il tourne comme un processus annexe (sidecar), transparent pour l'application.

Facet utilise déjà le mode WAL (`db/connection.py:apply_pragmas`), et le thread de checkpoint périodique (toutes les 30 min par défaut, configurable via `performance.wal_checkpoint_minutes`) maintient le WAL borné. Les lectures restent non bloquées pendant la réplication.

### Configuration Litestream minimale

```yaml
# /etc/litestream.yml
dbs:
  - path: /opt/facet/photo_scores_pro.db
    replicas:
      # Stockage objet économique ; remplacez par le bucket de votre choix.
      - type: s3
        bucket: my-facet-backups
        path: photo_scores_pro
        region: us-east-1
        access-key-id:     $LITESTREAM_AWS_KEY
        secret-access-key: $LITESTREAM_AWS_SECRET
        retention: 72h               # conserver 3 jours d'historique à un instant donné
        snapshot-interval: 24h        # instantané complet une fois par jour
        validation-interval: 6h       # détecter la corruption tôt
```

### Unité systemd

```ini
# /etc/systemd/system/litestream.service
[Unit]
Description=Litestream continuous SQLite replication
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/bin/litestream replicate -config /etc/litestream.yml
Restart=always
User=facet
EnvironmentFile=/etc/litestream.env

[Install]
WantedBy=multi-user.target
```

`litestream.env` contient les identifiants AWS / B2 pour les garder hors du YAML.

### Exercice de restauration

Entraînez-vous avant d'en avoir besoin :

```bash
sudo systemctl stop facet
sudo systemctl stop litestream
litestream restore -o /tmp/restored.db s3://my-facet-backups/photo_scores_pro
# vérifier
sqlite3 /tmp/restored.db "SELECT COUNT(*) FROM photos;"
# remplacer par
sudo mv /opt/facet/photo_scores_pro.db /opt/facet/photo_scores_pro.bad
sudo mv /tmp/restored.db /opt/facet/photo_scores_pro.db
sudo chown facet:facet /opt/facet/photo_scores_pro.db
sudo systemctl start litestream
sudo systemctl start facet
```

### Ordre de grandeur des coûts

Pour la base de 14 Go avec environ 50 Mo/jour de variation du WAL pendant le scoring actif, prévoyez :
- environ 0,30 $/mois pour le stockage sur S3 Standard
- environ 0,05 $/mois pour les opérations PUT
Négligeable comparé à un re-scan : environ 50 heures-GPU sur une RTX 16 Go.
