# Visualizador Web

> 🌐 [English](../VIEWER.md) · [Français](../fr/VIEWER.md) · [Deutsch](../de/VIEWER.md) · [Italiano](../it/VIEWER.md) · [Español](../es/VIEWER.md) · **Português** · [简体中文](../zh/VIEWER.md)

O visualizador é uma aplicação web em FastAPI + Angular para navegar, filtrar, fazer a triagem e gerenciar suas fotos.

## Conteúdo

- [Iniciando o Visualizador](#iniciando-o-visualizador) · [Autenticação](#autenticação) · [Opções de Filtragem](#opções-de-filtragem) · [Ordenação](#ordenação) · [Decisões de revisão](#decisões-de-revisão) · [Recursos da Galeria](#recursos-da-galeria)
- [Panorâmicas e brackets de exposição](#panorâmicas-e-brackets-de-exposição)
- [Gerenciamento de Pessoas](#gerenciamento-de-pessoas) · [Disparo de Varredura](#disparo-de-varredura) · [Busca Semântica](#busca-semântica) · [Álbuns](#álbuns)
- [Crítica por IA](#crítica-por-ia) · [Legendagem por IA](#legendagem-por-ia-gpu-16gb24gb-edition) · [Memórias ("Neste Dia")](#memórias-neste-dia) · [Visão de Linha do Tempo](#visão-de-linha-do-tempo) · [Visão de Mapa](#visão-de-mapa) · [Cápsulas](#cápsulas)
- [Visão de Pastas](#visão-de-pastas) · [Diálogo de Filtro por GPS](#diálogo-de-filtro-por-gps) · [Sugestões de Mesclagem](#sugestões-de-mesclagem) · [Exportação para Editor](#exportação-para-editor) · [Download](#download) · [Triagem](#triagem) · [Limpeza de lixo](#limpeza-de-lixo) · [Modo de Comparação Pareada](#modo-de-comparação-pareada)
- [Estatísticas EXIF](#estatísticas-exif) · [Atalhos de Teclado](#atalhos-de-teclado-galeria) · [Desfazer](#desfazer) · [Progressive Web App](#progressive-web-app) · [Mobile](#mobile) · [Moldura Digital / Endpoint de Quiosque](#moldura-digital--endpoint-de-quiosque) · [Envio Automático do Telefone](#envio-automático-do-telefone)
- [Configuração](#configuração-2) · [Desempenho](#desempenho) · [Endpoints da API](#endpoints-da-api) · [Fotos JPEG XL](#fotos-jpeg-xl) · [Solução de Problemas](#solução-de-problemas)

> **Requisitos de recurso** são marcados em linha: `[GPU]` · `[16gb/24gb]` (perfil de VRAM) · `[Edition]` (senha de edição) · `[Superadmin]`. Veja a [matriz de recursos](INSTALLATION.md#requisitos-por-recurso).

> **Assistentes de IA**: o Facet pode servir as suas ferramentas a assistentes compatíveis com MCP. Com o nível de token adequado, eles podem pesquisar, alterar e fazer a triagem da biblioteca. Veja [Agentes de IA (MCP)](AGENTS.md).

## Iniciando o Visualizador

### Produção

```bash
python viewer.py
# Abra http://localhost:5000
```

Isso serve a API e a aplicação Angular pré-compilada em uma única porta.

Para maior taxa de transferência, execute em modo de produção (Uvicorn, sem auto-reload). Adicione `--workers N` para escalar (padrão 1):

```bash
python viewer.py --production --workers 4
```

### Desenvolvimento

Execute o servidor da API e o servidor de desenvolvimento do Angular separadamente:

```bash
# Terminal 1: servidor da API
python viewer.py
# API disponível em http://localhost:5000

# Terminal 2: servidor de desenvolvimento do Angular com hot reload
cd client && npx ng serve
# Abra http://localhost:4200 (encaminha as chamadas de API para :5000)
```

## Autenticação

### Modo de Usuário Único (Padrão)

Proteja o visualizador com uma senha opcional:

```json
{
  "viewer": {
    "password": "your-password-here"
  }
}
```

Duas senhas controlam o acesso:

- **`viewer.password`** decide quem pode *navegar*. Vazia, qualquer pessoa navega por toda a biblioteca. Definida, os usuários precisam se autenticar antes.
- **`viewer.edition_password`** é necessária para qualquer edição: avaliações, favoritos e rejeições, triagem, álbuns, gerenciamento de pessoas e rostos, modo de comparação, mudanças de pesos e prioridades e exportações. Vazia (o padrão distribuído), a instalação fica **somente leitura**: toda edição é recusada com `403` ("Set viewer.edition_password to enable editing").

A geração por IA sob demanda (legendas, críticas VLM) também exige a senha de edição. Sem ela, você recebe apenas o que já está em cache (`source: "none"` ou `vlm_available: false`). Sem senha de edição, a galeria também oculta os emblemas existentes de estrelas, favoritos e rejeições, como faz para visualizadores sem edição em uma instalação protegida por senha.

Reinicie o visualizador depois de definir `viewer.edition_password`: a configuração não é recarregada a quente.

> **Aviso:** com um `viewer.password` vazio (o padrão distribuído), qualquer pessoa que alcance a porta do visualizador pode navegar pela biblioteca e baixar os originais. O `viewer.py` escuta por padrão em todas as interfaces (`--host 0.0.0.0`, de que a imagem Docker depende). Defina `viewer.password` antes de expô-lo além do seu próprio computador, ou associe-o ao loopback com `--host 127.0.0.1`. No Docker, publique a porta como `127.0.0.1:5000:5000`. O visualizador registra um aviso na inicialização enquanto `viewer.password` estiver vazio (a menos que seja instruído a escutar apenas no loopback).

O login também grava o token de sessão em um cookie `HttpOnly` `SameSite=Lax`, de modo que miniaturas e o fluxo de progresso da varredura carregam em instalações protegidas por senha. O cookie é aceito apenas em requisições somente leitura (GET/HEAD); as edições continuam exigindo o token Bearer. Encerrar a sessão (`POST /api/auth/logout`) o apaga.

### Modo Multiusuário

Para um NAS familiar em que cada membro tem pastas de fotos privadas. Adicione uma seção `users` ao `scoring_config.json`:

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

Escreva cada entrada de `directories` e `shared_directories` exatamente como o scanner armazenou o caminho. A comparação ignora maiúsculas e minúsculas ASCII no Windows, no macOS e em entradas UNC ou com letra de unidade. Em todos os demais casos (Linux, por exemplo) ela diferencia maiúsculas de minúsculas. Diferenças de maiúsculas fora do ASCII e uma unidade mapeada que o host não consegue resolver não correspondem.

Crie os usuários pela CLI (não há página de registro):

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

Cada usuário vê as fotos de seus próprios diretórios mais as dos diretórios compartilhados. Isso vale em todo lugar: galeria, miniaturas, downloads, estatísticas, opções de filtro e páginas de pessoas.

### Avaliações por Usuário

No modo multiusuário, avaliações por estrelas, favoritos e rejeições são armazenados por usuário na tabela `user_preferences`. Os favoritos da Alice não afetam a visão do Bob.

Para migrar avaliações existentes de usuário único:

```bash
python database.py --migrate-user-preferences --user alice
```

## Opções de Filtragem

A pesquisa de texto da galeria preserva palavras Unicode e trata a pontuação dos nomes de arquivo como abas de palavras. `IMG_0042.JPG` pesquisa os prefixos `IMG`, `0042` e `JPG` em conjunto. Termos em cirílico e CJK funcionam. Operadores FTS como `OR` são tratados como palavras literais.

### Abas da barra lateral

A barra lateral de filtros agrupa as suas seções em cinco abas, mostradas como ícones (passe o mouse para ver o nome). Um pequeno emblema num ícone conta os filtros ativos da aba, e a aba mantém o nome para leitores de tela (“Explorar, 2 ativos”). A última aba usada fica guardada neste navegador (`facet_sidebar_tab`). Explorar, Qualidade e Assunto têm painéis recolhíveis, e cada um lembra se está aberto; Revisão e Visualização não os têm.

| Aba | Seções |
|-----|--------|
| **Explorar** | Busca semântica, Pessoas, Período, Conteúdo, Álbuns, Localização, Pasta, Equipamento |
| **Revisão** | Uma linha de menu cada para a decisão e depois para rajadas, duplicatas, piscadas, brackets, panorâmicas e rejeitadas, uma avaliação por estrelas, os interruptores Favoritos e Monocromático e, para editores, *Rostos manuais a rever* e *Correções de panorama* |
| **Qualidade** | Qualidade, Cor e qualidade, Qualidade estendida, Técnico, Exposição e amplitude (quão boa é a imagem) |
| **Assunto** | Métricas de rosto, Composição, Saliência do sujeito, Momentos (o que está no enquadramento) |
| **Visualização** | Vista (tamanho dos cartões, layout, rolagem rápida, ações dos cartões) |

O cabeçalho, **Encontrar um filtro**, o aviso de álbum inteligente e a busca por nome de arquivo ficam acima das abas em todas elas, por isso `/` funciona a partir de qualquer uma. Digitar em **Encontrar um filtro** oculta as abas e lista os controles correspondentes de todas.

O número junto a **Filtros** é o total de todos os filtros ativos. Um intervalo mín./máx. conta uma vez, assim como o filtro de localização. A busca por nome de arquivo e *Semelhante a* não têm seção e são contados apenas neste total, assim como um filtro sobre uma métrica que esta instalação oculta, para que **Redefinir filtros** ainda possa limpá-lo. **Redefinir filtros** (com dica) aparece junto ao número enquanto houver pelo menos um filtro ativo; o simples **X** no extremo direito apenas fecha a barra lateral em telas estreitas.

Na aba Revisão, a decisão e cada grupo (por exemplo Duplicatas) é uma linha que mostra o valor atual (como Ocultos, Mostrados ou Só estes) e abre um menu de opções, cada uma com uma explicação de uma linha. Uma linha deixada no valor padrão não conta no emblema da aba nem do cabeçalho. *Só* e *Ocultos* excluem-se mutuamente. Enquanto uma decisão está escolhida, Rejeitadas fica bloqueada, e a dica explica o motivo. O botão de estrela define uma avaliação mínima: cada clique a aumenta em um, e o clique depois de 5, ou depois de um máximo vindo de um link, a limpa. Ele divide uma linha com os interruptores Favoritos e Monocromático, só com ícone e com dicas. Nas abas Qualidade e Assunto, passar o mouse sobre o nome de uma configuração explica o que é pontuado e por qual modelo, e os controles de Revisão também têm dicas.

<details><summary>Barra lateral de filtros completa — todas as seções expandidas (clique para ver)</summary>
<p align="center"><img src="../screenshots/filter-sidebar-full.jpg" alt="As cinco abas da barra lateral de filtros lado a lado: Explorar, Revisão, Qualidade, Assunto e Visualização" width="900"></p>
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
| **Cor** | Pontuação de cor, saturação, luminância, espalhamento do histograma; temperatura de cor e faixa de matiz (requerem `--recompute-colors`) |
| **Exposição** | Pontuação de exposição |
| **Avaliações do Usuário** | Avaliação por estrelas |
| **Configurações da Câmera** | ISO, abertura (controle deslizante de faixa de f-stop), distância focal (controle deslizante de faixa) |
| **Conteúdo** | Tags, alternância de monocromático |
| **Momentos** | Confiança do momento narrativo (controle deslizante 0–1: `min_moment_confidence` / `max_moment_confidence`) |

Alguns filtros de intervalo só retornam fotos que têm um valor, então até um filtro que começa em 0 exclui as fotos sem pontuação:

- **Estética IAA, Qualidade do rosto IQA, LIQE, Aesthetic V2.5, Q-ReAlign, DeQA**: uma foto que o modelo não conseguiu pontuar não tem valor. Uma ordenação crescente por esses campos a coloca por último, na galeria e nos álbuns. Veja [Dimensões Suplementares de IQA](SCORING.md#dimensões-suplementares-de-iqa).
- **Nitidez do sujeito, Posicionamento do sujeito, Separação do fundo, Pontos de força**: uma foto sem sujeito detectável não tem valor, e o painel de detalhes omite a linha. A proeminência do sujeito é 0.0 para essa foto. Veja [SCORING.md](SCORING.md).

### Padrões de Composição

Filtrar pelos 8 padrões que o SAMP-Net detecta (em `models/samp_net.py`):
- global, horizontal, vertical, triangular
- surround, quarter, cross, rule_of_thirds

## Ordenação

O botão de ordenação no cabeçalho (e na barra de ferramentas móvel) mostra o ícone da ordenação atual; a sua dica diz `Ordenar por: <ordenação atual>`. Ele abre um menu agrupado com todas as ordenações. O alternador ascendente/descendente fica ao lado. Os modelos de pontuação alternativos usam rótulos curtos (IAA, 2.5, Q-R, DeQA, LIQE e IQA).

**Ordenação lembrada.** A galeria abre na última ordenação escolhida, que prevalece sobre `viewer.defaults.sort`. A escolha é salva por navegador no `localStorage`, não por conta de usuário.

- Só uma escolha feita no menu de ordenação é lembrada. Uma ordenação vinda de um link compartilhado ou de um assistente não é, e o `sort` próprio de um link prevalece.
- Escolher de novo a ordenação padrão configurada, ou redefinir os filtros, esquece a escolha.
- **Relevância** nunca é lembrada, pois exige uma consulta de busca.

As velocidades do obturador são ordenadas pela duração, então `1/250` e `0.004` são iguais. Valores ausentes ou inválidos aparecem por último em ambas as direções.

Colunas ordenáveis por grupo (de `viewer.sort_options`):

| Grupo | Colunas |
|-------|---------|
| **Geral** | Pontuação Agregada, Estética, Pontuação de Qualidade, Data de Captura, Avaliação por Estrelas, Estética (IAA), Pontuação LIQE, Q-ReAlign (estética), DeQA, Estética v2.5 (as três últimas aparecem quando uma foto tem essa pontuação) |
| **Métricas de Rosto** | Qualidade do Rosto, Qualidade do Rosto (IQA), Nitidez dos Olhos, Nitidez do Rosto, Proporção do Rosto, Contagem de Rostos |
| **Técnica** | Nitidez Técnica, Contraste, Nível de Ruído |
| **Cor** | Pontuação de Cor, Saturação |
| **Exposição** | Pontuação de Exposição, Luminância Média, Espalhamento do Histograma, Faixa Dinâmica |
| **Composição** | Pontuação de Composição, Pontuação de Ponto de Força, Linhas Guia, Bônus de Isolamento, Padrão de Composição |
| **Saliência do Sujeito** | Nitidez do Sujeito, Proeminência do Sujeito, Posicionamento do Sujeito, Separação do Fundo |
| **Conteúdo** | Confiança do Momento (NULLs ao final) |

### Meu Gosto

Ordena pelo `learned_score` do ranqueador pessoal: o que ele aprendeu com suas comparações A/B, avaliações e decisões de triagem. Um selo ao lado da ordenação mostra a cobertura (% de fotos com uma pontuação aprendida) e a precisão do ranqueador em dados retidos, para que você julgue o quanto confiar nele. Treine ou atualize o ranqueador com `python facet.py --train-ranker`.

Controlado por `viewer.features.show_my_taste` (padrão: `true`). Status do ranqueador: `GET /api/ranker/status`.

### Métricas ocultas no modo comercial

Com `licensing.mode` definido como `commercial`, o visualizador oculta as métricas cujos modelos não podem ser usados comercialmente: LIQE, Aesthetic IAA, Face Quality IQA (a menos que o OFIQ esteja instalado), DeQA (a menos que `licensing.allow_unclear` esteja definido) e Aesthetic V2.5. Os respectivos filtros, chips e opções de ordenação desaparecem; `/api/config` as lista em `unavailable_metrics`. Na página de ajuste de pesos os controles continuam visíveis, mas desativados, e a pontuação descarta e renormaliza esses pesos. Reinicie o visualizador depois de alterar o modo de licença.

## Decisões de revisão

Use **Estado de revisão → Precisa de revisão** na galeria para percorrer fotos sem decisão. Essa visualização é ordenada por **Data de Captura, mais antigas primeiro**; você pode invertê-la ou restringi-la por data, pasta ou álbum. Escolher um estado de revisão encerra as buscas semânticas e de fotos semelhantes.

- **Manter** uma foto que você quer; **Rejeitar** uma que não quer. Qualquer das duas a retira de Precisa de revisão. Encontre as fotos mantidas com o filtro de estado **Mantidas**.
- Manter é independente de favoritos e de estrelas.
- Manter e **Repor decisão** estão nos detalhes da foto, no menu de contexto e nas ações em lote. Pressione **K** (remapeável, veja [Atalhos de Teclado](#atalhos-de-teclado-galeria)) para manter a foto atual. Nos detalhes da foto, Manter alterna.
- **Repor decisão** limpa Manter e Rejeitar sem alterar estrelas ou favorito.
- As decisões persistem após recarregar, reiniciar e analisar novamente. Em instalações multiusuário, pertencem ao usuário atual.
- Confirmar um grupo de triagem marca suas fotos escolhidas como Mantidas. Avaliações e favoritos existentes não são convertidos em decisões Manter.

**Contagens de progresso.** A galeria mostra as contagens **por decidir**, **mantidas** e **rejeitadas** para toda a pasta, álbum ou escopo filtrado visível, não apenas para a página carregada. A porcentagem é `(mantidas + rejeitadas) / total`. O estado de revisão e a opção Ocultar rejeitadas não reduzem o total; os outros filtros, sim.

**Retomar uma fila.** **Rever por decidir** inicia uma fila. **Continuar revisão** reabre neste navegador a sua fila Precisa de revisão mais recente, na primeira foto ainda por decidir.

- O marcador é por navegador e por identidade conectada (até 20 identidades). Não é sincronizado entre dispositivos.
- Mudar os filtros não o substitui, a menos que você abra outra fila Precisa de revisão.
- Filas de álbum usam os critérios salvos atuais do álbum.
- Grupos temporários de rajada/sequência não são salvos, porque uma nova varredura pode renumerá-los.
- Encerrar a sessão apaga todos os marcadores de fila de revisão neste navegador.

**Avisos flutuantes.** O progresso da revisão, **Continuar revisão**, o aviso de fotos ocultas, o aviso de filtros ativos (com **Redefinir todos os filtros**) e o aviso de migração de miniaturas se empilham no canto inferior direito.

- O × de cada cartão o oculta na aba atual do navegador. Ele volta em uma nova aba, ou quando o aviso muda (outro escopo, outro número de ocultas, um filtro adicionado ou removido).
- Para ocultar o progresso da revisão de vez, use **Ocultar progresso da revisão** / **Mostrar progresso da revisão** no menu do usuário. A escolha é salva por navegador e também oculta o botão **Rever por decidir**.
- Após alguns segundos sem interação, a pilha se recolhe em uma pequena pílula de contagem. Passe o ponteiro ou clique nela para abrir.

## Recursos da Galeria

### Pilhas de fotos manuais

Selecione **2–1000 fotos explícitas** e escolha **Empilhar fotos** na barra ou prima **S** para abrir o editor de página inteira em `/stacks/edit`. Selecionar toda a visualização não cria pilhas. S abre uma pré-visualização, sem guardar diretamente. Menu do utilizador → **Personalizar atalhos** muda a tecla da galeria; a dica, a Ajuda e a referência `?` mostram a tecla atual. Se uma configuração anterior já usa S, é preservada e Empilhar fica **Não atribuído** até escolher uma tecla livre. São necessárias permissões de edição. Cada foto pertence a uma pilha por proprietário. A página centra uma pré-visualização com zoom sobre uma faixa de miniaturas permanente. Clique numa miniatura ou use `←`/`→` para focar uma foto e os seus controlos de capa, ordem ou remoção da pilha. O botão de zoom, a roda ou um duplo clique permitem examinar detalhes.

Use **Cmd+Shift+S** ou **Ctrl+Shift+S** para empilhar fotos explícitas sem pilha pela ordem de seleção, com a primeira como capa. Membros de pilhas existentes abrem o editor. O sucesso limpa a seleção guardada e Desfazer repõe-na; cancelar ou falhar mantém-na. Escape no editor regressa à galeria de origem sem guardar.

**Rejeitar ao empilhar.** Foque uma foto no editor de página inteira ou no diálogo e use **Rejeitar** ou **R**. A foto ativa na câmara escura das pilhas sugeridas tem a mesma ação; abra-a primeiro para escolher a foto. Rejeitar guarda imediatamente a decisão habitual, limpa Manter, favorito e estrelas, e exclui só essa foto da pilha proposta. Não apaga nem modifica ficheiros originais. O contador e as miniaturas esbatidas mostram as exclusões. Desfazer restaura os valores anteriores e a pertença ao rascunho relevante sem substituir escolhas posteriores de ordem ou capa; alterações de revisão posteriores podem impedir Desfazer. Fotos já rejeitadas ficam até serem excluídas explicitamente, sem outra decisão. O agrupamento espera por Guardar; sair sem guardar não desfaz Rejeitar.

Se as fotos selecionadas já pertencem a pilhas, **Combinar pilhas** é a opção inicial: a pré-visualização inclui os outros membros. **Apenas fotos selecionadas** move apenas a seleção explícita. O editor mostra as contagens selecionada e final, membros adicionais e um resumo dos efeitos; expanda os detalhes para cada pilha de origem. Dois ou mais membros restantes conservam a pilha; um só fica sem pilha e uma origem vazia desaparece. Excluir uma foto da nova pilha deixa-a na origem segundo as mesmas regras. A pilha final e o total de fotos afetadas têm um limite de 1000 cada; origens indisponíveis ou parcialmente visíveis são recusadas. Mudar de modo conserva a ordem, a capa e as exclusões ainda aplicáveis.

Reveja a pré-visualização atualizada pelo servidor e escolha **Empilhar fotos** para guardar. A página continua aberta para examinar o resultado; a notificação oferece **Desfazer** enquanto estiver disponível e as revisões corresponderem. **Continuar a editar** obtém uma nova pré-visualização antes de guardar outra vez. **Voltar à galeria** regressa à galeria ou ao álbum de origem com o URL exato e faz expirar o Desfazer anterior. Sair sem guardar descarta o agrupamento; uma rejeição explícita persiste. Recarregar o navegador restaura a seleção apenas para a mesma conta, após nova autorização; abrir o URL sem seleção válida oferece uma forma de voltar.

O indicador ou uma foto empilhada abre o visualizador com miniaturas, botões anterior/seguinte e contador na ordem guardada. As setas permanecem na pilha. **Gerir pilha** abre uma janela de diálogo secundária: clique numa miniatura ou use Esquerda/Direita para a pré-visualização grande, escolha **Capa**, reordene com os botões de seta ou remova membros. Abri-lo por si só mantém a edição normal: membros removidos ficam sem pilha, remover a capa escolhe o primeiro membro restante e menos de dois membros ou **Desempilhar** dissolve a pilha. **Adicionar fotos selecionadas** de outra pilha ativa explicitamente a pré-visualização de reagrupamento e os dois modos. Alterações de agrupamento preservam ficheiros e valores de revisão; Rejeitar explicitamente muda os valores de revisão imediatamente.

- Ações de avaliação, Manter/Rejeitar, metadados, download, álbum e exclusão nunca ampliam uma pilha implicitamente.

**Na galeria.** Uma pilha se recolhe em um cartão; **Expandir todas as pilhas** é uma preferência salva. Filtros e álbuns se aplicam às fotos individuais: a capa aparece se corresponder, senão o primeiro membro correspondente. A navegação por pilha ignora o ocultamento automático de rajadas/duplicatas. Linha do tempo e mapa exibem fotos individuais.

**Seleção.** Selecionar um cartão recolhido seleciona apenas a foto exibida. Abra a pilha e use **Selecionar os N membros** para todos. **Selecionar toda a visualização**, a seleção percentual e `target:view` do assistente incluem todas as fotos correspondentes, inclusive as recolhidas, e as ações de toda a visualização mostram antes a contagem real de fotos. Nos resumos da API e do assistente, `total` conta os cartões exibidos e `photo_total` conta as fotos.

**Privacidade e persistência.**

- As pilhas são privadas do proprietário (a instalação, no modo de usuário único). Editar exige acesso de edição.
- Ficam fora de compartilhamentos públicos e exportações do visualizador. Uma pilha parcialmente visível é somente leitura.
- Novas varreduras preservam capa, ordem e membros. Backups comuns do banco de dados preservam as pilhas.
- As exportações completas do banco de dados do visualizador omitem as pilhas e os álbuns inteligentes cujos filtros indicam uma pilha privada, além dos álbuns inteligentes com filtros ilegíveis (JSON inválido, aninhamento excessivo ou mais de 1 MiB). As atualizações incrementais preservam os álbuns e pilhas do próprio destino.
- A [importação/envio de pilhas Immich](IMMICH.md#importar-e-enviar-pilhas-manuais) é uma operação de CLI separada.

**Pilhas sugeridas** abre a revisão de página inteira em `/culling?mode=stacks`, com os filtros atuais e o regresso à galeria ou ao álbum de origem. Requer permissões de edição. Revê grupos de duplicados e rajadas existentes sem ocultar os seus membros.

- Na grelha, `↑`/`↓` selecionam um grupo, **Enter** abre a câmara escura e **S** empilha-o com a capa proposta. Na câmara escura, `←`/`→` focam uma foto e **S** ou **Enter** empilham com essa capa. **X** ignora o grupo; empilhar e ignorar oferecem Desfazer.
- **Rejeitar** ou **R** na câmara escura exclui a foto ativa. Empilhar guarda as fotos restantes e exige pelo menos duas. Ignorar descarta a proposta original. Com poucas fotos pode examinar as excluídas, mudar de grupo, desfazer, ignorar ou voltar. A rejeição continua guardada após concluir uma proposta. Desfazer Empilhar ou Ignorar restaura as suas exclusões; uma sugestão posterior inicia um novo rascunho.
- A câmara escura conserva a pré-visualização grande com zoom, a lupa, a comparação e a faixa de miniaturas. **Z** alterna o zoom, **P** o realce de foco, **F** o ecrã inteiro; **G** percorre as grelhas de composição; **Escape** regressa à grelha dos grupos. **Editar membros** abre uma janela secundária; reduzir a sugestão a uma foto oferece **Ignorar esta pilha**.
- Os grupos ignorados são guardados por conta até os seus membros mudarem. São excluídos grupos com fotos já empilhadas ou imagens de bracketing/panorama; grupos sobrepostos são excluídos por inteiro, dando prioridade aos duplicados.
- O cabeçalho conta sugestões carregadas, não o total da biblioteca. Cada lote contém no máximo 20 propostas e 2000 fotos (1000 por grupo). O seguinte só carrega automaticamente depois de empilhar ou ignorar todas as sugestões carregadas. **Recarregar sugestões** recarrega o mesmo âmbito; **Voltar à galeria** regressa à origem.
- Indisponível em listas fixadas, Fotos semelhantes ou pesquisa semântica. Empilhar e Ignorar não alteram decisões de revisão nem originais. Só Rejeitar explicitamente muda os valores de revisão.

### Cartões de Foto

- Miniatura com selo de pontuação. Passe o cursor para ver onde a pontuação se situa na sua biblioteca ("Top 18% da biblioteca").
- Tags clicáveis para filtragem rápida
- Avatares de pessoas para rostos reconhecidos
- Selo de categoria
- O clique direito (ou Shift+F10) abre o [menu de contexto](#seleção-múltipla-e-ações-em-lote)

No detalhe da foto, as métricas ficam em abas com ícone: dados EXIF (se houver), Qualidade, Composição (com a saliência do sujeito), Técnica e Histograma. A última aba aberta é lembrada. Cada pontuação fica ao lado da sua distribuição na biblioteca, com a barra da foto destacada; passe o cursor sobre uma barra para ver a posição da foto e o intervalo da biblioteca. A posição é calculada sobre toda a biblioteca, não sobre os filtros atuais, aproximada a uma das 20 barras.

### Seleção Múltipla e Ações em Lote

Clique nas fotos para selecionar; Shift+Clique seleciona um intervalo. Uma barra de ações aparece no canto inferior esquerdo com botões de ícone (passe o cursor para ver os rótulos). As ações em lote exigem o modo de edição.

- **Favoritar** — marca todas como favoritas (limpa rejeição)
- **Rejeitar** — marca todas como rejeitadas (limpa favorito e avaliação)
- **Avaliar** — define ou limpa uma avaliação de 1–5 estrelas
- **Adicionar ao álbum** — adiciona a um álbum existente ou novo
- **Editar etiquetas** — adiciona ou remove uma [tag manual](#tags-manuais) em todas as fotos selecionadas
- **Selecionar todas** — com uma seleção vazia, seleciona todas as fotos que os filtros encontram, não só as páginas carregadas. Com fotos já selecionadas, acrescenta as carregadas e oferece ampliar para toda a visualização. As ações de toda a visualização confirmam antes a contagem exata de fotos.
- **Inverter** — troca a seleção pelo seu complemento. A partir de uma seleção vazia, é toda a visualização. A partir de uma seleção não vazia, permanece entre as fotos carregadas: escolha as que ficam, inverta, rejeite.
- **Comparar** — abre 2 a 4 fotos lado a lado com deslocamento e zoom sincronizados (role para ampliar, arraste para deslocar, duplo clique para restaurar). Os painéis passam à resolução total quando ampliados.
- **Copiar nomes de arquivo** — copia os nomes de arquivo para a área de transferência. Uma cópia de toda a visualização pede confirmação antes; acima de 10 000 fotos é recusada.
- **Exportar** — grava sidecars XMP ao lado dos arquivos (veja [Exportação para Editor](#exportação-para-editor))
- **Selecionar para pasta** — copia as mantidas, ou move/descarta as rejeitadas, para uma pasta (veja [Selecionar para pasta](#selecionar-para-pasta))
- **Excluir** — envia as fotos para a lixeira do sistema (veja [Excluir](#excluir)). Aparece só com `viewer.cull.allow_trash` ligado. Desabilitado para uma seleção "toda a visualização": selecione as fotos explicitamente.
- **Baixar** — baixa as fotos selecionadas
- Limpe a seleção com Escape ou o botão Limpar.

Dê um duplo clique em uma foto para abri-la.

**Menu de contexto.** Clique com o botão direito em uma foto, ou dê foco a ela e pressione Shift+F10 / a tecla Menu.

- Em uma foto dentro de uma seleção de várias fotos, atua sobre toda a seleção com as ações da barra (exceto Inverter e Selecionar todas), inclusive **Editar etiquetas**.
- Em qualquer outra foto, atua apenas sobre ela e acrescenta Abrir foto, Encontrar semelhantes, Por que esta pontuação?, Gravar metadados no arquivo e Atribuir rosto à pessoa (quando a foto tem rostos sem atribuição), conforme as respectivas condições.
- Fazer a triagem de uma só foto pelo menu retira da seleção apenas essa foto.
- Não é oferecido em dispositivos de toque (`hover: none` e `pointer: coarse`); use ali a folha de Ações.

### Manter Top N%

O controle **Manter top %** na barra de ferramentas (modo de edição) faz a triagem de toda a visualização filtrada em uma única etapa. Defina uma porcentagem. O Facet classifica a visualização pela **ordenação atual** (agregada, Meu Gosto, Melhores Escolhas, nitidez…), mantém a parcela superior e **seleciona o restante**. Rejeite-as pela barra de ações, depois de desselecionar as que quiser poupar.

- Nada é movido nem excluído; apenas se preenche a seleção. As rejeições continuam treinando o Meu Gosto.
- A seleção é limitada a 5000 fotos. Em uma visualização maior, refine o filtro (álbum, data, pessoa…).
- Com `hide_brackets` / `hide_panoramas` por padrão, um bracketing ou uma panorâmica conta como **uma** foto.

### Lista fixada pelo assistente

Quando um assistente ligado através de [Agentes de IA (MCP)](AGENTS.md) lhe mostra uma lista exata de fotos, a galeria a apresenta na ordem do assistente. Uma linha de estado indica quantas fotos foram escolhidas; **Voltar à vista habitual** restaura os seus filtros.

- Enquanto a lista é mostrada, a barra de filtros, os chips de tags, os avatares de pessoas, **Encontrar semelhantes** e as ações baseadas em filtros (como **Manter top N%**) ficam ocultos. Mudar de álbum continua substituindo a lista.
- Mostrar uma lista limpa a sua seleção e o painel lateral.
- As escritas do assistente surgem sem recarregar: os cartões alterados se atualizam e as fotos excluídas saem da lista. Uma foto que `cull_apply` moveu ou enviou para a lixeira permanece. Surge um só aviso "O assistente alterou N fotos" por rajada de mudanças. Veja [Atualizações em direto](AGENTS.md#atualizações-ao-vivo).

**Chip Assistente ativo.** Enquanto um assistente trabalha na sua aba, um chip **Assistente ativo** aparece no cabeçalho durante alguns segundos após cada escrita ou comando. Clique nele para abrir **Atividade do assistente**: as últimas 50 ações desta sessão (se perdem ao recarregar), com ferramenta, número de fotos e hora. As ações que indicavam fotos têm **Mostrar as fotos**. Quando o assistente pergunta, a aba lhe diz em que foto está o seu cursor (`focused`) e o que você fez desde a última consulta (`user_activity`). Nada é enviado sem ser pedido. Veja [Controlar a aba aberta](AGENTS.md#controlar-a-aba-aberta).

### Selecionar para pasta

**Selecionar para pasta…** na barra de ações em lote (modo de edição) copia as mantidas, ou move/descarta as rejeitadas, para uma pasta de destino. Descartar significa a lixeira do sistema, nunca uma exclusão permanente, e exige `viewer.cull.allow_trash`.

- **Toda execução começa como simulação.** Você vê uma prévia antes de qualquer gravação; mover/descartar só rodam com um `dry_run=false` explícito.
- **O servidor escolhe os arquivos a partir do estado de cada foto.** Copiar age apenas sobre as mantidas, mover/descartar apenas sobre as rejeitadas. Tudo o mais é reportado como `excluded_by_state`. O cliente não pode entregar uma lista de arquivos a excluir.
- **Os acompanhantes são opcionais.** Rejeitar um JPEG não leva o seu RAW, a menos que você marque **Incluir RAW/XMP acompanhante** (`include_companions`).
- No macOS e no Windows, os arquivos RAW acompanhantes mantêm os nomes no disco, incluindo extensões em maiúsculas; no Windows, os sidecars `.xmp` também.

**Disponibilidade de "Descartar rejeitadas".** A opção "Descartar rejeitadas" só aparece com `viewer.cull.allow_trash` ligado *e* o pacote `send2trash` instalado (`/api/config` informa `cull.trash_available: true`). Caso contrário, o diálogo diz por quê: "o pacote `send2trash` não está instalado" ou "um administrador desativou a lixeira".

**Séries multi-fotograma.** Com `hide_brackets` / `hide_panoramas` por padrão, a seleção contém apenas a exposição base de um bracketing ou o quadro central de uma panorâmica. Assim, por padrão, fazer a triagem de uma série age sobre esse **único** arquivo. Duas caixas opcionais ampliam o alcance:

- **Incluir RAW/XMP acompanhante** (`include_companions`) acrescenta o RAW e o sidecar `.xmp` do mesmo quadro.
- **Incluir irmãos de sequência** (`include_sequence_siblings`) acrescenta os outros quadros da série, mas somente aqueles cujo estado de manter/rejeitar corresponde à ação. Quadros mantidos nunca vão para a lixeira porque um irmão foi rejeitado. Um quadro que você desselecionou nunca é readicionado.
- A prévia sempre informa quantos quadros irmãos existem (`sequence_siblings`). `matched` distingue "nada se qualificou" de um resultado vazio.
- Mover ou descartar o líder de uma série promove um irmão sobrevivente, de modo que a série continua visível.
- Para escolher um subconjunto exato de uma série, abra-a antes pela ação "abrir esta série na galeria" do detalhe da foto. Essa visualização mostra todos os quadros.

Uma triagem com escopo de filtro segue as mesmas regras de filtro da galeria, Tipo de Foto incluído. Uma visualização com mais de 10 000 fotos é recusada em vez de truncada, mesmo em uma simulação: refine (álbum, data, pessoa…) e tente de novo. Detalhes: [API.md](../API.md).

**Onde você pode gravar.** Sem `viewer.export.allowed_target_dirs`, o Facet grava apenas dentro dos seus diretórios de varredura. Uma subpasta da árvore de fotos (por exemplo, `_rejected`) funciona sem configuração. Para uma pasta em outro lugar, adicione-a a `viewer.export.allowed_target_dirs`. Veja [Configuração — Destinos de exportação e seleção](CONFIGURATION.md#destinos-de-exportação-e-seleção). Em Docker/Podman, os caminhos são resolvidos **dentro do contêiner** — veja [Implantação — Semântica de caminhos em contêiner](DEPLOYMENT.md#semântica-de-caminhos-em-contêiner).

**"Acesso negado" em toda ação.** É uma recusa deliberada: a pasta de destino não é permitida, ou a sua sessão de edição expirou. Verifique o campo `detail` da requisição que falhou na aba Rede do navegador. Um problema real do sistema de arquivos se apresenta de outra forma: sucesso parcial com uma contagem `errors` diferente de zero, e o erro do sistema no registro do servidor.

### Excluir

**Excluir** no detalhe da foto e na barra de seleção envia os arquivos direto para a lixeira do sistema (recuperável, via `send2trash`). É distinto de Selecionar para pasta e da câmara escura `/culling`. Usa a mesma flag `viewer.cull.allow_trash`.

- **A entrada da biblioteca some na hora.** Ao contrário de Selecionar para pasta, a linha da foto é removida assim que o arquivo vai para a lixeira; não é preciso `--cleanup-missing-photos`. Um RAW acompanhante trazido junto que havia sido escaneado como foto própria também sai.
- **Somente seleção explícita.** Até 10000 caminhos; "selecionar toda a visualização" fica desabilitado.
- **Escopo.** Por padrão, apenas o arquivo indicado. **Incluir RAW/XMP acompanhante** (`include_companions`) e **Incluir irmãos de sequência** (`include_sequence_siblings`) o ampliam, como em Selecionar para pasta. Ambos vêm desativados.
- **As exposições base de bracketing são protegidas.** O quadro base de um bracketing (`sequence_ev_offset = 0`) é recusado (`refused_bracket_lead`), a menos que você inclua irmãos; então todo o bracketing sai junto. Um líder de panorâmica excluído promove um irmão sobrevivente.
- **Resultados parciais.** Cada caminho é reportado separadamente. Um líder de bracketing recusado não interrompe o resto. Um arquivo cuja tentativa de lixeira falhou (`errors`) mantém a sua linha.
- **Arquivos que já faltam no disco.** **Remover também as entradas da biblioteca cujo arquivo já falta no disco** (ligado por padrão) remove também essas linhas, reportadas como `removed_missing`. Desmarcado, elas voltam em `skipped` com as linhas mantidas. Um caminho fora dos diretórios de varredura, ou em uma pasta ausente ou vazia (um volume offline), permanece sempre em `skipped`. Use `--cleanup-missing-photos` para varrer a biblioteca inteira.

Campos de resposta e códigos de status: [API.md](../API.md).

### Opções de Exibição

- **Modo de Layout** — **Grade** (cartões uniformes) ou **Mosaico** (linhas justificadas que preservam as proporções), em qualquer largura de tela.
- **Tamanho da Miniatura** — controle deslizante de altura do cartão/linha (120–400px, salvo no localStorage)
- **Ocultar Detalhes** — oculta os metadados nos cartões (apenas no modo grade)
- **Dica** — como os detalhes das fotos aparecem: **Painel lateral** (padrão), **Passar o mouse**, **Clicar** ou **Desligado**.
  - O painel lateral mostra todos os detalhes na gaveta da direita, com a mesma disposição do detalhe da foto. Ele acompanha o ponteiro e o clique, então funciona em telas de toque. Mantém a última foto quando o cursor sai da grade.
  - Clicar em uma foto mantém o painel nela até você pressionar **Desselecionar** (que também desseleciona a foto). **Escape** faz o mesmo e limpa a seleção.
  - O painel divide a gaveta com os filtros; abrir os filtros o oculta. Exige uma janela de pelo menos 1280px de largura.
  - **Passar o mouse** e **Clicar** mostram um balão curto: categoria, agregada e posição, estética, composição, nitidez, exposição e uma linha de EXIF.
- **Personalizar botões do cartão** — reordene e mostre/oculte os botões da linha que aparece ao passar o cursor em um cartão. Há nove ações: encontrar semelhantes, por que esta pontuação, gravar metadados, atribuir um rosto, abrir o grupo de duplicatas, o grupo de rajada, a série de bracketing/panorâmica ou a pilha de fotos, e abrir a página da foto. Os botões de grupo só aparecem em fotos que pertencem a um grupo. Os botões de grupo de duplicatas e de pilha de fotos vêm ligados; os demais são opcionais. Salvo por navegador.
- **Ocultar Piscadas** — oculta fotos com piscadas detectadas
- **Somente piscadas / Somente duplicadas** — mostra apenas as fotos com piscada, ou todos os membros de cada grupo de duplicatas. Os alternadores de ocultação ficam suspensos nessa visualização.
- **Mostrar somente rejeitadas** — lista apenas as fotos que você rejeitou. Processe-as com selecionar tudo e **Selecionar para pasta**, ou com **Enviar todas as rejeitadas à lixeira do sistema** na Triagem. Ambos limitam o escopo do filtro a 10 000 fotos; refine por data ou álbum para mais, e desligue os filtros que ocultam grupos para incluir todos os quadros rejeitados. Desabilitado enquanto um estado de revisão está selecionado.
- **Melhor da rajada** — mostra apenas a foto mais bem pontuada de cada rajada
- **Melhor do bracketing** — mostra apenas a exposição base de cada bracketing. **Ligado por padrão.** Independente de Melhor da rajada, porque o líder de rajada de um bracketing nem sempre é a sua exposição base.
- **Melhor do panorama** — mostra apenas o quadro central de cada conjunto de panorâmica ou panorâmica HDR. **Ligado por padrão.**
- **Rolagem Infinita** — as fotos carregam conforme você rola
- **Rolagem Rápida (virtualizada)** — renderiza apenas as linhas próximas à janela de visualização, então a rolagem profunda continua rápida. Ligada por padrão. Desligue-a na aba Exibição da barra lateral se tiver problemas de layout. O modo grade com detalhes visíveis sempre renderiza tudo. Salvo no localStorage (`facet_virtual_scroll`).

### Fotos Semelhantes

Clique em **Semelhante** em uma foto e escolha um modo:

- **Visual** (padrão) — similaridade pHash (70%) + similaridade CLIP/SigLIP (30%). Quando duas fotos compartilham só um dos dois sinais, ele conta com peso total; fotos que não compartilham nenhum nunca são listadas. Todas as correspondências acima do limiar são devolvidas, página a página. Se a foto não tiver nenhum dos sinais, analise-a de novo com `--force` (um simples `python facet.py <dir>` ignora arquivos já processados).
- **Cor** — interseção de histograma (70%) + distância de saturação (10%) + distância de luminância (10%) + bônus monocromático (10%). Pré-filtra pela marcação monocromática e faixa de saturação.
- **Pessoa** — fotos com a(s) mesma(s) pessoa(s), por `person_id` quando disponível, senão por similaridade do embedding facial.

O **controle deslizante de limiar de similaridade** (0–90%) define o rigor da correspondência (não no modo pessoa). Os resultados rolam infinitamente.

### Chips de Filtro

Os filtros ativos aparecem como chips removíveis com contagens no topo da galeria.

### Tags manuais

Tags manuais são tags que você digita por conta própria, salvas ao lado das tags de IA. Ficam armazenadas à parte (`photo_manual_tags`, não a coluna `tags` da foto), então novas varreduras e nova etiquetagem nunca as apagam.

- **Onde aparecem.** Somente no **detalhe** da foto, como chips marcados de forma diferente das tags de IA. Cartões e dicas mostram as tags de IA.
- **Quem pode editar.** Usuários com edição. Em uma instalação sem `viewer.edition_password` são somente leitura. As tags de IA não podem ser removidas.
- **Edição em lote.** Selecione fotos e use **Editar etiquetas** (barra de seleção, folha de Ações móvel ou menu de contexto) para adicionar ou remover uma tag. Seleções de toda a visualização funcionam. Fotos que já têm 50 tags manuais são ignoradas; `count` informa as fotos efetivamente alteradas.
- **Formato.** As tags têm os espaços das pontas removidos, são passadas para minúsculas e têm os espaços colapsados (NFC). Máximo de 64 caracteres, 50 por foto. Tags vazias, vírgulas e caracteres de controle são rejeitados. Uma tag igual a uma das tags de IA da foto não é armazenada.
- **A busca e os filtros as alcançam.** O filtro de tags, a busca de texto, a busca semântica (`/api/search`, exceto o escopo de texto só de legendas), a lista suspensa de tags, as estatísticas e as exportações de sidecar/incorporação/Lightroom usam tags de IA + manuais. A busca de texto encontra uma tag manual como frase inteira.
- **Exceções.** As cápsulas contam apenas tags de IA. As tags manuais nunca afetam pontuações, categorias nem momentos narrativos.
- **Ocultas nos links de compartilhamento.** Quem visualiza por link de compartilhamento nunca as vê. Um álbum inteligente compartilhado ainda aplica o filtro salvo do proprietário.
- **Compartilhadas por todos os usuários.** No modo multiusuário, qualquer usuário com edição pode remover uma tag adicionada por outro.
- **Não podem ser desfeitas.** [Desfazer](#desfazer) não as cobre. Uma tag removida pode voltar de um sidecar; veja [Regras de conflito](INTEROP.md#regras-de-conflito).
- **Tags importadas.** `--import-sidecars` armazena como tags manuais, com origem `xmp`, as palavras-chave de sidecar desconhecidas (que não são tags de IA nem nomes de pessoas).
- **Presas ao caminho do arquivo.** Mover ou renomear um arquivo perde as suas tags manuais.

## Panorâmicas e brackets de exposição

Os quadros de uma panorâmica se destinam a ser unidos e os de um bracketing a ser fundidos; não são tomadas rivais. A detecção de rajadas sozinha os agruparia e ocultaria todos menos um, por isso o Facet detecta essas séries à parte.

**Na galeria.** `Melhor do bracketing` e `Melhor do panorama` (ambos ligados por padrão) mostram um quadro por série: a exposição base de um bracketing, o quadro central de uma panorâmica. Esse quadro leva um pequeno ícone ao lado da estrela e do coração: varredura simples, varredura HDR ou bracketing de exposição. O ícone aparece apenas enquanto o alternador esconde o resto da série.

**Na triagem.** O menu de granularidade oferece `Bracketings de exposição`, `Panoramas` e `Panoramas HDR` como fluxos próprios, nunca fundidos em `Tudo`. Todos os quadros começam mantidos, e confirmar uma série não registra pares de comparação, de modo que o ranqueador não é treinado pela forma como a série foi fotografada.

**Corrigir uma série.** A detecção erra cerca de 4% das séries. As correções são persistentes: sobrevivem a todas as execuções de detecção seguintes. Ambas exigem o modo de edição, pelo menos dois quadros, e podem ser desfeitas pela barra de aviso.

- **Falso positivo** (não é uma panorâmica, ou simples vs HDR): use o menu de correção na barra de ações do grupo, na triagem.
- **Panorâmica não detectada**: selecione os seus quadros na galeria e escolha *Marcar como série* → *Marcar como uma panorâmica*.

**Marcar um bracketing não detectado.** Para uma escada de exposição detectada como rajada comum:

- Na câmara escura, um grupo de rajada simples (sem nenhum quadro já em um bracketing ou panorâmica) oferece *Marcar como bracketing*.
- Na barra de seleção da galeria, use *Marcar como série* → *Marcar como um bracketing*.
- Os quadros devem formar uma escada real: pelo menos 2 quadros, cada um com dados de exposição (f-stop, velocidade do obturador, ISO) e data de captura, e dois nunca com o mesmo valor de exposição. Caso contrário, a marcação é recusada com uma mensagem e nada é salvo.
- Marcar quadros que se sobrepõem a um bracketing já marcado o estende. O conjunto combinado ainda deve ser uma escada válida.
- O fluxo da câmara escura oculta os quadros rejeitados, então uma marcação feita ali nunca inclui um degrau rejeitado.
- Um grupo `bracket` oferece *Descartar a correção*.
- Se um quadro marcado desaparece ou perde os dados de exposição ou de data, toda a série espera até que todos os membros voltem a qualificar.
- **A marcação prevalece sobre a detecção de panorâmica**: uma panorâmica detectada que contém quadros marcados é descartada na próxima execução.

**As correções se aplicam na próxima execução de detecção.** Uma correção é salva na hora e mostrada como pendente: um emblema de relógio no cartão da galeria, um chip *Correção pendente* na triagem. A página de triagem mostra um banner com o botão **Executar a detecção de novo**. O filtro *Correções de panorâmica* da barra lateral (só edição, na aba Revisão) lista as correções pendentes em toda a biblioteca. *Descartar a correção* remove uma depois.

**Ajuste.** A aba Panorâmicas em Comparar salva os limiares calibrados: mínimo de quadros, varredura mínima, maior intervalo e dispersão de exposição HDR. Salvá-los não muda nada até você executar a detecção de novo (o botão fica ao lado de Salvar). Veja [CONFIGURATION.md](CONFIGURATION.md#detecção-de-panorâmicas).

## Gerenciamento de Pessoas

> Navegar pelas pessoas está aberto a todos os visualizadores; renomear, mesclar, alterar avatares e atribuir rostos requerem `[Edition]`.

### Filtro de Pessoa

O menu suspenso lista as pessoas com miniaturas de rostos. Clique em uma para filtrar a galeria.

### Galeria de Pessoa

Clique no nome de uma pessoa para ver todas as suas fotos em `/person/<id>`. Na página Gerenciar pessoas, um clique duplo em um cartão (com nome, sem nome em "Precisa de nome" ou ignorado) abre a galeria com as fotos dessa pessoa; cliques duplos no campo de nome, na caixa de seleção e nos botões continuam com eles.

**Nomear pela galeria.** Quando a galeria está filtrada por uma pessoa (`?person_id=95`), a etiqueta dela na linha de filtros ativos mostra o rosto e o nome, ou **Sem nome**, contornado como lembrete; o × dela (**Remover do filtro**) tira a pessoa do filtro. Para usuários de edição há dois botões antes do ×. **Renomear** (o lápis) renomeia a pessoa ali mesmo: o campo de nome mostra "Quem é? Digite ou escolha um nome" para uma pessoa sem nome e "Renomear ou mesclar em…" para uma com nome, as sugestões mostram o rosto, o nome e o número de fotos de cada pessoa, e **Salvar** ou **Cancelar** o fecha (Esc também cancela). O nome é sempre salvo primeiro (`POST /api/persons/{id}/rename`); se outros grupos já o usam (sem diferenciar maiúsculas e espaços, estejam ou não entre as sugestões), a etiqueta oferece em seguida a mesma mesclagem da página Gerenciar pessoas (veja **Renomear** abaixo), e após uma mesclagem a galeria passa para a pessoa mantida. **Mais** (⋮) abre o menu da pessoa: **Ver todas as fotos de {name}**, **Encontrar mais rostos de {name}** e **Ignorar** (**Restaurar** para uma pessoa ignorada). Quando as opções de ocultação da galeria deixam algumas fotos da pessoa fora de vista, os avisos da galeria informam quantas, divididas em fotos de rajada, de piscada, duplicadas, de bracketing e de panorama, para que você as mostre antes de nomear.

### Página Gerenciar Pessoas

No modo de edição a página tem duas abas, **Com nome (N)** e **Precisa de nome (N)**, e sempre abre em **Com nome**. **Precisa de nome** lista os clusters sem nome, cada um com um campo de nome; **Com nome** reúne as pessoas nomeadas, com as ignoradas numa seção recolhível **Ignoradas** no fim. Usuários somente leitura veem apenas a grade de pessoas com nome. As sugestões de nome, aqui como na etiqueta de pessoa da galeria e no menu de rostos da foto, mostram o rosto, o nome e o número de fotos de cada pessoa. Em **Precisa de nome** o menu de ordenação oferece **Número de rostos** e **Mais recentes**. Quando não resta ninguém para nomear, a aba mostra "Todos têm nome. Os novos rostos que precisarem de nome aparecerão aqui."

Abra-a pelo botão no cabeçalho ou por `/persons`:

| Ação | Como Fazer |
|--------|--------|
| **Mesclar** | Selecione a pessoa de origem, clique no destino, confirme |
| **Excluir** | Clique no botão excluir no cartão da pessoa |
| **Renomear** | Clique no nome da pessoa para editar na própria linha. Se outros grupos já usam esse nome (sem diferenciar maiúsculas e espaços ao redor), uma confirmação mostra um bloco por pessoa (rosto, nome, número de rostos), todos selecionados, com a pessoa que será mantida marcada: a maior entre as selecionadas, que mantém a grafia dela. Desmarque um homônimo, ou cancele, para mantê-lo separado. Uma mesclagem não pode ser desfeita |
| **Dividir** | Abra os rostos de uma pessoa, selecione um subconjunto e divida-o em uma nova pessoa |
| **Encontrar mais rostos** | O botão de busca no cartão de uma pessoa, ou **Encontrar mais rostos de {name}** num menu de pessoa, lista os rostos parecidos com ela, os mais parecidos primeiro, comparados com o centroide da pessoa (`GET /api/person/{id}/possible_faces`). Em **Quais rostos incluir**, três chips mostram cada um sua contagem: **Sem grupo** e **Grupos sem nome**, ativados por padrão, e **Pessoas com nome**, desativado. Um rosto que pertence a uma pessoa com nome leva um selo **de {name}**, e marcar um mostra um aviso de que adicioná-lo o move para esta pessoa. Acima dos rostos, **Grupos parecidos** lista outros clusters cujo centroide se parece com o dessa pessoa (os sem nome, mais os com nome enquanto **Pessoas com nome** estiver ativado); cada um mostra a foto, o nome ou **Grupo sem nome**, o número de rostos e **{percent}% parecido**, com **Mesclar tudo** para incorporar o grupo inteiro a essa pessoa. Mesclar um grupo com nome pede confirmação, e uma mesclagem não pode ser desfeita. Cada rosto leva **Forte** (50 % de semelhança ou mais) ou **Possível**, com a porcentagem, e **Quão parecido** define o limite: um botão de barras de sinal que mostra `≥NN%` e abre o menu de níveis, com cinco níveis, **Muito estrito** 60 %, **Rigoroso** 50 %, **Normal** 35 % (padrão), **Amplo** 25 % e **Muito amplo** 20 %. Quando nenhum rosto atinge o limite, o diálogo mostra "Nenhum rosto se parece com {name} (o mais próximo: N%)." e oferece **Tentar Amplo** ou **Incluir pessoas com nome**. Quando uma busca teria de comparar rostos demais, ela procura só entre os rostos sem grupo; se ainda forem demais, pede um **Ano** em que procurar. **Selecionar os fortes**, Shift+clique para um intervalo e Espaço no rosto em foco agilizam a marcação, e o botão Adicionar mostra quantos estão marcados. Adicionar recalcula o centroide, então a próxima rodada é ordenada pelo que você acabou de confirmar; rostos deixados desmarcados não são oferecidos de novo enquanto o diálogo estiver aberto |
| **Ignorar** | Ignorar um cluster (equipe, desconhecidos): o botão ⊘ de um cartão, também nos cartões "Precisa de nome". Pessoas ignoradas saem da lista, de "Precisa de nome", dos filtros, das sugestões de mesclagem e da busca de rostos, e aparecem na seção recolhível **Ignoradas** no fim da aba **Com nome**, com **Restaurar** (`GET /api/persons?hidden_only=true`). Usa o mesmo sinalizador `is_hidden` de antes. Ignorar vale na hora e mostra por 10 segundos uma notificação com **Desfazer**, aqui e em cada menu de pessoa. |

### Marcar um rosto esquecido
### Rostos na foto
Na visualização da foto, aparece um quadro em volta de cada rosto detectado enquanto o ponteiro está sobre a foto, e passar sobre um rosto mostra o nome (quadro vermelho: ainda sem nome). Os quadros acompanham o zoom e o deslocamento, e arrastar ou clicar duas vezes sobre um rosto continua deslocando a vista ou redefinindo o zoom. O quadro de um rosto sem nome também é tracejado, para não depender só da cor, e todo quadro tem um contorno escuro para continuar visível em qualquer fundo. A menos que os quadros estejam em **Desativado**, pelo teclado Tab passa de um rosto a outro, cada um anunciado pelo nome (ou como rosto desconhecido), e Enter ou Espaço abre o menu dele. Em uma tela sensível ao toque, um toque abre o menu de um rosto só enquanto os quadros estão visíveis (os quadros estão em **Sempre**, ou, exceto em **Desativado**, o rosto é da pessoa pela qual a galeria está filtrada); caso contrário, tocar na foto não faz nada com o rosto. No modo de edição, clicar em um rosto abre um menu: **Trocar pessoa…** (ou **Nomear este rosto…**) para escolher uma pessoa existente ou digitar um novo nome, **Encontrar mais rostos de …** para essa pessoa e **Não é …** para tirar só esse rosto dessa pessoa (`POST /api/face/{id}/unassign`); os outros rostos dela na foto continuam atribuídos a ela. Rostos cujas dimensões salvas não são confiáveis não são desenhados. Os quadros vêm de `GET /api/photo/faces`, que retorna o `box` de cada rosto normalizado ao enquadramento. Todo rosto que pertence a uma pessoa, com ou sem nome, também oferece **Ver todas as fotos de …** (ou **Ver todas as fotos deste grupo**), que abre a galeria filtrada por essa pessoa; isso funciona também no modo somente leitura. Um botão da barra alterna os quadros entre três estados, lembrados por navegador: **Desativado** (sem quadros, e os rostos não podem ser clicados nem focados), **Ao passar o ponteiro** (o padrão, como descrito acima) e **Sempre** (todos os quadros e nomes ficam visíveis). Quando a galeria está filtrada por uma pessoa, os rostos dela continuam com um quadro de traço mais grosso, a menos que os quadros estejam em **Desativado**. **Usar como foto de …** torna o rosto clicado a foto do cartão da pessoa; uma pessoa que recebe rostos sem ter foto ganha automaticamente o mais confiável. Na galeria filtrada por uma pessoa, cada miniatura contorna o rosto dela em vermelho, para ver de qual rosto um cluster trata antes de nomeá-lo. Na lista **Pessoas** do painel direito, clicar no avatar de uma pessoa abre o mesmo menu que clicar no quadro desse rosto, mesmo com os quadros em **Desativado**; **Ver todas as fotos de …** nesse menu abre a galeria.

No modo de edição, abra uma foto e escolha **Marcar um rosto ausente**, mesmo quando nenhum rosto foi detectado. Desenhe um retângulo (ou digite as coordenadas), escolha uma pessoa existente ou digite um novo nome, e então **Salvar**. Cancelar não salva nada.

Salvar, editar ou remover um rosto manual atualiza as caixas e as pessoas da foto sem reabri-la.

- Use o mesmo editor para ajustar, reatribuir ou remover uma marca manual.
- As marcas manuais continuam ligadas à sua pessoa através de novas varreduras e da sincronização do visualizador. Não treinam o reconhecimento nem alteram as pontuações de qualidade do rosto.
- O editor trabalha a partir da imagem original, de modo que fotos RAW e giradas se alinham. Sem o original você pode listar e remover marcas, mas não desenhar.
- Uma marca que não pode ser verificada aparece como **Precisa de revisão**. As marcas de versões de pré-visualização anteriores precisam de uma revisão: abra o original, edite e salve a marca.
- Uma imagem substituída sinaliza as suas marcas. Um retoque sutil ou um pequeno reenquadramento do mesmo tamanho pode passar despercebido. Gravações de metadados, remontagens e outros hosts mantêm as marcas atualizadas.
- O editor reutiliza um quadro decodificado de até 128 MiB; quadros maiores podem exigir outra decodificação. O limite é fixo.
- As marcas excluídas continuam excluídas nas sincronizações seguintes.
- As alterações ficam no banco de dados da biblioteca; originais e sidecars não são tocados.

> **Aviso:** uma reconstrução forçada do banco de dados do visualizador substitui as edições exclusivas do visualizador, marcas manuais incluídas, pelo banco de dados de origem. Exporte-as ou faça backup antes. A sincronização incremental normal as mantém.

A configuração antiga `viewer.performance.face_cache_size` é ignorada e pode ser removida.

## Disparo de Varredura

Inicie uma varredura pelo navegador. O botão Varrer aparece quando **ambas** as condições valem:

- `viewer.features.show_scan_button` é `true` (vem **`false`**).
- Você tem acesso à varredura: o papel `superadmin` no modo multiusuário, ou uma sessão de edição em uma instalação de usuário único com `viewer.edition_password` não vazio.

Em uma instalação aberta de usuário único (`viewer.edition_password` vazio, o padrão), ninguém pode varrer pelo navegador. Exceção: sob `viewer.trusted_local_editing`, uma sessão de navegador local confiável, ou um assistente local com token de Edição completa, pode varrer sem `show_scan_button` nem senha de edição.

O botão fica na galeria vazia (**Escaneie as fotos para começar**) e no fim do cabeçalho (**Procurar novas fotos**; barra inferior em telas pequenas). Ambos abrem o iniciador de varredura:

- Escolha um diretório da lista e inicie a varredura.
- O progresso ao vivo e as linhas de saída chegam ao diálogo. A galeria é atualizada quando a varredura termina.
- A varredura executa o `facet.py` em segundo plano; uma por vez.
- A lista de diretórios combina os `directories` de cada usuário, os diretórios compartilhados, os destinos de `path_mapping` e `viewer.scan_directories`. Preencha `viewer.scan_directories` (por exemplo, `/data/photos`) para que instalações de usuário único e Docker tenham um destino.

Nenhuma GPU é necessária — veja [Which profile fits my hardware?](INSTALLATION.md#qual-perfil-combina-com-o-meu-hardware) e [No graphics card](INSTALLATION.md#sem-placa-de-vídeo). A varredura roda na máquina do visualizador, então é mais rápida quando essa máquina tem GPU.

Para repontuar fotos existentes sem varrer arquivos novos, use `POST /api/scan/recompute` (somente edição) — veja [Prioridade de Categoria e Contextos de Pontuação](#prioridade-de-categoria-e-contextos-de-pontuação).

## Busca Semântica

Digite uma consulta como "pôr do sol sobre as montanhas" e obtenha as fotos correspondentes. A classificação combina a similaridade de embeddings CLIP/SigLIP (70%) com a correspondência de texto FTS5 BM25 em legendas e tags (30%).

- **Requisitos.** As fotos precisam de dados `clip_embedding` armazenados (calculados durante a pontuação). Execute `database.py --rebuild-fts` para habilitar a parte de texto de legendas/tags.
- **Modelo.** Usa o modelo de embeddings do perfil de VRAM ativo (SigLIP 2 para 16gb/24gb, CLIP ViT-L-14 para legacy/8gb), ou o que de `models.clip`/`clip_legacy` corresponder aos embeddings armazenados (veja [CONFIGURATION.md](CONFIGURATION.md)).
- **Velocidade.** Instalar o sqlite-vec acelera a busca; caso contrário o Facet mantém uma matriz em memória. A primeira consulta em uma biblioteca grande pode levar vários segundos.
- **Limiar.** O limiar de correspondência vem de `models.clip.search_threshold_percent` (`5%`) ou `models.clip_legacy.search_threshold_percent` (15%), separado de `tag_threshold_percent`. O controle deslizante da galeria vai de 0 a 50%; `search_threshold_default` de `/api/config` define o início. Até `0%` rejeita similaridade negativa. O padrão de 5% do SigLIP favorece a revocação — veja `clip.search_threshold_percent` em [CONFIGURATION.md](CONFIGURATION.md).
- **Só texto.** `scope=text` restringe a consulta a correspondências FTS5 literais no texto de OCR/legendas.
- **Funciona com todos os filtros da galeria**, inclusive os de ocultação. Com os padrões, membros ocultos de rajadas, duplicatas, bracketings e panorâmicas, piscadas e rejeitadas continuam ocultos.
- **Sem limite de resultados.** A galeria pagina os resultados e mostra o total verdadeiro.
- **Ordenação por relevância.** Com uma consulta ativa, a ordenação passa por padrão a **Relevância** (melhor correspondência primeiro). Limpar a consulta restaura a ordenação padrão.
- **Seleção.** Selecionar todas cobre apenas as fotos carregadas; o escopo de toda a visualização não está disponível aqui.
- Controlado por `viewer.features.show_semantic_search` (padrão: `true`).

Os resultados informam `similarity` (a pontuação combinada) e `embedding_similarity` (o cosseno bruto testado contra o limiar, ausente em resultados só de texto). Os parâmetros de galeria `semantic_q`, `semantic_threshold` e `sort=relevance` estão documentados em [API.md](../API.md).

## Álbuns

Organize fotos em álbuns nomeados em `/albums`. Controlado por `viewer.features.show_albums` (padrão: `true`).

### Álbuns Manuais

Crie álbuns e adicione fotos da galeria com a seleção múltipla. Os álbuns suportam:
- Nome e descrição
- Foto de capa personalizada
- Ordenação personalizada
- Navegar pelo conteúdo do álbum em `/album/:albumId`

### Álbuns Inteligentes

Salve uma combinação de filtros (câmera, tag, pessoa, datas, limiares de pontuação…) como álbum inteligente. Ele se atualiza à medida que novas fotos correspondem. Os filtros são armazenados como JSON em `smart_filter_json`.

### Contexto de Pontuação

Um álbum pode carregar um contexto de pontuação que decide qual categoria vence para as suas fotos, independentemente da prioridade global — veja [Contextos de Pontuação](CONFIGURATION.md#contextos-de-pontuação). Defina-o no diálogo do álbum (modo de edição).

- Defini-lo grava o contexto nos membros **atuais** do álbum. Uma foto com substituição manual própria é deixada em paz.
- Os membros de um álbum inteligente vêm do seu filtro salvo, ignorando os alternadores de ocultação da galeria, então a contagem pode exceder o que a visualização do álbum mostra.
- Fotos adicionadas depois a um álbum manual herdam o contexto. Novas correspondências de um álbum inteligente, não; defina o contexto de novo.
- **Limpar contexto** (diferente de escolher `default`) remove a marca. Uma foto que ainda está em outro álbum com contexto passa a ter esse contexto.
- O Facet pode sugerir um contexto a partir do momento narrativo dominante do álbum (via `suggest_from_moments` de cada contexto). Nada é gravado até você confirmar.
- Execute um recálculo (`POST /api/scan/recompute`) para que o novo contexto altere as categorias armazenadas.

Endpoints e contagens de resposta: [API.md](../API.md#albums).

### Exportação de portfólio

Transforme um álbum manual em uma galeria HTML estática autônoma. Com `viewer.features.show_portfolio_export` ligado (padrão `true`) e a edição desbloqueada, cada cartão de álbum manual tem **Exportar portefólio**. Escolha um título, a pasta de destino e se quer incluir legendas.

- O resultado contém `index.html` (uma grade de miniaturas com lightbox integrado, sem referências externas ou de CDN, funciona offline), uma pasta `assets/` de JPEGs com nomes sequenciais (sem vazar caminhos da biblioteca) e um `manifest.json`.
- Cada foto usa o original, reduzido a `portfolio.max_edge`, ou a miniatura armazenada de 640px se o original estiver inacessível.
- A pasta de destino deve estar na lista de permissão de exportação (`viewer.export.allowed_target_dirs` mais os diretórios de varredura, veja [Configuração — Destinos de exportação e seleção](CONFIGURATION.md#destinos-de-exportação-e-seleção)).
- Álbuns com mais de `portfolio.max_photos` (padrão 500) são recusados.
- Reexportar reescreve apenas os arquivos da própria exportação.

Veja [Configuração da Exportação de portfólio](CONFIGURATION.md#exportação-de-portfólio). Endpoint: `POST /api/albums/{album_id}/export-portfolio`.

### Compartilhamento de Fotos

Compartilhe álbuns por links com token. Ver um álbum compartilhado não exige login.

| Ação | Como Fazer |
|--------|--------|
| **Compartilhar** | Abra o álbum e clique em "Compartilhar" para gerar um link |
| **Revogar** | Clique em "Descompartilhar" para invalidar o token |
| **Ver** | Os destinatários abrem o link para navegar pelo álbum compartilhado em `/shared/album/:id` |

### Aprovação pelo Cliente

Deixe um cliente escolher favoritas de uma entrega. Com `viewer.features.show_proofing` ligado (padrão `false`), um link de compartilhamento pode funcionar em **modo de aprovação**: o cliente o abre, informa um PIN se houver (`viewer.proofing.pin`), então **curte** fotos com um coração e deixa **comentários**.

- As escolhas do cliente são armazenadas à parte (`album_client_picks`) e nunca tocam seus favoritos nem avaliações, nem treinam o ranqueador.
- Leia as escolhas em um diálogo `[Edition]` no cartão do álbum.
- As sessões duram `viewer.proofing.session_minutes` (padrão 24h) e terminam quando o álbum deixa de ser compartilhado ou a aprovação é desligada.

Veja [Configuração — Aprovação pelo Cliente](CONFIGURATION.md#aprovação-de-cliente).

## Crítica por IA

Explica a pontuação de uma foto como pontos fortes, pontos fracos e sugestões. Controlado por `viewer.features.show_critique` (padrão: `true`).

### Crítica Baseada em Regras

Disponível em todos os perfis de VRAM. O Facet recalcula a pontuação a partir das métricas armazenadas da foto e da configuração atual, e mostra o cálculo.

- A **Categoria** é a que a fórmula atual atribui (respeitando uma substituição de categoria e o contexto de pontuação). Pode diferir da categoria armazenada até o próximo `--recompute-average`.
- As **linhas do detalhamento** mostram cada entrada de 0–10 que o pontuador pondera (quanto maior, melhor, então ruído e faixa dinâmica são lidos como qualidade), com peso e contribuição.
- Os **ajustes líquidos e o arredondamento** (bônus, multiplicador de piscada, penalidades de clipping, ruído e supersaturação, limitação) conciliam as linhas com o total do **Cálculo atual**, mostrado ao lado da **Pontuação armazenada**.
- **Condições detectadas** lista a piscada e a dominante de tom de pele.
- Nitidez, cor e nitidez dos olhos usam o instantâneo de percentis do último `--recompute-average`. Uma biblioteca que só foi escaneada usa os valores da varredura.
- **Linhas informativas**, mostradas apenas quando calculadas: forma e harmonia de cores (simetria, equilíbrio, entropia de orientação das bordas, complexidade fractal, harmonia de cores de Matsuda; `--recompute-form`), chips de distorção (desfoque de movimento, dominante de cor, excesso de nitidez…; `--recompute-distortions`) e uma nota de tom de pele para retratos (`--recompute-skin-tone`). Explicam a foto, mas não alteram a pontuação agregada.

Se o cálculo não estiver disponível, apenas a pontuação armazenada é mostrada, com a correção:

| Motivo | Correção |
|--------|-----|
| Esquema desatualizado | `python database.py` |
| Instantâneo de normalização indisponível | Tente de novo, depois `python facet.py --recompute-average` |
| Métricas armazenadas inválidas | Analise de novo com `--force` |

O diálogo também distingue uma foto *ainda não pontuada* de uma cuja *pontuação armazenada é inutilizável*.

### Crítica por VLM `[GPU]` `[16gb/24gb]`

Usa o VLM configurado (Qwen3.5-2B ou Qwen3.5-4B) para uma crítica sensível ao contexto. Exige o perfil 16gb ou 24gb, `viewer.features.show_vlm_critique` como `true` (o padrão) e uma sessão de edição para gerar. Sem edição, apenas uma crítica em cache é mostrada e `vlm_available` é `false`. A caixa de diálogo gera por `POST /api/critique/vlm` (somente edição; requisições simultâneas para uma mesma foto compartilham uma única geração); `GET /api/critique` apenas lê o cache e nunca gera, traduz nem grava.

- O prompt (`critique.vlm`) inclui o detalhamento da pontuação, as pontuações armazenada e recalculada, as condições detectadas e o EXIF.
- A resposta se lê como **Observação / Avaliação / Sugestões**. É salva em cache por foto (`photos.vlm_critique`), traduzida quando uma sessão de edição a abre no idioma de destino (depois salva e servida como está), e **Regenerar** a recalcula. Sem uma sessão de edição você vê o texto sem tradução, a menos que já exista uma tradução salva.
- Roda sobre a miniatura armazenada, então arquivos RAW funcionam.

**Sobreposição visual "por que esta pontuação".** Com `viewer.features.show_saliency_overlay` ligado (padrão `true`), o diálogo de crítica tem **Mostrar sobreposição**. Ela desenha o mapa de saliência do BiRefNet como mapa de calor (`GET /api/saliency_overlay`), além de caixas de rostos e marcadores de olhos a partir dos pontos de referência armazenados (`GET /api/photo/face_markers`). As caixas são verdes para olhos abertos e âmbar para piscada. O mapa de calor tem a resolução da miniatura, então é aproximado. O botão se oculta em perfis que não conseguem produzir uma máscara de saliência.

## Legendagem por IA `[GPU]` `[16gb/24gb]` `[Edition]`

Obtenha uma legenda em linguagem natural para qualquer foto. Uma sessão de edição a gera na primeira requisição; depois fica em cache na coluna `caption`. Edite as legendas no detalhe da foto (modo de edição). Uma instalação aberta, somente leitura, nunca gera uma. `POST /api/caption` a gera (e traduz); `GET /api/caption` apenas devolve a legenda ou a tradução salva e nunca gera, traduz nem grava.

Geração e tradução em lote pela CLI:

```bash
python facet.py --generate-captions      # Gera legendas para todas as fotos sem legenda
python facet.py --translate-captions     # Traduz as legendas para o idioma de destino configurado
```

A tradução usa MarianMT na CPU (sem necessidade de GPU). Defina o idioma com `translation.target_language` (padrão: `"fr"`). Suportados: francês, alemão, espanhol, italiano.

Controlado por `viewer.features.show_captions` (padrão: `true`). Sem o perfil 16gb/24gb ou um `vlm_backend` remoto, o botão Gerar legenda fica oculto e as críticas permanecem baseadas em regras.

## Memórias ("Neste Dia")

Veja fotos tiradas na data de hoje em anos anteriores. Memórias abre uma apresentação aleatória em tela cheia.

Controlado por `viewer.features.show_memories` (padrão: `true`).

## Fluxos de trabalho comuns

- **Fazer a triagem de uma viagem** — abra Cápsulas e encontre a cápsula `journey` da viagem. Cada cápsula pode ser salva como álbum.
- **Revisar dia a dia** — abra a Linha do Tempo e desça de anos para meses e dias. Clique em um dia para abrir a galeria filtrada nele.
- **Mostrar o que está oculto** — por padrão a galeria oculta piscadas e rajadas e duplicatas não líderes. Quando algo está oculto, aparece no canto inferior direito o aviso "N fotos ocultas pelos filtros atuais · Mostrar todas".
- **Voltar aos seus filtros** — o ícone de fotos do cabeçalho volta à galeria com os filtros, a ordenação e a posição em que você estava. Toque duas vezes nele, ou redefina os filtros, para começar do padrão.

## Visão de Linha do Tempo

Navegue cronologicamente: os anos descem para meses e depois para um calendário de dias. Cada bloco mostra a contagem de fotos e uma foto de capa. Clique em um dia para abrir a galeria filtrada por essa data; ordene ali.

Os cinco alternadores de ocultação da galeria (`hide_blinks`, `hide_bursts`, `hide_duplicates`, `hide_brackets`, `hide_panoramas`) se aplicam, com `viewer.defaults` como padrão, de modo que as contagens dos blocos coincidem com o que a galeria mostra. Quando algo está oculto, um botão `visibility_off` aparece na barra de ferramentas ("Algumas fotos estão ocultas pelos seus filtros"); clique nele para limpar os cinco.

Abra `/timeline`. Controlado por `viewer.features.show_timeline` (padrão: `true`).

## Visão de Mapa

Veja as fotos em um mapa Leaflet interativo, agrupadas por nível de zoom, a partir das coordenadas GPS do EXIF.

### Preparação

Extraia as coordenadas GPS de fotos existentes:

```bash
python facet.py --extract-gps    # Extrai lat/lng GPS do EXIF para o banco de dados
```

As fotos novas recebem as coordenadas durante a pontuação.

Abra `/map`. Controlado por `viewer.features.show_map` (padrão: `true`). Os fundos do mapa vêm do OpenStreetMap e exigem conexão com a internet, mesmo no aplicativo instalado.

### Locais salvos e GPS manual

**Encontrar fotos sem localização.** Nos filtros, abra **Localização** e ative **Sem geolocalização**. Pode ser salvo em um álbum inteligente. Desliga-se quando você inicia uma busca semântica/de semelhantes ou escolhe um raio no mapa.

**Definir a localização de uma foto.** No modo de edição, abra **Adicionar localização** ou **Editar localização** em uma foto. Pesquise em **Locais guardados**, escolha uma **Localização recente**, solte um pino ou digite coordenadas. **Salvar** aplica.

**Definir várias de uma vez.** Selecione fotos e escolha **Definir localização** (barra de seleção, ações móveis ou menu de contexto).

- **Somente fotos sem localização** vem ligado por padrão; desligue para substituir localizações existentes.
- **Pré-visualizar alterações de localização** mostra quantas serão alteradas ou ignoradas. Se algo mudar nesse meio-tempo, pré-visualize de novo.
- Até 1000 fotos visíveis por lote, inclusive seleções de toda a visualização.

**Locais guardados.** Escolha um ponto e use **Guardar este local** com um nome (por exemplo, "Trabalho"), ou marque como favorito o ponto de uma foto georreferenciada. Renomeie ou exclua pela lista; isso não move fotos já atribuídas. Cada editor tem uma lista privada: até 100 locais salvos e 20 pontos recentes.

**As localizações manuais permanecem.** Uma localização definida no visualizador sobrevive a novas varreduras e à nova extração de EXIF, inclusive uma limpa. **Usar a localização do arquivo** descarta a substituição e relê o GPS do arquivo (ou o limpa se o arquivo não tiver).

**Gravação nos arquivos.** Salvar nunca grava o arquivo de imagem. Uma exportação explícita de metadados grava as localizações manuais (e as limpezas explícitas) no sidecar XMP: no visualizador ou com `--export-sidecars`. A incorporação (**Gravar metadados no arquivo**, ou `--embed-originals`) também grava o GPS EXIF nos originais suportados. Veja [INTEROP](INTEROP.md).

### Pesquisa online de locais

Use **Endereço ou estabelecimento → Pesquisar online** para procurar um local com o Photon (dados do OpenStreetMap, © contribuidores do OpenStreetMap). A consulta só é enviada quando você clica em **Pesquisar online** ou pressiona Enter. Escolha um resultado para pré-visualizar e então **Salvar**. Locais salvos e coordenadas funcionam offline.

- `viewer.place_search_url` (padrão `https://photon.komoot.io/api`) aponta para o provedor. Use um Photon próprio, ou `""` para desativar a busca.
- A demonstração pública não tem garantia de disponibilidade. Use um único worker do visualizador com ela, pois cada worker tem o seu próprio limite de taxa.
- As consultas têm de 3 a 200 pontos de código Unicode e devolvem até cinco resultados em cinco segundos, em uma resposta de no máximo 64 KiB. Os rótulos dos resultados são limitados a 600 caracteres Unicode.
- Um cache por processo salva 128 buscas por 15 minutos. No modo multiusuário, cada conta vê apenas as suas entradas, mas a capacidade de 128 entradas e a limitação do provedor são compartilhadas pelo processo.
- O Facet espera pelo menos um segundo entre chamadas ao provedor e nunca envia duas ao mesmo tempo.
- O Facet não registra as consultas. Configure o seu proxy reverso para não registrar as query strings.

## Cápsulas

Apresentações temáticas agrupadas por tema, local, pessoas e tempo. Abra `/capsules` e clique em uma cápsula para reproduzi-la.

### Tipos de Cápsula

O Facet gera cápsulas a partir da sua biblioteca:

- **Journey** — viagens detectadas por agrupamento de GPS, com nomes de destino geocodificados ("Journey to Rome — March 2025")
- **Moments with [Person]** — melhores fotos de cada pessoa reconhecida
- **Seasonal Palette** — fotos agrupadas por estação + ano
- **Golden Collection** — o 1% superior por pontuação agregada
- **Color Story** — grupos visualmente semelhantes por agrupamento de embeddings CLIP
- **This Week, Years Ago** — "Neste Dia" ampliado a ±3 dias
- **Location** — grupos de fotos georreferenciadas com nomes de locais
- **Favorites** — fotos favoritas agrupadas por ano e estação
- **Dimension-based** — por câmera, lente, categoria, padrão de composição, faixa de distância focal, hora do dia, avaliação por estrelas e combinações

### Apresentação de slides

Clique no cartão de uma cápsula para iniciar uma apresentação:
- **Transições temáticas** — slide (journeys), zoom (retratos), kenburns (golden/seasonal), crossfade (padrão)
- **Encadeamento automático** — quando uma cápsula termina, um cartão mostra a próxima
- **Embaralhar e retomar** — as fotos são embaralhadas; a sua posição é salva por cápsula
- **Agrupamento adaptativo** — fotos em retrato são mostradas lado a lado para caber na tela
- **Salvar como álbum** — salve qualquer cápsula como álbum

### Atualização

As cápsulas giram segundo um agendamento (padrão: 24 horas). **Regenerar** no cabeçalho as atualiza agora.

### Geocodificação Inversa

As cápsulas de local e de viagem mostram nomes de locais (por exemplo, "Paris, France") usando o pacote offline `reverse_geocoder`. Sem chamadas de API; os resultados ficam em cache no banco de dados.

Instalação: `pip install reverse_geocoder`

### Configuração

Veja [Configuração — Cápsulas](CONFIGURATION.md#capsules) para todas as opções.

## Visão de Pastas

Navegue por diretório em `/folders`.

- As migalhas de pão sobem na árvore.
- Cada pasta mostra como capa a sua foto de maior pontuação.
- Clique em uma pasta para abri-la, ou em uma foto para abri-la na galeria.
- Cada cartão de pasta tem uma ação de filtro que abre a galeria restrita a essa pasta.
- No modo multiusuário, você vê apenas os seus diretórios.

### Filtro de Pasta

A seção **Pasta** da barra lateral de filtros tem **Escolher pasta…**, um seletor que percorre a árvore. Aplicá-lo restringe a galeria a essa pasta **e às suas subpastas**. Aparece como chip, combina com outros filtros, sobrevive a um recarregamento (parâmetro de URL `path_prefix`) e é salvo em álbuns inteligentes.

Ele restringe apenas a grade de fotos. As listas suspensas da barra lateral, as contagens por tipo, as estatísticas, a linha do tempo, o mapa e a busca continuam em toda a biblioteca.

## Diálogo de Filtro por GPS

Filtre as fotos por localização com um seletor de mapa:

- Clique no botão de filtro de localização para abrir o mapa.
- Clique ou arraste para definir um ponto central.
- Ajuste o controle deslizante de raio.
- As fotos dentro do raio aparecem na galeria.
- Exige coordenadas GPS (execute `--extract-gps` se as fotos tiverem dados GPS no EXIF).

## Sugestões de Mesclagem

Encontre agrupamentos de pessoas que podem ser a mesma pessoa. Abra `/merge-suggestions` ou vá pela página Gerenciar Pessoas.

- **Controle deslizante de limiar de similaridade** — mais baixo mostra mais sugestões, mais alto menos
- **Mesclar** — aceita uma sugestão
- **Mesclagem em lote** — mescla várias sugestões de uma vez
- As sugestões descartadas não são propostas de novo
- CLI: `python facet.py --suggest-person-merges`

## Exportação para Editor

Grave avaliações, favoritos e rejeições em sidecars XMP para que darktable, Lightroom e outros editores os leiam. Exige o modo de edição.

- **Pela galeria** — selecione fotos e então **Ações → Exportar** grava um sidecar ao lado de cada arquivo.
- **Por um álbum** — exporte o álbum inteiro como sidecars, ou copie/crie links simbólicos dos seus arquivos para uma pasta (mesma lista de permissão de [Selecionar para pasta](#selecionar-para-pasta)). Os álbuns usam a sua composição armazenada, inclusive os inteligentes.
- **Gravar metadados no arquivo** — no detalhe da foto, incorpora avaliação e palavras-chave no original (JPEG/HEIC/TIFF/PNG/DNG via exiftool) além de gravar o sidecar. Arquivos RAW proprietários nunca são modificados. Controlado por `viewer.features.show_embed_metadata` (padrão: `true`).
- **Lightroom** (modo de edição) — **Baixar manifesto do Lightroom** salva `facet_manifest.json` para a seleção do diálogo, para a etapa **Facet: Apply ratings and flags...** do `facet.lrplugin`. **Importar estado do Lightroom…** lê o `facet_lightroom_state.json` do menu **Facet: Export Lightroom State to Facet...** do plug-in (o Lightroom prevalece em avaliação e escolha/rejeição) e informa as contagens de correspondidas/não correspondidas/alteradas. Não é preciso executar `--import-lightroom`. Veja [Lightroom Classic](INTEROP.md#lightroom-classic).

**Limites e progresso.**

- As exportações são limitadas a 10 000 fotos, seja para seleções, visualizações filtradas ou álbuns. Um conjunto maior é recusado antes de qualquer gravação; refine os filtros e tente de novo.
- As exportações rodam em segundo plano, com progresso e contagens de gravados/ignorados/erros. **Parar após o arquivo atual** cancela entre arquivos; os sidecars concluídos permanecem.
- Só um trabalho da biblioteca roda por vez. Enquanto uma exportação roda, varreduras, recálculos e o retreinamento automático esperam ou são recusados, e uma exportação é recusada enquanto um deles roda.
- Fechar o diálogo deixa de acompanhar o progresso, não a exportação.
- Reabra Exportar para o editor para ver as suas 20 exportações mais recentes. **Tentar de novo os arquivos pendentes** inicia um novo trabalho para os arquivos com falha, ignorados e não processados. Um arquivo interrompido durante a gravação pode ser gravado de novo.

## Download

Baixe fotos pelo detalhe da foto ou pela barra de seleção. O menu de download por foto lista os tipos disponíveis para essa foto, inclusive os perfis darktable configurados:

- **Original** (`original`) — o arquivo como está (JPG/HEIF), ou um RAW convertido em JPEG com a mesma renderização que o visualizador mostra. Um quadro de bracketing baixa, portanto, sem correção de exposição — veja [CONFIGURATION.md](CONFIGURATION.md#quadros-de-bracketing-são-renderizados-sem-correção).
- **darktable** (`darktable`) — o RAW acompanhante convertido com um perfil darktable nomeado. Recorre ao original se não houver RAW acompanhante.
- **RAW** (`raw`) — o arquivo RAW acompanhante como está. Não disponível em álbuns compartilhados.

**Recorte social orientado pela saliência.** Com `viewer.features.show_social_export` ligado (padrão `true`) e a edição desbloqueada, a barra de download do detalhe da foto tem um menu **Recorte social**. Ele lista `social_export.presets` (quadrado 1:1, retrato 4:5, story 9:16 por padrão). Escolher um baixa um JPEG de resolução total recortado nessa proporção e centrado no sujeito. O sujeito vem da caixa de sujeito do BiRefNet (`photos.subject_bbox`, de `--recompute-saliency`), senão dos rostos detectados, senão do centro. A dica do menu mostra qual foi usado (`saliency` / `faces` / `center`).

Endpoints: [API.md — Download](../API.md#download).

## Triagem

A página de triagem (`/culling`, modo de edição) agrupa tomadas quase idênticas para que você fique com a melhor de cada e rejeite o resto. Escolha a(s) melhor(es) de cada grupo; confirmar rejeita as outras. As confirmações são adiadas e podem ser desfeitas (veja [Desfazer](#desfazer)).

A **Granularidade** (o primeiro controle da barra de ferramentas) escolhe como as fotos são agrupadas:

- **Tudo** (padrão) — rajadas e grupos de semelhantes fundidos.
- **Rajadas** — fotos tiradas em sequência próxima no tempo.
- **Semelhantes** — fotos de aspecto parecido, seja qual for o horário, por similaridade CLIP/SigLIP. Um controle deslizante define o rigor.
- **Cenas** — sequências cronológicas por horário de captura, cada uma encabeçada pelo seu intervalo de tempo e pelo momento narrativo principal. Exige `viewer.features.show_scenes`.
- **Bracketings de exposição** — séries encontradas por [`--detect-sequences`](COMMANDS.md), exposição base primeiro, cada quadro com o emblema da sua compensação (`-2 EV` … `+2 EV`).
- **Panoramas** — varreduras encontradas por [`--detect-panoramas`](COMMANDS.md), em ordem de captura, com o quadro central marcado.
- **Panoramas HDR** — varreduras de panorâmica com dispersão de exposição acima de `hdr_min_span_stops`. Um conjunto HDR de tripé aparece primeiro em **Bracketings de exposição** e passa para cá (como `hdr_panorama`) quando a passagem de panorâmica reconhece a varredura. Se nunca reconhecer, continua como bracketing.

**Séries mantidas inteiras.** Bracketings de exposição, Panoramas e Panoramas HDR não fazem parte de **Tudo**. Todos os quadros começam mantidos, e confirmar não registra pares de comparação. O duplo clique ("manter só esta") não faz nada ali. Esses fluxos ignoram os alternadores `hide_*` da galeria e mostram todos os quadros. Para descartar as exposições laterais, use a poda de bracketings da seleção automática (abaixo).

Um grupo que fica com menos de 2 quadros depois de removidas as fotos já rejeitadas sai do fluxo.

**Ordenação.** O **modo de ordenação** (mais fáceis primeiro, mais redundantes, melhores, mais recentes, precisa de comparações, **mais antigas primeiro**) fica ao lado da granularidade, com um botão de seta que o inverte. "Mais antigas primeiro" também ordena as fotos *dentro* de cada grupo por horário de captura, o que convém a bracketings e panorâmicas.

Granularidade, ordenação e categoria persistem no `localStorage`. Os controles que não se aplicam ficam ocultos (sem ordenação nem limiar no modo cenas; sem botão de escopo sem álbuns manuais). Em telas pequenas a barra de ferramentas vira uma barra inferior rolável.

**Enviar todas as rejeitadas à lixeira do sistema.** Este botão da barra de ferramentas pré-visualiza todas as fotos rejeitadas visíveis para você em toda a biblioteca, inclusive quadros ocultos. Ignora álbum, data e filtros da galeria. **Aplicar** envia os arquivos à lixeira do sistema na máquina do Facet. Ao contrário de **Excluir**, as linhas da biblioteca e as decisões permanecem, para o Meu Gosto.

- Exige acesso de edição, `viewer.cull.allow_trash` e suporte a lixeira.
- Limitado a 10 000 fotos. Para mais, use Mostrar somente rejeitadas na galeria, refine por data ou álbum e use Selecionar para pasta → Descartar rejeitadas em lotes. Desligue os filtros que ocultam grupos para incluir todos os quadros rejeitados.
- Os arquivos RAW/XMP acompanhantes são opcionais.
- Se os arquivos resolvidos, as opções ou o destino mudaram desde a prévia, Aplicar é recusado; pré-visualize de novo. A verificação compara nomes de arquivo e configurações, não o conteúdo dos arquivos, e não bloqueia os arquivos.
- Uma falha do sistema de arquivos no meio do caminho deixa os arquivos já concluídos na lixeira; o diálogo continua aberto para uma nova prévia.
- Em contêineres, a lixeira e a recuperação dependem do sistema de arquivos do servidor.

> **Aviso:** em uma biblioteca compartilhada, Enviar todas as rejeitadas à lixeira usa apenas as *suas* rejeições. Ele envia à lixeira os arquivos compartilhados mesmo que outro usuário os tenha mantido, favoritado ou avaliado. Confira a prévia.

**Triagem com escopo.** Restrinja a câmara escura com parâmetros de URL: `?group_by=scene` para cenas, `?album=<id>` para um álbum, `?from=&to=` para uma janela de horário de captura (texto EXIF ou datas ISO como `2026-06-01`). Um banner mostra o escopo com **Sair da cena**. As rajadas que cruzam a borda da janela ainda mostram todos os seus quadros.

**Intervalo de datas.** O botão de **intervalo de datas** (ícone `date_range`) oferece **Últimos 7 dias**, **Últimos 30 dias**, **Este ano**, **Ano passado**, **Intervalo personalizado...** e **Todas as datas**. As datas aparecem como dd/MM/yyyy.

- Combina com o escopo de álbum. Fotos sem data de captura saem de um intervalo com datas.
- Os padrões são resolvidas quando escolhidas, então um "Últimos 7 dias" nos favoritos é uma janela fixa.
- O intervalo vive só na URL (`?from=2026-07-01&to=2026-07-31`), não no `localStorage`.
- Mudá-lo recarrega o fluxo: uma confirmação pendente é efetivada, e seleções e pulos não confirmados são descartados.

**Linha Meu Gosto.** Cada confirmação registra comparações `source='culling'` que treinam o ranqueador pessoal. O diálogo de Ajuda (menu do usuário → Ajuda) mostra "Meu Gosto · N comparações" (`GET /api/ranker/status`) e lista os atalhos da triagem.

**Perfis de gênero.** O seletor de **Perfil** aplica um padrão de gênero que define de uma vez o rigor, o orçamento de fotos mantidas, o limiar de similaridade e os cortes de rosto de olhos fechados / expressão ruim. Esportes mantém só as mais nítidas de uma rajada, casamentos mantêm mais variantes de olhos abertos, shows e vida selvagem relaxam os critérios de rosto. A escolha e o controle deslizante de rigor persistem no `localStorage`. Mudar um parâmetro à mão mostra "Personalizado". Os padrões vivem em [`cull_profiles`](CONFIGURATION.md#perfis-de-seleção-por-gênero) (`GET /api/culling/profiles`).

### Seleção automática

**Seleção automática** na barra de ferramentas faz a triagem de um escopo inteiro de uma só vez.

1. Escolha o escopo: todos os grupos, ou só rajadas / semelhantes / cenas, opcionalmente um álbum ou janela de datas.
2. Defina o **rigor** (mais alto mantém menos por grupo).
3. Pré-visualize. Cada grupo mantém a sua melhor foto mais tudo o que estiver dentro da margem de rigor (pelo menos um mínimo por grupo), e rejeita o resto.
4. Confirme. As rejeições são registradas, as fotos mantidas são marcadas como **Mantida**, e o Meu Gosto aprende com isso.

- A prévia é uma **simulação**: nada é gravado.
- Um álbum opcional de **Destaques** reúne a melhor foto de cada grupo com pontuação de pelo menos `auto_cull.highlights_min`.
- Um emblema "foto melhor neste grupo" assinala os grupos em que a seleção automática manteria um quadro diferente do líder atual.
- Quando um modelo de classificação de fotos mantidas está treinado e passa pelo seu limite de precisão, ele escolhe a foto mantida (`keeper_prob`). Caso contrário, a heurística habitual escolhe.
- O botão fica oculto nas granularidades que mantêm séries inteiras. Em um escopo misto, os bracketings são decididos primeiro.
- Configure com o bloco [`auto_cull`](CONFIGURATION.md#auto-cull) (`POST /api/culling/auto`). Execute-a pelo terminal com `python facet.py --auto-cull` — veja [Triagem](COMMANDS.md#triagem-pelo-terminal).

**Poda de bracketings redundantes** (`trim_brackets`, desligada por padrão) é a única forma de a seleção automática reduzir uma série. Quando a exposição base de um bracketing não corta nem sombras nem realces, os quadros laterais não acrescentam nada, então só o quadro base é mantido. Séries cujo clipping da base nunca foi medido são deixadas em paz.

### Modo de plano do assistente

Quando um assistente ligado através de [Agentes de IA (MCP)](AGENTS.md) pré-visualiza uma seleção automática (`auto_cull`, ou `ui_show_culling_plan`), a sua aba aberta carrega esse plano em `/culling`. É a câmara escura normal (lupa `Z`, comparar 2-up / 4-up, peaking), com as fotos a manter do plano pré-selecionadas.

- Um banner diz **Plano do assistente · x/y confirmados · Sair**.
- Cada grupo tem um chip como **#3 · motivo · manter 2 / rejeitar 1 sugerido**. Um chip azul no cabeçalho é a nota do assistente sobre o grupo.
- Um ponto em um quadro significa que você o alterou em relação ao plano.
- Um emblema tracejado **Assistente: manter** / **Assistente: rejeitar** é a sugestão do assistente, com o motivo na dica. Clique nele (ou Enter/Espaço) para aplicá-lo; você ainda confirma o grupo.
- Confirme grupo a grupo como de costume, com a contagem regressiva e **Desfazer**. As confirmações do modo de plano nunca adicionam a um álbum de destaques.
- Um grupo de rajada ou de semelhantes confirmado sai do plano. Um grupo de cena confirmado não é registrado, então a próxima prévia pode propô-lo de novo.
- Confirmar uma rajada rejeita apenas os membros mostrados; os membros fora da janela de álbum ou de datas não são tocados.
- Ordenação e limiar ficam travados. Mover o controle deslizante de rigor ou mudar o **intervalo de datas** replaneja; as suas inversões e os grupos confirmados são mantidos. **Todas as datas** pode atingir o limite do plano (`plan_truncated`).
- **Sair**, ou mudar o agrupamento, o escopo ou a ordenação, deixa o modo de plano. Sair de `/culling` e voltar o restaura; recarregar o descarta.
- Se a biblioteca mudou desde a prévia, um aviso diz que o plano está desatualizado. Os grupos grandes demais ficam de fora e são contados em um aviso.

O assistente lê o seu progresso com `ui_get_context` (`culling`: grupos confirmados, pendentes e alterados) e não aplica nada pela própria aba. Veja [Modo de plano em `/culling`](AGENTS.md#os-resultados-aparecem-na-sua-aba).

### Tela cheia

Pressione **`F`** (ou o alternador do cabeçalho) para revisar em tela cheia, sem elementos do aplicativo. Pressione `F` ou `Esc` para sair.

Pressione **`S`** (ou o botão de pilha do cabeçalho) para empilhar o grupo aberto com o quadro em foco como capa. As decisões não são tocadas e Desfazer é oferecido. Não é oferecido para grupos com quadros de bracketing ou panorâmica, nem com uma foto já em uma pilha.

### Lupa / zoom com a tecla Z

Pressione **`Z`** na visão única para alternar uma lupa (ajuste ↔ 2×; roda ou `+`/`-` até 800%). Ampliado além do ajuste, o painel carrega o `/image` em resolução total, para você avaliar o foco em pixels reais. As miniaturas têm 640px e a visão ajustada é uma renderização de até 1920px; a lupa vai além.

- Na tira de contatos de Cenas, `Z` alterna uma lupa ao passar o cursor, com um controle deslizante de zoom.
- Os painéis mostram primeiro a miniatura armazenada e depois trocam pela renderização nítida. Os quadros seguinte e anterior são pré-carregados (exceto com a Economia de Dados ligada).
- Uma renderização que não consegue começar em 5 s é substituída pela miniatura por 60 segundos.

**Lupa de passagem da câmara escura.** Uma lupa redonda segue o cursor sobre o quadro principal, cada painel de comparação e os detalhes dos rostos, mostrando pixels em resolução total. Um botão da barra de ferramentas a liga ou desliga (ligada por padrão, salva por navegador). Ela pausa enquanto o quadro está ampliado além do ajuste, funciona em tela cheia e acompanha `←`/`→`.

### Selos por Rosto

No lightbox da triagem, cada rosto leva os seus próprios selos: olhos abertos/fechados, expressão ruim e confiança da detecção. Você vê qual rosto de uma foto de grupo tem os olhos fechados. Obtidos por grupo com `POST /api/culling-group/faces`.

**Painel de rostos.** Os recortes de rostos ficam verdes / laranja / vermelhos a partir das suas pontuações de olhos abertos e de sorriso.

- Os controles deslizantes de **Olhos** e **sorriso** ajustam o que conta como piscada ou expressão fraca. Começam em `face_detection.eyes_closed_max` e `face_detection.poor_expression_min` (ambos com padrão `4.0`).
- **Tamanho** (64–256 px, passos de 16, padrão `112px`) redimensiona os recortes. Os valores dos controles deslizantes são salvos por navegador.
- Depois de usar um controle deslizante com o mouse, as setas do teclado voltam à câmara escura (`←`/`→` quadro, `↑`/`↓` manter/rejeitar). Use Tab para chegar a um controle deslizante e ajustá-lo pelo teclado.

**Tira de detalhe do sujeito (grupos sem rostos).** Para grupos sem rostos significativos (vida selvagem, macro, produtos), a câmara escura mostra lado a lado o sujeito principal de cada quadro, recortado a partir da caixa de sujeito do BiRefNet. Cada recorte tem um selo de nitidez (10 = a mais nítida do grupo) e um anel verde / âmbar / vermelho. Clique em um recorte para ir a essa foto. Nenhum modelo roda (`POST /api/culling-group/subjects`). Para uma biblioteca existente, execute antes `python facet.py --recompute-saliency` (GPU); até então a tira não aparece.

**Sujeito-chave (alvo do zoom + pessoa-chave).** Ampliar (**`Z`**, duplo clique ou o primeiro passo da roda) leva ao sujeito-chave do quadro em vez do centro: o seu melhor rosto, ou a caixa de sujeito se não houver rosto. Quando você mesmo desloca ou amplia um quadro, o Facet para de reenquadrá-lo. Uma pessoa nomeada que vence recebe uma pílula de nome âmbar na tira de rostos. Pessoas nomeadas na meia distância vencem desconhecidos maiores; um rosto minúsculo ao fundo não vence. Nada é armazenado. As caixas são frações do quadro inteiro (`normalized_frame_xyxy`). Endpoints: `POST /api/photos/key_subjects`, `GET /api/photo/key_subject`.

**Comparação sincronizada (2-up / 4-up).** Os botões Único / Comparar 2 / Comparar 4 do cabeçalho alternam as visões. No modo de comparação, todos os painéis compartilham um único deslocamento/zoom, então você compara o recorte idêntico. O duplo clique alterna ajuste ↔ zoom. No ajuste, cada painel mostra `/thumbnail?size=1920`; ampliado, carrega o `/image` em resolução total. O gesto de pinça no toque ainda não está ligado; use a roda do mouse.

**Deslizar para manter ou rejeitar (toque).** Em um dispositivo de toque, arraste o quadro para a direita para manter ou para a esquerda para rejeitar. Ele se inclina e ganha tom verde (MANTER) ou vermelho (REJEITAR).

- Além de 35% da largura (pelo menos 48px), soltar efetiva a mesma decisão que `↑` / `↓` e passa ao quadro seguinte. Antes disso, ele volta.
- Um arrasto vertical é ignorado.
- Cada deslize mostra **Desfazer**, que restaura a decisão e volta a esse quadro.
- Apenas na visão única, na escala de ajuste, com um dedo ou caneta. Uma dica de uma linha aparece até ser dispensada.

**Prévia do visual editado.** Na visão única, o menu de **paleta** lista "Original" mais cada estilo darktable configurado, para você fazer a triagem sobre o visual revelado.

- O Facet renderiza o original pelo darktable-cli (`--style`, limitado a `preview_max_edge`). Em caso de falha, volta ao Original.
- O estilo permanece para o grupo atual e é redefinido quando você reabre a câmara escura.
- Aparece apenas quando um estilo está configurado **e** o darktable-cli é encontrado. Os estilos devem existir na configuração do darktable do usuário que executa o visualizador.
- As renderizações ficam em cache no disco.
- Endpoint: `GET /api/photo/cull_preview?path=&style=` (edição). Configure via [`raw_processor.darktable.cull_styles`](CONFIGURATION.md#decodificação-raw).

## Visão de Cenas

Uma visão **somente leitura** da biblioteca como cenas cronológicas, na ordem da história, com cabeçalhos de data/momento e uma lupa ao passar o cursor. Aberta a **todos os usuários autenticados**.

- Uma nova cena começa quando passam mais de `scenes.gap_minutes` entre as tomadas (ampliado em sessões esparsas). Sequências muito longas são divididas.
- Abra-a pela ação **Exibir cenas deste álbum** do álbum na grade de Álbuns; um seletor troca de álbum. Não há item Cenas na navegação principal.
- Cada cena tem um botão **Fazer a triagem desta cena**, só para edição, que abre a [Triagem](#triagem) nessa cena (`/culling?group_by=scene&album=&from=&to=`).
- Com os momentos narrativos calculados, cada cena recebe o título do seu momento principal, e `scenes.split_on_moment_change` pode dividir uma sequência onde o momento muda.
- Cenas menores que `scenes.min_size` são omitidas; no máximo `scenes.max_photos` fotos são carregadas.

Controlado por `viewer.features.show_scenes` (padrão: `true`). Veja [Configuração — Cenas](CONFIGURATION.md#scenes) para `gap_minutes`, `min_size`, `max_photos`, `max_scene_size`, `adaptive` e `adaptive_k`.

## Momentos Narrativos

O Facet rotula cada foto com a atividade que ela mostra. O vocabulário **geral** padrão: celebração, refeição, praia, atividade aquática, montanhas, natureza e vida selvagem, paisagem urbana, ponto turístico, show, esportes, reunião de grupo, retrato, crianças, animais de estimação, vida noturna, cerimônia, paisagem cênica, neve e inverno, interior doméstico, estrada e veículo, ou `other`. Um vocabulário `wedding` está disponível como gênero opcional.

- Roda localmente, sem passagem extra de modelo: a legenda de IA de cada foto é comparada com os prompts de texto de cada momento (o embedding da imagem é usado quando não há legenda). Um suavizamento da linha do tempo corrige leituras erradas isoladas.
- Um desempate opcional por VLM (16gb/24gb) reexamina os quadros de baixa confiança.
- **Roda automaticamente ao fim de cada varredura**. A primeira passagem sobre uma biblioteca existente codifica todas as legendas (GPU recomendada). Rotule tudo de novo com `python facet.py --recompute-moments`.
- Os momentos aparecem como títulos de cena e como filtro da galeria (`GET /api/photos?narrative_moment=beach`, opções de `GET /api/filter_options/narrative_moments`).
- O vocabulário é configurável — veja [Configuração — Momentos Narrativos](CONFIGURATION.md#narrative-moments).

**Confiança do momento.** Cada rótulo tem uma confiança (`narrative_moment_confidence`). Os rótulos abaixo de `viewer.moment_confidence_min` (padrão `0` = nunca esmaecer) aparecem esmaecidos com "(incerto)" nos cabeçalhos de Cenas e Triagem e na dica. A confiança também é uma ordenação (**Confiança do Momento**, em Conteúdo) e um filtro de intervalo 0–1 (`min_moment_confidence` / `max_moment_confidence`, seção **Momentos** da barra lateral).

## Limpeza de lixo

Uma fila de revisão rápida para capturas de tela, documentos digitalizados, recibos, memes e slides. Execute `python facet.py --detect-junk` (também roda após cada varredura) para preencher `junk_kind`. Veja [Configuração — Limpeza de lixo](CONFIGURATION.md#junk-sweep).

Abra **Limpeza** na navegação (`/junk`, somente edição):

- **Chips de filtro por tipo** — "Todos os tipos" mais um chip por tipo com a sua contagem (`GET /api/filter_options/junk_kinds`).
- **Contagem de candidatas** — diminui conforme você decide.
- **Manter** — retira a foto da fila **para sempre** (`not_junk`); as execuções seguintes de `--detect-junk` a ignoram.
- **Rejeitar** — marca a foto como rejeitada (nada é excluído).
- **Rejeitar todas as exibidas** — rejeita todas as candidatas carregadas, após confirmação.
- **Lupa** — pressione **`Z`** (ou o botão da barra de ferramentas) para ampliar textos pequenos.

As fotos de lixo continuam visíveis na galeria normal. Filtre-as com `?junk_kind=<kind>` ou `?junk_kind=any` (exclui `not_junk`).

Controlado por `viewer.features.show_junk_sweep` (padrão: `true`).

## Modo de Comparação Pareada

Classifique fotos julgando duas de cada vez; os votos alimentam o ajuste de pesos. Abra `/compare` (botão Comparar no cabeçalho). Exige uma `edition_password` não vazia (usuário único) ou o papel `admin`/`superadmin` (multiusuário).

### Aba Comparação A/B

Escolha um vencedor, marque um empate ou pule. Uma barra de progresso conta até 50 votos, com os totais de vitórias de A/vitórias de B/empates. Um filtro de categoria delimita a sessão; um menu de estratégia escolhe os pares:

| Estratégia | Descrição |
|----------|-------------|
| `learning` | Padrão. Pares diversos primeiro, depois os pares em que o ranqueador pessoal mais discorda (os mais informativos) |
| `uncertainty` | Fotos com pontuações semelhantes (as mais informativas) |
| `boundary` | Faixa de pontuação de 6–8 (zona ambígua) |
| `active` | Fotos com menos comparações (garante cobertura) |
| `random` | Pares aleatórios (linha de base) |

**Atalhos de teclado:**

| Tecla | Ação |
|-----|--------|
| `A` | A foto da esquerda vence |
| `B` | A foto da direita vence |
| `T` | Empate |
| `S` | Pular par |
| `Escape` | Fechar o modal de substituição de categoria |

### Aba Sugestões de Pesos

Compara os pesos aprendidos com os seus votos com os atuais, com a precisão do modelo antes/depois e as 10 melhores fotos agora vs. após o recálculo.

- **Aplicar** grava os pesos sugeridos; **Recalcular** repontua a categoria (ambos no modo de edição).
- **Aplicar** só aparece quando a sugestão supera os pesos atuais em comparações retidas (`suggest_changes`, o mesmo teste de `--optimize-weights`, veja [COMMANDS.md](COMMANDS.md)).
- Ao contrário de `--optimize-weights`, **Aplicar** não recentraliza o bônus da categoria, então a pontuação média dela pode variar.

### Aba Pesos

Um controle deslizante por métrica para a categoria selecionada, com uma prévia ao vivo da pontuação. **Salvar** grava o `scoring_config.json` (com um backup); **Recalcular Pontuações** o aplica; **Redefinir** recarrega os pesos armazenados.

### Aba Snapshots

Salve os pesos atuais como um snapshot nomeado e restaure qualquer um anterior. Um snapshot também restaura o bônus da categoria (`modifiers.bonus`). Os snapshots anteriores à 1.21, vindos de `calibrate.py` ou de `others` não trazem bônus e o deixam inalterado.

### Prioridade de Categoria e Contextos de Pontuação

As categorias são verificadas em ordem crescente de `priority`; a primeira que corresponde vence. Veja [Filter Evaluation](SCORING.md#como-a-pontuação-funciona) e [Contextos de Pontuação](CONFIGURATION.md#contextos-de-pontuação). Duas ferramentas, só para edição, mudam isso sem editar o `scoring_config.json`:

- **Prioridade global** — reordene a ordem base de avaliação.
- **Contextos de pontuação** — padrões (`default`, `action_stage`, `party_event`, `portrait_session`, `wildlife`, `landscape`, `motorsport`) que promovem algumas categorias e excluem outras, sem alterar a ordem global. Edite qualquer padrão que não seja `default` na aba **Contexto de Pontuação**: arraste (ou mova para cima/baixo) as categorias promovidas, alterne as exclusões, salve. Uma categoria listada em ambas vence como excluída. `label_key` e `suggest_from_moments` não são editáveis aqui. Atribua um contexto por álbum (veja [Contexto de Pontuação](#contexto-de-pontuação)) ou por foto (abaixo).

Nenhum dos dois repontua fotos por si só. Depois, execute um recálculo (`POST /api/scan/recompute`) e acompanhe `GET /api/scan/recompute_status`. Uma varredura ou recálculo já em execução a partir de um terminal bloqueia um novo no visualizador. Com `normalization.per_category` ligado, um recálculo pode não convergir totalmente — veja [Normalização](CONFIGURATION.md#normalization) e [Reordenar a prioridade global](CONFIGURATION.md#reordenando-a-prioridade-global).

**Colisões de categoria** (`GET /api/stats/categories/overlap`) mostra qual categoria de maior prioridade está capturando as fotos de uma categoria. Por categoria lista **Atribuídas**, **Correspondem aos filtros** (se avaliada isoladamente) e **Capturadas por prioridade maior** (`matched - assigned`, com piso em 0). **Principais pares em colisão** classifica as categorias por fotos compartilhadas. A categoria genérica `default` fica de fora, pois corresponde a tudo.

### Substituição de Categoria

Reatribua a categoria de uma foto pela visão de comparação: edite o selo de categoria, escolha uma categoria, execute "Analisar Conflitos de Filtro" para ver quais filtros a excluem e então aplique. A substituição é persistente: sobrevive a recálculos até você a limpar (`POST /api/comparison/override_category`, `POST /api/comparison/clear_category_override`).

O lightbox da foto tem as mesmas ações em **Definir categoria de pontuação…** / **Limpar substituição** (só edição). A seta no chip de categoria abre **por que isto não é outra categoria?**: escolha uma categoria e ele lista os filtros que excluem a foto e o que cada um precisaria, por exemplo *"Raise shutter_speed_max from 0.02 to 0.033"*. Isso aparece quando uma categoria é inalcançável para uma foto, o que reordenar não resolve (`POST /api/comparison/suggest_filters`).

## Estatísticas EXIF

A página Estatísticas (`/stats`) tem 5 abas. Os seletores de **categoria** e de **intervalo de datas** filtram todos os gráficos. No modo multiusuário, cada usuário vê as estatísticas das suas próprias fotos visíveis.

### Abas

| Aba | Descrição |
|-----|-------------|
| **Equipamento** | Corpos de câmera, lentes e combinações (as 20 principais de cada) |
| **Configurações de Captura** | Distribuições de ISO, abertura, distância focal, velocidade do obturador |
| **Linha do Tempo** | Fotos ao longo do tempo |
| **Categorias** | Análises por categoria, gerenciamento de pesos e correlações de pontuação |
| **Correlações** | Gráficos de correlação X/Y de métricas personalizados, com agrupamento |

### Aba Categorias

Quatro subabas:

| Subaba | Descrição |
|---------|-------------|
| **Detalhamento** | Contagens de fotos por categoria, pontuações médias, histogramas de distribuição de pontuação |
| **Pesos** | Comparação em gráfico de radar (até 5 categorias), mapa de calor de pesos e editor de pesos (modo de edição) |
| **Correlações** | Mapa de calor de correlação de Pearson mostrando como cada dimensão influencia a agregada, com visão de detalhe ao clicar |
| **Sobreposição** | Análise de sobreposição de filtros mostrando quais categorias compartilham fotos correspondentes |

Cada gráfico tem um botão `?` que explica como lê-lo; um alternador na barra de subabas mostra todas as explicações.

### Editor de Pesos (Modo de Edição)

Na subaba Pesos, com o modo de edição ligado:

1. Selecione uma categoria no menu suspenso
2. Ajuste os controles deslizantes de peso (um por métrica, devem somar 100%)
3. Use "Normalizar para 100" para equilibrar automaticamente
4. Expanda a seção Modificadores para ajustar bônus/penalidades
5. A **Prévia da Distribuição de Pontuação** mostra um histograma antes/depois ao vivo
6. Clique em **Salvar** para atualizar o `scoring_config.json` (cria um backup com data e hora)
7. Clique em **Recalcular Pontuações** (aparece após salvar) para aplicar os pesos a essa categoria

## Atalhos de Teclado (Galeria)

Os atalhos de uma tecla ficam inativos enquanto o foco está em um campo de texto, menu ou lista.

| Tecla | Ação |
|-----|--------|
| `←` `→` `↑` `↓` | Move o marcador de foto atual entre os cartões de foto (colunas da grade e linhas do mosaico) |
| `Enter` | Abre a foto em foco |
| `Space` | Seleciona / desseleciona a foto em foco |
| `Ctrl+A` / `Cmd+A` | Selecionar todas — toda a visualização filtrada a partir de uma seleção vazia, senão as fotos carregadas |
| `Escape` | Limpa a seleção (no modo de painel lateral, também libera a foto retida) / fecha a gaveta de filtros |
| `Shift+Click` | Seleciona o intervalo de fotos entre a última selecionada e a clicada |
| `Double-click` | Abre a foto |
| `Shift+F10` / `Menu` | Abre o menu de contexto do cartão de foto em foco (o clique direito faz o mesmo) |
| `1`–`5` | Avalia a foto em foco com 1–5 estrelas (modo de edição; avança sozinho para a foto seguinte) |
| `K` | Mantém a foto em foco (modo de edição) |
| `F` | Favorita / desfavorita a foto em foco (modo de edição) |
| `X` ou `0` | Rejeita / desfaz a rejeição da foto em foco (modo de edição; avança sozinho) |
| `/` | Foca a busca da barra de ferramentas (mostrada a partir de 1360 px de largura); em larguras menores, abre a busca da barra lateral de filtros |
| `S` | Abre o editor de pilhas para a seleção explícita (modo de edição; remapeável, pode ficar sem atribuição) |
| `Ctrl+Shift+S` / `Cmd+Shift+S` | Empilha de imediato a seleção explícita sem pilha pela ordem de seleção, com a primeira foto como capa (modo de edição; membros de pilhas existentes abrem o editor) |
| `B` | Mostra / oculta a barra lateral de filtros |
| `V` | Alterna entre o layout em grade e em mosaico |
| `?` | Mostra a referência de atalhos de teclado (em todas as páginas; também no menu do usuário → Ajuda) |

**Remapear teclas.** `K`, `F`, `X`, `/`, `B`, `V` e `S` são padrões. Menu do usuário → **Personalizar atalhos** permite clicar em uma ação e pressionar uma nova tecla (`Esc` ou `Tab` cancela). Dígitos, `Space` e `?` são reservados, e uma tecla já em uso é recusada. **Restaurar tudo** restaura os padrões. O mapeamento é salvo por navegador (`localStorage`). A página da foto usa as mesmas teclas, e a referência `?` sempre mostra as teclas em vigor.

**Foto atual.** A foto sobre a qual agem as teclas de avaliação, favorito e rejeição tem um contorno de 4px; os outros cartões esmaecem para 50%. Nada é marcado até você passar para uma foto. Clicar em uma foto leva o marcador até ela. Voltar de uma foto deixa o marcador na última que você viu. A dica do cartão em foco aparece apenas no modo de edição com `viewer.features.show_rating_controls` ligado.

**Na página da foto**, `1`–`5`, a tecla de favorito e a tecla de rejeição (`F` e `X` por padrão; `0` também rejeita) agem sobre a foto aberta, no modo de edição com `viewer.features.show_rating_controls` ligado. Não avançam; use `←` `→`. A referência `?` as lista em *Visão da foto*.

## Desfazer

As alterações em lote de favorito/rejeição/avaliação e as confirmações de triagem mostram uma barra de aviso com **Desfazer** por ~7 segundos.

- As alterações de marcadores em lote se aplicam na hora e são desfeitas revertendo-as (até 500 fotos).
- As confirmações de triagem são adiadas: o grupo some na hora, mas nada é salvo até o fim da janela de desfazer.
- As edições de [tags manuais](#tags-manuais) não podem ser desfeitas.

Para alterações mais antigas, veja o [Histórico de organização](#histórico-de-organização).

## Progressive Web App

Os builds de produção podem ser instalados na tela inicial. O shell do aplicativo carrega offline, e até 1000 miniaturas ficam em cache por 7 dias (tamanhos maiores, como as renderizações de 1920 px da câmara escura, dependem do cache do navegador). As respostas da API nunca ficam em cache, exceto os pacotes de tradução. Uma barra de aviso oferece recarregar quando uma nova versão é implantada.

> **Aviso:** encerrar a sessão limpa o cache de miniaturas do aplicativo, mas não o cache HTTP do navegador, que pode manter imagens vistas (miniaturas, renderizações, imagens em resolução total) por até um ano. Contas que não devem ver as fotos umas das outras não devem compartilhar um perfil de navegador.

## Mobile

Em telas pequenas, o cartão flutuante de seleção mantém a contagem e os botões de limpar, selecionar tudo e inverter, mais um botão **Ações**. Ele abre uma folha inferior com todas as operações em lote (favoritar, rejeitar, avaliar, álbuns, copiar, baixar). Um botão de comparar aparece quando a seleção cabe na visão de comparação.

## Moldura Digital / Endpoint de Quiosque

Molduras de fotos inteligentes, painéis do Home Assistant e telas no estilo ImmichFrame / Immich-Kiosk podem puxar as suas melhores fotos sem login. **Não há interface de cliente**: os dispositivos chamam os endpoints com um **token de moldura** de longa duração, do bloco de configuração `frame`. Com `frame.tokens` vazio (o padrão), o recurso fica desligado e todos os endpoints retornam 404.

- **O que é mostrado.** As fotos vêm de toda a biblioteca, não das pastas de um usuário. Fotos rejeitadas, de lixo e com piscadas são excluídas. `frame.min_aggregate` (padrão 7.0) define o piso de pontuação; `frame.favorites_only` e `frame.categories` restringem mais.
- **Variedade.** As fotos são uma amostra aleatória ponderada pela pontuação, então você vê boas fotos diferentes em vez das mesmas poucas.
- **Sem caminhos de arquivo.** Cada foto é endereçada por um id opaco assinado, de modo que quem tem um token não descobre onde estão os seus arquivos nem navega por outras linhas.

| Endpoint | Retorna | Cache |
|----------|---------|-------|
| `GET /api/frame/photos?token=&count=` | `{photos: [{id, caption?, date_taken?, width, height}]}` — `count` limitado a `frame.max_count` (padrão 100), com padrão `frame.count` (20) | — |
| `GET /api/frame/image/{id}?token=&max_edge=` | o JPEG da foto — original reduzido a `max_edge` (limitado por `frame.max_edge`, padrão 1920), ou a miniatura armazenada se o original estiver inacessível | imutável de longa duração |
| `GET /api/frame/next?token=` | um JPEG curado aleatório, diferente a cada chamada — para molduras simples e Home Assistant | `no-store` |

### Gerando um token

Um token é qualquer texto que você escolher. Use um aleatório e longo e trate-o como uma senha:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Adicione-o a `frame.tokens` no `scoring_config.json`. Liste um por dispositivo; remova um para revogá-lo:

```json
"frame": {
  "tokens": ["Xu8w…your-random-token…"],
  "count": 20,
  "min_aggregate": 7.0,
  "max_edge": 1920,
  "favorites_only": false,
  "categories": []
}
```

### Receita para o Home Assistant

`/api/frame/next` funciona como uma [câmera genérica](https://www.home-assistant.io/integrations/generic/) do Home Assistant; cada atualização puxa uma nova foto:

```yaml
camera:
  - platform: generic
    name: Facet Frame
    still_image_url: "http://facet.local:5000/api/frame/next?token=Xu8w…your-random-token…"
    verify_ssl: false
    framerate: 0.05  # atualiza a cada ~20 s
```

Adicione a câmera a um cartão Picture Glance / Picture Entity para obter uma moldura de fotos que se atualiza sozinha.

Para um cliente **no estilo ImmichFrame** que executa a própria apresentação, consulte `GET /api/frame/photos?token=…&count=30` para obter ids e então busque cada `GET /api/frame/image/{id}?token=…&max_edge=1920`. Os ids são estáveis e as imagens ficam em cache de longa duração, então cada foto é baixada uma única vez.

## Envio Automático do Telefone

Envie fotos do telefone para o Facet. Um pequeno servidor **WebDAV** em `/dav` permite que o PhotoSync (ou qualquer cliente WebDAV) envie para um **diretório de entrada**. Coloque o diretório de entrada dentro de um diretório varrido e execute `facet.py --watch` nele: cada foto é pontuada ao chegar.

- **Credenciais separadas.** O acesso usa HTTP Basic com um login de dispositivo compartilhado do bloco `upload` (`upload.username` / `upload.password`), não uma conta de usuário.
- **Desligado por padrão.** `/dav` retorna **404** até que `upload.username`, `upload.password` e `upload.inbox_dir` estejam todos definidos.
- **Confinado ao diretório de entrada.** Nada fora de `upload.inbox_dir` é alcançável. Os arquivos são limitados a `upload.max_file_mb` (padrão 500).
- **Métodos:** `OPTIONS`, `PROPFIND` (profundidade 0/1), `MKCOL`, `PUT`, `MOVE`, `DELETE`, `GET`, `HEAD`. `LOCK`/`UNLOCK` não são implementados; os aplicativos de envio funcionam sem eles.

### Configuração

```json
"upload": {
  "username": "phone",
  "password": "…a-long-random-shared-secret…",
  "inbox_dir": "/photos/inbox",
  "max_file_mb": 500
}
```

Mantenha `inbox_dir` sob um diretório varrido para que o `--watch` veja os envios:

```bash
python facet.py /photos --watch
```

### Receita para o PhotoSync

1. No PhotoSync, adicione uma configuração **WebDAV** (Configure → Add Configuration → WebDAV).
2. **URL / Servidor**: `http://<host>:5000/dav/` (`https://` atrás de um proxy reverso).
3. **Usuário / Senha**: o seu `upload.username` / `upload.password`.
4. **Pasta de destino**: a raiz (`/`) para o diretório de entrada, ou uma subpasta.
5. No host do Facet, monitore o diretório de entrada para que os envios sejam pontuados:

   ```bash
   python facet.py /photos --watch
   ```

### Teste rápido com curl

```bash
curl -T photo.jpg -u phone:'…a-long-random-shared-secret…' http://<host>:5000/dav/photo.jpg
```

`201 Created` (ou `204 No Content` ao sobrescrever) significa que o arquivo chegou ao diretório de entrada; o `--watch` o pontua logo depois.

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

### Limites das Listas Suspensas

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

Aumente `min_photos_for_person` para ocultar da lista suspensa de filtro as pessoas com poucas fotos.

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
      "hide_brackets": true,
      "hide_panoramas": true,
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

Execute estes comandos para um melhor desempenho:

```bash
python database.py --migrate-tags    # consultas de tags 10-50x mais rápidas
python database.py --refresh-stats   # Pré-calcula agregações
python database.py --optimize        # Desfragmenta o banco de dados
```

`--migrate-tags` é uma configuração feita uma única vez. Depois, as varreduras, `--recompute-tags`, `--recompute-tags-vlm` e `tag_existing.py` mantêm a tabela de tags atualizada. Até você executá-lo, os filtros de tags usam uma alternativa mais lenta.

Verifique o cache de estatísticas (vida útil de 5 minutos) com:

```bash
python database.py --stats-info
```

### Índices da Galeria e Cache de Contagem

O Facet adiciona índices que mantêm rápidas as páginas e contagens da galeria em bibliotecas grandes. Em uma biblioteca de 130 mil fotos, eles reduziram a página padrão de cerca de 1,2 s para 26 a 38 ms com a contagem em cache, e cerca de 104 ms logo após uma mudança no banco de dados.

- **Criados uma vez, em segundo plano.** A primeira inicialização do visualizador após uma atualização cria os índices que faltam enquanto ele já atende. Em uma biblioteca de 130 mil fotos, o maior índice levou de 45 a 55 s para ser criado e cerca de 106 a 111 MB de tamanho extra do banco de dados. Enquanto um índice é escrito, as gravações são brevemente recusadas com a mensagem "tente de novo em instantes". Uma varredura `python facet.py` ou uma execução de `python database.py` os cria antes. Veja [DEPLOYMENT.md](DEPLOYMENT.md#início-do-visualizador-e-índices-da-galeria) para gravações durante a criação, desligamento, `--workers N` e Docker.
- **As gravações ficam um pouco mais lentas**: cerca de 0,5 a 0,7 ms a mais por linha quando muda uma coluna que esses índices carregam.
- **Cache de contagem.** As contagens da galeria ficam em cache por 5 minutos. Qualquer mudança vinda de um processo no mesmo host (inclusive `--detect-junk` e `--recompute-*`) as atualiza. Uma mudança feita de outra máquina por um compartilhamento de rede aparece quando o cache expira.

## Endpoints da API

A referência da API HTTP está em [API.md](../API.md). A documentação interativa é servida em `/api/docs`.

## Fotos JPEG XL

O Facet varre JPEG XL (`.jxl`) com a dependência principal `imagecodecs`, incluída nas instalações padrão e no Docker. Nenhum pacote extra é necessário; as varreduras ignoram `.jxl` apenas se esse codec não estiver disponível.

- **Visualização.** Os navegadores que aceitam `image/jxl` recebem o arquivo original; os demais recebem um JPEG. As miniaturas da galeria são JPEGs.
- **Metadados.** Os originais permanecem `.jxl`. As edições de revisão vão para sidecars, não para dentro do arquivo.
- **Animações.** Só o primeiro quadro é usado.
- **Cor.** Um JXL que reconstrói um JPEG mantém o seu perfil ICC e as pré-visualizações são convertidas para sRGB. Para JXL nativo, o perfil de cor incorporado não está disponível, então as pontuações e pré-visualizações de arquivos de gama ampla ou HDR podem não ter exatidão de cor. Os downloads de originais mantêm a profundidade de bits e o perfil.
- **Limites.** A decodificação verifica o limite de pixels do Pillow antes de alocar pixels, e a inspeção do cabeçalho do contêiner para em 4 096 caixas. O EXIF codificado e o descomprimido são limitados a 16 MiB cada; um EXIF grande demais é descartado e a imagem continua legível. No máximo cinco conversões JPEG ficam em cache. Arquivos com layouts de canais extras não suportados são recusados.

## Solução de Problemas

| Problema | Solução |
|-------|----------|
| Carregamento lento de página | Execute `--migrate-tags` e `--optimize` |
| Filtros não aparecem | Verifique `--stats-info`, execute `--refresh-stats` |
| Filtro de pessoa vazio | Execute `--cluster-faces-incremental` |
| Botão Comparar ausente | Defina uma `edition_password` não vazia (usuário único) ou use o papel `admin`/`superadmin` (multiusuário) |
| Senha não funciona | Verifique `viewer.password` (usuário único) ou confira o hash da senha (multiusuário) |
| Usuário não vê fotos | Verifique `directories` na configuração do usuário e `shared_directories` |
| Botão Varrer ausente | Exige `viewer.features.show_scan_button: true` mais acesso à varredura — veja [Disparo de Varredura](#disparo-de-varredura) |
| A busca não retorna resultados | Garanta que as fotos tenham dados `clip_embedding` (execute a pontuação antes) |
| A busca diz que a aceleração do Apple Silicon está ocupada | Tente de novo quando a tarefa de modelo atual terminar |
| Crítica VLM indisponível | Exige o perfil 16gb/24gb, `viewer.features.show_vlm_critique: true` e uma sessão de edição |
| O mapa não mostra fotos | Execute `--extract-gps`; verifique se as fotos têm dados GPS no EXIF |
| As legendas não são geradas | Exige o perfil de VRAM 16gb/24gb para a legendagem por VLM |
| Linha do tempo vazia | Garanta que as fotos tenham valores em `date_taken` |
| Porta 5000 em uso | Execute `python viewer.py --port 5001` (ou defina `PORT=5001`). No macOS, o AirPlay Receiver usa a 5000: escolha outra porta ou desligue-o em Ajustes do Sistema → Geral → AirDrop e Handoff. |

### Revisar rostos manuais salvos

Encontre fotos cujos retângulos de rosto salvos precisam de verificação. Na aba Revisão da barra lateral da galeria, ative **Rostos manuais a rever** (editores). Abra o editor de rostos de uma foto e ajuste e salve, ou exclua, cada retângulo sinalizado. A foto então sai da lista. O filtro funciona em álbuns inteligentes e em seleções de toda a visualização, e aparece como um chip removível.

- A lista reflete a última varredura ou verificação do editor, não uma observação ao vivo de arquivos. As varreduras verificam fotos com marcas manuais mesmo com a detecção de rostos desligada.
- Abrir o editor reverifica o original e é a palavra final.
- As marcas carregadas por uma religação (`relink_unverified`) continuam sinalizadas até serem salvas de novo no editor.
- Revisar nunca altera os arquivos originais. As exportações e atualizações do banco de dados do visualizador mantêm o estado de revisão.

## Correção da data de captura

Corrija um relógio de câmera errado. No modo de edição, escolha **Corrigir data de captura** no ícone de calendário junto à data da foto, ou na barra de seleção da galeria. Até 1000 fotos visíveis, "Selecionar toda a visualização" incluído.

- **Deslocar em** (padrão): escolha **Mais cedo** ou **Mais tarde** e informe Dias, Horas, Minutos e Segundos. Padrão: 1 hora mais tarde. Os botões rápidos −1 h, +1 h, −1 d e +1 d somam ao deslocamento.
- **Definir hora exata**: informe a data e hora corretas de uma foto de referência (a foto aberta, ou a primeira foto com data da seleção; não para "Selecionar toda a visualização"). O deslocamento é derivado dela.
- O deslocamento deve ser diferente de zero e de no máximo ±366 dias.
- Um resumo indica o deslocamento ("1 h 30 min mais tarde"), e a prévia mostra as contagens de alteradas/ignoradas e os primeiros 20 carimbos de data antigos/novos.
- **Aplicar correção (N)** a aplica. Se algo mudou nesse meio-tempo, um erro oferece **Pré-visualizar** para atualizar.

**O que muda.**

- A hora da câmera é deslocada como está: sem lógica de fuso horário nem de horário de verão.
- Só são suportadas datas completas `YYYY:MM:DD HH:MM:SS` ou `YYYY-MM-DD[T ou espaço]HH:MM:SS`. Datas desconhecidas, só com a data, com fuso/subsegundos e inválidas são ignoradas.
- As datas corrigidas sobrevivem a novas varreduras e a exportações incrementais do banco de dados do visualizador.
- **Usar a data do arquivo** remove a correção e relê o arquivo. Sem data no arquivo, a data de captura fica desconhecida.
- Aplicar uma correção nunca grava o original nem altera o horário do arquivo. A exportação XMP grava `exif:DateTimeOriginal`; **Gravar metadados no arquivo** também atualiza o EXIF `DateTimeOriginal` nos formatos suportados.
- Os grupos de rajada e de sequência não são recalculados; execute a detecção de novo se precisar reagrupar.

Endpoints: `POST /api/photos/capture_date/preview`, `POST /api/photos/capture_date/apply`, `DELETE /api/photo/capture_date?path=` — veja [API.md](../API.md).

## Histórico de organização

Reveja e reverta as suas edições recentes em toda a biblioteca. No modo de edição, abra **Histórico de organização** pelo ícone de relógio na navegação principal (depois de Neste Dia). Expanda uma entrada para ver os valores exatos de antes/depois e então **Reverter esta entrada**.

- **O que é registrado:** GPS, datas de captura, decisões de revisão, estrelas, favoritos e pilhas manuais. Não arquivos nem reconhecimento facial.
- GPS e datas de captura são valores compartilhados da biblioteca. Decisões de revisão, estrelas e favoritos são seus.
- A lista curta de Desfazer e a de atividade do assistente são separadas.
- **Limites.** As últimas **50 entradas por conta**, cada uma com até **1000 fotos e 1 MiB** de valores. Ações de revisão filtradas maiores são divididas em partes; reverter restaura uma parte. A substituição de uma pilha pode cobrir até 2000 fotos em uma entrada.
- O histórico sobrevive a reinicializações e a atualizações incrementais do banco de dados do visualizador. Uma exportação nova/completa do visualizador começa vazia. Não é sincronizado com outro banco de dados.
- **Reverter é tudo ou nada.** É recusado se o valor de qualquer foto mudou desde então, mesmo que tenha voltado ao que era. A edição de revisão privada de outra conta não bloqueia a sua. Novas varreduras, importações e Desfazer também podem invalidar entradas mais antigas.
- Uma entrada fica oculta quando uma das suas fotos é excluída ou deixa de ser visível para você.
- Uma reversão adiciona a sua própria entrada e marca a original como revertida.

## Rostos sem nome

Encontre rostos não atribuídos e grupos de pessoas sem nome: `Filtros → Pessoas → Rostos sem nome` (`faces_need_names=true`). Use + para atribuir um rosto, ou dê um nome a um grupo em Pessoas. Fotos sem rostos detectados são excluídas.

Usuários somente leitura podem navegar por este filtro; atribuir ou nomear exige acesso de edição.

## Atribuindo pessoas

O seletor **Atribuir rosto à pessoa** lista primeiro até 12 pessoas que você atribuiu recentemente neste navegador (por identidade conectada). As demais pessoas nomeadas vêm depois, por contagem de rostos em fotos que você pode ver. A pesquisa e a paginação cobrem todos.

- Uma pessoa só se torna recente após uma atribuição ou gravação de rosto manual bem-sucedida.
- Apenas os IDs das pessoas são armazenados localmente. Encerrar a sessão limpa a lista.

## Atualizar metadados e pré-visualização

Releia os metadados de uma foto e reconstrua a sua pré-visualização sem uma nova varredura completa. Anotações manuais, avaliações, rostos e pontuações de IA permanecem. Os originais nunca são gravados. Escaneie de novo se pixels alterados precisarem de novas pontuações ou de detecção de rostos.

- Até 100 fotos selecionadas; seleções de toda a visualização não são suportadas.
- Valores de origem ausentes não limpam os armazenados. Sem `exiftool`, apenas a pré-visualização é atualizada.
- GPS e datas manuais são mantidos.
- É recusado enquanto outro trabalho da biblioteca está em execução; tente mais tarde.
- Cada foto é salva separadamente; tentar de novo processa as que falharam.
- Até a próxima nova varredura, os histogramas usam a nova pré-visualização e a busca por similaridade de cor ignora a foto.
