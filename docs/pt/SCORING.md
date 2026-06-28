# Sistema de Pontuação

> 🌐 [English](../SCORING.md) · [Français](../fr/SCORING.md) · [Deutsch](../de/SCORING.md) · [Italiano](../it/SCORING.md) · [Español](../es/SCORING.md) · **Português**

As fotos são classificadas em uma categoria e, em seguida, pontuadas com os pesos dessa categoria.

## Como a Pontuação Funciona

1. **Detecção de Categoria** - A foto é analisada quanto ao conteúdo (rostos, tags, dados EXIF)
2. **Avaliação de Filtros** - As categorias são avaliadas em ordem de prioridade até que uma corresponda
3. **Aplicação de Pesos** - Pesos específicos da categoria são aplicados às métricas
4. **Aplicação de Modificadores** - Bônus, penalidades e flags de comportamento são aplicados
5. **Pontuação Final** - Soma ponderada limitada ao intervalo de 0 a 10

## Categorias

`scoring_config.json` define 34 categorias (33 nomeadas mais `default`), avaliadas em ordem crescente de prioridade até que uma corresponda. A menor prioridade vence. A lista completa fica no array `categories`; as principais são:

| Prioridade | Categoria | Método de Detecção |
|----------|----------|------------------|
| 8 | `art` | Tags: painting, statue, drawing, cartoon, anime |
| 10 | `astro` | Tags: aurora, astrophotography, stars, milky way |
| 15 | `concert` | Tags: concert |
| 35 | `group_portrait` | Proporção de rosto ≥ 5% E is_group_portrait |
| 42 | `silhouette` | Tem rosto E is_silhouette |
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
| `is_silhouette` | Contraluz com sombras/altas-luzes intensas |
| `is_group_portrait` | face_count >= `min_faces_for_group` (configurável, padrão: 4) |

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
| `quality_percent` | Qualidade legada | Redistribuída em `aesthetic` (sem sinal separado) | — |
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

## Modificadores

Ajustam o comportamento da pontuação por categoria:

| Modificador | Tipo | Descrição |
|----------|------|-------------|
| `bonus` | float | Adicionado à pontuação final (ex.: 0.5) |
| `noise_tolerance_multiplier` | float | Escala a penalidade de ruído (0.5 = metade) |
| `iso_tolerance_multiplier` | float | Escala a penalidade de ISO |
| `min_saturation_bonus` | float | Bônus para alta saturação |
| `contrast_bonus` | float | Bônus para alto contraste |
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

## Dimensões Suplementares de IQA

Três modelos de qualidade adicionais:

| Chave de Peso | Modelo | Descrição |
|-----------|-------|-------------|
| `aesthetic_iaa_percent` | TOPIQ IAA | Mérito estético treinado com AVA, distinto da pontuação estética de qualidade técnica. Melhor para categorias de arte/criativas. |
| `face_quality_iqa_percent` | TOPIQ NR-Face | Avaliação de qualidade da região do rosto. Melhor para categorias de retrato. |
| `liqe_percent` | LIQE | Pontuação de qualidade mais um diagnóstico de distorção (motion blur, superexposição, ruído). |

Esses modelos são executados como parte do pipeline de pontuação padrão em todos os perfis de GPU (8gb/16gb/24gb) e compartilham VRAM com o TOPIQ; o perfil legado de CPU os ignora. Adicione suas chaves de peso a qualquer categoria onde a avaliação seja útil.

### Sinais suplementares (não no agregado padrão)

| Coluna | Origem | Descrição |
|--------|--------|-------------|
| `aesthetic_clip` | `analyzers/aesthetic_clip.py` + embedding CLIP/SigLIP em cache | Uma pontuação estética suplementar gratuita (0-10) derivada de embeddings de imagem em cache, projetando-os sobre um "eixo estético" construído a partir de prompts de texto positivos/negativos. Zero inferência de imagem extra no momento da varredura. **Não** faz parte do `aggregate` padrão. Preencha com `python scripts/compute_aesthetic_clip.py --db <path>`. Faça benchmark com `python scripts/benchmark_aesthetic.py --db <path> --ava AVA.txt --photo-dir <dir>`. AVA SRCC ≈ 0,52 no conjunto `ava_test/` de 500 fotos (vs 0,94 para `aesthetic_iaa`) — útil como um pré-filtro barato ou quando o TOPIQ-IAA não está disponível. |

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

