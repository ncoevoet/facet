# Sistema de Pontuação

> 🌐 [English](../SCORING.md) · [Français](../fr/SCORING.md) · [Deutsch](../de/SCORING.md) · [Italiano](../it/SCORING.md) · [Español](../es/SCORING.md) · **Português**

As fotos são classificadas em uma categoria e, em seguida, pontuadas com os pesos dessa categoria.

## Como a Pontuação Funciona

1. **Detecção de Categoria** - A foto é analisada quanto ao conteúdo (rostos, tags, dados EXIF)
2. **Avaliação de Filtros** - As categorias são avaliadas em ordem de prioridade até que uma corresponda (um *contexto de pontuação* pode promover/excluir categorias por álbum ou foto sem alterar a ordem base — veja [Contextos de Pontuação](#contextos-de-pontuação))
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

## Contextos de Pontuação

A ordem de prioridade acima é global — toda foto é avaliada contra a mesma lista. Um **contexto de pontuação** é um *delta* nomeado sobre essa ordem base: ele promove uma lista curta de categorias para o início e exclui outras completamente, sem renumerar nada. `default` (`promote`/`excluded` vazios) é o contexto neutro (no-op), então nada muda para uma foto a menos que um contexto seja explicitamente atribuído a ela.

**Ordem efetiva** = `promote` (na ordem informada) → a ordem de prioridade global com os nomes promovidos e excluídos removidos → `default` por último. Um nome presente tanto em `promote` quanto em `excluded` é removido inteiramente — `excluded` prevalece. `ScoringConfig.resolve_context_order()` (`config/scoring_config.py`) calcula e armazena em cache esse resultado uma vez por nome de contexto.

Presets fornecidos — editáveis pela aba **Contexto de pontuação** do visualizador (`PUT /api/config/scoring_contexts/{name}`, protegido por edition) ou diretamente no JSON; veja [Contextos de Pontuação](CONFIGURATION.md#contextos-de-pontuação) para a referência completa dos campos:

| Contexto | Promove | Exclui |
|---------|----------|----------|
| `default` | — | — |
| `action_stage` | `sports`, `concert`, `candid` | `silhouette` |
| `party_event` | `group_portrait`, `candid`, `food` | — |
| `portrait_session` | `portrait`, `portrait_bw`, `fashion` | — |
| `wildlife` | `wildlife` | — |
| `landscape` | `landscape`, `golden_hour`, `blue_hour` | — |
| `motorsport` | `sports`, `vehicle` | `silhouette` |

Apenas o *delta* é editável — arraste a cabeça promovida para a ordem desejada, alterne a exclusão de uma categoria — nunca uma ordenação completa e independente por contexto: as categorias não promovidas sempre mantêm a ordem de prioridade global, então uma categoria adicionada depois nunca pode faltar silenciosamente em seis listas separadas. Veja [Editando um Contexto](CONFIGURATION.md#editando-um-contexto) para as regras de validação.

Um contexto é atribuído por álbum (`PUT /api/albums/{id}/scoring_context`, que o materializa em cada foto que é membro naquele momento — para um álbum inteligente, um instantâneo, não uma assinatura, veja [Contextos de Pontuação](CONFIGURATION.md#contextos-de-pontuação)) ou, para uma única foto teimosa, aplicado como uma substituição de categoria persistente (`POST /api/comparison/override_category`). Ambas as alavancas persistem em uma tabela auxiliar `photo_scoring_overrides`, em vez de como colunas em `photos` — `save_photo`/`save_photos_batch` gravam linhas de foto com `INSERT OR REPLACE`, o que apagaria silenciosamente uma nova coluna nessa linha na próxima nova varredura. Definir uma alavanca não afeta a outra, e cada uma pode ser removida independentemente. **Nenhuma das duas entra em vigor em fotos já pontuadas até um recálculo** — `python facet.py --recompute-average`, ou `POST /api/scan/recompute` a partir do visualizador (protegido entre processos contra dois rodando ao mesmo tempo — veja [Alterar prioridades exige um recálculo](CONFIGURATION.md#reordenando-a-prioridade-global)). Se `normalization.per_category` estiver ativado, execute o recálculo duas vezes — veja [Normalization](CONFIGURATION.md#normalization) para entender por que a primeira passagem normaliza em relação à categoria antiga de cada foto.

### A Armadilha dos Dados EXIF Ausentes

Reordenar — seja editando a prioridade global, seja promovendo via um contexto — só muda qual categoria é *tentada primeiro*. Isso não pode fazer os filtros de uma categoria corresponderem a uma foto que de outra forma não corresponderiam. `config/category_filter.py:122-128` falha um filtro de intervalo numérico completamente sempre que o valor subjacente da foto está ausente ou não pode ser interpretado, em vez de pular apenas esse limite — um valor ausente e um valor fora do intervalo são tratados de forma idêntica, e a categoria é descartada de qualquer forma.

Concretamente: `sports` (prioridade 71) carrega `shutter_speed_max: 0.02`. Um quadro de dança fotografado mais lento que 1/50s, ou sem nenhuma velocidade do obturador EXIF legível, falha nesse filtro não importa onde `sports` esteja na ordem de avaliação — mesmo promovida para o início por um contexto como `action_stage`. A foto cai para o que corresponder em seguida, tipicamente `fashion` (prioridade 43, marcada com a tag `fashion`, tem rosto) ou `silhouette` (prioridade 42, contraluz com rosto). **Esta é a coisa mais útil a verificar quando uma foto cai em uma categoria inesperada:** antes de reordenar ou promover qualquer coisa, confirme que os filtros numéricos da categoria de destino realmente conseguem corresponder aos dados EXIF armazenados da foto, não apenas às suas tags.

### Reordenando a Prioridade Global

`GET/POST /api/config/category_priorities` (protegido por edition) lê e reescreve a ordem base sobre a qual todo contexto aplica seu delta. `POST` recebe `{"order": [name, ...]}` — uma permutação com o mesmo conjunto de todo nome de categoria não-`default` — e **permuta os valores de prioridade existentes para a nova ordem** em vez de renumerar (10/20/30/…): o multiconjunto de prioridades permanece inalterado, então os números na tabela acima continuam significativos e a unicidade se mantém por construção. `default` (prioridade 999) fica fixado por último e é excluído da reordenação. Toda gravação faz primeiro uma cópia com timestamp `.backup.<timestamp>` de `scoring_config.json`; este gravador e o editor de pesos (`update_category_weights`) agora compartilham um único lock, já que o antigo read-modify-write sem proteção permitia que um salvamento concorrente de cada um descartasse silenciosamente as mudanças do outro.

Reordenar, por si só, não altera a `category` armazenada de nenhuma foto — execute um recálculo depois (`--recompute-average` ou `POST /api/scan/recompute`) para aplicar a mudança.

**Limitação conhecida:** `api/types.py` monta a lista suspensa de tipo/filtro da galeria a partir de `ScoringConfig.get_categories()` uma única vez, no momento da importação. Uma reordenação de prioridade é aplicada imediatamente para a correspondência real de categorias (toda chamada de pontuação e recálculo relê a configuração do disco), mas a lista suspensa de tipo da galeria mantém sua ordem antiga até o processo do visualizador ser reiniciado. A filtragem em si não é afetada — reordenar não adiciona nem remove nomes de categoria.

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
