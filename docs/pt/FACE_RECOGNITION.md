# Reconhecimento facial

> 🌐 [English](../FACE_RECOGNITION.md) · [Français](../fr/FACE_RECOGNITION.md) · [Deutsch](../de/FACE_RECOGNITION.md) · [Italiano](../it/FACE_RECOGNITION.md) · [Español](../es/FACE_RECOGNITION.md) · **Português**

O Facet usa o InsightFace para detecção de rostos e o HDBSCAN para agrupar rostos em pessoas.

## Visão geral

1. **Detecção** - O modelo buffalo_l do InsightFace detecta rostos e extrai embeddings de 512 dimensões
2. **Agrupamento** - O HDBSCAN agrupa embeddings semelhantes em clusters de pessoas
3. **Gerenciamento** - Visualizador web para mesclar, renomear e organizar pessoas

## Fluxo de trabalho completo

### Passo 1: Extrair rostos

Durante a varredura das fotos, os rostos são extraídos automaticamente:

```bash
python facet.py /path/to/photos
```

Para fotos existentes sem rostos:

```bash
python facet.py --extract-faces-gpu-incremental  # New photos only
python facet.py --extract-faces-gpu-force        # All photos (deletes existing)
```

### Passo 2: Agrupar rostos

Agrupe rostos semelhantes em pessoas:

```bash
python facet.py --cluster-faces-incremental  # Preserves existing persons
```

**Modos de agrupamento:**

| Comando | Comportamento |
|---------|----------|
| `--cluster-faces-incremental` | Preserva todas as pessoas, associa novos rostos aos existentes |
| `--cluster-faces-incremental-named` | Preserva apenas pessoas nomeadas |
| `--cluster-faces-force` | Exclui todas as pessoas, reagrupa do zero |

### Passo 3: Revisar e mesclar

Encontre clusters de pessoas duplicados:

```bash
python facet.py --suggest-person-merges
python facet.py --suggest-person-merges --merge-threshold 0.7  # Stricter
```

Isso abre a página de sugestões de mesclagem no navegador.

### Passo 4: Gerenciar no visualizador

O trabalho restante acontece no visualizador web, seguindo o pipeline **Extrair → Agrupar → Mesclar → Gerenciar**:

- **Mescle** clusters duplicados na página Sugestões de mesclagem.
- **Gerencie** pessoas (mesclar, mesclagem em lote, dividir, ocultar, renomear, excluir) na página Gerenciar pessoas.

