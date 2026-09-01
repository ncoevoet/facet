# Instalação

> 🌐 [English](../INSTALLATION.md) · [Français](../fr/INSTALLATION.md) · [Deutsch](../de/INSTALLATION.md) · [Italiano](../it/INSTALLATION.md) · [Español](../es/INSTALLATION.md) · **Português**

O Facet roda na sua própria máquina. Escolha a seção que combina com a sua configuração,
copie o bloco e pronto. A metade [Avançado](#avançado), no final, só é necessária quando
você precisar dela.

## Qual instalação é para mim?

| A sua situação | Vá para |
|----------------|-------|
| Windows, macOS ou Linux, e você só quer que funcione | [Instalar com Docker](#instalar-com-docker) |
| Linux ou macOS, e você prefere não usar containers | [Instalar sem Docker](#instalar-sem-docker) |
| Um NAS, ou um servidor que você quer acessar de outras máquinas | [Implantação](DEPLOYMENT.md) |

## Qual perfil combina com o meu hardware?

O Facet vem com quatro *perfis*. Um perfil é apenas um conjunto de modelos de IA
dimensionado para a sua máquina — você escolhe um durante a instalação e pode trocá-lo
depois.

| O seu hardware | Perfil | O que você ganha |
|---------------|---------|--------------|
| Sem placa de vídeo | `legacy` | Tudo funciona — pontuação, rostos, tags, seleção, a galeria — só que mais devagar. |
| Placa NVIDIA, 6–14 GB | `8gb` | Os mesmos modelos do `legacy`, executados na placa de vídeo em vez do processador. |
| Placa NVIDIA, 14–20 GB | `16gb` | A pontuação de fotos mais robusta, além de tags e legendas de IA escritas pela máquina. |
| Placa NVIDIA, 20 GB ou mais | `24gb` | Os modelos maiores, além de explicações escritas sobre a composição de uma foto. |
| Mac com Apple Silicon (M1–M4) | escolhido para você | O Facet usa os núcleos gráficos do Mac e dimensiona o perfil pela sua memória. |

Não sabe quanta memória a sua placa tem? Pule esta parte — o bloco *Detectar
automaticamente* abaixo descobre isso por você.

## Instalar com Docker

Você precisa do [Docker](https://docs.docker.com/get-started/get-docker/). Se a sua
máquina tiver uma placa NVIDIA, você também precisa do
[NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)
para que o Docker consiga acessá-la — no Windows, isso significa rodar o Facet dentro do
WSL2 ([guia passo a passo](DEPLOYMENT.md#windows-wsl2-com-uma-gpu-nvidia)).

Cada bloco abaixo parte do zero. Escolha **um**.

### Detectar meu hardware automaticamente

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
cp .env.example .env          # abra o .env e defina PHOTOS_DIR para a pasta das suas fotos
docker compose up -d
```

Abra <http://localhost:5000>.

### Sem placa de vídeo

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
cp .env.example .env          # abra o .env e defina PHOTOS_DIR para a pasta das suas fotos
docker compose -f docker-compose.yml -f docker-compose.legacy.yml up -d
```

Abra <http://localhost:5000>.

### Placa de vídeo de 8 GB

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
cp .env.example .env          # abra o .env e defina PHOTOS_DIR para a pasta das suas fotos
docker compose -f docker-compose.yml -f docker-compose.8gb.yml up -d
```

Abra <http://localhost:5000>.

### Placa de vídeo de 16 GB

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
cp .env.example .env          # abra o .env e defina PHOTOS_DIR para a pasta das suas fotos
docker compose -f docker-compose.yml -f docker-compose.16gb.yml up -d
```

Abra <http://localhost:5000>.

### Placa de vídeo de 24 GB

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
cp .env.example .env          # abra o .env e defina PHOTOS_DIR para a pasta das suas fotos
docker compose -f docker-compose.yml -f docker-compose.24gb.yml up -d
```

Abra <http://localhost:5000>.

### Placa NVIDIA mais antiga (Maxwell, Pascal, Volta)

Os blocos de 8 GB, 16 GB e 24 GB acima, e o overlay genérico
`docker-compose.gpu.yml`, todos baixam `ghcr.io/ncoevoet/facet:latest-cuda`, cuja
build do PyTorch cobre `sm_75`-`sm_120` — de Turing a Blackwell. Uma placa
Maxwell, Pascal (série GTX 900/10) ou Volta (por exemplo, uma Titan V) precisa
da outra imagem CUDA: edite a linha `image:` no arquivo compose que você usou
acima (`docker-compose.8gb.yml`, `.16gb.yml`, `.24gb.yml` ou `.gpu.yml`),
trocando `ghcr.io/ncoevoet/facet:latest-cuda` por
`ghcr.io/ncoevoet/facet:latest-cuda-legacy` (`sm_50`-`sm_90`, de Maxwell a Hopper)
antes de executar `docker compose up -d`. Não confunda essa tag de imagem com
`docker-compose.legacy.yml`: esse arquivo seleciona o **perfil de VRAM**
`legacy` (somente CPU) e não tem relação com a tag de **arquitetura**
`-cuda-legacy` acima. Uma placa mais antiga que Maxwell (Kepler, Fermi —
`sm_50` é o piso da própria imagem legacy) não tem imagem CUDA compatível;
use em vez disso o perfil de VRAM `legacy` na CPU — o bloco
["Sem placa de vídeo"](#sem-placa-de-vídeo) acima.

### Comandos do dia a dia

A galeria fica vazia até você pontuar suas fotos. Dentro do Docker, a sua pasta de fotos
sempre se chama `/data/photos`, seja qual for o nome dela na sua máquina:

```bash
docker compose exec facet python facet.py /data/photos   # pontue suas fotos
docker compose logs -f                                   # acompanhe o que está acontecendo
docker compose down                                      # pare o serviço
```

Para iniciar de novo mais tarde, execute novamente a mesma linha `docker compose … up -d`
que você usou acima.

## Instalar sem Docker

### Linux

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
bash install.sh
```

O `install.sh` encontra a sua placa de vídeo, instala tudo o que combina com ela e
compila a galeria web. Depois, toda vez que você usar o Facet:

```bash
source venv/bin/activate
python facet.py /path/to/your/photos   # pontue suas fotos
python viewer.py                       # inicie a galeria
```

Abra <http://localhost:5000>.

### macOS

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
bash install.sh
```

Em um Mac com Apple Silicon, isso usa os núcleos gráficos do Mac automaticamente. Depois,
toda vez que você usar o Facet:

```bash
source venv/bin/activate
python facet.py /path/to/your/photos   # pontue suas fotos
python viewer.py                       # inicie a galeria
```

Abra <http://localhost:5000>.

> **A porta 5000 já está em uso?** O macOS a usa para o AirPlay. Inicie a galeria com
> `python viewer.py --port 5001` e abra <http://localhost:5001> em vez disso.

### Windows

Use o [Docker](#instalar-com-docker). Para usar uma placa NVIDIA no Windows, siga o
[guia do WSL2](DEPLOYMENT.md#windows-wsl2-com-uma-gpu-nvidia) — esse é o caminho testado.

## Primeira execução: o que esperar

- **Um download.** A primeira varredura baixa os modelos de IA do seu perfil — cerca de
  4,7 GB para `legacy`, 6,9 GB para `8gb`, 14,6 GB para `16gb`, 19,1 GB para `24gb`
  (detalhamento completo em [Tamanhos de download](#tamanhos-de-download)). Isso
  acontece uma vez; as próximas execuções começam na hora.
- **Sem configuração.** Não há nada para configurar. O Facet cria o seu banco de dados na
  primeira varredura e já vem com configurações que funcionam.
- **Suas fotos não são modificadas.** A varredura apenas as lê; os resultados vão para o
  banco de dados do próprio Facet. Gravar notas e palavras-chave de volta nos seus
  arquivos é uma ação separada, disparada por você ([Interop](INTEROP.md)).
- **Tempo.** Uma primeira varredura de uma biblioteca grande demora, e é bem mais lenta
  em um processador do que em uma placa de vídeo. O progresso é exibido conforme avança,
  e você pode navegar pela galeria enquanto ela trabalha.

## Verificar se funcionou

```bash
python facet.py --doctor                             # sem Docker
docker compose exec facet python facet.py --doctor   # com Docker
```

Isso mostra o que o Facet encontrou: a sua placa de vídeo, o perfil escolhido e o que
estiver faltando. Se a galeria estiver rodando, <http://localhost:5000/health> responde
`ok`.

Algo não está funcionando? Veja
[Solução de Conflitos de Dependência](#solução-de-conflitos-de-dependência) e
[Problemas de detecção de GPU](#problemas-de-detecção-de-gpu) abaixo.

---

# Avançado

Tudo a partir daqui é opcional: o que a instalação realmente faz, como alterá-la e a
referência completa de dependências.

- [Configurações do Docker que você pode alterar](#configurações-do-docker-que-você-pode-alterar)
- [Escolhendo o perfil você mesmo](#escolhendo-o-perfil-você-mesmo)
- [Instalação manual, sem o install.sh](#instalação-manual-sem-o-installsh)
- [Opções do install.sh e atalhos do Makefile](#opções-do-installsh-e-atalhos-do-makefile)
- [exiftool](#exiftool)
- [ONNX Runtime para detecção de faces](#onnx-runtime-para-detecção-de-faces)
- [Agrupamento de faces por GPU com RAPIDS cuML](#agrupamento-de-faces-por-gpu-com-rapids-cuml)
- [Apple Silicon (Metal/MPS)](#apple-silicon-metalmps)
- [Tamanhos de download](#tamanhos-de-download)
- [Dependências](#dependências)
- [Requisitos por recurso](#requisitos-por-recurso)
- [Solução de Conflitos de Dependência](#solução-de-conflitos-de-dependência)
- [Cliente Angular](#cliente-angular)

## Configurações do Docker que você pode alterar

Os ajustes de implantação ficam em `.env` (copie o `.env.example`):

| Chave | Padrão | Finalidade |
|-----|---------|---------|
| `PHOTOS_DIR` | `./photos` | Pasta do host montada com leitura e escrita em `/data/photos` (gravável para que os sidecars XMP possam ser escritos ao lado dos originais) |
| `PORT` | `5000` | Porta do host para a galeria |
| `FACET_VRAM_PROFILE` | `auto` | `auto`, `legacy`, `8gb`, `16gb`, `24gb` — substitui `models.vram_profile` sem editar nenhum JSON |
| `DB_PATH` | `/app/data/photo_scores_pro.db` | Caminho do banco de dados dentro do container, mantido no bind mount `./data` |
| `FACET_RETRAIN_THRESHOLD` / `FACET_RETRAIN_IDLE_S` | `auto_retrain` da configuração | Gatilho de retreinamento do ranqueador pessoal, para quem avalia muitas fotos |

Uma versão sanitizada de `scoring_config.default.json` já vem embutida na imagem como a
configuração inicial. O `docker-entrypoint.sh` a copia, apenas na primeira execução,
para o arquivo persistente `./facet-config/scoring_config.json`, que o `docker-compose.yml`
já monta (como `FACET_CONFIG=/config/scoring_config.json` dentro do container) — assim o
container roda sem nenhuma configuração no host, e toda escrita de configuração em tempo
de execução (a migração da senha do visualizador, pesos, prioridades, contextos de
pontuação) agora sobrevive a um `docker compose down && up`. Edite
`./facet-config/scoring_config.json` diretamente para personalizar pesos, a senha do
visualizador ou categorias à mão; um arquivo já existente nunca é sobrescrito.

> **Está atualizando de uma versão anterior a esta mudança?** As versões anteriores
> mandavam fazer `cp scoring_config.default.json scoring_config.json` e descomentar uma
> linha `- ./scoring_config.json:/app/scoring_config.json` no `docker-compose.yml`. Esse
> mount saiu do arquivo compose distribuído. Se você adotar o novo, **mova antes a sua
> configuração existente**:
>
> ```bash
> mkdir -p facet-config && cp scoring_config.json facet-config/scoring_config.json
> ```
>
> Caso contrário o entrypoint cria uma configuração padrão nova e seus pesos, suas
> categorias e **sua senha do visualizador deixam de ser lidos** — e um
> `viewer.edition_password` vazio desativa por completo o controle de edição. Se você
> mantiver seu próprio `docker-compose.yml` com o mount antigo, o entrypoint inicializa
> `./facet-config` a partir *desse* arquivo e nada se perde.

Os caches de modelos ficam em volumes nomeados gerenciados pelo Docker (`facet-hf-cache`,
`facet-torch-cache`, `facet-insightface`, `facet-pretrained`), então a imagem nunca lê os
caches da sua própria máquina, e os modelos sobrevivem a reinicializações.
`docker compose down -v` os apaga e força um novo download.

A imagem inclui o `exiftool`, mas **não** o darktable, então o download opcional de perfil
RAW/darktable do visualizador fica inerte a menos que você estenda a imagem com um binário
`darktable-cli`. Tudo o mais funciona normalmente.

## Escolhendo o perfil você mesmo

Os arquivos por perfil (`docker-compose.legacy.yml`, `docker-compose.8gb.yml`,
`docker-compose.16gb.yml`, `docker-compose.24gb.yml`) definem cada um o
`FACET_VRAM_PROFILE` e, para os perfis de GPU, reservam o dispositivo NVIDIA. O
`docker-compose.gpu.yml` é a alternativa genérica: ele reserva a GPU, mas deixa o perfil
por conta do próprio `vram_profile` da configuração (padrão `auto`).

Três imagens são publicadas a partir de um único `Dockerfile`:
`ghcr.io/ncoevoet/facet:latest` é uma build enxuta somente CPU (3,34 GB
descompactados em disco; veja [Tamanhos de download](#tamanhos-de-download)).
`ghcr.io/ncoevoet/facet:latest-cuda` traz CUDA 12.8, RAPIDS cuML e a build do
PyTorch `sm_75`-`sm_120` — de Turing a Blackwell, incluindo a série RTX 50
(13,1 GB descompactados) — e é o que os arquivos compose `8gb`/`16gb`/`24gb`
baixam por padrão. `ghcr.io/ncoevoet/facet:latest-cuda-legacy` traz CUDA 12.6 e a
build do PyTorch `sm_50`-`sm_90` — de Maxwell, Pascal (série GTX 900/10) e Volta a
Hopper (13,8 GB descompactados) — para placas que `latest-cuda` não cobre mais;
veja [Placa NVIDIA mais antiga](#placa-nvidia-mais-antiga-maxwell-pascal-volta)
acima. As três são apenas `linux/amd64` — em uma máquina ARM, compile localmente
com `docker compose build` em vez de baixar. O `docker compose build`
(ou `up --build`) sempre compila a partir deste repositório; veja os build args
`BASE_IMAGE`, `STRIP_TORCH`, `INSTALL_CUML` e `REQUIREMENTS_LOCK` no `Dockerfile`.

Sem o Docker, a mesma escolha é uma variável de ambiente ou uma chave de configuração:

```bash
FACET_VRAM_PROFILE=8gb python facet.py /path/to/photos
```

Os limites exatos que o `auto` aplica estão em
[Configuração › Detecção automática de VRAM](CONFIGURATION.md#detecção-automática-de-vram).

## Instalação manual, sem o install.sh

Requer Python 3.12 (3.10+ funciona) e Node.js 20+ para compilar a galeria.

```bash
# 1. Crie e ative um ambiente virtual
python3 -m venv venv
source venv/bin/activate

# 2. Instale o PyTorch primeiro, com a index URL correspondente à sua versão de CUDA.
#    cu128 é para CUDA 12.8+/13.x; use cu126 para CUDA 12.6-12.7, cu124 para CUDA
#    12.4-12.5, ou cu118 para CUDA 11.8-12.3.
#    Na dúvida, copie o comando de https://pytorch.org/get-started/locally/
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128

# 3. Instale o restante de uma vez, para que o pip resolva todo o grafo de uma só vez.
#    O requirements.txt já inclui transformers e accelerate, necessários para os
#    modelos SigLIP/BiRefNet/VLM usados pelos perfis 8gb+.
pip install -r requirements.txt

# 4. Instale UM ONNX Runtime para detecção de faces (veja a tabela abaixo)
pip install onnxruntime-gpu>=1.17.0   # ou: pip install onnxruntime>=1.15.0

# 5. Compile a galeria web
cd client && npm install && npx ng build && cd ..

# 6. Execute
python facet.py /path/to/photos
python viewer.py
```

Verifique o ambiente em uma linha:

```bash
python -c "import torch, cv2, fastapi, insightface, open_clip, pyiqa, numpy, scipy, sklearn, PIL, imagehash, rawpy, tqdm, exifread; print('All imports successful')"
```

Encontrando erros? Veja
[Solução de Conflitos de Dependência](#solução-de-conflitos-de-dependência).

## Opções do install.sh e atalhos do Makefile

O `install.sh` localiza um Python 3.10+, cria o `venv`, detecta o sistema operacional e a
GPU (Apple Silicon → Metal, senão `nvidia-smi` → build de CUDA correspondente), instala o
PyTorch, o ONNX Runtime certo, o `requirements.txt`, o `transformers` e o `accelerate`,
verifica a presença do `exiftool`, compila o cliente Angular e verifica todas as
importações.

| Flag | Efeito |
|------|--------|
| `--cpu` | Força o PyTorch somente em CPU (sem CUDA) |
| `--cuda VERSION` | Substitui a versão de CUDA detectada (ex.: `--cuda 12.8`) |
| `--skip-client` | Pula a compilação do frontend Angular |
| `--no-uv` | Usa pip em vez de uv |

| Alvo do Make | Executa |
|-------------|------|
| `make install` / `make install-cpu` | `install.sh`, detecção automática ou somente CPU |
| `make client` | Recompila o frontend Angular |
| `make doctor` | `python facet.py --doctor` |
| `make run` | `python viewer.py` |
| `make up` / `make up-gpu` | `docker compose up`, CPU ou NVIDIA |
| `make test` / `make test-cov` | pytest, com ou sem cobertura |
| `make clean` | Remove `venv`, `client/dist`, `client/node_modules` |

## exiftool

O exiftool oferece a melhor extração de EXIF para todos os formatos. Sem ele, o Facet
recorre ao `exifread` (uma biblioteca Python que lida com todos os formatos RAW) e depois
ao PIL (apenas JPEG/TIFF/DNG).

| SO | Comando |
|----|---------|
| Ubuntu/Debian | `sudo apt install libimage-exiftool-perl` |
| macOS | `brew install exiftool` |
| Windows | Baixe em [exiftool.org](https://exiftool.org/) |

## ONNX Runtime para detecção de faces

A detecção de faces (InsightFace) roda sobre o ONNX Runtime, disponível em variantes de
CPU e GPU. Instale exatamente uma:

| Configuração | Comando |
|--------|---------|
| Somente CPU | `pip install onnxruntime>=1.15.0` |
| CUDA 12.x | `pip install onnxruntime-gpu>=1.17.0` |
| CUDA 11.8 | `pip install onnxruntime-gpu>=1.15.0,<1.18` |

Verifique a sua versão de CUDA com `nvidia-smi` — ela aparece no canto superior direito.
Para migrar uma instalação existente de CPU para GPU:

```bash
pip uninstall onnxruntime
pip install onnxruntime-gpu>=1.17.0
```

## Agrupamento de faces por GPU com RAPIDS cuML

Para grandes bancos de dados de faces (80 mil+ faces), o cuML acelera bastante o
agrupamento. É necessário um ambiente conda:

```bash
conda create -n facet python=3.12
conda activate facet
conda install -c rapidsai -c conda-forge -c nvidia cuml cuda-version=12.0
# ou: pip install --extra-index-url https://pypi.nvidia.com/ "cuml-cu12"
pip install -r requirements.txt
```

Quando o cuML está disponível, o agrupamento usa a GPU automaticamente
(`face_clustering.use_gpu` em `scoring_config.json`). A imagem Docker CUDA já vem com ele
embutido, então os perfis `8gb`/`16gb`/`24gb` em container agrupam na GPU sem nenhum passo
extra; o `legacy` sempre agrupa no processador.

## Apple Silicon (Metal/MPS)

Nenhum pacote de GPU separado é necessário. Instale com `bash install.sh` e depois
confirme que `python facet.py --doctor` reporta `Facet runtime device: mps`. Por padrão, o
Facet ativa o fallback para CPU do PyTorch para operadores não suportados. Para comparar:

```bash
FACET_DEVICE=cpu python facet.py /path/to/photos --pass embeddings --force
FACET_DEVICE=mps python facet.py /path/to/photos --pass embeddings --force
```

Defina `FACET_DEVICE=cpu` para desativar a aceleração, ou `FACET_DEVICE=mps` para
exigi-la (e falhar de forma clara se ela não estiver disponível). O InsightFace permanece
no processador porque é um modelo do ONNX Runtime, não do PyTorch.

O Metal não tem memória de vídeo dedicada, então `vram_profile: "auto"` é dimensionado
pela memória unificada total:

| Memória unificada total | Perfil escolhido pelo `auto` |
|----------------------|----------------------------|
| menos de 16 GB | `legacy` |
| 16-31 GB | `8gb` |
| 32-47 GB | `16gb` |
| 48 GB ou mais | `24gb` |

Cada limite pede aproximadamente o dobro da pegada de memória dos modelos do perfil,
porque a memória unificada é compartilhada com o macOS, o servidor de janelas e todos os
outros aplicativos em execução — um Mac que recorre ao swap é mais lento do que um em um
perfil menor. Um perfil configurado explicitamente é sempre respeitado como está, então
defina um para substituir esses limites em qualquer direção.

## Tamanhos de download

Os modelos são baixados no primeiro uso para `~/.cache/huggingface/` (modelos Hugging
Face), `~/.cache/torch/hub/` (pesos do PyIQA) e `~/.insightface/` (detecção/reconhecimento
facial), ou os volumes nomeados do Docker. `samp_net.pth`, `u2netp.pth`,
`face_landmarker.task` e o `aesthetic_predictor_weights.pth` da cabeça estética CLIP-MLP
(somente `legacy`/`8gb`) vão todos para `pretrained_models/`, resolvido em relação à raiz
do repositório, e não ao diretório de trabalho do processo — no Docker isso é o volume
montado `facet-pretrained`, então nenhum deles é baixado novamente ao recriar o contêiner.
Nenhum peso de modelo vem embutido na imagem.

Os tamanhos abaixo são decimais (GB = 10⁹ bytes, MB = 10⁶ bytes), medidos a partir dos
caches de modelos locais e da API do Hugging Face.

| Modelo | Tamanho | Perfis |
|-------|------|----------|
| CLIP ViT-L-14 laion2b (embeddings + marcação CLIP + estética CLIP-MLP) | 1,711 GB | `legacy`/`8gb` |
| Cabeça estética MLP (`sac+logos+ava1-l14-linearMSE.pth`) | 3,7 MB | somente `legacy`/`8gb` |
| SigLIP 2 NaFlex SO400M (embeddings) | 4,581 GB | `16gb`/`24gb` |
| Qwen3.5-2B (marcação por VLM) | 4,571 GB | `16gb` |
| Qwen3.5-4B (marcação por VLM) | 9,343 GB | `24gb` |
| Qwen2-VL-2B (composição) | 4,430 GB | nenhum por padrão — somente se você definir manualmente `composition_model: "qwen2-vl-2b"` **e** `processing.mode: "single-pass"` |
| InsightFace buffalo_l (rostos) | 289 MB baixados / 630 MB em disco (o zip é mantido ao lado dos arquivos `.onnx` extraídos) | todos |
| Pesos do SAMP-Net (composição) | 183 MB | todos |
| U2-Net-P (submodelo de saliência do SAMP-Net) | 4,7 MB | mesmos perfis do SAMP-Net |
| BiRefNet_dynamic (saliência do sujeito) | 445 MB | todos |
| TOPIQ NR (modelo estético) | 181 MB | `16gb`/`24gb` |
| TOPIQ IAA (estética complementar) | 873 MB | todos |
| TOPIQ NR-Face (qualidade facial complementar) | 376 MB | todos |
| LIQE (qualidade/distorção complementar) | 708 MB | todos |
| timm resnet50.a1_in1k (backbone PyIQA compartilhado) | 102 MB | todos |
| Q-ReAlign-Mini-0.8B (`iqa_extended.qrealign`) | 2,235 GB | `8gb`/`16gb`/`24gb`, **ativado por padrão** (`"auto"` resulta em ativado em todos os perfis exceto `legacy`) |

Totais por perfil (download): `legacy` 4,69 GB · `8gb` 6,93 GB · `16gb` 14,55 GB ·
`24gb` 19,32 GB · `24gb` com `composition_model: "qwen2-vl-2b"` e
`processing.mode: "single-pass"` 23,56 GB (a substituição manual troca SAMP-Net/U2-Net-P
em vez de somar-se a eles).

Como referência, a própria imagem Docker (antes de qualquer download de modelo)
pesa, descompactada, 3,34 GB em `latest`, 13,1 GB em `latest-cuda` e 13,8 GB em
`latest-cuda-legacy` — veja [Deployment › Tamanho da imagem](DEPLOYMENT.md#tamanho-da-imagem)
para saber como esses números foram medidos. As três imagens mudaram de base
nesta versão (issue #119); os tamanhos de download comprimidos correspondentes
serão adicionados assim que essas bases forem publicadas e houver um manifesto
para medi-los.

Modelos opcionais não contabilizados nos totais acima:

| Modelo | Tamanho | Gatilho |
|-------|------|----------|
| DeQA-Score-Mix3 (`iqa_extended.deqa`) | 16,41 GB | desativado por padrão |
| Backbone SigLIP so400m-patch14-384 (`iqa_extended.aesthetic_v25`) | 3,515 GB | desativado por padrão, **descontinuado** (AGPL-3.0, sem manutenção upstream — prefira `qrealign`) |
| Helsinki-NLP OPUS-MT, por idioma de destino (tradução de legendas) | en→fr 303 MB · en→de 298 MB · en→es 312 MB · en→it 343 MB · en→pt 465 MB | somente para os idiomas ativados |
| MediaPipe `face_landmarker.task` | 3,76 MB | somente quando `mediapipe` está instalado |

`reverse_geocoder` não precisa de download algum — seus dados vêm embutidos no wheel.

Os pesos do SAMP-Net vêm do
[release model-weights-v1](https://github.com/ncoevoet/facet/releases/download/model-weights-v1/samp_net.pth)
do projeto. Se esse download falhar (offline ou rede restrita), você verá
`Failed to download SAMP-Net weights: HTTP Error 404: Not Found` — baixe o arquivo
manualmente e coloque-o em `pretrained_models/samp_net.pth`.

## Dependências

### Pacotes obrigatórios

| Pacote | Finalidade |
|---------|---------|
| `torch`, `torchvision` | Framework de deep learning (instalado separadamente, veja acima) |
| `open-clip-torch` | Embeddings/tagueamento CLIP (perfis legacy/8gb) |
| `pyiqa` | TOPIQ e outros modelos de qualidade/estética |
| `opencv-python` | Processamento de imagens |
| `pillow` | Carregamento de imagens |
| `imagehash` | Hashing perceptual para detecção de rajadas |
| `rawpy` | Suporte a arquivos RAW |
| `fastapi`, `uvicorn` | Servidor de API |
| `pyjwt` | Autenticação JWT |
| `numpy` | Operações numéricas |
| `tqdm` | Barras de progresso |
| `exifread` | Extração de metadados EXIF |
| `insightface` | Detecção e reconhecimento de faces |
| `transformers`, `accelerate` | Modelos SigLIP/BiRefNet/VLM (perfis 8gb+) |
| `scipy` | Computação científica |
| `hdbscan` | Agrupamento de faces (puxa o scikit-learn) |
| `reverse_geocoder` | Geocodificação reversa para GPS |
| `psutil` | Auto-ajuste do processamento em lote (monitoramento do sistema) |
| `aiosqlite` | SQLite assíncrono para os endpoints de leitura do FastAPI |
| `sqlite-vec` | KNN em disco para busca semântica e similaridade (recorre ao cache NumPy em memória se ausente) |

Todos esses estão em `requirements.txt`; nenhum perfil precisa de pacotes base adicionais.

### Pacotes opcionais

Cada um desbloqueia um recurso; sem ele, o recurso é pulado ou um fallback é usado.

| Pacote | Desbloqueia / finalidade | Sem ele |
|---------|-------------------|-----------|
| `watchdog` | Modo de observação (daemon `--watch` reescaneia novos arquivos) — **não está em `requirements.txt`**; só é puxado via `pip install .[watch]`, então usuários diretos de `requirements.txt` não obtêm o `--watch` | `--watch` indisponível |
| `pillow-heif` | Decodificação HEIF/HEIC | Arquivos HEIF/HEIC pulados |
| `rawpy` | Decodificação RAW (CR2/CR3/NEF/ARW/…) | Arquivos RAW pulados (já está no `requirements.txt` base) |
| `cuml`, `cupy` | Agrupamento de faces acelerado por GPU (conda + CUDA) | O agrupamento roda em CPU via `hdbscan` (padrão) |
| `onnxruntime-gpu` | Detecção de faces acelerada por GPU | `onnxruntime` em CPU (mais lento) |
| `aesthetic-predictor-v2-5` | Camada de IQA estendida — pontuador `aesthetic_v25` (`pip install -e .[iqa-extended]`; `iqa_extended.aesthetic_v25` em `scoring_config.json`, desativada por padrão). **Descontinuado** — AGPL-3.0, sem manutenção desde 2024-12-18; prefira `qrealign`, que não precisa de nenhum pacote extra (vem com a dependência base `pyiqa`) | `aesthetic_v25` indisponível |
| `darktable-cli` (sistema) | Exportação de perfil RAW/darktable a partir do visualizador | Apenas download original/embutido oferecido |
| `exiftool` (sistema) | Melhor extração de EXIF/GPS | Recorre ao `exifread`, depois ao PIL |

## Requisitos por recurso

A maior parte do Facet roda em qualquer lugar (CPU, qualquer perfil). Alguns recursos precisam de uma GPU, de um **perfil de VRAM** mais alto, de um pacote opcional, ou da **senha de edição** / função de **superadmin** do visualizador. Tags usadas ao longo da documentação:
`[GPU]` · `[16gb/24gb]` (perfil de VRAM) · `[Edition]` · `[Superadmin]` · `[Optional: pkg]`.

| Recurso | GPU | Perfil | Autenticação | Pacote opcional |
|---------|:---:|---------|:----:|------------------|
| Pontuação / escaneamento (base) | opcional | qualquer (`legacy` = CPU) | — | — |
| Estética TOPIQ | sim | `16gb`/`24gb` | — | — |
| IQA suplementar (TOPIQ IAA, NR-Face, LIQE) | opcional | qualquer (`legacy` = CPU) | — | — |
| Embeddings SigLIP 2 | sim | `16gb`/`24gb` | — | — |
| Marcação por VLM (Qwen3.5) | sim | `16gb`/`24gb` | — | — |
| Padrão de composição (SAMP-Net) | opcional | qualquer (`legacy` = CPU) | — | — |
| Composição (Qwen2-VL) | sim | `24gb` | — | — |
| Saliência do sujeito (BiRefNet) | opcional | qualquer (`legacy` = CPU) | — | — |
| Legendas por IA (gerar / visualizar) | sim | `16gb`/`24gb` | — | — |
| Legendas por IA (editar) | sim | `16gb`/`24gb` | edition | — |
| Crítica VLM | sim | `16gb`/`24gb` | — | — |
| Detecção / extração de faces (InsightFace) | recomendado (funciona em CPU, mais lento) | qualquer | — | — |
| Agrupamento de faces (HDBSCAN) | não (CPU) | qualquer | — | `cuml`/`cupy` (aceleração opcional por GPU) |
| Busca semântica | não | qualquer | — | `sqlite-vec` (recorre ao NumPy) |
| Decodificação RAW / HEIF | não | qualquer | — | `rawpy` / `pillow-heif` |
| Modo de observação (`--watch`) | não | qualquer | — | `watchdog` |
| Extração de GPS / exportação darktable | não | qualquer | — | `exiftool` / `darktable-cli` |
| Avaliações, favoritos, edições de face e pessoa, seleção (culling) | não | qualquer | edition | — |
| Disparar escaneamentos a partir da interface web | não | qualquer | superadmin | — |
| Multiusuário (avaliações e funções por usuário) | não | qualquer | baseada em função | — |

> O *agrupamento* de faces roda em CPU por padrão (`hdbscan` autônomo); `cuml`/`cupy`
> apenas adicionam aceleração opcional por GPU — eles **não** são obrigatórios. A senha de
> edição e as funções de usuário são configuradas em `scoring_config.json` — veja
> [Configuração](CONFIGURATION.md) para autenticação.

> Sem GPU local? Aponte a marcação por VLM, as legendas e a crítica para um servidor
> Ollama remoto ou compatível com OpenAI usando `vlm_backend` em `scoring_config.json` —
> esses recursos passam a funcionar também nos perfis de CPU `legacy`/`8gb`.

## Solução de Conflitos de Dependência

O Facet tem muitas dependências de ML (`torch`, `open-clip-torch`, `insightface`, etc.) que puxam suas próprias dependências transitivas. O pip resolve dependências sequencialmente, o que pode levar a erros em cascata, nos quais a instalação de um pacote quebra outro.

**Sintomas:** instalar pacotes um a um dispara erros pedindo mais um pacote; conflitos de
versão entre `torch`, `numpy`, `huggingface-hub` ou `open-clip-torch`; o `pip install` é
bem-sucedido, mas o `import` falha em tempo de execução.

**1. Instale tudo de uma vez** — `pip install -r requirements.txt` dá ao pip o grafo completo de dependências para resolver. Não instale pacotes individualmente (`pip install open-clip-torch && pip install insightface && ...`); isso impede que o pip resolva o grafo completo.

**2. Use o [uv](https://docs.astral.sh/uv/) em vez do pip** — o `uv` resolve o grafo completo de dependências antecipadamente, antes de instalar qualquer coisa, evitando conflitos em cascata:

```bash
pip install uv
uv pip install -r requirements.txt
# Com o índice de CUDA para o PyTorch:
uv pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cu128
```

**3. Comece do zero** — se o seu ambiente já está quebrado, execute `deactivate`,
`rm -rf venv`, e refaça a [instalação manual](#instalação-manual-sem-o-installsh) (ou apenas reexecute o `install.sh`).

### Problemas de detecção de GPU

Se a sua GPU não for detectada (comum em placas mais novas), execute o diagnóstico:

```bash
python facet.py --doctor
```

Isso verifica o suporte a CUDA do PyTorch e a compatibilidade do driver, e sugere o
comando pip correto. Também detecta um caso que o `torch.cuda.is_available()` não
consegue: uma GPU que o driver enxerga, mas para a qual a build do PyTorch instalada
não traz kernels — a série RTX 50 (Blackwell, `sm_120`) em uma build anterior à CUDA
12.8 era exatamente esse caso. O Facet compara a compute capability do dispositivo
com a lista de arquiteturas da build e executa um kernel de teste antes de definir
um perfil de VRAM; em caso de incompatibilidade, ele recorre à CPU em vez de travar
na primeira operação real, e o `--doctor` indica a incompatibilidade e a correção —
a tag de imagem correspondente no Docker (`ghcr.io/ncoevoet/facet:latest-cuda-legacy`
para placas Maxwell/Pascal/Volta), ou a `--index-url` correta em uma instalação
nativa.

Você também pode simular hardware para testes:

```bash
python facet.py --doctor --simulate-gpu "RTX 5070 Ti" --simulate-vram 16
```

## Cliente Angular

Necessário apenas para desenvolvimento ou builds personalizados — o `install.sh` e a
imagem Docker já o compilam.

```bash
cd client
npm install
npm run build    # Build de produção → client/dist/
npm start        # Servidor de desenvolvimento em http://localhost:4200 (encaminha a API para :5000)
```

> **Avisos do `npm audit`:** o Angular puxa uma árvore profunda de dependências
> transitivas e o `npm audit` reportará achados, a maioria dos quais está em
> dependências de desenvolvimento de tempo de compilação que nunca chegam ao
> navegador. Revise a lista antes de executar `npm audit fix` — ele pode
> silenciosamente rebaixar ou remover pacotes.
