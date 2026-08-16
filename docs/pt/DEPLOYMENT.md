# Guia de Implantação

> 🌐 [English](../DEPLOYMENT.md) · [Français](../fr/DEPLOYMENT.md) · [Deutsch](../de/DEPLOYMENT.md) · [Italiano](../it/DEPLOYMENT.md) · [Español](../es/DEPLOYMENT.md) · **Português**

Execute o visualizador do Facet em um servidor remoto ou NAS.

> **Chegando agora?** Este guia é para servir o Facet a outras máquinas. Para colocá-lo
> rodando na sua própria máquina, comece pela [Instalação](INSTALLATION.md).

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

## Semântica de caminhos em contêiner

Tudo que você digita em um campo de pasta no visualizador — um destino de "Selecionar para pasta", o destino de exportação copiar/symlink de um álbum, ou `viewer.export.allowed_target_dirs` em `scoring_config.json` — é resolvido pelo próprio processo do Facet. **No Docker/Podman esse processo roda dentro do contêiner**, então todo caminho é o caminho que *o contêiner* vê: o ponto de montagem, nunca o caminho do lado do host.

**Exemplo.** O `docker-compose.yml` fornecido monta sua pasta de fotos em `/data/photos`:

```yaml
volumes:
  - ${PHOTOS_DIR:-./photos}:/data/photos
```

Para selecionar rejeitadas para uma subpasta `rejects`, digite `/data/photos/rejects` na caixa de diálogo — nunca o caminho do host (`/home/voce/Fotos`, `D:\Fotos`, …), que o contêiner não consegue ver de forma alguma. O mesmo vale para `viewer.export.allowed_target_dirs`: liste o caminho do lado do contêiner.

Para gravar em outro lugar que não a árvore de fotos varrida — um volume de exportação separado, por exemplo —, monte-o primeiro no contêiner e depois adicione seu caminho do lado do contêiner a `viewer.export.allowed_target_dirs`:

```yaml
services:
  facet:
    volumes:
      - ${PHOTOS_DIR:-./photos}:/data/photos
      - /volume1/Exports:/data/exports   # volume extra para saída de cull/export
```

```json
{
  "viewer": {
    "export": {
      "allowed_target_dirs": ["/data/exports"]
    }
  }
}
```

