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

### Baixando (pull) a Imagem Publicada

`docker-compose.yml` e `docker-compose.gpu.yml` carregam uma chave `image:` ao lado de `build: .`, então `docker compose up` **baixa (pull)** uma imagem pré-compilada do GHCR em vez de compilar localmente a pilha CPU de ~3,3 GB (ou a pilha CUDA de ~21 GB):

```bash
# Apenas o visualizador (CPU) — pulls ghcr.io/ncoevoet/facet:latest
docker compose up -d

# Com GPU NVIDIA para pontuação (requer o NVIDIA Container Toolkit) —
# pulls ghcr.io/ncoevoet/facet:latest-cuda
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

`docker compose build` (ou `up --build`) ainda compila a partir do `Dockerfile` deste repositório para experimentação local — a chave `build:` permanece abaixo de `image:` exatamente para isso. As sobreposições por perfil (`docker-compose.{8gb,16gb,24gb}.yml`) também baixam `:latest-cuda`, já que os três são perfis de GPU; `docker-compose.legacy.yml` (CPU) baixa a base `:latest`.

**Duas tags publicadas, um único Dockerfile.** `ghcr.io/ncoevoet/facet:latest` é uma build enxuta somente CPU (sem runtime CUDA, sem RAPIDS cuML — o agrupamento de rostos recorre ao HDBSCAN em CPU). `ghcr.io/ncoevoet/facet:latest-cuda` é a pilha completa CUDA + cuML descrita ao longo deste documento, idêntica a um `docker build .` local. Ambas vêm do mesmo `Dockerfile`, parametrizadas por build args (`BASE_IMAGE`, `STRIP_TORCH`, `INSTALL_CUML`) definidos por variante em `.github/workflows/docker-publish.yml`. Tags versionadas (`:1.7.2`, `:1.7`, `:1.7.2-cuda`, `:1.7-cuda`, …) são publicadas junto com `latest`/`latest-cuda` a cada tag git `vX.Y.Z`.

**Publicando sem uma release.** `.github/workflows/docker-publish.yml` também aceita um disparo manual `workflow_dispatch` pelo botão *Run workflow* da aba Actions, independente do push de tag `vX.Y.Z` acima — ele reconstrói e republica `latest`/`latest-cuda` a partir do estado atual de `master`, sem precisar cortar uma release. Ele não gera uma tag versionada: os padrões `type=semver` do `docker/metadata-action` só disparam com uma tag git `vX.Y.Z` de verdade, então uma execução manual move apenas `latest`/`latest-cuda`.

**Ambas as imagens publicadas são apenas `linux/amd64` (x86_64).** Isso cobre o hardware NAS x86 (Synology Plus/x86, UGREEN, UnifyDrive e qualquer coisa que execute Coolify, Portainer ou Docker comum em uma CPU Intel/AMD). Não existe uma imagem `arm64`: a compilação cruzada de uma pilha de ML de vários gigabytes sob QEMU custa horas por tag, e a variante CUDA é, de qualquer forma, exclusiva de x86. Em um NAS ARM ou um Raspberry Pi, compile localmente com `docker compose build` em vez de baixar — `docker compose up` mantém `build: .` abaixo da chave `image:` exatamente para esse caso.

> **Apenas na primeira publicação:** um novo pacote GHCR vem, por padrão, como **privado**. Após a primeira execução do workflow `docker-publish`, um proprietário precisa alternar `ghcr.io/ncoevoet/facet` para **público** (Settings do pacote → Change visibility) — caso contrário, o `docker compose up` de um clone novo falha ao baixar com um erro 401. Essa mudança já aconteceu para `ghcr.io/ncoevoet/facet` — `:latest` (a build enxuta de CPU, ~3,3 GB) e `:latest-cuda` são baixadas anonimamente hoje; por enquanto só existem essas duas tags, as tags versionadas (`:1.7.2`, …) aparecerão no primeiro push de uma tag `vX.Y.Z`.

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

## Windows (WSL2) com uma GPU NVIDIA

Execute a pilha completa de scoring + visualizador em GPU no Docker no Windows via WSL2 — sem o Docker Desktop. Isso mantém tudo (a distribuição Linux, suas imagens Docker e `/var/lib/docker`) em uma **unidade de dados** (por ex. `D:`), o que importa quando a unidade do sistema `C:` está com pouco espaço.

**Pré-requisitos:** um driver NVIDIA recente no Windows (`nvidia-smi` funciona no prompt do Windows — o driver fornece o passthrough de CUDA para o WSL2; você **não** instala nenhum driver dentro do WSL).

### 1. Instalar o WSL2 (admin, uma vez)

Em um PowerShell **elevado** (executado como administrador) e reinicie se solicitado:

```powershell
wsl --install --no-distribution   # WSL2 platform only, no distro on C:
```

### 2. Instalar uma distribuição cujo disco fica na unidade de dados

```powershell
wsl --install -d Ubuntu --location D:\wsl\facet --name facet --no-launch
```

`--location` coloca o `ext4.vhdx` da distribuição em `D:\wsl\facet`, para que o armazenamento de imagens do Docker fique fora de `C:`. `--no-launch` pula o prompt interativo de primeira execução; os comandos abaixo rodam como `root`, o que é adequado para uma máquina dedicada a um único propósito.

### 3. Habilitar o systemd (necessário para o serviço docker)

```powershell
wsl -d facet -u root -- bash -lc 'printf "[boot]\nsystemd=true\n" > /etc/wsl.conf'
wsl --shutdown           # apply on next start
```

### 4. Instalar o Docker CE + o NVIDIA Container Toolkit (dentro da distribuição)

```bash
wsl -d facet -u root
# --- inside the distro ---
apt-get update && apt-get install -y ca-certificates curl gnupg
# Docker repo (fall back to the newest supported codename if yours is too new):
. /etc/os-release; CODE=$VERSION_CODENAME
curl -fsSL -o /dev/null "https://download.docker.com/linux/ubuntu/dists/$CODE/Release" || CODE=noble
install -m0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $CODE stable" > /etc/apt/sources.list.d/docker.list
# NVIDIA toolkit repo (distribution-agnostic):
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  > /etc/apt/sources.list.d/nvidia-container-toolkit.list
apt-get update && apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin nvidia-container-toolkit
nvidia-ctk runtime configure --runtime=docker
nvidia-ctk config --set nvidia-container-cli.no-cgroups=true --in-place   # WSL2 has no nvidia cgroup
systemctl enable --now docker
# Verify GPU passthrough:
docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu24.04 nvidia-smi --query-gpu=name,memory.total --format=csv
```

### 5. Compilar e executar o Facet, um arquivo por perfil

O repositório na unidade Windows fica visível dentro do WSL em `/mnt/d/...`. A imagem é **autônoma**: as dependências ficam fixadas em `requirements.lock.txt` (um conjunto de versões testado e congelado — veja "Imagem reproduzível e autônoma" abaixo), e todos os caches de modelos ficam em **volumes nomeados** gerenciados pelo Docker, de modo que o container nunca lê os caches de modelos nativos do host nem nenhum estado local compartilhado. Os modelos são baixados uma única vez na primeira execução para esses volumes e persistem.

Escolha o perfil com um arquivo de sobreposição por perfil — sem precisar editar nenhum JSON:

```bash
cd /mnt/d/photo-llm
# legacy (CPU-only): CLIP ViT-L-14 + CLIP-MLP aesthetic + CLIP tagging
docker compose -f docker-compose.yml -f docker-compose.legacy.yml up -d --build
# 8gb (GPU): CLIP + TOPIQ + SAMP-Net + faces + saliency
docker compose -f docker-compose.yml -f docker-compose.8gb.yml up -d --build
# 16gb (GPU): SigLIP2 + TOPIQ + Qwen3.5-2B tagging + BiRefNet saliency
docker compose -f docker-compose.yml -f docker-compose.16gb.yml up -d --build

