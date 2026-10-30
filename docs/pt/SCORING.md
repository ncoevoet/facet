# Sistema de Pontuação

> 🌐 [English](../SCORING.md) · [Français](../fr/SCORING.md) · [Deutsch](../de/SCORING.md) · [Italiano](../it/SCORING.md) · [Español](../es/SCORING.md) · **Português** · [简体中文](../zh/SCORING.md)

As fotos são classificadas em uma categoria e, em seguida, pontuadas com os pesos dessa categoria.

Os valores ausentes ou NULL de subject_sharpness, subject_prominence, subject_placement, bg_separation e face_quality_iqa são excluídos da pontuação ponderada. Apenas o seu peso positivo é redistribuído pelas métricas disponíveis; zero continua válido. Se faltarem todas as entradas ponderadas, usa-se o valor neutro 5.0. As exclusões de licença aplicam-se primeiro. Os pesos predefinidos não mudam. `--optimize-weights` deixa um peso inalterado quando o conjunto de comparações não tem nenhum valor para essa métrica. Para preencher a saliência, execute `--recompute-saliency` e depois `--recompute-average`.

## Como a Pontuação Funciona

1. **Detecção de Categoria** - A foto é analisada quanto ao conteúdo (rostos, tags, dados EXIF)
2. **Avaliação de Filtros** - As categorias são avaliadas em ordem de prioridade até que uma corresponda (um [contexto de pontuação](#contextos-de-pontuação) pode alterar isso por álbum ou foto)
3. **Aplicação de Pesos** - Pesos específicos da categoria são aplicados às métricas
4. **Aplicação de Modificadores** - Bônus, penalidades e flags de comportamento são aplicados
5. **Pontuação Final** - Soma ponderada limitada ao intervalo de 0 a 10

## Categorias

`scoring_config.json` define 34 categorias (33 nomeadas mais `default`), avaliadas em ordem crescente de prioridade até que uma corresponda. A menor prioridade vence. A lista completa está no array `categories`; as principais são:

| Prioridade | Categoria | Método de Detecção |
|----------|----------|------------------|
| 8 | `art` | Tags: painting, statue, drawing, cartoon, anime |
| 10 | `astro` | Tags: aurora, astrophotography, stars, milky way, E luminância média ≤ 0.30 |
| 15 | `concert` | Tags: concert |
| 35 | `group_portrait` | Proporção de rosto ≥ 5% E is_group_portrait |
| 42 | `silhouette` | Tem rosto E `is_silhouette` (o maior rosto é escuro contra um entorno mais claro) |
| 45 | `portrait` | Proporção de rosto ≥ 5%, não silhueta/grupo/mono |
| 46 | `portrait_bw` | Retrato monocromático (rosto ≥ 5%) |
| 55 | `macro` | Tags: macro, insect, butterfly, dewdrop, ... |
| 65 | `wildlife` | Tags: animal, bird, marine, reptile, primate |
| 80 | `long_exposure` | Obturador de 1 a 10 segundos |
| 85 | `night` | Luminância < 0,15 |
| 88 | `monochrome` | is_monochrome (saturação < 5%) |
| 95 | `street` | Tags: street, urban_culture |
| 96 | `human_others` | Tem rosto E proporção de rosto < 5% |
| 100 | `landscape` | Tags: landscape, mountain, beach, forest, ... |
| 999 | `default` | Fallback (sem filtro) |

Outras categorias baseadas em tags incluem `aerial`, `food`, `sports`, `vehicle`, `travel`, `fashion`, `candid`, `product`, `architecture`, `urban`, `golden_hour`, `blue_hour`, `cinematic`, `vintage`, `abstract`, `minimalist`, `dramatic` e `weather`.

Nos perfis com tagging CLIP (`legacy`/`8gb`, e `16gb`/`24gb` quando o seu tagger VLM não roda), uma varredura etiqueta cada foto antes de calcular a sua categoria, de modo que a categoria armazenada usa as tags. Uma execução com um único `--pass NAME` não etiqueta.

**Silhueta.** `is_silhouette` vem de uma regra de pixels baseada no rosto (veja [Filtros Booleanos](#filtros-booleanos)), não de uma tag.

- Com `exposure.silhouette_detection` em `true` (o padrão), o agregado de uma silhueta ignora a penalidade de recorte.
- Uma varredura armazena `exposure_score` com a penalidade de recorte. `--recompute-average` o recalcula sem ela para toda foto marcada `is_silhouette`, seja qual for o valor de `exposure.silhouette_detection`.
- Para rederivar os sinalizadores de uma biblioteca existente, execute `python facet.py --recompute-silhouette` e depois `--recompute-average` duas vezes (veja [COMMANDS.md](COMMANDS.md)).

**Astro.** Uma foto precisa de uma tag astro *e* de uma luminância média de no máximo 0.30 (`luminance_max`). Uma cena clara etiquetada como `aurora` ou `stars` não é astro, e uma foto sem luminância armazenada nunca corresponde. Se o seu `scoring_config.json` tem seu próprio array `categories`, adicione você mesmo `"luminance_max": 0.30` a `astro.filters`; `python facet.py --doctor` avisa quando ele está ausente.

## Contextos de Pontuação

Um **contexto de pontuação** altera a ordem das categorias para algumas fotos sem tocar nas prioridades globais. Ele promove algumas categorias para o início e exclui outras. `default` (`promote`/`excluded` vazios) não altera nada, e as fotos o usam a menos que você atribua outro.

**Ordem efetiva** = `promote` (na ordem informada) → a ordem de prioridade global sem os nomes promovidos e excluídos → `default` por último. Um nome presente tanto em `promote` quanto em `excluded` é removido: `excluded` prevalece.

Presets fornecidos, editáveis pela aba **Contexto de pontuação** do visualizador ou no JSON (referência dos campos: [Contextos de Pontuação](CONFIGURATION.md#contextos-de-pontuação)):

| Contexto | Promove | Exclui |
|---------|----------|----------|
| `default` | — | — |
| `action_stage` | `sports`, `concert`, `candid` | `silhouette` |
| `party_event` | `group_portrait`, `candid`, `food` | — |
| `portrait_session` | `portrait`, `portrait_bw`, `fashion` | — |
| `wildlife` | `wildlife` | — |
| `landscape` | `landscape`, `golden_hour`, `blue_hour` | — |
| `motorsport` | `sports`, `vehicle` | `silhouette` |

Você edita apenas a lista de promovidas (modo de edição; arraste, ou mova para cima/para baixo) e as exclusões. As demais categorias sempre mantêm a ordem global, de modo que uma categoria nova nunca falta em um contexto. Regras de validação: [Editando um Contexto](CONFIGURATION.md#editando-um-contexto).

**Atribuindo um contexto:**

- **Por álbum.** Aplica-se a toda foto que está no álbum agora. É um instantâneo único: as fotos adicionadas depois a um álbum inteligente não o recebem. Veja [Atribuindo um Contexto](CONFIGURATION.md#atribuindo-um-contexto).
- **Por foto.** Uma substituição de categoria persistente para uma única foto.

Ambos sobrevivem a novas varreduras e podem ser removidos separadamente.

**Nenhum dos dois afeta fotos já pontuadas até que você recalcule:** execute `python facet.py --recompute-average` ou recalcule pelo visualizador (veja [Alterar prioridades exige um recálculo](CONFIGURATION.md#reordenando-a-prioridade-global)). Com `normalization.per_category` ativado, execute-o duas vezes (veja [Normalization](CONFIGURATION.md#normalization)).

### A Armadilha dos Dados EXIF Ausentes

Reordenar só muda qual categoria é *tentada primeiro*. Isso não faz os filtros de uma categoria corresponderem. Um filtro de intervalo numérico falha quando o valor da foto está ausente ou ilegível, exatamente como se estivesse fora do intervalo.

Exemplo: `sports` (prioridade 71) tem `shutter_speed_max: 0.02`. Um quadro de dança fotografado mais lento que 1/50s, ou sem velocidade do obturador legível, falha nesse filtro mesmo quando `action_stage` promove `sports` para o início. A foto cai para a próxima correspondência, tipicamente `fashion` (prioridade 43, marcada com a tag `fashion`, tem rosto) ou `silhouette` (prioridade 42, contraluz com rosto).

**Quando uma foto cai em uma categoria inesperada, verifique isto primeiro:** os filtros numéricos da categoria de destino conseguem corresponder aos dados EXIF armazenados da foto, e não apenas às suas tags?

### A Armadilha da Tag Ausente

`required_tags` falha da mesma forma: um filtro não pode corresponder a uma tag ausente do vocabulário. As `required_tags` de `sports` são `sports`, `motion`, `athlete`, `competition`, `action_sport` e `dance`.

`sports.tags.dance` carrega 11 prompts CLIP (`dance performance`, `dancer on stage`, `ballet dancer`, `contemporary dance`, `ballroom dancing`, `latin dance`, `hip hop dance`, `dance competition`, `dance troupe performing`, `dancer mid leap`, `dancer in motion`), e `dance` está em `sports.filters.required_tags`. Uma foto de dança marcada consegue chegar a `sports`, mas uma com obturador lento ou sem EXIF ainda falha em `shutter_speed_max: 0.02`.

**Fotos existentes mantêm as tags que já têm.** Uma mudança de vocabulário só afeta as novas etiquetagens; execute `python facet.py --recompute-tags` para aplicá-la à biblioteca.

### Reordenando a Prioridade Global

Você pode reordenar a prioridade global no visualizador (modo de edição). A reordenação permuta os números de prioridade existentes entre as categorias em vez de renumerar, então os números da tabela acima continuam significativos. `default` (prioridade 999) fica sempre por último. Toda gravação faz primeiro uma cópia com timestamp `.backup.<timestamp>` de `scoring_config.json`.

Reordenar não altera a `category` armazenada de nenhuma foto: execute um recálculo depois.

**Limitação conhecida:** a lista suspensa de tipo da galeria mantém a ordem antiga até o visualizador ser reiniciado. A correspondência e a filtragem usam a nova ordem imediatamente.

## Definição de Categoria

Cada categoria em `scoring_config.json` tem estes componentes:

```json
{
  "name": "portrait",
  "priority": 45,
  "filters": {
    "face_ratio_min": 0.05,
    "has_face": true,
    "is_silhouette": false,
    "is_group_portrait": false,
    "is_monochrome": false
  },
  "weights": {
    "aesthetic_percent": 32,
    "eye_sharpness_percent": 16,
    "face_quality_percent": 14,
    "composition_percent": 12,
    "liqe_percent": 8,
    "exposure_percent": 4,
    "tech_sharpness_percent": 4,
    "color_percent": 4,
    "contrast_percent": 4,
    "aesthetic_iaa_percent": 2
  },
  "modifiers": {
    "bonus": 0.419,
    "_apply_blink_penalty": true,
    "noise_tolerance_multiplier": 0.006,
    "_clipping_multiplier": 0.5
  },
  "tags": {}
}
```

## Referência de Filtros

### Filtros de Intervalo Numérico

| Filtro | Campo | Descrição |
|--------|-------|-------------|
| `face_ratio_min` / `face_ratio_max` | `face_ratio` | Área do rosto como fração (0.0-1.0) |
| `face_count_min` / `face_count_max` | `face_count` | Número de rostos |
| `iso_min` / `iso_max` | `ISO` | ISO da câmera |
| `shutter_speed_min` / `shutter_speed_max` | `shutter_speed` | Tempo de exposição (segundos) |
| `luminance_min` / `luminance_max` | `mean_luminance` | Brilho (0.0-1.0) |
| `focal_length_min` / `focal_length_max` | `focal_length` | Distância focal (mm) |
| `f_stop_min` / `f_stop_max` | `f_stop` | Número f da abertura |

### Filtros Booleanos

| Filtro | Descrição |
|--------|-------------|
| `has_face` | Pelo menos um rosto detectado |
| `is_monochrome` | Saturação < 5% |
| `is_silhouette` | O maior rosto é escuro contra um entorno claro (veja abaixo). Uma foto sem rosto nunca é uma silhueta |
| `is_group_portrait` | face_count >= `min_faces_for_group` (configurável, padrão: 4) |

**Regra de `is_silhouette`.** A luminosidade média (luma, 0-1) dos 60 % centrais da caixa do rosto é inferior a 0.12, e a faixa ao redor da caixa (de 0.2 a 0.75 do tamanho da caixa para fora em cada lado, recortada ao quadro) é mais clara em mais de 0.20. Nem a tag CLIP `silhouette` nem o histograma do quadro inteiro a definem.

### Filtros de Tags

| Filtro | Descrição |
|--------|-------------|
| `required_tags` | Lista de tags que a foto deve ter |
| `excluded_tags` | Lista de tags que a foto NÃO deve ter |
| `tag_match_mode` | `"any"` (padrão) ou `"all"` |

## Chaves de Peso

Todos os pesos usam o sufixo `_percent`. Eles são normalizados por `get_weights()`, portanto os totais não precisam ser exatamente iguais a 100 — mas mantê-los em 100 mantém as pontuações na escala de 0 a 10.

| Chave | Métrica | Origem | Melhor Para |
|-----|--------|--------|----------|
| `aesthetic_percent` | Apelo visual | TOPIQ ou CLIP+MLP | Tudo |
| `quality_percent` | Qualidade legada | Somado a `aesthetic_percent` antes do cálculo (sem sinal separado) | — |
| `face_quality_percent` | Nitidez do rosto | InsightFace | Retratos |
| `eye_sharpness_percent` | Nitidez dos olhos | Landmarks do InsightFace | Retratos |
| `tech_sharpness_percent` | Nitidez geral | Variância do Laplaciano | Paisagens |
| `composition_percent` | Composição | SAMP-Net ou baseada em regras | Tudo |
| `exposure_percent` | Equilíbrio de exposição | Análise de histograma | Tudo |
| `color_percent` | Harmonia de cores | Análise HSV | Fotos coloridas |
| `contrast_percent` | Contraste tonal | Amplitude do histograma | P&B |
| `dynamic_range_percent` | Faixa tonal | Análise de histograma | HDR, paisagens |
| `isolation_percent` | Separação do sujeito | Rosto vs fundo | Retratos, vida selvagem |
| `leading_lines_percent` | Linhas guia | Detecção de bordas | Arquitetura |
| `power_point_percent` | Regra dos terços | Posicionamento do sujeito | Tudo |
| `saturation_percent` | Saturação de cor | Análise HSV | Fotos vibrantes |
| `noise_percent` | Nível de ruído | Estimativa de ruído | Pouca luz |
| `face_sharpness_percent` | Nitidez da região do rosto | Análise de rosto | Retratos |
| `aesthetic_iaa_percent` | Mérito estético artístico | TOPIQ IAA (treinado com AVA) | Arte, criativo |
| `face_quality_iqa_percent` | Qualidade do rosto (IQA) | TOPIQ NR-Face | Retratos |
| `liqe_percent` | Pontuação de qualidade LIQE | LIQE | Diagnósticos |
| `subject_sharpness_percent` | Nitidez da região do sujeito | BiRefNet + Laplaciano | Retratos, vida selvagem |
| `subject_prominence_percent` | Proporção da área do sujeito | BiRefNet | Macro, vida selvagem |
| `subject_placement_percent` | Regra dos terços do sujeito | BiRefNet | Tudo |
| `bg_separation_percent` | Separação do fundo | BiRefNet | Retratos, macro |

**`quality_percent` conta como `aesthetic`.** A métrica de qualidade não tem pontuação própria, então o `quality_percent` de uma categoria é redistribuído para `aesthetic`: ele é somado a `aesthetic_percent` antes do cálculo, e os pesos continuam somando 100. Versões anteriores perdiam essa parcela do agregado; execute `--recompute-average` uma vez após atualizar para recuperá-la. As categorias não mudam.

## Modificadores

Ajustam o comportamento da pontuação por categoria:

| Modificador | Tipo | Descrição |
|----------|------|-------------|
| `bonus` | float | Adicionado à pontuação final (ex.: 0.5) |
| `noise_tolerance_multiplier` | float | Escala a penalidade de ruído (0.5 = metade) |
| `_skip_clipping_penalty` | bool | Pula a penalidade de clipping de exposição |
| `_skip_oversaturation_penalty` | bool | Pula a penalidade de supersaturação |
| `_clipping_multiplier` | float | Escala a penalidade de clipping |
| `_apply_blink_penalty` | bool | Aplica a penalidade de detecção de piscada |

## Dimensões de Saliência do Sujeito

Quatro dimensões derivadas da segmentação de sujeito do BiRefNet:

| Chave de Peso | Métrica | Descrição |
|-----------|--------|-------------|
| `subject_sharpness_percent` | Nitidez do sujeito | Qualidade de foco da região do sujeito vs o fundo. Alta = sujeito nítido, fundo suave. |
| `subject_prominence_percent` | Proeminência do sujeito | Área do sujeito como fração do quadro. Alta para macro e sujeitos com enquadramento fechado, baixa para cenas amplas. |
| `subject_placement_percent` | Posicionamento do sujeito | Pontuação da regra dos terços para o centro de massa do sujeito. |
| `bg_separation_percent` | Separação do fundo | Diferença de gradiente de borda no limite do sujeito (qualidade do bokeh). |

Use `subject_sharpness_percent` e `bg_separation_percent` para retrato/vida selvagem; `subject_prominence_percent` para macro.

**Sem sujeito, sem número.** Quando nenhum sujeito é encontrado, `subject_sharpness`, `subject_placement` e `bg_separation` são armazenados como NULL (assim como `power_point_score` quando não há caixa de sujeito), `subject_prominence` é 0.0 e `subject_bbox` é NULL.

- Os filtros de intervalo da galeria ignoram um NULL (`min_subject_sharpness=0` não devolve uma foto sem sujeito). As estatísticas o deixam de fora das médias e a interface o mostra como ausente.
- As entradas de saliência NULL seguem a regra acima para valores ausentes; os pesos predefinidos não mudam.
- Versões anteriores armazenavam um 5.0 neutro. As linhas existentes o mantêm até que `--recompute-saliency` e `--recompute-composition-cpu` as reescrevam.

**Quando a saliência falha**, nada é gravado; o Facet nunca grava um número neutro no lugar de um resultado com falha. Uma foto que nunca foi pontuada mantém NULL nas cinco colunas de saliência (`subject_sharpness`, `subject_prominence`, `subject_placement`, `bg_separation`, `subject_bbox`), como uma foto varrida antes de a saliência existir. Regras de nova tentativa e de tamanho de lote: [Saliência do Sujeito](COMMANDS.md#saliência-do-sujeito).

## Dimensões Suplementares de IQA

Três modelos de qualidade adicionais:

| Chave de Peso | Modelo | Descrição |
|-----------|-------|-------------|
| `aesthetic_iaa_percent` | TOPIQ IAA | Mérito estético treinado com AVA, distinto da pontuação estética de qualidade técnica. Melhor para categorias de arte/criativas. |
| `face_quality_iqa_percent` | TOPIQ NR-Face | Avaliação de qualidade da região do rosto. Melhor para categorias de retrato. |
| `liqe_percent` | LIQE | Pontuação de qualidade mais um diagnóstico de distorção (motion blur, superexposição, ruído). |

Esses modelos são executados como parte do pipeline de pontuação padrão em todos os perfis, inclusive o perfil `legacy` de CPU (mais lento ali), e compartilham VRAM com o TOPIQ em uma GPU. Adicione suas chaves de peso a qualquer categoria onde a avaliação seja útil.

**Quando um modelo suplementar não consegue pontuar uma foto**, ele grava NULL na coluna desse modelo (`face_quality_iqa`, `liqe_score`, `aesthetic_iaa`, `aesthetic_v25`) em vez de um 5.0 neutro. Isso acontece quando o TOPIQ NR-Face não encontra rosto ou o LIQE recebe um lado menor abaixo de 224 px; o Aesthetic V2.5, quando ativado, pode falhar em qualquer imagem. Um erro de memória da CPU não é repetido com um tamanho de lote menor.

- Um face_quality_iqa NULL segue a regra acima; as outras entradas suplementares NULL mantêm a imputação neutra 5.0.
- **Galeria:** um filtro de intervalo em Estética (IAA), Qualidade do rosto (IQA), LIQE ou Aesthetic V2.5 não inclui uma foto sem pontuação (`min_face_quality_iqa=0` ignora uma foto sem rosto). Uma ordenação crescente por esses campos, Q-ReAlign ou DeQA coloca as fotos sem pontuação por último, na galeria e nos álbuns.
- **Valores neutros 5.0 antigos** permanecem até que `--repair-neutral-iqa` os apague; depois execute `--recompute-iqa` e `--recompute-average`, ou faça uma nova varredura com `--force`.
- **Falha do modelo principal** (TOPIQ nos perfis `16gb` e `24gb`): a foto é registrada como falha em vez de ser gravada com um 5.0 neutro. Uma foto nova é retomada pela próxima varredura; uma já gravada mantém a sua linha e é repetida por `--retry-failed all` (um `--retry-failed` sem argumento cobre apenas a última execução que registrou falhas) ou por outra varredura com `--force`.

Regras de nova tentativa de cada comando: [Modelos de Qualidade Suplementares](COMMANDS.md#modelos-de-qualidade-suplementares).

### Sinais suplementares (não no agregado padrão)

| Coluna | Origem | Descrição |
|--------|--------|-------------|
| `aesthetic_clip` | `analyzers/aesthetic_clip.py` + embedding CLIP/SigLIP em cache | Pontuação estética gratuita (0-10) a partir de embeddings em cache; **não** faz parte do `aggregate` padrão |

`aesthetic_clip` projeta o embedding de cada imagem sobre um "eixo estético" construído a partir de prompts de texto, então não precisa de nenhuma inferência de imagem extra.

- Preencha com `python scripts/compute_aesthetic_clip.py --db <path>`.
- Faça benchmark com `python scripts/benchmark_aesthetic.py --db <path> --ava AVA.txt --photo-dir <dir>`.
- AVA SRCC ≈ 0,52 no conjunto `ava_test/` de 500 fotos (vs 0,94 para `aesthetic_iaa`). Use-o como pré-filtro barato ou quando o TOPIQ-IAA não está disponível.

## Tags de Categoria (Vocabulário CLIP)

As tags acionam categorias baseadas em tags e são correspondidas usando similaridade CLIP:

```json
{
  "tags": {
    "landscape": ["landscape", "scenic view", "nature scene"],
    "mountain": ["mountain", "alpine", "peaks"],
    "beach": ["beach", "ocean", "seaside", "coastal"]
  }
}
```

Cada chave é o nome canônico da tag, e o array contém os sinônimos para correspondência CLIP.

## Pontuação de Top Picks

O filtro "Top Picks" do visualizador usa uma pontuação ponderada personalizada:

```json
"top_picks_weights": {
  "aggregate_percent": 30,
  "aesthetic_percent": 28,
  "composition_percent": 18,
  "face_quality_percent": 24
}
```

**Cálculo da pontuação:**
- Com rosto (face_ratio ≥ 20%): As quatro métricas contribuem
- Sem rosto: `face_quality_percent` é redistribuído uniformemente (metade para cada) para `aesthetic` e `composition` (com os pesos padrão: aesthetic 0.40, composition 0.30)

## Considerações sobre Perfis de VRAM

Os pesos padrão são otimizados para **TOPIQ** (0,93 SRCC), o modelo estético de todos os perfis.

| Perfil | Modelo Estético | Embeddings | Tagger | Recomendações |
|---------|-----------------|-----------|--------|-----------------|
| `24gb` | TOPIQ (0,93 SRCC) | SigLIP 2 NaFlex SO400M | Qwen3.5-4B | Melhor precisão, pesos padrão |
| `16gb` | TOPIQ (0,93 SRCC) | SigLIP 2 NaFlex SO400M | Qwen3.5-2B | Pesos padrão |
| `8gb` | CLIP+MLP (0,76 SRCC) | CLIP ViT-L-14 | Similaridade CLIP | Pesos padrão funcionam bem |
| `legacy` | CLIP+MLP na CPU | CLIP ViT-L-14 | Similaridade CLIP | Pesos padrão, mais lento |

Todos os perfis, inclusive o perfil `legacy` de CPU, executam adicionalmente modelos PyIQA suplementares (TOPIQ IAA, TOPIQ NR-Face, LIQE) e, opcionalmente, BiRefNet_dynamic para saliência do sujeito.

Execute `--compute-recommendations` após trocar de perfil para analisar as distribuições de pontuação.

## Fluxo de Ajuste de Pesos

### Opção A: Pelo Visualizador (Recomendado)

1. Abra `/stats` → aba **Categories** → sub-aba **Weights**
2. Desbloqueie o modo de edição
3. Selecione uma categoria no menu suspenso do editor
4. Ajuste os controles deslizantes — a **Pré-visualização de Distribuição de Pontuação** ao vivo mostra o impacto estimado
5. Clique em **Save** e depois em **Recompute Scores** para aplicar

O visualizador executa `--recompute-category` nos bastidores, atualizando apenas as fotos dessa categoria.

Um assistente MCP pode ler estes pesos e simular uma alteração sem tocar em nada: `explain_score` (porque uma foto obteve a sua pontuação), `category_weights` e `preview_weights` (uma pré-visualização aproximada com as mudanças de posição). Ver [Pontuações e pesos](AGENTS.md#pontuações-e-pesos).

### Opção B: Pela CLI

#### 1. Analisar as Pontuações Atuais

```bash
python facet.py --compute-recommendations
```

Mostra:
- Distribuições de pontuação por categoria
- Análise de correlação de pesos
- Ajustes sugeridos

#### 2. Ajustar os Pesos

Edite os pesos de categoria em `scoring_config.json`. Certifique-se de que somem 100.

#### 3. Recalcular as Pontuações

```bash
python facet.py --recompute-average               # Todas as categorias
python facet.py --recompute-category portrait      # Categoria única (mais rápido)
```

Usa os embeddings armazenados - não precisa de GPU.

#### 4. Validar as Mudanças

```bash
python facet.py --compute-recommendations
```

Compare as distribuições antes/depois.

## Modo de Comparação Pareada

Treine os pesos comparando pares de fotos:

### Configuração

1. Defina um `edition_password` não vazio na configuração: `"viewer": { "edition_password": "your-password" }`
2. Inicie o visualizador: `python viewer.py`
3. Clique no botão "Compare"

### Interface de Comparação

- Fotos lado a lado
- Teclado: ← (esquerda vence), → (direita vence), T (empate), S (pular). Os botões na tela são rotulados **A** / **B**.
- A barra de progresso mostra as comparações em direção ao mínimo de 50

### Origens de Comparação

Cada comparação tem um `source`, que o otimizador pondera pela confiabilidade:

- `vote` — votos A/B explícitos da interface de comparação
- `culling` — das decisões de seleção de burst/similares: cada
  foto rejeitada é pareada com até duas fotos mantidas do seu grupo
  (no máximo 12 pares por grupo). As fotos mantidas vencem. Votos explícitos no mesmo
  par nunca são sobrescritos.
- `rating` — pares sintéticos a partir de classificações por estrelas e favoritos

Assim, revisar grupos de burst no visualizador também aumenta o conjunto de treinamento.

### Otimização de Pesos

```bash
# Verificar as estatísticas de comparação
python facet.py --comparison-stats

# Otimizar pesos a partir de comparações (aplicado apenas se generalizar)
python facet.py --optimize-weights --optimize-category portrait

# Restringir os dados de treinamento a origens específicas
python facet.py --optimize-weights --optimize-category portrait --optimize-sources vote,culling

# Aplicar mesmo que o gate de dados retidos não seja atingido
python facet.py --optimize-weights --optimize-category portrait --optimize-force

# Aplicar a todas as fotos
python facet.py --recompute-average
```

### Pipeline de Rótulo para Peso

Além dos votos A/B, dois fluxos de rótulos alimentam o otimizador:

1. **Decisões de seleção** são capturadas em cada confirmação de
   burst/similares (`source='culling'`).
2. **Classificações por estrelas, favoritos e rejeições** viram pares
   sintéticos com `python facet.py --sync-label-comparisons` (`source='rating'`).
   Reexecutar resincroniza a partir dos rótulos atuais, de modo que classificações retiradas desaparecem.

**Como o ajuste funciona.** O otimizador encontra os pesos que melhor preveem o vencedor de cada comparação (um modelo de Bradley-Terry).

- As fontes contam pela confiabilidade: vote 1.0, rating 0.7, culling 0.5.
- Um **empate** conta como meia vitória e meia derrota.
- O ajuste é **ancorado nos seus pesos atuais**: com poucas comparações ele fica perto deles.
- Usa as mesmas métricas 0-10 do agregado (incluindo `liqe`, `aesthetic_iaa`, `face_quality_iqa` e a saliência do sujeito), com nitidez dos olhos, nitidez técnica e cor normalizadas pelos percentis que o último `--recompute-average` salvou.
- `quality_percent` é somado a `aesthetic`, como o pontuador faz; a aplicação grava `quality_percent: 0`.

**Os pesos só são aplicados se generalizarem.** A decisão usa comparações reservadas: validação cruzada de 5 dobras com **dobras agrupadas por foto** (nenhuma foto está ao mesmo tempo nos pares de treino e nos pares reservados).

- Um **teste exato de McNemar unilateral** verifica se os novos pesos acertam significativamente mais dos pares em que os dois conjuntos de pesos discordam.
- Os pesos só são aplicados quando `p < 0.05` **e** o ganho reservado é de pelo menos 2 pontos percentuais. Caso contrário, a execução registra os números e não grava nada.
- Passe `--optimize-force` para aplicar mesmo assim. Se o teste não puder ser executado (poucos grupos independentes de fotos), nada é aplicado a menos que seja forçado.
- Cada categoria precisa de pelo menos 30 comparações **decisivas** (uma foto venceu) **naquela categoria**. Empates e outras categorias não contam.

O log mostra, por exemplo:

```
Held-out accuracy:      69.2% +/- 4.0 (5-fold, photo-grouped) - the honest estimate
Held-out gain:          +8.5 pp over the current weights on the same 389 pairs
McNemar (one-sided):    p = 0.0006 (only the fit right: 66, only the current weights right: 33)
NOT applying: the held-out gate needs p < 0.05 and a gain of at least 2.0 pp. ...   (logged when the gate fails)
```

**Aplicar mantém o nível da categoria.** `--optimize-weights` muda como as fotos da categoria se ordenam entre si, não em relação às outras categorias. Ele desloca `modifiers.bonus` para cancelar o deslocamento médio da pontuação da categoria.

- O bônus é mantido dentro de [-5, 5]; o log avisa quando esse limite se aplica.
- Uma categoria sem entrada em `categories` (`others`) não tem bônus e não é recentrada.
- Restaurar um instantâneo de pesos restaura pesos **e** bônus. Instantâneos mais antigos, os de `calibrate.py` e os de `others` deixam o bônus intacto.
- O botão **Aplicar** do visualizador e as edições manuais na aba Pesos não recentram o bônus; só `--optimize-weights` o faz.

**Após atualizar, retreine o ranker pessoal e a head keeper (`--train-ranker`, `--train-keeper`), depois execute `--recompute-average`.** Eles agora leem a nitidez dos olhos, a nitidez técnica e a cor normalizadas por percentis, e um modelo salvo por uma versão anterior não consegue detectar a mudança.

Cadência recomendada:

```bash
python facet.py --mine-insights          # que sinal existe, drift, saúde
python facet.py --sync-label-comparisons # atualizar pares derivados de classificações
python facet.py --optimize-weights       # aprender pesos de todas as origens
python facet.py --recompute-average      # aplicar + persistir snapshot de percentil
```

### Ajuste de Pesos na UI

Durante a comparação, o painel Weight Preview mostra as mudanças de pontuação conforme você move os controles deslizantes, e **Suggest Weights** propõe valores otimizados. Salvar e recalcular funcionam como na [Opção A: Pelo Visualizador](#opção-a-pelo-visualizador-recomendado).

**Sugerir pesos** mostra dois números, na aba Sugestões de Pesos e na barra lateral da Comparação A/B:

- `accuracy_before`: com que frequência os pesos atuais preveem o vencedor dos pares rotulados desta categoria.
- `accuracy_after`: o mesmo para os pesos sugeridos. É medido nos pares em que foram ajustados, então é otimista.

**Aplicar** só é oferecido quando passa o mesmo teste de McNemar reservado da CLI (`suggest_changes` é verdadeiro). A validação cruzada só é executada quando o ganho otimista chega a 2 pontos percentuais (`?use_cv=true` a executa sempre). O visualizador exige `min_comparisons_for_optimization` (padrão 50) comparações decisivas na categoria, enquanto a CLI exige 30. Abaixo disso informa «Need at least N decisive comparisons (have K)».

## Adicionando Categorias Personalizadas

```json
{
  "name": "underwater",
  "priority": 62,
  "filters": {
    "required_tags": ["underwater"],
    "tag_match_mode": "any"
  },
  "weights": {
    "aesthetic_percent": 40,
    "color_percent": 25,
    "composition_percent": 20,
    "exposure_percent": 15
  },
  "modifiers": {
    "noise_tolerance_multiplier": 0.3,
    "bonus": 0.5
  },
  "tags": {
    "underwater": ["underwater", "scuba", "diving", "ocean"],
    "fish": ["fish", "coral", "reef"]
  }
}
```

Adicione ao array `categories` em `scoring_config.json`, então execute `--recompute-average` (ou `--recompute-category underwater` apenas para a nova categoria).

## Exemplos de Fluxo

### Ajustar a Categoria Concert

```bash
# Edit scoring_config.json:
# Find "concert" category, adjust:
#   "noise_tolerance_multiplier": 0.05
#   "exposure_percent": 5

python facet.py --recompute-category concert
```

Ou use o editor de pesos do visualizador em `/stats` → Categories → Weights para pré-visualização ao vivo e recálculo com um clique.

### Mudar para o Perfil 8gb

```bash
# Edit: "vram_profile": "8gb"
python facet.py --compute-recommendations  # Analyze
# Reduce aesthetic_percent in categories if needed
python facet.py --recompute-average
```

### Adicionar a Categoria Underwater

1. Adicione a definição da categoria (veja acima)
2. Execute `python facet.py --validate-categories`
3. Execute `python facet.py --recompute-average`
