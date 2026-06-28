# Guia de Implantação

> 🌐 [English](../DEPLOYMENT.md) · [Français](../fr/DEPLOYMENT.md) · [Deutsch](../de/DEPLOYMENT.md) · [Italiano](../it/DEPLOYMENT.md) · [Español](../es/DEPLOYMENT.md) · **Português**

Execute o visualizador do Facet em um servidor remoto ou NAS.

## Visão geral

O Facet tem duas cargas de trabalho:

| Componente | Hardware | Finalidade |
|-----------|----------|---------|
| **Pontuação** (`facet.py`) | GPU (6-24GB VRAM) ou CPU (8GB+ de RAM) | Analisar e pontuar fotos |
| **Visualizador** (`viewer.py`) | Qualquer máquina (poucos recursos) | Servir a galeria web |

Apenas o visualizador precisa rodar no servidor. Pontue em uma estação de trabalho e, em seguida, sincronize o banco de dados.

## Mapeamento de caminhos

Quando a máquina de pontuação e o servidor do visualizador acessam as fotos a partir de pontos de montagem diferentes, configure `viewer.path_mapping` em `scoring_config.json` para traduzir os caminhos do banco de dados em caminhos de disco locais.

**Exemplo:** Fotos pontuadas no Windows via UNC/NFS, servidas a partir de um NAS Linux:

```json
{
  "viewer": {
    "path_mapping": {
      "//NAS/share/Photos": "/volume1/Photos"
    }
  }
}
```

Use **barras normais** nas chaves de configuração para facilitar a leitura — as barras invertidas são normalizadas automaticamente. Isso mapeia caminhos do banco de dados como `\\NAS\share\Photos\2024\IMG_001.jpg` para `/volume1/Photos/2024/IMG_001.jpg`.

Vários mapeamentos são suportados (o primeiro que corresponder vence):

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