curl -s localhost:5000/health          # -> ok
```

Cada sobreposição define `FACET_VRAM_PROFILE` (respeitado por `config/scoring_config.py`, substituindo `models.vram_profile` na configuração — sem edição de JSON) e, para os perfis de GPU, reserva a GPU NVIDIA. Os perfis de GPU (8gb/16gb/24gb) agrupam rostos na GPU via o RAPIDS cuML embutido; o perfil legacy sempre agrupa na CPU. O `docker-compose.gpu.yml` genérico permanece para uma execução simples com GPU usando o `vram_profile` próprio da configuração (padrão `auto`).

A primeira execução baixa os modelos do perfil para os volumes nomeados; redefina-os com `docker compose down -v`.

### Imagem reproduzível e autônoma

- **Versões fixadas.** A imagem é compilada a partir de `requirements.lock.txt` — um `pip freeze` completo de um container validado, com `torch`/`torchvision` e `nvidia-*` removidos (a imagem base CUDA já os fornece). Isso evita deriva silenciosa para versões não testadas. (Exemplo do que isso evita: o transformers 5.3+ mudou o processamento em lote de visão do Qwen3.5 e quebrou o marcador VLM; o `kornia`, exigido pelo BiRefNet, não é trazido pelo transformers e precisa ser fixado.) Regenere após uma atualização intencional: `docker compose ... exec facet pip freeze --all | grep -ivE '^(pip|wheel|torch|torchvision|nvidia-|triton)' > requirements.lock.txt`.
- **Agrupamento de rostos em GPU embutido.** O RAPIDS cuML (`cuml-cu12`) vem embutido na imagem, então os perfis de GPU (8gb/16gb/24gb) agrupam rostos na GPU (HDBSCAN via `face_clustering.use_gpu="auto"`); o perfil legacy — e qualquer host sem dispositivo CUDA — sempre agrupa na CPU. O cuML é, de longe, a maior dependência (~5,75 GB; veja o detalhamento de tamanhos abaixo).
- **Nenhum acoplamento com o host.** Os caches de modelos são volumes nomeados, não montagens do host; o container roda sem privilégios (o entrypoint padrão passa para o usuário `facet`).
- **Contexto de compilação enxuto.** O `.dockerignore` exclui volumosos apenas locais (`conda/`, conjuntos de dados de exemplo, `*.db`, caches, artefatos de desenvolvimento) — mantenha novos diretórios locais grandes fora do contexto adicionando-os ali.

### Tamanho da imagem e downloads de modelos

Duas variantes são publicadas a partir do mesmo `Dockerfile` — **nenhuma contém os pesos dos modelos**:

| Imagem | Tamanho medido | Base |
|-------|------|------|
| `ghcr.io/ncoevoet/facet:latest` (CPU) | ~3,3 GB | `python:3.12-slim` + PyTorch em wheels de CPU |
| `ghcr.io/ncoevoet/facet:latest-cuda` (GPU) | ~21 GB | PyTorch CUDA + RAPIDS cuML |

**Imagem CPU** — o tamanho mais relevante para a maioria dos usuários, dominado pela pilha de dependências de ML, e não pelo PyTorch em si:

| Camada | Tamanho |
|-------|------|
| Dependências de ML do Python (opencv, transformers, insightface, pyiqa, scipy, hdbscan, …) | ~1,9 GB |
| PyTorch + torchvision (wheels de CPU) | ~960 MB |
| Bibliotecas do sistema (`libgl1`, `libglib2.0-0`, `exiftool`, `gosu`) | ~288 MB |
| SO base (`python:3.12-slim`) + código do app | ~150 MB |

**Imagem CUDA** — inalterada em relação à imagem única que este repositório publicava antes, ainda dominada pela pilha de GPU:

| Camada | Tamanho |
|-------|------|
| RAPIDS cuML (agrupamento de rostos na GPU) | ~5,75 GB |
| Bibliotecas de runtime do CUDA (`nvidia-*`) | ~3,7 GB |
| PyTorch + Triton | ~1,9 GB |
| Dependências de ML do Python (transformers, pyiqa, insightface, …) | ~1,9 GB |
| SO base + conda | ~2-3 GB |

Os pesos dos modelos são **baixados na primeira execução** para os volumes nomeados (`facet-hf-cache`, `facet-insightface`, `facet-pretrained`) — nunca para a imagem —, então o tamanho em disco depende do perfil ativo:

| Modelo | Tamanho | Perfis |
|-------|------|----------|
| SigLIP 2 NaFlex SO400M (embeddings) | ~4,3 GB | 16gb / 24gb |
| Qwen3.5-2B (marcação) | ~4,2 GB | 16gb |
| Qwen3.5-4B (marcação) | ~8 GB | 24gb |
| Qwen2-VL-2B (composição) | ~4,2 GB | 24gb |
| CLIP ViT-L-14 (embeddings + marcação) | ~1,6 GB | legacy / 8gb |
| BiRefNet (saliência) | ~424 MB | todos |
| InsightFace buffalo_l (rostos) | ~600 MB | todos |
| SAMP-Net (composição) | ~175 MB | todos |

**Total de download na primeira execução por perfil:** legacy / 8gb ~3-4 GB, 16gb ~10-11 GB, 24gb ~18 GB. Reserve espaço em disco para a imagem **mais** esses volumes; `docker compose down -v` apaga os volumes e força um novo download na próxima inicialização.

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

### Um trabalho de biblioteca por vez

Um escaneamento, `--recompute-average`, `--upgrade-db` e um treinamento do ranqueador pessoal reescrevem cada um o banco de dados inteiro, então o Facet permite apenas um por vez: cada um toma um arquivo de bloqueio em `<db_dir>/.facet_cache/library.lock`, e um segundo trabalho se recusa a iniciar, nomeando o que já está em execução.

Esse bloqueio é um bloqueio de arquivo do kernel, portanto exclui trabalhos **apenas em uma máquina**. Quando o banco de dados é acessado por SMB/CIFS — por exemplo, uma estação de trabalho Windows pontuando fotos em um compartilhamento de NAS —, cada máquina toma sua própria cópia do bloqueio e nenhuma enxerga a outra. O Facet detecta a montagem e registra um aviso ao tomar o bloqueio, mas não pode impor nada entre máquinas: execute os trabalhos de biblioteca a partir de uma única máquina por vez. NFS entre clientes Linux não é afetado — lá o `flock` vira um bloqueio de registro POSIX arbitrado pelo servidor.

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
