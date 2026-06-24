# Guía de despliegue

> 🌐 [English](../DEPLOYMENT.md) · [Français](../fr/DEPLOYMENT.md) · [Deutsch](../de/DEPLOYMENT.md) · [Italiano](../it/DEPLOYMENT.md) · **Español**

Ejecuta la galería web de Facet en un servidor remoto o NAS.

## Visión general

Facet tiene dos cargas de trabajo:

| Componente | Hardware | Propósito |
|-----------|----------|---------|
| **Puntuación** (`facet.py`) | GPU (6-24 GB VRAM) o CPU (8 GB+ de RAM) | Analizar y puntuar fotos |
| **Galería web** (`viewer.py`) | Cualquier máquina (pocos recursos) | Servir la galería web |

Solo la galería web necesita ejecutarse en el servidor. Puntúa en una estación de trabajo y luego sincroniza la base de datos.

## Mapeo de rutas

Cuando la máquina de puntuación y el servidor de la galería web acceden a las fotos desde puntos de montaje diferentes, configura `viewer.path_mapping` en `scoring_config.json` para traducir las rutas de la base de datos a rutas locales en disco.

**Ejemplo:** fotos puntuadas en Windows a través de UNC/NFS y servidas desde un NAS Linux:

```json
{
  "viewer": {
    "path_mapping": {
      "//NAS/share/Photos": "/volume1/Photos"
    }
  }
}
```

Usa **barras inclinadas** en las claves de configuración para mejorar la legibilidad — las barras invertidas se normalizan automáticamente. Esto mapea rutas de la base de datos como `\\NAS\share\Photos\2024\IMG_001.jpg` a `/volume1/Photos/2024/IMG_001.jpg`.

Se admiten varios mapeos (gana la primera coincidencia):

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

