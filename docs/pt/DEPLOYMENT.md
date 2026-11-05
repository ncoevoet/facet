# Guia de Implantação

> 🌐 [English](../DEPLOYMENT.md) · [Français](../fr/DEPLOYMENT.md) · [Deutsch](../de/DEPLOYMENT.md) · [Italiano](../it/DEPLOYMENT.md) · [Español](../es/DEPLOYMENT.md) · **Português** · [简体中文](../zh/DEPLOYMENT.md)

Execute o visualizador do Facet em um servidor remoto ou NAS.

> **Chegando agora?** Este guia é para servir o Facet a outras máquinas. Para colocá-lo
> rodando na sua própria máquina, comece pela [Instalação](INSTALLATION.md).

## Visão geral

O Facet tem duas cargas de trabalho:

| Componente | Hardware | Finalidade |
|-----------|----------|---------|
| **Pontuação** (`facet.py`) | GPU (6-24GB VRAM) ou CPU (8GB de RAM no mínimo, 12GB recomendado; mais para `12gb`/`16gb`/`24gb`, veja [Limites de memória do contêiner](#limites-de-memória-do-contêiner)) | Analisar e pontuar fotos |
| **Visualizador** (`viewer.py`) | Qualquer máquina (poucos recursos) | Servir a galeria web |

Apenas o visualizador precisa rodar no servidor. Pontue em uma estação de trabalho e, em seguida, sincronize o banco de dados.

> **Aviso:** enquanto `viewer.password` estiver vazio (o padrão), qualquer pessoa que alcance
> a porta do visualizador pode navegar por toda a biblioteca e baixar as fotos originais.
> Defina `viewer.password` antes de expor a porta além da máquina; veja
> [Modo de Usuário Único](VIEWER.md#modo-de-usuário-único-padrão).

Em uma instalação aberta (sem `viewer.password`), os tokens do assistente (**Ligar um assistente**)
só se criam, listam e revogam a partir do computador onde o Facet está rodando. Atrás do Docker
ou de um proxy inverso, defina `viewer.password` ou execute o pedido no host
(`docker compose exec facet python -c "import urllib.request ..."`). Um proxy inverso tem de
enviar `X-Forwarded-For` ou `Forwarded`; caso contrário é tratado como a máquina local.

## Mapeamento de caminhos

Quando a máquina de pontuação e o visualizador veem as fotos em caminhos diferentes, configure
`viewer.path_mapping` em `scoring_config.json` para traduzir os caminhos do banco de dados em caminhos locais.

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

Isso mapeia `\\NAS\share\Photos\2024\IMG_001.jpg` para `/volume1/Photos/2024/IMG_001.jpg`.
Use barras normais nas chaves; as barras invertidas são normalizadas.

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

- O banco de dados mantém os caminhos originais da varredura (por exemplo, `\\NAS\share\Photos\2024\IMG_001.jpg`).
- As miniaturas ficam no banco de dados, então a navegação não precisa de acesso ao disco.
- O mapeamento é aplicado sempre que o visualizador abre um original: downloads, visualização em
  resolução total, legendagem e crítica.
- Tanto caminhos UNC (`\\server\share`) quanto letras de unidade (`Z:\`) funcionam.

## Semântica de caminhos em contêiner

No Docker/Podman, toda pasta digitada no visualizador é um caminho **dentro do contêiner**.
Isso vale para o destino de "Selecionar para pasta", o destino de exportação de um álbum e
`viewer.export.allowed_target_dirs`. Use o ponto de montagem, nunca o caminho do host.

**Exemplo.** O `docker-compose.yml` fornecido monta suas fotos em `/data/photos`:

```yaml
volumes:
  - ${PHOTOS_DIR:-./photos}:/data/photos
```

Para selecionar rejeitadas para uma subpasta `rejects`, digite `/data/photos/rejects`, não
`/home/voce/Fotos` nem `D:\Fotos`, que o contêiner não consegue ver.

Para gravar fora da árvore de fotos, monte primeiro o destino e depois liste o caminho do lado do
contêiner em `viewer.export.allowed_target_dirs`:

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

Um destino fora de todas as raízes permitidas é recusado, depois de resolver links simbólicos e `..`.
Veja [Configuração — Destinos de exportação e seleção](CONFIGURATION.md#destinos-de-exportação-e-seleção).

**Essa recusa não é um problema de permissões.** Ela acontece antes de qualquer arquivo ser tocado. Uma
divergência de uid entre o usuário `facet` do contêiner e sua conta no host é uma falha separada:
ocorre durante a cópia/movimentação e é registrada com o erro do sistema operacional.

### Para onde vai a lixeira de um contêiner

Com `viewer.cull.allow_trash` ativado, `trash_rejects` usa `send2trash`. No layout fornecido
(fotos montadas via bind em `/data/photos`, uid 1000, `HOME=/home/facet`), as fotos e o
`$HOME` ficam em sistemas de arquivos diferentes, então os arquivos enviados para a lixeira vão para a lixeira do próprio volume de fotos:

- arquivos: `/data/photos/.Trash-1000/files/<nome>`
- metadados: `<nome>.trashinfo` (com `Path=` e `DeletionDate=`) em `/data/photos/.Trash-1000/info/`
- o diretório é criado com o modo `0700`

`.Trash-1000` fica visível no **host**, então um simples `mv` para fora de `files/` restaura uma foto.
As novas varreduras o ignoram enquanto `scanning.skip_hidden_directories` for verdadeiro (o padrão).

Dois casos diferentes:

- **Sem bind mount** para as fotos (por exemplo, um `docker run` com as fotos dentro do contêiner):
  a lixeira vai para `~/.local/share/Trash` no contêiner e **se perde quando o contêiner é
  removido**.
- **Podman sem root**: `.Trash-1000` pertence ao subuid do host mapeado, não à sua conta;
  restaurar pode exigir `podman unshare`.

Para escolher o destino você mesmo, use `move_rejects` para um `target_dir`
([Selecionar para pasta](VIEWER.md#selecionar-para-pasta)).

### Propriedade do arquivo de configuração

O Facet só assume a posse de um `/config/scoring_config.json` que ele mesmo criou; um arquivo existente
mantém o dono e as permissões. A única exceção (uma configuração que o usuário `facet` do contêiner não consegue
ler) e a receita para Podman sem root estão em
[Instalação — Propriedade do arquivo no contêiner](INSTALLATION.md#propriedade-do-arquivo-no-contêiner).

Com `group_add` do compose (veja [Compartilhamentos de fotos legíveis apenas por um grupo](#compartilhamentos-de-fotos-legíveis-apenas-por-um-grupo-group_add)),
a verificação de legibilidade também usa esses grupos, então uma configuração legível por meio de um desses grupos é
deixada como está. Se a própria verificação `setpriv` falhar, o arquivo é tratado como ilegível.

## Compilando o cliente Angular

O servidor serve a SPA pré-compilada a partir de `client/dist/client/browser/`. Compile-a antes de
implantar:

```bash
cd client && npm install && npx ng build && cd ..
```

Isso requer Node.js 20+ apenas no momento da compilação, não no servidor.

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

Na estação de trabalho de pontuação, exporte um banco de dados menor para o NAS:

```bash
python database.py --export-viewer-db
```

Isso cria `photo_scores_viewer.db`, que:

- remove os embeddings CLIP, de legenda e de rostos;
- mantém o histograma por foto (~2 KB cada) para o widget de histograma RGB;
- reduz as miniaturas de 640px para 320px;
- normalmente reduz um banco de dados de 14GB para ~4-5GB.

As exportações são incrementais: apenas as fotos novas e alteradas são sincronizadas. Para uma reconstrução completa:

```bash
python database.py --export-viewer-db --force-export
```

> **Aviso:** `--force-export` descarta as classificações, localizações e tags manuais definidos no
> visualizador no NAS. Apenas uma exportação incremental os mantém.

"Encontrar semelhantes" não funciona no banco de dados exportado (sem embeddings). Use a
máquina de pontuação para isso.

**Tags manuais.** A exportação inclui as [tags manuais](VIEWER.md#tags-manuais)
(`photo_manual_tags`). Uma exportação incremental apenas acrescenta as tags do banco de dados de pontuação:

- Uma tag removida no NAS volta se o banco de dados de pontuação ainda a tiver.
- Uma tag adicionada no NAS nunca é copiada de volta; adicione-a também na máquina de pontuação.
- Uma tag removida na máquina de pontuação permanece no NAS até `--force-export`.
- O limite de 50 tags por foto não é aplicado na mesclagem, então uma foto pode ultrapassá-lo.

### Sincronizando arquivos

Compile primeiro o cliente Angular ([Compilando o cliente Angular](#compilando-o-cliente-angular)),
depois sincronize com o NAS:

```bash
rsync -avz \
  viewer.py config_resolve.py database.py tagger.py \
  photo_scores_viewer.db \
  api/ client/dist/ config/ db/ i18n/ \
  admin@your-synology-ip:/volume1/facet/
```

`config/` carrega os padrões distribuídos, então o NAS roda com esses valores. Para usar seu próprio
`scoring_config.json`, adicione-o à lista do `rsync`. Revise-o primeiro: ele contém a senha do
visualizador e as chaves de API em texto simples.

O visualizador abre `photo_scores_pro.db` por padrão (substituível com `DB_PATH`). No NAS,
defina `DB_PATH=/volume1/facet/photo_scores_viewer.db` ou crie um link simbólico:

```bash
cd /volume1/facet
ln -sf photo_scores_viewer.db photo_scores_pro.db
```

Para os downloads, os originais devem estar acessíveis no NAS no caminho de `path_mapping`.

### Configuração para pouca memória

Adicione `viewer.performance` ao `scoring_config.json` no NAS:

```json
{
  "viewer": {
    "performance": {
      "mmap_size_mb": 0,
      "cache_size_mb": 4,
      "pool_size": 2,
      "thumbnail_cache_size": 200
    }
  }
}
```

Isso substitui as configurações globais de `performance` (ajustadas para a pontuação) por valores para 1GB
de RAM. Consulte [Configuração](CONFIGURATION.md#desempenho-do-visualizador).

### Execução

```bash
cd /volume1/facet

# Teste
python3 viewer.py

# Produção (1 worker para 1GB de RAM)
uvicorn api:create_app --factory --host 0.0.0.0 --port 5000 --workers 1
```

Acesse em `http://your-synology-ip:5000`.

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

Use o proxy reverso do Synology: DSM > Painel de Controle > Portal de Login > Avançado > Proxy Reverso:

| Origem | Destino |
|--------|-------------|
| `https://photos.yourdomain.com:443` | `http://localhost:5000` |

Adicione um certificado Let's Encrypt em DSM > Painel de Controle > Segurança > Certificado.

Para a ponte de aba para agentes ([Agentes de IA](AGENTS.md)), abra a aba **Cabeçalho personalizado**
da regra e escolha **Criar > WebSocket**. Isso acrescenta os cabeçalhos `Upgrade` e `Connection`
de que `/api/mcp/bridge` precisa. Se a regra reescrever o cabeçalho `Host`, indique a sua origem pública em
`viewer.mcp.allowed_origins`.

## Synology NAS (série Plus / x86)

O NAS da série Plus suporta Docker (Container Manager).

### Executando a imagem publicada

Instale como em [Instalação › Instalar com Docker](INSTALLATION.md#instalar-com-docker):
`docker compose up -d` em um NAS somente CPU, ou o bloco específico do perfil com uma placa NVIDIA. Os ajustes do
`.env` e a montagem da configuração estão em
[Instalação › Configurações do Docker que você pode alterar](INSTALLATION.md#configurações-do-docker-que-você-pode-alterar).
O que segue é apenas o que muda em um NAS.

**As imagens são apenas `linux/amd64` (x86_64).** Isso cobre o hardware NAS x86 (Synology
Plus/x86, UGREEN, UnifyDrive, Coolify, Portainer ou Docker comum em Intel/AMD). Não existe
uma imagem `arm64`. Em um NAS ARM ou um Raspberry Pi, compile localmente com
`docker compose build`; o arquivo compose mantém `build: .` abaixo da chave `image:` para esse caso.

**Reserve espaço em disco:** a imagem mais os modelos que cada perfil baixa na primeira execução.

- Imagens, descompactadas: CPU ~3,34 GB, `latest-cuda` (`sm_75`-`sm_120`) ~13,1 GB,
  `latest-cuda-legacy` (`sm_50`-`sm_90`) ~13,8 GB ([Tamanho da imagem](#tamanho-da-imagem)).
  O `docker pull` baixa menos, compactado.
- Modelos: `legacy` 4,69 GB, `8gb` 6,93 GB, `12gb`/`16gb` 14,55 GB, `24gb` 19,32 GB
  ([Tamanhos de download](INSTALLATION.md#tamanhos-de-download)).
- `docker compose down -v` apaga os volumes de modelos e força um novo download.

**Tags versionadas.** `:latest`, `:latest-cuda` e `:latest-cuda-legacy` avançam a cada
release. Fixe uma versão (`:1.7.2`, `:1.7`, `:1.7.2-cuda`, `:1.7.2-cuda-legacy`, …) em um NAS
que você não quer que mude sozinho. As variantes são compiladas a partir de um único `Dockerfile` com os
build args `BASE_IMAGE`, `STRIP_TORCH`, `INSTALL_CUML` e `REQUIREMENTS_LOCK`, definidos em
`.github/workflows/docker-publish.yml`. Uma execução manual via `workflow_dispatch` desse workflow
republica `latest` / `latest-cuda` / `latest-cuda-legacy` a partir de `master` sem uma release.

**Build comercial.** Adicione `--build-arg FACET_LICENSING=commercial` (compose:
`build.args.FACET_LICENSING: commercial`). Isso pula o lock restrito (`insightface`,
`pyiqa` e suas dependências) e define `FACET_LICENSING_MODE=commercial`. O padrão
`FACET_LICENSING=default` mantém o comportamento publicado. O lock restrito segue
`REQUIREMENTS_LOCK` (`requirements.legacy.restricted.lock.txt` para o lock legacy). Veja
[Instalação](INSTALLATION.md#instalação-comercial-e-pacotes-restritos).

Para uma imagem pequena apenas de visualização (sem CUDA), compile uma enxuta. Toda origem `COPY` deve estar
versionada no git, e por isso `scoring_config.json` não é copiado; sem ele, o contêiner
roda com os padrões de `config/`.

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN pip install fastapi uvicorn pyjwt pillow aiosqlite 'mcp>=2.3,<3' 'httpx>=0.28,<1' 'websockets>=13.0'
COPY viewer.py config_resolve.py database.py tagger.py ./
COPY api/ api/
COPY config/ config/
COPY client/dist/ client/dist/
COPY db/ db/
COPY i18n/ i18n/
EXPOSE 5000
CMD ["uvicorn", "api:create_app", "--factory", "--host", "0.0.0.0", "--port", "5000", "--workers", "4"]
```

> **A ponte de aba para agentes exige um worker.** Com mais de um worker, uma chamada `ui_*` pode chegar a
> um processo que não conhece a sua aba e responder `no_tab`. Use `--workers 1` se usar os
> [Agentes de IA](AGENTS.md).

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

### Compartilhamentos de fotos legíveis apenas por um grupo (`group_add`)

Em um NAS, o compartilhamento de fotos costuma ser legível apenas por um grupo (no Synology, tipicamente
`users`, gid 100). Dê esse grupo ao contêiner com `group_add`, usando o gid numérico
de `id <seu-usuario>` no NAS:

```yaml
services:
  facet:
    group_add:
      - "100"
```

O entrypoint passa de root para `facet` com `setpriv` e preserva esses gids. Confira com
`docker compose exec facet grep Groups /proc/1/status`: a saída lista `1000` mais os seus gids.

Alternativa: executar com `user: "1000:1000"` mais `group_add`. O entrypoint então não faz
chown nem inicializa `/config`, de modo que todo mount já deve ser gravável pelo uid 1000.

## Limites de memória do contêiner

O Facet lê o limite de memória do contêiner (`memory.max` no cgroup v2,
`memory.limit_in_bytes` no v1) em vez da RAM do host. Ele dimensiona em função desse limite quais modelos são carregados
juntos, o tamanho do bloco de RAM, o cache de modelos e a decodificação RAW. As versões anteriores
(v1.7.2 e anteriores) ignoravam `mem_limit` e podiam ser mortas por OOM
([issue #111](https://github.com/ncoevoet/facet/issues/111)).

### Memória mínima recomendada por perfil

Os pesos dos modelos são apenas uma parte do pico de memória: o runtime do torch, as imagens decodificadas e
as ativações se somam a ele. Trate esses números como pisos.

| Perfil de VRAM | Pesos dos modelos (total) | Memória de contêiner recomendada |
|---|---|---|
| `legacy` / `8gb` | 15,0 GB | 12 GB (GPU) / 8 GB mínimo, 12 GB recomendado (CPU) |
| `12gb` / `16gb` | 22,0 GB | pelo menos 18 GB (provisório) |
| `24gb` | 25,0 GB | pelo menos 18 GB (provisório) |

- **GPU e CPU diferem.** Em uma GPU os pesos ficam na VRAM, e a RAM contém principalmente as imagens
  decodificadas: uma execução `8gb` em uma RTX 3080 (405 fotos, `ram_chunk_size: 12`, `num_workers: 2`) atingiu um pico de
  9,23 GB e passou com `mem_limit: 12g`. Em
  CPU, todos os modelos são carregados na RAM. Dimensione pela linha que corresponde a como você roda.
- **8 GB é um piso em CPU.** Varreduras de 50 fotos com `--memory=8g` foram concluídas em `legacy` (pico de 7,26 GB) e
  `8gb` (7,56 GB), a cerca de meio gigabyte do limite em JPEGs de 18-20 MP. Quadros maiores, decodificação
  RAW ou um host ocupado precisam de mais, daí os 12 GB recomendados.
- **`12gb`, `16gb` e `24gb` não foram medidos.** 18 GB é um valor provisório.
- **Pico de VRAM do `12gb`: TODO_VRAM12 GiB (simulado).** Medido com um limite simulado de 12 GiB em uma placa de 16 GB; os modelos do ONNX Runtime (InsightFace) ignoram o limite; não medido em uma placa real de 12 GB.
- **Observe a memória anônima.** O MemUsage do `docker stats` e o `memory.current` do cgroup
  contam o cache de páginas recuperável, então enganam.
- **Cache de modelos.** Com `models.keep_in_ram` em `"auto"`, um modelo permanece na RAM entre
  blocos apenas enquanto o seu tamanho mais `models.ram_cache_reserve_gb` (padrão 4 GB) estiver livre. Uma
  reserva menor faz mais cache ([Configuração](CONFIGURATION.md#models)).

Em CPU, o perfil `8gb` sempre planeja os mesmos 5 passes, qualquer que seja o limite:
`Pass 1: qrealign [~5.0GB RAM]`, `Pass 2: clip + topiq_iaa [~5.0GB RAM]`,
`Pass 3: topiq_nr_face + liqe [~4.0GB RAM]`, `Pass 4: saliency + samp_net [~4.0GB RAM]`,
`Pass 5: insightface [~2.0GB RAM]`.

Defina o limite no `docker-compose.yml` (ou em um arquivo de override):

```yaml
services:
  facet:
    mem_limit: 16g
```

### O agrupamento de passes tem um teto, e nenhum piso

- **Com um limite de contêiner**, cada passe de CPU recebe o limite menos uma reserva de 2 GB, limitado a
  5 GB. Um limite apertado significa um modelo por passe.
- **Sem um limite**, o orçamento é (RAM do sistema − 1 GB) ÷ 1,6. Um host de 4 GB orça 1,9 GB por
  passe, um de 2 GB, 0,6 GB.
- **Um modelo maior do que o orçamento** ainda recebe seu próprio passe, com um aviso que o nomeia. Por
  exemplo, `qwen3_5_4b_tagger` (`24gb`) sozinho dá um passe de 8,0 GB.

> **Aviso:** nunca dimensione um contêiner abaixo do maior modelo individual do seu perfil.

## Windows (WSL2) com uma GPU NVIDIA

Execute a pilha de pontuação em GPU e o visualizador no Docker no Windows via WSL2, sem o Docker
Desktop. Tudo (a distribuição, suas imagens, `/var/lib/docker`) fica em uma **unidade de dados**
(por ex. `D:`), útil quando `C:` está com pouco espaço.

**Pré-requisitos:** um driver NVIDIA recente no Windows (`nvidia-smi` funciona no prompt do Windows).
**Não** instale um driver dentro do WSL.

### 1. Instalar o WSL2 (admin, uma vez)

Em um PowerShell **elevado**, e reinicie se solicitado:

```powershell
wsl --install --no-distribution   # WSL2 platform only, no distro on C:
```

### 2. Instalar uma distribuição cujo disco fica na unidade de dados

```powershell
wsl --install -d Ubuntu --location D:\wsl\facet --name facet --no-launch
```

`--location` coloca o `ext4.vhdx` da distribuição em `D:\wsl\facet`. `--no-launch` pula o
prompt de primeira execução; os comandos abaixo rodam como `root`.

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

O repositório na unidade Windows fica em `/mnt/d/...` dentro do WSL. Execute o bloco da sua placa
a partir de [Instalação › Instalar com Docker](INSTALLATION.md#instalar-com-docker):

```bash
cd /mnt/d/photo-llm
docker compose -f docker-compose.yml -f docker-compose.16gb.yml up -d   # ou o arquivo da sua placa
curl -s localhost:5000/health          # -> ok
```

Adicione `--build` para compilar a partir do checkout em vez de baixar a imagem. Os perfis de GPU
(`8gb`/`12gb`/`16gb`/`24gb`) agrupam rostos na GPU via o RAPIDS cuML embutido; o perfil `legacy`
agrupa na CPU. A primeira execução baixa os modelos para os volumes nomeados; redefina-os com
`docker compose down -v`.

### Imagem reproduzível e autônoma

- **Versões fixadas.** A imagem é compilada a partir de `requirements.lock.txt`, um `pip freeze` de um
  contêiner validado sem `torch`/`torchvision` e `nvidia-*` (a base CUDA os fornece).
  O `kornia`, exigido pelo BiRefNet, também está fixado ali. Regenere após uma atualização
  intencional: `docker compose ... exec facet pip freeze --all | grep -ivE '^(pip|wheel|torch|torchvision|nvidia-|triton)' > requirements.lock.txt`.
- **Agrupamento de rostos em GPU embutido.** O RAPIDS cuML (`cuml-cu12`, ~5,75 GB) permite que os perfis de GPU
  agrupem na GPU (`face_clustering.use_gpu="auto"`). O `legacy`, e hosts sem CUDA,
  agrupam na CPU.
- **Nenhum acoplamento com o host.** Os caches de modelos são volumes nomeados; o contêiner roda como o
  usuário sem privilégios `facet`.
- **Contexto de compilação enxuto.** O `.dockerignore` exclui volumosos locais (`conda/`, conjuntos de dados de exemplo,
  `*.db`, caches); adicione ali novas pastas locais grandes.

### Tamanho da imagem

Nenhuma imagem contém os pesos dos modelos; eles são baixados na primeira execução para os volumes nomeados
([totais por perfil](INSTALLATION.md#tamanhos-de-download)). Reserve espaço em disco para ambos.

| Imagem | Em disco (medido) | Base |
|-------|------|------|
| `ghcr.io/ncoevoet/facet:latest` (CPU) | 3,34 GB | `python:3.12-slim` + PyTorch em wheels de CPU |
| `ghcr.io/ncoevoet/facet:latest-cuda` (GPU) | 13,1 GB | PyTorch CUDA 12.8 (`sm_75`-`sm_120`, de Turing a Blackwell) + RAPIDS cuML |
| `ghcr.io/ncoevoet/facet:latest-cuda-legacy` (GPU) | 13,8 GB | PyTorch CUDA 12.6 (`sm_50`-`sm_90`, de Maxwell a Hopper) + RAPIDS cuML |

"Em disco" é o tamanho descompactado (`docker images`). O `docker pull` baixa menos; os tamanhos
compactados ainda não foram medidos.

## Servidor Linux genérico

### Uvicorn

```bash
pip install fastapi uvicorn pyjwt pillow aiosqlite 'mcp>=2.3,<3' 'httpx>=0.28,<1' 'websockets>=13.0'
uvicorn api:create_app --factory --host 0.0.0.0 --port 5000 --workers 4
```

Ou use o wrapper (1 worker por padrão; `--workers N` para mais):

```bash
python viewer.py --production --workers 4
```

A ponte de aba para agentes exige `--workers 1` (veja
[Executando a imagem publicada](#executando-a-imagem-publicada)).

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

    location /api/mcp/bridge {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $http_host;
        proxy_read_timeout 3600s;
    }
}
```

A ponte de aba para agentes (`/api/mcp/bridge`, veja [Agentes de IA](AGENTS.md)) é um WebSocket. Ela
precisa dos cabeçalhos `Upgrade` e `Connection` do segundo bloco `location` e de um único worker
(`--workers 1`, o padrão); caso contrário, as ferramentas `ui_*` para agentes respondem `no_tab`.

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

Use `--workers 1` se usar a ponte de aba para agentes.

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

Reexecute a exportação e o `rsync` após cada sessão de pontuação. Em um servidor com bastante
memória, você pode sincronizar o `photo_scores_pro.db` completo em vez disso.

### Um trabalho de biblioteca por vez

Uma varredura, `--recompute-average`, `--upgrade-db` e um treinamento do ranqueador reescrevem cada um o
banco de dados, então apenas um roda por vez. Um segundo trabalho se recusa a iniciar, nomeia o que está em execução
e termina com o código 75 (código 1 se o arquivo de bloqueio em `<db_dir>/.facet_cache/library.lock` estiver
inutilizável).

> **Aviso:** esse bloqueio funciona em **apenas uma máquina**. Em SMB/CIFS (por exemplo, uma estação de trabalho
> Windows pontuando fotos em um compartilhamento de NAS), cada máquina tem o seu próprio bloqueio. O Facet registra um
> aviso, mas não pode impedir isso: execute os trabalhos de biblioteca a partir de uma máquina por vez. NFS entre
> clientes Linux não é afetado.

### Início do visualizador e índices da galeria

A primeira inicialização após uma atualização da 1.20 cria os índices da galeria que faltam
([detalhes](VIEWER.md#índices-da-galeria-e-cache-de-contagem)). Em uma biblioteca de ~130k fotos isso
leva alguns minutos e acrescenta cerca de 130 MB ao banco de dados.

**Recomendado:** após a atualização, execute `python database.py` (Docker:
`docker compose exec facet python database.py`) uma vez **antes** de iniciar o visualizador. Uma
varredura `python facet.py` também os cria na sua inicialização.

Se for o visualizador a criá-los:

- Ele atende durante a criação, mas a galeria fica lenta e **os salvamentos (classificações, rejeições, alterações
  de álbum…) podem ser recusados** com a mensagem «biblioteca ocupada, tente novamente».
- O log mostra `Creating index ...` e `Created index ... in N s` por índice, depois
  `Gallery indexes ready`. `/health` informa o progresso como `gallery_indexes` (`state`:
  `building`, `ready`, `deferred`, `failed` ou `stopped`; `done` de `total`).
- Parar o visualizador mantém os índices concluídos; a inicialização seguinte continua.
- Se uma varredura ou outro trabalho de biblioteca estiver em andamento, o visualizador atende sem os índices e
  registra um aviso. Reinicie-o quando o trabalho terminar, ou execute `python database.py`.
- Se `.facet_cache/library.lock` ao lado do banco de dados estiver inutilizável (permissões, montagem
  somente leitura), o visualizador não cria os índices. Corrija o caminho e reinicie.
- Com `--workers N`, um worker cria e os outros atendem.
- No Docker, o `start_period` de 30 s do healthcheck não precisa de alteração: `/health` responde durante a criação.

Em um SQLite anterior à 3.48.0 (a imagem de CPU inclui a 3.46.1), a detecção de panorâmicas não consegue ler
apenas a partir do novo índice; a sua velocidade ali não foi medida. Em um SQLite que não seja o 3.51,
fotos com carimbos de data/hora idênticos podem ser agrupadas de forma diferente na primeira passagem de burst após
a atualização (veja o CHANGELOG).

> **Aviso:** copie ou substitua o banco de dados somente depois de parar o visualizador. Enquanto ele roda,
> as alterações recentes ficam nos arquivos `-wal` e `-shm`, não apenas no `.db`; um encerramento limpo
> as mescla (também com `performance.wal_checkpoint_minutes: 0`). No Windows, o arquivo
> não pode ser substituído de forma alguma enquanto o visualizador o mantém aberto.

## Armazenamento e rotação do segredo

Um único segredo assina cada sessão de login (JWT) e cada link do porta-retratos digital. Ele fica em
`.facet_secret` ao lado da configuração (modo `0600`, ignorado pelo git), não em `scoring_config.json`.

Versões anteriores o salvavam como `share_secret` na configuração, e o valor distribuído era público.
Na inicialização, o Facet move um `share_secret` remanescente para o arquivo do segredo e remove a chave.
Um valor que o próprio Facet publicou é substituído, o que desconecta todo mundo uma vez.

| Onde | Como |
|------|------|
| Padrão | `.facet_secret` ao lado de `scoring_config.json`, modo `0600` |
| Contêiner / orquestrador | Variável de ambiente `FACET_JWT_SECRET` — lida primeiro, nunca gravada em disco |
| Rotação | `python database.py --rotate-secret` e depois reinicie o viewer |

- **Docker:** `/app` é a camada gravável do contêiner, então um segredo criado ali se perde
  quando o contêiner é recriado e todo mundo é desconectado a cada atualização de imagem. Defina `FACET_JWT_SECRET` no
  `docker-compose.yml`, ou monte o arquivo com `- ./.facet_secret:/app/.facet_secret`.
- **Faça a rotação** sempre que o segredo puder ter vazado (uma configuração commitada, um backup vazado, um
  administrador que sai). Todos entram de novo e os dispositivos de quiosque buscam novos links do porta-retratos.
- **Vários workers:** crie o segredo antes da primeira inicialização com `--workers > 1` (execute
  `python database.py --rotate-secret` uma vez, inicie uma vez com `--workers 1`, ou defina
  `FACET_JWT_SECRET`). Caso contrário, cada worker cria o seu e as sessões quebram até reiniciar.
- **Diretório de instalação somente leitura:** o servidor roda com um segredo em memória, então as sessões morrem
  a cada reinicialização. Defina `FACET_JWT_SECRET`.
- **Inclua-o no backup** do banco de dados; restaurar um banco sem ele desconecta todo mundo.

## Configuração multiusuário

Para dar a cada usuário um conjunto privado de diretórios de fotos, adicione uma seção `users` ao
`scoring_config.json`. Consulte [Configuração](CONFIGURATION.md#users).

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

Os caminhos dos diretórios devem corresponder aos caminhos das fotos no banco de dados. Com `viewer.path_mapping`,
use os caminhos **mapeados** (como aparecem no host do visualizador).

### Migrando avaliações existentes

Para mover as avaliações do modo de usuário único para um usuário:

```bash
python database.py --migrate-user-preferences --user alice
```

### Botão de varredura

Para permitir que o visualizador dispare varreduras (o superadmin no modo multiusuário; uma sessão de edição em uma
instalação de usuário único com `viewer.edition_password` não vazia), ative-o. A varredura roda na
máquina do visualizador e não requer GPU ([Sem placa de vídeo](INSTALLATION.md#sem-placa-de-vídeo)):

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

O banco de dados pode crescer para dezenas de gigabytes (~14 GB após mais de 20 mil fotos), e uma nova varredura
custa tempo de GPU. O [Litestream](https://litestream.io/) transmite as alterações continuamente para S3,
B2, GCS, SFTP ou outro disco, com restauração para um ponto no tempo com precisão de poucos segundos.

O Facet não inclui o Litestream. Instale-o no host que executa o Facet; ele roda ao lado,
sem alterações no Facet. O checkpoint periódico do WAL do Facet (a cada 30 min por padrão,
`performance.wal_checkpoint_minutes`; `0` o desativa, um encerramento limpo do visualizador ainda faz
checkpoint) mantém o WAL pequeno.

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

O `litestream.env` salva as credenciais da AWS / B2, fora do YAML.

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

Para um banco de dados de 14 GB com ~50 MB/dia de rotatividade de WAL durante a pontuação ativa:

- ~US$ 0,30/mês de armazenamento no S3 Standard
- ~US$ 0,05/mês para operações PUT

Negligenciável em comparação a uma nova varredura: ~50 GPU-horas em uma RTX de 16 GB.
