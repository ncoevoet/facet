# Referência de Configuração

> 🌐 [English](../CONFIGURATION.md) · [Français](../fr/CONFIGURATION.md) · [Deutsch](../de/CONFIGURATION.md) · [Italiano](../it/CONFIGURATION.md) · [Español](../es/CONFIGURATION.md) · **Português** · [简体中文](../zh/CONFIGURATION.md)

Cada configuração é distribuída em `config/scoring_config.default.json`. O seu próprio `scoring_config.json` a sobrescreve chave por chave — veja [Padrões e Seu Override](#padrões-e-seu-override). Após uma mudança, execute `python facet.py --recompute-average` para atualizar as pontuações (não é necessário GPU).

## Sumário

- [Padrões e Seu Override](#padrões-e-seu-override)
- [Usuários](#users)
- [Escaneamento](#scanning)
- [Categorias](#categories)
- [Contextos de Pontuação](#contextos-de-pontuação)
- [Pontuação](#scoring)
- [Limiares](#thresholds)
- [Composição](#composition)
- [Ajustes de EXIF](#exif-adjustments)
- [Exposição](#exposure)
- [Penalidades](#penalties)
- [Normalização](#normalization)
- [Modelos](#models)
- [Modelos de Avaliação de Qualidade](#quality-assessment-models)
- [Processamento](#processing)
- [Decodificação RAW](#decodificação-raw)
- [Mapeamento de tons HDR PQ](#mapeamento-de-tons-hdr-pq)
- [Detecção de Rajadas](#burst-detection)
- [Pontuação de Rajadas](#burst-scoring)
- [Detecção de Duplicatas](#duplicate-detection)
- [Detecção de Faces](#face-detection)
- [Agrupamento de Faces](#face-clustering)
- [Processamento de Faces](#face-processing)
- [Detecção de Monocromático](#monochrome-detection)
- [Marcação de Tags](#tagging)
- [Tags Independentes](#standalone-tags)
- [Análise](#analysis)
- [Visualizador](#viewer)
- [Desempenho](#performance)
- [Armazenamento](#storage)
- [Plugins](#plugins)
- [Cápsulas](#capsules)
- [Grupos de Similaridade](#similarity-groups)
- [Cenas](#scenes)
- [OCR](#ocr)
- [Linha do Tempo](#timeline)
- [Mapa](#map)
- [Tradução](#translation)

---

## Padrões e Seu Override

`scoring_config.json` salva **apenas o que você mudou**. O Facet o resolve por cima de `config/scoring_config.default.json`, então tudo o que você deixar de fora mantém o valor distribuído. Uma instalação nova não tem nenhum `scoring_config.json` e roda com os padrões.

Para aumentar o peso estético dos retratos e definir uma senha de edição, o arquivo inteiro fica:

```json
{
  "viewer": { "edition_password": "your-password" },
  "categories": [ ... ]
}
```

Como os dois arquivos se combinam:

- **Objetos são mesclados chave por chave.** `{"performance": {"mmap_size_mb": 4096}}` muda apenas essa configuração; `cache_size_mb` e qualquer outra chave de `performance` mantêm os valores distribuídos.
- **Arrays são substituídos por completo.** Um array `categories` no seu arquivo substitui totalmente o distribuído. A ordem importa (`categories` segue a regra de que a primeira correspondência vence, `scoring_contexts.*.promote` é lido na ordem), e deixar uma categoria fora do seu array a exclui.

Para mudar um único peso em uma única categoria, copie o array `categories` inteiro de `config/scoring_config.default.json`, edite-o e mantenha-o no seu arquivo.

### Atualizando uma instalação existente

Não há nada a fazer: um `scoring_config.json` completo de uma versão anterior continua funcionando. Qualquer escrita do Facet no arquivo (salvar pesos ou prioridades no visualizador, uma mudança de limiar de panorama, o primeiro login que promove uma senha em texto simples, uma varredura em que `validate_weights` corrige pesos) o reescreve como um override e descarta toda chave que coincida com o padrão distribuído.

Para compactá-lo sob demanda, com uma cópia de backup em `0600` feita antes:

```bash
python database.py --compact-config
```

O resultado se resolve exatamente na mesma configuração.

> **Nota:** um valor igual ao padrão distribuído não permanece no seu arquivo. Se uma versão posterior mudar esse padrão, o seu comportamento também muda. Para fixar um valor, ele precisa ser diferente do padrão.

## Users

Modo multiusuário opcional. Quando a chave `users` contém pelo menos um usuário, o login por usuário substitui a autenticação por senha única.

```json
{
  "users": {
    "alice": {
      "password_hash": "salt_hex:dk_hex",
      "display_name": "Alice",
      "role": "superadmin",
      "directories": ["/volume1/Photos/Alice"]
    },
    "bob": {
      "password_hash": "salt_hex:dk_hex",
      "display_name": "Bob",
      "role": "user",
      "directories": ["/volume1/Photos/Bob"]
    },
    "shared_directories": [
      "/volume1/Photos/Family",
      "/volume1/Photos/Vacations"
    ]
  }
}
```

### Campos de usuário

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `password_hash` | string | Hash PBKDF2-HMAC-SHA256 (`salt_hex:dk_hex`), gerado por `--add-user` |
| `display_name` | string | Exibido no cabeçalho da interface |
| `role` | string | `user`, `admin` ou `superadmin` |
| `directories` | array | Diretórios de fotos privados deste usuário (comparação: veja [Diretórios compartilhados](#diretórios-compartilhados)) |

### Diretórios compartilhados

`shared_directories` (irmã dos objetos de usuário) lista diretórios que todos os usuários podem ver. As entradas de `directories` e `shared_directories` são comparadas com os caminhos que o scanner armazenou:

- A diferença entre maiúsculas e minúsculas ASCII é ignorada no Windows e no macOS, e em entradas UNC ou com letra de unidade em qualquer host.
- Nos demais hosts (no Linux, por exemplo) as maiúsculas importam: escreva cada entrada exatamente como o scanner a armazenou.
- Não tratados: diferenças de maiúsculas fora do ASCII e uma unidade mapeada que o host não consegue resolver.
- Uma entrada em branco não concede nada.

### Funções (roles)

| Função | Ver próprias + compartilhadas | Avaliar/favoritar | Gerenciar pessoas/faces | Disparar escaneamentos |
|------|:-:|:-:|:-:|:-:|
| `user` | sim | sim | não | não |
| `admin` | sim | sim | sim | não |
| `superadmin` | sim | sim | sim | sim |

### Adicionando usuários

Os usuários são criados somente pela CLI; não há interface de registro nem API:

```bash
python database.py --add-user alice --role superadmin --display-name "Alice"
# Solicita a senha, grava o hash em scoring_config.json
```

Depois, edite `scoring_config.json` para definir seus `directories`.

### Compatibilidade retroativa

- Sem a chave `users` = modo de usuário único (comportamento inalterado).
- `viewer.password` e `viewer.edition_password` são ignorados no modo multiusuário.
- As avaliações existentes na tabela `photos` permanecem para o modo de usuário único; `--migrate-user-preferences` as copia.

---

## Scanning

Controla quais diretórios o escaneamento visita.

```json
{
  "scanning": {
    "skip_hidden_directories": true,
    "skip_directories": ["@eaDir", "#recycle", "#snapshot", "@Recycle"]
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `skip_hidden_directories` | `true` | Ignora diretórios cujo nome começa com `.` |
| `skip_directories` | `["@eaDir", "#recycle", "#snapshot", "@Recycle"]` | Globs de nomes de pasta ignorados em qualquer profundidade |

Notas sobre `skip_directories`:
- Os globs usam `fnmatch`, diferenciam maiúsculas de minúsculas e comparam apenas o nome da pasta.
- Os padrões cobrem `@eaDir` da Synology (suas miniaturas `SYNOPHOTO_THUMB_*.jpg`), `#recycle`, `#snapshot` e `@Recycle` da QNAP.
- Sua lista substitui a padrão; `[]` desativa a exclusão por nome. A raiz do escaneamento nunca é ignorada.
- Fotos já indexadas dessas pastas permanecem no banco de dados.

---

## Categories

Array de configurações de categorias. Veja [Pontuação](SCORING.md) para o guia completo de categorias.

Cada categoria possui:
- `name` - Identificador da categoria
- `priority` - Menor = maior prioridade (avaliada primeiro)
- `filters` - Condições para correspondência
- `weights` - Pesos das métricas de pontuação (devem somar 100)
- `modifiers` - Ajustes de comportamento
- `tags` - Vocabulário CLIP para correspondência baseada em tags

> **Pesos de forma e harmonia de cores.** O `weights` de cada categoria tem cinco chaves preenchidas por `--recompute-form`: `symmetry_percent`, `balance_percent`, `edge_entropy_percent`, `fractal_percent` e `color_harmony_percent`. Elas são distribuídas com valor `0`, então as pontuações não mudam até você atribuir um peso a alguma (depois execute `--recompute-average`). Os pesos continuam somando 100.

> **`quality_percent` conta como `aesthetic`.** A qualidade não tem pontuação própria, então `quality_percent` é somado a `aesthetic_percent` antes do cálculo. Veja [SCORING.md](SCORING.md).

> **A categoria `astro` incluída exige um quadro escuro.** Além de uma de suas tags, ela exige `luminance_max: 0.30` (luminância média de no máximo 0.30), então uma cena clara etiquetada como `aurora` ou `stars` não é `astro`. Se o seu `scoring_config.json` tem seu próprio array `categories`, a entrada `astro` dele não recebe este filtro: adicione `"luminance_max": 0.30` em `astro.filters` ou apague o array. `python facet.py --doctor` imprime um «Config notice» quando `astro` não tem `luminance_max`. Depois execute `--recompute-average` (após uma atualização: primeiro `--recompute-silhouette`, depois `--recompute-average` duas vezes; veja [COMMANDS.md](COMMANDS.md)).

---

## Contextos de Pontuação

Um contexto de pontuação muda qual categoria vence para um álbum ou uma foto. Ele promove algumas categorias para o início da ordem global de `categories` e exclui outras; o resto mantém sua ordem de prioridade. Use-o quando a ordem global escolhe a categoria errada para uma sessão: um quadro de dança em contraluz marcado com a tag `sports` é capturado por `silhouette` (prioridade 42) antes de `sports` (prioridade 71). Os controles deslizantes de peso não conseguem corrigir isso, porque só mudam como a categoria selecionada pontua.

```json
{
  "scoring_contexts": {
    "default": {
      "label_key": "comparison.context.default",
      "promote": [],
      "excluded": [],
      "suggest_from_moments": []
    },
    "action_stage": {
      "label_key": "comparison.context.action_stage",
      "promote": ["sports", "concert", "candid"],
      "excluded": ["silhouette"],
      "suggest_from_moments": ["sports", "concert", "nightlife"]
    }
  }
}
```

| Campo | Descrição |
|-------|-------------|
| `label_key` | Chave i18n para o nome de exibição do contexto |
| `promote` | Categorias movidas para o início da ordem de avaliação, na ordem informada |
| `excluded` | Categorias que nunca correspondem sob este contexto |
| `suggest_from_moments` | Valores de `narrative_moment` que sugerem este contexto para um álbum (`GET /api/albums/{id}/suggested_context`, veja [VIEWER.md](VIEWER.md)) |

**Ordem efetiva** = `promote` (na ordem) → a ordem de prioridade global sem os nomes promovidos e excluídos → `default` (a categoria coringa, prioridade 999) por último.

- Um nome presente em `promote` e em `excluded` é excluído.
- `default` nunca pode ser promovido nem excluído.
- Sem contexto, ou com um nome desconhecido, se usa a ordem global simples (um nome desconhecido registra um aviso).
- `python facet.py --validate-categories` relata nomes de categoria desconhecidos, nomes presentes nas duas listas e entradas de `suggest_from_moments` que não são chaves de `narrative_moments.event_types.<default_event_type>`. Do contrário, os erros de digitação passam em silêncio.

Presets fornecidos (`default` é vazio, então nada muda até você atribuir um contexto):

| Contexto | Promove | Exclui | Sugerido a partir de momentos |
|---------|----------|----------|------------------------|
| `default` | — | — | — |
| `action_stage` | `sports`, `concert`, `candid` | `silhouette` | `sports`, `concert`, `nightlife` |
| `party_event` | `group_portrait`, `candid`, `food` | — | `celebration`, `group_gathering`, `dining` |
| `portrait_session` | `portrait`, `portrait_bw`, `fashion` | — | `portrait`, `children` |
| `wildlife` | `wildlife` | — | `nature_wildlife`, `pets` |
| `landscape` | `landscape`, `golden_hour`, `blue_hour` | — | `scenic_landscape`, `mountains`, `snow_winter` |
| `motorsport` | `sports`, `vehicle` | `silhouette` | `sports`, `road_vehicle` |

### Adicionar o seu próprio contexto

Adicione uma chave em `scoring_contexts` e ela funciona como um preset fornecido: você pode atribuí-la a um álbum e editá-la na aba **Contexto de pontuação**.

```json
{
  "scoring_contexts": {
    "dance_comp": {
      "label_key": "comparison.context.dance_comp",
      "promote": ["sports", "concert"],
      "excluded": ["silhouette", "fashion"],
      "suggest_from_moments": ["sports"]
    }
  }
}
```

Se `label_key` não tiver tradução, o seletor mostra o **`name`** do contexto (p. ex. `dance_comp`). Adicione a chave aos seis pacotes `i18n/translations/*.json` para obter um rótulo localizado.

### Editando um Contexto

Na aba **Contexto de pontuação** do visualizador (protegida por edition, `PUT /api/config/scoring_contexts/{name}`), arraste ou mova categorias para a lista promovida, clique em uma categoria para alternar sua exclusão e depois salve.

- Apenas `promote` e `excluded` são editáveis; `label_key`, `suggest_from_moments` e os outros contextos permanecem como estavam.
- A gravação é recusada quando o contexto não existe, quando uma entrada não é uma categoria existente, quando `default` está em qualquer uma das listas ou quando `promote` repete um nome. Um nome presente nas duas listas é aceito (`excluded` prevalece); uma repetição dentro de `excluded` é reduzida.
- Cada gravação mantém uma cópia `.backup.<timestamp>` da configuração, com marca de tempo.
- Editar um contexto não recategoriza as fotos: execute um recálculo em seguida (veja [Alterar prioridades exige um recálculo](#reordenando-a-prioridade-global)). A aba tem um botão **Recalcular agora**.

### Atribuindo um Contexto

Atribua um contexto **por álbum** com `PUT /api/albums/{id}/scoring_context` (protegido por edition).

- Ele se aplica a todas as fotos do álbum naquele momento, exceto às fotos cujo contexto você definiu manualmente.
- Uma foto adicionada depois a um álbum manual herda o contexto. Uma foto nova que passa a corresponder ao filtro de um álbum inteligente não herda; chame `PUT` novamente para reaplicar.
- Um álbum inteligente usa seu filtro salvo, não os alternadores de ocultação da galeria, então pode abranger mais fotos do que a sua visão de galeria exibe.
- `DELETE /api/albums/{id}/scoring_context` remove o contexto das fotos que este álbum definiu. As escolhas manuais permanecem.
- Remover fotos de um álbum (`DELETE /api/albums/{id}/photos`) remove delas o contexto deste álbum. Uma foto que ainda está em outro álbum com contexto assume o contexto desse álbum.
- `GET /api/albums/{id}/suggested_context` propõe um contexto a partir do `narrative_moment` dominante do álbum, por meio de `suggest_from_moments`. Ele não altera nada.

Para uma única foto teimosa, use uma **substituição de categoria**: `POST /api/comparison/override_category` (protegido por edition) define a categoria diretamente, e `POST /api/comparison/clear_category_override` a remove. Uma substituição prevalece sobre qualquer contexto.

As substituições e os contextos sobrevivem a novas varreduras. Um filtro numérico ainda falha quando o valor EXIF está ausente, qualquer que seja o contexto — veja [Pontuação — A Armadilha dos Dados EXIF Ausentes](SCORING.md#a-armadilha-dos-dados-exif-ausentes).
### Reordenando a Prioridade Global

`GET|POST /api/config/category_priorities` (protegido por edition) lê e salva a ordem global da qual todo contexto parte. O visualizador reordena os números de prioridade existentes em vez de renumerá-los.

- `default` (prioridade 999) fica por último e não pode ser movido.
- Uma categoria com prioridade ausente ou duplicada recebe, ao salvar, um valor novo acima do máximo atual.
- Cada gravação mantém uma cópia `.backup.<timestamp>` de `scoring_config.json`, com marca de tempo; as 20 mais recentes são mantidas.

**Alterar prioridades exige um recálculo.** Uma reordenação não altera a `category` armazenada de nenhuma foto. Execute `python facet.py --recompute-average` ou inicie `POST /api/scan/recompute` pelo visualizador (protegido por edition) e acompanhe `GET /api/scan/recompute_status`.

- Um recálculo e uma varredura não podem rodar ao mesmo tempo: a CLI se recusa, e o visualizador informa qual job detém a biblioteca.
- Duas varreduras iniciadas por um terminal geram apenas um aviso (`--resume` se recusa).
- Com `normalization.per_category` ativado, um recálculo pode precisar rodar duas vezes — veja [Normalization](#normalization).

---

## Scoring

```json
{
  "scoring": {
    "score_min": 0.0,
    "score_max": 10.0,
    "score_precision": 2
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `score_min` | `0.0` | Pontuação mínima possível |
| `score_max` | `10.0` | Pontuação máxima possível |
| `score_precision` | `2` | Casas decimais das pontuações |

---

## Thresholds

Limiares de pontuação. Resta apenas `blink_penalty_percent`. Se uma foto é um retrato, uma foto noturna ou uma longa exposição é decidido pelos `filters` de cada categoria (veja [Categories](#categories)), não por este bloco.

```json
{
  "thresholds": {
    "blink_penalty_percent": 50
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `blink_penalty_percent` | `50` | Multiplicador de pontuação quando um piscar é detectado (0,5x) |

---

## Composition

Pontuação de composição baseada em regras (usada quando o SAMP-Net não está ativo).

```json
{
  "composition": {
    "power_point_weight": 2.0,
    "line_weight": 1.0
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `power_point_weight` | `2.0` | Peso para o posicionamento pela regra dos terços |
| `line_weight` | `1.0` | Peso para linhas-guia |

---

## EXIF Adjustments

Ajustes automáticos de pontuação com base nas configurações da câmera.

```json
{
  "exif_adjustments": {
    "iso_sharpness_compensation": true,
    "aperture_isolation_boost": true
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `iso_sharpness_compensation` | `true` | Reduz a penalidade de nitidez para ISO alto |
| `aperture_isolation_boost` | `true` | Aumenta o isolamento para aberturas amplas (f/1.4-f/2.8) |

---

## Exposure

Controla a análise de exposição e a detecção de clipping.

```json
{
  "exposure": {
    "shadow_clip_threshold_percent": 15,
    "highlight_clip_threshold_percent": 10,
    "silhouette_detection": true
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `shadow_clip_threshold_percent` | `15` | Sinaliza se > 15% dos pixels forem preto puro |
| `highlight_clip_threshold_percent` | `10` | Sinaliza se > 10% dos pixels forem branco puro |
| `silhouette_detection` | `true` | Com `true`, uma foto marcada `is_silhouette` ignora a penalidade de recorte na sua pontuação agregada. O próprio sinalizador não é configurável: vem de uma regra fixa baseada no rosto (veja [SCORING.md](SCORING.md)) |

---

## Penalties

Penalidades de pontuação para problemas técnicos.

```json
{
  "penalties": {
    "noise_sigma_threshold": 4.0,
    "noise_max_penalty_points": 1.5,
    "noise_penalty_per_sigma": 0.3,
    "leading_lines_blend_percent": 30,
    "oversaturation_threshold": 0.9,
    "oversaturation_penalty_points": 0.5
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `noise_sigma_threshold` | `4.0` | Ruído acima disso aciona penalidade |
| `noise_max_penalty_points` | `1.5` | Penalidade máxima de ruído |
| `noise_penalty_per_sigma` | `0.3` | Pontos por sigma acima do limiar |
| `leading_lines_blend_percent` | `30` | Mescla no comp_score |
| `oversaturation_threshold` | `0.9` | Limiar de saturação média |
| `oversaturation_penalty_points` | `0.5` | Penalidade por supersaturação |

**Fórmula da penalidade de ruído:**
```
penalty = min(noise_max_penalty_points, (noise_sigma - threshold) * noise_penalty_per_sigma)
```

---

## Normalization

Controla como as métricas brutas são escalonadas para pontuações de 0 a 10.

```json
{
  "normalization": {
    "method": "percentile",
    "percentile_target": 90,
    "per_category": true,
    "category_min_samples": 50
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `method` | `"percentile"` | Método de normalização |
| `percentile_target` | `90` | 90º percentil = pontuação de 10,0 |
| `per_category` | `true` | Normalização específica por categoria |
| `category_min_samples` | `50` | Mínimo de fotos para normalização por categoria |


> **Nota:** com `per_category` ativado, um único recálculo não converge. Os percentis são agrupados pela categoria *armazenada* de cada foto antes de o recálculo reatribuí-la. Depois de uma mudança que move fotos entre categorias (prioridades, um contexto de pontuação, uma substituição de categoria), execute `--recompute-average` duas vezes.

---

## Models

Seleciona quais modelos são usados por perfil de VRAM.

```json
{
  "models": {
    "vram_profile": "auto",
    "keep_in_ram": "auto",
    "profiles": {
      "legacy": {
        "aesthetic_model": "clip-mlp",
        "clip_config": "clip_legacy",
        "composition_model": "samp-net",
        "tagging_model": "clip",
        "supplementary_pyiqa": ["topiq_iaa", "topiq_nr_face", "liqe"],
        "saliency_enabled": true,
        "description": "CPU: CLIP-MLP aesthetic + SAMP-Net composition + CLIP tagging + TOPIQ IAA/NR-Face/LIQE + BiRefNet saliency (8GB+ RAM; saliency/IQA are slower on CPU)"
      },
      "8gb": {
        "aesthetic_model": "clip-mlp",
        "clip_config": "clip_legacy",
        "composition_model": "samp-net",
        "tagging_model": "clip",
        "supplementary_pyiqa": ["topiq_iaa", "topiq_nr_face", "liqe"],
        "saliency_enabled": true,
        "description": "CLIP-MLP aesthetic + SAMP-Net composition + CLIP tagging + TOPIQ IAA/NR-Face/LIQE + BiRefNet saliency (6-14GB VRAM)"
      },
      "16gb": {
        "aesthetic_model": "topiq",
        "clip_config": "clip",
        "composition_model": "samp-net",
        "tagging_model": "qwen3.5-2b",
        "supplementary_pyiqa": ["topiq_iaa", "topiq_nr_face", "liqe"],
        "saliency_enabled": true,
        "description": "TOPIQ aesthetic + SigLIP 2 embeddings + Qwen3.5-2B tagging (~14GB VRAM)"
      },
      "24gb": {
        "aesthetic_model": "topiq",
        "clip_config": "clip",
        "composition_model": "samp-net",
        "tagging_model": "qwen3.5-4b",
        "supplementary_pyiqa": ["topiq_iaa", "topiq_nr_face", "liqe"],
        "saliency_enabled": true,
        "description": "TOPIQ aesthetic + SigLIP 2 embeddings + Qwen3.5-4B tagging (~18GB VRAM)"
      }
    },
    "clip": {
      "model_name": "google/siglip2-so400m-patch16-naflex",
      "backend": "transformers",
      "embedding_dim": 1152,
      "tag_threshold_percent": 8,
      "search_threshold_percent": 5
    },
    "clip_legacy": {
      "model_name": "ViT-L-14",
      "pretrained": "laion2b_s32b_b82k",
      "embedding_dim": 768,
      "tag_threshold_percent": 8,
      "search_threshold_percent": 15
    },
    "qwen2_vl": {
      "model_path": "Qwen/Qwen2-VL-2B-Instruct",
      "torch_dtype": "bfloat16",
      "max_new_tokens": 256
    },
    "qwen3_5_2b": {
      "model_path": "Qwen/Qwen3.5-2B",
      "torch_dtype": "bfloat16",
      "max_new_tokens": 100,
      "vlm_batch_size": 4
    },
    "qwen3_5_4b": {
      "model_path": "Qwen/Qwen3.5-4B",
      "torch_dtype": "bfloat16",
      "max_new_tokens": 100,
      "vlm_batch_size": 2
    },
    "saliency": {
      "model": "ZhengPeng7/BiRefNet_dynamic",
      "resolution": 1024,
      "mask_threshold": 0.3,
      "min_subject_pixels": 50
    },
    "samp_net": {
      "model_path": "pretrained_models/samp_net.pth"
    }
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `vram_profile` | `"auto"` | Perfil ativo (`auto`, `legacy`, `8gb`, `16gb`, `24gb`); `FACET_VRAM_PROFILE` o sobrescreve (veja abaixo) |
| `keep_in_ram` | `"auto"` | Mantém os modelos na RAM entre os blocos de múltiplas passagens (`"auto"`, `"always"`, `"never"`); `auto` verifica antes a RAM disponível |
| `ram_cache_reserve_gb` | `4.0` (opcional, ausente do arquivo fornecido) | RAM (GB) a deixar livre ao lado de um modelo em cache sob `"auto"` |
| `profiles.*.supplementary_pyiqa` | `["topiq_iaa", "topiq_nr_face", "liqe"]` | Modelos PyIQA a executar para este perfil (os quatro perfis executam o conjunto completo) |
| `profiles.*.saliency_enabled` | `true` (todos os perfis) | Executa a saliência de assunto do BiRefNet para este perfil |
| `clip.model_name` | `"google/siglip2-so400m-patch16-naflex"` | Modelo de embedding SigLIP 2 NaFlex (16gb/24gb) |
| `clip.backend` | `"transformers"` | `"transformers"` (SigLIP 2 NaFlex) ou `"open_clip"` (legado) |
| `clip.embedding_dim` | `1152` | Dimensões do embedding (1152 para SigLIP 2) |
| `clip.tag_threshold_percent` | `8` | Similaridade mínima para uma correspondência de **tag** no tagger SigLIP 2 dos perfis 16gb/24gb (substitui `similarity_threshold_percent`) |
| `clip.search_threshold_percent` | `5` | Similaridade mínima para a busca semântica (`GET /api/search`); número inteiro `0-50` |
| `clip_legacy.model_name` | `"ViT-L-14"` | Modelo CLIP legado (perfis legacy/8gb) |
| `clip_legacy.pretrained` | `"laion2b_s32b_b82k"` | Pesos pré-treinados legados |
| `clip_legacy.embedding_dim` | `768` | Dimensões do embedding legado |
| `clip_legacy.tag_threshold_percent` | `8` | O mesmo limiar de tags para o tagger CLIP dos perfis legacy/8gb; `tagging.max_tags` limita o número de tags |
| `clip_legacy.search_threshold_percent` | `15` | Limiar da busca semântica no perfil legacy/8gb; número inteiro `0-50` |
| `qwen2_vl.model_path` | `"Qwen/Qwen2-VL-2B-Instruct"` | Modelo da opção manual `composition_model: "qwen2-vl-2b"` (nenhum perfil o usa) |
| `qwen3_5_2b.model_path` | `"Qwen/Qwen3.5-2B"` | Modelo de tagging para o perfil 16gb |
| `qwen3_5_2b.vlm_batch_size` | `4` | Imagens por lote de inferência do VLM |
| `qwen3_5_4b.model_path` | `"Qwen/Qwen3.5-4B"` | Modelo de tagging para o perfil 24gb |
| `qwen3_5_4b.vlm_batch_size` | `2` | Imagens por lote de inferência do VLM |
| `saliency.model` | `"ZhengPeng7/BiRefNet_dynamic"` | Modelo de saliência BiRefNet |
| `saliency.resolution` | `1024` | Resolução de inferência |
| `saliency.mask_threshold` | `0.3` | Limiar sigmoide para a máscara binária do assunto |
| `saliency.min_subject_pixels` | `50` | Mínimo de pixels de assunto para contar um assunto como detectado |

Notas:
- **`ram_cache_reserve_gb`:** um modelo só é mantido enquanto a RAM disponível for maior que o tamanho dele mais esta reserva. `"always"` pula a verificação; `"never"` não coloca nada em cache. Deve ser um número >= 0, ou a varredura para na inicialização. Sob pressão de memória, o cache devolve primeiro o modelo que será necessário mais tarde (veja [Como Funcionam as Múltiplas Passagens](#como-funcionam-as-múltiplas-passagens)).
- **Limiares de tag e de busca:** `tag_threshold_percent` controla o tagging (varredura, `--recompute-tags`, `tag_existing.py`). `search_threshold_percent` é o valor padrão do controle deslizante de busca de 0-50% da galeria (`search_threshold_default` em `/api/config`). O padrão `5` do SigLIP favorece a abrangência (recall): em uma amostra de 34 fotos, manteve as 21 correspondências verdadeiras e deixou passar 3 de 13 não correspondências.

**Busca semântica e uma biblioteca incorporada sob um perfil diferente:** `GET /api/search` escolhe o codificador de texto e o seu `search_threshold_percent` a partir do bloco, `clip` ou `clip_legacy`, que corresponde à dimensão de embedding *armazenada*, não ao `vram_profile` ativo. Uma biblioteca incorporada com CLIP de 768 dimensões e navegada em uma máquina 16gb, portanto, busca com `clip_legacy`. Se a dimensão armazenada não corresponder a nenhum dos dois blocos, se usa o bloco do perfil ativo.

### Detecção Automática de VRAM

Quando `vram_profile` é `"auto"` (padrão), o Facet detecta a VRAM da GPU na inicialização e seleciona o maior perfil que couber:

| VRAM detectada | Perfil selecionado |
|----------------|--------------------|
| ≥ 20GB | `24gb` |
| ≥ 14GB | `16gb` |
| ≥ 6GB | `8gb` |
| Sem GPU | `legacy` (usa a RAM do sistema) |

Uma GPU CUDA só conta quando o PyTorch a enxerga. Sem nenhum dispositivo visível (por exemplo, com `CUDA_VISIBLE_DEVICES=''`), a varredura usa a CPU, informa 0 GB de VRAM e seleciona `legacy`. `FACET_DEVICE=cuda` sem dispositivo visível para com «FACET_DEVICE=cuda was requested, but that device is not available».

**Placas de 10-14GB podem optar pelo conjunto completo de recursos.** A detecção automática continua selecionando `8gb` abaixo de 14GB. Defina `"vram_profile": "16gb"` ou `FACET_VRAM_PROFILE=16gb` para executar SigLIP 2, TOPIQ, tagging com Qwen3.5-2B, Q-ReAlign e saliência. Os modelos então rodam em quatro passagens, ou três em uma placa que informa 11,8 GiB ou mais (veja [Agrupamento Dinâmico de Passagens](#agrupamento-dinâmico-de-passagens)). Uma foto que a saliência ainda não consegue pontuar grava NULL e registra um ERROR.

> **Aviso:** trocar uma biblioteca `8gb` existente para `16gb` muda o modelo de embeddings (CLIP ViT-L-14 de 768 dimensões → SigLIP 2 de 1152 dimensões). Refaça a varredura ou execute `--recompute-embeddings`, ou a biblioteca misturará dois tamanhos de embedding. Até lá, a busca se comporta como descrito em *Busca semântica e uma biblioteca incorporada sob um perfil diferente* em [Models](#models).

### Substituição pela variável de ambiente `FACET_VRAM_PROFILE`

`FACET_VRAM_PROFILE` substitui `models.vram_profile` no carregamento, de modo que uma única configuração montada pode servir a todos os perfis Docker. Valores aceitos: `auto`, `legacy`, `8gb`, `16gb`, `24gb`; qualquer outro valor é ignorado com um aviso. As sobreposições do Docker Compose (`docker-compose.{legacy,8gb,16gb,24gb}.yml`) definem essa variável para você.

A substituição nunca é gravada de volta em `scoring_config.json`. Um `vram_profile` que você definiu no arquivo continua valendo quando a variável não está definida.

```bash
FACET_VRAM_PROFILE=8gb python facet.py /path/to/photos
```

---

## Quality Assessment Models

Seleciona o modelo que pontua a qualidade/estética da imagem, via biblioteca [pyiqa](https://github.com/chaofengc/IQA-PyTorch).

```json
{
  "quality": {
    "model": "auto",
    "prefer_llm": false
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `model` | `"auto"` | Modelo de qualidade: `auto`, `topiq`, `hyperiqa`, `dbcnn`, `musiq`, `clip-mlp`. `auto` usa `topiq`. |
| `prefer_llm` | `false` | Prefere um pontuador baseado em LLM quando houver um disponível |

### Modelos de Qualidade Disponíveis

SRCC = Coeficiente de Correlação de Postos de Spearman no benchmark KonIQ-10k (1,0 = perfeito).

| Modelo | SRCC | VRAM | Notas |
|--------|------|------|-------|
| `topiq` | 0.93 | ~2GB | Padrão (`auto`); backbone ResNet50 com atenção top-down |
| `hyperiqa` | 0.90 | ~2GB | Hyper-network, adaptável ao conteúdo |
| `dbcnn` | 0.90 | ~2GB | CNN de ramo duplo (distorções sintéticas + autênticas) |
| `musiq` | 0.87 | ~2GB | Transformer multiescala; lida com qualquer resolução |
| `clipiqa+` | 0.86 | ~4GB | CLIP com prompts de qualidade aprendidos |
| `clip-mlp` | 0.76 | ~4GB | CLIP ViT-L-14 legado + cabeça MLP |

### Trocando os Modelos de Qualidade

1. Edite `scoring_config.json`:
   ```json
   "quality": {
     "model": "topiq"
   }
   ```

2. Repontue as fotos existentes (opcional):
   ```bash
   python facet.py /path --pass quality
   python facet.py --recompute-average
   ```

---

## Processing

Configurações de processamento em lote na GPU e de múltiplas passagens.

```json
{
  "processing": {
    "mode": "auto",
    "gpu_batch_size": 16,
    "ram_chunk_size": 32,
    "num_workers": 4,
    "auto_tuning": {
      "enabled": true,
      "monitor_interval_seconds": 5,
      "tuning_interval_images": 32,
      "min_processing_workers": 1,
      "max_processing_workers": 32,
      "min_gpu_batch_size": 2,
      "max_gpu_batch_size": 32,
      "min_ram_chunk_size": 10,
      "max_ram_chunk_size": 128,
      "memory_limit_percent": 85,
      "cpu_target_percent": 85,
      "metrics_print_interval_seconds": 30
    },
    "thumbnails": {
      "photo_size": 640,
      "photo_quality": 80,
      "face_padding_ratio": 0.3
    }
  }
}
```

### Conceitos-Chave

- **`gpu_batch_size`**: imagens processadas juntas em uma única passagem direta na GPU. Limitado pela VRAM; o ajuste automático o reduz quando a memória da GPU excede o limite.
- **`ram_chunk_size`**: imagens mantidas na RAM entre as passagens dos modelos (apenas no modo de múltiplas passagens), de modo que cada imagem é lida do disco uma vez por bloco. Limitado por `memory_limit_percent`. O ajuste automático o reduz imediatamente quando a memória excede o limite, e só o aumenta depois de um bloco cujo uso *máximo* permaneceu abaixo do limite.

### Referência de Configurações

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `mode` | `"auto"` | Modo de processamento: `auto`, `multi-pass`, `single-pass`. Somente `single-pass` seleciona a passagem única; `auto` sempre executa múltiplas passagens |
| `gpu_batch_size` | `16` | Imagens por lote de GPU (limitado pela VRAM) |
| `ram_chunk_size` | `32` | Imagens por bloco de RAM (múltiplas passagens) |
| `num_workers` | `4` | Threads de carregamento de imagens |
| `load_workers` | `num_workers` | Threads de carregamento de blocos em múltiplas passagens (limitado a 8, `1` = sequencial) |
| `raw_decode_concurrency` | `0` (auto) | Máximo de decodificações RAW simultâneas; dimensionado automaticamente a partir de CPU/RAM (1-4), `1` = totalmente serializado |
| `raw_decode_timeout_seconds` | `120` | Abandona uma decodificação RAW travada após este atraso (`0` = desativado); o escaneamento falha rapidamente após travamentos repetidos |
| `exif_prefetch` | `true` | Modo de passagem única: pré-busca o EXIF em segundo plano em vez de bloquear a thread da GPU |
| **auto_tuning** | | |
| `enabled` | `true` | Ativa o ajuste automático |
| `monitor_interval_seconds` | `5` | Intervalo de verificação de recursos |
| `tuning_interval_images` | `32` | Reajusta a cada N imagens |
| `min_processing_workers` | `1` | Mínimo de threads de carregamento |
| `max_processing_workers` | `32` | Máximo de threads de carregamento |
| `min_gpu_batch_size` | `2` | Tamanho mínimo do lote de GPU |
| `max_gpu_batch_size` | `32` | Tamanho máximo do lote de GPU |
| `min_ram_chunk_size` | `10` | Tamanho mínimo do bloco de RAM |
| `max_ram_chunk_size` | `128` | Tamanho máximo do bloco de RAM |
| `memory_limit_percent` | `85` | Percentual do limite de memória efetivo (limite de cgroup sob um teto de contêiner, senão RAM do host) |
| `cpu_target_percent` | `85` | Meta de uso de CPU |
| `metrics_print_interval_seconds` | `30` | Intervalo de impressão de estatísticas |
| **thumbnails** | | |
| `photo_size` | `640` | Tamanho da miniatura armazenada (pixels) |
| `photo_quality` | `80` | Qualidade JPEG da miniatura |
| `face_padding_ratio` | `0.3` | Margem ao redor dos recortes de face |

### Modos de Processamento

| Modo | Descrição |
|------|-----------|
| `auto` | Sempre executa múltiplas passagens (o padrão); somente `single-pass` seleciona a passagem única |
| `multi-pass` | Carregamento sequencial de modelos (funciona com VRAM limitada) |
| `single-pass` | Todos os modelos carregados de uma vez (VRAM alta); apenas perfis `legacy`/`8gb` |

Em `16gb`/`24gb` (estética com TOPIQ), `single-pass` registra um aviso e executa múltiplas passagens, exceto no modo comercial (veja [Licenciamento](#licenciamento)).
### Como Funcionam as Múltiplas Passagens

Em vez de carregar todos os modelos de uma vez, as múltiplas passagens:

1. Carregam imagens em blocos de RAM (padrão de `ram_chunk_size`: 32)
2. Para cada bloco, executam os modelos sequencialmente: carregar modelo → processar bloco → baixar modelo
3. Combinam os resultados em uma passagem final de agregação

Cada imagem é decodificada uma vez por bloco e compartilhada por todas as passagens. As passagens são agrupadas para caber na VRAM disponível, de modo que os VLMs maiores rodem mesmo em placas pequenas.

- As threads de carregamento também calculam EXIF, métricas técnicas, composição baseada em regras, o hash perceptual e uma cópia compartilhada de 1024 px para os modelos pyiqa e o Q-ReAlign.
- Um erro de composição faz falhar apenas essa foto. Ele é registrado em `scan_failures` na etapa `composition`; tente de novo com `--retry-failed`.
- Em uma GPU CUDA, um bloco é decodificado enquanto os próximos modelos carregam, quando a memória livre do host permite e `keep_in_ram` não é `"never"`. Caso contrário (e sempre em CPU e Apple MPS), é decodificado primeiro. Os resultados são idênticos nos dois casos.
- Quando a memória fica curta antes de um bloco, o cache de RAM devolve primeiro o modelo que será necessário mais tarde e mantém `ram_cache_reserve_gb` livre.
- O resumo da varredura informa `Plane rebuilds`, `I/O wait (scan thread blocked on decode)` e `Decode wall`.

### Comportamento do Ajuste Automático

O Facet monitora o uso de recursos e ajusta da seguinte forma. `memory_limit_percent` é medido em relação ao limite de memória *efetivo*: o limite de cgroup sob um teto de contêiner (`mem_limit` do Docker, `--memory` do Podman, `resources.limits.memory` do Kubernetes), senão a RAM do host. Assim, `85` sobre um teto de 8GB resulta em cerca de 6,8GB.

| Métrica | Ação |
|---------|------|
| Memória de GPU > limite | Reduz `gpu_batch_size` em 25% |
| Uso de memória > limite | Reduz `ram_chunk_size` em 25% (imediatamente) |
| Um bloco concluído cujo uso máximo permaneceu < (limite - 20%) | Aumenta `ram_chunk_size` em 25% |
| CPU > meta | Sugere menos workers |
| Timeouts de fila > 5% | Sugere mais workers |

### Agrupamento Dinâmico de Passagens

Quando a VRAM permite, vários modelos rodam na mesma passagem:

| VRAM | Passagem 1 | Passagem 2 | Passagem 3 | Passagem 4 |
|---|---|---|---|---|
| 8GB (perfil `8gb`) | CLIP | Q-ReAlign + saliência | TOPIQ IAA + TOPIQ NR-Face + LIQE | SAMP-Net + InsightFace |
| 12GB\* (perfil `16gb`, opcional) | Tagger Qwen3.5 + Q-ReAlign | SigLIP + saliência + TOPIQ IAA | TOPIQ + TOPIQ NR-Face + LIQE + SAMP-Net | InsightFace |
| 16GB (perfil `16gb`) | Tagger Qwen3.5 + SigLIP + TOPIQ | Q-ReAlign + saliência + TOPIQ IAA + TOPIQ NR-Face + LIQE + SAMP-Net | InsightFace | - |
| 24GB (perfil `24gb`) | Tagger Qwen3.5 4B + SigLIP + Q-ReAlign + saliência | TOPIQ + TOPIQ IAA + TOPIQ NR-Face + LIQE + SAMP-Net + InsightFace | - | - |
| 35GB+ (perfil `24gb`) | Todos os modelos juntos (passagem única) | - | - | - |

As linhas são os planos para placas que informam 8,0, 11,7, 15,99 e 23,99 GiB de VRAM total; 34,8 GiB ou mais planeja uma única passagem. O planejador mantém 1,3 GiB livres para o CUDA, o ONNX Runtime e o desktop. Uma placa de 12GB não é selecionada automaticamente (veja [Detecção Automática de VRAM](#detecção-automática-de-vram)): defina `"vram_profile": "16gb"` ou `FACET_VRAM_PROFILE=16gb`.

\* A linha de 12GB vale para uma placa que informa 11,7 GiB. Uma que informa 11,8 GiB ou mais (por exemplo, 11,99 GiB) planeja em vez disso três passagens: tagger Qwen3.5 + Q-ReAlign; SigLIP + saliência + TOPIQ; TOPIQ IAA + TOPIQ NR-Face + LIQE + SAMP-Net + InsightFace.

### Opções de CLI

```bash
# Padrão: múltiplas passagens automáticas com agrupamento ideal
python facet.py /path/to/photos

# Força passagem única (todos os modelos carregados de uma vez; somente perfis legacy/8gb, em 16gb/24gb avisa e executa múltiplas passagens)
python facet.py /path --single-pass

# Executa apenas uma passagem específica
python facet.py /path --pass quality       # Apenas TOPIQ
python facet.py /path --pass quality-iaa   # TOPIQ IAA (mérito estético)
python facet.py /path --pass quality-face  # TOPIQ NR-Face
python facet.py /path --pass quality-liqe  # LIQE (qualidade + distorção)
python facet.py /path --pass tags          # Apenas o tagger configurado
python facet.py /path --pass composition   # Apenas SAMP-Net
python facet.py /path --pass faces         # Apenas InsightFace
python facet.py /path --pass embeddings    # Apenas embeddings CLIP/SigLIP
python facet.py /path --pass saliency      # Saliência de assunto BiRefNet

# Lista os modelos disponíveis
python facet.py --list-models
```

---

## Decodificação RAW

Como os arquivos RAW são transformados em pixels. O Facet usa dois perfis:

- **Perfil de métricas**: a demosaicagem a partir da qual cada pontuação é calculada (e o espaço de pixels das caixas de rosto e de `image_width`/`image_height`). Um único ganho de exposição fixo para toda a biblioteca, sem adaptação por quadro.
- **Perfil de exibição**: o que a miniatura armazenada, a galeria e `/image` mostram. Prefere a pré-visualização incorporada pela câmera (a curva de tons e a exposição próprias dela) e recai na demosaicagem das métricas.

```json
"raw_decode": {
  "bright": 1.62,
  "prefer_embedded_preview": true,
  "preview_min_sensor_ratio": 0.5,
  "viewer_concurrency": 3,
  "faithful_bracket_render": true
}
```

| Definição | Padrão | Descrição |
|-----------|--------|-----------|
| `bright` | `1.62` | Ganho de exposição fixo para cada demosaicagem (`1.0` = o nível próprio do LibRaw; `1.62` ≈ +0,7 EV do darktable) |
| `prefer_embedded_preview` | `true` | Mostra a pré-visualização da câmera quando existe uma; `false` faz a demosaicagem de tudo (mais lento, sem a curva de tons da câmera) |
| `preview_min_sensor_ratio` | `0.5` | Quanto do sensor uma pré-visualização precisa cobrir para que `/image` a use em vez de fazer a demosaicagem |
| `viewer_concurrency` | `3` | Máximo de demosaicagens RAW simultâneas para `/image` e `/thumbnail` do visualizador, separado de `processing.raw_decode_concurrency` |
| `faithful_bracket_render` | `true` | Mostra os quadros de bracketing sem nenhuma correção (sem pré-visualização, sem ganho `bright`); veja [mais abaixo](#quadros-de-bracketing-são-renderizados-sem-correção) |

Notas:
- `bright` é a única constante arbitrária aqui. Valide-o na sua biblioteca com `--check-raw-rendering` antes de uma varredura grande.
- Nikon, Pentax, Samsung e Canon CR3 incorporam uma pré-visualização quase de tamanho completo (0,98-0,99). A Panasonic fica em 0,52. Olympus, Fuji, Sony e DNG incorporam uma pequena (0,29-0,49), por isso passam pela demosaicagem.

### Compromisso de memória

`viewer_concurrency` e `processing.raw_decode_concurrency` são orçamentos separados. No pior caso os dois rodam ao mesmo tempo, e cada demosaicagem tem um pico de cerca de 200-400 MB. Reduza `viewer_concurrency` em um host com memória limitada. Na prática, só os arquivos Sony, Fuji, Olympus e DNG usam o orçamento do visualizador, porque os demais têm uma pré-visualização suficientemente grande.

### Por que não há brilho automático

O brilho automático do LibRaw se adapta a cada quadro, de modo que um bracketing sai com todos os quadros com praticamente o mesmo brilho. O ganho fixo preserva a escala real de exposição entre os quadros.

Aumentar `bright` clareia cada renderização. As métricas de exposição se movem com ele: execute novamente `--recompute-average` depois de o alterar e refaça a varredura para reescrever as próprias métricas.

### Quadros de bracketing são renderizados sem correção

Uma foto cujo `sequence_kind` é `bracket` ou `hdr_panorama` é exibida sem pré-visualização da câmera e sem ganho `bright`. Ambos cortariam as luzes altas que você está avaliando em um bracketing. Uma `panorama` comum não é afetada.

Onde se aplica:
- `/image` (vista de detalhe, lupa de comparação, lupa de triagem), renderizado em tempo real.
- Os blocos da galeria e a grade de comparação, depois de `--refresh-thumbnails`.
- `GET /api/download` com `type=original`.

Não são afetados: `type=raw` (o RAW intocado), `type=darktable` (a exportação de aspeto editado), `GET /api/photo/cull_preview` (renderizado pelo darktable-cli) e a pontuação.

A detecção de sequências roda depois de uma varredura; execute primeiro `--detect-sequences` e depois `--refresh-thumbnails`, para que os blocos acompanhem.

Defina `faithful_bracket_render` como `false` para renderizar os bracketings como qualquer outra foto.

### Migrando uma biblioteca varrida antes deste perfil

As miniaturas e os histogramas são armazenados no momento da varredura, por isso mudar de perfil não altera as fotos já varridas. `photos.render_version` registra qual renderização produziu cada miniatura armazenada:

- `NULL`: anterior à marca
- `1`: primeiro a pré-visualização da câmera, ganho `bright` na demosaicagem de reserva (o que toda varredura armazena)
- `2`: sem pré-visualização e sem ganho, para um quadro de bracketing (só `--refresh-thumbnails` o armazena)

Apenas duas coisas atualizam as miniaturas armazenadas:
- **Uma nova varredura** reescreve a miniatura e o histograma, e marca sempre `1`.
- **`--refresh-thumbnails`** reescreve as miniaturas RAW e marca `1` ou `2` conforme o `sequence_kind` atual. Reconstrói todas as linhas, por isso execute-o novamente depois de uma alteração de `bright` ou de uma passagem de `--detect-sequences`.

A vista de detalhe (`/image`) está sempre atual; a grade da galeria só muda depois de uma das duas acima.

A galeria mostra um banner descartável que conta as fotos ainda na renderização antiga. Pode ficar atrás da realidade até uma hora; `python database.py --refresh-stats` o atualiza de imediato.

Uma renderização que sai totalmente preta (por exemplo, um RW2 Panasonic truncado) é recusada, registrada com o nome do arquivo e tentada de novo em uma execução posterior.

---

## Mapeamento de tons HDR PQ

As fotos estáticas Canon HDR PQ (`.HIF`) carregam a função de transferência PQ (SMPTE ST 2084) sobre primários BT.2020, com até 10.000 nits. Os modelos de qualidade e as miniaturas precisam de sRGB SDR de 8 bits; por isso, o Facet decodifica uma imagem PQ na profundidade nativa da câmera, a converte para sRGB e aplica o mapeamento de tons. Este bloco controla esse mapeamento.

Aplica-se **somente** a imagens cujo perfil de cor NCLX declara a transferência PQ (característica 16). HEIF SDR, HLG e JPEG passam sem alterações, independentemente de `enabled`. Quadros girados (orientação EXIF diferente de 1) saem em pé, inclusive pelo caminho de profundidade nativa: com pillow-heif 1.6 e mais recentes, o plano é girado antes do mapeamento de tons.

```json
"hdr_pq_tonemap": {
  "enabled": true,
  "method": "hable",
  "white_point": {
    "mode": "percentile",
    "percentile": 99.99,
    "min_nits": 100.0,
    "max_nits": 1200.0,
    "fixed_nits": 1000.0
  },
  "chroma_preserve": "per_channel"
}
```

| Configuração | Padrão | Descrição |
|---------|---------|-------------|
| `enabled` | `true` | Mapeia por tons as imagens PQ para SDR; `false` as deixa escuras e desbotadas (apenas para depuração) |
| `method` | `hable` | Curva de tons: `hable` (fílmica, como no filtro `tonemap` do ffmpeg) ou `clip` (linear com corte duro, apenas como referência) |
| `white_point.mode` | `percentile` | Como o ponto de branco por imagem é escolhido: `percentile`, `max` (o pixel mais brilhante) ou `fixed` (`fixed_nits`) |
| `white_point.percentile` | `99.99` | Percentil usado no modo `percentile` |
| `white_point.min_nits` | `100.0` | Piso para o ponto de branco; um quadro escuro nunca é normalizado abaixo do branco de referência SDR |
| `white_point.max_nits` | `1200.0` | Teto no modo `percentile`; limita o quanto um quadro excepcionalmente brilhante pode puxar a curva para baixo |
| `white_point.fixed_nits` | `1000.0` | Ponto de branco usado no modo `fixed` |
| `chroma_preserve` | `per_channel` | `per_channel` (mais brilhante, com leve mudança de matiz nos realces) ou `max_channel` (preserva a matiz, um pouco mais escuro) |

O modo `max` deixa um único pixel quente em uma cena noturna escurecer todo o quadro; `percentile` evita isso.

### Por que o ponto de branco é por imagem

Um ponto de branco fixo de 100 nits corta para o branco puro tudo o que for mais brilhante, e as fotos HDR reais atingem picos de centenas a milhares de nits. O Facet normaliza, em vez disso, em um ponto de branco por imagem, como o ffmpeg (`vf_tonemap.c`). O p99.99 padrão, limitado a 100-1200 nits, mantém a textura dos realces e ignora pixels quentes isolados.

### Por que a decodificação usa a profundidade nativa da câmera

Decodificar o PQ em 8 bits antes do mapeamento de tons posteriza os degradês suaves. O Facet pede ao decodificador HEIF a profundidade do próprio arquivo (10 bits nas câmeras atuais) e só estreita para 8 bits depois da curva de tons. O ganho aparece em conteúdo suave (céus limpos, fundos de estúdio, bokeh acentuado); os sinalizadores de corte e o `exposure_score` não mudam em fotos reais. Um decodificador que não consiga fornecer a profundidade nativa volta aos 8 bits.

**Referências.** EOTF PQ: SMPTE ST 2084:2014. Curva Hable e pico por quadro:
ffmpeg `vf_tonemap.c` (John Hable, "Filmic Tonemapping Operators", 2010).
Matriz BT.2020 para sRGB: BT.2020-2 / IEC 61966-2-1 com D65. OETF sRGB:
IEC 61966-2-1. Característica de transferência NCLX 16: ISO/IEC 23001-8 / ITU-T H.273.

## Burst Detection

Agrupa fotos similares tiradas em sucessão rápida.

```json
{
  "burst_detection": {
    "similarity_threshold_percent": 70,
    "time_window_minutes": 0.8,
    "rapid_burst_seconds": 0.4
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `similarity_threshold_percent` | `70` | Limiar de similaridade do hash da imagem |
| `time_window_minutes` | `0.8` | Tempo máximo entre fotos |
| `rapid_burst_seconds` | `0.4` | Fotos dentro deste intervalo são agrupadas automaticamente |

---

## Notificações de atualização

Avisa os usuários em modo edição de que existe uma versão mais recente do Facet. Isso é independente do aviso «Está disponível uma nova versão — Recarregar» do navegador.

- A versão em execução aparece no fim do menu do usuário, para todos que podem abrir o visualizador.
- Uma imagem construída com `--build-arg FACET_BUILD=<branch>@<commit>` mostra também essa linha de build. `/api/config` devolve ambos como `version` e `build`, apenas a quem pode ler a biblioteca.
- O servidor consulta o GitHub no máximo uma vez por `interval_days`, sem token nem dados da fototeca. Uma verificação que falha aparece como «nenhuma atualização conhecida».
- Só os usuários em modo edição veem o aviso, no máximo uma vez por semana por navegador.

```json
{
  "updates": {
    "enabled": true,
    "check_url": "https://api.github.com/repos/ncoevoet/facet/releases/latest",
    "interval_days": 7
  }
}
```

| Definição | Padrão | Descrição |
|---|---|---|
| `enabled` | `true` | `false` desativa a verificação; nada é alguma vez pedido |
| `check_url` | API do GitHub da última versão | Onde procurar a versão publicada mais recente |
| `interval_days` | `7` | Durante quanto tempo um resultado fica em cache antes de nova consulta |

---

## Detecção de sequências

Dá nome aos bracketings de exposição para que não sejam tratados como tomadas em competição. A exposição de cada quadro vem de `f_stop` / `shutter_speed` / `ISO` já armazenados (`EV = log2(N^2 / t) - log2(ISO / 100)`), por isso uma biblioteca existente é etiquetada sem nova varredura.

Uma série é um bracketing quando os seus quadros:
- vêm da mesma câmera, cada um dentro de `max_gap_seconds` do anterior;
- mantêm o mesmo enquadramento (`max_hamming` sobre o pHash);
- formam uma escada regular de exposições distintas, em qualquer ordem de captura (começar pela foto base, `0, -, +`, vale como do escuro para o claro), abrangendo `min_span_stops`, em pelo menos `min_frames` quadros.

Cada quadro recebe `sequence_ev_offset`, a sua exposição face ao quadro base, com o sinal dos rótulos AEB de uma câmera (`-2` escuro, `+2` claro). A base é o degrau central. Com um número par de quadros, a base é o quadro central que corta menos extremos do seu histograma (o mais antigo em caso de empate); uma série ímpar como `(-2, 0, +2)` usa sempre o quadro do meio. Quando um grupo de rajada é exatamente um bracketing, a galeria mostra o seu quadro base.

Executa-se com `--detect-sequences`; roda também no fim de cada varredura, depois do agrupamento das rajadas.

**As correções manuais também cobrem bracketings.** Marque à mão um bracketing que a detecção falhou, a partir da galeria ou do laboratório de triagem («Marcar como série de exposição»). Exige ≥2 quadros, cada um com dados de exposição utilizáveis, sem dois com a mesma exposição. Veja [docs/VIEWER.md — Panorâmicas e brackets de exposição](VIEWER.md#panorâmicas-e-brackets-de-exposição).

```json
{
  "sequence_detection": {
    "enabled": true,
    "max_gap_seconds": 3.0,
    "max_hamming": 10,
    "min_frames": 3,
    "min_step_stops": 0.5,
    "min_span_stops": 1.0,
    "step_tolerance_stops": 0.34
  }
}
```

| Definição | Padrão | Descrição |
|---|---|---|
| `enabled` | `true` | Desativa por completo a detecção de bracketing |
| `max_gap_seconds` | `3.0` | Intervalo máximo entre dois quadros consecutivos de uma série |
| `max_hamming` | `10` | Distância pHash admitida entre os quadros (mesmo enquadramento) |
| `min_frames` | `3` | Série mais curta considerada um bracketing. `2` é opcional — veja a advertência abaixo |
| `min_step_stops` | `0.5` | Menor passo de EV que conta como alteração deliberada |
| `min_span_stops` | `1.0` | Amplitude total mínima entre o quadro mais escuro e o mais claro |
| `step_tolerance_stops` | `0.34` | Irregularidade admitida entre os passos (um terço de passo) |

**Porque `min_frames` está em `3` por padrão.** Dois quadros separados por um passo parecem iguais, quer sejam um bracketing AEB de duas fotos, quer uma rápida correção de exposição. Com `2`, a maioria das séries adicionais encontradas em uma biblioteca de teste não eram bracketings. Um par pode também ser o que resta de uma série de três, e então a base (`sequence_ev_offset` `0`) pode cair no quadro errado enquanto `hide_brackets` (ativo por padrão) esconde o outro. Defina `2` apenas se fotografar com bracketing AEB de dois quadros e aceitar alguns falsos positivos.

---

## Detecção de panorâmicas

Dá nome aos quadros de origem de uma panorâmica, que a detecção de rajadas esconderia como tomadas em competição. A detecção compara características SIFT entre miniaturas consecutivas de 640px já armazenadas; não precisa de decodificar o original, de um modelo nem de dependências extras.

- Uma varredura avança de forma contínua em uma direção; uma rajada oscila em torno de um ponto. Panorâmicas simples e HDR são tipos distintos, separados pela amplitude de exposição.
- A precisão medida foi de cerca de 96 % em uma biblioteca de teste. Algumas panorâmicas verticais ou com poucas posições são perdidas.
- Pode corrigir nos dois sentidos com a correção manual por série.

```json
{
  "panorama_detection": {
    "enabled": true,
    "max_gap_seconds": 30.0,
    "min_frames": 8,
    "min_drift": 0.43,
    "min_inliers": 25,
    "hdr_min_span_stops": 1.5,
    "sift_features": 400
  }
}
```

| Definição | Padrão | Descrição |
|---------|---------|-------------|
| `enabled` | `true` | Desativar completamente a detecção de panorâmicas |
| `max_gap_seconds` | `30.0` | Intervalo máximo entre quadros consecutivos de uma varredura |
| `min_frames` | `8` | Série mais curta considerada panorâmica (o filtro mais forte; as não-panorâmicas tinham 6 quadros ou menos) |
| `min_drift` | `0.43` | Varredura total, em larguras de enquadramento, para a série contar |
| `min_inliers` | `25` | Correspondências RANSAC necessárias para validar um par |
| `max_step` | `0.9` | Maior passo isolado, em larguras de enquadramento — acima disso é um corte de cena |
| `back_tolerance` | `0.02` | Recuo tolerado em um passo antes de a série terminar |
| `max_ortho` | `0.15` | Desvio lateral tolerado em toda a varredura |
| `ortho_ratio` | `0.25` | Margem lateral adicional proporcional à varredura, para não penalizar séries longas |
| `step_ortho_abs` | `0.02` | Movimento lateral tolerado em um único passo antes de ser lido como reenquadramento |
| `step_ortho_ratio` | `0.5` | O mesmo limite como fração do próprio passo |
| `hdr_min_span_stops` | `1.5` | Amplitude de exposição acima da qual uma varredura é uma panorâmica HDR |
| `sift_features` | `400` | Características por miniatura; o custo cresce com o quadrado deste valor |
| `match_ratio` | `0.75` | Razão de Lowe que uma correspondência tem de superar para ser mantida |
| `workers` | `0` | Processos de trabalho paralelos; `0` escolhe pelo número de núcleos |
| `probe_stride` | `8` | Quadros entre as sondagens baratas que descartam rajadas comuns |
| `probe_min_drift` | `0.05` | Movimento abaixo do qual uma sondagem declara a série imóvel |
| `max_run_frames` | `500` | Série candidata mais longa medida (limita a memória, ~220 KB por quadro e por processo) |

Notas:
- `sift_features` custa cerca de 2,3 ms por par de quadros com 400 e cerca de 0,12 s com 3000.
- Alterar uma definição não faz nada até a detecção rodar de novo: use `--detect-panoramas` (ou a ação de nova execução do visualizador), que volta a medir toda a biblioteca.
- A etapa de panoramas depois de uma varredura, de `--recompute-average` ou de `--recompute-burst` volta a medir apenas as séries alteradas. Editar qualquer definição além de `enabled` e `workers` faz com que volte a medir tudo.
- As suas correções se aplicam na passagem seguinte. Duas passagens sobre uma biblioteca inalterada encontram os mesmos conjuntos, com os mesmos números de grupo.

---

## Burst Scoring

Pesos usados pela seleção de rajadas para escolher o melhor disparo em cada grupo de rajada. Os pesos devem somar 1,0.

```json
{
  "burst_scoring": {
    "weight_aggregate": 0.4,
    "weight_aesthetic": 0.25,
    "weight_sharpness": 0.2,
    "weight_blink": 0.15
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `weight_aggregate` | `0.4` | Peso da pontuação agregada geral |
| `weight_aesthetic` | `0.25` | Peso da pontuação de qualidade estética |
| `weight_sharpness` | `0.2` | Peso da pontuação de nitidez técnica |
| `weight_blink` | `0.15` | Peso de penalidade para piscadas detectadas (maior = penalidade mais forte) |

---

## Duplicate Detection

Encontra fotos duplicadas em toda a biblioteca: candidatos de pHash frouxo, confirmados por uma verificação de similaridade de embedding.

```json
{
  "duplicate_detection": {
    "similarity_threshold_percent": 90,
    "prefilter_hamming": 12,
    "embedding_cosine_threshold": 0.90
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `similarity_threshold_percent` | `90` | Filtro estrito de pHash (90% = distância de Hamming <= 6 de 64 bits); é o único teste quando falta o embedding de alguma das fotos |
| `prefilter_hamming` | `12` | Opcional (ausente no arquivo distribuído). Filtro frouxo de Hamming para os candidatos quando ambas as fotos têm embeddings (pelo menos igual ao filtro estrito) |
| `embedding_cosine_threshold` | `0.90` | Opcional (ausente no arquivo distribuído). Um candidato só é mesclado quando o cosseno SigLIP/CLIP >= este valor |

- `python facet.py --detect-duplicates` detecta e agrupa duplicatas.
- `python facet.py --sweep-dedup-thresholds [labels.json]` avalia o filtro de cosseno: com um JSON de rótulos imprime precisão/recall; caso contrário, imprime a distribuição de cosseno dos candidatos e quantas correspondências de pHash estrito o filtro rejeita.

---

## Camada IQA estendida (opcional)

Pontuadores de qualidade extras que gravam suas próprias colunas; nunca substituem o TOPIQ. Rodam durante um escaneamento normal. Uma falha de carregamento/VRAM é registrada e deixa a coluna `NULL`; o escaneamento continua.

- `qrealign` tem como padrão `"auto"`: **ligado** para os perfis `8gb`/`16gb`/`24gb`, **desligado** para `legacy`/CPU.
- `aesthetic_v25` e `deqa` ficam **DESLIGADOS por padrão**.

```json
{
  "iqa_extended": {
    "qrealign": "auto",
    "qrealign_size": "mini",
    "aesthetic_v25": false,
    "deqa": false
  }
}
```

| Configuração | Padrão | Valores aceitos | Coluna | Descrição |
|--------------|--------|-----------------|--------|-----------|
| `qrealign` | `"auto"` | `"auto"` · `true` · `false` | `qrealign_score` | IQA estético Q-ReAlign-Mini 0.8B (Apache-2.0, ~2-3GB VRAM/RAM, sem pyiqa) |
| `qrealign_size` | `"mini"` | `"mini"` · `"lite"` | - | `mini` (0.8B) ou `lite` (4B); também o modelo principal em `licensing.mode: "commercial"` |
| `aesthetic_v25` | `false` | `true` / `false` | `aesthetic_v25` | Aesthetic Predictor V2.5 (cabeça SigLIP, ~2GB); **descontinuado**, prefira `qrealign` |
| `deqa` | `false` | `true` / `false` | `deqa_score` | IQA VLM DeQA-Score (GPU 16GB+; ignorado e deixado NULL caso contrário) |

Notas:
- **Ordenação:** cada métrica aparece no menu de ordenação do visualizador assim que pelo menos uma foto tem pontuação (**Q-ReAlign (estética)**, **Estética v2.5**, **DeQA**). As fotos sem pontuação ficam por último.
- `qrealign_score` contém a tarefa estética; a qualidade usa `quality_score`.
- `aesthetic_v25` requer o pacote `aesthetic-predictor-v2-5`. É licenciado sob AGPL-3.0 e sem manutenção upstream desde 2024-12-18.

**Instale as dependências opcionais** para o que você habilitar: `pip install -e .[iqa-extended]` (adiciona `aesthetic-predictor-v2-5`), ou descomente a linha correspondente em `requirements.txt`. O DeQA-Score é baixado via `transformers`.

Cada métrica fica disponível ao agregado ponderado com peso 0, de modo que `--recompute-average` não muda nada até você atribuir um peso. `python facet.py --eval-iqa-srcc` mede o quanto cada métrica concorda com as suas próprias avaliações por estrelas.

**Exibição no visualizador.** Os valores preenchidos aparecem no painel **Quality** dos detalhes da foto (`Q-ReAlign`, `Aesthetic V2.5`, `DeQA`), com controles deslizantes de faixa sob **Extended Quality** nos filtros da galeria (`min_qrealign`/`max_qrealign`, `min_aesthetic_v25`/`max_aesthetic_v25`, `min_deqa`/`max_deqa`).

> **Aviso:** as fotos escaneadas antes de você habilitar uma métrica têm `NULL` nela, e qualquer mínimo ou máximo no seu controle deslizante as oculta. Faça um novo escaneamento antes de filtrar por uma métrica recém-habilitada.

**Robustez.** O DeQA-Score executa código de modelo remoto (`trust_remote_code`). Se ele falhar em uma imagem (mudança de assinatura, saída estranha, OOM), o `deqa_score` dessa imagem fica `NULL` e o escaneamento continua.

---

## Licenciamento

Controla quais componentes de modelos o Facet pode carregar. Veja [THIRD_PARTY_MODELS.md](THIRD_PARTY_MODELS.md) para a tabela de licenças por componente.

```json
{
  "licensing": {
    "mode": "default",
    "allow_unclear": false
  }
}
```

| Configuração | Padrão | Valores aceitos | Descrição |
|---------|---------|-------------------|-------------|
| `mode` | `"default"` | `"default"` · `"commercial"` | `"default"` carrega todos os modelos; `"commercial"` carrega apenas componentes adequados ao uso comercial |
| `allow_unclear` | `false` | `true` / `false` | No modo comercial, permite também componentes com licença *incerta* (SAMP-Net, U2-Net-P, a cabeça estética CLIP-MLP da LAION); deve ser um booleano JSON |

No modo `"commercial"`:
- `pyiqa` (TOPIQ, HyperIQA, LIQE, ...) e InsightFace nunca são importados nem baixados.
- Estética e qualidade vêm do Q-ReAlign, a composição do analisador baseado em regras.
- Os rostos usam detecção YuNet, embeddings SFace de 128 dimensões e, opcionalmente, MediaPipe para olhos/sorriso e a qualidade facial OFIQ.
- `liqe` e `aesthetic_iaa` ficam `NULL`. `deqa` (licença *pouco clara*) exige `allow_unclear`. `aesthetic_v25` (AGPL) nunca está disponível.
- Um componente recusado para a varredura no inicialização com um `LicenceError` que nomeia o componente e o seu substituto.
- `--score-topiq`, `--recompute-iqa` (modelos pyiqa) e `--recompute-composition-gpu` terminam com essa mensagem.
- Componentes com licença não comercial continuam recusados mesmo com `allow_unclear`.

Nada disto é aconselhamento jurídico.

Substituições por variável de ambiente (só podem restringir; um valor inválido interrompe o inicialização):

| Variável | Efeito |
|----------|--------|
| `FACET_LICENSING_MODE` | `commercial` força o modo comercial; `default` ou vazia = sem substituição |
| `FACET_LICENSING_ALLOW_UNCLEAR` | `0`, `false`, `no`, `off` forçam `allow_unclear` desligado; `1`, `true`, `yes`, `on` ou vazia = sem substituição |

O visualizador passa `FACET_LICENSING_MODE=commercial` e, quando a sua política proíbe componentes incertos, `FACET_LICENSING_ALLOW_UNCLEAR=0` a cada processo `facet.py` que inicia. Uma cadeia como `"false"` em `licensing.allow_unclear` é rejeitada no inicialização.

---

## Face Detection

Configurações de detecção de faces do InsightFace.

```json
{
  "face_detection": {
    "min_confidence_percent": 65,
    "min_face_size": 20,
    "blink_ear_threshold": 0.28,
    "min_faces_for_group": 4,
    "enable_3d_landmarks": false,
    "eyes_closed_max": 4.0,
    "poor_expression_min": 4.0,
    "blendshapes": {
      "enabled": true,
      "min_crop_size": 192,
      "blink_pose_gate_deg": null
    }
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `min_confidence_percent` | `65` | Confiança mínima de detecção (apenas InsightFace) |
| `min_face_size` | `20` | Tamanho mínimo da face em pixels (apenas InsightFace) |
| `blink_ear_threshold` | `0.28` | Razão de Aspecto do Olho (EAR) para detecção de piscar |
| `min_faces_for_group` | `4` | Mínimo de faces para classificar como retrato de grupo (recalculado em `--recompute-average`) |
| `enable_3d_landmarks` | `false` | Opcional (ausente no arquivo distribuído). Carrega o `landmark_3d_68` do InsightFace para a pose da cabeça (yaw/pitch/roll); ~5MB, apenas informativo |
| `eyes_closed_max` | `4.0` | Pontuação de olhos-abertos (0–10) igual ou abaixo da qual o laboratório de triagem sinaliza uma piscada (anéis de rosto, controle deslizante de olhos) |
| `poor_expression_min` | `4.0` | Pontuação de sorriso/expressão (0–10) abaixo da qual o laboratório sinaliza uma expressão fraca |
| `blendshapes.enabled` | `true` | Usa os blendshapes do MediaPipe para `eyes_open_score` / `smile_score` quando instalado; caso contrário, a geometria de pontos de referência |
| `blendshapes.min_crop_size` | `192` | Rostos cujo recorte com margem seja menor que este valor (px, lado mais curto) usam a pontuação geométrica |
| `blendshapes.blink_pose_gate_deg` | `null` | Apenas modo comercial (MediaPipe): limite da pose da cabeça em graus; `null` = desativado |

Notas:
- O detetor YuNet do modo comercial usa valores fixos (confiança 0,7, 30 px) e ignora `min_confidence_percent` e `min_face_size`.
- O MediaPipe precisa do pacote `face_landmarker.task`. Instale-o com `pip install mediapipe==0.10.35 --no-deps`, nunca um simples `pip install mediapipe`. Veja [FACE_RECOGNITION.md](FACE_RECOGNITION.md#sinais-de-expressão-por-rosto-olhos-abertos--sorriso).
- `blink_pose_gate_deg`: um rosto cujo |yaw| ou |pitch| o ultrapasse não recebe veredito de piscada nem pontuação de olhos abertos / sorriso (NULL), porque uma cabeça virada parece ter os olhos fechados. Nenhum limite entre 20° e 45° melhorou a detecção de piscadas em uma biblioteca de teste, por isso fica desativado. Deve ser um número positivo; se aplica a fotos recém-escaneadas (`is_blink` muda ao reescanear).

---

## Face Clustering

Agrupamento HDBSCAN para reconhecimento de faces.

```json
{
  "face_clustering": {
    "enabled": true,
    "min_faces_per_person": 2,
    "min_samples": 2,
    "clustering_algorithm": "best",
    "leaf_size": 40,
    "use_gpu": "auto",
    "thresholds_by_model": {
      "arcface_buffalo_l": { "auto_merge_distance_percent": 15, "merge_threshold": 0.6 },
      "sface": { "auto_merge_distance_percent": 27.5, "merge_threshold": 0.65 }
    }
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `enabled` | `true` | Ativa o agrupamento de faces |
| `min_faces_per_person` | `2` | Mínimo de fotos por pessoa |
| `min_samples` | `2` | Parâmetro min_samples do HDBSCAN |
| `clustering_algorithm` | `"best"` | Algoritmo HDBSCAN |
| `leaf_size` | `40` | Tamanho da folha da árvore (apenas CPU) |
| `use_gpu` | `"auto"` | Modo de GPU: `auto`, `always`, `never` (veja as notas abaixo) |
| `thresholds_by_model` | ver JSON | Por modelo de reconhecimento: `auto_merge_distance_percent` e `merge_threshold`. Valores padrão: ArcFace `15` / `0.6`, SFace `27.5` / `0.65` |

`merge_threshold` (semelhança de centroides para a correspondência) e `auto_merge_distance_percent` (distância de fusão automática) são lidos de `thresholds_by_model` para o modelo de reconhecimento **ativo** (ArcFace por padrão, SFace no modo comercial). Um modelo sem entrada é um erro. As mesmas chaves colocadas diretamente em `face_clustering` já não são lidas.

**Notas sobre o agrupamento na GPU (`use_gpu`):**

- Requer os pacotes opcionais `cuml` + `cupy`. A imagem Docker para GPU inclui o cuML.
- O perfil `legacy` agrupa sempre na CPU, seja qual for o valor de `use_gpu`.
- Sem um dispositivo CUDA utilizável, o agrupamento recorre ao HDBSCAN na CPU.
- `always` avisa e usa a CPU se o cuML estiver ausente; um erro de GPU durante o agrupamento também recorre à CPU.

**Algoritmos de agrupamento:**

| Algoritmo | Complexidade | Melhor Para |
|-----------|--------------|-------------|
| `boruvka_balltree` | O(n log n) | Dados de alta dimensionalidade (recomendado) |
| `boruvka_kdtree` | O(n log n) | Dados de baixa dimensionalidade |
| `prims_balltree` | O(n²) | Memória limitada, alta dimensionalidade |
| `prims_kdtree` | O(n²) | Memória limitada, baixa dimensionalidade |
| `best` | Auto | Deixa o HDBSCAN decidir |

---

## Face Processing

Controla a extração de faces e a geração de miniaturas.

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
    "refill_batch_size": 100,
    "auto_tuning": {
      "enabled": true,
      "memory_limit_percent": 80,
      "min_batch_size": 8,
      "monitor_interval_seconds": 5
    }
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `crop_padding` | `0.3` | Razão de margem para recortes de face |
| `use_db_thumbnails` | `true` | Usa as miniaturas armazenadas |
| `face_thumbnail_size` | `640` | Tamanho da miniatura em pixels |
| `face_thumbnail_quality` | `90` | Qualidade JPEG |
| `extract_workers` | `2` | Workers de extração paralelos |
| `extract_batch_size` | `16` | Tamanho do lote de extração |
| `refill_workers` | `4` | Workers de reabastecimento de miniaturas |
| `refill_batch_size` | `100` | Tamanho do lote de reabastecimento |
| **auto_tuning** | | |
| `enabled` | `true` | Ativa o ajuste baseado em memória |
| `memory_limit_percent` | `80` | Percentual do limite de memória efetivo (limite de cgroup sob um teto de contêiner, senão RAM do host) |
| `min_batch_size` | `8` | Tamanho mínimo do lote |
| `monitor_interval_seconds` | `5` | Intervalo de verificação |

---

## Monochrome Detection

Detecção de fotos em preto e branco.

```json
{
  "monochrome_detection": {
    "saturation_threshold_percent": 5
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `saturation_threshold_percent` | `5` | Saturação média < 5% = monocromático |

---

## Tagging

Configurações gerais de tagging. O modelo de tagging é configurado por perfil em `models.profiles.*.tagging_model`.

```json
{
  "tagging": {
    "enabled": true,
    "max_tags": 5
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `enabled` | `true` | Ativa o tagging |
| `max_tags` | `5` | Máximo de tags por foto |


**Nota:** o limiar de tags do CLIP/SigLIP é `tag_threshold_percent` no bloco do perfil ativo: `models.clip` para `16gb`/`24gb`, `models.clip_legacy` para `legacy`/`8gb`. A antiga chave `similarity_threshold_percent` não é mais lida. Se você a personalizou, copie o valor para `tag_threshold_percent`; o carregamento da configuração e `python facet.py --doctor` sinalizam a chave antiga.

Ao final de uma varredura, a etapa de marcação é ignorada (com uma linha de log) quando `enabled` é `false` ou quando nenhuma foto tem ao mesmo tempo um embedding e uma lista de tags vazia. As fotos que nenhuma tag consegue corresponder continuam pendentes, então o modelo ainda é carregado a cada varredura. `python tag_existing.py` (com ou sem `--force`) e `python facet.py --tag-untagged` sempre são executados.
### Modelos de Tagging Disponíveis

Configurados via `models.profiles.*.tagging_model`:

| Modelo | VRAM | Estilo de Tag | Notas |
|--------|------|---------------|-------|
| `clip` | 0 (reutiliza embeddings) | Clima/atmosfera (dramatic, golden_hour, vintage) | Sem carga extra de modelo; detecção de objetos menos literal |
| `qwen3.5-2b` | ~4GB | Cenas estruturadas (landscape, architecture, reflection) | Requer transformers + VRAM extra |
| `qwen3.5-4b` | ~8GB | Cenas detalhadas com nuance | VRAM maior; inferência mais lenta |

### Modelos de Tagging Padrão por Perfil

| Perfil | Modelo de Tagging | Modelo de Embedding |
|--------|-------------------|---------------------|
| `legacy` | `clip` | CLIP ViT-L-14 (768-dim) |
| `8gb` | `clip` | CLIP ViT-L-14 (768-dim) |
| `16gb` | `qwen3.5-2b` | SigLIP 2 NaFlex SO400M (1152-dim) |
| `24gb` | `qwen3.5-4b` | SigLIP 2 NaFlex SO400M (1152-dim) |

### Repetindo o Tagging de Fotos

```bash
python facet.py --recompute-tags       # Refaz as tags usando o modelo configurado por perfil
python facet.py --recompute-tags-vlm   # Refaz as tags usando o tagger VLM
```

---

## Standalone Tags

Tags com listas de sinônimos que não estão vinculadas a nenhuma categoria específica. Elas ficam disponíveis para todas as fotos independentemente da categoria atribuída. Cada chave é o nome da tag; o valor é uma lista de sinônimos para correspondência CLIP/VLM.

```json
{
  "standalone_tags": {
    "bokeh": ["bokeh", "shallow depth of field", "background blur", "out of focus"],
    "surreal": ["surreal", "dreamlike", "fantasy", "composite", "double exposure"],
    "flat_lay": ["flat lay", "overhead shot", "top down", "bird's eye product"],
    "golden_hour": ["golden hour", "magic hour", "warm light", "sunset light"],
    "portrait_tag": ["portrait", "headshot", "face portrait", "close-up portrait"]
  }
}
```

Adicione novas tags independentes fornecendo uma chave e uma lista de sinônimos. As tags definidas aqui são mescladas com as tags específicas de categoria para formar o vocabulário completo de tags.

---

## Analysis

Limiares para `--compute-recommendations`.

```json
{
  "analysis": {
    "aesthetic_max_threshold": 9.0,
    "aesthetic_target": 9.5,
    "quality_avg_threshold": 7.5,
    "quality_weight_threshold_percent": 10,
    "correlation_dominant_threshold": 0.5,
    "category_min_samples": 50,
    "category_imbalance_threshold": 0.5,
    "score_clustering_std_threshold": 1.0,
    "top_score_threshold": 8.5,
    "exposure_avg_threshold": 8.0
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `aesthetic_max_threshold` | `9.0` | Avisa se a estética máxima estiver abaixo disso |
| `aesthetic_target` | `9.5` | Meta para aesthetic_scale |
| `quality_avg_threshold` | `7.5` | Limiar de qualidade "alto valor" |
| `quality_weight_threshold_percent` | `10` | Avisa se o peso de qualidade ≤ este valor |
| `correlation_dominant_threshold` | `0.5` | Aviso de "sinal dominante" |
| `category_min_samples` | `50` | Mínimo de fotos por categoria |
| `category_imbalance_threshold` | `0.5` | Aviso de diferença de pontuação |
| `score_clustering_std_threshold` | `1.0` | Avisa se o desvio padrão < este valor |
| `top_score_threshold` | `8.5` | Avisa se o agregado máximo < este valor |
| `exposure_avg_threshold` | `8.0` | Avisa se a exposição média > este valor |

---

## Viewer

Exibição e comportamento da galeria web.

```json
{
  "viewer": {
    "default_category": "",
    "edition_password": "",
    "comparison_mode": {
      "min_comparisons_for_optimization": 50,
      "pair_selection_strategy": "learning",
      "candidate_pool_size": 200,
      "show_current_scores": true
    },
    "sort_options": { ... },
    "pagination": {
      "default_per_page": 64
    },
    "dropdowns": {
      "max_cameras": 50,
      "max_lenses": 50,
      "max_persons": 50,
      "max_tags": 20,
      "min_photos_for_person": 10
    },
    "persons": {
      "needs_naming_min_faces": 5
    },
    "raw_processor": {
      "backend": "rawpy",
      "darktable": {
        "executable": "darktable-cli",
        "hq": true,
        "width": null,
        "height": null,
        "extra_args": [],
        "cull_styles": [],
        "preview_max_edge": 1440,
        "preview_timeout_seconds": 60
      }
    },
    "display": {
      "tags_per_photo": 4,
      "card_width_px": 168,
      "image_width_px": 160,
      "image_jpeg_quality": 96,
      "thumbnail_slider": {
        "min_px": 120,
        "max_px": 400,
        "default_px": 168,
        "step_px": 8
      }
    },
    "face_thumbnails": {
      "output_size_px": 64,
      "jpeg_quality": 80,
      "crop_padding_ratio": 0.2,
      "min_crop_size_px": 20
    },
    "quality_thresholds": {
      "good": 6,
      "great": 7,
      "excellent": 8,
      "best": 9
    },
    "photo_types": {
      "top_picks_min_score": 7,
      "top_picks_min_face_ratio": 0.2,
      "top_picks_weights": {
        "aggregate_percent": 30,
        "aesthetic_percent": 28,
        "composition_percent": 18,
        "face_quality_percent": 24
      },
      "low_light_max_luminance": 0.2
    },
    "defaults": {
      "hide_blinks": true,
      "hide_bursts": true,
      "hide_duplicates": true,
      "hide_brackets": true,
      "hide_panoramas": true,
      "hide_details": true,
      "tooltip_mode": "panel",
      "hide_rejected": true,
      "sort": "aggregate",
      "sort_direction": "DESC",
      "type": "",
      "gallery_mode": "mosaic"
    },
    "cache_ttl_seconds": 3600,
    "notification_duration_ms": 2000,
    "moment_confidence_min": 0,
    "path_mapping": {}
  }
}
```

> **Nota:** `sort_options` (elidido como `{ ... }` acima) mapeia colunas do banco de dados para rótulos de menu suspenso e raramente é editado. O grupo **Conteúdo** inclui uma ordenação `{ "column": "narrative_moment_confidence", "label": "Moment Confidence" }` (NULLs ao final).

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `default_category` | `""` | Filtro de categoria padrão |
| `edition_password` | `""` | Senha para desbloquear o modo de edição; vazio = somente leitura (exceto sob `trusted_local_editing`) |
| `trusted_local_editing` | `false` | Concede direitos de edição, sem senha, a um navegador no mesmo computador. Veja [Edição Local Confiável](#edição-local-confiável) |
| `place_search_url` | `"https://photon.komoot.io/api"` | Endpoint do Photon por trás da pesquisa **Pesquisar online** da galeria; `""` a desativa. Veja [Pesquisa online de lugares](#pesquisa-online-de-lugares) |
| **comparison_mode** | | |
| `min_comparisons_for_optimization` | `50` | Comparações decisivas (empates excluídos) necessárias em uma categoria antes de sugerir pesos |
| `pair_selection_strategy` | `"learning"` | Estratégia de pares: `learning`, `uncertainty`, `boundary`, `active`, `random` |
| `candidate_pool_size` | `200` | Conjunto aleatório de candidatos dentro do qual a estratégia `learning` amostra os pares |
| `show_current_scores` | `true` | Mostra as pontuações durante a comparação |
| **pagination** | | |
| `default_per_page` | `64` | Fotos por página |
| **dropdowns** | | |
| `max_cameras` | `50` | Máximo de câmeras no menu suspenso |
| `max_lenses` | `50` | Máximo de lentes |
| `max_persons` | `50` | Máximo de pessoas |
| `max_tags` | `20` | Máximo de tags |
| `min_photos_for_person` | `10` | Oculta do menu suspenso pessoas com menos fotos |
| **persons** | | |
| `needs_naming_min_faces` | `5` | Mínimo de faces para que um cluster apareça em "Precisa de nome" de `/persons`; `1` lista todas as pessoas sem nome |
| **raw_processor** | | |
| `darktable.executable` | `"darktable-cli"` | Nome do binário darktable-cli ou caminho absoluto |
| `darktable.profiles` | `[]` | Array de perfis de exportação darktable nomeados (veja abaixo) |
| `darktable.profiles[].name` | *(obrigatório)* | Nome de exibição do perfil (usado no menu de download e no parâmetro `profile` da API) |
| `darktable.profiles[].hq` | `true` | Passa `--hq true` para exportação de alta qualidade |
| `darktable.profiles[].width` | *(omitir)* | Largura máxima de saída (omita para resolução total) |
| `darktable.profiles[].height` | *(omitir)* | Altura máxima de saída (omita para resolução total) |
| `darktable.profiles[].style` | *(omitir)* | Nome do estilo darktable aplicado durante a exportação (`--style`) |
| `darktable.profiles[].apply_custom_presets` | `true` | `false` passa `--apply-custom-presets false`, de modo que apenas o `style` explícito se aplica |
| `darktable.profiles[].extra_args` | `[]` | Argumentos de CLI adicionais (ex.: `["--style-overwrite"]`) |
| `darktable.cull_styles` | `[]` | Estilos darktable oferecidos como pré-visualização editada no laboratório de triagem; vazio oculta o seletor |
| `darktable.cull_styles[].name` | *(obrigatório)* | Nome do estilo darktable (passado a `--style`) |
| `darktable.cull_styles[].label_key` | *(name)* | Chave i18n opcional para o rótulo do menu (padrão: o nome do estilo) |
| `darktable.preview_max_edge` | `1440` | Borda máxima (px) do render da pré-visualização de seleção |
| `darktable.preview_timeout_seconds` | `60` | Tempo limite do darktable-cli por render de pré-visualização |
| **display** | | |
| `tags_per_photo` | `4` | Tags exibidas nos cartões |
| `card_width_px` | `168` | Largura do cartão |
| `image_width_px` | `160` | Largura da imagem |
| `image_jpeg_quality` | `96` | Qualidade JPEG para conversão de RAW/HEIF em `/api/download` e `/api/image` (1–100) |
| `thumbnail_slider.min_px` | `120` | Tamanho mínimo de miniatura (px) |
| `thumbnail_slider.max_px` | `400` | Tamanho máximo de miniatura (px) |
| `thumbnail_slider.default_px` | `168` | Tamanho padrão de miniatura (px) |
| `thumbnail_slider.step_px` | `8` | Incremento de passo do controle deslizante (px) |
| **face_thumbnails** | | |
| `output_size_px` | `64` | Tamanho da miniatura |
| `jpeg_quality` | `80` | Qualidade JPEG |
| `crop_padding_ratio` | `0.2` | Margem da face |
| `min_crop_size_px` | `20` | Tamanho mínimo do recorte |
| **quality_thresholds** | | |
| `good` | `6` | Limiar de "Bom" |
| `great` | `7` | Limiar de "Ótimo" |
| `excellent` | `8` | Limiar de "Excelente" |
| `best` | `9` | Limiar de "Melhor" |
| **photo_types** | | |
| `top_picks_min_score` | `7` | Mínimo de Top Picks |
| `top_picks_min_face_ratio` | `0.2` | Razão de face para os pesos |
| `low_light_max_luminance` | `0.2` | Limiar de pouca luz |
| **defaults** | | |
| `type` | `""` | Filtro de tipo de foto padrão (ex.: `"portraits"`, `"landscapes"`, ou `""` para Todas) |
| `sort` | `"aggregate"` | Coluna de ordenação padrão (uma ordenação lembrada pelo navegador prevalece; veja [Ordenação](VIEWER.md#ordenação)) |
| `sort_direction` | `"DESC"` | Direção de ordenação padrão (`"ASC"` ou `"DESC"`) |
| `hide_blinks` | `true` | Oculta fotos com piscar por padrão |
| `hide_bursts` | `true` | Mostra apenas a melhor da rajada por padrão |
| `hide_duplicates` | `true` | Oculta fotos duplicadas que não sejam a principal por padrão |
| `hide_brackets` | `true` | Mostra apenas a exposição base de cada bracketing por padrão |
| `hide_panoramas` | `true` | Mostrar por padrão apenas um quadro representativo por panorâmica |
| `hide_details` | `true` | Oculta os detalhes da foto nos cartões por padrão |
| `tooltip_mode` | `"panel"` | Gatilho do tooltip: `"hover"`, `"click"`, `"off"` ou `"panel"` (barra fixada); substitui `hide_tooltip` |
| `panel_activation` | `"both"` | Gesto que muda a foto da barra fixada no modo `"panel"`: `"hover"`, `"click"` ou `"both"` |
| `hide_rejected` | `true` | Oculta fotos rejeitadas por padrão |
| `gallery_mode` | `"mosaic"` | Layout padrão da galeria (`"grid"` ou `"mosaic"`) |
| **allowed_origins** | | |
| `allowed_origins` | `["http://localhost:4200", "http://localhost:5000"]` | Origens permitidas de CORS; adicione seu domínio ou URL de proxy reverso ao hospedar remotamente |
| **security_headers** | | |
| `security_headers.content_security_policy` | _(padrão seguro para SPA)_ | Cabeçalho Content-Security-Policy; `""` o desativa, ou forneça uma política mais estrita |
| `security_headers.hsts` | `false` | Envia `Strict-Transport-Security`. Habilite apenas quando o visualizador for servido por HTTPS. |
| **Outros** | | |
| `cache_ttl_seconds` | `3600` | TTL dos caches em memória de estatísticas/consultas; mantenha-o maior que um cálculo completo de estatísticas (pode demorar minutos) |
| `notification_duration_ms` | `2000` | Duração do toast |
| `moment_confidence_min` | `0` | Rótulos de momento abaixo desta confiança (0–1) são renderizados esmaecidos com "(incerto)"; `0` = nunca esmaecer |

Notas:
- **`trusted_local_editing`** só se aplica enquanto `password` e `edition_password` estiverem vazias em uma instalação de usuário único. Cobre todas as rotas sujeitas a edição, o disparo da varredura incluído, e permite que a caixa «Ligar um assistente» crie um token de assistente com edição completa para as requisições `/mcp` do mesmo computador.

> **Aviso:** nunca ative `trusted_local_editing` atrás de um proxy reverso no mesmo host.

- **`pair_selection_strategy`:** `learning` escolhe primeiro pares diversos e depois pares que o modelo classifica de forma inconsistente.
- **`darktable.cull_styles`** alimentam `GET /api/photo/cull_preview`. Cada estilo **tem de já existir** na configuração darktable do usuário que executa o visualizador.
- A Content-Security-Policy padrão permite os recursos próprios da SPA: script/estilo de tema inline, Google Fonts, tiles do OpenStreetMap e a API de mesma origem.
- `moment_confidence_min` esmaece os rótulos no cabeçalho de Cenas, no cabeçalho de grupo de cena da Triagem e na dica da foto na galeria.
### Selos do cartão e recorte

`viewer.badges` liga e desliga cada selo do cartão da galeria. Os selos mais antigos valem `true` por padrão, portanto omitir o bloco não muda nada.

```json
{
  "viewer": {
    "badges": {
      "favorite": true,
      "star_rating": true,
      "rejected": true,
      "sequence_kind": true,
      "sequence_override_pending": true,
      "stack": true,
      "keeper_hint": true,
      "best_of_burst": true,
      "clipping_highlight": true,
      "clipping_shadow": false
    },
    "clipping": {
      "badge_percent": 5,
      "indicator_percent": 1,
      "histogram_mode": "rgb",
      "tooltip_histogram_mode": "luma"
    }
  }
}
```

| Chave | Padrão | Descrição |
|-------|--------------|-----------|
| `badges.favorite` | `true` | Selo de coração em uma foto favorita (modo de edição) |
| `badges.star_rating` | `true` | Selo de estrela e contador em uma foto classificada (modo de edição) |
| `badges.rejected` | `true` | Selo de polegar para baixo em uma foto rejeitada (modo de edição) |
| `badges.sequence_kind` | `true` | Selo do conjunto (rajada/bracketing/panorama/duplicado), visível enquanto a opção de ocultar correspondente recolhe o conjunto |
| `badges.sequence_override_pending` | `true` | Selo de relógio para uma correção de panorama à espera da próxima detecção |
| `badges.stack` | `true` | Selo de camadas com o número de membros nos cartões de uma pilha de fotos manual; um clique abre a pilha |
| `badges.keeper_hint` | `true` | Seta «existe uma foto melhor neste grupo» do modelo de seleção aprendido |
| `badges.best_of_burst` | `true` | Selo «Melhor» na foto principal de uma rajada, visível apenas quando `hide_bursts` está desativado |
| `badges.clipping_highlight` | `true` | Selo em uma foto cujas altas luzes ultrapassam `clipping.badge_percent` |
| `badges.clipping_shadow` | `false` | O mesmo para sombras empastadas (desativado: o recorte de sombras é muitas vezes intencional em silhuetas, noite, low-key) |

Desativar `badges.stack` oculta apenas o selo; o botão de cartão «Abrir pilha de fotos» continua funcionando.

`viewer.clipping` define «recortado» uma única vez para o selo do cartão, os marcadores do histograma e o filtro da galeria.

| Chave | Padrão | Descrição |
|-------|--------------|-----------|
| `badge_percent` | `5` | Porcentagem de pixels, no pior dos canais R/G/B, acima da qual o cartão recebe selo (cerca de 1 foto em 25 em uma amostra) |
| `indicator_percent` | `1` | Limiar dos marcadores R/G/B próprios do histograma |
| `histogram_mode` | `"rgb"` | Padrão do histograma do **painel de detalhe**: `"luma"`, `"rgb"`, `"r"`, `"g"` ou `"b"` |
| `tooltip_histogram_mode` | `"luma"` | Padrão da aba Histograma do **painel lateral** (`tooltip_mode: "panel"`), os mesmos cinco valores |

Notas:
- A escolha de histograma do próprio usuário fica em `localStorage` (`facet_histogram_mode`, `facet_histogram_mode_tooltip`) e prevalece sobre estes padrões. As duas configurações são independentes.
- As bolhas **Passar o mouse** e **Clicar** não mostram histograma.

**O recorte é medido por canal, exatamente nos bins 0 e 255.** Fica em `photos.channel_clip_shadow_pct` / `channel_clip_highlight_pct` como a porcentagem de pixels do pior canal. É diferente dos indicadores `shadow_clipped` / `highlight_clipped`, que cobrem as faixas de luminância 0–30 e 225–255 e alimentam `exposure_score`.

**`NULL` significa desconhecido, nunca limpo.** Uma foto com um histograma armazenado mais antigo não tem dados de canal, por isso não leva selo e não corresponde a nenhum lado do filtro da galeria. `python facet.py --backfill-clipping` preenche as colunas a partir dos histogramas armazenados; não descodifica imagens e é retomável.

### Recursos

Ative/desative recursos opcionais para reduzir o uso de memória ou simplificar a interface:

```json
{
  "viewer": {
    "features": {
      "show_similar_button": true,
      "show_merge_suggestions": true,
      "show_rating_controls": true,
      "show_memories": true,
      "show_captions": true,
      "show_timeline": true,
      "show_map": true,
      "show_scenes": true,
      "show_my_taste": true
    }
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `show_similar_button` | `true` | Mostra o botão "Encontrar Similares" nos cartões de foto (usa numpy para similaridade CLIP) |
| `show_merge_suggestions` | `true` | Ativa o recurso de sugestões de mesclagem na página de gerenciamento de pessoas |
| `show_rating_controls` | `true` | Mostra os controles de avaliação por estrelas e favoritos |
| `show_scan_button` | `false` | Mostra o botão de disparo de escaneamento (não requer GPU; veja as notas) |
| `metrics_enabled` | `false` | Ativa o endpoint público Prometheus `GET /metrics` (veja o aviso abaixo) |
| `show_semantic_search` | `true` | Mostra a barra de busca semântica (busca de texto para imagem usando embeddings CLIP/SigLIP) |
| `show_albums` | `true` | Mostra o recurso de álbuns (criar, gerenciar e navegar por álbuns de fotos) |
| `show_critique` | `true` | Mostra o botão de crítica por IA nos cartões de foto (detalhamento de pontuação baseado em regras) |
| `show_vlm_critique` | `true` | Ativa a crítica com VLM (perfil 16gb/24gb); `false` quando a chave está ausente |
| `show_embed_metadata` | `true` | Mostra "Gravar metadados no arquivo" no modo de edição (embute avaliações/palavras-chave via exiftool) |
| `show_memories` | `true` | Mostra o diálogo de memórias "Neste Dia" (fotos tiradas na mesma data em anos anteriores) |
| `show_captions` | `true` | Mostra as legendas geradas por IA nos cartões de foto |
| `show_timeline` | `true` | Mostra a visualização de linha do tempo para navegação cronológica com navegação por data |
| `show_map` | `true` | Mostra a visualização de mapa por GPS (requer Leaflet); `false` quando a chave está ausente |
| `show_capsules` | `true` | Mostra a visualização de Cápsulas (diaporamas de fotos curados e agrupados por tema) |
| `show_folders` | `true` | Mostra a navegação por pastas da estrutura de diretórios das fotos |
| `show_scenes` | `true` | Mostra a visualização de Cenas (`/scenes`), fotos principais de rajada agrupadas em cenas cronológicas |
| `show_my_taste` | `true` | Mostra a ordenação "My Taste" do ranqueador pessoal, com um selo confiável |
| `show_social_export` | `true` | Mostra o menu de download **Recorte social** (somente edição). Veja [Exportação social](#exportação-social) |
| `show_portfolio_export` | `true` | Mostra a ação de álbum **Exportar portefólio** (somente edição). Veja [Exportação de portfólio](#exportação-de-portfólio) |
| `show_proofing` | `false` | Ativa a aprovação de cliente em álbuns compartilhados. Veja [Aprovação de Cliente](#aprovação-de-cliente) |

Notas:
- **`show_scan_button`:** visível ao superadmin no modo multiusuário, ou a uma sessão de edição desbloqueada no modo de usuário único. As varreduras rodam apenas na CPU com o perfil `legacy`. Uma sessão local confiável (`trusted_local_editing`) pode varrer sem ele.
- **Otimização de memória:** `show_similar_button: false` evita que o numpy seja carregado, o que reduz a memória do visualizador.

> **Aviso:** `metrics_enabled` expõe contagens de fotos/pessoas/faces, tamanho do banco de dados e memória do processo. Habilite-o apenas onde a rede do coletor o alcance, nunca na internet pública.
### Aprovação de Cliente

`viewer.features.show_proofing` (padrão `false`) transforma qualquer álbum compartilhado em uma página de aprovação de cliente. Um cliente com o link de compartilhamento (e o `viewer.proofing.pin` opcional) pode curtir fotos e deixar comentários sem conta. O dono os revisa em um diálogo restrito à edição no cartão do álbum. As escolhas do cliente nunca tocam as avaliações do dono nem treinam o ranqueador pessoal.

```json
{
  "viewer": {
    "features": { "show_proofing": false },
    "proofing": {
      "pin": "",
      "session_minutes": 1440
    }
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `features.show_proofing` | `false` | Interruptor mestre para a aprovação de cliente em álbuns compartilhados |
| `proofing.pin` | `""` | PIN opcional que o cliente deve inserir com o link de compartilhamento; vazio = sem PIN (as tentativas têm limite de taxa) |
| `proofing.session_minutes` | `1440` | Tempo de vida da sessão do cliente em minutos (24h); termina de imediato se o álbum deixa de ser compartilhado ou a aprovação é desativada |

### Mapeamento de Caminhos

Mapeia caminhos do banco de dados para caminhos locais, para quando as fotos foram pontuadas em uma máquina (ex.: Windows com caminhos UNC) e o visualizador roda em outra (ex.: um NAS Linux).

```json
{
  "viewer": {
    "path_mapping": {
      "\\\\NAS\\Photos": "/mnt/photos",
      "D:\\Pictures": "/volume1/pictures"
    }
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `path_mapping` | `{}` | Prefixo de origem → prefixo de destino, aplicado ao ler arquivos do disco |

**Como funciona:**
- Aplica-se apenas ao **ler arquivos do disco** (imagens em tamanho completo, downloads, crítica VLM). Os caminhos do banco de dados nunca são modificados.
- Barras invertidas e barras normais são normalizadas: `\\NAS\Photos\img.jpg` e `//NAS/Photos/img.jpg` correspondem ambos.
- Os mapeamentos são avaliados em ordem; o primeiro prefixo correspondente vence.
- Os destinos de mapeamento são incluídos automaticamente na lista de permissões de diretórios do modo multiusuário.

**Exemplo:** Um banco de dados populado no Windows armazena caminhos como `\\NAS\Photos\2024\IMG_001.jpg`. No Linux, o mesmo compartilhamento é montado em `/mnt/nas/Photos`. Configure:

```json
"path_mapping": {"\\\\NAS\\Photos": "/mnt/nas/Photos"}
```

### Proteção por Senha

Proteção por senha opcional para o visualizador:

```json
{
  "viewer": {
    "password": "your-password-here"
  }
}
```

Quando definida, os usuários precisam entrar antes de usar o visualizador.

### Edição Local Confiável

Permite que um visualizador de usuário único, usado apenas a partir de um navegador no mesmo computador, edite sem senha de edição:

```json
{
  "viewer": {
    "trusted_local_editing": true
  }
}
```

Só se aplica enquanto **tanto** `viewer.password` **quanto** `viewer.edition_password` estiverem vazias, o modo multiusuário estiver desativado e a configuração tiver sido carregada sem erros. Definir uma senha de edição a desativa. Não define nem revela nenhuma senha, não altera tokens nem habilita a administração multiusuário.

O Facet verifica cada requisição. Uma requisição só é confiável quando todas estas condições valem:

- o par TCP é um endereço de loopback (um par IPv4 mapeado como `::ffff:127.0.0.1` é avaliado pelo seu endereço IPv4);
- há exatamente um cabeçalho `Host`, e ele é `localhost`, `127.0.0.1` ou `[::1]`, com uma porta opcional;
- a requisição não traz nenhum cabeçalho `Forwarded`, `Via`, `X-Real-IP`, `X-Client-IP`, `True-Client-IP`, `CF-Connecting-IP`, `X-Original-Forwarded-For` nem `X-Forwarded-*`;
- um `Origin` ou `Referer`, se presente, indica exatamente o esquema, o host e a porta, sem credenciais (um `Origin` com caminho, consulta ou fragmento é recusado); um `Sec-Fetch-Site`, se presente, é `same-origin` ou `none`.

Qualquer outra requisição é tratada como se a opção estivesse desativada, requisições GET incluídas.

Uma requisição confiável tem direitos de edição completos em toda rota sujeita a edição: avaliações, comparações, seleção (incluindo **Selecionar para pasta**, que move arquivos ou os envia para a lixeira, e a exclusão por foto), álbuns, pessoas e rostos, pesos, prioridades e contextos de pontuação, incorporação de metadados e exportações, jobs de recálculo e de panoramas, e a geração de legendas e críticas. Também pode varrer sem `viewer.features.show_scan_button`. O fluxo de progresso da varredura só aceita um token de fluxo local confiável vindo da mesma máquina local.

**Assistentes.** A caixa «Ligar um assistente» pode então criar um token de **Edição completa** (ainda requer `viewer.mcp.enabled`).

- O token é `edition` apenas para requisições `/mcp` que passam as verificações acima: `http://localhost:<port>` ou `127.0.0.1`, em `:5000` ou no proxy de desenvolvimento do `ng serve` `:4200`.
- A partir de um cliente da rede local, de um URL com nome de host ou `0.0.0.0`, ou em uma implantação Docker, passa a `readonly`. Definir qualquer senha também o torna `readonly`; removê-la o restaura.
- As ferramentas de exclusão continuam precisando de `viewer.mcp.allow_destructive`. Veja [Agentes de IA (MCP)](AGENTS.md).
- Em uma instalação aberta, criar, listar e revogar tokens do assistente só funciona com um pedido que passe estas verificações (ou em uma sessão de edição quando `viewer.edition_password` está definido), seja qual for o valor de `trusted_local_editing`.
- `ng serve --host 0.0.0.0`, ou um proxy no mesmo host que não adicione cabeçalho de encaminhamento, deixa passar um cliente da rede local que envie `Host: localhost`. Um proxy inverso tem de enviar `X-Forwarded-For` ou `Forwarded`.

> **Aviso:** apenas a verificação de loopback é uma fronteira real; os demais cabeçalhos vêm do cliente. Um proxy reverso, túnel ou redirecionamento de porta no mesmo host que não adicione nenhum dos cabeçalhos acima é indistinguível do seu navegador. Nunca ative esta opção atrás de qualquer proxy reverso no mesmo host. Enquanto estiver ativa, qualquer processo local e qualquer conta do computador pode editar.
### Pesquisa online de lugares

`viewer.place_search_url` tem como padrão `https://photon.komoot.io/api`.

- Defina `""` para desativar a pesquisa de endereços e estabelecimentos, ou aponte-o para um endpoint HTTP(S) do Photon auto-hospedado (sem credenciais, parâmetros de consulta nem fragmento).
- O navegador só recebe `place_search_enabled`, nunca a URL.
- As pesquisas exigem acesso de edição e um clique explícito em **Pesquisar online**. Não há novas tentativas nem redirecionamentos.
- Uma requisição expira após cinco segundos; a resolução DNS segue o resolvedor do sistema operacional e pode demorar mais.

Veja [Pesquisa online de lugares](VIEWER.md#pesquisa-online-de-locais) para privacidade, cache e limites. A [política da demo do Photon](https://github.com/komoot/photon#demo-server) permite uso razoável do projeto sem garantia de disponibilidade; a [documentação da API do Photon](https://github.com/komoot/photon/blob/master/docs/api-v1.md) define seu formato GeoJSON.
### Desempenho do Visualizador

Sobrescreve as configurações globais de `performance` apenas para o visualizador, p. ex. em um NAS com pouca memória.

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

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `mmap_size_mb` | *(global)* | Override do tamanho de mmap do SQLite para conexões do visualizador. `0` desativa o mmap. |
| `cache_size_mb` | *(global)* | Override do tamanho de cache do SQLite para conexões do visualizador |
| `pool_size` | `5` | Tamanho do pool de conexões (reduza para sistemas com pouca memória) |
| `thumbnail_cache_size` | `2000` | Máximo de entradas no cache em memória de redimensionamento de miniaturas |

Quando não definido, o visualizador usa os valores globais de `performance`. Veja [Implantação](DEPLOYMENT.md) para as configurações de NAS recomendadas.

---

## Performance

Configurações de desempenho do banco de dados.

```json
{
  "performance": {
    "mmap_size_mb": 2048,
    "cache_size_mb": 128,
    "slow_request_ms": 1000
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `mmap_size_mb` | `2048` | Tamanho de E/S mapeada em memória do SQLite |
| `cache_size_mb` | `128` | Tamanho do cache do SQLite |
| `wal_checkpoint_minutes` | `30` | Opcional (ausente no arquivo distribuído). Minutos entre os checkpoints do WAL em segundo plano do visualizador; `0` os desativa |
| `slow_request_ms` | `1000` | Registra requisições da API do visualizador mais lentas que isto (WARNING, marcador `SLOW`); `0` desativa |

O checkpoint periódico (`PRAGMA wal_checkpoint(TRUNCATE)`) mantém o arquivo WAL pequeno em instalações de longa duração; um checkpoint também é executado em um encerramento limpo.

---

## Storage

Onde as miniaturas e os embeddings são armazenados: colunas BLOB no banco de dados SQLite (padrão) ou arquivos em disco, para manter o banco de dados menor.

```json
{
  "storage": {
    "mode": "database",
    "filesystem_path": "./storage"
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `mode` | `"database"` | Backend de armazenamento: `"database"` (BLOBs SQLite) ou `"filesystem"` (arquivos em disco) |
| `filesystem_path` | `"./storage"` | Diretório base para o modo de sistema de arquivos (`<path>/thumbnails/` e `<path>/embeddings/`) |

**Detalhes do modo de sistema de arquivos:**
- Os arquivos são nomeados pelo hash SHA-256 do caminho da foto, em subdiretórios de dois caracteres (ex.: `thumbnails/a3/a3f8..._640.jpg`).
- Excluir uma foto remove todos os tamanhos de miniatura e arquivos de embedding associados.
- O diretório é criado automaticamente no primeiro uso.

---

## Plugins

Sistema de plugins orientado a eventos para reagir a eventos de pontuação. Os plugins podem ser módulos Python, webhooks ou ações integradas.

### Configuração

```json
{
  "plugins": {
    "enabled": true,
    "high_score_threshold": 8.0,
    "webhooks": [
      {
        "url": "https://example.com/hook",
        "events": ["on_score_complete", "on_high_score"],
        "min_score": 8.0
      }
    ],
    "actions": {
      "copy_high_scores": {
        "event": "on_high_score",
        "action": "copy_to_folder",
        "folder": "/path/to/best-photos",
        "min_score": 9.0
      }
    }
  }
}
```

| Chave | Padrão | Descrição |
|-------|--------|-----------|
| `enabled` | `false` | Interruptor mestre — quando falso, nenhum evento é emitido |
| `high_score_threshold` | `8.0` | Pontuação agregada mínima para disparar eventos `on_high_score` |
| `webhooks` | `[]` | Lista de endpoints de webhook que recebem cargas úteis JSON via POST |
| `actions` | `{}` | Ações integradas nomeadas disparadas por eventos |

### Eventos Suportados

| Evento | Gatilho | Carga útil |
|--------|---------|------------|
| `on_score_complete` | Após cada foto ser pontuada | `path`, `filename`, `aggregate`, `aesthetic`, `comp_score`, `category`, `tags` |
| `on_new_photo` | Quando uma foto entra no banco de dados | Igual a `on_score_complete` |
| `on_high_score` | Quando o agregado ≥ `high_score_threshold` | Igual a `on_score_complete` |
| `on_burst_detected` | Quando um grupo de rajada é identificado | `burst_group_id`, `photo_count`, `best_path`, `paths` |

### Escrevendo um Plugin

Coloque um arquivo `.py` no diretório `plugins/`. Defina funções nomeadas conforme os eventos que você deseja tratar:

```python
def on_score_complete(data: dict) -> None:
    print(f"Scored: {data['path']} — {data['aggregate']:.1f}")

def on_high_score(data: dict) -> None:
    print(f"High score! {data['path']} — {data['aggregate']:.1f}")
```

Veja `plugins/example_plugin.py.example` para a interface completa.

### Webhooks

Cada webhook recebe um POST JSON. Endereços privados e de loopback são bloqueados:

```json
{
  "event": "on_high_score",
  "data": {
    "path": "/photos/IMG_001.jpg",
    "aggregate": 9.2,
    "aesthetic": 9.5,
    "comp_score": 8.8,
    "category": "portrait",
    "tags": "person, outdoor"
  }
}
```

Opções de webhook: `url` (obrigatório), `events` (lista de nomes de eventos), `min_score` (agregado mínimo para disparar).

### Ações Integradas

| Ação | Descrição | Opções |
|------|-----------|--------|
| `copy_to_folder` | Copia a foto para uma pasta | `folder`, `min_score` |
| `send_notification` | Registra uma notificação | `min_score` |

### Endpoints da API

| Método | Caminho | Descrição |
|--------|---------|-----------|
| `GET` | `/api/plugins` | Lista os plugins, webhooks e ações carregados |
| `POST` | `/api/plugins/test-webhook` | Envia uma carga útil de teste para uma URL de webhook |

---

## Capsules

Diaporamas (slideshows) curados e agrupados por tema, gerados a partir da sua biblioteca e armazenados em cache por `freshness_hours`.

```json
{
  "capsules": {
    "min_aggregate": 6.0,
    "max_photos_per_capsule": 40,
    "max_photo_overlap": 0.2,
    "mmr_lambda": 0.5,
    "mmr_moment_weight": 0.0,
    "freshness_hours": 24,
    "reverse_geocoding": true,
    "journey": {
      "min_distance_km": 50,
      "min_photos": 8,
      "time_gap_hours": 24
    },
    "faces_of": { "min_photos": 10 },
    "seasonal": { "min_photos": 10 },
    "golden": { "percentile": 99, "max_photos": 50 },
    "color_story": { "embedding_threshold": 0.75, "min_group_size": 8, "max_groups": 5 },
    "this_week_years_ago": { "min_photos_per_year": 3 },
    "monthly": { "min_photos": 8 },
    "yearly": { "min_photos": 20, "max_photos": 60 },
    "camera": { "min_photos": 15 },
    "tag_collection": { "min_photos": 15 },
    "seeded": {
      "num_seeds": 10,
      "min_photos": 8,
      "seed_lifetime_minutes": 1440,
      "time_window_days": 7,
      "embedding_threshold": 0.7,
      "location_radius_km": 30
    },
    "progress": { "min_improvement_pct": 5, "min_photos": 10, "period_months": 3 },
    "color_palette": { "min_photos": 8 },
    "rare_pair": { "max_shared_photos": 5, "min_score": 7.0, "min_photos": 3 }
  }
}
```

### Configurações Globais

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `min_aggregate` | `6.0` | Pontuação agregada mínima para que as fotos sejam incluídas nas cápsulas |
| `max_photos_per_capsule` | `40` | Máximo de fotos por cápsula (diversidade MMR aplicada acima de 5) |
| `max_photo_overlap` | `0.2` | Fração máxima de fotos compartilhadas entre duas cápsulas antes que a deduplicação remova uma |
| `mmr_lambda` | `0.5` | Peso de diversidade do MMR: 0=maximizar diversidade, 1=maximizar qualidade |
| `mmr_moment_weight` | `0.0` | Peso opcional que mescla o `narrative_moment_confidence` de cada foto na seleção MMR da cápsula. `0.0` = comportamento inalterado |
| `freshness_hours` | `24` | TTL do cache e período de rotação para fotos de capa e cápsulas com seed |
| `reverse_geocoding` | `true` | Ativa a geocodificação reversa offline para títulos de cápsulas de localização/jornada (requer o pacote `reverse_geocoder`) |

### Tipos de Cápsula

| Tipo | Descrição |
|------|-----------|
| `journey` | Viagens detectadas por agrupamento de GPS + lacunas temporais. Os títulos incluem o nome do destino quando a geocodificação está ativada. |
| `faces_of` | Melhores fotos de cada pessoa reconhecida |
| `seasonal` | Fotos agrupadas por estação + ano |
| `golden` | Top 1% por pontuação agregada |
| `color_story` | Grupos visualmente similares via agrupamento de embeddings CLIP |
| `this_week` | "Esta Semana, Anos Atrás" — "Neste Dia" estendido por ±3 dias |
| `location` | Clusters de fotos geotagueadas com nomes de lugares por geocodificação reversa |
| `person_pair` | Pares de pessoas nomeadas que aparecem juntas |
| `seeded` | Descoberta baseada em seed por tempo, similaridade, pessoa, tag, localização, clima |
| `progress` | "Sua Fotografia Está Melhorando" a partir de tendências trimestrais de pontuação |
| `color_palette` | "Cor do Mês" a partir de perfis de saturação/monocromático |
| `rare_pair` | Pares de pessoas pouco frequentes em fotos de alta pontuação |
| `favorites` | Fotos favoritadas agrupadas por ano e estação |

### Cápsulas Baseadas em Dimensão

Geradas automaticamente a partir das colunas do banco de dados:

| Dimensão | Agrupa Por |
|----------|------------|
| `year` | Ano extraído de date_taken |
| `month` | Ano-mês extraído de date_taken |
| `week` | Ano-semana extraído de date_taken |
| `camera` | Modelo da câmera |
| `lens` | Modelo da lente |
| `tag` | Tags da foto (requer a tabela `photo_tags`) |
| `day_of_week` | Dia da semana (domingo–sábado) |
| `composition` | Padrão de composição SAMP-Net (rule_of_thirds, horizontal, etc.) |
| `focal_range` | Faixas de distância focal: ultra wide (<24mm), wide (24–35mm), standard (36–70mm), portrait (71–135mm), telephoto (136–300mm), super telephoto (300mm+) |
| `category` | Categoria de conteúdo da foto (portrait, landscape, street, etc.) |
| `time_of_day` | Faixas de horário: golden morning, morning, midday, afternoon, golden evening, night |
| `star_rating` | Avaliações por estrelas do usuário (1–5 estrelas) |

Combinações entre dimensões também são geradas (ex.: camera × year, focal_range × category, category × year).

### Transições do Slideshow

Cada tipo de cápsula mapeia para uma transição de slide temática:

| Transição | Usada Por | Efeito |
|-----------|-----------|--------|
| `crossfade` | Padrão | Troca de opacidade em 300ms |
| `slide` | journey, location, this_week | Desliza da direita (500ms) |
| `zoom` | faces_of, color_story | Escala 1,05→1,0 com fade (400ms) |
| `kenburns` | golden, seasonal, star_rating, favorites | Zoom lento 1,0→1,08 ao longo da duração do slide |

### Geocodificação Reversa

As cápsulas de localização e jornada usam geocodificação reversa offline por meio do pacote `reverse_geocoder` (conjunto de dados GeoNames local, ~30MB, sem chamadas de API). Os resultados são armazenados em cache em resolução de grade de 0,1° (~11km).

Instale: `pip install reverse_geocoder`

Defina `"reverse_geocoding": false` para desativar e recorrer à exibição de coordenadas.

## Similarity Groups

Configurações da seleção de fotos similares, que agrupa fotos visualmente similares por embedding CLIP/SigLIP:

```json
{
  "similarity_groups": {
    "default_threshold": 0.85,
    "min_group_size": 2,
    "max_photos": 10000,
    "max_group_size": 50
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `default_threshold` | `0.85` | Similaridade de cosseno mínima (0,0–1,0) para duas fotos contarem como similares; menor = grupos maiores e mais frouxos |
| `min_group_size` | `2` | Número mínimo de fotos necessário para formar um grupo de similaridade |
| `max_photos` | `10000` | Máximo de fotos carregadas para a comparação (o custo cresce como O(n²)) |
| `max_group_size` | `50` | Máximo de fotos por grupo; grupos maiores são divididos |

## Auto-Cull

Triagem automática de um botão só para o laboratório de triagem (`POST /api/culling/auto`, restrito à edição). Ela tria um escopo inteiro em uma única passagem: todos os grupos, ou apenas rajadas / semelhantes / cenas, opcionalmente restrito a um álbum ou janela de datas. Cada grupo mantém sua melhor foto mais tudo dentro de uma margem definida pelo rigor (como no controle deslizante do laboratório), com um mínimo por grupo, e rejeita o resto.

```json
{
  "auto_cull": {
    "default_strictness": 50,
    "highlights_min": 8.0
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `default_strictness` | `50` | Orçamento de fotos mantidas (0–100) quando a requisição omite `strictness`; maior = menos fotos mantidas por grupo |
| `highlights_min` | `8.0` | Pontuação agregada mínima para a melhor foto de um grupo entrar no álbum opcional **Highlights** ao aplicar |

- `dry_run` vem ativado por padrão e retorna uma prévia de manter/rejeitar por grupo.
- Aplicar registra comparações `source='culling'` e conta para um re-treinamento automático. Veja [Visualizador Web — Triagem automática](VIEWER.md#seleção-automática).
- A mesma configuração alimenta `python facet.py --auto-cull` (veja [Triagem pelo terminal](COMMANDS.md#triagem-pelo-terminal)); suas regras são lidas da configuração do servidor, não de `--config`.

## Re-treinamento automático

Controla quando o classificador pessoal («Meu gosto») se re-treina. Cada confirmação de triagem e cada mudança de avaliação incrementa um contador por usuário. Ultrapassar `threshold` arma o re-treinamento, que começa quando você fica inativo por `idle_seconds`, de modo que ele não atrapalha suas avaliações.

```json
{
  "auto_retrain": {
    "threshold": 25,
    "idle_seconds": 60,
    "backend": "native"
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `threshold` | `25` | Novas comparações necessárias antes de armar um re-treinamento; aumente se você avalia lotes muito grandes |
| `idle_seconds` | `60` | Segundos sem atividade de avaliação/triagem antes que o re-treinamento armado comece; `0` o inicia imediatamente |
| `backend` | `"native"` | `"native"` treina localmente; `"external"` apenas mantém as preferências e as contagens. Veja [Backend de aprendizado externo](#backend-de-aprendizado-externo) |

Variáveis de ambiente substituem `threshold` e `idle_seconds` (úteis no Docker):

```bash
FACET_RETRAIN_THRESHOLD=100 FACET_RETRAIN_IDLE_S=300 python viewer.py
```

| Variável | Sobrescreve |
|----------|-------------|
| `FACET_RETRAIN_THRESHOLD` | `auto_retrain.threshold` |
| `FACET_RETRAIN_IDLE_S` | `auto_retrain.idle_seconds` |

- Um `threshold` ou `idle_seconds` inválido recai no valor do JSON e depois no padrão embutido. Ambos são lidos na inicialização; alterá-los exige um reinício.
- Um `auto_retrain.backend` inválido recai em `"external"` (veja abaixo).
- Um re-treinamento que não supera o modelo atual em dados reservados não grava nada.

### Backend de aprendizado externo

`"backend": "external"` mantém avaliações, comparações e contagens pendentes, mas nunca treina nem avalia localmente o classificador pessoal, a cabeça de seleção ou os pesos aprendidos. Use-o quando um fluxo separado, controlado pelo operador, treina e publica as pontuações. O Facet não inicia nenhum worker externo.

No modo externo:
- Os comandos manuais do classificador pessoal, da cabeça de seleção e do aprendizado de pesos informam que o treinamento foi adiado.
- As probabilidades de seleção não estão disponíveis; as respostas de Comparar (pesos aprendidos e confiança) informam `available: false`.
- A pontuação normal das fotos e os votos não são afetados.

Um bloco `auto_retrain` malformado, um `backend` diferente de `"native"` ou `"external"`, ou uma configuração ilegível selecionam o modo externo e registram um aviso. Uma configuração válida sem a chave `backend` usa o modo nativo.

## Perfis de seleção por gênero

Padrões por gênero que definem todos os controles de seleção em um clique, a partir de um seletor no laboratório de triagem. Esportes mantém apenas o quadro mais nítido de uma longa rajada; casamentos mantêm mais variantes e exigem olhos abertos; shows relaxam os limiares de olhos/expressão; a vida selvagem remove o filtro de rosto.

```json
{
  "cull_profiles": {
    "default": "balanced",
    "profiles": {
      "balanced": { "label_key": "culling.profiles.balanced", "strictness": 50, "eyes_closed_max": 4.0, "poor_expression_min": 4.0, "keep_min_per_group": 1, "similarity_threshold": 85 },
      "wedding":  { "label_key": "culling.profiles.wedding",  "strictness": 35, "eyes_closed_max": 5.0, "poor_expression_min": 5.0, "keep_min_per_group": 2, "similarity_threshold": 90 },
      "sports":   { "label_key": "culling.profiles.sports",   "strictness": 85, "eyes_closed_max": 2.0, "poor_expression_min": 0.0, "keep_min_per_group": 1, "similarity_threshold": 80 },
      "concert":  { "label_key": "culling.profiles.concert",  "strictness": 55, "eyes_closed_max": 2.0, "poor_expression_min": 0.0, "keep_min_per_group": 1, "similarity_threshold": 85 },
      "wildlife": { "label_key": "culling.profiles.wildlife", "strictness": 70, "eyes_closed_max": 0.0, "poor_expression_min": 0.0, "keep_min_per_group": 1, "similarity_threshold": 82 }
    }
  }
}
```

| Configuração | Descrição |
|---|---|
| `default` | Id do perfil aplicado quando nenhum está armazenado no cliente |
| `profiles.<id>.label_key` | Caminho i18n do nome exibido do padrão (`culling.profiles.*`) |
| `profiles.<id>.strictness` | Orçamento de fotos mantidas (0–100) da auto-seleção com este padrão |
| `profiles.<id>.eyes_closed_max` | Pontuação de olhos abertos (0–10) igual ou abaixo da qual um rosto conta como fechado (substitui `face_detection.eyes_closed_max`) |
| `profiles.<id>.poor_expression_min` | Pontuação de expressão/sorriso (0–10) abaixo da qual um rosto conta como ruim (substitui `face_detection.poor_expression_min`) |
| `profiles.<id>.keep_min_per_group` | Mínimo por grupo do conjunto mantido pela auto-seleção |
| `profiles.<id>.similarity_threshold` | Limiar de agrupamento por similaridade (porcentagem) aplicado pela câmara escura quando o padrão é selecionada |

`GET /api/culling/profiles` retorna a lista ordenada de padrões e o padrão. `POST /api/culling/auto` e `POST /api/culling-group/faces` aceitam um id `profile` opcional; um `strictness`/`min_keep_per_group` explícito na requisição prevalece sobre o padrão.

## Scenes

Configurações da visualização de Cenas, que agrupa fotos principais de rajada em cenas cronológicas (divididas por lacunas no tempo de captura) para seleção em ordem narrativa:

```json
{
  "scenes": {
    "gap_minutes": 20.0,
    "min_size": 2,
    "max_photos": 5000,
    "max_scene_size": 60,
    "adaptive": true,
    "adaptive_k": 6.0
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `gap_minutes` | `20.0` | Intervalo entre fotos principais de rajada consecutivas que inicia uma nova cena (o piso quando `adaptive` está ligado) |
| `min_size` | `2` | Mínimo de fotos para que uma cena seja exibida |
| `max_photos` | `5000` | Máximo de fotos principais de rajada carregadas para o agrupamento de cenas |
| `max_scene_size` | `60` | Cenas maiores são divididas de novo em suas maiores lacunas internas |
| `adaptive` | `true` | Amplia a lacuna para `adaptive_k × mediana` das lacunas da sessão (mais apertada para fotografia rápida, mais frouxa para viagens esparsas) |
| `adaptive_k` | `6.0` | Multiplicador aplicado à lacuna mediana quando `adaptive` está ligado |
| `split_on_moment_change` | `false` | Com os momentos narrativos computados, divide também onde o momento dominante muda por `moment_split_min_run` quadros |
| `moment_split_min_run` | `4` | Quadros consecutivos que um novo momento precisa durar para forçar um limite de cena |

## Narrative Moments

Rotula, sem treinamento, o "momento" de cena/atividade de cada foto. O vocabulário **general** padrão cobre `celebration`, `dining`, `beach`, `water_activity`, `mountains`, `nature_wildlife`, `cityscape`, `travel_landmark`, `concert`, `sports`, `group_gathering`, `portrait`, `children`, `pets`, `nightlife`, `ceremony`, `scenic_landscape`, `snow_winter`, `home_indoor`, `road_vehicle` ou `other`. `wedding` vem como um gênero opcional. `--detect-moments` os preenche (também é executado ao final de cada escaneamento); eles aparecem como nomes de cenas e um filtro de galeria.

O Facet compara a legenda por IA de cada foto, codificada uma vez e armazenada (`caption_embedding`), com prompts de texto para cada momento, e mantém a melhor correspondência. Sem legenda, usa o embedding de imagem. As legendas correspondem de forma mais limpa, então o sinal `caption` tem limiares mais altos que o fallback `image`, ajustados por backend. Os valores de `transformers` (SigLIP) são padrões conservadores; reajuste-os se você usar um perfil SigLIP.

```json
{
  "narrative_moments": {
    "enabled": true,
    "prompt_template": "a photo of {desc}",
    "default_event_type": "general",
    "pooling": "max",
    "caption_min_confidence": 0,
    "thresholds": {
      "caption": {
        "open_clip": { "min_confidence": 0.30, "min_margin": 0.02 },
        "transformers": { "min_confidence": 0.12, "min_margin": 0.01 }
      },
      "image": {
        "open_clip": { "min_confidence": 0.20, "min_margin": 0.01 },
        "transformers": { "min_confidence": 0.10, "min_margin": 0.01 }
      }
    },
    "priors": {
      "enabled": true, "weight": 0.04, "caption_tag_scale": 0.25,
      "rules": [
        { "kind": "structural", "when": { "is_group_portrait": true, "face_count_min": 4 }, "boost": { "group_gathering": 1.0 } },
        { "kind": "tag", "when": { "tags_any": ["beach", "ocean", "sand"] }, "boost": { "beach": 0.8 } }
      ],
      "event_types": { "wedding": { "rules": [ { "kind": "tag", "when": { "tags_any": ["cake"] }, "boost": { "cake_cutting": 1.0 } } ] } }
    },
    "vlm_tiebreak": { "enabled": false, "min_confidence": 0.0, "min_margin": 0.04 },
    "transitions": { "stay_prob": 0.7, "forward_bias": 0.0, "weight": 0.3 },
    "event_types": { "general": { "beach": ["people at a sandy beach by the sea", "..."], "...": [] }, "wedding": { "vows": ["the couple exchanging vows at the altar", "..."] } }
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `enabled` | `true` | Interruptor mestre; quando desligado, `--detect-moments` e o hook de escaneamento não fazem nada |
| `prompt_template` | `"a photo of {desc}"` | Invólucro aplicado a cada prompt antes da codificação |
| `default_event_type` | `"general"` | Vocabulário de `event_types` ativo (`general` = 20 momentos; `wedding` opcional) |
| `pooling` | `"max"` | Pontuação por momento = a melhor correspondência individual de prompt |
| `caption_min_confidence` | `0` | Quando > 0, a geração de legendas ignora fotos sem rótulo, `other`, ou abaixo desta confiança; `0` = sem portão |
| `thresholds.<signal>.<backend>.min_confidence` | caption `0.30`/`0.12`, image `0.20`/`0.10` | Abaixo deste cosseno top-1, uma foto é `other` (indexado por sinal e depois por backend) |
| `thresholds.<signal>.<backend>.min_margin` | caption `0.02`/`0.01`, image `0.01`/`0.01` | Diferença mínima de cosseno entre top-1/top-2; abaixo dela o quadro vira `other` |
| `priors.enabled` / `priors.weight` | `true` / `0.04` | Pequenos ajustes de face/tag que só desempatam quase-empates; `weight` limita cada ajuste |
| `priors.caption_tag_scale` | `0.25` | Reduz as regras `tag` no sinal caption; as regras estruturais mantêm o peso total |
| `priors.rules` | (conjunto geral) | Lista de regras `{kind, when, boost}` (veja abaixo) |
| `priors.event_types.<et>.rules` | substituição `wedding` | Regras que **substituem** as `rules` globais quando esse vocabulário está ativo |
| `transitions.stay_prob` / `forward_bias` / `weight` | `0.7` / `0.0` / `0.3` | Suavização da linha do tempo entre quadros vizinhos (`weight=0` = nenhuma) |
| `vlm_tiebreak.enabled` / `min_confidence` / `min_margin` | `false` / `0.0` / `0.04` | Nos perfis 16gb/24gb, reclassifica com o VLM do perfil apenas quadros de baixa confiança ou de baixa margem |
| `event_types` | `general` + `wedding` | `{momento: [sinônimos de prompt]}` por tipo de evento; defina `default_event_type` para trocar de gênero ou adicionar o seu próprio |

Formato de `priors.rules`:
- `kind`: `structural` (geometria de rostos) ou `tag`.
- `when` (todos devem corresponder): `is_group_portrait`, `face_count_min`/`face_count_max`, `face_ratio_min`/`face_ratio_max`, `tags_any`, `tags_all`.
- `boost`: `{moment: valor}`. Um momento ausente do vocabulário ativo é ignorado.

O desempate por VLM é executado durante `--detect-moments` / `--recompute-moments`.

> **Custo do backfill de legendas.** Os embeddings de legenda são computados uma vez e armazenados. Um escaneamento codifica apenas suas novas legendas, mas a primeira passagem sobre uma biblioteca existente codifica todas: rápida na GPU, horas na CPU. Execute `python facet.py --detect-moments` uma vez (GPU recomendada); adicione `--limit N` para verificar primeiro em uma amostra.

**Descobrindo um vocabulário específico da biblioteca.** `python facet.py --discover-moments` agrupa os vetores `caption_embedding` armazenados, nomeia cada cluster a partir de suas legendas e grava um bloco `event_types.discovered` em `scoring_config.discovered.json`. Ele nunca altera a configuração ativa. Para adotá-lo, copie `discovered` para `event_types`, defina `default_event_type` como `discovered` e execute `--recompute-moments`. `--discover-min-cluster-size N` controla a granularidade (menor = mais momentos, mais finos).
## OCR

Busca de texto na foto: lê as palavras *dentro* das suas fotos (placas de rua, fachadas de lojas, números de peito de corrida, lombadas de livros, slides, quadros brancos, documentos digitalizados) em `photos.ocr_text`. Esse texto fica então pesquisável a partir da barra de busca da galeria como qualquer legenda ou tag; `GET /api/search?scope=text` pesquisa apenas os campos de texto.

**Desativado por padrão**, e precisa de um mecanismo instalado:

```bash
pip install easyocr           # ou: pip install -e .[ocr]
```

Depois ative-o e execute a passagem:

```json
{
  "ocr": {
    "enabled": false,
    "languages": ["en", "fr"],
    "min_confidence": 0.4,
    "full_resolution": false
  }
}
```

```bash
python facet.py --detect-text      # apenas fotos nunca avaliadas
python facet.py --recompute-text   # relê a biblioteca inteira
```

| Chave | Padrão | Descrição |
|-------|--------|-----------|
| `enabled` | `false` | Interruptor mestre; `--detect-text` se recusa a rodar enquanto isso for `false` |
| `languages` | `["en", "fr"]` | Códigos de idioma passados para o mecanismo; uma família de escrita por execução (o easyocr rejeita, por exemplo, `en` + `ja`) |
| `min_confidence` | `0.4` | Descarta detecções pontuadas abaixo deste valor (0–1); aumente-o contra ruído, diminua-o para texto fraco |
| `full_resolution` | `false` | Faz OCR no original em vez da miniatura de 640px (muito mais lento; recorre à miniatura quando offline) |

Notas:
- `ocr_text` é `NULL` até a foto ser avaliada e `''` quando ela não tem texto. `--detect-text` lê apenas fotos `NULL`; `--recompute-text` relê tudo.
- **Não é preciso `--rebuild-fts`:** a passagem atualiza o índice de busca à medida que grava. `python database.py --rebuild-fts` só é necessário para um banco de dados criado antes de o OCR existir, e `init_database` cuida disso para você.
- A miniatura de 640px já resolve placas, cartazes e cabeçalhos de documentos.

**Mecanismos.** `easyocr` (Apache-2.0, PyTorch) é o padrão e reutiliza a pilha que o Facet já tem. Seus pesos (~113MB) são baixados das releases do GitHub do projeto na primeira execução. O binário `tesseract` mais `pytesseract` é usado quando o easyocr está ausente, mas lê pior o texto de cena. Sem nenhum dos dois instalado, a passagem termina com um erro.

**Custo.** Cerca de 0,4s por miniatura na CPU, então uma biblioteca de 50 mil fotos é um trabalho único de uma noite; os escaneamentos posteriores só adicionam fotos novas. Uma GPU é usada automaticamente quando o torch reporta uma.

## Destinos de exportação e seleção

A exportação de álbum (`POST /api/albums/{id}/export`, modos `copy`/`symlink`) e a seleção-para-pasta (`POST /api/cull/apply`, ações `copy_keeps` / `move_rejects`) gravam em um `target_dir`. Ele precisa se resolver sob uma raiz permitida, ou a requisição é recusada antes de tocar em qualquer arquivo.

```json
{
  "viewer": {
    "export": {
      "allowed_target_dirs": ["/data/exports"]
    },
    "cull": {
      "allow_trash": false
    }
  }
}
```

| Configuração | Padrão | Descrição |
|---------|---------|-------------|
| `allowed_target_dirs` | *(chave ausente)* | Raízes extras nas quais a exportação e a seleção-para-pasta podem gravar, além dos diretórios de varredura (sempre permitidos) |
| `cull.allow_trash` | `false` | Permite a ação `trash_rejects` da seleção-para-pasta (lixeira do sistema operacional via `send2trash`, recuperável); desativado oculta a opção |

**Séries multi-fotograma e ações em lote.** Com `hide_brackets` / `hide_panoramas` ativados (o padrão, veja [Visualizador web — Filtros Padrão](VIEWER.md#filtros-padrão)), uma seleção contém apenas o quadro representativo de cada série, então as ações em lote agem apenas sobre esse quadro. O opt-in `include_sequence_siblings` da seleção-para-pasta amplia uma foto correspondida para toda a sua série; veja [Visualizador web — Selecionar para pasta § Séries multi-fotograma](VIEWER.md#selecionar-para-pasta).

**Ordem de resolução.** As raízes permitidas são `allowed_target_dirs` e depois cada diretório de varredura (por usuário, compartilhados e destinos de `path_mapping`). Exportar dentro da árvore de fotos não precisa de configuração; um destino fora dela precisa de uma entrada aqui. Links simbólicos e `..` são resolvidos antes da verificação (`os.path.realpath()`), então um link que aponta para fora de uma raiz permitida é recusado.

**Fechado por padrão (fail-closed).** Sem `allowed_target_dirs` e sem diretórios de varredura, a exportação copiar/symlink/mover é recusada.

**Solução de problemas de "acesso negado".** A interface web mostra um aviso genérico de "Acesso negado". Para ver o motivo, abra a aba Rede do navegador, encontre a requisição que falhou para `/api/cull/apply` ou `/api/albums/{id}/export` e leia o campo `detail`: ou é esta lista de permissões, ou uma sessão de edição expirada. Um erro real de permissão do sistema de arquivos se apresenta de forma diferente: a requisição tem sucesso, a contagem `errors` da resposta é diferente de zero e o log do servidor tem um traceback por arquivo. Veja [Implantação — Semântica de caminhos em contêiner](DEPLOYMENT.md#semântica-de-caminhos-em-contêiner) para o caso do contêiner.

Veja [Visualizador web — Selecionar para pasta](VIEWER.md#selecionar-para-pasta) e [Visualizador web — Exportação para Editor](VIEWER.md#exportação-para-editor).

## Exportação social

Padrões de recorte para proporções de redes sociais, enquadradas no sujeito (`GET /api/photo/social_crop`, restrito à edição). Cada padrão recorta o original em resolução total para o maior retângulo dessa proporção, centrado no sujeito. O sujeito é a caixa de sujeito BiRefNet (`photos.subject_bbox`), senão a união das caixas de rostos, senão o centro da imagem. Veja [Visualizador web — Download](VIEWER.md#download).

```json
{
  "social_export": {
    "presets": {
      "square":       { "label_key": "social_export.presets.square",       "aspect": "1:1" },
      "portrait_4x5": { "label_key": "social_export.presets.portrait_4x5", "aspect": "4:5" },
      "story_9x16":   { "label_key": "social_export.presets.story_9x16",   "aspect": "9:16" }
    },
    "jpeg_quality": 92
  }
}
```

| Configuração | Padrão | Descrição |
|---------|---------|-------------|
| `presets.<id>.label_key` | — | Caminho i18n com pontos para o nome exibido do padrão (`social_export.presets.*`) |
| `presets.<id>.aspect` | — | Proporção alvo como `"l:a"` (ex.: `1:1`, `4:5`, `9:16`) |
| `jpeg_quality` | `92` | Qualidade JPEG do recorte exportado |

Controlado por `viewer.features.show_social_export` (padrão `true`). A caixa do sujeito é escrita pela passagem de saliência na varredura e por `--recompute-saliency`; fotos mais antigas usam o recorte por rostos ou centralizado.

## Exportação de portfólio

Exporta um álbum como uma galeria HTML estática e autónoma que pode ser enviada para qualquer alojamento web (`POST /api/albums/{album_id}/export-portfolio`, somente edição).

- A pasta de saída contém `index.html` (grade de miniaturas e lightbox, sem referências externas nem CDN), uma pasta `assets/` de JPEG com nomes sequenciais (sem caminhos da biblioteca) e um `manifest.json`.
- Cada foto usa o **original**, reduzido para `max_edge`, ou a miniatura de 640 px armazenada quando o original está inacessível. O manifesto registra qual.
- Reexportar reescreve apenas os seus próprios arquivos.

```json
{
  "portfolio": {
    "max_photos": 500,
    "max_edge": 2048,
    "jpeg_quality": 88
  }
}
```

| Definição | Padrão | Descrição |
|-----------|--------|-----------|
| `max_photos` | `500` | Álbuns maiores são recusados (a exportação é síncrona) |
| `max_edge` | `2048` | Limite do lado maior (px) para os originais exportados; o pedido pode substituí-lo (limitado 256–8000) |
| `jpeg_quality` | `88` | Qualidade JPEG das imagens exportadas |

O `target_dir` usa a mesma lista de permissões das outras exportações (`viewer.export.allowed_target_dirs` mais os diretórios de varredura — veja [Destinos de exportação e seleção](#destinos-de-exportação-e-seleção)). Controlado por `viewer.features.show_portfolio_export` (padrão `true`). Veja [Visualizador web — Portfolio export](VIEWER.md#exportação-de-portfólio).

## Endpoint de agentes (MCP)

Expõe as ferramentas descritas em [Agentes de IA (MCP)](AGENTS.md) em `POST /mcp`: leitura, controle da aba aberta e, consoante o nível do token, alteração de classificações, etiquetas e álbuns, seleção e exclusão. Está ativado por padrão.

Em uma instalação aberta (sem `viewer.password`):
- `/mcp` serve apenas uma chave anônima só de leitura, que não mostra nada que a `/api` aberta não mostre.
- Um token novo é `readonly`, a menos que `viewer.trusted_local_editing` esteja ativo ou a sessão tenha entrado com `viewer.edition_password`: ambos podem criar um token de edição completa, que só edita nas requisições do mesmo computador.
- Os tokens só se criam, listam e revogam a partir do computador onde o Facet está rodando (ou em uma sessão de edição quando `viewer.edition_password` está definido).

```json
{
  "viewer": {
    "mcp": {
      "enabled": true,
      "bridge": true,
      "max_rows": 100,
      "max_bytes": 60000,
      "max_image_bytes": 262144,
      "call_timeout_s": 30,
      "semantic_timeout_s": 120,
      "rate_per_min": 120,
      "write_rate_per_min": 30,
      "tool_profile": "full",
      "allow_destructive": false,
      "inpage_tools": true,
      "allowed_origins": []
    }
  }
}
```

| Chave | Padrão | Descrição |
|-----|---------|-------------|
| `enabled` | `true` | Interruptor geral de `/mcp` e `/api/mcp/*` |
| `bridge` | `true` | Permite a ponte com a aba do navegador (`/api/mcp/bridge`) para que as ferramentas `ui_*` cheguem a uma aba; exige um único worker |
| `max_rows` | `100` | Máximo de linhas em um resultado de ferramenta (1 a 500); as linhas a mais definem `truncated: true` |
| `max_bytes` | `60000` | Tamanho serializado máximo de um resultado de ferramenta em bytes (4000 a 500000). |
| `max_image_bytes` | `262144` | Tamanho máximo da imagem de `get_thumbnail` ou `contact_sheet` (de 32768 a 2097152); não contada em `max_bytes` |
| `call_timeout_s` | `30` | Tempo limite de uma chamada de ferramenta em segundos (1 a 300), também a espera de uma chamada `ui_*` pela aba (`tab_timeout`) |
| `semantic_timeout_s` | `120` | Tempo limite de `semantic_search` em segundos (1 a 300); carrega o modelo de embeddings e precisa de mais. |
| `rate_per_min` | `120` | Chamadas de ferramentas por minuto e por token (mínimo 1). |
| `write_rate_per_min` | `30` | Chamadas de escrita por minuto e por token (mínimo 1), à parte para que as leituras não deixem as escritas sem quota |
| `tool_profile` | `"full"` | `"full"` lista todas as ferramentas permitidas; `"core"` lista um conjunto de 11 ferramentas para modelos pequenos |
| `allow_destructive` | `false` | Permite `delete_photos`, os `move_rejects`/`trash_rejects` de `cull_apply` e `assign_faces` com `allow_reassign` |
| `inpage_tools` | `true` | Permite que uma aba com sessão iniciada chame as ferramentas do servidor a partir da página (`GET /api/mcp/inpage_tools`, `POST /api/mcp/call`) |
| `allowed_origins` | `[]` | Origens de navegador adicionais (por exemplo `["https://photos.example.com"]`) autorizadas a abrir a ponte da aba atrás de um proxy que reescreve `Host`; não é a chave CORS `viewer.allowed_origins` |

Notas:
- **`enabled: false`** desliga `/mcp` e `/api/mcp/*` (a ponte fecha com o código 4404). **`bridge: false`** recusa a ponte e faz as ferramentas `ui_*` devolverem um erro.
- **`write_rate_per_min`** cobre as ferramentas de escrita, incluindo a simulação de `cull_apply` e `delete_photos`; veja [Agentes de IA](AGENTS.md#alterar-a-biblioteca).
- **`"core"`** lista `status`, `search_photos`, `semantic_search`, `get_photo`, `filter_options`, `library_stats`, `ui_show_photos`, `set_rating`, `set_favorite`, `set_rejected`, `album_add_photos`. Só a lista muda; as outras ferramentas ainda podem ser chamadas se o nível da chave o permitir. Qualquer outro valor significa `"full"`. Ver [Agentes de IA](AGENTS.md#níveis-de-permissão).
- **`allow_destructive: false`** oculta `delete_photos`; as outras duas respondem `feature_disabled` indicando esta chave. Ver [Agentes de IA](AGENTS.md#ações-destrutivas-pré-visualizar-e-confirmar).
- **`inpage_tools`** executa as ferramentas como a sessão, ao seu nível atual. Desativado, `features.mcp_inpage` é falso em `/api/auth/status`. Veja [Agentes de IA](AGENTS.md#webmcp-na-página-agentes-do-navegador).
- Os números fora do intervalo são limitados, e um valor de tipo errado usa o padrão. As alterações se aplicam ao recarregar a configuração, sem reiniciar.

## Moldura digital / Quiosque

Serve as melhores fotos curadas para dispositivos de quiosque sem início de sessão: molduras digitais inteligentes, painéis do Home Assistant, telas ao estilo ImmichFrame / Immich-Kiosk. Três endpoints usam um token estático: `GET /api/frame/photos`, `GET /api/frame/image/{id}`, `GET /api/frame/next`. Uma lista `tokens` vazia desativa a funcionalidade (os endpoints devolvem 404). As respostas nunca contêm caminhos de arquivos; as fotos são endereçadas por um id assinado.

```json
{
  "frame": {
    "tokens": [],
    "count": 20,
    "max_count": 100,
    "min_aggregate": 7.0,
    "max_edge": 1920,
    "favorites_only": false,
    "categories": []
  }
}
```

| Definição | Padrão | Descrição |
|-----------|--------|-----------|
| `tokens` | `[]` | Tokens de moldura, uma cadeia aleatória longa por dispositivo; remova um para o revogar. **Vazio = funcionalidade desativada.** |
| `count` | `20` | Número padrão de fotos devolvidas por `/api/frame/photos` |
| `max_count` | `100` | Limite máximo do parâmetro de consulta `count` |
| `min_aggregate` | `7.0` | Pontuação agregada mínima para uma foto ser curada |
| `max_edge` | `1920` | Limite do lado maior (px) dos JPEG servidos; o parâmetro `max_edge` só pode reduzi-lo |
| `favorites_only` | `false` | Se `true`, apenas as fotos favoritas são curadas |
| `categories` | `[]` | Lista de nomes de categorias permitidas (vazio = todas) |

Gerencia um token com `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

A curadoria exclui as fotos rejeitadas, lixo (`junk_kind`) e com olhos fechados, aplica os filtros de pontuação, favoritos e categorias, e depois escolhe uma amostra aleatória ponderada pela pontuação. Veja [Visualizador Web — Moldura Digital / Endpoint de Quiosque](VIEWER.md#moldura-digital--endpoint-de-quiosque) para a receita do Home Assistant.

> **Aviso:** um token de moldura não é um login de usuário. No [modo multiusuário](#users), ele ignora os `directories` privados de cada usuário e pode ler as fotos de todos os usuários, não apenas `shared_directories`. Emita tokens de moldura apenas onde todos os usuários aceitem isso.
## Envio automático do celular

Um endpoint **WebDAV** mínimo em `/dav` permite que apps de envio automático do celular (PhotoSync e outras) enviem fotos para uma **pasta de entrada** (inbox), que o `facet.py --watch` pontua depois. O acesso usa HTTP Basic com **credenciais de dispositivo compartilhado** (`username` / `password`), não uma conta de usuário.

- `/dav` devolve **404** até `username`, `password` e `inbox_dir` estarem todos definidos.
- Cada operação fica dentro de `inbox_dir`; traversal, caminhos absolutos e fugas por conexão simbólica são recusados.
- Os envios são gravados de forma atómica e limitados por `max_file_mb`.

```json
{
  "upload": {
    "username": "",
    "password": "",
    "inbox_dir": "",
    "max_file_mb": 500
  }
}
```

| Definição | Padrão | Descrição |
|-----------|--------|-----------|
| `username` | `""` | Nome de usuário HTTP Basic (credencial de dispositivo compartilhado). **Vazio = funcionalidade desativada.** |
| `password` | `""` | Senha HTTP Basic; use uma cadeia aleatória longa. **Vazio = funcionalidade desativada.** |
| `inbox_dir` | `""` | Caminho absoluto da pasta de entrada, criada a pedido. **Vazio = funcionalidade desativada.** |
| `max_file_mb` | `500` | Limite de tamanho por arquivo (MB); um envio maior é abortado e não deixa qualquer arquivo parcial |

Aponte `inbox_dir` para um diretório analisado (ou um subdiretório) para que o `facet.py --watch` pontue os envios à medida que chegam.

Métodos suportados: `OPTIONS`, `PROPFIND` (profundidade 0/1), `MKCOL`, `PUT`, `MOVE`, `DELETE`, `GET`, `HEAD` (sem `LOCK`/`UNLOCK`). Um cabeçalho `Authorization` ausente ou incorreto recebe `WWW-Authenticate: Basic realm="Facet upload"`. Veja [Visualizador Web — Envio Automático do Telefone](VIEWER.md#envio-automático-do-telefone) para a receita do PhotoSync e um teste rápido com `curl`.
## Junk Sweep

Sinaliza "lixo" não fotográfico (capturas de tela, documentos escaneados, recibos, memes, slides de apresentação) a partir do **embedding de imagem armazenado**, sem decodificar imagens. Cada tipo tem uma lista de prompts de texto, e o prompt de melhor correspondência vale para esse tipo.

- Uma foto só é sinalizada quando o melhor tipo de lixo atinge `min_confidence` **e** supera o melhor prompt `not_junk` por `min_margin`.
- Caso contrário, é armazenada como `not_junk` (avaliada, limpa). `NULL` significa ainda não avaliada.
- `--detect-junk` rotula apenas as fotos `NULL` (também roda ao final da varredura); `--recompute-junk` reavalia a biblioteca inteira.
- Os resultados vão para `photos.junk_kind`, revisados na fila **Limpeza de lixo** do visualizador ([VIEWER.md](VIEWER.md#limpeza-de-lixo)).

```json
{
  "junk_sweep": {
    "enabled": true,
    "prompt_template": "{desc}",
    "pooling": "max",
    "thresholds": {
      "open_clip": { "min_confidence": 0.2, "min_margin": 0.06 },
      "transformers": { "min_confidence": 0.1, "min_margin": 0.02 }
    },
    "kinds": {
      "screenshot": ["a screenshot of a phone user interface", "..."],
      "document": ["a scanned document", "..."],
      "receipt": ["a close-up photo of a paper receipt", "..."],
      "meme": ["a meme with overlaid text", "..."],
      "slide": ["a presentation slide", "..."]
    },
    "not_junk_prompts": ["a natural photograph", "a candid photo of people", "..."]
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `enabled` | `true` | Executa a detecção de lixo durante `--detect-junk` / `--recompute-junk` e ao final da varredura |
| `prompt_template` | `"{desc}"` | String de formato aplicada a cada prompt (`{desc}` = o prompt); inalterada por padrão |
| `pooling` | `"max"` | Combina as pontuações dos prompts por tipo via `max` (melhor prompt individual) ou `mean` |
| `thresholds.<backend>.min_confidence` | open_clip `0.2`, transformers `0.1` | Pontuação mínima para o melhor tipo de lixo (por backend; as pontuações de CLIP/`open_clip` são mais baixas que as de SigLIP/`transformers`) |
| `thresholds.<backend>.min_margin` | open_clip `0.06`, transformers `0.02` | Quanto o melhor tipo de lixo precisa superar o melhor prompt de contraste `not_junk` antes de a foto ser sinalizada |
| `kinds` | screenshot/document/receipt/meme/slide | `{tipo: [sinônimos de prompt]}`; adicione, remova ou renomeie tipos livremente |
| `not_junk_prompts` | 8 prompts fotográficos | Prompts que descrevem fotografias reais, que mantêm as fotos genuínas fora da fila |

## AI Critique

Configurações de prompt para a crítica com VLM (perfis 16gb/24gb). A crítica alimenta o VLM com o detalhamento da pontuação, as penalidades e o EXIF, e apresenta a resposta como Observação / Avaliação / Sugestões.

- A Avaliação cobre composição, cor e luz, foco/PdC e execução técnica, e sujeito e momento, confrontados com as métricas.
- Fica em cache por foto (`photos.vlm_critique`, traduções em `vlm_critique_translated`); `refresh` a regenera.
- Roda sobre a miniatura armazenada, então arquivos RAW funcionam.

```json
{
  "critique": {
    "vlm": {
      "max_new_tokens": 320
    }
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `critique.vlm.max_new_tokens` | `320` | Orçamento de tokens para a geração estruturada da crítica com VLM |

Veja [Visualizador Web — Crítica por IA](VIEWER.md#crítica-por-ia).

## VLM Backend

Seleciona onde o modelo visão-linguagem de legendas/tags é executado. `local` (padrão) usa o modelo Qwen embutido dos perfis 16gb/24gb. Os dois backends remotos usam um servidor externo, de modo que legendas e marcação por VLM também funcionem nos **perfis legacy/8gb que não trazem VLM local**.

```json
{
  "vlm_backend": {
    "type": "local",
    "ollama": {
      "base_url": "http://localhost:11434",
      "model": "qwen2.5vl:7b",
      "timeout_seconds": 120
    },
    "openai_compatible": {
      "base_url": "http://localhost:1234/v1",
      "api_key": "",
      "model": "qwen2.5-vl-7b",
      "timeout_seconds": 120
    }
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `type` | `"local"` | `local` (Qwen embutido), `ollama` (API REST do Ollama) ou `openai_compatible` (LM Studio, vLLM, OpenRouter, …) |
| `ollama.base_url` | `"http://localhost:11434"` | URL base do servidor Ollama (as imagens vão para `POST /api/generate`) |
| `ollama.model` | `"qwen2.5vl:7b"` | Tag do modelo Ollama (precisa ser um modelo de visão já baixado no servidor) |
| `ollama.timeout_seconds` | `120` | Tempo limite por requisição para as chamadas ao Ollama |
| `openai_compatible.base_url` | `"http://localhost:1234/v1"` | URL base **incluindo o sufixo `/v1`** (as requisições vão para `{base_url}/chat/completions`, com a imagem como URI de dados `image_url`) |
| `openai_compatible.api_key` | `""` | Enviado como `Authorization: Bearer <chave>`; deixe vazio para servidores locais sem chave |
| `openai_compatible.model` | `"qwen2.5-vl-7b"` | Nome do modelo passado ao endpoint |
| `openai_compatible.timeout_seconds` | `120` | Tempo limite por requisição para as chamadas compatíveis com OpenAI |

O backend alimenta as legendas (`--generate-captions` e `/api/caption`), a crítica por VLM (`/api/critique?mode=vlm`), a remarcação por VLM (`--recompute-tags-vlm`) e o desempate dos momentos narrativos. Uma requisição remota que falha afeta apenas essa foto (registrada em log, sem tags nem legenda). A marcação durante a varredura ainda usa o marcador do perfil; execute `--recompute-tags-vlm` para aplicar um backend remoto a uma biblioteca existente.

## Distortion Attributes

Rótulos de distorção apenas informativos. `--recompute-distortions` compara o embedding CLIP/SigLIP armazenado de cada foto com prompts de defeitos comuns (desfoque de movimento, dominante de cor, nitidez excessiva, …) e armazena os prováveis. Eles nunca afetam a pontuação; aparecem como chips de aviso no diálogo de crítica.

```json
{
  "distortion_attributes": {
    "enabled": true,
    "top_n": 5,
    "thresholds": {
      "open_clip":    { "temperature": 0.02, "min_confidence": 0.6 },
      "transformers": { "temperature": 0.05, "min_confidence": 0.6 }
    },
    "vocabulary": {}
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `enabled` | `true` | Calcula os atributos de distorção durante `--recompute-distortions` |
| `top_n` | `5` | Número máximo de rótulos de distorção mantidos por foto |
| `thresholds.<backend>.temperature` | open_clip `0.02`, transformers `0.05` | Temperatura do softmax sobre as pontuações dos prompts, por backend de embedding (as escalas diferem, como em `narrative_moments`) |
| `thresholds.<backend>.min_confidence` | `0.6` | Probabilidade mínima para que um rótulo de distorção seja mantido |
| `vocabulary` | `{}` | Substituição opcional dos prompts embutidos (`{atributo: [sinônimos de prompt]}`); vazio = padrões |

## Skin Tone

Verificação informativa do tom de pele em retratos. `--recompute-skin-tone` mede a cor das bochechas nas miniaturas de rosto armazenadas e sinaliza retratos cuja pele desvia para verde, magenta, azul ou amarelo. Nunca afeta a pontuação; o resultado aparece como uma nota no diálogo de crítica.

```json
{
  "skin_tone": {
    "cast_delta_threshold": 12.0
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `cast_delta_threshold` | `12.0` | Distância CIEDE2000 mínima dos tons de pele naturais antes de uma dominante de cor ser sinalizada |

## Immich Sync

Sincronização unidirecional das avaliações por estrelas e favoritos do Facet para um servidor [Immich](https://immich.app/) por meio da API REST dele. Os ativos são resolvidos por `originalPath` através de `path_map`. Execute `--immich-sync` (verifique antes com `--immich-test`); veja [Comandos — Immich Sync](COMMANDS.md#sincronização-com-o-immich).

```json
{
  "immich": {
    "url": "",
    "api_key": "",
    "path_map": [
      { "facet_prefix": "", "immich_prefix": "" }
    ],
    "push": {
      "ratings": true,
      "favorites": true,
      "rejected": false,
      "top_picks_album": "",
      "top_picks_min_rating": 4
    },
    "webhook": {
      "token_env": "",
      "header": "x-facet-token",
      "max_pending": 500
    },
    "timeout_seconds": 30
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `url` | `""` | URL base do servidor Immich (ex.: `http://nas:2283`) |
| `api_key` | `""` | Chave de API do Immich, enviada como o cabeçalho `x-api-key` |
| `owner_id` | `""` | ID exato do proprietário (opcional); ativos sem ele ou de outro proprietário são ignorados |
| `library_id` | `""` | ID exato da biblioteca (opcional); vazio = sem filtro de biblioteca |
| `path_map` | `[{facet_prefix, immich_prefix}]` | Reescritas de prefixo dos caminhos do Facet para o `originalPath` do Immich; o primeiro `facet_prefix` correspondente vale |
| `push.ratings` | `true` | Envia as avaliações por estrelas (apenas 1–5 é gravado, nunca 0/−1) |
| `push.favorites` | `true` | Envia a marcação de favorito |
| `push.rejected` | `false` | Envia `rating: -1` para fotos rejeitadas no Facet. Requer `push.ratings` |
| `push.top_picks_album` | `""` | Nome opcional de álbum no Immich que reúne as fotos enviadas acima do limiar de avaliação. Vazio = sem álbum |
| `push.top_picks_min_rating` | `4` | Avaliação por estrelas mínima para que uma foto seja adicionada a `top_picks_album` |
| `webhook.token_env` | `""` | Variável de ambiente que salva o segredo compartilhado do webhook de entrada; vazio ou não definida desativa o webhook |
| `webhook.header` | `"x-facet-token"` | Cabeçalho em que o workflow do Immich envia o token |
| `webhook.max_pending` | `500` | Teto para a lista de caminhos lembrados mas ainda não pontuados, relatada pela próxima sincronização |
| `timeout_seconds` | `30` | Timeout REST por requisição |

`--immich-sync` aceita `--dry-run` (resolve cada ativo mas não grava nada) e `--user` (envia as avaliações de `user_preferences` daquele usuário no modo multiusuário). O Facet usa apenas a API REST e nunca toca no banco de dados do Immich.

## Timeline

Configurações da visualização cronológica em linha do tempo:

```json
{
  "timeline": {
    "photos_per_group": 30
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `photos_per_group` | `30` | Fotos carregadas por grupo de data; valores maiores mostram mais por data, mas deixam as páginas mais pesadas |

## Map

Configurações da visualização de mapa interativo:

```json
{
  "map": {
    "cluster_zoom_threshold": 10
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `cluster_zoom_threshold` | `10` | Nível de zoom em que marcadores individuais substituem os clusters; 1 (mundo) a 18 (rua) |

## Translation

Configurações para a tradução de legendas por IA via MarianMT:

```json
{
  "translation": {
    "target_language": "fr"
  }
}
```

| Configuração | Padrão | Descrição |
|--------------|--------|-----------|
| `target_language` | `"fr"` | Idioma de destino de `--translate-captions`: `fr`, `de`, `es`, `it`, `pt` (português do Brasil) |

A tradução usa os modelos MarianMT da Helsinki-NLP na CPU; não é necessária GPU.
## Aesthetic CLIP (R2)

Uma pontuação estética extra calculada a partir dos embeddings CLIP/SigLIP em cache e de prompts de texto. Use `scripts/benchmark_aesthetic.py` para medir o efeito de uma alteração de prompt no AVA.

```json
{
  "aesthetic_clip": {
    "positive_prompts": [
      "a professional, high-quality photograph",
      "an aesthetically beautiful image",
      "a masterful, award-winning photograph",
      "a sharp, well-composed photograph",
      "a stunning, visually striking image"
    ],
    "negative_prompts": [
      "a low-quality, amateur photograph",
      "a blurry, poorly composed photograph",
      "an unattractive, mundane snapshot",
      "a noisy, badly lit photograph",
      "a boring, forgettable image"
    ]
  }
}
```

Arrays vazios usam os padrões de `analyzers/aesthetic_clip.py`. Rode novamente o benchmark AVA antes de alterá-los: os padrões pontuam SRCC ~0,52 em `ava_test/`, e edições podem facilmente derrubá-lo para ~0,30.

## Adicionando modelos alternativos de VLM tagger / crítica (R3)

O `tagging_model` de cada perfil (ex.: `qwen3.5-2b`) nomeia uma entrada de modelo na mesma seção `models`. Para experimentar outro VLM (Pixtral-12B, InternVL-2.5, etc.):

1. Adicione uma entrada de modelo sob `models`:
   ```json
   "pixtral_12b": {
     "model_path": "mistralai/Pixtral-12B-2409",
     "torch_dtype": "bfloat16",
     "max_new_tokens": 100,
     "vlm_batch_size": 1
   }
   ```
2. Aponte um perfil para ele:
   ```json
   "profiles": {
     "24gb": { "tagging_model": "pixtral_12b", ... }
   }
   ```
3. Execute `python facet.py --recompute-tags-vlm` para refazer as tags.

Sem necessidade de alterações de código. Verifique ~30 fotos lado a lado antes de torná-lo o padrão.

## Segredo do servidor

O segredo que assina os tokens de sessão e os links do porta-retratos digital **não** é uma chave deste arquivo. Ele fica em `.facet_secret`, ao lado de `scoring_config.json` (modo `0600`, ignorado pelo git), e é gerado na primeira execução.

- Substituição: a variável de ambiente `FACET_JWT_SECRET`.
- Rotação: `python database.py --rotate-secret`.

Um `share_secret` de uma instalação antiga é movido para esse arquivo na inicialização seguinte e removido de `scoring_config.json`. Veja [Armazenamento e rotação do segredo](DEPLOYMENT.md#armazenamento-e-rotação-do-segredo).