Um destino que se resolve fora de todo volume montado é recusado (`403`) — a verificação de target-dir do Facet executa `os.path.realpath()` tanto na requisição *quanto* em cada raiz permitida, resolvendo links simbólicos e `..` antes de comparar, então um caminho que só parece correto de fora do contêiner (ou um link simbólico apontando para fora de uma montagem) ainda falha no teste de contenção. Veja [Configuração — Destinos de exportação e seleção](CONFIGURATION.md#destinos-de-exportação-e-seleção) para a referência completa da lista de permissões.

**Isso não é um problema de permissões do usuário do contêiner.** O UID do usuário `facet` dentro do contêiner costuma diferir do da sua conta no host, e isso pode causar um problema real e separado de permissões do sistema de arquivos em um bind mount — mas isso acontece *depois* que essa verificação de caminho é aprovada, quando a cópia/symlink/movimentação realmente roda, e é registrado no servidor com o erro subjacente do sistema operacional para o arquivo que falhou. Um `403 target_dir is not an allowed export location` (ou um "acesso negado" genérico na interface) acontece *antes* de qualquer arquivo ser tocado e não tem nada a ver com UIDs.

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
- Remove os embeddings CLIP, os embeddings de legenda e os embeddings de rostos
- Mantém o histograma por foto (~2 KB cada), lido pelo widget de histograma RGB da galeria
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

Isso substitui as configurações globais de `performance` (que são ajustadas para a pontuação) por valores adequados para 1GB de RAM. Consulte [Configuração](CONFIGURATION.md#desempenho-do-visualizador) para detalhes.

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

### Executando a imagem publicada

Instale exatamente como em
[Instalação › Instalar com Docker](INSTALLATION.md#instalar-com-docker):
`docker compose up -d` para um NAS somente CPU, ou o bloco específico do perfil se a
máquina tiver uma placa NVIDIA. Os ajustes do `.env` e a montagem da configuração estão
documentados em
[Instalação › Configurações do Docker que você pode alterar](INSTALLATION.md#configurações-do-docker-que-você-pode-alterar).
O que segue é apenas o que muda em um NAS.

**Ambas as imagens publicadas são apenas `linux/amd64` (x86_64).** Isso cobre o hardware NAS x86 (Synology Plus/x86, UGREEN, UnifyDrive e qualquer coisa que execute Coolify, Portainer ou Docker comum em uma CPU Intel/AMD). Não existe uma imagem `arm64`: a compilação cruzada de uma pilha de ML de vários gigabytes sob QEMU custa horas por tag, e a variante CUDA é, de qualquer forma, exclusiva de x86. Em um NAS ARM ou um Raspberry Pi, compile localmente com `docker compose build` em vez de baixar — `docker compose up` mantém `build: .` abaixo da chave `image:` exatamente para esse caso.

**Reserve espaço em disco.** Já descompactada, a imagem CPU tem aproximadamente 3,3 GB
em disco e a imagem CUDA aproximadamente 21 GB (valores aproximados, não reverificados
com a build atual; o próprio download transfere menos, compactado — veja
[Tamanho da imagem](#tamanho-da-imagem) mais abaixo), além dos pesos de modelo que cada
perfil baixa na primeira execução (`legacy` 4,69 GB, `8gb` 6,93 GB, `16gb` 14,55 GB,
`24gb` 19,13 GB — tabela completa em
[Instalação › Tamanhos de download](INSTALLATION.md#tamanhos-de-download)).
`docker compose down -v` apaga os volumes de modelos e força um novo download.

**Tags versionadas.** `:latest` e `:latest-cuda` avançam a cada release; fixe uma versão
(`:1.7.2`, `:1.7`, `:1.7.2-cuda`, …) em um NAS que você não quer que mude sozinho. Ambas
as variantes são compiladas a partir do mesmo `Dockerfile`, com os build args
`BASE_IMAGE`, `STRIP_TORCH` e `INSTALL_CUML`, definidos por variante em
`.github/workflows/docker-publish.yml`. Esse workflow também aceita uma execução manual
via `workflow_dispatch`, que republica `latest` / `latest-cuda` a partir de `master` sem
cortar uma release nem gerar uma tag versionada.

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

### 5. Executar o Facet

O repositório na unidade Windows fica visível dentro do WSL em `/mnt/d/...`. A partir
daí, execute o bloco da sua placa a partir de
[Instalação › Instalar com Docker](INSTALLATION.md#instalar-com-docker):

```bash
cd /mnt/d/photo-llm
docker compose -f docker-compose.yml -f docker-compose.16gb.yml up -d   # ou o arquivo da sua placa
curl -s localhost:5000/health          # -> ok
```

Adicione `--build` para compilar a partir do checkout em vez de baixar a imagem
publicada. Os perfis de GPU (`8gb`/`16gb`/`24gb`) agrupam rostos na GPU via o RAPIDS cuML
já embutido; o perfil `legacy` sempre agrupa na CPU. A primeira execução baixa os modelos
do perfil para os volumes nomeados; redefina-os com `docker compose down -v`.

### Imagem reproduzível e autônoma

- **Versões fixadas.** A imagem é compilada a partir de `requirements.lock.txt` — um `pip freeze` completo de um container validado, com `torch`/`torchvision` e `nvidia-*` removidos (a imagem base CUDA já os fornece). Isso evita deriva silenciosa para versões não testadas. (Exemplo do que isso evita: o transformers 5.3 mudou o processamento em lote de visão do Qwen3.5 e quebrou o marcador VLM até a correção de padding chegar; o `kornia`, exigido pelo BiRefNet, não é trazido pelo transformers e precisa ser fixado.) Regenere após uma atualização intencional: `docker compose ... exec facet pip freeze --all | grep -ivE '^(pip|wheel|torch|torchvision|nvidia-|triton)' > requirements.lock.txt`.
- **Agrupamento de rostos em GPU embutido.** O RAPIDS cuML (`cuml-cu12`) vem embutido na imagem, então os perfis de GPU (8gb/16gb/24gb) agrupam rostos na GPU (HDBSCAN via `face_clustering.use_gpu="auto"`); o perfil legacy — e qualquer host sem dispositivo CUDA — sempre agrupa na CPU. O cuML é, de longe, a maior dependência (~5,75 GB; veja o detalhamento de tamanhos abaixo).
- **Nenhum acoplamento com o host.** Os caches de modelos são volumes nomeados, não montagens do host; o container roda sem privilégios (o entrypoint padrão passa para o usuário `facet`).
- **Contexto de compilação enxuto.** O `.dockerignore` exclui volumosos apenas locais (`conda/`, conjuntos de dados de exemplo, `*.db`, caches, artefatos de desenvolvimento) — mantenha novos diretórios locais grandes fora do contexto adicionando-os ali.

### Tamanho da imagem

Nenhuma das imagens publicadas contém os pesos dos modelos — eles são baixados na
primeira execução para os volumes nomeados
([totais por perfil](INSTALLATION.md#tamanhos-de-download)). Reserve espaço em disco
para a imagem **mais** esses volumes.

| Imagem | Download compactado | Em disco (aprox.) | Base |
|-------|------|------|------|
| `ghcr.io/ncoevoet/facet:latest` (CPU) | 4,18 GB | ~3,3 GB | `python:3.12-slim` + PyTorch em wheels de CPU |
| `ghcr.io/ncoevoet/facet:latest-cuda` (GPU) | 7,33 GB | ~21 GB | PyTorch CUDA + RAPIDS cuML |

O "download compactado" é o que o `docker pull` transfere, medido a partir dos
manifestos atuais do registro `ghcr.io/ncoevoet/facet`. O valor "em disco" é o espaço
ocupado pela imagem já descompactada; esses números não foram reverificados em relação
ao digest `:latest` atual nesta rodada, então trate-os como uma estimativa aproximada
de planejamento, não como uma medição atual precisa.

A imagem CPU é dominada pela pilha de dependências de ML (~1,9 GB), e não pelo PyTorch em
si (~960 MB), além das bibliotecas de sistema (~288 MB) e do SO base (~150 MB). Na imagem
CUDA, a pilha de GPU domina: RAPIDS cuML ~5,75 GB, bibliotecas de runtime do CUDA ~3,7 GB,
PyTorch e Triton ~1,9 GB, dependências de ML ~1,9 GB, SO base e conda ~2-3 GB.

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

## Armazenamento e rotação do segredo

Um único segredo assina cada sessão de login (JWT) e cada link do porta-retratos digital. **Não** é uma chave de `scoring_config.json`: ele fica em `.facet_secret`, ao lado da configuração, criado com modo `0600` na primeira execução e ignorado pelo git.

Antes era a chave `share_secret` dentro de `scoring_config.json`. Esse arquivo é rastreado pelo git, então o valor gerado na primeira execução foi commitado e publicado — o segredo distribuído por este projeto é público e deve ser considerado comprometido. Na inicialização seguinte, o Facet move qualquer `share_secret` remanescente para o arquivo do segredo, remove a chave da configuração e registra um aviso. Um valor que o próprio Facet publicou é substituído em vez de mantido, o que desconecta todo mundo de propósito.

| Onde | Como |
|------|------|
| Padrão | `.facet_secret` ao lado de `scoring_config.json`, modo `0600` |
| Contêiner / orquestrador | Variável de ambiente `FACET_JWT_SECRET` — lida primeiro, nunca gravada em disco |
| Rotação | `python database.py --rotate-secret` e depois reinicie o viewer |

No Docker, `/app` é a camada gravável do contêiner: um segredo criado ali se perde quando o contêiner é recriado — a cada atualização de imagem todo mundo é desconectado. Defina `FACET_JWT_SECRET` no `docker-compose.yml`, ou monte o arquivo com `- ./.facet_secret:/app/.facet_secret`.

Faça a rotação sempre que o segredo puder ter sido lido por outra pessoa: uma configuração que já foi commitada, um backup vazado, um administrador que sai. A rotação invalida cada sessão e cada URL assinada do porta-retratos: os usuários entram de novo e os dispositivos de quiosque buscam novos links.

Com `--workers > 1` todos os workers leem o mesmo arquivo, então um JWT assinado por um vale em todos — **assim que esse arquivo existir**. Uma primeira inicialização com `--workers > 1` e ainda sem `.facet_secret` é a exceção: cada worker gera o próprio segredo e apenas um vence a escrita, de modo que uma sessão aberta em um worker é rejeitada pelos outros até o servidor ser reiniciado. Crie o segredo antes da primeira inicialização multi-worker — execute uma vez `python database.py --rotate-secret`, inicie uma vez com `--workers 1`, ou defina `FACET_JWT_SECRET`.

Essa mesma divergência se torna permanente quando o diretório de instalação não é gravável: o servidor registra um erro e funciona com um segredo em memória, então cada sessão morre a cada reinicialização e cada worker assina com uma chave diferente. Defina ali `FACET_JWT_SECRET`.

Inclua o arquivo no backup do banco de dados — restaurar um banco sem ele desconecta todo mundo.

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