Todos os perfis de GPU (8gb/16gb/24gb) executam adicionalmente modelos PyIQA suplementares (TOPIQ IAA, TOPIQ NR-Face, LIQE) e, opcionalmente, BiRefNet_dynamic para saliência do sujeito; o perfil legado de CPU os ignora.

Execute `--compute-recommendations` após trocar de perfil para analisar as distribuições de pontuação.

## Fluxo de Ajuste de Pesos

### Opção A: Pelo Visualizador (Recomendado)

1. Abra `/stats` → aba **Categories** → sub-aba **Weights**
2. Desbloqueie o modo de edição
3. Selecione uma categoria no menu suspenso do editor
4. Ajuste os controles deslizantes — a **Pré-visualização de Distribuição de Pontuação** ao vivo mostra o impacto estimado
5. Clique em **Save** e depois em **Recompute Scores** para aplicar

O visualizador executa `--recompute-category` nos bastidores, atualizando apenas as fotos dessa categoria.

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
- Teclado: ← (esquerda vence), → (direita vence), T (empate), S (pular). Os botões na tela ainda são rotulados como **A** / **B** (os valores enviados), mas as teclas são ArrowLeft/ArrowRight.
- A barra de progresso mostra as comparações em direção ao mínimo de 50

### Origens de Comparação

As comparações carregam um marcador `source` para que o otimizador possa ponderá-las pela confiabilidade:

- `vote` — votos A/B explícitos da interface de comparação
- `culling` — derivado automaticamente das decisões de seleção de burst/similares: cada
  foto rejeitada é pareada contra até duas fotos mantidas do mesmo grupo
  (limitado a 12 pares por grupo). As fotos mantidas vencem. Votos explícitos no mesmo
  par nunca são sobrescritos.
- `rating` — pares sintéticos gerados a partir de classificações por estrelas e favoritos

Revisar grupos de burst no visualizador, portanto, aumenta o conjunto de treinamento para
a otimização de pesos sem nenhum esforço extra.

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

Além dos votos A/B explícitos, mais dois fluxos de rótulos alimentam o otimizador:

1. **Decisões de seleção** são capturadas automaticamente em cada confirmação de
   burst/similares (`source='culling'`).
2. **Classificações por estrelas, favoritos e rejeições** são materializados em pares
   sintéticos com `python facet.py --sync-label-comparisons` (`source='rating'`).
   Reexecutar resincroniza a partir dos rótulos atuais, de modo que classificações retiradas desaparecem.

O otimizador pondera cada origem pela confiabilidade (vote 1.0, rating 0.7,
culling 0.5) ao maximizar a verossimilhança de Bradley-Terry. Ele treina sobre o
vetor exato de métricas de 0 a 10 que o pontuador usa (incluindo `liqe`, `aesthetic_iaa`,
`face_quality_iqa` e as métricas de saliência do sujeito), de modo que os pesos otimizados se mapeiam
diretamente para a pontuação em produção.

Os pesos são **aplicados apenas se generalizarem**: os pesos finais são ajustados sobre
todas as comparações, mas a decisão de gravá-los é condicionada à acurácia k-fold em dados
retidos, não à acurácia de treinamento. Se o ganho em dados retidos sobre os pesos atuais
estiver abaixo do limite (padrão 2 pp), a execução reporta os números e não grava
nada — passe `--optimize-force` para sobrepor. A otimização é por categoria e
precisa de comparações rotuladas **para aquela categoria**; categorias sem votos
não podem ser ajustadas a partir de dados.

Cadência recomendada:

```bash
python facet.py --mine-insights          # que sinal existe, drift, saúde
python facet.py --sync-label-comparisons # atualizar pares derivados de classificações
python facet.py --optimize-weights       # aprender pesos de todas as origens
python facet.py --recompute-average      # aplicar + persistir snapshot de percentil
```

### Ajuste de Pesos na UI

Durante a comparação, o painel Weight Preview permite ajustar os controles deslizantes para
mudanças de pontuação em tempo real e clicar em "Suggest Weights" para valores otimizados.
Este é o mesmo fluxo de controles deslizantes no visualizador descrito em
[Opção A: Pelo Visualizador](#opção-a-pelo-visualizador-recomendado) acima — consulte lá
para o fluxo completo de salvar/recalcular.

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
