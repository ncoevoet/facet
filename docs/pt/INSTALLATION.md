# Instalação

> 🌐 [English](../INSTALLATION.md) · [Français](../fr/INSTALLATION.md) · [Deutsch](../de/INSTALLATION.md) · [Italiano](../it/INSTALLATION.md) · [Español](../es/INSTALLATION.md) · **Português** · [简体中文](../zh/INSTALLATION.md)

O Facet roda na sua própria máquina. Escolha a seção que combina com a sua configuração e
copie o bloco. A parte [Avançado](#avançado) só é necessária quando você precisar dela.

## Qual instalação é para mim?

Os dois caminhos executam o mesmo Facet; eles trocam simplicidade de instalação por
desempenho. Escolha o que combina com você.

| | Docker | Sem Docker |
|---|---|---|
| Instalação | Um comando: tudo vem na imagem | `install.sh` (Linux, macOS) ou o instalador do Windows cria um ambiente Python na máquina |
| Atualização | Baixar a nova imagem | Atualizar o código e rodar `install.sh` de novo, ou instalar o novo instalador do Windows |
| Desempenho | Um container fica entre o Facet e seus arquivos e sua placa de vídeo; no Windows ele roda dentro do WSL2 | O Facet usa diretamente a placa de vídeo e os arquivos da máquina |

| A sua situação | Vá para |
|----------------|-------|
| Windows, macOS ou Linux, em um container | [Instalar com Docker](#instalar-com-docker) |
| Windows, macOS ou Linux, sem containers | [Instalar sem Docker](#instalar-sem-docker) |
| Um NAS, ou um servidor que você quer acessar de outras máquinas | [Implantação](DEPLOYMENT.md) |

## Qual perfil combina com o meu hardware?

Um *perfil* é um conjunto de modelos de IA dimensionado para a sua máquina. Você escolhe um na
instalação e pode trocá-lo depois.

| O seu hardware | Perfil | O que você ganha |
|---------------|---------|--------------|
| Sem placa de vídeo | `legacy` | Tudo funciona, só que mais devagar. |
| Placa NVIDIA, 6–14 GB | `8gb` | Os modelos do `legacy`, executados na placa de vídeo. |
| Placa NVIDIA, 14–20 GB | `16gb` | A pontuação mais robusta, além de tags e legendas de IA. |
| Placa NVIDIA, 20 GB ou mais | `24gb` | Os modelos maiores, além de explicações escritas sobre a composição. |
| Mac com Apple Silicon (M1–M4) | escolhido para você | Usa os núcleos gráficos do Mac; perfil dimensionado pela memória. |

Não sabe quanta memória a sua placa tem? Use o bloco *Detectar automaticamente* abaixo.

## Instalar com Docker

Você precisa do [Docker](https://docs.docker.com/get-started/get-docker/). Com uma placa NVIDIA, você
também precisa do
[NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html).
No Windows, isso significa rodar o Facet dentro do WSL2
([guia passo a passo](DEPLOYMENT.md#windows-wsl2-com-uma-gpu-nvidia)).

Cada bloco parte do zero. Escolha **um**.

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

Os blocos de GPU acima e o `docker-compose.gpu.yml` baixam `ghcr.io/ncoevoet/facet:latest-cuda`,
que cobre `sm_75`-`sm_120` (de Turing a Blackwell).

Para uma placa Maxwell, Pascal (série GTX 900/10) ou Volta (por exemplo, uma Titan V), edite a linha
`image:` do arquivo compose que você usou (`docker-compose.8gb.yml`, `.16gb.yml`, `.24gb.yml` ou
`.gpu.yml`) antes de executar `docker compose up -d`:

- de `ghcr.io/ncoevoet/facet:latest-cuda`
- para `ghcr.io/ncoevoet/facet:latest-cuda-legacy` (`sm_50`-`sm_90`, de Maxwell a Hopper)

Essa tag de imagem `-cuda-legacy` não tem relação com `docker-compose.legacy.yml`, que seleciona
o perfil `legacy` somente CPU. Placas mais antigas que Maxwell (Kepler, Fermi) não têm imagem
CUDA: use o bloco [Sem placa de vídeo](#sem-placa-de-vídeo).

### Comandos do dia a dia

A galeria fica vazia até você pontuar suas fotos. Dentro do Docker, a sua pasta de fotos é
sempre `/data/photos`:

```bash
docker compose exec facet python facet.py /data/photos   # pontue suas fotos
docker compose logs -f                                   # acompanhe o que está acontecendo
docker compose down                                      # pare o serviço
```

Para iniciar de novo, execute novamente a linha `docker compose … up -d` que você usou acima.

## Instalar sem Docker

### Linux

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
bash install.sh
```

O `install.sh` detecta a sua placa de vídeo, instala os pacotes correspondentes e compila a
galeria web. Depois, toda vez:

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

Em um Apple Silicon, isso usa os núcleos gráficos automaticamente. Depois, toda vez:

```bash
source venv/bin/activate
python facet.py /path/to/your/photos   # pontue suas fotos
python viewer.py                       # inicie a galeria
```

Abra <http://localhost:5000>.

> **A porta 5000 já está em uso?** O macOS a usa para o AirPlay. Execute
> `python viewer.py --port 5001` e abra <http://localhost:5001>.

### Windows

Um instalador por usuário (MSI) instala o Facet sem direitos de administrador:

| Pasta | Conteúdo |
|---|---|
| `%LOCALAPPDATA%\Facet\app` | o programa, substituído a cada atualização |
| `%LOCALAPPDATA%\Facet\venv` | o ambiente Python, criado quando o instalador termina |
| `%LOCALAPPDATA%\Facet\data` | o banco de dados (`photo_scores_pro.db`) e os logs |
| `%LOCALAPPDATA%\Facet\config` | `scoring_config.json` |

**Obter o instalador.** Nenhuma versão publicada o inclui ainda. Gere-o a partir de um clone
com `installer\build-msi.ps1` (precisa do WiX 3.14, do `uv` e do cliente compilado, e indica
onde obter o WiX), ou baixe o artefato `facet-msi` de uma execução do workflow *Windows install
(MSI)*. A compilação precisa do Node.js 22.22.3 ou mais recente para o cliente (22.14 falha em
`npm run build`).

**Primeira execução.** O instalador inicia a criação do ambiente Python assim que termina. O ambiente tem cerca de 6 GB, e o cache de download do uv
(`%LOCALAPPDATA%\uv\cache`) ocupa quase o mesmo. O item *Facet* do menu Iniciar executa a
configuração se ela nunca foi concluída, e de novo após uma atualização que mude as
dependências do Facet. Ele escolhe a versão do PyTorch para sua placa NVIDIA e o driver dela
como o `install.sh` faz, ou a versão para CPU sem placa NVIDIA. Se a versão para GPU instalada
não alcançar a placa, a instalação para e explica: atualize o driver, ou rode `Setup-Facet.ps1
-Force -Cpu`.

Se a galeria não consegue iniciar (porta em uso, falha na configuração, sem resposta após 90
s), a janela do item do menu Iniciar mostra o erro e espera por Enter. Após 90 s sem resposta,
a galeria continua em execução e ainda pode subir.

**No dia a dia:**

```powershell
cd "$env:LOCALAPPDATA\Facet\app\installer"
.\Scan-Facet.ps1 "\\NAS\Photos"   # pontuar fotos; argumentos extras vão para o facet.py
.\Start-Facet.ps1                # a galeria, em http://localhost:5000
.\Stop-Facet.ps1                 # parar a galeria e qualquer varredura
```

A galeria só responde neste computador. `Start-Facet.ps1 -Lan` a abre para outros
dispositivos e se recusa a iniciar enquanto `viewer.password` não estiver definido na
configuração.

**Uma só grafia por pasta.** O Facet guarda cada foto com o caminho pelo qual ela foi varrida:
`\\NAS\Photos` e o mesmo compartilhamento mapeado como `Z:\` são, para ele, duas pastas
diferentes, e varrer as duas adiciona cada foto duas vezes. Escolha uma e mantenha.

**Computadores gerenciados.** Os atalhos executam os scripts PowerShell não assinados do Facet com `-ExecutionPolicy Bypass`. Uma política de execução definida por Política de Grupo tem prioridade, então em um PC gerenciado os scripts podem não rodar; peça ao administrador para permiti-los.

**Desinstalar** (Configurações, Aplicativos) para o Facet e remove o programa, os atalhos, o
ambiente Python e o ExifTool (também sob um `FACET_HOME` próprio), e mantém `data` e `config`. O
que ele não conseguir apagar fica listado em `data\logs\uninstall.log`. O cache de download do uv
(`%LOCALAPPDATA%\uv\cache`) e os modelos baixados ficam (`.cache`, `.insightface` na sua pasta de
usuário). Uma atualização mantém uma pasta de instalação personalizada e só prepara o ambiente de
novo quando as dependências do Facet mudaram.

**Trazer uma biblioteca do Docker.** O banco de dados guarda o caminho completo de cada foto,
e a instalação do Windows vê as mesmas fotos em outro (`\\NAS\Photos\...` em vez de
`/data/photos/...`). Copie o banco para `data`, pare o Facet e reescreva os caminhos,
primeiro em simulação:

```powershell
cd "$env:LOCALAPPDATA\Facet\app"
..\venv\Scripts\python.exe scripts\rewrite_db_paths.py ..\data\photo_scores_pro.db /data/photos "\\NAS\Photos" --dry-run
..\venv\Scripts\python.exe scripts\rewrite_db_paths.py ..\data\photo_scores_pro.db /data/photos "\\NAS\Photos"
```

A ferramenta guarda uma cópia do banco (`photo_scores_pro.db.before-rewrite-<hora>`), se recusa
a mesclar uma foto já varrida no novo caminho e esvazia o índice vetorial, que
`..\venv\Scripts\python.exe database.py --db ..\data\photo_scores_pro.db --populate-vec`
reconstrói. O histórico de desfazer de antes da mudança deixa de valer. Estes comandos
pressupõem a pasta de instalação padrão. Um prefixo antigo e um novo em que um está dentro do
outro (por exemplo, `D:\Photos` para `D:\Photos\new`) são recusados; passe por um prefixo
temporário.

O Docker também funciona no Windows; para uma placa NVIDIA, siga o [guia do WSL2](DEPLOYMENT.md#windows-wsl2-com-uma-gpu-nvidia).

## Primeira execução: o que esperar

- **Um download.** A primeira varredura baixa os modelos do seu perfil: cerca de 4,7 GB para
  `legacy`, 6,9 GB para `8gb`, 14,6 GB para `16gb`, 19,3 GB para `24gb`
  ([Tamanhos de download](#tamanhos-de-download)). Isso acontece uma vez.
- **Sem configuração para varrer.** O Facet cria o seu banco de dados na primeira varredura.
- **Somente leitura até você definir uma senha.** Para editar (avaliar, selecionar, álbuns, pessoas), defina
  `viewer.edition_password` em `scoring_config.json` e reinicie o visualizador. Com o
  `docker-compose.yml` incluído, a imagem gera uma na primeira inicialização.
- **Suas fotos não são modificadas.** A varredura apenas as lê. Gravar notas e palavras-chave
  de volta nos arquivos é uma ação separada, que você ativa ([Interop](INTEROP.md)).
- **Tempo.** Uma primeira varredura de uma biblioteca grande demora, mais em um processador do que em uma
  placa de vídeo. Você pode navegar pela galeria enquanto ela trabalha.

## Verificar se funcionou

```bash
python facet.py --doctor                             # sem Docker
docker compose exec facet python facet.py --doctor   # com Docker
```

Isso mostra a sua placa de vídeo, o perfil escolhido e o que estiver faltando. Enquanto a galeria
roda, <http://localhost:5000/health> responde `ok`.

Algo não está funcionando? Veja [Solução de Conflitos de Dependência](#solução-de-conflitos-de-dependência)
e [Problemas de detecção de GPU](#problemas-de-detecção-de-gpu).

---

# Avançado

Opcional: o que a instalação faz, como alterá-la e a referência de dependências.

- [Configurações do Docker que você pode alterar](#configurações-do-docker-que-você-pode-alterar)
- [Escolhendo o perfil você mesmo](#escolhendo-o-perfil-você-mesmo)
- [Instalação manual, sem o install.sh](#instalação-manual-sem-o-installsh)
- [Opções do install.sh e atalhos do Makefile](#opções-do-installsh-e-atalhos-do-makefile)
- [exiftool](#exiftool)
- [ONNX Runtime para detecção de faces](#onnx-runtime-para-detecção-de-faces)
- [OpenCV na versão headless](#opencv-na-versão-headless)
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
| `PHOTOS_DIR` | `./photos` | Pasta do host montada com leitura e escrita em `/data/photos` (para que os sidecars XMP possam ser escritos) |
| `PORT` | `5000` | Porta do host para a galeria |
| `FACET_VRAM_PROFILE` | `auto` | `auto`, `legacy`, `8gb`, `16gb`, `24gb`; substitui `models.vram_profile` |
| `DB_PATH` | `/app/data/photo_scores_pro.db` | Caminho do banco de dados dentro do container, no bind mount `./data` |
| `FACET_RETRAIN_THRESHOLD` / `FACET_RETRAIN_IDLE_S` | `auto_retrain` da configuração | Gatilho de retreinamento do ranqueador pessoal, para quem avalia muitas fotos |

`scoring_config.json` é o seu **override**. Os valores distribuídos ficam em
`config/scoring_config.default.json` dentro da imagem. Seu arquivo contém apenas o que você
mudou; todo o resto mantém o valor distribuído e acompanha as atualizações. Veja
[Configuração](CONFIGURATION.md#padrões-e-seu-override) e
[a referência completa das chaves](CONFIGURATION.md).

Na primeira execução, o `docker-entrypoint.sh` cria `./facet-config/scoring_config.json`:

- O `docker-compose.yml` o monta como `FACET_CONFIG=/config/scoring_config.json`, então
  as alterações de configuração feitas no visualizador sobrevivem a `docker compose down && up`.
- Sob compose, ele contém uma `viewer.edition_password` gerada, impressa uma única vez em
  `docker compose logs facet`. Um simples `docker run` sem `FACET_CONFIG` cria um override
  vazio e nenhuma senha.
- Um arquivo existente nunca é sobrescrito, e seu dono e permissões são deixados como estão.

### Propriedade do arquivo no contêiner

O Facet só faz `chown` e `chmod` em um `scoring_config.json` que ele mesmo criou.

Uma exceção: se uma configuração existente não é **legível** pelo usuário `facet` do contêiner
(uid 1000), o entrypoint assume a posse dela e avisa isso no stderr. Uma configuração
ilegível o deixaria sem acesso à interface. Para manter a posse, torne-a legível em vez disso:
`chmod o+r facet-config/scoring_config.json`.

Em Podman/Docker rootless, seu arquivo pertence a um uid em que o usuário `facet` do contêiner
não pode se tornar. Torne-o **gravável pelo usuário do contêiner sem abrir mão da sua posse**:

```bash
# 100999 = o subuid do host para o qual o usuário facet dentro do contêiner (uid 1000) é mapeado;
# veja o seu em um arquivo já criado pelo contêiner: stat -c %u facet-config/.facet_secret
chown "$USER":100999 facet-config/scoring_config.json
chmod 664 facet-config/scoring_config.json
```

O arquivo continua seu e editável, e as gravações do Facet o mantêm assim. Alternativas:
`podman unshare chown` para editar um arquivo pertencente ao contêiner, ou `--userns=keep-id` (ou uma
diretiva `user:` no compose) para que o usuário do contêiner seja você.

> **Aviso — atualizando de um arquivo compose anterior.** As versões anteriores montavam
> `- ./scoring_config.json:/app/scoring_config.json`. O arquivo compose distribuído não
> faz mais isso. Se você adotar o novo, **mova antes a sua configuração**, ou seus pesos,
> categorias e senha do visualizador deixam de ser lidos:
>
> ```bash
> mkdir -p facet-config && cp scoring_config.json facet-config/scoring_config.json
> ```
>
> Se você mantiver seu próprio `docker-compose.yml` com o mount antigo, `./facet-config` é inicializado
> a partir desse arquivo e nada se perde.
>
> Uma configuração trazida de uma versão anterior é uma cópia completa dos antigos padrões. Ela continua
> funcionando, mas suas edições ficam difíceis de ver. Execute `python database.py --compact-config` (Docker:
> `docker compose exec facet python database.py --compact-config`) para reduzi-la ao
> que você mudou. Ele faz um backup em `0600` primeiro e se resolve na mesma configuração.

Os caches de modelos ficam em volumes nomeados (`facet-hf-cache`, `facet-torch-cache`,
`facet-insightface`, `facet-pretrained`) e sobrevivem a reinicializações. `docker compose down -v`
os apaga e força um novo download.

A imagem inclui o `exiftool`, mas **não** o darktable. O download de perfil RAW/darktable do
visualizador fica desativado a menos que você adicione um binário `darktable-cli` à imagem.

## Escolhendo o perfil você mesmo

- `docker-compose.legacy.yml`, `docker-compose.8gb.yml`, `docker-compose.16gb.yml`,
  `docker-compose.24gb.yml` definem cada um o `FACET_VRAM_PROFILE`; os de GPU também reservam o
  dispositivo NVIDIA.
- `docker-compose.gpu.yml` reserva a GPU e deixa o perfil por conta do `vram_profile` da
  configuração (padrão `auto`).

Três imagens são publicadas:

| Imagem | Conteúdo | Descompactada |
|-------|----------|----------|
| `ghcr.io/ncoevoet/facet:latest` | Build enxuta somente CPU | 3,34 GB |
| `ghcr.io/ncoevoet/facet:latest-cuda` | CUDA 12.8, RAPIDS cuML, PyTorch `sm_75`-`sm_120` (Turing–Blackwell, incluindo a série RTX 50); padrão para `8gb`/`16gb`/`24gb` | 13,1 GB |
| `ghcr.io/ncoevoet/facet:latest-cuda-legacy` | CUDA 12.6, PyTorch `sm_50`-`sm_90` (Maxwell, Pascal, Volta–Hopper); veja [Placa NVIDIA mais antiga](#placa-nvidia-mais-antiga-maxwell-pascal-volta) | 13,8 GB |

- As duas imagens CUDA trazem o `onnxruntime-gpu` (1.26.0, CUDA 12) no lugar do `onnxruntime`, então
  a detecção de faces roda na GPU. A imagem de CPU mantém o `onnxruntime`.
- As três são apenas `linux/amd64`. Em ARM, compile localmente com `docker compose build`.
- `docker compose build` (ou `up --build`) compila a partir deste repositório. Build args:
  `BASE_IMAGE`, `STRIP_TORCH`, `INSTALL_CUML`, `REQUIREMENTS_LOCK`, `ORT_GPU_VERSION`
  (veja o `Dockerfile`).

Sem o Docker, use a variável de ambiente ou a chave de configuração:

```bash
FACET_VRAM_PROFILE=8gb python facet.py /path/to/photos
```

Os limites que o `auto` usa estão em
[Configuração › Detecção automática de VRAM](CONFIGURATION.md#detecção-automática-de-vram).

## Instalação comercial e pacotes restritos

`insightface` e `pyiqa` (mais `openai-clip`, `facexlib` e `onnxruntime`, que só eles
usam) trazem pesos de modelos com termos não comerciais. Eles não fazem parte da instalação base. Ficam
nos extras `faces-insightface` e `iqa` e em `requirements.restricted.txt` (mais
`requirements.restricted.lock.txt` e `requirements.legacy.restricted.lock.txt` para o Docker).

> **Mudança incompatível.** `pip install -e .` e `pip install -r requirements.txt` sozinhos não
> incluem mais insightface nem pyiqa. Use `pip install -e .[all]` ou
> `pip install -r requirements.txt -r requirements.restricted.txt`. O `install.sh` e a
> imagem Docker padrão instalam ambos.

| Objetivo | Comando |
|----------|---------|
| Tudo (padrão) | `bash install.sh` ou `pip install -e .[all]` |
| Adequado ao uso comercial | `bash install.sh --commercial` |
| Comercial, manual | `pip install -r requirements.txt`, depois `pip install -e .[commercial]` e `pip install mediapipe==0.10.35 --no-deps` |
| Comercial, Docker | `docker build --build-arg FACET_LICENSING=commercial .` |

- `pip install -e .[all]` e o extra `faces-insightface` instalam o `onnxruntime` de CPU.
  Em uma máquina CUDA, complete com o comando de GPU de
  [ONNX Runtime para detecção de faces](#onnx-runtime-para-detecção-de-faces). O `bash install.sh`
  e as imagens CUDA já fazem isso.
- Instale sempre o `mediapipe` com `--no-deps`, ou o `opencv-contrib-python` dele instala em duplicidade
  o namespace `cv2`. O extra `commercial` declara as dependências de execução dele (`absl-py`,
  `flatbuffers`).
- O `python-ofiq` (os bindings OFIQ de qualidade facial) só tem wheels para Linux x86-64 e macOS arm64.
  Instale-o manualmente com `pip install python-ofiq` onde estiver disponível.

Instalar para uso comercial não muda o modo. Defina-o no seu override:
`{ "licensing": { "mode": "commercial" } }`. O argumento de build do Docker também define
`FACET_LICENSING_MODE=commercial`. `python facet.py --doctor` mostra o modo de licenciamento
ativo e, no modo comercial, os componentes que uma varredura carregaria (YuNet, SFace, Q-ReAlign).

## Instalação manual, sem o install.sh

Requer Python 3.12 (3.10+ funciona) e Node.js 20+ para compilar a galeria.

```bash
# 1. Crie e ative um ambiente virtual
python3 -m venv venv
source venv/bin/activate

# 2. Instale o PyTorch primeiro, conforme a sua versão de CUDA:
#    cu128 = CUDA 12.8+/13.x, cu126 = 12.6-12.7, cu124 = 12.4-12.5, cu118 = 11.8-12.3.
#    A sua PLACA também conta: Maxwell/Pascal/Volta (GTX 900/10, Titan V) precisam de cu126,
#    mesmo com um driver CUDA 12.8. Verifique: `nvidia-smi --query-gpu=compute_cap --format=csv`
#    Na dúvida, copie o comando de https://pytorch.org/get-started/locally/
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128

# 3. Instale o restante de uma vez para que o pip resolva todo o grafo
pip install -r requirements.txt -r requirements.restricted.txt

# 4. Somente CUDA, DEPOIS do passo 3: troque pelo ONNX Runtime de GPU (conforme o build CUDA do PyTorch)
pip uninstall -y onnxruntime onnxruntime-gpu
pip install "onnxruntime-gpu>=1.19.0,<1.27"   # PyTorch CUDA 12.x (cu124, cu126, cu128)
# Somente CPU, ou CUDA 11.8 (cu118): mantenha o que o passo 3 instalou, ou reinstale com
# pip install "onnxruntime>=1.15.0"

# 5. DEPOIS dos passos 3 e 4: mantenha só o build headless do OpenCV (o com interface exige libGL.so.1)
CV_VER=$(pip show opencv-python-headless opencv-python 2>/dev/null | awk '/^Version:/ {print $2; exit}')
pip uninstall -y opencv-python opencv-python-headless
pip install --no-deps "opencv-python-headless==$CV_VER"

# 6. Compile a galeria web
cd client && npm install && npx ng build && cd ..

# 7. Execute
python facet.py /path/to/photos
python viewer.py
```

A ordem dos passos importa: nos pacotes que compartilham arquivos (`onnxruntime`/`onnxruntime-gpu`,
`opencv-python`/`opencv-python-headless`) vence o último a ser instalado.
O `install.sh` aplica o piso da placa e as duas trocas automaticamente.

Verifique o ambiente:

```bash
python -c "import torch, cv2, fastapi, insightface, open_clip, pyiqa, numpy, scipy, sklearn, PIL, imagehash, rawpy, tqdm, exifread; print('All imports successful')"
```

Encontrando erros? Veja [Solução de Conflitos de Dependência](#solução-de-conflitos-de-dependência).

## Opções do install.sh e atalhos do Makefile

O `install.sh`:

1. localiza um Python 3.10+ e cria o `venv`;
2. detecta o SO e a GPU (Apple Silicon → Metal, senão `nvidia-smi` → build de CUDA correspondente);
3. instala o PyTorch, o `requirements.txt`, o `transformers` e o `accelerate`;
4. troca para o [ONNX Runtime](#onnx-runtime-para-detecção-de-faces) certo e para o
   [build headless do OpenCV](#opencv-na-versão-headless);
5. verifica a presença do `exiftool`, compila o cliente Angular e verifica todas as importações (status de saída 1 se alguma falhar).

| Flag | Efeito |
|------|--------|
| `--cpu` | Força o PyTorch somente em CPU (sem CUDA) |
| `--cuda VERSION` | Substitui a versão de CUDA detectada (ex.: `--cuda 12.8`) |
| `--skip-client` | Pula a compilação do frontend Angular |
| `--no-uv` | Usa pip em vez de uv |
| `--commercial` | Instalação adequada ao uso comercial: omite insightface, pyiqa e ONNX Runtime, instala o mediapipe com `--no-deps`; você mesmo define `licensing.mode` como `commercial` |

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

O exiftool oferece a melhor extração de EXIF para todos os formatos. Sem ele, o Facet recorre ao
`exifread` (que lida com todos os formatos RAW) e depois ao PIL (apenas JPEG/TIFF/DNG).

| SO | Comando |
|----|---------|
| Ubuntu/Debian | `sudo apt install libimage-exiftool-perl` |
| macOS | `brew install exiftool` |
| Windows | Baixe em [exiftool.org](https://exiftool.org/) |

## ONNX Runtime para detecção de faces

A detecção de faces (InsightFace) roda sobre o ONNX Runtime: `onnxruntime` (CPU) ou
`onnxruntime-gpu` (CUDA). Os dois compartilham o diretório `onnxruntime/`, então só um pode estar instalado; vale o último que
o pip instalar. O `insightface` depende do build de CPU, de modo que instalá-lo
(`requirements.restricted.txt`, `pip install -e .[all]`, o extra `faces-insightface`)
traz o build de CPU de volta. Em uma máquina CUDA, instale o pacote de GPU **depois** desses,
removendo antes os dois nomes.

O `bash install.sh` faz isso em x86_64 com um PyTorch para CUDA 12 e depois testa uma sessão CUDA real
(como o `--doctor`). Execute-o de novo para reparar um `venv` quebrado ou alternar entre CPU/GPU. As
imagens Docker CUDA fazem o mesmo. Instalações de CPU, CUDA 11.8 (cu118), macOS, a imagem de CPU e
aarch64 (sem wheel `onnxruntime-gpu` para CUDA 12) mantêm o `onnxruntime`.

Manualmente, escolha a linha do build CUDA do seu **PyTorch**:

| Build do PyTorch | Comando |
|---------------|---------|
| Somente CPU, ou CUDA 11.8 (cu118) | `pip uninstall -y onnxruntime onnxruntime-gpu && pip install "onnxruntime>=1.15.0"` |
| CUDA 12.x (cu124, cu126, cu128) | `pip uninstall -y onnxruntime onnxruntime-gpu && pip install "onnxruntime-gpu>=1.19.0,<1.27"` |

- **Acompanhe o PyTorch, não o driver.** A versão de CUDA que o `nvidia-smi` mostra é a mais recente que o
  driver suporta; um driver CUDA 13 ainda executa o PyTorch cu128. O `python facet.py --doctor`
  mostra o build do PyTorch na linha `CUDA (compiled)`.
- **Mantenha o intervalo de versões.** As versões 1.19–1.26 do `onnxruntime-gpu` são builds para CUDA 12; a 1.27+ exige
  bibliotecas CUDA 13. Uma instalação sem limite parece correta, mas roda discretamente na CPU. Para um PyTorch
  CUDA 13 instalado à mão, `"onnxruntime-gpu>=1.27.0"` corresponde (não testado).
- **O CUDA 11.8 não tem build de GPU utilizável.** O antigo `onnxruntime-gpu` para CUDA 11 exige o cuDNN 8,
  mas o PyTorch cu118 usa o cuDNN 9. Para detecção de faces na GPU, atualize o driver para um que informe
  CUDA 12.4 ou mais recente e execute o `install.sh` de novo.
- **Coloque o requisito entre aspas.** Sem aspas, `pip install onnxruntime-gpu>=1.19.0,<1.27` cria um
  arquivo vazio chamado `=1.19.0,` e falha com `1.27: No such file or directory`. Apague esse arquivo.
- **Desinstale os dois nomes.** `pip uninstall onnxruntime` seguido de `pip install onnxruntime-gpu`
  deixa `import onnxruntime` um pacote vazio, e o InsightFace falha com
  `module 'onnxruntime' has no attribute 'InferenceSession'`.

Depois da troca, o `pip check` informa "insightface ... requires onnxruntime, which is not
installed" (`uv pip check`: "The package `insightface` requires `onnxruntime`, but it's not
installed"). Isso é inofensivo: o `onnxruntime-gpu` fornece o mesmo módulo. Da mesma forma, depois da
troca do OpenCV, `insightface` e `facexlib` exigirem `opencv-python` é inofensivo. Um
`pip install -r requirements.txt` posterior traz de volta o OpenCV com interface gráfica; refaça a
[troca do OpenCV](#opencv-na-versão-headless) ou execute o `install.sh` de novo.

**Confira:** a seção **ONNX Runtime** do `python facet.py --doctor` lista o pacote, a versão
e os provedores de execução, e avisa (com a correção) quando os dois pacotes estão instalados
ou a importação falha. Em CUDA, executa uma sessão de teste; a linha `CUDA session` só fica OK quando
realmente roda em `CUDAExecutionProvider`. O teste exige o pacote `onnx` e é ignorado
na CPU e no modo comercial. Uma varredura em CUDA também avisa uma vez quando o InsightFace roda na CPU.

No Docker, um reparo feito dentro do contêiner se perde no próximo `docker run`: baixe uma imagem
atual ou reconstrua-a. As imagens CUDA trazem o `onnxruntime-gpu` 1.26.0 pelo argumento de
build `ORT_GPU_VERSION`; nunca defina a 1.27 ou posterior (CUDA 13).

## OpenCV na versão headless

`opencv-python` (com interface gráfica) e `opencv-python-headless` compartilham o diretório `cv2/`; vale o último
instalado. As dependências do Facet trazem os dois. O build com interface gráfica exige `libGL.so.1`, que
Debian, WSL e hosts enxutos não têm, então `import cv2` falha com
`ImportError: libGL.so.1: cannot open shared object file`. O Facet não abre janelas do OpenCV,
então o build headless basta.

O `bash install.sh` mantém só o build headless em todos os modos, inclusive `--commercial`.
As imagens Docker não são afetadas (elas instalam `libgl1`). Para reparar um `venv` à mão,
troque `<version>` pela versão que o `pip list` mostra para qualquer um dos dois pacotes:

```bash
pip uninstall -y opencv-python opencv-python-headless && pip install --no-deps "opencv-python-headless==<version>"
```

A seção **OpenCV** do `python facet.py --doctor` mostra `[OK]` quando o `cv2` é importado, ou
o erro de importação e o comando de reparo com a sua versão preenchida. Ter os dois pacotes com uma importação
que funciona é normal (as imagens Docker trazem os dois, com `libgl1`). Se uma importação essencial, como
`cv2`, falhar, o `install.sh` imprime "Installation finished with errors" e termina com
status 1.

## Agrupamento de faces por GPU com RAPIDS cuML

Para grandes bancos de dados de faces (80 mil+ faces), o cuML acelera bastante o agrupamento. Ele exige o conda:

```bash
conda create -n facet python=3.12
conda activate facet
conda install -c rapidsai -c conda-forge -c nvidia cuml cuda-version=12.0
# ou: pip install --extra-index-url https://pypi.nvidia.com/ "cuml-cu12"
pip install -r requirements.txt
# requirements.txt instala o opencv-python, o build com interface gráfica (exige libGL.so.1): mantenha só o headless
CV_VER=$(pip show opencv-python-headless opencv-python 2>/dev/null | awk '/^Version:/ {print $2; exit}')
pip uninstall -y opencv-python opencv-python-headless
pip install --no-deps "opencv-python-headless==$CV_VER"
```

Com o cuML instalado, o agrupamento usa a GPU automaticamente (`face_clustering.use_gpu` em
`scoring_config.json`). As imagens Docker CUDA o trazem embutido, então os contêineres `8gb`/`16gb`/`24gb`
agrupam na GPU. O `legacy` sempre agrupa no processador.

## Apple Silicon (Metal/MPS)

Nenhum pacote de GPU extra é necessário. Instale com `bash install.sh` e depois confirme que
`python facet.py --doctor` reporta `Facet runtime device: mps`. O Facet ativa o fallback para CPU
do PyTorch para operadores não suportados. Para comparar:

```bash
FACET_DEVICE=cpu python facet.py /path/to/photos --pass embeddings --force
FACET_DEVICE=mps python facet.py /path/to/photos --pass embeddings --force
```

- `FACET_DEVICE=cpu` desativa a aceleração; `FACET_DEVICE=mps` a exige e falha se
  estiver indisponível. `FACET_DEVICE=cuda` falha da mesma forma quando o PyTorch não vê nenhum dispositivo CUDA
  (por ex. `CUDA_VISIBLE_DEVICES=''`).
- O InsightFace fica no processador (é um modelo do ONNX Runtime).
- As pontuações do TOPIQ podem diferir ligeiramente da CPU/CUDA. No MPS, uma foto cujos lados não são
  múltiplos de 32 é recortada ao centro primeiro (1024×682 vira 1024×672).

`vram_profile: "auto"` dimensiona o perfil pela memória unificada total:

| Memória unificada total | Perfil escolhido por `auto` |
|----------------------|----------------------------|
| menos de 16GB | `legacy` |
| 16-31GB | `8gb` |
| 32-47GB | `16gb` |
| 48GB ou mais | `24gb` |

Cada limite é cerca do dobro da pegada de modelos do perfil, porque o macOS e outros aplicativos
compartilham essa memória. Um Mac que usa swap fica mais lento do que um em um perfil menor. Um perfil
definido explicitamente é sempre usado como escrito.

### Memória em um Mac

Se o Monitor de Atividade mostrar o Facet usando mais memória do que o Mac tem, ou o swap continuar
crescendo durante uma varredura, tente o seguinte, nesta ordem.

**1. Limite o pool de memória do PyTorch:**

```bash
PYTORCH_MPS_HIGH_WATERMARK_RATIO=1.0 python facet.py /path/to/photos
```

`1.0` significa "o conjunto de trabalho recomendado do Mac, nada mais". Uma passagem pode então parar com "out of
memory" em vez de recorrer ao swap, o que é preferível a travar o Mac.

**Os pesos são carregados um a um.** No macOS, o Facet define `HF_DEACTIVATE_ASYNC_LOAD=1` por
padrão, porque o carregamento concorrente pode travar uma varredura no MPS. Não há nada a configurar; defina
`HF_DEACTIVATE_ASYNC_LOAD=0` você mesmo para recuperar o carregamento concorrente.

**2. Desative os dois modelos opcionais mais pesados.** Adicione ao `scoring_config.json` apenas estas chaves:

```json
{
  "models": { "profiles": { "16gb": { "saliency_enabled": false } } },
  "iqa_extended": { "qrealign": false }
}
```

`saliency_enabled` desativa a detecção de assunto; `qrealign` desativa um modelo extra de qualidade.
Estética, composição, rostos e qualidade técnica continuam sendo avaliados. Use a chave de perfil do
seu Mac: `"16gb"` em 32-47GB, `"24gb"` a partir de 48GB.

**3. Processe menos fotos por vez:**

```json
{ "processing": { "ram_chunk_size": 4,
                  "auto_tuning": { "min_ram_chunk_size": 4, "max_ram_chunk_size": 4 } } }
```

Defina as três, ou o ajuste automático move o tamanho do lote entre `min_ram_chunk_size` e
`max_ram_chunk_size`.

## Tamanhos de download

Os modelos são baixados no primeiro uso para:

- `~/.cache/huggingface/` (modelos Hugging Face)
- `~/.cache/torch/hub/` (pesos do PyIQA)
- `~/.insightface/` (detecção/reconhecimento facial)
- `pretrained_models/` na raiz do repositório: `samp_net.pth`, `u2netp.pth`,
  `face_landmarker.task` e `aesthetic_predictor_weights.pth` (somente `legacy`/`8gb`)

No Docker, esses são volumes nomeados (`pretrained_models/` é `facet-pretrained`), então nada é
baixado de novo quando o contêiner é recriado. Nenhum peso vem embutido na imagem.

Os tamanhos são decimais (GB = 10⁹ bytes, MB = 10⁶ bytes).

| Modelo | Tamanho | Perfis |
|-------|------|----------|
| CLIP ViT-L-14 laion2b (embeddings + marcação CLIP + estética CLIP-MLP) | 1,711 GB | `legacy`/`8gb` |
| Cabeça estética MLP (`sac+logos+ava1-l14-linearMSE.pth`) | 3,7 MB | somente `legacy`/`8gb` |
| SigLIP 2 NaFlex SO400M (embeddings) | 4,581 GB | `16gb`/`24gb` |
| Qwen3.5-2B (marcação por VLM) | 4,571 GB | `16gb` |
| Qwen3.5-4B (marcação por VLM) | 9,343 GB | `24gb` |
| Qwen2-VL-2B (composição) | 4,430 GB | nenhum por padrão; veja a nota 1 |
| InsightFace buffalo_l (rostos) | 289 MB baixados / 630 MB em disco (o zip é mantido ao lado dos arquivos `.onnx`) | todos |
| Pesos do SAMP-Net (composição) | 183 MB | todos |
| U2-Net-P (submodelo de saliência do SAMP-Net) | 4,7 MB | mesmos do SAMP-Net |
| BiRefNet_dynamic (saliência do sujeito) | 445 MB | todos |
| TOPIQ NR (modelo estético) | 181 MB | `16gb`/`24gb` |
| TOPIQ IAA (estética complementar) | 873 MB | todos |
| TOPIQ NR-Face (qualidade facial complementar) | 376 MB | todos |
| LIQE (qualidade/distorção complementar) | 708 MB | todos |
| timm resnet50.a1_in1k (backbone PyIQA compartilhado) | 102 MB | todos |
| Q-ReAlign-Mini-0.8B (`iqa_extended.qrealign`) | 2,235 GB | `8gb`/`16gb`/`24gb`, **ativado por padrão** (`"auto"`) |

1. O Qwen2-VL-2B só é carregado se você definir `composition_model: "qwen2-vl-2b"` **e**
   `processing.mode: "single-pass"`, substituindo SAMP-Net/U2-Net-P. Fora do modo comercial
   isso só funciona em `legacy`/`8gb`: em `16gb`/`24gb` o passo único recorre ao multi-passo,
   que não tem passo do Qwen2-VL.

Totais por perfil (download): `legacy` 4,69 GB · `8gb` 6,93 GB · `16gb` 14,55 GB ·
`24gb` 19,32 GB · `24gb` com composição Qwen2-VL 23,56 GB (somente no modo comercial, veja a nota 1).

As próprias imagens Docker, antes de qualquer download de modelo: `latest` 3,34 GB descompactada,
`latest-cuda` 13,1 GB, `latest-cuda-legacy` 13,8 GB
([Implantação › Tamanho da imagem](DEPLOYMENT.md#tamanho-da-imagem)). Os tamanhos de download compactados ainda não foram
medidos.

Modelos opcionais, fora dos totais:

| Modelo | Tamanho | Gatilho |
|-------|------|---------|
| DeQA-Score-Mix3 (`iqa_extended.deqa`) | 16,41 GB | desativado por padrão |
| Backbone SigLIP so400m-patch14-384 (`iqa_extended.aesthetic_v25`) | 3,515 GB | desativado por padrão, **descontinuado** (prefira `qrealign`) |
| Helsinki-NLP OPUS-MT, por idioma de destino (tradução de legendas) | en→fr 303 MB · en→de 298 MB · en→es 312 MB · en→it 343 MB · en→pt 465 MB | somente para os idiomas ativados |
| MediaPipe `face_landmarker.task` | 3,76 MB | somente quando `mediapipe` está instalado |

O `reverse_geocoder` não precisa de download; seus dados vêm no wheel.

Os pesos do SAMP-Net vêm do
[release model-weights-v1](https://github.com/ncoevoet/facet/releases/download/model-weights-v1/samp_net.pth).
Se você vir `Failed to download SAMP-Net weights: HTTP Error 404: Not Found` (offline ou
rede restrita), baixe o arquivo e coloque-o em `pretrained_models/samp_net.pth`.

## Dependências

### Pacotes obrigatórios

| Pacote | Finalidade |
|---------|---------|
| `torch`, `torchvision` | Framework de deep learning (instalado separadamente, veja acima) |
| `open-clip-torch` | Embeddings/tagueamento CLIP (perfis legacy/8gb) |
| `pyiqa` | TOPIQ e outros modelos de qualidade/estética |
| `opencv-python` | Processamento de imagens |
| `pillow` | Carregamento de imagens, incl. PNG/GIF/WebP/BMP/TIFF/AVIF (AVIF precisa de pillow>=11.3) |
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
| `sqlite-vec` | Busca semântica em disco (recorre a um cache NumPy em memória); `pip install -e .[vec]` |
| `tifffile`, `imagecodecs` | Fotos JPEG XL e prévias de DNGs mesclados pelo Lightroom Classic 13+ (HDR/Panorama/Aprimorar) |

Todos esses estão em `requirements.txt`, exceto `pyiqa` e `insightface`, que estão em `requirements.restricted.txt` (veja [Instalação comercial e pacotes restritos](#instalação-comercial-e-pacotes-restritos)). Nenhum perfil precisa de pacotes base adicionais.

### Pacotes opcionais

Cada um desbloqueia um recurso; sem ele, o recurso é pulado ou um fallback é usado.

| Pacote | Desbloqueia | Sem ele |
|---------|-------------------|-----------|
| `watchdog` | Modo de observação (`--watch`); **não está em `requirements.txt`**, instale com `pip install .[watch]` | `--watch` indisponível |
| `pillow-heif` | Decodificação HEIF/HEIC | Arquivos HEIF/HEIC pulados |
| `rawpy` | Decodificação RAW (CR2/CR3/NEF/ARW/…), já está no `requirements.txt` | Arquivos RAW pulados |
| `cuml`, `cupy` | Agrupamento de faces por GPU (conda + CUDA) | Agrupamento em CPU via `hdbscan` (padrão) |
| `onnxruntime-gpu` | Detecção de faces por GPU, **no lugar do** `onnxruntime` ([detalhes](#onnx-runtime-para-detecção-de-faces)) | `onnxruntime` em CPU (mais lento) |
| `aesthetic-predictor-v2-5` | Pontuador `aesthetic_v25` (`pip install -e .[iqa-extended]`, `iqa_extended.aesthetic_v25`, desativado por padrão). **Descontinuado** (AGPL-3.0, sem manutenção desde 2024-12-18); prefira `qrealign`, que não precisa de nenhum pacote extra | `aesthetic_v25` indisponível |
| `darktable-cli` (sistema) | Exportação de perfil RAW/darktable a partir do visualizador | Apenas download original/embutido oferecido |
| `exiftool` (sistema) | Melhor extração de EXIF/GPS | Recorre ao `exifread`, depois ao PIL |

## Requisitos por recurso

A maior parte do Facet roda em qualquer lugar (CPU, qualquer perfil). Alguns recursos precisam de uma GPU, de um **perfil
de VRAM** mais alto, de um pacote opcional, ou da **senha de edição** / função de **superadmin** do visualizador. Tags usadas na documentação:
`[GPU]` · `[16gb/24gb]` (perfil de VRAM) · `[Edition]` · `[Superadmin]` · `[Optional: pkg]`.

| Recurso | GPU | Perfil | Autenticação | Pacote opcional |
|---------|:---:|---------|:----:|------------------|
| Pontuação / escaneamento (base) | opcional | qualquer (`legacy` = CPU) | — | — |
| Estética TOPIQ | sim | `16gb`/`24gb` | — | — |
| IQA suplementar (TOPIQ IAA, NR-Face, LIQE) | opcional | qualquer (`legacy` = CPU) | — | — |
| Embeddings SigLIP 2 | sim | `16gb`/`24gb` | — | — |
| Marcação por VLM (Qwen3.5) | sim | `16gb`/`24gb` | — | — |
| Padrão de composição (SAMP-Net) | opcional | qualquer (`legacy` = CPU) | — | — |
| Saliência do sujeito (BiRefNet) | opcional | qualquer (`legacy` = CPU) | — | — |
| Legendas por IA (gerar / visualizar) | sim | `16gb`/`24gb` | edition (geração) | — |
| Legendas por IA (editar) | sim | `16gb`/`24gb` | edition | — |
| Crítica VLM | sim | `16gb`/`24gb` | edition (geração) | — |
| Detecção / extração de faces (InsightFace) | recomendado (funciona em CPU, mais lento) | qualquer | — | — |
| Agrupamento de faces (HDBSCAN) | não (CPU) | qualquer | — | `cuml`/`cupy` (aceleração opcional por GPU) |
| Busca semântica | não | qualquer | — | `sqlite-vec` (recorre ao NumPy) |
| Decodificação RAW / HEIF | não | qualquer | — | `rawpy` / `pillow-heif` |
| Modo de observação (`--watch`) | não | qualquer | — | `watchdog` |
| Extração de GPS / exportação darktable | não | qualquer | — | `exiftool` / `darktable-cli` |
| Avaliações, favoritos, edições de face e pessoa, seleção (culling) | não | qualquer | edition | — |
| Disparar escaneamentos a partir da interface web | não | qualquer | edição (usuário único) / superadmin (multiusuário) | — |
| Multiusuário (avaliações e funções por usuário) | não | qualquer | baseada em função | — |

A senha de edição e as funções de usuário são configuradas em `scoring_config.json`; veja
[Configuração](CONFIGURATION.md).

> Sem GPU local? Aponte a marcação por VLM, as legendas e a crítica para um servidor Ollama remoto ou
> compatível com OpenAI com `vlm_backend` em `scoring_config.json`. Esses recursos passam a
> funcionar também nos perfis `legacy`/`8gb`.

## Solução de Conflitos de Dependência

Os pacotes de ML do Facet (`torch`, `open-clip-torch`, `insightface`, …) puxam muitas
dependências, e instalá-los um a um pode quebrar uns aos outros.

**Sintomas:** cada instalação pede mais um pacote; conflitos de versão entre
`torch`, `numpy`, `huggingface-hub` ou `open-clip-torch`; o `pip install` é bem-sucedido, mas o
`import` falha.

**1. Instale tudo de uma vez:** `pip install -r requirements.txt`, para que o pip resolva o
grafo completo. Não instale pacotes individualmente
(`pip install open-clip-torch && pip install insightface && ...`).

**2. Use o [uv](https://docs.astral.sh/uv/)**: o `uv` resolve o grafo completo antes de
instalar:

```bash
pip install uv
uv pip install -r requirements.txt
# Com o índice de CUDA para o PyTorch:
uv pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cu128
```

**3. Comece do zero:** `deactivate`, `rm -rf venv`, e refaça a
[instalação manual](#instalação-manual-sem-o-installsh) (ou execute o `install.sh` de novo).

### Problemas de detecção de GPU

Se a sua GPU não for detectada (comum em placas mais novas), execute:

```bash
python facet.py --doctor
```

Ele verifica o suporte a CUDA do PyTorch e o driver, e sugere o comando pip correto. Também
detecta o que o `torch.cuda.is_available()` não percebe: uma GPU para a qual o PyTorch instalado não tem kernels (por ex. série RTX 50 em uma build anterior à CUDA
12.8). Nesse caso o Facet recorre à CPU em vez de travar, e o `--doctor` indica
a correção: no Docker, a tag de imagem correta (`ghcr.io/ncoevoet/facet:latest-cuda-legacy` para
Maxwell/Pascal/Volta); em instalação nativa, a `--index-url` correta.

Para simular hardware em testes:

```bash
python facet.py --doctor --simulate-gpu "RTX 5070 Ti" --simulate-vram 16
```

## Cliente Angular

Necessário apenas para desenvolvimento ou builds personalizados; o `install.sh` e a imagem Docker já
o compilam.

```bash
cd client
npm install
npm run build    # Build de produção → client/dist/
npm start        # Servidor de desenvolvimento em http://localhost:4200 (encaminha a API para :5000)
```

> **Avisos do `npm audit`:** a maioria dos achados está em dependências de desenvolvimento de tempo
> de compilação que nunca chegam ao navegador. Revise-os antes de executar `npm audit fix`, que pode
> rebaixar ou remover pacotes.
