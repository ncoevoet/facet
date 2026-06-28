# Instalação

> 🌐 [English](../INSTALLATION.md) · [Français](../fr/INSTALLATION.md) · [Deutsch](../de/INSTALLATION.md) · [Italiano](../it/INSTALLATION.md) · [Español](../es/INSTALLATION.md) · **Português**

## Início Rápido

```bash
git clone https://github.com/ncoevoet/facet.git && cd facet
bash install.sh          # auto-detects GPU, creates venv, installs everything

# Activate the venv that install.sh created — the install script can't do this
# for you because it runs in a subshell.
source venv/bin/activate         # macOS/Linux
# .\venv\Scripts\Activate.ps1    # Windows PowerShell

python facet.py --doctor # verify your setup
```

`install.sh` cria o venv, detecta GPU/CUDA, instala o PyTorch com a index URL correspondente, a variante correta do ONNX Runtime, o restante das dependências e compila o frontend Angular.

**Opções:**
| Flag | Efeito |
|------|--------|
| `--cpu` | Força o PyTorch somente em CPU (sem CUDA) |
| `--cuda VERSION` | Substitui a versão de CUDA detectada (ex.: `--cuda 12.8`) |
| `--skip-client` | Pula a compilação do frontend Angular |
| `--no-uv` | Usa pip em vez de uv |

Um `Makefile` também está disponível: `make install`, `make install-cpu`, `make run`, `make doctor`.

---

## Instalação Manual

### Requisitos de Sistema

- Python 3.12 (3.10+ suportado)
- `exiftool` (pacote de sistema, opcional mas recomendado)

#### Instalando o exiftool

O exiftool oferece a melhor extração de EXIF para todos os formatos. Sem ele, o aplicativo recorre ao `exifread` (biblioteca Python, lida com todos os formatos RAW) e depois ao PIL (apenas JPEG/TIFF/DNG).

