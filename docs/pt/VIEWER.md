# Visualizador Web

> 🌐 [English](../VIEWER.md) · [Français](../fr/VIEWER.md) · [Deutsch](../de/VIEWER.md) · [Italiano](../it/VIEWER.md) · [Español](../es/VIEWER.md) · **Português**

Aplicação de página única em FastAPI + Angular para navegar, filtrar e gerenciar fotos.

## Conteúdo

- [Iniciando o Visualizador](#iniciando-o-visualizador) · [Autenticação](#autenticação) · [Opções de Filtragem](#opções-de-filtragem) · [Ordenação](#ordenação) · [Recursos da Galeria](#recursos-da-galeria)
- [Gerenciamento de Pessoas](#gerenciamento-de-pessoas) · [Disparo de Varredura (Superadmin)](#disparo-de-varredura-superadmin) · [Busca Semântica](#busca-semântica) · [Álbuns](#álbuns)
- [Crítica por IA](#crítica-por-ia) · [Legendagem por IA](#legendagem-por-ia-gpu-16gb24gb-edition) · [Memórias ("Neste Dia")](#memórias-neste-dia) · [Visão de Linha do Tempo](#visão-de-linha-do-tempo) · [Visão de Mapa](#visão-de-mapa) · [Cápsulas](#cápsulas)
- [Visão de Pastas](#visão-de-pastas) · [Diálogo de Filtro por GPS](#diálogo-de-filtro-por-gps) · [Sugestões de Mesclagem](#sugestões-de-mesclagem) · [Exportação para Editor](#exportação-para-editor) · [Triagem](#triagem) · [Limpeza de lixo](#limpeza-de-lixo) · [Modo de Comparação Pareada](#modo-de-comparação-pareada)
- [Estatísticas EXIF](#estatísticas-exif) · [Atalhos de Teclado](#atalhos-de-teclado-galeria) · [Desfazer](#desfazer) · [Progressive Web App](#progressive-web-app) · [Mobile](#mobile)
- [Configuração](#configuração) · [Desempenho](#desempenho) · [Endpoints da API](#endpoints-da-api) · [Solução de Problemas](#solução-de-problemas)

> **Requisitos de recurso** são marcados em linha: `[GPU]` · `[16gb/24gb]` (perfil de VRAM) · `[Edition]` (senha de edição) · `[Superadmin]`. Veja a [matriz de recursos](../README.md#feature-availability--requirements).

## Iniciando o Visualizador

### Produção

```bash
python viewer.py
# Open http://localhost:5000
```

Isso serve tanto a API quanto a aplicação Angular pré-compilada em uma única porta.

Para maior taxa de transferência, execute em modo de produção (Uvicorn, sem auto-reload). Adicione `--workers N` para escalar (padrão 1):

```bash
python viewer.py --production --workers 4
```

### Desenvolvimento

Execute o servidor da API e o servidor de desenvolvimento do Angular separadamente:

```bash
# Terminal 1: API server
python viewer.py
# API available at http://localhost:5000

# Terminal 2: Angular dev server with hot reload
cd client && npx ng serve
# Open http://localhost:4200 (proxies API calls to :5000)
```

## Autenticação

### Modo de Usuário Único (Padrão)

Proteção por senha opcional via configuração:

```json
{
  "viewer": {
    "password": "your-password-here"
  }
}
```

Quando definida, os usuários precisam se autenticar antes de acessar o visualizador. Uma `edition_password` opcional concede acesso ao gerenciamento de pessoas e ao modo de comparação.

### Modo Multiusuário

Para cenários de NAS familiar onde cada membro tem diretórios de fotos privados. Habilitado adicionando uma seção `users` ao `scoring_config.json`:

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

Os usuários são criados apenas via CLI (sem interface de registro):

```bash
python database.py --add-user alice --role superadmin --display-name "Alice"
```

Veja [Configuração](CONFIGURATION.md#users) para a referência completa.

### Papéis

| Papel | Ver próprias + compartilhadas | Avaliar/favoritar | Gerenciar pessoas/rostos | Disparar varreduras |
|------|:-:|:-:|:-:|:-:|
| `user` | sim | sim | não | não |
| `admin` | sim | sim | sim | não |
| `superadmin` | sim | sim | sim | sim |

### Visibilidade de Fotos

Cada usuário vê fotos de seus diretórios configurados além dos diretórios compartilhados. A visibilidade é aplicada em todos os endpoints: galeria, miniaturas, downloads, estatísticas, opções de filtro e páginas de pessoas.

### Avaliações por Usuário

No modo multiusuário, avaliações por estrelas, favoritos e marcações de rejeição são armazenados por usuário na tabela `user_preferences`. Cada usuário avalia de forma independente — os favoritos da Alice não afetam a visão do Bob.

Para migrar avaliações existentes de usuário único:

```bash
python database.py --migrate-user-preferences --user alice
```

## Opções de Filtragem

<details><summary>Barra lateral de filtros completa — todas as seções expandidas (clique para ver)</summary>
<p align="center"><img src="screenshots/filter-sidebar-full.jpg" alt="Filter sidebar with every section expanded" width="360"></p>
</details>

### Filtros Primários

| Filtro | Opções |
|--------|---------|
| **Tipo de Foto** | Melhores Escolhas, Retratos, Pessoas na Cena, Paisagens, Arquitetura, Natureza, Animais, Arte e Estátuas, Preto e Branco, Pouca Luz, Silhuetas, Macro, Astrofotografia, Rua, Longa Exposição, Aéreo e Drone, Shows |
| **Nível de Qualidade** | Bom (6+), Ótimo (7+), Excelente (8+), Melhor (9+) |
| **Câmera e Lente** | Filtragem baseada em equipamento |
| **Pessoa** | Filtrar por pessoa reconhecida |
| **Categoria** | Filtrar por categoria de foto |

### Filtros Avançados

| Categoria | Filtros |
|----------|---------|
| **Data** | Data de início e fim |
| **Pontuações** | Agregada, estética, pontuação TOPIQ, pontuação de qualidade |
| **Qualidade Estendida** | IAA estético (mérito artístico), IQA de qualidade de rosto, pontuação LIQE |
| **Métricas de Rosto** | Qualidade do rosto, nitidez dos olhos, nitidez do rosto, proporção do rosto, confiança do rosto, contagem de rostos |
| **Composição** | Pontuação de composição, pontos de força, linhas guia, isolamento, padrão de composição |
| **Saliência do Sujeito** | Nitidez do sujeito, proeminência do sujeito, posicionamento do sujeito, separação do fundo |
| **Técnica** | Nitidez, contraste, faixa dinâmica, nível de ruído |
| **Cor** | Pontuação de cor, saturação, luminância, espalhamento do histograma; temperatura de cor (quente/fria/neutra) e faixa de matiz (requer `--recompute-colors`) |
| **Exposição** | Pontuação de exposição |
| **Avaliações do Usuário** | Avaliação por estrelas |
| **Configurações da Câmera** | ISO, abertura (controle deslizante de faixa de f-stop), distância focal (controle deslizante de faixa) |
| **Conteúdo** | Tags, alternância de monocromático |
| **Momentos** | Confiança do momento narrativo (controle deslizante de faixa 0–1: `min_moment_confidence` / `max_moment_confidence`) |

### Padrões de Composição

Filtrar pelos padrões detectados pelo SAMP-Net:
- rule_of_thirds, golden_ratio, center, diagonal
- horizontal, vertical, symmetric, triangle
- curved, radial, vanishing_point, pattern, fill_frame

## Ordenação

Colunas ordenáveis agrupadas por categoria (de `viewer.sort_options`):

| Grupo | Colunas |
|-------|---------|
| **Geral** | Pontuação Agregada, Estética, Pontuação de Qualidade, Data de Captura, Avaliação por Estrelas, Estética (IAA), Pontuação LIQE |
| **Métricas de Rosto** | Qualidade do Rosto, Qualidade do Rosto (IQA), Nitidez dos Olhos, Nitidez do Rosto, Proporção do Rosto, Contagem de Rostos |
| **Técnica** | Nitidez Técnica, Contraste, Nível de Ruído |
| **Cor** | Pontuação de Cor, Saturação |
| **Exposição** | Pontuação de Exposição, Luminância Média, Espalhamento do Histograma, Faixa Dinâmica |
| **Composição** | Pontuação de Composição, Pontuação de Ponto de Força, Linhas Guia, Bônus de Isolamento, Padrão de Composição |
| **Saliência do Sujeito** | Nitidez do Sujeito, Proeminência do Sujeito, Posicionamento do Sujeito, Separação do Fundo |
| **Conteúdo** | Confiança do Momento (NULLs ao final) |

### Meu Gosto

Uma opção de ordenação de primeira classe apoiada pelo `learned_score` do ranqueador pessoal (renomeada de "Escolhido para você"). Ela ordena as fotos pelo que o ranqueador aprendeu com suas comparações A/B, avaliações e decisões de triagem. Um selo de confiança ao lado da ordenação mostra a cobertura aprendida (% de fotos com uma pontuação aprendida) e a precisão em dados retidos do ranqueador, para que você possa julgar o quanto confiar na ordenação. Treine ou atualize o ranqueador com `python facet.py --train-ranker`.

Controlado por `viewer.features.show_my_taste` (padrão: `true`). O status do ranqueador é exposto via `GET /api/ranker/status`.

## Recursos da Galeria

### Cartões de Foto

- Miniatura com selo de pontuação
- Tags clicáveis para filtragem rápida
- Avatares de pessoas para rostos reconhecidos
- Selo de categoria

### Seleção Múltipla e Ações em Lote

- Clique nas fotos para selecionar, Shift+Clique para seleção de intervalo
- A barra de ações aparece com a contagem da seleção e as ações disponíveis
- **Favoritar** — Marca todas as selecionadas como favoritas (limpa rejeição)
- **Rejeitar** — Marca todas as selecionadas como rejeitadas (limpa favorito e avaliação)
- **Avaliar** — Define a avaliação por estrelas (1–5) para todas as selecionadas, ou limpa a avaliação
- **Adicionar ao álbum** — Adiciona as selecionadas a um álbum existente ou novo
- **Copiar nomes de arquivo** — Copia os nomes de arquivo selecionados para a área de transferência
- **Exportar** — Grava sidecars XMP (avaliação/favorito/rejeição) ao lado dos arquivos selecionados (veja [Exportação para Editor](#exportação-para-editor))
- **Baixar** — Baixa as fotos selecionadas
- Limpe a seleção com Escape ou o botão Limpar

As ações em lote requerem o modo de edição. Dê um duplo clique em qualquer foto para baixá-la diretamente.

### Opções de Exibição

- **Modo de Layout** - Alterne entre **Grade** (cartões uniformes) e **Mosaico** (linhas justificadas preservando as proporções). O Mosaico é apenas para desktop; o mobile sempre usa grade.
- **Tamanho da Miniatura** - Controle deslizante para ajustar a altura do cartão/linha (120–400px, persistido no localStorage)
- **Ocultar Detalhes** - Oculta os metadados da foto nos cartões (apenas no modo grade)
- **Ocultar Dica** - Desativa a dica de ferramenta ao passar o mouse que mostra os detalhes da foto no desktop
- **Ocultar Piscadas** - Filtra fotos com piscadas detectadas
- **Melhor da Sequência** - Mostra apenas a foto com maior pontuação de cada sequência (burst)
- **Rolagem Infinita** - As fotos carregam conforme você rola
- **Rolagem Rápida (virtualizada)** - Renderização em janela de linhas: apenas as linhas
  próximas à viewport ficam no DOM, então a rolagem profunda por dezenas de milhares de fotos
  permanece responsiva. Ativada por padrão; desative na seção Exibição da barra
  lateral de filtros se você encontrar problemas de layout (o modo grade com detalhes exibidos
  sempre usa renderização completa, já que as alturas das linhas não são determinísticas ali). Persistido no
  localStorage (`facet_virtual_scroll`).

### Fotos Semelhantes

Clique no botão "Semelhantes" em qualquer foto para escolher um modo de similaridade:

- **Visual** (padrão) — distância de Hamming do pHash (70%) + similaridade de cosseno CLIP/SigLIP (30%). Recorre apenas ao CLIP quando nenhum pHash está disponível.
- **Cor** — Interseção de histograma (70%) + distância de saturação (10%) + distância de luminância (10%) + bônus monocromático (10%). Pré-filtra pela marcação monocromática e faixa de saturação.
- **Pessoa** — Encontra fotos contendo a(s) mesma(s) pessoa(s). Usa `person_id` quando disponível (rápido), caso contrário recorre à similaridade de cosseno do embedding facial.

Use o **controle deslizante de limiar de similaridade** (0–90%) para controlar o quão restrita é a correspondência (não exibido no modo pessoa). O painel suporta rolagem infinita para grandes conjuntos de resultados.

### Chips de Filtro

Os filtros ativos são exibidos como chips removíveis com contagens no topo da galeria.

## Gerenciamento de Pessoas

> Navegar pelas pessoas está aberto a todos os visualizadores; renomear, mesclar, alterar avatares e atribuir rostos requer `[Edition]`.

### Filtro de Pessoa

O menu suspenso mostra pessoas com miniaturas de rostos. Clique para filtrar a galeria.

### Galeria de Pessoa

Clique no nome da pessoa para ver todas as suas fotos em `/person/<id>`.

### Página Gerenciar Pessoas

Acesse pelo botão no cabeçalho ou por `/persons`:

| Ação | Como Fazer |
|--------|--------|
| **Mesclar** | Selecione a pessoa de origem, clique no destino, confirme |
| **Excluir** | Clique no botão excluir no cartão da pessoa |
| **Renomear** | Clique no nome da pessoa para editar em linha |
| **Dividir** | Abra os rostos de uma pessoa, selecione um subconjunto, divida-os em uma nova pessoa |
| **Ocultar** | Oculta um cluster da lista de pessoas, filtros e sugestões de mesclagem (reversível) |

## Disparo de Varredura (Superadmin)

Quando `viewer.features.show_scan_button` é `true` e o usuário tem o papel `superadmin`, um botão **Varrer fotos para começar** aparece no estado de galeria vazia. Ele vem definido como **`false`** no `scoring_config.json` (adesão explícita do superadmin). O botão abre o diálogo do lançador de varredura (`ScanLauncherComponent`).

- Escolha um diretório da lista do lançador e inicie a varredura dentro do aplicativo
- O lançador transmite o progresso ao vivo (SSE com fallback automático para polling) em uma `mat-progress-bar` controlada pelo campo estruturado `progress`, além de um trecho final de linhas de saída, e atualiza a galeria quando a varredura termina
- A varredura é executada como um subprocesso em segundo plano (`facet.py`); apenas uma varredura por vez (trava global)
- As escolhas de diretório vêm de `get_all_scan_directories()`, que une os `directories` de cada usuário, os diretórios compartilhados, os destinos de `path_mapping` e a lista autônoma `viewer.scan_directories` — preencha esta última (ex.: `/data/photos`) para que instalações de usuário único / Docker tenham um destino selecionável

Isso é útil quando o visualizador é executado na mesma máquina que tem acesso à GPU para pontuação.

## Busca Semântica

Busca híbrida combinando a similaridade de embedding CLIP/SigLIP (70%) com a correspondência de texto FTS5 BM25 em legendas e tags (30%). Digite uma consulta como "pôr do sol sobre montanhas" ou "criança brincando na neve" e o visualizador retorna fotos correspondentes ranqueadas pela pontuação combinada.

- Requer dados `clip_embedding` armazenados (computados durante a pontuação)
- Usa sqlite-vec para busca vetorial KNN quando instalado, recorre ao NumPy em memória
- A busca de texto FTS5 em legendas/tags geradas por IA fornece correspondência de palavras-chave adicional (execute `database.py --rebuild-fts` para habilitar)
- Usa o mesmo modelo de embedding do perfil de VRAM ativo (SigLIP 2 para 16gb/24gb, CLIP ViT-L-14 para legacy/8gb)
- `scope=text` restringe a consulta a correspondências literais FTS5 em texto OCR/legenda e ignora a busca por embedding
- Controlado por `viewer.features.show_semantic_search` (padrão: `true`)

## Álbuns

Organize fotos em álbuns nomeados. Acesse pela rota `/albums`.

### Álbuns Manuais

Crie álbuns e adicione fotos da galeria usando seleção múltipla. Os álbuns suportam:
- Nome e descrição
- Foto de capa personalizada
- Ordenação personalizada
- Navegar pelo conteúdo do álbum em `/album/:albumId`

### Álbuns Inteligentes

Salve uma combinação de filtros (câmera, tag, pessoa, intervalo de datas, limiares de pontuação, etc.) como um álbum inteligente. Os álbuns inteligentes se atualizam dinamicamente conforme novas fotos correspondem aos critérios de filtro salvos. A combinação de filtros é armazenada como JSON em `smart_filter_json`.

API: veja a seção [Endpoints da API](#endpoints-da-api) abaixo.

Controlado por `viewer.features.show_albums` (padrão: `true`).

### Compartilhamento de Fotos

Compartilhe álbuns com usuários externos por meio de links com token. Nenhuma autenticação é necessária para visualizar álbuns compartilhados.

| Ação | Como Fazer |
|--------|--------|
| **Compartilhar** | Abra o álbum, clique no botão "Compartilhar" para gerar um link compartilhável |
| **Revogar** | Clique em "Descompartilhar" para invalidar o token de compartilhamento |
| **Visualizar** | Os destinatários abrem o link para navegar pelo álbum compartilhado em `/shared/album/:id` |

API: veja a seção [Endpoints da API](#endpoints-da-api) abaixo.

### Aprovação de Cliente

Quando `viewer.features.show_proofing` está ativado (padrão `false`), um link de álbum compartilhado pode rodar em **modo de aprovação**: o cliente (sem conta) abre o link de compartilhamento, opcionalmente insere um PIN (`viewer.proofing.pin`) e pode então **curtir** fotos e deixar **comentários** — uma forma leve de deixar um cliente escolher seus favoritos de uma entrega.

As escolhas do cliente ficam totalmente isoladas da sua biblioteca. Elas vivem em uma tabela dedicada `album_client_picks`, são limitadas às fotos daquele álbum e nunca tocam seus próprios favoritos/avaliações (`photos.is_favorite` / `user_preferences`) nem treinam o ranqueador pessoal. Como dono, você lê as escolhas em um diálogo `[Edition]` no cartão do álbum. As sessões são de curta duração (`viewer.proofing.session_minutes`, padrão 24h) e param de funcionar no momento em que o álbum deixa de ser compartilhado ou a aprovação é desativada.

Controlado por `viewer.features.show_proofing` (padrão: `false`). Veja [Configuração — Aprovação de Cliente](CONFIGURATION.md#aprovação-de-cliente).

## Crítica por IA

Decompõe as pontuações de uma foto em pontos fortes, pontos fracos e sugestões.

### Crítica Baseada em Regras

Disponível em todos os perfis de VRAM. Analisa métricas armazenadas (estética, composição, nitidez, qualidade do rosto, etc.) e gera uma explicação estruturada da pontuação.

O detalhamento também exibe as linhas explicáveis de **forma e harmonia de cores** (simetria, equilíbrio, entropia de orientação de bordas, complexidade fractal, harmonia de cores de Matsuda — preenchidas por `--recompute-form`), **chips de atributos de distorção** para quaisquer defeitos prováveis (desfoque de movimento, dominante de cor, nitidez excessiva, … — de `--recompute-distortions`) e uma **nota de tom de pele** para retratos cujo croma de pele desvia do natural (`--recompute-skin-tone`). Os três são informativos — explicam a foto, não alteram o agregado — e cada linha só aparece quando sua coluna subjacente está preenchida.

### Crítica por VLM `[GPU]` `[16gb/24gb]`

Usa o VLM configurado (Qwen3.5-2B ou Qwen3.5-4B) para uma crítica contextual. Requer o perfil de VRAM 16gb ou 24gb e `viewer.features.show_vlm_critique: true`.

O prompt é uma escada configurável (`critique.vlm`) que injeta o detalhamento completo de regras, penalidades e EXIF, e a resposta é apresentada como **Observação / Avaliação / Sugestões**. O resultado é armazenado em cache por foto (`photos.vlm_critique`) e traduzido sob demanda, com um botão **Regenerar** para recomputá-lo. Ele roda sobre a miniatura armazenada, então arquivos RAW são criticados corretamente em vez de falharem silenciosamente.

API: veja a seção [Endpoints da API](#endpoints-da-api) abaixo.

Controlado por `viewer.features.show_critique` (padrão: `true`) e `viewer.features.show_vlm_critique` (padrão: `true`).

**Sobreposição visual "por que esta pontuação".** Quando `viewer.features.show_saliency_overlay` é `true` (padrão), o diálogo de crítica ganha uma alternância **Mostrar sobreposição**: ela desenha o mapa de saliência do BiRefNet como um mapa de calor translúcido sobre a foto (recomputado sob demanda a partir da miniatura armazenada — `GET /api/saliency_overlay`), além de caixas suaves por rosto e marcadores de olhos reconstruídos de pontos de referência (landmarks) armazenados (`GET /api/photo/face_markers`). As caixas ficam verdes quando os olhos estão abertos, âmbar em uma piscada. O mapa de calor é ilustrativo (resolução de miniatura), não exato ao pixel; a alternância se oculta em perfis onde nenhuma máscara de saliência pode ser produzida.

## Legendagem por IA `[GPU]` `[16gb/24gb]` `[Edition]`

Obtenha uma legenda em linguagem natural gerada por IA para qualquer foto. As legendas são geradas na primeira solicitação e armazenadas em cache na coluna `caption` do banco de dados. As legendas podem ser editadas manualmente no modo de edição pela página de detalhes da foto. (A *tradução* de legendas roda na CPU — veja abaixo.)

API: veja a seção [Endpoints da API](#endpoints-da-api) abaixo.

Também disponível via CLI para geração e tradução em lote:

```bash
python facet.py --generate-captions      # Generate captions for all uncaptioned photos
python facet.py --translate-captions     # Translate captions to configured target language
```

A tradução de legendas usa MarianMT (CPU, sem GPU necessária). Configure o idioma de destino no `scoring_config.json` em `translation.target_language` (padrão: `"fr"`). Idiomas suportados: francês, alemão, espanhol, italiano.

Controlado por `viewer.features.show_captions` (padrão: `true`). Requer o perfil de VRAM 16gb ou 24gb para legendagem baseada em VLM.

## Memórias ("Neste Dia")

Navegue pelas fotos tiradas na mesma data do calendário em anos anteriores. Abrir Memórias inicia um diaporama (apresentação de slides) aleatório em tela cheia das fotos correspondentes, em vez de uma grade; a dica do botão de navegação explica o que ele faz.

API: veja a seção [Endpoints da API](#endpoints-da-api) abaixo.

Controlado por `viewer.features.show_memories` (padrão: `true`).

## Fluxos de trabalho comuns

- **Triar umas férias** — abra Cápsulas → procure a cápsula `journey` gerada automaticamente para as datas da viagem. Cada cápsula oferece uma ação Salvar como Álbum.
- **Percorrer uma revisão dia a dia** — abra a Linha do Tempo → ordene por agregada → percorra o ano. As melhores fotos sobem primeiro quando você habilita `hide_bursts` e `hide_duplicates` (padrões: ativados).
- **Mostrar o que está oculto** — a galeria oculta piscadas / sequências não líderes / duplicatas não líderes por padrão. Quando pelo menos um desses filtros está ativo e excluiria linhas, um banner "N fotos ocultas pelos filtros atuais · Mostrar tudo" aparece acima da grade.

## Visão de Linha do Tempo

Navegador cronológico de fotos com navegação baseada em datas. Role pelas fotos organizadas por data com uma barra lateral mostrando os anos e meses disponíveis.

API: veja a seção [Endpoints da API](#endpoints-da-api) abaixo.

Acesse pela rota `/timeline`. Controlado por `viewer.features.show_timeline` (padrão: `true`).

## Visão de Mapa

Veja fotos em um mapa interativo com base nas coordenadas GPS extraídas dos dados EXIF. Usa Leaflet para renderização do mapa com agrupamento em diferentes níveis de zoom.

### Configuração

Extraia coordenadas GPS de fotos existentes:

```bash
python facet.py --extract-gps    # Extract GPS lat/lng from EXIF into database
```

As coordenadas GPS também são extraídas automaticamente durante a pontuação para fotos novas.

API: veja a seção [Endpoints da API](#endpoints-da-api) abaixo.

Acesse pela rota `/map`. Controlado por `viewer.features.show_map` (padrão: `true`).

## Cápsulas

Diaporamas (apresentações de slides) de fotos curadas, agrupadas por tema, lugar, pessoas e tempo — clique em uma cápsula para reproduzi-la. Acesse pela rota `/capsules`.

### Tipos de Cápsula

As cápsulas são geradas automaticamente a partir da sua biblioteca usando múltiplos algoritmos:

- **Jornada** — viagens detectadas via agrupamento de GPS, com nomes de destino obtidos por geocodificação reversa ("Jornada a Roma — Março de 2025")
- **Momentos com [Pessoa]** — melhores fotos de cada pessoa reconhecida
- **Paleta Sazonal** — fotos agrupadas por estação + ano
- **Coleção Dourada** — top 1% por pontuação agregada
- **História de Cores** — grupos visualmente semelhantes via agrupamento de embedding CLIP
- **Esta Semana, Anos Atrás** — "Neste Dia" estendido por ±3 dias
- **Localização** — clusters de fotos geolocalizadas com nomes de lugares
- **Favoritos** — fotos favoritadas agrupadas por ano e estação
- **Baseadas em dimensão** — geradas automaticamente a partir de câmera, lente, categoria, padrão de composição, faixa de distância focal, hora do dia, avaliação por estrelas e combinações entre dimensões

### Apresentação de Slides

Clique em qualquer cartão de cápsula para iniciar uma apresentação de slides. Recursos:
- **Transições temáticas** — slide (jornadas), zoom (retratos), kenburns (dourada/sazonal), crossfade (padrão)
- **Encadeamento automático** — quando uma cápsula termina, um cartão de transição mostra a próxima cápsula antes de continuar
- **Embaralhar e retomar** — as fotos são embaralhadas para variar; a posição de retomada é rastreada por cápsula
- **Agrupamento adaptativo** — fotos em retrato são agrupadas lado a lado com base na proporção da viewport
- **Salvar como álbum** — salve qualquer cápsula como um álbum permanente

### Atualização

As cápsulas são rotacionadas em um cronograma configurável (padrão: 24 horas). As fotos de capa e as cápsulas de descoberta semeadas alinham-se ao mesmo período de rotação. O botão "Regenerar" no cabeçalho força uma atualização imediata.

### Geocodificação Reversa

As cápsulas de localização e jornada mostram nomes de lugares (ex.: "Paris, França") em vez de coordenadas. Isso usa geocodificação offline via o pacote `reverse_geocoder` — sem necessidade de chamadas de API. Os resultados são armazenados em cache no banco de dados.

Instalação: `pip install reverse_geocoder`

API: veja a seção [Endpoints da API](#endpoints-da-api) abaixo.

### Configuração

Veja [Configuração — Cápsulas](CONFIGURATION.md#capsules) para todas as configurações.

## Visão de Pastas

Navegue pela sua biblioteca de fotos pela estrutura de diretórios. Acesse pela rota `/folders`.

- Navegação por trilha de navegação (breadcrumb) para subir na árvore de diretórios
- Cada pasta mostra uma foto de capa (a imagem de maior pontuação naquele diretório)
- Clique em uma pasta para entrar nela, ou clique em uma foto para abri-la na galeria
- Respeita a visibilidade de diretórios multiusuário no modo multiusuário

## Diálogo de Filtro por GPS

Filtre fotos por localização geográfica usando um seletor de mapa interativo:

- Clique no botão de filtro de localização para abrir o diálogo do mapa
- Clique ou arraste no mapa para definir um ponto central
- Ajuste o controle deslizante de raio para controlar a área de busca
- As fotos dentro do raio selecionado são filtradas na galeria
- Requer coordenadas GPS (execute `--extract-gps` se as fotos tiverem dados GPS EXIF)

## Sugestões de Mesclagem

Encontre clusters de pessoas que podem ser o mesmo indivíduo. Acesse por `/merge-suggestions` ou pela página Gerenciar Pessoas.

- **Controle deslizante de limiar de similaridade** — o quão semelhantes duas pessoas devem parecer para serem sugeridas (menor = mais sugestões, maior = menos)
- **Mesclar** — aceite uma sugestão para mesclar as duas pessoas
- **Mesclagem em lote** — selecione várias sugestões e mescle-as de uma vez
- As sugestões descartadas são lembradas e não propostas novamente
- Também disponível via CLI: `python facet.py --suggest-person-merges`

## Exportação para Editor

Grave suas avaliações, favoritos e rejeições no disco como sidecars XMP, para que editores externos (darktable, Lightroom) os reconheçam. Requer o modo de edição.

- **Da galeria** — selecione fotos, então **Ações → Exportar** grava um sidecar ao lado de cada arquivo.
- **De um álbum** ("cesta") — exporte o álbum inteiro como sidecars, ou copie/crie links simbólicos dos arquivos para um diretório de destino.
- **Gravar metadados no arquivo** — a ação "Gravar metadados no arquivo" nos detalhes da foto incorpora a avaliação/palavras-chave diretamente no arquivo original (JPEG/HEIC/TIFF/PNG/DNG via exiftool) além de gravar o sidecar, para que todo o ecossistema de fotos os veja. Originais RAW proprietários nunca são modificados. Controlado por `viewer.features.show_embed_metadata` (padrão: `true`).

API: veja a seção [Endpoints da API](#endpoints-da-api) abaixo.

## Triagem

A página de triagem (`/culling`, modo de edição) agrupa fotos quase idênticas para que você possa manter a melhor de cada uma e rejeitar o resto. Um seletor de **granularidade** — o primeiro e mais impactante controle da barra de ferramentas — escolhe como as fotos são agrupadas:

- **Tudo** (padrão) — grupos combinados de sequência + semelhantes.
- **Sequências** — fotos tiradas próximas no tempo (da detecção de sequências).
- **Semelhantes** — fotos que se parecem independentemente de quando foram tiradas, agrupadas pela similaridade de embedding CLIP/SigLIP. Um controle deslizante de limiar controla o quão restrito é o agrupamento.
- **Cenas** — grupos de cenas cronológicas (sequências por horário de captura), cada um encabeçado por seu intervalo de tempo e momento narrativo dominante. Condicionado a `viewer.features.show_scenes`.

Para cada grupo, escolha a(s) foto(s) a manter; confirmar rejeita o resto. As confirmações são adiadas e podem ser desfeitas (veja [Desfazer](#desfazer)). As escolhas de granularidade, ordenação e categoria persistem no `localStorage`. Controles que não se aplicam à granularidade atual são ocultados — o menu suspenso de ordenação e o controle deslizante de limiar de similaridade desaparecem no modo de cena, e o botão de escopo fica oculto quando você não tem álbuns manuais. Cada botão da barra de ferramentas e de ação de grupo tem uma dica (tooltip), e em telas pequenas a barra de ferramentas se destaca em uma barra inferior rolável.

**Triagem com escopo.** O laboratório (darkroom) pode ser restringido a um subconjunto via parâmetros de consulta: `?group_by=scene` muda para a granularidade de cena, `?album=<id>` restringe-o a um álbum, e `?from=&to=` (janela de horário de captura EXIF, a base de **Triar esta cena**) restringe-o a uma cena. Um banner mostra o escopo ativo com um controle **Sair da cena**; a busca de membros da sequência permanece com escopo de álbum, mas ignora a janela, então uma sequência que atravessa o limite da cena ainda mostra todos os seus quadros.

**Chip Meu Gosto.** Cada confirmação registra linhas de comparação `source='culling'` que treinam o ranqueador pessoal, então o cabeçalho mostra um pequeno chip "Meu Gosto · N comparações" que se atualiza após cada decisão — a IA aprende seu olhar conforme você tria (`GET /api/ranker/status`).

### Triagem automática

Um botão **Triagem automática** na barra de ferramentas tria um escopo inteiro em uma passagem, em vez de grupo por grupo. Escolha o escopo com os controles de granularidade/escopo (todos os grupos, ou apenas sequências / semelhantes / cenas, opcionalmente um álbum ou janela de datas), defina um **rigor** — o orçamento de fotos mantidas, onde maior mantém menos por grupo — e visualize a prévia. Cada grupo mantém sua melhor foto mais tudo dentro da margem de rigor (com um piso mínimo por grupo) e rejeita o resto.

A prévia é uma **simulação** (dry run — nada é gravado): ela mostra a divisão de manter/rejeitar por grupo. Confirme para aplicar — as rejeições são registradas e, como toda triagem, treinam o "Meu Gosto"; um álbum opcional **Highlights** reúne de forma idempotente a melhor foto de cada grupo com pontuação de pelo menos `auto_cull.highlights_min`. Um selo de dica "foto melhor neste grupo" sinaliza os grupos em que a triagem automática manteria um quadro diferente do líder atual. `POST /api/culling/auto`; configurado pelo bloco [`auto_cull`](CONFIGURATION.md#auto-cull).

### Tela cheia

Pressione **`F`** (ou a alternância no cabeçalho) para acionar a API de Tela cheia do navegador e revisar de borda a borda — o laboratório preenche a tela sem os controles do aplicativo. A tecla está listada na legenda de atalhos do laboratório; pressione `F` ou `Esc` para sair.

### Lupa / Zoom com tecla Z

Pressione **`Z`** na lightbox de visualização única para alternar uma lupa no estilo Photo Mechanic (ajuste ↔ 2×; roda/`+`/`-` para zoom de até 800%). Além da escala de ajuste, o painel troca sua miniatura pela fonte `/image` em resolução total, para que você julgue o foco crítico em pixels reais sem sair da visão. Na tira de contato de Cenas, `Z` alterna uma lupa flutuante que segue o cursor sobre um ladrilho (originada da imagem em resolução total), com um controle deslizante de zoom ajustável. As miniaturas armazenadas têm um limite de 640px, então a lupa é a forma de inspecionar pixels além disso.

### Selos por Rosto

Na lightbox de triagem de sequência/semelhantes, cada rosto detectado carrega seus próprios selos — olhos abertos/fechados, expressão ruim e confiança da detecção — em vez de uma única marcação de piscada por foto. Isso facilita a triagem de fotos em grupo: você pode ver de relance qual rosto tem os olhos fechados ou uma expressão fraca. Os selos são buscados para um grupo inteiro em uma única chamada em lote (`POST /api/culling-group/faces`).

O **painel de rostos** do laboratório colore cada recorte de rosto em verde / laranja / vermelho a partir de suas pontuações contínuas de olhos-abertos e sorriso, e adiciona controles deslizantes de limiar de **olhos** e **sorriso** ao vivo para que você ajuste na hora o que conta como uma piscada ou uma expressão fraca. Os limites são as chaves de configuração `face_detection.eyes_closed_max` e `face_detection.poor_expression_min` (ambas com padrão `4.0`); os controles deslizantes começam nesses valores.

**Comparação sincronizada (2-up / 4-up).** O cabeçalho da lightbox tem botões Único / Comparar 2 / Comparar 4. No modo de comparação, os painéis compartilham uma única transformação de panorâmica/zoom, então o zoom com roda do mouse ou panorâmica com arrasto em qualquer painel move todos para o recorte idêntico — a forma de escolher o quadro mais nítido de uma sequência inspecionando pixels de verdade. O duplo clique alterna ajuste ↔ zoom; além da escala de ajuste, cada painel troca preguiçosamente sua miniatura de 1920px pela fonte `/image` em resolução total, para que a inspeção fique nítida. Sem mudança no backend — ambas as rotas de imagem já existem. (O pinçar por toque ainda não está implementado; use a roda no desktop.)

API: veja a seção [Endpoints da API](#endpoints-da-api) abaixo.

## Visão de Cenas

Uma navegação **somente leitura** da sua biblioteca agrupada em "cenas" cronológicas — sequências por horário de captura exibidas na ordem da história com uma grade, uma lupa flutuante e cabeçalhos de data/momento. Aberta a **todos os usuários autenticados** (somente leitura e edição igualmente). As fotos são divididas em cenas por intervalos de horário de captura (uma nova cena começa quando mais de `scenes.gap_minutes` passam entre fotos consecutivas, ampliado de forma adaptativa em sessões esparsas), e qualquer sequência longa demais é subdividida para que um evento fotografado continuamente nunca colapse em uma única cena gigante.

O único ponto de entrada é o botão de ação por álbum **Exibir cenas deste álbum** na grade de Álbuns (um seletor de escopo de álbum dentro da navegação permite trocar o escopo). Não há entrada de Cenas na navegação principal. Cada cena carrega um botão **Triar esta cena** (somente edição) que cria um link direto para a superfície de [Triagem](#triagem) na granularidade de cena (`/culling?group_by=scene&album=&from=&to=`); usuários de edição também podem acessar Cenas-como-triagem diretamente pela navegação de Triagem. A navegação em si não tem grade de rejeição nem confirmação em lote — toda a triagem agora acontece pela superfície de Triagem unificada.

Quando os momentos narrativos são computados (abaixo), cada cena também é intitulada por seu momento dominante, e `scenes.split_on_moment_change` pode subdividir uma sequência longa onde o momento muda.

## Momentos Narrativos

O Facet rotula cada foto com o "momento" de cena/atividade que ela retrata. O vocabulário **general** padrão é agnóstico à biblioteca — celebração, refeição, praia, atividade aquática, montanhas, natureza e vida selvagem, paisagem urbana, ponto turístico de viagem, show, esportes, reunião em grupo, retrato, crianças, animais de estimação, vida noturna, cerimônia, paisagem cênica, neve e inverno, ambiente interno, estrada e veículo — ou `other` (um vocabulário `wedding` vem como um gênero opcional). Nem o Narrative Select nem o AfterShoot fazem isso; eles agrupam apenas por tempo e similaridade visual.

É **zero-shot e totalmente local**, e **semântico de legenda** (caption-semantic): a legenda por IA de cada foto é codificada uma vez e armazenada, e o momento é o melhor cosseno com **max-pooling** desse embedding de legenda contra os prompts de texto de cada momento (L0) — o embedding de imagem armazenado é o fallback quando uma foto não tem legenda. O sinal de legenda corresponde aos momentos ~2,4× de forma mais limpa do que a imagem bruta. Pequenos priors de rosto/tag desempatam quase-empates (L1), depois uma passagem de Viterbi **suaviza ao longo da linha do tempo** para que uma leitura incorreta isolada seja puxada de volta para a sequência circundante (L2). Um desempate opcional por VLM (L3, 16gb/24gb) pode rejulgar quadros de baixa confiança. Os embeddings de legenda são computados uma vez e reutilizados, então a re-rotulagem é um produto escalar barato sobre vetores armazenados — sem decodificação de imagem, sem passagem de modelo por imagem; **roda automaticamente ao final de cada varredura** (codificando apenas as novas legendas). A primeira passagem completa sobre uma biblioteca existente codifica cada legenda (GPU recomendada); reprocesse a biblioteca inteira com `python facet.py --recompute-moments`.

Os momentos surgem como títulos de cenas e como um filtro de galeria (`GET /api/photos?narrative_moment=beach`, opções de `GET /api/filter_options/narrative_moments`). O vocabulário é controlado por configuração por tipo de evento — veja [Configuração — Momentos Narrativos](CONFIGURATION.md#narrative-moments) para ajustar prompts/limiares ou trocar de gênero.

**Confiança do momento.** Cada rótulo armazena uma confiança posterior (`narrative_moment_confidence`). Rótulos abaixo de `viewer.moment_confidence_min` (padrão `0` = nunca esmaecer) são renderizados esmaecidos com um sufixo "(incerto)" no cabeçalho de Cenas, no cabeçalho de grupo de cena da Triagem e na dica da foto na galeria (que também mostra a % de confiança). A confiança também é uma opção de ordenação — **Confiança do Momento** (NULLs ao final) sob o grupo Conteúdo — e um filtro de faixa na galeria (`min_moment_confidence` / `max_moment_confidence`, um controle deslizante de 0–1 na seção **Momentos** da barra lateral).

- Cada cena mostra suas fotos líderes na ordem de captura
- Triar uma cena pelo seu botão **Triar esta cena**, que abre a superfície de triagem com escopo para aquela cena
- Cenas menores que `scenes.min_size` são omitidas; no máximo `scenes.max_photos` fotos são carregadas

API: veja a seção [Endpoints da API](#endpoints-da-api) abaixo.

Controlado por `viewer.features.show_scenes` (padrão: `true`). Veja [Configuração — Cenas](CONFIGURATION.md#scenes) para `gap_minutes`, `min_size`, `max_photos`, `max_scene_size`, `adaptive` e `adaptive_k`.

## Limpeza de lixo

Uma fila de revisão rápida para o "lixo" não fotográfico que se acumula em uma biblioteca amadora — capturas de tela, documentos escaneados, recibos, memes e slides de apresentação. A detecção é zero-shot sobre os embeddings de imagem armazenados (veja [Configuração — Junk Sweep](CONFIGURATION.md#junk-sweep)); execute `python facet.py --detect-junk` (ou deixe-o rodar automaticamente ao final de cada varredura) para preencher `junk_kind`.

Abra-a pelo botão de navegação **Limpeza** (a rota `/junk`, somente edição). A página reutiliza a grade da galeria e exibe cada candidato sinalizado:

- **Chips de filtro por tipo** — "Todos os tipos" mais um chip por tipo detectado com sua contagem (de `GET /api/filter_options/junk_kinds`). Clique para restringir a fila a um único tipo.
- **Manter** (por foto) — limpa o rótulo de lixo para que a foto saia da fila **permanentemente**: ela é marcada como avaliada-limpa (`not_junk`) e nunca mais é sinalizada por um `--detect-junk` posterior.
- **Rejeitar** (por foto) — marca a foto como rejeitada usando o mesmo mecanismo de rejeição de todo o resto (nada é excluído do disco).
- **Rejeitar tudo** — uma rejeição em lote de todos os candidatos atualmente carregados, atrás de um diálogo de confirmação.
- **Lupa** — pressione **`Z`** (ou o botão da barra de ferramentas) para uma lupa flutuante no estilo Photo Mechanic, para ler texto fino antes de decidir.

As fotos de lixo **não** são ocultadas da galeria normal — elas permanecem visíveis até você filtrar por elas. Filtre qualquer visão da galeria com `?junk_kind=<tipo>` (exato) ou `?junk_kind=any` (qualquer lixo, exclui a sentinela `not_junk`).

Controlado por `viewer.features.show_junk_sweep` (padrão: `true`).

## Modo de Comparação Pareada

Ranqueie fotos julgando-as de duas em duas. Os votos acumulados alimentam o ajuste de pesos. Acesse pela rota `/compare` (botão Comparar no cabeçalho). Requer uma `edition_password` não vazia (usuário único) ou o papel `admin`/`superadmin` (multiusuário).

A página tem quatro abas:

### Aba Comparar A/B

Pares de fotos lado a lado. Escolha um vencedor, marque um empate ou pule. Uma barra de progresso rastreia os votos em direção a 50, com contagens correntes de vitórias-A/vitórias-B/empates. Um filtro de categoria define o escopo da sessão, e um menu suspenso de estratégia de seleção controla como os pares são escolhidos.

| Estratégia | Descrição |
|----------|-------------|
| `uncertainty` | Fotos com pontuações semelhantes (mais informativas) |
| `boundary` | Faixa de pontuação 6–8 (zona ambígua) |
| `active` | Fotos com o menor número de comparações (garante cobertura) |
| `random` | Pares aleatórios (linha de base) |

**Atalhos de teclado:**

| Tecla | Ação |
|-----|--------|
| `A` | Foto da esquerda vence |
| `B` | Foto da direita vence |
| `T` | Empate |
| `S` | Pular par |
| `Escape` | Fechar o modal de substituição de categoria |

### Aba Sugestões de Pesos

Mostra os pesos aprendidos das comparações em relação aos pesos atuais, lado a lado, com a precisão do modelo antes/depois. As top 10 fotos atuais e as top 10 previstas após o recálculo são visualizadas em colunas adjacentes. **Aplicar** grava os pesos sugeridos; **Recalcular** repontua a categoria para aplicá-los (ambos requerem o modo de edição).

### Aba Pesos

Editor de pesos manual: um controle deslizante por métrica para a categoria selecionada com uma prévia de pontuação ao vivo. **Salvar** grava no `scoring_config.json` (com um backup); **Recalcular Pontuações** os aplica; **Redefinir** recarrega os pesos armazenados.

### Aba Instantâneos

Salve os pesos atuais como um instantâneo nomeado e restaure qualquer instantâneo anterior.

### Substituição de Categoria

Para reatribuir a categoria de uma foto a partir da visão de comparação: edite o selo de categoria, selecione uma categoria de destino, execute "Analisar Conflitos de Filtro" para ver quais filtros a excluem, depois aplique a substituição.

## Estatísticas EXIF

A página de Estatísticas (`/stats`) fornece análises em 5 abas. Use os seletores de **categoria** e **intervalo de datas** na barra de ferramentas para filtrar todos os gráficos para um subconjunto específico da sua biblioteca.

### Abas

| Aba | Descrição |
|-----|-------------|
| **Equipamento** | Corpos de câmera, lentes e combinações (top 20 de cada) |
| **Configurações de Captura** | Distribuições de ISO, abertura, distância focal, velocidade do obturador |
| **Linha do Tempo** | Fotos ao longo do tempo |
| **Categorias** | Análises de categoria, gerenciamento de pesos e correlações de pontuação |
| **Correlações** | Gráficos de correlação personalizados de métrica X/Y com agrupamento |

### Aba Categorias

Quatro sub-abas:

| Sub-aba | Descrição |
|---------|-------------|
| **Detalhamento** | Contagens de fotos por categoria, pontuações médias, histogramas de distribuição de pontuação |
| **Pesos** | Comparação por gráfico de radar (até 5 categorias), mapa de calor de pesos e editor de pesos (modo de edição) |
| **Correlações** | Mapa de calor de correlação de Pearson mostrando como cada dimensão influencia a agregada, visão de detalhe ao clicar |
| **Sobreposição** | Análise de sobreposição de filtros mostrando quais categorias compartilham fotos correspondentes |

Cada gráfico tem um botão de ajuda `?` alternável que explica como lê-lo. Uma alternância de ajuda global na barra de sub-abas mostra as explicações de todas as sub-abas.

### Editor de Pesos (Modo de Edição)

Disponível na sub-aba Pesos quando o modo de edição está ativo:

1. Selecione uma categoria no menu suspenso
2. Ajuste os controles deslizantes de peso (um por métrica, devem somar 100%)
3. Use "Normalizar para 100" para autobalancear
4. Expanda a seção recolhível de Modificadores para ajustar bônus/penalidades
5. A **Prévia de Distribuição de Pontuação** mostra um histograma ao vivo antes/depois conforme você move os controles deslizantes
6. Clique em **Salvar** para atualizar o `scoring_config.json` (cria um backup com data e hora)
7. Clique em **Recalcular Pontuações** (aparece após salvar) para aplicar os novos pesos a todas as fotos daquela categoria

Todas as estatísticas são sensíveis ao usuário no modo multiusuário — cada usuário vê análises apenas de suas fotos visíveis.

## Atalhos de Teclado (Galeria)

| Tecla | Ação |
|-----|--------|
| `←` `→` `↑` `↓` | Move o foco do teclado entre os cartões de foto (colunas da grade e linhas do mosaico) |
| `Enter` | Abre a foto em foco |
| `Space` | Seleciona / desseleciona a foto em foco |
| `Ctrl+A` | Seleciona todas as fotos carregadas |
| `Escape` | Limpa a seleção / fecha a gaveta de filtros |
| `Shift+Click` | Seleciona em intervalo as fotos entre a última selecionada e a clicada |
| `Double-click` | Abre a foto |
| `?` | Mostra a referência de atalhos de teclado (funciona em todas as páginas) |

## Desfazer

Operações em lote de favoritar/rejeitar/avaliar e confirmações de triagem mostram uma snackbar
com uma ação **Desfazer** por cerca de 7 segundos. As operações de marcação em lote são confirmadas
imediatamente e desfeitas por chamadas de API inversas (limitadas a 500 fotos); as confirmações
de triagem são adiadas — o grupo desaparece instantaneamente, mas a chamada de API só
dispara quando a janela de desfazer expira.

## Progressive Web App

O visualizador inclui um manifesto de web app e um service worker do Angular (apenas em
builds de produção): ele pode ser instalado na tela inicial, o app shell carrega
offline, e até 1000 miniaturas são armazenadas em cache LRU por 7 dias. As respostas da API
nunca são armazenadas em cache (exceto os bundles de i18n com uma estratégia de atualização), e o logout
limpa o cache de miniaturas para que configurações multiusuário compartilhando um navegador não vazem
prévias entre contas. Uma snackbar oferece um recarregamento quando uma nova versão é
implantada.

## Mobile

Em telas pequenas, a barra de seleção em lote colapsa para a contagem da seleção,
limpar, selecionar-tudo e um único botão **Ações** que abre uma folha inferior
amigável ao toque com todas as operações em lote (favoritar, rejeitar, avaliar, álbuns, copiar,
baixar).

## Configuração

### Configurações de Exibição

```json
{
  "viewer": {
    "display": {
      "tags_per_photo": 4,
      "card_width_px": 168,
      "image_width_px": 160,
      "image_jpeg_quality": 96
    }
  }
}
```

### Paginação

```json
{
  "viewer": {
    "pagination": {
      "default_per_page": 64
    }
  }
}
```

### Limites de Menus Suspensos

```json
{
  "viewer": {
    "dropdowns": {
      "max_cameras": 50,
      "max_lenses": 50,
      "max_persons": 50,
      "max_tags": 20,
      "min_photos_for_person": 10
    }
  }
}
```

Defina `min_photos_for_person` mais alto para ocultar do menu suspenso de filtro as pessoas com poucas fotos.

### Limiares de Qualidade

```json
{
  "viewer": {
    "quality_thresholds": {
      "good": 6,
      "great": 7,
      "excellent": 8,
      "best": 9
    }
  }
}
```

### Filtros Padrão

```json
{
  "viewer": {
    "defaults": {
      "hide_blinks": true,
      "hide_bursts": true,
      "hide_duplicates": true,
      "hide_details": true,
      "hide_rejected": true,
      "sort": "aggregate",
      "sort_direction": "DESC",
      "type": ""
    },
    "default_category": ""
  }
}
```

### Pesos das Melhores Escolhas

```json
{
  "viewer": {
    "photo_types": {
      "top_picks_min_score": 7,
      "top_picks_min_face_ratio": 0.2,
      "top_picks_weights": {
        "aggregate_percent": 30,
        "aesthetic_percent": 28,
        "composition_percent": 18,
        "face_quality_percent": 24
      }
    }
  }
}
```

## Desempenho

### Bancos de Dados Grandes (50k+ fotos)

Execute estes comandos para melhor desempenho:

```bash
python database.py --migrate-tags    # 10-50x faster tag queries
python database.py --refresh-stats   # Precompute aggregations
python database.py --optimize        # Defragment database
```

### SQLite Assíncrono (opcional, para caminhos de leitura de alta concorrência)

`api.database.get_async_db()` é um gerenciador de contexto assíncrono apoiado por aiosqlite,
paralelo ao `get_db()`. Os endpoints são atualmente síncronos (o FastAPI os delega
a um pool de threads de trabalho, o que é adequado para concorrência típica). Para caminhos de
leitura de alta concorrência (>5 usuários simultâneos), endpoints individuais podem ser
migrados assim:

1. Mude `def foo(...)` para `async def foo(...)`.
2. Substitua `with get_db() as conn:` por `async with get_async_db() as conn:`.
3. Use `await` em cada `.execute()` e `.fetchone()` / `.fetchall()`.
4. Mantenha os caminhos de escrita síncronos — o aiosqlite serializa as escritas de qualquer forma, e o
   pool de conexões do caminho síncrono já as gerencia.

Os candidatos mais quentes do plano são `/api/photos`, `/api/timeline`,
`/api/search`. Migre um de cada vez e faça benchmark antes de promover.

### Cache de Estatísticas

Agregações pré-computadas com TTL de 5 minutos:
- Contagens totais de fotos
- Contagens de modelos de câmera/lente
- Contagens de pessoas
- Contagens de categorias e padrões

Verifique o status:
```bash
python database.py --stats-info
```

### Carregamento Preguiçoso de Filtros

Os menus suspensos de filtro carregam sob demanda via API:
- `/api/filter_options/cameras`
- `/api/filter_options/lenses`
- `/api/filter_options/tags`
- `/api/filter_options/persons`
- `/api/filter_options/patterns`
- `/api/filter_options/categories`
- `/api/filter_options/apertures`
- `/api/filter_options/focal_lengths`
- `/api/filter_options/colors`
- `/api/filter_options/metric_ranges`

## Endpoints da API

A documentação interativa da API está disponível em `/api/docs` (Swagger UI) e o esquema OpenAPI em `/api/openapi.json`.

### Galeria

| Endpoint | Descrição |
|----------|-------------|
| `GET /api/photos` | Lista paginada de fotos com filtros |
| `GET /api/photo` | Detalhes de uma única foto |
| `GET /api/type_counts` | Contagens de fotos por tipo |
| `GET /api/similar_photos/{path}` | Fotos semelhantes (modos: `visual`, `color`, `person`) |
| `GET /api/search?q=&limit=&threshold=&scope=` | Busca semântica de texto para imagem (`scope=text` = apenas texto OCR/legenda) |
| `GET /api/critique?path=&mode=&refresh=` | Crítica por IA (baseada em regras ou VLM); `refresh=true` regenera a crítica VLM em cache |
| `GET /api/ranker/status` | Status do ranqueador pessoal para a ordenação "Meu Gosto" (% de cobertura aprendida, precisão em dados retidos) |
| `GET /api/config` | Configuração do visualizador |

### Autenticação

| Endpoint | Descrição |
|----------|-------------|
| `POST /api/auth/login` | Autentica e recebe um token |
| `POST /api/auth/edition/login` | Desbloqueia o modo de edição |
| `POST /api/auth/edition/logout` | Bloqueia o modo de edição (abandona privilégios, permanece autenticado) |
| `GET /api/auth/status` | Verifica o status de autenticação |

### Miniaturas e Imagens

| Endpoint | Descrição |
|----------|-------------|
| `GET /thumbnail` | Miniatura da foto |
| `GET /face_thumbnail/{id}` | Miniatura de recorte de rosto |
| `GET /person_thumbnail/{id}` | Miniatura representativa da pessoa |
| `GET /image` | Imagem em resolução total |

### Opções de Filtro

| Endpoint | Descrição |
|----------|-------------|
| `GET /api/filter_options/cameras` | Modelos de câmera com contagens |
| `GET /api/filter_options/lenses` | Modelos de lente com contagens |
| `GET /api/filter_options/tags` | Tags com contagens |
| `GET /api/filter_options/persons` | Pessoas com contagens |
| `GET /api/filter_options/patterns` | Padrões de composição |
| `GET /api/filter_options/categories` | Categorias com contagens |
| `GET /api/filter_options/apertures` | Valores distintos de f-stop com contagens |
| `GET /api/filter_options/focal_lengths` | Distâncias focais distintas com contagens |
| `GET /api/filter_options/colors` | Facetas de temperatura de cor e faixa de matiz com contagens |
| `GET /api/filter_options/metric_ranges` | Mín/máx observados e histograma por métrica numérica (para limites do controle deslizante) |

### Operações em Lote

| Endpoint | Descrição |
|----------|-------------|
| `POST /api/photos/batch_favorite` | Marca várias fotos como favoritas |
| `POST /api/photos/batch_reject` | Marca várias fotos como rejeitadas |
| `POST /api/photos/batch_rating` | Define a avaliação por estrelas para várias fotos |

### Pessoas

| Endpoint | Descrição |
|----------|-------------|
| `GET /api/persons` | Lista todas as pessoas |
| `POST /api/persons` | Cria uma nova pessoa, opcionalmente anexando rostos (restrito à edição). Corpo: `{name, face_ids}` |
| `GET /api/persons/needs_naming?min_faces=N` | Lista pessoas agrupadas automaticamente e sem nome com `face_count >= N` (padrão de `viewer.persons.needs_naming_min_faces`) |
| `POST /api/persons/{id}/rename` | Renomeia uma pessoa |
| `POST /api/persons/{id}/assign_faces` | Anexa rostos em massa a uma pessoa; pessoas antigas vazias são excluídas automaticamente (restrito à edição). Corpo: `{face_ids}` |
| `POST /api/persons/{id}/split` | Divide um subconjunto dos rostos de uma pessoa em uma nova pessoa (restrito à edição). Corpo: `{face_ids, name}` |
| `POST /api/persons/{id}/hide` | Oculta uma pessoa da lista, filtros e sugestões de mesclagem |
| `POST /api/persons/{id}/unhide` | Reexibe uma pessoa anteriormente oculta |
| `POST /api/persons/merge` | Mescla duas pessoas (corpo JSON) |
| `POST /api/persons/merge/{source_id}/{target_id}` | Mescla a pessoa de origem no destino |
| `POST /api/persons/merge_batch` | Mescla várias pessoas de uma vez |
| `POST /api/persons/merge_suggestions/reject` | Descarta uma sugestão de mesclagem para que não seja proposta novamente |
| `POST /api/persons/{id}/delete` | Exclui uma pessoa |
| `POST /api/persons/delete_batch` | Exclui várias pessoas de uma vez |

### Álbuns

| Endpoint | Descrição |
|----------|-------------|
| `GET /api/albums` | Lista todos os álbuns |
| `POST /api/albums` | Cria um álbum |
| `GET /api/albums/{id}` | Obtém os detalhes do álbum |
| `PUT /api/albums/{id}` | Atualiza o álbum |
| `DELETE /api/albums/{id}` | Exclui o álbum |
| `GET /api/albums/{id}/photos` | Lista as fotos do álbum (paginado) |
| `POST /api/albums/{id}/photos` | Adiciona fotos ao álbum |
| `DELETE /api/albums/{id}/photos` | Remove fotos do álbum |
| `POST /api/albums/{id}/share` | Gera um token de compartilhamento |
| `DELETE /api/albums/{id}/share` | Revoga o token de compartilhamento |
| `GET /api/shared/album/{id}?token=` | Visualiza o álbum compartilhado (sem autenticação) |
| `POST /api/shared/album/{id}/session` | Troca um token de compartilhamento (+ PIN opcional) por uma sessão de aprovação de cliente (com limite de taxa) |
| `PUT /api/shared/album/{id}/picks` | O cliente insere/atualiza uma curtida/comentário em uma foto (sessão de aprovação) |
| `GET /api/shared/album/{id}/picks` | O cliente lê suas próprias escolhas (sessão de aprovação) |
| `GET /api/albums/{id}/picks` | `[Edition]` O dono lê todas as escolhas de clientes do álbum |

### Memórias, Linha do Tempo, Mapa e Legendas

| Endpoint | Descrição |
|----------|-------------|
| `GET /api/memories?date=` | Fotos tiradas nesta data em anos anteriores |
| `GET /api/memories/check` | Verifica se existem memórias para uma data |
| `GET /api/caption?path=` | Obtém ou gera uma legenda por IA |
| `PUT /api/caption` | Atualiza a legenda da foto (modo de edição) |
| `GET /api/timeline?cursor=&limit=&direction=` | Fotos paginadas da linha do tempo |
| `GET /api/timeline/dates?year=&month=` | Datas disponíveis para navegação |
| `GET /api/timeline/years` | Anos disponíveis com contagens de fotos |
| `GET /api/timeline/months` | Meses disponíveis para um ano |
| `GET /api/photos/map?bounds=&zoom=&limit=` | Fotos geolocalizadas dentro dos limites |
| `GET /api/photos/map/count` | Contagem de fotos geolocalizadas |

### Cápsulas

| Endpoint | Descrição |
|----------|-------------|
| `GET /api/capsules` | Lista paginada de cápsulas (em cache) |
| `GET /api/capsules/{id}/photos` | Fotos de uma cápsula específica |
| `POST /api/capsules/{id}/save-album` | Salva a cápsula como álbum (modo de edição) |

### Estatísticas

| Endpoint | Descrição |
|----------|-------------|
| `GET /api/stats/overview` | Resumo geral das estatísticas de pontuação |
| `GET /api/stats/score_distribution` | Dados do histograma de distribuição de pontuação |
| `GET /api/stats/top_cameras` | Principais câmeras por contagem de fotos |
| `GET /api/stats/categories` | Contagens e médias de categorias |
| `GET /api/stats/gear` | Contagens de câmera/lente/combinação |
| `GET /api/stats/settings` | Distribuições de configurações de captura |
| `GET /api/stats/timeline` | Dados da linha do tempo |
| `GET /api/stats/correlations` | Correlações de métricas personalizadas |
| `GET /api/stats/categories/breakdown` | Contagens de fotos por categoria e distribuições de pontuação |
| `GET /api/stats/categories/weights` | Pesos e modificadores de categoria da configuração |
| `GET /api/stats/categories/correlations` | Correlação r de Pearson por dimensão por categoria |
| `GET /api/stats/categories/metrics?category=X` | Valores brutos de métricas para prévia no cliente |
| `GET /api/stats/categories/overlap` | Análise de sobreposição de filtros entre categorias |
| `POST /api/stats/categories/update` | Atualiza pesos/modificadores de categoria (modo de edição) |
| `POST /api/stats/categories/recompute` | Recalcula as pontuações de uma categoria (modo de edição) |

### Modo de Comparação

| Endpoint | Descrição |
|----------|-------------|
| `GET /api/comparison/next_pair` | Obtém o próximo par de fotos para comparação |
| `POST /api/comparison/submit` | Envia o resultado da comparação |
| `POST /api/comparison/reset` | Redefine os dados de comparação |
| `GET /api/comparison/stats` | Estatísticas da sessão de comparação |
| `GET /api/comparison/history` | Lista comparações anteriores |
| `POST /api/comparison/edit` | Edita o resultado de uma comparação |
| `POST /api/comparison/delete` | Exclui uma comparação |
| `GET /api/comparison/coverage` | Cobertura de comparações por categoria |
| `GET /api/comparison/confidence` | Métricas de confiança para pontuações aprendidas |
| `GET /api/comparison/photo_metrics` | Métricas brutas das fotos |
| `GET /api/comparison/category_weights` | Pesos/filtros de categoria |
| `GET /api/comparison/learned_weights` | Pesos sugeridos a partir de comparações |
| `POST /api/comparison/preview_score` | Prévia com pesos personalizados |
| `POST /api/comparison/suggest_filters` | Analisa conflitos de filtro |
| `POST /api/comparison/override_category` | Substitui a categoria da foto |
| `POST /api/recalculate` | Recalcula as pontuações com os pesos atuais |

### Triagem de Sequências

| Endpoint | Descrição |
|----------|-------------|
| `GET /api/burst-groups` | Lista grupos de sequência para triagem |
| `POST /api/burst-groups/select` | Seleciona as fotos a manter de um grupo de sequência |
| `GET /api/similar-groups?threshold=&page=&per_page=` | Grupos de fotos visualmente semelhantes |
| `POST /api/similar-groups/select` | Seleciona as fotos a manter de um grupo semelhante |
| `GET /api/culling-groups?group_by=all\|burst\|similar\|scene&exclude_rejected=true&similarity_threshold=&page=&per_page=` | Grupos de sequência/semelhantes/cena para triagem. `group_by` (padrão `all`) seleciona grupos combinados de sequência+semelhantes, apenas de sequência, apenas semelhantes, ou grupos de cenas cronológicas (grupos de cena adicionam `type`/`start`/`end`/`moment`/`moment_confidence`; o parâmetro `sort` é ignorado no modo de cena). `exclude_rejected` (padrão `true`) oculta fotos com `is_rejected=1`; grupos com menos de 2 fotos restantes são descartados |
| `POST /api/culling-groups/confirm` | Confirma as seleções de triagem (sequência, semelhantes ou cena). Corpo `{group_id, type, paths, keep_paths}`; `type:'scene'` registra as linhas de comparação de triagem de cena |
| `POST /api/culling/auto` | `[Edition]` Triagem automática de um botão só para um escopo inteiro. Corpo `{group_by, album_id?, date_from?, date_to?, strictness?, min_keep_per_group, highlights_album, dry_run}`; `dry_run` (padrão `true`) retorna a prévia de manter/rejeitar por grupo, uma aplicação rejeita o resto e registra pares de triagem |
| `POST /api/culling-group/faces` | Selos por rosto (olhos abertos/fechados, expressão, confiança) para um grupo, em um único lote |
| `GET /api/scenes` | Cenas cronológicas de fotos líderes de sequência (navegação somente leitura) |
| `GET /api/filter_options/junk_kinds` | Tipos de lixo detectados com contagem (exclui a sentinela `not_junk`) para os chips da Limpeza de lixo |
| `POST /api/photo/clear_junk` | `[Edition]` Mantém um candidato a lixo — redefine seu `junk_kind` para `not_junk` para que ele saia da fila permanentemente. Corpo `{photo_path}` |

### Varredura

| Endpoint | Descrição |
|----------|-------------|
| `POST /api/scan/start` | `[Superadmin]` Inicia uma varredura de pontuação |
| `GET /api/scan/status` | Verifica o progresso da varredura (`progress` estruturado: `{phase, current, total, eta_seconds}`) |
| `GET /api/scan/stream?token=<jwt>` | `[Superadmin]` Progresso em tempo real via Server-Sent Events; o token é passado como parâmetro de consulta (a API `EventSource` não pode definir cabeçalhos), com fallback automático para polling de `/status` |
| `GET /api/scan/directories` | Lista os diretórios de varredura configurados |

### Gerenciamento de Rostos

| Endpoint | Descrição |
|----------|-------------|
| `GET /api/person/{id}/faces` | Lista os rostos de uma pessoa |
| `POST /api/person/{id}/avatar` | Define o rosto de avatar da pessoa |
| `GET /api/photo/faces` | Lista os rostos detectados em uma foto |
| `POST /api/face/{id}/assign` | Atribui um rosto a uma pessoa |
| `POST /api/photo/assign_all_faces` | Atribui todos os rostos de uma foto a uma pessoa |
| `POST /api/photo/unassign_person` | Desatribui uma pessoa de uma foto |

### Ações de Foto

| Endpoint | Descrição |
|----------|-------------|
| `POST /api/photo/set_rating` | Define a avaliação por estrelas de uma foto |
| `POST /api/photo/toggle_favorite` | Alterna o status de favorito |
| `POST /api/photo/toggle_rejected` | Alterna o status de rejeição |

### Gerenciamento de Configuração

| Endpoint | Descrição |
|----------|-------------|
| `POST /api/config/update_weights` | Atualiza os pesos de pontuação |
| `GET /api/config/weight_snapshots` | Lista os instantâneos de pesos salvos |
| `POST /api/config/save_snapshot` | Salva os pesos atuais como instantâneo |
| `POST /api/config/restore_weights` | Restaura os pesos de um instantâneo |

### Sugestões de Mesclagem

| Endpoint | Descrição |
|----------|-------------|
| `GET /api/merge_suggestions` | Sugestões de mesclagem de pessoas com base na similaridade de rostos |

### Pastas

| Endpoint | Descrição |
|----------|-------------|
| `GET /api/folders` | Lista a estrutura de pastas de fotos |

### Download

| Endpoint | Descrição |
|----------|-------------|
| `GET /api/download/options` | Tipos de download disponíveis para uma foto (`path`, `is_shared` opcional) |
| `GET /api/download` | Baixa uma foto (`path`, `type=original\|darktable\|raw`, `profile` opcional) |

**Tipos de download:**

- `original` — Serve o arquivo como está (JPG/HEIF) ou convertido para JPEG por rawpy (arquivos RAW).
- `darktable` — Converte o RAW companheiro com um perfil darktable nomeado (requer o parâmetro `profile`). Recorre ao original se não houver RAW companheiro.
- `raw` — Serve o arquivo RAW companheiro como está (não disponível em álbuns compartilhados).

O endpoint `/api/download/options` detecta automaticamente arquivos RAW companheiros e retorna as opções disponíveis, incluindo perfis darktable configurados. O visualizador usa isso para preencher um menu de download por foto.

### Exportação para Editor

| Endpoint | Descrição |
|----------|-------------|
| `POST /api/photo/export_xmp` | `[Edition]` Grava um sidecar XMP |
| `POST /api/export/sidecars` | `[Edition]` Grava sidecars para caminhos explícitos ou um conjunto de filtros |
| `POST /api/photo/embed_metadata` | `[Edition]` Incorpora metadados no arquivo original (JPEG/HEIC/TIFF/PNG/DNG; RAW nunca modificado) e grava o sidecar |
| `POST /api/albums/{id}/export` | `[Edition]` Exportação de álbum como sidecars, cópia ou link simbólico |

### Plugins

| Endpoint | Descrição |
|----------|-------------|
| `GET /api/plugins` | Lista os plugins configurados |
| `POST /api/plugins/test-webhook` | Testa um plugin de webhook |

### Saúde

| Endpoint | Descrição |
|----------|-------------|
| `GET /health` | Verificação de saúde do servidor |
| `GET /ready` | Verificação de prontidão do servidor |
| `GET /metrics` | Métricas em formato Prometheus: contagens de fotos, cobertura de embeddings, tamanho do BD, memória do processo |

### Internacionalização

| Endpoint | Descrição |
|----------|-------------|
| `GET /api/i18n/languages` | Lista os idiomas disponíveis |
| `GET /api/i18n/{lang}` | Obtém as traduções de um idioma |

### Opções de Filtro (adicionais)

| Endpoint | Descrição |
|----------|-------------|
| `GET /api/filter_options/location_name?lat=&lng=` | Geocodifica coordenadas reversamente para um nome de lugar |

## Solução de Problemas

| Problema | Solução |
|-------|----------|
| Carregamento lento da página | Execute `--migrate-tags` e `--optimize` |
| Filtros não aparecem | Verifique `--stats-info`, execute `--refresh-stats` |
| Filtro de pessoa vazio | Execute `--cluster-faces-incremental` |
| Botão Comparar ausente | Defina uma `edition_password` não vazia (usuário único) ou use o papel `admin`/`superadmin` (multiusuário) |
| Senha não funciona | Verifique `viewer.password` (usuário único) ou verifique o hash da senha (multiusuário) |
| Usuário não consegue ver fotos | Verifique `directories` na configuração do usuário e `shared_directories` |
| Botão de varredura ausente | Requer o papel `superadmin` e `viewer.features.show_scan_button: true` |
| Busca não retorna resultados | Garanta que as fotos tenham dados `clip_embedding` (execute a pontuação primeiro) |
| Crítica por VLM indisponível | Requer o perfil de VRAM 16gb/24gb e `viewer.features.show_vlm_critique: true` |
| Mapa não mostra fotos | Execute `--extract-gps` para preencher as colunas GPS, garanta que as fotos tenham dados GPS EXIF |
| Legendas não são geradas | Requer o perfil de VRAM 16gb/24gb para legendagem por VLM |
| Linha do tempo vazia | Garanta que as fotos tenham valores em `date_taken` |
| Porta 5000 em uso | Execute `python viewer.py --port 5001` (ou defina `PORT=5001`). No macOS, o AirPlay Receiver do ControlCenter vincula a 5000 por padrão — escolha outra porta ou desative o AirPlay Receiver em Ajustes do Sistema → Geral → AirDrop e Handoff. |
