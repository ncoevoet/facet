# Visualizador Web

> 🌐 [English](../VIEWER.md) · [Français](../fr/VIEWER.md) · [Deutsch](../de/VIEWER.md) · [Italiano](../it/VIEWER.md) · [Español](../es/VIEWER.md) · **Português**

Aplicação de página única em FastAPI + Angular para navegar, filtrar e gerenciar fotos.

## Conteúdo

- [Iniciando o Visualizador](#starting-the-viewer) · [Autenticação](#authentication) · [Opções de Filtragem](#filtering-options) · [Ordenação](#sorting) · [Recursos da Galeria](#gallery-features)
- [Gerenciamento de Pessoas](#person-management) · [Disparar Varredura (Superadmin)](#scan-trigger-superadmin) · [Busca Semântica](#semantic-search) · [Álbuns](#albums)
- [Crítica por IA](#ai-critique) · [Legendagem por IA](#ai-captioning-gpu-16gb24gb-edition) · [Memórias ("Neste Dia")](#memories-on-this-day) · [Visão Linha do Tempo](#timeline-view) · [Visão Mapa](#map-view) · [Cápsulas](#capsules)
- [Visão Pastas](#folders-view) · [Diálogo de Filtro GPS](#gps-filter-dialog) · [Sugestões de Mesclagem](#merge-suggestions) · [Exportação para Editores](#editor-export) · [Triagem](#culling) · [Modo de Comparação por Pares](#pairwise-comparison-mode)
- [Estatísticas EXIF](#exif-statistics) · [Atalhos de Teclado](#keyboard-shortcuts-gallery) · [Desfazer](#undo) · [Progressive Web App](#progressive-web-app) · [Mobile](#mobile)
- [Configuração](#configuration) · [Desempenho](#performance) · [Endpoints da API](#api-endpoints) · [Solução de Problemas](#troubleshooting)

> **Os requisitos de cada recurso** são marcados inline: `[GPU]` · `[16gb/24gb]` (perfil de VRAM) · `[Edition]` (senha de edição) · `[Superadmin]`. Veja a [matriz de recursos](../README.md#feature-availability--requirements).

## Iniciando o Visualizador

### Produção

```bash
python viewer.py
# Open http://localhost:5000
```

Isso serve tanto a API quanto a aplicação Angular pré-compilada em uma única porta.

Para maior throughput, execute em modo de produção (Uvicorn, sem auto-reload). Adicione `--workers N` para escalar (padrão 1):

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

Proteção opcional por senha via configuração:

```json
{
  "viewer": {
    "password": "your-password-here"
  }
}
```

Quando definida, os usuários devem se autenticar antes de acessar o visualizador. Uma `edition_password` opcional concede acesso ao gerenciamento de pessoas e ao modo de comparação.

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

Os usuários são criados somente via CLI (sem interface de registro):

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

### Visibilidade das Fotos

Cada usuário vê fotos de seus diretórios configurados mais os diretórios compartilhados. A visibilidade é aplicada em todos os endpoints: galeria, miniaturas, downloads, estatísticas, opções de filtro e páginas de pessoas.

### Avaliações por Usuário

No modo multiusuário, as classificações por estrelas, favoritos e marcações de rejeitado são armazenadas por usuário na tabela `user_preferences`. Cada usuário avalia de forma independente — os favoritos de Alice não afetam a visão de Bob.

Para migrar avaliações existentes de usuário único:

```bash
python database.py --migrate-user-preferences --user alice
```

## Opções de Filtragem

<details><summary>Barra lateral de filtros completa — todas as seções expandidas (clique para ver)</summary>
<p align="center"><img src="screenshots/filter-sidebar-full.jpg" alt="Barra lateral de filtros com todas as seções expandidas" width="360"></p>
</details>

### Filtros Primários

| Filtro | Opções |
|--------|---------|
| **Tipo de Foto** | Top Picks, Retratos, Pessoas na Cena, Paisagens, Arquitetura, Natureza, Animais, Arte & Estátuas, Preto & Branco, Pouca Luz, Silhuetas, Macro, Astrofotografia, Rua, Longa Exposição, Aérea & Drone, Shows |
| **Nível de Qualidade** | Bom (6+), Ótimo (7+), Excelente (8+), Melhor (9+) |
| **Câmera & Lente** | Filtragem por equipamento |
| **Pessoa** | Filtrar por pessoa reconhecida |
| **Categoria** | Filtrar por categoria de foto |

### Filtros Avançados

| Categoria | Filtros |
|----------|---------|
| **Data** | Data inicial e final |
| **Pontuações** | Agregada, estética, pontuação TOPIQ, pontuação de qualidade |
| **Qualidade Estendida** | IAA estético (mérito artístico), Face Quality IQA, pontuação LIQE |
| **Métricas Faciais** | Qualidade do rosto, nitidez dos olhos, nitidez do rosto, proporção do rosto, confiança do rosto, contagem de rostos |
| **Composição** | Pontuação de composição, pontos de poder, linhas-guia, isolamento, padrão de composição |
| **Saliência do Sujeito** | Nitidez do sujeito, proeminência do sujeito, posicionamento do sujeito, separação do fundo |
| **Técnica** | Nitidez, contraste, faixa dinâmica, nível de ruído |
| **Cor** | Pontuação de cor, saturação, luminância, espalhamento do histograma; temperatura de cor (quente/fria/neutra) e faixa de matiz (requer `--recompute-colors`) |
| **Exposição** | Pontuação de exposição |
| **Avaliações do Usuário** | Classificação por estrelas |
| **Configurações da Câmera** | ISO, abertura (slider de faixa de f-stop), distância focal (slider de faixa) |
| **Conteúdo** | Tags, alternância monocromática |

### Padrões de Composição

Filtre pelos padrões detectados pelo SAMP-Net:
- rule_of_thirds, golden_ratio, center, diagonal
- horizontal, vertical, symmetric, triangle
- curved, radial, vanishing_point, pattern, fill_frame

## Ordenação

Colunas ordenáveis agrupadas por categoria (de `viewer.sort_options`):

| Grupo | Colunas |
|-------|---------|
| **Geral** | Pontuação Agregada, Estética, Pontuação de Qualidade, Data da Captura, Classificação por Estrelas, Estética (IAA), Pontuação LIQE |
| **Métricas Faciais** | Qualidade do Rosto, Qualidade do Rosto (IQA), Nitidez dos Olhos, Nitidez do Rosto, Proporção do Rosto, Contagem de Rostos |
| **Técnica** | Nitidez Técnica, Contraste, Nível de Ruído |
| **Cor** | Pontuação de Cor, Saturação |
| **Exposição** | Pontuação de Exposição, Luminância Média, Espalhamento do Histograma, Faixa Dinâmica |
| **Composição** | Pontuação de Composição, Pontuação de Pontos de Poder, Linhas-Guia, Bônus de Isolamento, Padrão de Composição |
| **Saliência do Sujeito** | Nitidez do Sujeito, Proeminência do Sujeito, Posicionamento do Sujeito, Separação do Fundo |

### My Taste

Uma opção de ordenação de primeira classe apoiada pelo `learned_score` do ranqueador pessoal (renomeada de "Picked for you"). Ela ordena as fotos pelo que o ranqueador aprendeu com suas comparações A/B, avaliações e decisões de triagem. Um selo de confiança ao lado da ordenação mostra a cobertura aprendida (% de fotos com uma pontuação aprendida) e a acurácia do ranqueador em dados retidos, para que você possa julgar o quanto confiar na ordenação. Treine ou atualize o ranqueador com `python facet.py --train-ranker`.

Controlada por `viewer.features.show_my_taste` (padrão: `true`). O status do ranqueador é exposto via `GET /api/ranker/status`.

## Recursos da Galeria

### Cartões de Foto

- Miniatura com selo de pontuação
- Tags clicáveis para filtragem rápida
- Avatares de pessoas para rostos reconhecidos
- Selo de categoria

### Multisseleção & Ações em Lote

- Clique nas fotos para selecionar, Shift+Clique para seleção de intervalo
- A barra de ações aparece com a contagem da seleção e as ações disponíveis
- **Favoritar** — Marca todas as selecionadas como favoritas (limpa rejeitado)
- **Rejeitar** — Marca todas as selecionadas como rejeitadas (limpa favorito e classificação)
- **Avaliar** — Define a classificação por estrelas (1–5) para todas as selecionadas, ou limpa a classificação
- **Adicionar ao álbum** — Adiciona as selecionadas a um álbum existente ou novo
- **Copiar nomes de arquivo** — Copia os nomes de arquivo selecionados para a área de transferência
- **Exportar** — Escreve sidecars XMP (classificação/favorito/rejeitado) ao lado dos arquivos selecionados (veja [Exportação para Editores](#editor-export))
- **Baixar** — Baixa as fotos selecionadas
- Limpe a seleção com Escape ou o botão Limpar

As ações em lote exigem o modo de edição. Dê duplo clique em qualquer foto para baixá-la diretamente.

### Opções de Exibição

- **Modo de Layout** - Alterne entre **Grade** (cartões uniformes) e **Mosaico** (linhas justificadas preservando as proporções). O Mosaico é exclusivo para desktop; o mobile sempre usa grade.
- **Tamanho da Miniatura** - Slider para ajustar a altura do cartão/linha (120–400px, persistido no localStorage)
- **Ocultar Detalhes** - Oculta os metadados da foto nos cartões (somente no modo grade)
- **Ocultar Tooltip** - Desativa o tooltip de hover que mostra os detalhes da foto no desktop
- **Ocultar Piscadas** - Filtra fotos com piscadas detectadas
- **Melhor da Rajada** - Mostra apenas a foto com maior pontuação de cada rajada
- **Rolagem Infinita** - As fotos carregam conforme você rola
- **Rolagem Rápida (virtualizada)** - Renderização por janelamento de linhas: apenas as
  linhas próximas à viewport ficam no DOM, então rolar profundamente por dezenas de
  milhares de fotos permanece responsivo. Ativada por padrão; desative na seção
  Exibição da barra lateral de filtros se encontrar problemas de layout (o modo grade
  com detalhes exibidos sempre usa renderização completa, pois as alturas das linhas
  não são determinísticas nesse caso). Persistida no
  localStorage (`facet_virtual_scroll`).

### Fotos Similares

Clique no botão "Similar" em qualquer foto para escolher um modo de similaridade:

- **Visual** (padrão) — distância de hamming de pHash (70%) + similaridade de cosseno CLIP/SigLIP (30%). Recai para apenas CLIP quando nenhum pHash está disponível.
- **Cor** — Interseção de histograma (70%) + distância de saturação (10%) + distância de luminância (10%) + bônus monocromático (10%). Pré-filtra pela marcação monocromática e pela faixa de saturação.
- **Pessoa** — Encontra fotos que contêm a(s) mesma(s) pessoa(s). Usa `person_id` quando disponível (rápido), caso contrário recai para a similaridade de cosseno do embedding facial.

Use o **slider de limiar de similaridade** (0–90%) para controlar o quão rigorosa é a correspondência (não exibido no modo pessoa). O painel suporta rolagem infinita para grandes conjuntos de resultados.

### Chips de Filtro

Os filtros ativos são exibidos como chips removíveis com contagens no topo da galeria.

## Gerenciamento de Pessoas

> Navegar pelas pessoas está aberto a todos os visualizadores; renomear, mesclar, alterar avatares e atribuir rostos requer `[Edition]`.

### Filtro de Pessoa

O dropdown mostra as pessoas com miniaturas de rosto. Clique para filtrar a galeria.

### Galeria de Pessoa

Clique no nome da pessoa para ver todas as suas fotos em `/person/<id>`.

### Página de Gerenciar Pessoas

Acesse via botão no cabeçalho ou `/persons`:

| Ação | Como Fazer |
|--------|--------|
| **Mesclar** | Selecione a pessoa de origem, clique no alvo, confirme |
| **Excluir** | Clique no botão de excluir no cartão da pessoa |
| **Renomear** | Clique no nome da pessoa para editar inline |
| **Dividir** | Abra os rostos de uma pessoa, selecione um subconjunto, divida-os em uma nova pessoa |
| **Ocultar** | Oculta um cluster da lista de pessoas, dos filtros e das sugestões de mesclagem (reversível) |

## Disparar Varredura (Superadmin)

Quando `viewer.features.show_scan_button` é `true` e o usuário tem o papel `superadmin`, um botão **Scan photos to get started** aparece no estado de galeria vazia. Ele vem definido como **`false`** no `scoring_config.json` (opt-in de superadmin). O botão abre o diálogo do lançador de varredura (`ScanLauncherComponent`).

- Escolha um diretório na lista do lançador e inicie a varredura no app
- O lançador transmite o progresso ao vivo (SSE com fallback automático para polling) em uma `mat-progress-bar` acionada pelo campo estruturado `progress`, além de uma cauda de linhas de saída, e atualiza a galeria quando a varredura termina
- A varredura roda como um subprocesso em segundo plano (`facet.py`); apenas uma varredura por vez (trava global)
- As opções de diretório vêm de `get_all_scan_directories()`, que une os `directories` de cada usuário, os diretórios compartilhados, os alvos de `path_mapping` e a lista independente `viewer.scan_directories` — preencha esta última (por exemplo, `/data/photos`) para que instalações de usuário único / Docker tenham um alvo selecionável

Isso é útil quando o visualizador roda na mesma máquina que tem acesso à GPU para pontuação.

## Busca Semântica

Busca híbrida que combina a similaridade de embedding CLIP/SigLIP (70%) com a correspondência de texto BM25 do FTS5 em legendas e tags (30%). Digite uma consulta como "pôr do sol sobre montanhas" ou "criança brincando na neve" e o visualizador retorna as fotos correspondentes ordenadas pela pontuação combinada.

- Requer dados `clip_embedding` armazenados (computados durante a pontuação)
- Usa o sqlite-vec para busca vetorial KNN quando instalado, recai para NumPy em memória
- A busca de texto FTS5 nas legendas/tags geradas por IA fornece correspondência adicional por palavra-chave (execute `database.py --rebuild-fts` para habilitar)
- Usa o mesmo modelo de embedding do perfil de VRAM ativo (SigLIP 2 para 16gb/24gb, CLIP ViT-L-14 para legacy/8gb)
- `scope=text` restringe a consulta a correspondências literais do FTS5 em texto de OCR/legenda e ignora a busca por embedding
- Controlada por `viewer.features.show_semantic_search` (padrão: `true`)

## Álbuns

Organize fotos em álbuns nomeados. Acesse via a rota `/albums`.

### Álbuns Manuais

Crie álbuns e adicione fotos da galeria usando a multisseleção. Os álbuns suportam:
- Nome e descrição
- Foto de capa personalizada
- Ordenação personalizada
- Navegue pelo conteúdo do álbum em `/album/:albumId`

### Álbuns Inteligentes

Salve uma combinação de filtros (câmera, tag, pessoa, faixa de datas, limiares de pontuação, etc.) como um álbum inteligente. Os álbuns inteligentes se atualizam dinamicamente à medida que novas fotos correspondem aos critérios de filtro salvos. A combinação de filtros é armazenada como JSON em `smart_filter_json`.

API: veja a seção [Endpoints da API](#api-endpoints) abaixo.

Controlados por `viewer.features.show_albums` (padrão: `true`).

### Compartilhamento de Fotos

Compartilhe álbuns com usuários externos via links com token. Nenhuma autenticação é necessária para visualizar álbuns compartilhados.

| Ação | Como Fazer |
|--------|--------|
| **Compartilhar** | Abra o álbum, clique no botão "Share" para gerar um link compartilhável |
| **Revogar** | Clique em "Unshare" para invalidar o token de compartilhamento |
| **Visualizar** | Os destinatários abrem o link para navegar pelo álbum compartilhado em `/shared/album/:id` |

API: veja a seção [Endpoints da API](#api-endpoints) abaixo.

## Crítica por IA

Desmembra as pontuações de uma foto em pontos fortes, pontos fracos e sugestões.

### Crítica Baseada em Regras

Disponível em todos os perfis de VRAM. Analisa as métricas armazenadas (estética, composição, nitidez, qualidade do rosto, etc.) e gera uma explicação estruturada da pontuação.

### Crítica por VLM `[GPU]` `[16gb/24gb]`

Usa o VLM configurado (Qwen3.5-2B ou Qwen3.5-4B) para uma crítica sensível ao contexto. Requer o perfil de VRAM 16gb ou 24gb e `viewer.features.show_vlm_critique: true`.

API: veja a seção [Endpoints da API](#api-endpoints) abaixo.

Controlada por `viewer.features.show_critique` (padrão: `true`) e `viewer.features.show_vlm_critique` (padrão: `true`).

**Sobreposição visual "por que esta pontuação".** Quando `viewer.features.show_saliency_overlay` é `true` (padrão), o diálogo de crítica ganha uma alternância **Show overlay**: ele desenha o mapa de saliência do BiRefNet como um mapa de calor translúcido sobre a foto (recomputado sob demanda a partir da miniatura armazenada — `GET /api/saliency_overlay`), além de caixas suaves por rosto e marcadores de olhos reconstruídos a partir de pontos de referência armazenados (`GET /api/photo/face_markers`). As caixas ficam verdes quando os olhos estão abertos, âmbar em uma piscada. O mapa de calor é ilustrativo (resolução de miniatura), não exato em nível de pixel; a alternância se oculta em perfis onde nenhuma máscara de saliência pode ser produzida.

## Legendagem por IA `[GPU]` `[16gb/24gb]` `[Edition]`

Obtenha uma legenda em linguagem natural gerada por IA para qualquer foto. As legendas são geradas na primeira solicitação e armazenadas em cache na coluna `caption` do banco de dados. As legendas podem ser editadas manualmente no modo de edição através da página de detalhes da foto. (A *tradução* da legenda roda na CPU — veja abaixo.)

API: veja a seção [Endpoints da API](#api-endpoints) abaixo.

Também disponível via CLI para geração e tradução em lote:

```bash
python facet.py --generate-captions      # Generate captions for all uncaptioned photos
python facet.py --translate-captions     # Translate captions to configured target language
```

A tradução de legendas usa o MarianMT (CPU, nenhuma GPU necessária). Configure o idioma de destino no `scoring_config.json` em `translation.target_language` (padrão: `"fr"`). Idiomas suportados: francês, alemão, espanhol, italiano.

Controlada por `viewer.features.show_captions` (padrão: `true`). Requer o perfil de VRAM 16gb ou 24gb para legendagem baseada em VLM.

## Memórias ("Neste Dia")

Navegue por fotos tiradas na mesma data do calendário em anos anteriores. Um diálogo de memórias mostra uma retrospectiva ano a ano das fotos correspondentes.

API: veja a seção [Endpoints da API](#api-endpoints) abaixo.

Controlada por `viewer.features.show_memories` (padrão: `true`).

## Fluxos de trabalho comuns

- **Triar uma viagem** — abra Cápsulas → procure a cápsula `journey` gerada automaticamente para as datas da viagem. Cada cápsula oferece uma ação de Salvar-como-Álbum.
- **Percorrer uma revisão dia a dia** — abra a Linha do Tempo → ordene por agregada → avance pelo ano. As melhores fotos sobem primeiro quando você habilitou `hide_bursts` e `hide_duplicates` (padrões: ativados).
- **Mostrar o que está oculto** — a galeria oculta piscadas / rajadas não-líderes / duplicatas não-líderes por padrão. Quando pelo menos um desses filtros está ativo e excluiria linhas, um banner "N photos hidden by current filters · Show all" aparece acima da grade.

## Visão Linha do Tempo

Navegador cronológico de fotos com navegação baseada em datas. Role pelas fotos organizadas por data com uma barra lateral mostrando os anos e meses disponíveis.

API: veja a seção [Endpoints da API](#api-endpoints) abaixo.

Acesse via a rota `/timeline`. Controlada por `viewer.features.show_timeline` (padrão: `true`).

## Visão Mapa

Visualize fotos em um mapa interativo com base nas coordenadas GPS extraídas dos dados EXIF. Usa o Leaflet para renderização do mapa com agrupamento em diferentes níveis de zoom.

### Configuração Inicial

Extraia as coordenadas GPS de fotos existentes:

```bash
python facet.py --extract-gps    # Extract GPS lat/lng from EXIF into database
```

As coordenadas GPS também são extraídas automaticamente durante a pontuação de novas fotos.

API: veja a seção [Endpoints da API](#api-endpoints) abaixo.

Acesse via a rota `/map`. Controlada por `viewer.features.show_map` (padrão: `true`).

## Cápsulas

Diaporamas (apresentações de slides) de fotos curadas e agrupadas por tema. Acesse via a rota `/capsules`.

### Tipos de Cápsula

As cápsulas são geradas automaticamente a partir da sua biblioteca usando múltiplos algoritmos:

- **Journey** — viagens detectadas via agrupamento por GPS, com nomes de destino geocodificados reversamente ("Journey to Rome — March 2025")
- **Moments with [Person]** — as melhores fotos de cada pessoa reconhecida
- **Seasonal Palette** — fotos agrupadas por estação + ano
- **Golden Collection** — top 1% por pontuação agregada
- **Color Story** — grupos visualmente similares via agrupamento de embedding CLIP
- **This Week, Years Ago** — "Neste Dia" estendido por ±3 dias
- **Location** — clusters de fotos geotagueadas com nomes de lugares
- **Favorites** — fotos favoritadas agrupadas por ano e estação
- **Baseadas em dimensão** — geradas automaticamente a partir de câmera, lente, categoria, padrão de composição, faixa de distância focal, hora do dia, classificação por estrelas e combinações entre dimensões

### Apresentação de Slides

Clique em qualquer cartão de cápsula para iniciar uma apresentação de slides. Recursos:
- **Transições temáticas** — slide (journeys), zoom (retratos), kenburns (golden/seasonal), crossfade (padrão)
- **Encadeamento automático** — quando uma cápsula termina, um cartão de transição mostra a próxima cápsula antes de continuar
- **Embaralhar & retomar** — as fotos são embaralhadas para variedade; a posição de retomada é rastreada por cápsula
- **Agrupamento adaptativo** — fotos em retrato são agrupadas lado a lado com base na proporção da viewport
- **Salvar como álbum** — salve qualquer cápsula como um álbum permanente

### Atualização

As cápsulas rotacionam em um cronograma configurável (padrão: 24 horas). As fotos de capa e as cápsulas de descoberta com seed se alinham ao mesmo período de rotação. O botão "Regenerate" no cabeçalho força uma atualização imediata.

### Geocodificação Reversa

As cápsulas de localização e viagem mostram nomes de lugares (por exemplo, "Paris, France") em vez de coordenadas. Isso usa geocodificação offline via o pacote `reverse_geocoder` — nenhuma chamada de API é necessária. Os resultados são armazenados em cache no banco de dados.

Instalação: `pip install reverse_geocoder`

API: veja a seção [Endpoints da API](#api-endpoints) abaixo.

### Configuração

Veja [Configuração — Cápsulas](CONFIGURATION.md#capsules) para todas as configurações.

## Visão Pastas

Navegue pela sua biblioteca de fotos por estrutura de diretórios. Acesse via a rota `/folders`.

- Navegação por breadcrumb para subir na árvore de diretórios
- Cada pasta mostra uma foto de capa (a imagem com maior pontuação naquele diretório)
- Clique em uma pasta para entrar nela, ou clique em uma foto para abri-la na galeria
- Respeita a visibilidade de diretórios multiusuário no modo multiusuário

## Diálogo de Filtro GPS

Filtre fotos por localização geográfica usando um seletor de mapa interativo:

- Clique no botão de filtro de localização para abrir o diálogo do mapa
- Clique ou arraste no mapa para definir um ponto central
- Ajuste o slider de raio para controlar a área de busca
- As fotos dentro do raio selecionado são filtradas na galeria
- Requer coordenadas GPS (execute `--extract-gps` se as fotos tiverem dados de GPS EXIF)

## Sugestões de Mesclagem

Encontre clusters de pessoas que podem ser o mesmo indivíduo. Acesse via `/merge-suggestions` ou na página de Gerenciar Pessoas.

- **Slider de limiar de similaridade** — o quão similares duas pessoas devem parecer para serem sugeridas (menor = mais sugestões, maior = menos)
- **Mesclar** — aceite uma sugestão para mesclar as duas pessoas
- **Mesclagem em lote** — selecione várias sugestões e mescle-as de uma vez
- As sugestões descartadas são lembradas e não propostas novamente
- Também disponível via CLI: `python facet.py --suggest-person-merges`

## Exportação para Editores

Escreva suas avaliações, favoritos e rejeições no disco como sidecars XMP, para que editores externos (darktable, Lightroom) os reconheçam. Requer o modo de edição.

- **A partir da galeria** — selecione fotos, então **Ações → Exportar** escreve um sidecar ao lado de cada arquivo.
- **A partir de um álbum** ("cesta") — exporte o álbum inteiro como sidecars, ou copie/crie symlink dos arquivos para um diretório de destino.
- **Escrever metadados no arquivo** — a ação "Write metadata to file" nos detalhes da foto incorpora a classificação/palavras-chave diretamente no arquivo original (JPEG/HEIC/TIFF/PNG/DNG via exiftool) além de escrever o sidecar, para que todo o ecossistema de fotos os enxergue. Os originais RAW proprietários nunca são modificados. Controlada por `viewer.features.show_embed_metadata` (padrão: `true`).

API: veja a seção [Endpoints da API](#api-endpoints) abaixo.

## Triagem

A página de triagem (`/culling`, modo de edição) agrupa fotos quase idênticas para que você possa manter a melhor de cada e rejeitar o restante. Duas fontes de grupos:

- **Rajada** — fotos tiradas em curto intervalo de tempo (da detecção de rajadas).
- **Similar** — fotos que se parecem independentemente de quando foram tiradas, agrupadas pela similaridade de embedding CLIP/SigLIP. Um slider de limiar controla o quão rigoroso é o agrupamento.

Para cada grupo, escolha a(s) que serão mantidas; confirmar rejeita o restante. As confirmações são adiadas e podem ser desfeitas (veja [Desfazer](#undo)).

### Selos por Rosto

Na lightbox de triagem de rajada/similar, cada rosto detectado carrega seus próprios selos — olhos abertos/fechados, expressão ruim e confiança de detecção — em vez de uma única marcação de piscada em nível de foto. Isso torna fotos de grupo mais fáceis de triar: você pode ver de relance qual rosto tem olhos fechados ou uma expressão fraca. Os selos são buscados para um grupo inteiro em uma única chamada em lote (`POST /api/culling-group/faces`).

**Comparação sincronizada (2-up / 4-up).** O cabeçalho da lightbox tem botões Single / Compare 2 / Compare 4. No modo de comparação, os painéis compartilham uma única transformação de pan/zoom, então o zoom da roda de rolagem ou o pan por arrasto em qualquer painel move todos para o recorte idêntico — a forma de escolher o quadro mais nítido de uma rajada inspecionando os pixels de verdade. O duplo clique alterna entre ajustar ↔ zoom; passada a escala de ajuste, cada painel troca preguiçosamente sua miniatura de 1920px pela fonte `/image` em resolução total para que a inspeção fique nítida. Nenhuma mudança no backend — ambas as rotas de imagem já existem. (O pinch por toque ainda não está conectado; use a roda no desktop.)

API: veja a seção [Endpoints da API](#api-endpoints) abaixo.

## Visão Cenas

Agrupe fotos líderes de rajada em "cenas" cronológicas para que você possa triar uma sessão inteira na ordem da história. As fotos são divididas em cenas por intervalos de tempo de captura (uma nova cena começa quando passam mais de `scenes.gap_minutes` entre fotos consecutivas, ampliado de forma adaptativa em sessões esparsas), e qualquer sequência excessivamente longa é subdividida para que um evento fotografado continuamente nunca colapse em uma única cena gigante. Cada cena tem um botão primário **Cull this scene** que abre o câmara escura de triagem completa com escopo apenas para aquela cena (detecção de rajadas, marcações de piscada, pontuações de qualidade, close-ups de rosto, lupa), além de uma faixa de **Quick reject**. Acesse via a rota `/scenes` (ícone de navegação "theaters"); também acessível por álbum a partir da grade de Álbuns.

- Cada cena mostra suas fotos líderes na ordem de captura
- Toque nas fotos para marcá-las para triagem; confirmar as rejeita e alimenta o ranqueador pessoal
- Cenas menores que `scenes.min_size` são omitidas; no máximo `scenes.max_photos` fotos são carregadas

API: veja a seção [Endpoints da API](#api-endpoints) abaixo.

Controlada por `viewer.features.show_scenes` (padrão: `true`). Veja [Configuração — Cenas](CONFIGURATION.md#scenes) para `gap_minutes`, `min_size`, `max_photos`, `max_scene_size`, `adaptive` e `adaptive_k`.

## Modo de Comparação por Pares

Ranqueie fotos julgando-as duas de cada vez. Os votos acumulados alimentam o ajuste de pesos. Acesse via a rota `/compare` (botão Compare no cabeçalho). Requer uma `edition_password` não vazia (usuário único) ou o papel `admin`/`superadmin` (multiusuário).

A página tem quatro abas:

### Aba Comparação A/B

Pares de fotos lado a lado. Escolha um vencedor, marque um empate ou pule. Uma barra de progresso rastreia os votos até 50, com contagens correntes de vitórias-A/vitórias-B/empate. Um filtro de categoria define o escopo da sessão, e um dropdown de estratégia de seleção controla como os pares são escolhidos.

| Estratégia | Descrição |
|----------|-------------|
| `uncertainty` | Fotos com pontuações similares (mais informativas) |
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

### Aba Sugestões de Peso

Mostra os pesos aprendidos das comparações em relação aos pesos atuais, lado a lado, com a acurácia do modelo antes/depois. As 10 melhores fotos atuais e as 10 melhores previstas após o recálculo são pré-visualizadas em colunas adjacentes. **Aplicar** escreve os pesos sugeridos; **Recalcular** repontua a categoria para aplicá-los (ambos requerem o modo de edição).

### Aba Pesos

Editor manual de pesos: um slider por métrica para a categoria selecionada com uma pré-visualização de pontuação ao vivo. **Salvar** escreve no `scoring_config.json` (com um backup); **Recalcular Pontuações** os aplica; **Redefinir** recarrega os pesos armazenados.

### Aba Snapshots

Salve os pesos atuais como um snapshot nomeado e restaure qualquer snapshot anterior.

### Substituição de Categoria

Para reatribuir a categoria de uma foto a partir da visão de comparação: edite o selo de categoria, selecione uma categoria de destino, execute "Analyze Filter Conflicts" para ver quais filtros a excluem, então aplique a substituição.

## Estatísticas EXIF

A página de Estatísticas (`/stats`) fornece análises em 5 abas. Use os seletores de **categoria** e **faixa de datas** na barra de ferramentas para filtrar todos os gráficos para um subconjunto específico da sua biblioteca.

### Abas

| Aba | Descrição |
|-----|-------------|
| **Equipamento** | Corpos de câmera, lentes e combos (top 20 de cada) |
| **Configurações de Captura** | Distribuições de ISO, abertura, distância focal, velocidade do obturador |
| **Linha do Tempo** | Fotos ao longo do tempo |
| **Categorias** | Análises de categoria, gerenciamento de pesos e correlações de pontuação |
| **Correlações** | Gráficos personalizados de correlação de métricas X/Y com agrupamento |

### Aba Categorias

Quatro subabas:

| Subaba | Descrição |
|---------|-------------|
| **Detalhamento** | Contagens de fotos por categoria, pontuações médias, histogramas de distribuição de pontuação |
| **Pesos** | Comparação por gráfico de radar (até 5 categorias), mapa de calor de pesos e editor de pesos (modo de edição) |
| **Correlações** | Mapa de calor de correlação de Pearson mostrando como cada dimensão influencia a agregada, visão de detalhe ao clicar |
| **Sobreposição** | Análise de sobreposição de filtros mostrando quais categorias compartilham fotos correspondentes |

Cada gráfico tem um botão de ajuda `?` alternável explicando como lê-lo. Uma alternância de ajuda global na barra de subabas mostra explicações para todas as subabas.

### Editor de Pesos (Modo de Edição)

Disponível na subaba Pesos quando o modo de edição está ativo:

1. Selecione uma categoria no dropdown
2. Ajuste os sliders de peso (um por métrica, devem somar 100%)
3. Use "Normalize to 100" para auto-balancear
4. Expanda a seção recolhível de Modificadores para ajustar bônus/penalidades
5. A **Pré-visualização de Distribuição de Pontuação** mostra um histograma ao vivo de antes/depois conforme você move os sliders
6. Clique em **Salvar** para atualizar o `scoring_config.json` (cria um backup com timestamp)
7. Clique em **Recalcular Pontuações** (aparece após salvar) para aplicar os novos pesos a todas as fotos daquela categoria

Todas as estatísticas são sensíveis ao usuário no modo multiusuário — cada usuário vê análises apenas para suas fotos visíveis.

## Atalhos de Teclado (Galeria)

| Tecla | Ação |
|-----|--------|
| `←` `→` `↑` `↓` | Mover o foco do teclado entre os cartões de foto (colunas da grade e linhas do mosaico) |
| `Enter` | Abrir a foto em foco |
| `Space` | Selecionar / desmarcar a foto em foco |
| `Ctrl+A` | Selecionar todas as fotos carregadas |
| `Escape` | Limpar a seleção / fechar a gaveta de filtros |
| `Shift+Click` | Selecionar o intervalo de fotos entre a última selecionada e a clicada |
| `Double-click` | Abrir foto |
| `?` | Mostrar a referência de atalhos de teclado (funciona em todas as páginas) |

## Desfazer

Operações em lote de favoritar/rejeitar/avaliar e confirmações de triagem mostram uma
snackbar com uma ação **Desfazer** por ~7 segundos. As operações de marcação em lote são
confirmadas imediatamente e desfeitas via chamadas de API inversas (limitadas a 500 fotos);
as confirmações de triagem são adiadas — o grupo desaparece instantaneamente, mas a chamada
de API só é disparada quando a janela de desfazer expira.

## Progressive Web App

O visualizador inclui um manifesto de web app e um service worker do Angular (apenas em
builds de produção): ele pode ser instalado na tela inicial, o app shell carrega
offline, e até 1000 miniaturas são armazenadas em cache LRU por 7 dias. As respostas da API
nunca são armazenadas em cache (exceto os pacotes de i18n com uma estratégia de atualização), e o logout
limpa o cache de miniaturas para que configurações multiusuário que compartilham um navegador não vazem
pré-visualizações entre contas. Uma snackbar oferece um recarregamento quando uma nova versão foi
implantada.

## Mobile

Em telas pequenas, a barra de seleção em lote se reduz à contagem da seleção,
limpar, selecionar tudo e um único botão **Ações** que abre uma
bottom sheet amigável ao toque com todas as operações em lote (favoritar, rejeitar, avaliar, álbuns, copiar,
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

### Limites de Dropdown

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

Defina `min_photos_for_person` mais alto para ocultar pessoas com poucas fotos do dropdown de filtro.

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

### Pesos de Top Picks

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

Execute estes para um melhor desempenho:

```bash
python database.py --migrate-tags    # 10-50x faster tag queries
python database.py --refresh-stats   # Precompute aggregations
python database.py --optimize        # Defragment database
```

### SQLite Assíncrono (opt-in, para caminhos de leitura de alta concorrência)

`api.database.get_async_db()` é um gerenciador de contexto assíncrono apoiado por aiosqlite,
paralelo a `get_db()`. Os endpoints são atualmente síncronos (o FastAPI os delega
a um pool de threads de trabalho, o que é adequado em concorrência típica). Para caminhos
de leitura de alta concorrência (>5 usuários simultâneos), endpoints individuais podem ser
migrados assim:

1. Mude `def foo(...)` para `async def foo(...)`.
2. Substitua `with get_db() as conn:` por `async with get_async_db() as conn:`.
3. Use `await` em cada `.execute()` e `.fetchone()` / `.fetchall()`.
4. Mantenha os caminhos de escrita síncronos — o aiosqlite serializa as escritas de qualquer forma, e o pool de
   conexões do caminho síncrono já as gerencia.

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

Os dropdowns de filtro carregam sob demanda via API:
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
| `GET /api/similar_photos/{path}` | Fotos similares (modos: `visual`, `color`, `person`) |
| `GET /api/search?q=&limit=&threshold=&scope=` | Busca semântica de texto para imagem (`scope=text` = apenas texto de OCR/legenda) |
| `GET /api/critique?path=&mode=` | Crítica por IA (baseada em regras ou VLM) |
| `GET /api/ranker/status` | Status do ranqueador pessoal para a ordenação "My Taste" (% de cobertura aprendida, acurácia em dados retidos) |
| `GET /api/config` | Configuração do visualizador |

### Autenticação

| Endpoint | Descrição |
|----------|-------------|
| `POST /api/auth/login` | Autenticar e receber token |
| `POST /api/auth/edition/login` | Desbloquear o modo de edição |
| `POST /api/auth/edition/logout` | Bloquear o modo de edição (perder privilégios, permanecer autenticado) |
| `GET /api/auth/status` | Verificar o status de autenticação |

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
| `GET /api/filter_options/metric_ranges` | Mín/máx observados e histograma por métrica numérica (para os limites do slider) |

### Operações em Lote

| Endpoint | Descrição |
|----------|-------------|
| `POST /api/photos/batch_favorite` | Marcar múltiplas fotos como favoritas |
| `POST /api/photos/batch_reject` | Marcar múltiplas fotos como rejeitadas |
| `POST /api/photos/batch_rating` | Definir classificação por estrelas para múltiplas fotos |

### Pessoas

| Endpoint | Descrição |
|----------|-------------|
| `GET /api/persons` | Listar todas as pessoas |
| `POST /api/persons` | Criar uma nova pessoa, opcionalmente anexando rostos (restrito ao modo de edição). Corpo: `{name, face_ids}` |
| `GET /api/persons/needs_naming?min_faces=N` | Listar pessoas auto-agrupadas sem nome com `face_count >= N` (padrão de `viewer.persons.needs_naming_min_faces`) |
| `POST /api/persons/{id}/rename` | Renomear uma pessoa |
| `POST /api/persons/{id}/assign_faces` | Anexar rostos em massa a uma pessoa; pessoas antigas vazias são auto-excluídas (restrito ao modo de edição). Corpo: `{face_ids}` |
| `POST /api/persons/{id}/split` | Dividir um subconjunto dos rostos de uma pessoa em uma nova pessoa (restrito ao modo de edição). Corpo: `{face_ids, name}` |
| `POST /api/persons/{id}/hide` | Ocultar uma pessoa da lista, dos filtros e das sugestões de mesclagem |
| `POST /api/persons/{id}/unhide` | Reexibir uma pessoa previamente ocultada |
| `POST /api/persons/merge` | Mesclar duas pessoas (corpo JSON) |
| `POST /api/persons/merge/{source_id}/{target_id}` | Mesclar pessoa de origem no alvo |
| `POST /api/persons/merge_batch` | Mesclar múltiplas pessoas de uma vez |
| `POST /api/persons/merge_suggestions/reject` | Descartar uma sugestão de mesclagem para que não seja proposta novamente |
| `POST /api/persons/{id}/delete` | Excluir uma pessoa |
| `POST /api/persons/delete_batch` | Excluir múltiplas pessoas de uma vez |

### Álbuns

| Endpoint | Descrição |
|----------|-------------|
| `GET /api/albums` | Listar todos os álbuns |
| `POST /api/albums` | Criar álbum |
| `GET /api/albums/{id}` | Obter detalhes do álbum |
| `PUT /api/albums/{id}` | Atualizar álbum |
| `DELETE /api/albums/{id}` | Excluir álbum |
| `GET /api/albums/{id}/photos` | Listar fotos no álbum (paginado) |
| `POST /api/albums/{id}/photos` | Adicionar fotos ao álbum |
| `DELETE /api/albums/{id}/photos` | Remover fotos do álbum |
| `POST /api/albums/{id}/share` | Gerar token de compartilhamento |
| `DELETE /api/albums/{id}/share` | Revogar token de compartilhamento |
| `GET /api/shared/album/{id}?token=` | Visualizar álbum compartilhado (sem autenticação) |

### Memórias, Linha do Tempo, Mapa & Legendas

| Endpoint | Descrição |
|----------|-------------|
| `GET /api/memories?date=` | Fotos tiradas nesta data em anos anteriores |
| `GET /api/memories/check` | Verificar se existem memórias para uma data |
| `GET /api/caption?path=` | Obter ou gerar legenda por IA |
| `PUT /api/caption` | Atualizar a legenda da foto (modo de edição) |
| `GET /api/timeline?cursor=&limit=&direction=` | Fotos paginadas da linha do tempo |
| `GET /api/timeline/dates?year=&month=` | Datas disponíveis para navegação |
| `GET /api/timeline/years` | Anos disponíveis com contagens de fotos |
| `GET /api/timeline/months` | Meses disponíveis para um ano |
| `GET /api/photos/map?bounds=&zoom=&limit=` | Fotos geotagueadas dentro dos limites |
| `GET /api/photos/map/count` | Contagem de fotos geotagueadas |

### Cápsulas

| Endpoint | Descrição |
|----------|-------------|
| `GET /api/capsules` | Lista paginada de cápsulas (em cache) |
| `GET /api/capsules/{id}/photos` | Fotos de uma cápsula específica |
| `POST /api/capsules/{id}/save-album` | Salvar cápsula como álbum (modo de edição) |

### Estatísticas

| Endpoint | Descrição |
|----------|-------------|
| `GET /api/stats/overview` | Resumo geral das estatísticas de pontuação |
| `GET /api/stats/score_distribution` | Dados do histograma de distribuição de pontuação |
| `GET /api/stats/top_cameras` | Principais câmeras por contagem de fotos |
| `GET /api/stats/categories` | Contagens e médias por categoria |
| `GET /api/stats/gear` | Contagens de câmera/lente/combo |
| `GET /api/stats/settings` | Distribuições de configurações de captura |
| `GET /api/stats/timeline` | Dados da linha do tempo |
| `GET /api/stats/correlations` | Correlações de métricas personalizadas |
| `GET /api/stats/categories/breakdown` | Contagens de fotos por categoria e distribuições de pontuação |
| `GET /api/stats/categories/weights` | Pesos e modificadores de categoria da configuração |
| `GET /api/stats/categories/correlations` | Correlação de Pearson r por dimensão por categoria |
| `GET /api/stats/categories/metrics?category=X` | Valores brutos de métricas para pré-visualização no cliente |
| `GET /api/stats/categories/overlap` | Análise de sobreposição de filtros entre categorias |
| `POST /api/stats/categories/update` | Atualizar pesos/modificadores de categoria (modo de edição) |
| `POST /api/stats/categories/recompute` | Recalcular pontuações para uma categoria (modo de edição) |

### Modo de Comparação

| Endpoint | Descrição |
|----------|-------------|
| `GET /api/comparison/next_pair` | Obter o próximo par de fotos para comparação |
| `POST /api/comparison/submit` | Enviar resultado da comparação |
| `POST /api/comparison/reset` | Redefinir dados de comparação |
| `GET /api/comparison/stats` | Estatísticas da sessão de comparação |
| `GET /api/comparison/history` | Listar comparações anteriores |
| `POST /api/comparison/edit` | Editar um resultado de comparação |
| `POST /api/comparison/delete` | Excluir uma comparação |
| `GET /api/comparison/coverage` | Cobertura de categoria das comparações |
| `GET /api/comparison/confidence` | Métricas de confiança para pontuações aprendidas |
| `GET /api/comparison/photo_metrics` | Métricas brutas das fotos |
| `GET /api/comparison/category_weights` | Pesos/filtros de categoria |
| `GET /api/comparison/learned_weights` | Pesos sugeridos a partir das comparações |
| `POST /api/comparison/preview_score` | Pré-visualização com pesos personalizados |
| `POST /api/comparison/suggest_filters` | Analisar conflitos de filtro |
| `POST /api/comparison/override_category` | Substituir a categoria da foto |
| `POST /api/recalculate` | Recalcular pontuações com os pesos atuais |

### Triagem de Rajadas

| Endpoint | Descrição |
|----------|-------------|
| `GET /api/burst-groups` | Listar grupos de rajada para triagem |
| `POST /api/burst-groups/select` | Selecionar as mantidas de um grupo de rajada |
| `GET /api/similar-groups?threshold=&page=&per_page=` | Grupos de fotos visualmente similares |
| `POST /api/similar-groups/select` | Selecionar as mantidas de um grupo similar |
| `GET /api/culling-groups?exclude_rejected=true&similarity_threshold=&page=&per_page=` | Grupos combinados de rajada e similares. `exclude_rejected` (padrão `true`) oculta fotos com `is_rejected=1`; grupos com menos de 2 fotos restantes são descartados |
| `POST /api/culling-groups/confirm` | Confirmar seleções de triagem |
| `POST /api/culling-group/faces` | Selos por rosto (olhos abertos/fechados, expressão, confiança) para um grupo, em um único lote |
| `GET /api/scenes` | Cenas cronológicas de fotos líderes de rajada |
| `POST /api/scenes/confirm` | Confirmar seleções de triagem de cena |

### Varredura

| Endpoint | Descrição |
|----------|-------------|
| `POST /api/scan/start` | `[Superadmin]` Iniciar uma varredura de pontuação |
| `GET /api/scan/status` | Verificar o progresso da varredura (`progress` estruturado: `{phase, current, total, eta_seconds}`) |
| `GET /api/scan/stream?token=<jwt>` | `[Superadmin]` Progresso em tempo real via Server-Sent Events; o token é passado como parâmetro de consulta (a API `EventSource` não pode definir cabeçalhos), com fallback automático para polling de `/status` |
| `GET /api/scan/directories` | Listar diretórios de varredura configurados |

### Gerenciamento de Rostos

| Endpoint | Descrição |
|----------|-------------|
| `GET /api/person/{id}/faces` | Listar rostos de uma pessoa |
| `POST /api/person/{id}/avatar` | Definir o rosto de avatar da pessoa |
| `GET /api/photo/faces` | Listar rostos detectados em uma foto |
| `POST /api/face/{id}/assign` | Atribuir um rosto a uma pessoa |
| `POST /api/photo/assign_all_faces` | Atribuir todos os rostos de uma foto a uma pessoa |
| `POST /api/photo/unassign_person` | Desassociar uma pessoa de uma foto |

### Ações de Foto

| Endpoint | Descrição |
|----------|-------------|
| `POST /api/photo/set_rating` | Definir classificação por estrelas para uma foto |
| `POST /api/photo/toggle_favorite` | Alternar o status de favorito |
| `POST /api/photo/toggle_rejected` | Alternar o status de rejeitado |

### Gerenciamento de Configuração

| Endpoint | Descrição |
|----------|-------------|
| `POST /api/config/update_weights` | Atualizar pesos de pontuação |
| `GET /api/config/weight_snapshots` | Listar snapshots de peso salvos |
| `POST /api/config/save_snapshot` | Salvar os pesos atuais como snapshot |
| `POST /api/config/restore_weights` | Restaurar pesos de um snapshot |

### Sugestões de Mesclagem

| Endpoint | Descrição |
|----------|-------------|
| `GET /api/merge_suggestions` | Mesclagens de pessoas sugeridas com base na similaridade facial |

### Pastas

| Endpoint | Descrição |
|----------|-------------|
| `GET /api/folders` | Listar a estrutura de pastas de fotos |

### Download

| Endpoint | Descrição |
|----------|-------------|
| `GET /api/download/options` | Tipos de download disponíveis para uma foto (`path`, `is_shared` opcional) |
| `GET /api/download` | Baixar uma foto (`path`, `type=original\|darktable\|raw`, `profile` opcional) |

**Tipos de download:**

- `original` — Serve o arquivo como está (JPG/HEIF) ou convertido por rawpy para JPEG (arquivos RAW).
- `darktable` — Converte o RAW companheiro com um perfil darktable nomeado (requer o parâmetro `profile`). Recai para o original se não existir um RAW companheiro.
- `raw` — Serve o arquivo RAW companheiro como está (não disponível em álbuns compartilhados).

O endpoint `/api/download/options` detecta arquivos RAW companheiros automaticamente e retorna as opções disponíveis, incluindo os perfis darktable configurados. O visualizador usa isso para preencher um menu de download por foto.

### Exportação para Editores

| Endpoint | Descrição |
|----------|-------------|
| `POST /api/photo/export_xmp` | `[Edition]` Escrever um sidecar XMP |
| `POST /api/export/sidecars` | `[Edition]` Escrever sidecars para caminhos explícitos ou um conjunto de filtros |
| `POST /api/photo/embed_metadata` | `[Edition]` Incorporar metadados no arquivo original (JPEG/HEIC/TIFF/PNG/DNG; RAW nunca modificado) e escrever o sidecar |
| `POST /api/albums/{id}/export` | `[Edition]` Exportação de álbum como sidecars, cópia ou symlink |

### Plugins

| Endpoint | Descrição |
|----------|-------------|
| `GET /api/plugins` | Listar plugins configurados |
| `POST /api/plugins/test-webhook` | Testar um plugin de webhook |

### Saúde

| Endpoint | Descrição |
|----------|-------------|
| `GET /health` | Verificação de saúde do servidor |
| `GET /ready` | Verificação de prontidão do servidor |
| `GET /metrics` | Métricas em formato Prometheus: contagens de fotos, cobertura de embeddings, tamanho do DB, memória do processo |

### Internacionalização

| Endpoint | Descrição |
|----------|-------------|
| `GET /api/i18n/languages` | Listar idiomas disponíveis |
| `GET /api/i18n/{lang}` | Obter traduções para um idioma |

### Opções de Filtro (adicionais)

| Endpoint | Descrição |
|----------|-------------|
| `GET /api/filter_options/location_name?lat=&lng=` | Geocodificar reversamente coordenadas para um nome de lugar |

## Solução de Problemas

| Problema | Solução |
|-------|----------|
| Carregamento lento da página | Execute `--migrate-tags` e `--optimize` |
| Filtros não aparecem | Verifique `--stats-info`, execute `--refresh-stats` |
| Filtro de pessoa vazio | Execute `--cluster-faces-incremental` |
| Botão Compare ausente | Defina uma `edition_password` não vazia (usuário único) ou use o papel `admin`/`superadmin` (multiusuário) |
| Senha não funciona | Verifique `viewer.password` (usuário único) ou verifique o hash da senha (multiusuário) |
| Usuário não consegue ver fotos | Verifique `directories` na configuração do usuário e `shared_directories` |
| Botão de varredura ausente | Requer o papel `superadmin` e `viewer.features.show_scan_button: true` |
| Busca não retorna resultados | Certifique-se de que as fotos têm dados `clip_embedding` (execute a pontuação primeiro) |
| Crítica por VLM indisponível | Requer o perfil de VRAM 16gb/24gb e `viewer.features.show_vlm_critique: true` |
| Mapa não mostra fotos | Execute `--extract-gps` para preencher as colunas GPS, certifique-se de que as fotos têm dados de GPS EXIF |
| Legendas não são geradas | Requer o perfil de VRAM 16gb/24gb para legendagem por VLM |
| Linha do tempo vazia | Certifique-se de que as fotos têm valores de `date_taken` |
| Porta 5000 em uso | Execute `python viewer.py --port 5001` (ou defina `PORT=5001`). No macOS, o AirPlay Receiver do ControlCenter ocupa a porta 5000 por padrão — escolha outra porta ou desative o AirPlay Receiver em Configurações do Sistema → Geral → AirDrop & Handoff. |