**Como funciona:**
- O banco de dados armazena os caminhos originais da varredura (por exemplo, `\\NAS\share\Photos\2024\IMG_001.jpg`)
- As miniaturas são armazenadas como BLOBs no banco de dados, então a navegação não precisa de acesso ao disco
- O mapeamento de caminhos é aplicado sempre que o visualizador abre um arquivo original: downloads, visualização em resolução total, legendagem e crítica
- Tanto caminhos UNC (`\\server\share`) quanto letras de unidade (`Z:\`) são suportados
- O primeiro prefixo correspondente vence

## Compilando o cliente Angular

O servidor FastAPI serve a SPA pré-compilada a partir de `client/dist/client/browser/`. Compile-a antes da implantação:

```bash
cd client && npm install && npx ng build && cd ..
```

Isso requer Node.js 20+ apenas no momento da compilação. Os arquivos compilados são ativos estáticos — o Node.js não é necessário no servidor em tempo de execução.

## Synology NAS (DS420j / série J)

A série J tem uma CPU ARM, 1GB de RAM e nenhum suporte a Docker. O visualizador roda diretamente com Python.

### Pré-requisitos

1. **Habilite o SSH:** DSM > Painel de Controle > Terminal e SNMP > Habilitar SSH
2. **Instale o Python3:** Centro de Pacotes do DSM, ou via SSH:
   ```bash
   # Verifique se está disponível
   python3 --version
   pip3 --version
   ```

### Instalação

```bash
ssh admin@your-synology-ip

# Crie o diretório
mkdir -p /volume1/facet

# Instale as dependências (apenas do visualizador)
pip3 install fastapi uvicorn pyjwt pillow aiosqlite
```

### Exportando um banco de dados leve

Na sua estação de trabalho de pontuação, exporte um banco de dados reduzido para implantação no NAS:

```bash
python database.py --export-viewer-db
```

Isso cria `photo_scores_viewer.db`, que:
- Remove os embeddings CLIP, os dados de histograma e os embeddings de rostos
- Reduz as miniaturas de 640px para 320px
- Normalmente reduz um banco de dados de 14GB para ~4-5GB

As exportações são incrementais: se `photo_scores_viewer.db` já existir, apenas as fotos novas e alteradas são sincronizadas. Use `--force-export` para uma reconstrução completa:

```bash
python database.py --export-viewer-db --force-export
```

O recurso "Encontrar semelhantes" não funcionará no banco de dados exportado (os embeddings CLIP são removidos). Use a máquina de pontuação para isso.

### Sincronizando arquivos

Na máquina de pontuação, compile primeiro o cliente Angular (consulte [Compilando o cliente Angular](#compilando-o-cliente-angular)).

Em seguida, sincronize o visualizador e o banco de dados exportado com o NAS:

```bash
rsync -avz \
  viewer.py config.py database.py tagger.py \
  scoring_config.json photo_scores_viewer.db \
  api/ client/dist/ db/ i18n/ \
  admin@your-synology-ip:/volume1/facet/
```

O visualizador abre `photo_scores_pro.db` por padrão (substituível pela variável de ambiente `DB_PATH`). No NAS, defina `DB_PATH=/volume1/facet/photo_scores_viewer.db` ou crie um link simbólico:
```bash
cd /volume1/facet
ln -sf photo_scores_viewer.db photo_scores_pro.db
```

As fotos originais devem estar acessíveis no NAS no caminho configurado em `path_mapping` para que os downloads funcionem.

### Configuração para pouca memória

Adicione `viewer.performance` ao `scoring_config.json` no NAS para reduzir o uso de memória:

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

Isso substitui as configurações globais de `performance` (que são ajustadas para a pontuação) por valores adequados para 1GB de RAM. Consulte [Configuração](CONFIGURATION.md#viewer-performance) para detalhes.

### Execução

```bash
cd /volume1/facet

# Teste
python3 viewer.py

# Produção (1 worker para 1GB de RAM)
uvicorn api:create_app --factory --host 0.0.0.0 --port 5000 --workers 1
```

Acesse em `http://your-synology-ip:5000`

### Início automático

DSM > Painel de Controle > Agendador de Tarefas > Criar > Tarefa Acionada > Script definido pelo usuário:

- **Evento:** Inicialização
- **Usuário:** root
- **Script:**
  ```bash
  cd /volume1/facet
  /usr/local/bin/uvicorn api:create_app --factory --host 0.0.0.0 --port 5000 --workers 1 >> /var/log/facet.log 2>&1 &
  ```

### HTTPS

Use o proxy reverso integrado do Synology:

DSM > Painel de Controle > Portal de Login > Avançado > Proxy Reverso:

| Origem | Destino |
|--------|-------------|
| `https://photos.yourdomain.com:443` | `http://localhost:5000` |

Combine com um certificado Let's Encrypt em DSM > Painel de Controle > Segurança > Certificado.

## Synology NAS (série Plus / x86)

O NAS da série Plus suporta Docker (Container Manager).

O repositório fornece um `Dockerfile`, um `docker-compose.yml` e um `docker-compose.gpu.yml` na raiz. A imagem agrupa toda a pilha de pontuação + visualizador sobre uma base CUDA PyTorch, compila o cliente Angular e expõe a porta 5000. O visualizador roda em modo CPU por padrão; a substituição por GPU é opcional.

```bash
# Apenas o visualizador (CPU)
docker compose up -d

# Com GPU NVIDIA para pontuação (requer o NVIDIA Container Toolkit)
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

O `scoring_config.json` é montado como um volume (não embutido na imagem), então edite-o no host e reinicie. O caminho do banco de dados é definido por `DB_PATH` (padrão `/app/data/photo_scores_pro.db`). Os caches de modelos persistem em `./model-cache/`, então eles sobrevivem às reinicializações.

Para um NAS apenas de visualização, no qual a imagem deve permanecer pequena (sem CUDA), compile uma imagem enxuta. Observe que a proteção de CI exige que toda origem `COPY` esteja versionada no git, então o contexto de compilação deve incluir os arquivos listados:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN pip install fastapi uvicorn pyjwt pillow aiosqlite
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
pip install fastapi uvicorn pyjwt pillow aiosqlite
uvicorn api:create_app --factory --host 0.0.0.0 --port 5000 --workers 4
```

Ou use o wrapper (padrão de 1 worker; passe `--workers N` para mais):

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

Adicione HTTPS:
```bash
sudo certbot --nginx -d photos.yourdomain.com
```

### Serviço systemd

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

## Fluxo de trabalho

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

Reexecute a exportação e o `rsync` após cada sessão de pontuação para atualizar o banco de dados no servidor. Para servidores com bastante memória, você pode sincronizar diretamente o `photo_scores_pro.db` completo em vez de exportar.

## Configuração multiusuário

Para dar a cada usuário um conjunto privado de diretórios de fotos, adicione uma seção `users` ao `scoring_config.json`. Consulte [Configuração](CONFIGURATION.md#users) para a referência completa.

### Início rápido

```bash
# On the scoring machine, add users
python database.py --add-user alice --role superadmin --display-name "Alice"
python database.py --add-user bob --role user --display-name "Bob"
```

Em seguida, edite o `scoring_config.json`:

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

Os caminhos dos diretórios devem corresponder aos caminhos das fotos armazenados no banco de dados. Se você usar `viewer.path_mapping`, os diretórios devem usar os caminhos **mapeados** (como aparecem no host do visualizador).

### Migrando avaliações existentes

Se você tinha avaliações no modo de usuário único, migre-as para um usuário:

```bash
python database.py --migrate-user-preferences --user alice
```

### Botão de varredura

Para permitir que o superadmin acione varreduras de fotos a partir da interface do visualizador (útil apenas quando o visualizador roda na máquina com GPU):

```json
{
  "viewer": {
    "features": {
      "show_scan_button": true
    }
  }
}
```

## Backups contínuos com o Litestream

O banco de dados SQLite pode crescer para dezenas de gigabytes (`photo_scores_pro.db` chega a ~14 GB após pontuar mais de 20 mil fotos), e uma nova varredura custa tempo de GPU. O [Litestream](https://litestream.io/) transmite o WAL para S3, B2, GCS, SFTP ou outro disco local continuamente, com restauração para um ponto no tempo com precisão de poucos segundos.

O Facet não inclui o Litestream. Instale-o uma vez no host que executa o visualizador/pontuação; ele roda como um processo sidecar, transparente para a aplicação.

O Facet já usa o modo WAL (`db/connection.py:apply_pragmas`), e a thread de checkpoint periódico (padrão a cada 30 min, configurável via `performance.wal_checkpoint_minutes`) mantém o WAL limitado. As leituras permanecem desbloqueadas durante a replicação.

### Configuração mínima do Litestream

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

### Unidade systemd

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

O `litestream.env` guarda as credenciais da AWS / B2 para que elas fiquem fora do YAML.

### Exercício de restauração

Pratique isso antes de precisar:

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

### Estimativa de custo

Para o banco de dados de 14 GB com ~50 MB/dia de rotatividade de WAL durante a pontuação ativa, espere:
- ~US$ 0,30/mês de armazenamento no S3 Standard
- ~US$ 0,05/mês para operações PUT
Negligenciável em comparação a uma nova varredura: ~50 GPU-horas em uma RTX de 16 GB.