| SO | Comando |
|----|---------|
| Ubuntu/Debian | `sudo apt install libimage-exiftool-perl` |
| macOS | `brew install exiftool` |
| Windows | Baixe em [exiftool.org](https://exiftool.org/) |

### Ambiente Python

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install PyTorch first with the correct CUDA index URL.
# cu128 targets CUDA 12.8+/13.x; for CUDA 11.8 use cu118, for CUDA 12.4 use cu124.
# When unsure, pick the matching command at https://pytorch.org/get-started/locally/
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128

# Install dependencies (all at once for proper dependency resolution).
# requirements.txt already includes transformers and accelerate, needed for
# the SigLIP/BiRefNet/VLM models used by the 8gb+ profiles.
pip install -r requirements.txt
```

> **Encontrando erros de dependência?** Veja [Solução de Conflitos de Dependência](#troubleshooting-dependency-conflicts) abaixo.

### Configuração da GPU

#### PyTorch com CUDA

Instale a partir de [pytorch.org/get-started/locally](https://pytorch.org/get-started/locally/) de acordo com a sua versão de CUDA. O script de instalação faz isso automaticamente.

#### ONNX Runtime para Detecção de Faces

Escolha UM com base na sua configuração:

| Opção | Comando |
|--------|---------|
| Apenas CPU | `pip install onnxruntime>=1.15.0` |
| CUDA 12.x | `pip install onnxruntime-gpu>=1.17.0` |
| CUDA 11.8 | `pip install onnxruntime-gpu>=1.15.0,<1.18` |

**Verifique a sua versão de CUDA:** Execute `nvidia-smi` e veja no canto superior direito o texto "CUDA Version: X.X".

Ao migrar da versão CPU para a versão GPU:
```bash
pip uninstall onnxruntime
pip install onnxruntime-gpu>=1.17.0
```

### RAPIDS cuML para Agrupamento de Faces em GPU (Opcional)

Para grandes bancos de dados de faces (80 mil+ faces), o agrupamento acelerado por GPU via cuML acelera significativamente o agrupamento de faces. Requer um ambiente conda:

```bash
# Create conda environment with CUDA support
conda create -n facet python=3.12
conda activate facet

# Install cuML (choose your CUDA version)
conda install -c rapidsai -c conda-forge -c nvidia cuml cuda-version=12.0

# Alternative: pip install
pip install --extra-index-url https://pypi.nvidia.com/ "cuml-cu12"

# Install other dependencies
pip install -r requirements.txt
```

Quando o cuML está disponível, o agrupamento de faces usa GPU automaticamente (configurável via `face_clustering.use_gpu` em `scoring_config.json`).

## Verificar a Instalação

```bash
python -c "import torch, cv2, fastapi, insightface, open_clip, pyiqa, numpy, scipy, sklearn, PIL, imagehash, rawpy, tqdm, exifread; print('All imports successful')"
```

## Resumo das Dependências

### Pacotes Obrigatórios

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

### Pacotes Opcionais

Cada um desbloqueia um recurso; sem ele, o recurso é pulado ou um fallback é usado.

| Pacote | Desbloqueia / finalidade | Sem ele |
|---------|-------------------|-----------|
| `watchdog` | Modo de observação (daemon `--watch` reescaneia novos arquivos) — **não está em `requirements.txt`**; só é puxado via `pip install .[watch]`, então usuários diretos de `requirements.txt` não obtêm o `--watch` | `--watch` indisponível |
| `pillow-heif` | Decodificação HEIF/HEIC | Arquivos HEIF/HEIC pulados |
| `rawpy` | Decodificação RAW (CR2/CR3/NEF/ARW/…) | Arquivos RAW pulados (já está no `requirements.txt` base) |
| `cuml`, `cupy` | Agrupamento de faces acelerado por GPU (conda + CUDA) | O agrupamento roda em CPU via `hdbscan` (padrão) |
| `onnxruntime-gpu` | Detecção de faces acelerada por GPU | `onnxruntime` em CPU (mais lento) |
| `aesthetic-predictor-v2-5`, `bitsandbytes` | Camada de IQA estendida (`pip install -e .[iqa-extended]`; `iqa_extended` em `scoring_config.json`, desativada por padrão) | Métricas de IQA estendida indisponíveis |
| `darktable-cli` (sistema) | Exportação de perfil RAW/darktable a partir do visualizador | Apenas download original/embutido oferecido |
| `exiftool` (sistema) | Melhor extração de EXIF/GPS | Recorre ao `exifread`, depois ao PIL |

## Requisitos por recurso

A maior parte do Facet roda em qualquer lugar (CPU, qualquer perfil). Alguns recursos precisam de uma GPU, de um **perfil de VRAM** mais alto, de um pacote opcional, ou da **senha de edição** / função de **superadmin** do visualizador. Tags usadas ao longo da documentação:
`[GPU]` · `[16gb/24gb]` (perfil de VRAM) · `[Edition]` · `[Superadmin]` · `[Optional: pkg]`.

| Recurso | GPU | Perfil | Autenticação | Pacote opcional |
|---------|:---:|---------|:----:|------------------|
| Pontuação / escaneamento (base) | opcional | qualquer (`legacy` = CPU) | — | — |
| Estética TOPIQ | sim | `16gb`/`24gb` | — | — |
| IQA suplementar (TOPIQ IAA, NR-Face, LIQE) | sim | `8gb`/`16gb`/`24gb` | — | — |
| Embeddings SigLIP 2 | sim | `16gb`/`24gb` | — | — |
| Tagueamento VLM (Qwen3.5) | sim | `16gb`/`24gb` | — | — |
| Padrão de composição (SAMP-Net) | opcional | qualquer (`legacy` = CPU) | — | — |
| Composição (Qwen2-VL) | sim | `24gb` | — | — |
| Saliência do sujeito (BiRefNet) | sim | `16gb`/`24gb` | — | — |
| Legendas por IA (gerar / visualizar) | sim | `16gb`/`24gb` | — | — |
| Legendas por IA (editar) | sim | `16gb`/`24gb` | edition | — |
| Crítica VLM | sim | `16gb`/`24gb` | — | — |
| Detecção / extração de faces (InsightFace) | recomendado (CPU funciona, lento) | qualquer | — | — |
| Agrupamento de faces (HDBSCAN) | não (CPU) | qualquer | — | `cuml`/`cupy` (aceleração opcional por GPU) |
| Busca semântica | não | qualquer | — | `sqlite-vec` (recorre ao NumPy) |
| Decodificação RAW / HEIF | não | qualquer | — | `rawpy` / `pillow-heif` |
| Modo de observação (`--watch`) | não | qualquer | — | `watchdog` |
| Extração de GPS / exportação darktable | não | qualquer | — | `exiftool` / `darktable-cli` |
| Avaliações, favoritos, edições de face e pessoa, seleção (culling) | não | qualquer | edition | — |
| Disparar escaneamentos a partir da interface web | não | qualquer | superadmin | — |
| Multiusuário (avaliações e funções por usuário) | não | qualquer | baseada em função | — |

> O *agrupamento* de faces roda em CPU por padrão (`hdbscan` autônomo); `cuml`/`cupy` apenas adicionam aceleração opcional por GPU — eles **não** são obrigatórios. A senha de edição e as funções de usuário são configuradas em `scoring_config.json` — veja [Configuração](CONFIGURATION.md) para autenticação.

## Solução de Conflitos de Dependência

O Facet tem muitas dependências de ML (`torch`, `open-clip-torch`, `insightface`, etc.) que puxam suas próprias dependências transitivas. O pip resolve dependências sequencialmente, o que pode levar a erros em cascata onde a instalação de um pacote quebra outro.

### Sintomas

- Instalar pacotes um a um dispara erros pedindo que você instale ainda outro pacote
- Conflitos de versão entre `torch`, `numpy`, `huggingface-hub` ou `open-clip-torch`
- O `pip install` é bem-sucedido, mas o `import` falha em tempo de execução

### Soluções

**1. Instale tudo de uma vez** — `pip install -r requirements.txt` dá ao pip o grafo completo de dependências para resolver. Não instale pacotes individualmente (`pip install open-clip-torch && pip install insightface && ...`); isso impede que o pip resolva o grafo completo.

**2. Use o [uv](https://docs.astral.sh/uv/) em vez do pip** — o `uv` resolve o grafo completo de dependências antecipadamente, antes de instalar qualquer coisa, evitando conflitos em cascata:

```bash
# Install uv
pip install uv

# Install all dependencies with full resolution
uv pip install -r requirements.txt

# With CUDA index for PyTorch:
uv pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cu128
```

**3. Comece do zero** — se o seu ambiente já está em um estado quebrado, execute `deactivate`, `rm -rf venv` e reconstrua-o reexecutando os passos de [Ambiente Python](#python-environment) acima.

### Problemas de Detecção de GPU

Se a sua GPU não for detectada (comum com GPUs mais novas como a RTX 5070 Ti), execute a ferramenta de diagnóstico:

```bash
python facet.py --doctor
```

Isso verifica o suporte a CUDA do PyTorch, a compatibilidade do driver e sugere o comando de instalação pip correto. Você também pode simular cenários de GPU para testes:

```bash
python facet.py --doctor --simulate-gpu "RTX 5070 Ti" --simulate-vram 16
```

## Primeira Execução

Na primeira execução, o Facet baixa automaticamente o modelo de embedding para o seu perfil:
- CLIP ViT-L-14 (perfis legacy/8gb): ~1,7GB — ou SigLIP 2 NaFlex SO400M (perfis 16gb/24gb), maior
- Modelo InsightFace buffalo_l: ~400MB
- Pesos do SAMP-Net (todos os perfis): ~50MB

Os modelos são armazenados em cache em locais padrão (`~/.cache/` ou `~/.insightface/`).

## Cliente Angular (Opcional)

Necessário apenas para desenvolvimento ou builds personalizados; o `install.sh` já o compila.

```bash
cd client
npm install
npm run build    # Production build → client/dist/
npm start        # Dev server on http://localhost:4200 (proxies API to :5000)
```

> **Avisos do `npm audit`:** O Angular puxa uma árvore profunda de dependências
> transitivas e o `npm audit` reportará achados, a maioria dos quais está em
> dependências de desenvolvimento de tempo de compilação que nunca chegam ao
> navegador. Revise a lista antes de executar `npm audit fix` — ele pode
> silenciosamente rebaixar ou remover pacotes.

> **Porta 5000 no macOS:** O AirPlay Receiver do ControlCenter escuta na porta
> 5000 por padrão. Inicie o visualizador com `python viewer.py --port 5001` (ou
> defina a variável de ambiente `PORT`) para evitar o conflito.

### Download Manual do SAMP-Net

Os pesos do SAMP-Net são baixados automaticamente no primeiro uso a partir do release de pesos de modelo do projeto (`github.com/ncoevoet/facet/releases/download/model-weights-v1/samp_net.pth`). Normalmente nenhuma etapa manual é necessária.

Se o download automático falhar (ex.: offline ou com rede restrita) você verá:
```
Failed to download SAMP-Net weights: HTTP Error 404: Not Found
```

Então faça o download manualmente:
1. Baixe `samp_net.pth` do [release model-weights-v1](https://github.com/ncoevoet/facet/releases/download/model-weights-v1/samp_net.pth) (ou, como fallback secundário, do [Google Drive](https://drive.google.com/file/d/1sIcYr5cQGbxm--tCGaASmN0xtE_r-QUg/view))
2. Coloque o arquivo em `pretrained_models/samp_net.pth`