Consulte [Integração com o visualizador](#viewer-integration) para a referência completa da interface.

## Configuração

### Detecção de rostos

```json
{
  "face_detection": {
    "min_confidence_percent": 65,
    "min_face_size": 20,
    "blink_ear_threshold": 0.28
  }
}
```

| Configuração | Padrão | Descrição |
|---------|---------|-------------|
| `min_confidence_percent` | `65` | Confiança mínima de detecção |
| `min_face_size` | `20` | Tamanho mínimo do rosto em pixels |
| `blink_ear_threshold` | `0.28` | Eye Aspect Ratio para detecção de piscadas |

### Agrupamento de rostos

```json
{
  "face_clustering": {
    "enabled": true,
    "min_faces_per_person": 2,
    "min_samples": 2,
    "auto_merge_distance_percent": 15,
    "clustering_algorithm": "best",
    "leaf_size": 40,
    "use_gpu": "auto",
    "merge_threshold": 0.6,
    "chunk_size": 10000
  }
}
```

| Configuração | Padrão | Descrição |
|---------|---------|-------------|
| `min_faces_per_person` | `2` | Número mínimo de fotos para criar uma pessoa |
| `min_samples` | `2` | Parâmetro min_samples do HDBSCAN |
| `merge_threshold` | `0.6` | Similaridade de centroide para associação |
| `use_gpu` | `"auto"` | Modo de GPU: `auto`, `always`, `never` |

### Processamento de rostos

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

## Algoritmos de agrupamento

Para agrupamento em CPU, escolha o algoritmo de acordo com o tamanho do conjunto de dados:

| Algoritmo | Complexidade | Indicado para |
|-----------|------------|----------|
| `boruvka_balltree` | O(n log n) | Alta dimensionalidade (recomendado para mais de 50 mil rostos) |
| `boruvka_kdtree` | O(n log n) | Dados de baixa dimensionalidade |
| `prims_balltree` | O(n²) | Conjuntos pequenos, com restrição de memória |
| `prims_kdtree` | O(n²) | Conjuntos pequenos |
| `best` | Automático | Deixa o HDBSCAN decidir |

**Nota de desempenho:** Para grandes conjuntos de dados, use `boruvka_balltree`. Com 80 mil rostos, ele conclui em 2 a 5 minutos, enquanto algoritmos exatos podem travar.

## Agrupamento em GPU (cuML)

Para grandes conjuntos de dados (mais de 80 mil rostos), o agrupamento em GPU via RAPIDS cuML é mais rápido do que em CPU.

### Instalação

```bash
# Conda
conda install -c rapidsai -c conda-forge -c nvidia cuml cuda-version=12.0

# Pip
pip install --extra-index-url https://pypi.nvidia.com/ "cuml-cu12"
```

### Configuração

```json
{
  "face_clustering": {
    "use_gpu": "auto"
  }
}
```

| Modo | Comportamento |
|------|----------|
| `"auto"` | Usa GPU se o cuML estiver disponível, com fallback para CPU |
| `"always"` | Tenta a GPU; avisa e faz fallback se indisponível |
| `"never"` | Sempre usa CPU |

**Nota:** O cuML usa sua própria implementação do HDBSCAN. Os parâmetros `algorithm` e `leaf_size` aplicam-se somente ao agrupamento em CPU.

## Detecção de piscadas

Usa o Eye Aspect Ratio (EAR) a partir dos 106 pontos de referência (landmarks) do InsightFace.

### Como funciona

O EAR mede a razão entre a altura e a largura do olho. Quando os olhos se fecham, o EAR cai abaixo do limiar.

### Configuração

```json
{
  "face_detection": {
    "blink_ear_threshold": 0.28
  }
}
```

Limiar mais baixo = detecção mais rigorosa (mais fotos sinalizadas como piscadas).

### Recalcular após mudança de limiar

```bash
python facet.py --recompute-blinks
```

Processa apenas fotos com rostos, sem necessidade de GPU.

## Sinais de expressão por rosto (olhos abertos + sorriso)

Cada linha de rosto armazena dois sinais contínuos em escala 0-10 usados pelo painel de rostos da
seleção e pelos agregados em nível de foto: `eyes_open_score` (10 = totalmente aberto, 0 =
totalmente fechado) e `smile_score` (5 = neutro, 10 = sorriso amplo, 0 = carranca).

Dois mecanismos os produzem, na mesma escala 0-10:

1. **Geometria (sempre disponível).** Derivado dos 106 pontos de referência do InsightFace
   armazenados: o Eye Aspect Ratio para olhos abertos, a elevação dos cantos da boca para o
   sorriso. Geometria pura, então `--recompute-face-signals` pode recalculá-los a partir dos pontos
   de referência armazenados sem pixels e sem GPU.
2. **Blendshapes do MediaPipe (opcional, baseado em aparência).** Durante a varredura / extração de
   rostos, um recorte generoso de cada rosto passa pelo MediaPipe Face Landmarker, cujos blendshapes
   no estilo ARKit (`eyeBlink*`, `mouthSmile*`, `mouthFrown*`) mapeiam para as mesmas escalas. A
   aparência supera a geometria de pontos de referência em olhos fechados, sorrisos sutis e cabeças
   fora de eixo, então quando um rosto é pontuado pelo MediaPipe, ele **substitui** o valor
   geométrico. Se o MediaPipe ou seu pacote de modelo estiverem ausentes, ou o recorte do rosto for
   pequeno demais / não detectado, o valor geométrico é mantido — o comportamento é idêntico a uma
   instalação somente com geometria.

### Instalando o MediaPipe

O MediaPipe é opcional e **deve** ser instalado sem seu `opencv-contrib-python` empacotado, que
instalaria um segundo namespace `cv2` ao lado do `opencv-python` do Facet:

```bash
pip install mediapipe==0.10.35 --no-deps
pip install absl-py flatbuffers
```

Nunca execute um simples `pip install mediapipe`.

### Pacote de modelo

O pacote `face_landmarker.task` (~3,6 MiB, Apache-2.0) é baixado automaticamente no primeiro uso
para `pretrained_models/face_landmarker.task`. Se a máquina estiver offline, baixe-o manualmente em
`https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task`
e coloque-o nesse caminho. Um download com falha registra um aviso uma única vez e recorre às
pontuações geométricas.

### Configuração

```json
{
  "face_detection": {
    "blendshapes": {
      "enabled": true,
      "min_crop_size": 192
    }
  }
}
```

- `enabled` (padrão `true`): usa as pontuações de blendshape sempre que o MediaPipe e o pacote de
  modelo estiverem disponíveis; caso contrário, o retorno geométrico é executado automaticamente.
  Defina como `false` para forçar apenas geometria.
- `min_crop_size` (padrão `192`): rostos cujo recorte com margem seja menor que este valor (px,
  lado mais curto) recorrem à geometria em vez de ampliar um rosto minúsculo.

### Recálculo

`--recompute-face-signals` recalcula os sinais por rosto apenas a partir dos pontos de referência
armazenados — é **somente geometria** e não executa o MediaPipe (nenhum pixel é lido). Para
atualizar as pontuações baseadas em aparência, reextraia os rostos (`--extract-faces-gpu-force`)
para que os recortes em resolução total sejam reanalisados.

## Miniaturas de rostos

As miniaturas são armazenadas no banco de dados para exibição rápida.

### Armazenamento

- Geradas durante a varredura a partir de imagens em resolução total
- Armazenadas na coluna `faces.face_thumbnail` como BLOBs JPEG (cerca de 5 a 10 KB cada)
- Usadas pelo agrupamento e pelo visualizador em vez de serem regeradas

### Regeneração

```bash
# Generate missing thumbnails
python facet.py --refill-face-thumbnails-incremental

# Regenerate ALL thumbnails
python facet.py --refill-face-thumbnails-force
```

Ambos os comandos usam processamento paralelo para maior velocidade.

## Esquema do banco de dados

### Tabela faces

| Coluna | Tipo | Descrição |
|--------|------|-------------|
| `id` | INTEGER | Chave primária |
| `photo_path` | TEXT | Chave estrangeira para photos |
| `face_index` | INTEGER | Índice dentro da foto |
| `embedding` | BLOB | Embedding de rosto de 512 dimensões |
| `bbox_x1`, `bbox_y1`, `bbox_x2`, `bbox_y2` | INTEGER | Cantos da caixa delimitadora |
| `confidence` | REAL | Confiança de detecção |
| `person_id` | INTEGER | Chave estrangeira para persons |
| `face_thumbnail` | BLOB | Miniatura JPEG |
| `landmark_2d_106` | BLOB | 106 pontos de referência (detecção de piscadas) |
| `embedding_model` | TEXT | Tag do modelo de reconhecimento (padrão `arcface_buffalo_l`) |

### Tabela persons

| Coluna | Tipo | Descrição |
|--------|------|-------------|
| `id` | INTEGER | Chave primária |
| `name` | TEXT | Nome da pessoa (NULL = agrupada automaticamente) |
| `representative_face_id` | INTEGER | Melhor rosto para o avatar |
| `face_count` | INTEGER | Número de rostos |
| `centroid` | BLOB | Embedding do centroide do cluster |
| `auto_clustered` | INTEGER | 1 se gerada automaticamente |
| `face_thumbnail` | BLOB | Miniatura do avatar da pessoa |
| `is_hidden` | INTEGER | 1 = excluída de filtros/sugestões |

## Modos incremental e forçado

### Agrupamento incremental

- Preserva todas as pessoas existentes (nomeadas e agrupadas automaticamente)
- Agrupa apenas rostos novos e não atribuídos
- Associa novos clusters a pessoas existentes via similaridade de centroide
- Atualiza os centroides após a mesclagem

**Use quando:** Adicionar novas fotos a uma coleção existente

### Agrupamento forçado

- Exclui TODAS as pessoas, incluindo as nomeadas
- Reagrupa por completo do zero

**Use quando:** Começar do zero ou em grandes mudanças de algoritmo

### Agrupamento incremental-nomeado

- Preserva apenas pessoas nomeadas
- Exclui pessoas agrupadas automaticamente
- Reagrupa todos os rostos sem nome

**Use quando:** Manter nomes curados enquanto atualiza os clusters detectados automaticamente

## Integração com o visualizador

### Filtro por pessoa

- O menu suspenso mostra as pessoas com miniaturas de rostos
- Filtre a galeria por pessoa

### Galeria de pessoa

- Clique em uma pessoa no menu suspenso para ver todas as suas fotos
- Clicar em uma pessoa aplica um filtro `person_id` à galeria (não há rota dedicada por pessoa)

### Página Gerenciar pessoas

Acesse pelo botão no cabeçalho ou por `/persons`:

- **Visualização em grade** - Todas as pessoas reconhecidas
- **Mesclar** - Selecione a origem, clique no destino, confirme
- **Mesclagem em lote** - Selecione várias pessoas e mescle em um único destino
- **Dividir** - Mova os rostos selecionados para uma nova pessoa
- **Ocultar** - Exclua um cluster da lista, dos filtros e das sugestões de mesclagem
- **Excluir** - Remova o cluster de pessoa
- **Renomear** - Clique no nome para editar diretamente

### Criar uma pessoa

As pessoas não vêm mais apenas do agrupamento — você pode nomear um rosto que o agrupador não
capturou diretamente pela galeria:

1. Em um cartão de foto, abra as ações de pessoa e escolha um rosto não atribuído.
2. No seletor de pessoa, escolha **Criar nova pessoa** e digite um nome.
3. O rosto é vinculado à nova pessoa (criada manualmente, `auto_clustered = 0`) em uma única
   chamada.

Endpoint: `POST /api/persons` (somente edição), corpo
`{ "name": "<nome>", "face_ids": [<id>, ...] }`. O nome é obrigatório (não vazio após remover
espaços). Rostos que já pertencem a outra pessoa são reatribuídos, e qualquer pessoa antiga que
fique sem rostos é excluída — a mesma semântica da atribuição de rosto. No modo multiusuário, quem
chama só pode vincular rostos de fotos dentro dos próprios diretórios (ou compartilhados); um rosto
fora desse escopo é rejeitado como não encontrado.

### Precisa de nome

A página Gerenciar pessoas mostra as pessoas agrupadas automaticamente que valem a pena nomear em
uma seção **Precisa de nome**: clusters sem nome (`name IS NULL`, `auto_clustered = 1`) com pelo
menos `viewer.persons.needs_naming_min_faces` rostos (padrão `5`), cada um com um campo de nome em
linha para que clusters grandes possam ser nomeados sem precisar procurá-los. Servido por
`GET /api/persons/needs_naming?min_faces=N`.

### Página Sugestões de mesclagem

Acesse por `/merge-suggestions` ou pelo botão "Sugestões de mesclagem" na página Gerenciar pessoas:

- Mostra pares de pessoas com embeddings de rostos semelhantes que podem ser o mesmo indivíduo
- **Controle deslizante de limiar** — controla o corte de similaridade (mais baixo = mais sugestões)
- **Mesclagem com um clique** — mescle um par sugerido instantaneamente
- **Mesclagem em lote** — selecione várias sugestões e mescle todas de uma vez

### Cartões de foto

- Pequenas miniaturas de rostos (avatares) exibidas para pessoas reconhecidas
- Configurável via `viewer.face_thumbnails.output_size_px`

## Marcador de espaço de embedding (segurança do modelo de reconhecimento)

Cada linha de rosto carrega uma tag `embedding_model` (coluna na tabela `faces`, padrão
`arcface_buffalo_l` — o modelo de reconhecimento atual do InsightFace `buffalo_l` / ArcFace `w600k_r50`).
Embeddings produzidos por modelos de reconhecimento **diferentes** vivem
em **espaços vetoriais incompatíveis** e nunca devem ser agrupados juntos — fazê-lo
produz silenciosamente pessoas inválidas sem gerar erro algum.

Por isso, `FaceClusterer.load_embeddings()` carrega apenas o espaço de embedding **ativo**
(`ACTIVE_EMBEDDING_MODEL` em `faces/clusterer.py`; uma tag `NULL` é tratada
como o espaço ArcFace legado) e registra um aviso explícito se houver rostos de qualquer outro
espaço presentes e excluídos. Esta é uma salvaguarda de compatibilidade futura: ela torna uma
futura troca de modelo de reconhecimento segura por construção.

### Trocando o modelo de reconhecimento (por exemplo, AdaFace) — plano adiado

Um aprimoramento de qualidade como o **AdaFace** (margem adaptativa por qualidade, melhor agrupamento
de rostos borrados/espontâneos) é integrável como um backend opcional de 512 dimensões (mesmo caminho
de armazenamento, mesmo HDBSCAN), mas **ainda não está implementado** porque não pode ser
validado sem dados reais. Fazê-lo corretamente exige:

1. **Pesos + backbone** — um checkpoint AdaFace (por exemplo, `adaface_ir101_webface12m`)
   mais seu backbone IResNet; um novo download para o cache de modelos.
2. **Recortes alinhados** — calcular o embedding a partir de um recorte alinhado de 112×112 via
   `norm_crop(img, face.kps, 112)` no momento da extração (os kps existem no objeto
   `face` do InsightFace, mas não são persistidos, então o AdaFace não pode ser preenchido offline —
   ele deve ser executado durante a extração). Verifique se BGR/normalização correspondem ao checkpoint.
3. **Chave de configuração** — adicionar `face_detection.recognition_model: arcface|adaface`
   e resolver `ACTIVE_EMBEDDING_MODEL` a partir dela; marcar os novos rostos conforme apropriado.
4. **Reextração + reagrupamento completos** — `--extract-faces-gpu-force` e depois
   `--cluster-faces-force`, porque os embeddings do ArcFace e do AdaFace não são
   comparáveis. O marcador de espaço de embedding acima impede que um banco de dados parcialmente migrado
   agrupe silenciosamente os dois espaços juntos (ele avisa e exclui, em vez disso).
5. **Validação de qualidade** — medir a qualidade dos clusters em relação a identidades rotuladas;
   "executa e emite vetores de 512 dimensões" não prova que o pré-processamento está correto.

## Solução de problemas

| Problema | Solução |
|-------|----------|
| O agrupamento trava | Use o algoritmo `boruvka_balltree` |
| Clusters pequenos demais em excesso | Aumente `min_faces_per_person` |
| Rostos não se agrupam | Diminua `merge_threshold` |
| O agrupamento em GPU falha | Verifique a instalação do cuML; use `"never"` para forçar a CPU |
| Miniaturas ausentes | Execute `--refill-face-thumbnails-incremental` |
| Detecção de piscada incorreta | Ajuste `blink_ear_threshold` e execute `--recompute-blinks` |
| Aviso "Excluded N faces from non-active embedding space" | Uma mudança de modelo de reconhecimento deixou embeddings misturados — execute `--extract-faces-gpu-force` e depois `--cluster-faces-force` |