**Cómo funciona:**
- La base de datos almacena las rutas de escaneo originales (p. ej., `\\NAS\share\Photos\2024\IMG_001.jpg`)
- Las miniaturas se almacenan como BLOB en la base de datos, por lo que navegar no requiere acceso al disco
- El mapeo de rutas se aplica siempre que la galería web abre un archivo original: descargas, vista a resolución completa, generación de leyendas y crítica
- Se admiten tanto las rutas UNC (`\\server\share`) como las letras de unidad (`Z:\`)
- Gana el primer prefijo coincidente

## Compilar el cliente Angular

El servidor FastAPI sirve la SPA precompilada desde `client/dist/client/browser/`. Compílala antes del despliegue:

```bash
cd client && npm install && npx ng build && cd ..
```

Esto requiere Node.js 20+ únicamente en tiempo de compilación. Los archivos compilados son recursos estáticos — Node.js no es necesario en el servidor en tiempo de ejecución.

## NAS Synology (DS420j / serie J)

La serie J tiene una CPU ARM, 1 GB de RAM y no admite Docker. La galería web se ejecuta directamente con Python.

### Requisitos previos

1. **Habilitar SSH:** DSM > Panel de control > Terminal y SNMP > Habilitar SSH
2. **Instalar Python3:** Centro de paquetes de DSM, o a través de SSH:
   ```bash
   # Comprobar si está disponible
   python3 --version
   pip3 --version
   ```

### Instalación

```bash
ssh admin@your-synology-ip

# Crear directorio
mkdir -p /volume1/facet

# Instalar dependencias (solo galería web)
pip3 install fastapi uvicorn pyjwt pillow
```

### Exportar una base de datos ligera

En tu estación de trabajo de puntuación, exporta una base de datos reducida para el despliegue en el NAS:

```bash
python database.py --export-viewer-db
```

Esto crea `photo_scores_viewer.db`, que:
- Elimina los embeddings de CLIP, los datos de histograma y los embeddings faciales
- Reduce las miniaturas de 640px a 320px
- Normalmente reduce una base de datos de 14 GB a ~4-5 GB

Las exportaciones son incrementales: si `photo_scores_viewer.db` ya existe, solo se sincronizan las fotos nuevas y modificadas. Usa `--force-export` para una reconstrucción completa:

```bash
python database.py --export-viewer-db --force-export
```

La función "Buscar similares" no funcionará en la base de datos exportada (los embeddings de CLIP se eliminan). Usa la máquina de puntuación para ello.

### Sincronizar archivos

En la máquina de puntuación, compila primero el cliente Angular:

```bash
cd client && npm install && npx ng build && cd ..
```

Luego sincroniza la galería web y la base de datos exportada con el NAS:

```bash
rsync -avz \
  viewer.py config.py database.py tagger.py \
  scoring_config.json photo_scores_viewer.db \
  api/ client/dist/ db/ i18n/ \
  admin@your-synology-ip:/volume1/facet/
```

La galería web abre `photo_scores_pro.db` de forma predeterminada (se puede anular con la variable de entorno `DB_PATH`). En el NAS, establece `DB_PATH=/volume1/facet/photo_scores_viewer.db` o crea un enlace simbólico:
```bash
cd /volume1/facet
ln -sf photo_scores_viewer.db photo_scores_pro.db
```

Las fotos originales deben estar accesibles en el NAS en la ruta configurada en `path_mapping` para que las descargas funcionen.

### Configuración de baja memoria

Añade `viewer.performance` a `scoring_config.json` en el NAS para reducir el uso de memoria:

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

Esto anula la configuración global de `performance` (ajustada para la puntuación) con valores adecuados para 1 GB de RAM. Consulta [Configuración](CONFIGURATION.md#viewer-performance) para más detalles.

### Ejecución

```bash
cd /volume1/facet

# Prueba
python3 viewer.py

# Producción (1 worker para 1 GB de RAM)
uvicorn api:create_app --factory --host 0.0.0.0 --port 5000 --workers 1
```

Accede en `http://your-synology-ip:5000`

### Inicio automático

DSM > Panel de control > Programador de tareas > Crear > Tarea desencadenada > Script definido por el usuario:

- **Evento:** Arranque
- **Usuario:** root
- **Script:**
  ```bash
  cd /volume1/facet
  /usr/local/bin/uvicorn api:create_app --factory --host 0.0.0.0 --port 5000 --workers 1 >> /var/log/facet.log 2>&1 &
  ```

### HTTPS

Usa el proxy inverso integrado de Synology:

DSM > Panel de control > Portal de inicio de sesión > Avanzado > Proxy inverso:

| Origen | Destino |
|--------|-------------|
| `https://photos.yourdomain.com:443` | `http://localhost:5000` |

Combínalo con un certificado de Let's Encrypt desde DSM > Panel de control > Seguridad > Certificado.

## NAS Synology (serie Plus / x86)

Los NAS de la serie Plus admiten Docker (Container Manager).

El repositorio incluye un `Dockerfile`, un `docker-compose.yml` y un `docker-compose.gpu.yml` en la raíz. La imagen empaqueta el stack completo de puntuación + galería web sobre una base de CUDA PyTorch, compila el cliente Angular y expone el puerto 5000. La galería web se ejecuta en modo CPU de forma predeterminada; la anulación para GPU es opcional.

```bash
# Solo galería web (CPU)
docker compose up -d

# Con GPU NVIDIA para puntuación (requiere el NVIDIA Container Toolkit)
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

`scoring_config.json` se monta como un volumen (no se integra en la imagen), así que edítalo en el host y reinicia. La ruta de la base de datos se establece con `DB_PATH` (predeterminado `/app/data/photo_scores_pro.db`). Las cachés de modelos persisten en `./model-cache/`, por lo que sobreviven a los reinicios.

Para un NAS de solo galería web donde la imagen debe permanecer pequeña (sin CUDA), compila una imagen ligera en su lugar. Ten en cuenta que la protección de CI exige que cada fuente de `COPY` esté bajo control de git, por lo que el contexto de compilación debe incluir los archivos listados:

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
      - /volume1/Photos:/volume1/Photos:ro  # Mount photos for downloads
    restart: always
```

## Servidor Linux genérico

### Uvicorn

```bash
pip install fastapi uvicorn pyjwt pillow
uvicorn api:create_app --factory --host 0.0.0.0 --port 5000 --workers 4
```

O usa el wrapper (predeterminado a 1 worker; pasa `--workers N` para más):

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

Añade HTTPS:
```bash
sudo certbot --nginx -d photos.yourdomain.com
```

### Servicio Systemd

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

### Caddy (HTTPS automático)

```
photos.yourdomain.com {
    reverse_proxy localhost:5000
}
```

## Flujo de trabajo

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

Vuelve a ejecutar la exportación y `rsync` después de cada sesión de puntuación para actualizar la base de datos en el servidor. En servidores con mucha memoria, puedes sincronizar directamente la base de datos completa `photo_scores_pro.db` en lugar de exportarla.

## Configuración multiusuario

Para dar a cada usuario un conjunto privado de directorios de fotos, añade una sección `users` a `scoring_config.json`. Consulta [Configuración](CONFIGURATION.md#users) para la referencia completa.

### Inicio rápido

```bash
# On the scoring machine, add users
python database.py --add-user alice --role superadmin --display-name "Alice"
python database.py --add-user bob --role user --display-name "Bob"
```

Luego edita `scoring_config.json`:

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

Las rutas de directorio deben coincidir con las rutas de las fotos almacenadas en la base de datos. Si usas `viewer.path_mapping`, los directorios deben usar las rutas **mapeadas** (tal como aparecen en el host de la galería web).

### Migrar valoraciones existentes

Si tenías valoraciones en modo de un solo usuario, migrarlas a un usuario:

```bash
python database.py --migrate-user-preferences --user alice
```

### Botón de escaneo

Para permitir que el superadmin desencadene escaneos de fotos desde la interfaz de la galería web (solo útil cuando la galería web se ejecuta en la máquina con GPU):

```json
{
  "viewer": {
    "features": {
      "show_scan_button": true
    }
  }
}
```

## Copias de seguridad continuas con Litestream

La base de datos SQLite puede crecer hasta decenas de gigabytes (`photo_scores_pro.db` alcanza ~14 GB tras puntuar más de 20 000 fotos), y un nuevo escaneo cuesta tiempo de GPU. [Litestream](https://litestream.io/) transmite el WAL a S3, B2, GCS, SFTP u otro disco local de forma continua, con restauración a un punto en el tiempo con precisión de unos pocos segundos.

Facet no incluye Litestream. Instálalo una vez en el host que ejecuta la galería web/puntuación; se ejecuta como un proceso sidecar, transparente para la aplicación.

Facet ya usa el modo WAL (`db/connection.py:apply_pragmas`), y el hilo periódico de checkpoint (predeterminado cada 30 min, configurable mediante `performance.wal_checkpoint_minutes`) mantiene el WAL acotado. Las lecturas no se bloquean durante la replicación.

### Configuración mínima de Litestream

```yaml
# /etc/litestream.yml
dbs:
  - path: /opt/facet/photo_scores_pro.db
    replicas:
      # Cheap object storage; replace with the bucket of your choice.
      - type: s3
        bucket: my-facet-backups
        path: photo_scores_pro
        region: us-east-1
        access-key-id:     $LITESTREAM_AWS_KEY
        secret-access-key: $LITESTREAM_AWS_SECRET
        retention: 72h               # keep 3 days of point-in-time history
        snapshot-interval: 24h        # full snapshot once per day
        validation-interval: 6h       # detect corruption early
```

### Unidad de Systemd

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

`litestream.env` contiene las credenciales de AWS / B2 para mantenerlas fuera del YAML.

### Simulacro de restauración

Practícalo antes de necesitarlo:

```bash
sudo systemctl stop facet
sudo systemctl stop litestream
litestream restore -o /tmp/restored.db s3://my-facet-backups/photo_scores_pro
# verify
sqlite3 /tmp/restored.db "SELECT COUNT(*) FROM photos;"
# swap in
sudo mv /opt/facet/photo_scores_pro.db /opt/facet/photo_scores_pro.bad
sudo mv /tmp/restored.db /opt/facet/photo_scores_pro.db
sudo chown facet:facet /opt/facet/photo_scores_pro.db
sudo systemctl start litestream
sudo systemctl start facet
```

### Coste aproximado

Para la base de datos de 14 GB con ~50 MB/día de rotación de WAL durante la puntuación activa, espera:
- ~0,30 $/mes de almacenamiento en S3 Standard
- ~0,05 $/mes por operaciones PUT
Insignificante comparado con un nuevo escaneo: ~50 horas de GPU en una RTX de 16 GB.
