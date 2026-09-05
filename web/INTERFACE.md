# Interface NÓRIA — o que foi construído

Aplicação de página única em JavaScript puro (ES modules), sem build, servida pela própria
API em `http://localhost:5200` (FastAPI monta `web/` como StaticFiles).
Todo número exibido vem de uma rota da API. Não existe dado de exemplo em nenhuma tela.

## Arquivos

| Arquivo | Papel |
| --- | --- |
| `index.html` | Casca, fontes (Cabinet Grotesk + Satoshi via Fontshare, JetBrains Mono), carrega `js/ofx.js` e `js/app.js` |
| `css/tokens.css` | **Não alterado** (paleta e tokens da identidade) |
| `css/app.css` | 756 linhas escritas do zero, só com variáveis de `tokens.css` |
| `js/api.js` | Cliente HTTP: sessão por cookie, tradução de erro do FastAPI em frase legível, 401 → tela de login |
| `js/fmt.js` | Dinheiro `R$ 1.964.842,57`, data `10/08/2026`, data-hora, número, duração, rótulos de estado |
| `js/ui.js` | Fábrica `el()`, métrica, painel, etiqueta, estado vazio, tabela, tolerância a campo ausente |
| `js/app.js` | Roteador por hash, menu lateral, tema claro/escuro, rodapé de resumo, poll de eventos (4 s) |
| `js/telas/*.js` | As 8 telas |
| `js/abertura.js`, `abertura-teste.html`, `js/ofx.js` | **Não alterados** |

Removidos por serem do sistema anterior: `js/data.js`, `js/boot.js`, `js/grafo.js`,
`js/especialistas.js`, `js/arquivos.js`, além das versões antigas de `app.js` e `app.css`.
Nenhuma referência ao nome antigo restou no código (`rg -i cortex` volta vazio).

## Telas

1. **Visão geral** (`#/visao`) — 4 métricas do `/api/panorama`, últimas missões clicáveis,
   missões por estado, integrações resumidas e o fluxo de eventos ao vivo.
2. **Cérebro** (`#/cerebro`) — estado do núcleo, consultas e tempo medido em ferramenta,
   evidências ligadas, o ciclo objetivo → encerramento com marcação de "sem registro"
   nas etapas que não têm rastro real, e o **grafo de execução** da última missão
   (núcleo → tarefas → validação), com a nota de que ele não é o mapa de conhecimento.
3. **Missões** (`#/missoes`) — criação inline (objetivo em texto livre), filtro por estado,
   lista com origem/prioridade/datas.
4. **Detalhe da missão** (`#/missoes/<id>`) — critérios aprovados, tarefas com tentativas,
   conclusão do núcleo, as 6 camadas de validação, achados e artefatos para baixar.
   Aqui as tarefas e dependências aparecem como lista, não como grafo — o grafo está no Cérebro.
5. **Entregas** (`#/entregas`) — cada afirmação com o seu lastro (origem, raiz, consulta,
   trecho que sustenta), incertezas declaradas e o JSON cru em `<details>`. Lotes de 5.
6. **Agentes** (`#/agentes`, `#/agentes/<id>`) — habilitados separados dos sem integração,
   com a limitação escrita por extenso em cada um que não pode operar.
7. **Conhecimento** (`#/conhecimento`) — leitura local de OFX/CSV pelo parser do próprio
   projeto (nada sai do navegador) e o acervo de artefatos que o núcleo gerou.
8. **Aprovações** (`#/aprovacoes`) — fila de ação externa; hoje vazia, dito com clareza.
9. **Integrações** (`#/integracoes`) — estado real por conexão, com botão de teste que
   consulta o destino de verdade. Nada não configurado aparece em verde.

## Regras de exibição respeitadas

- Número sem origem na API não entra na tela; onde a rota não existe, a tela diz que não existe
  (é o caso do índice semântico de conhecimento — não há `/api/conhecimento` implementada).
- Integração não configurada usa cor de atenção e mostra o motivo (`credencial não fornecida`,
  `remetente não configurado`). Agente sem executor aparece como "sem integração".
- Estado vazio é sempre escrito, nunca preenchido com exemplo.
- Dinheiro e data em formato brasileiro, inclusive centavos (`R$ 1.329.640,05`).
- Tema claro e escuro conferidos por captura; `prefers-reduced-motion` respeitado; foco visível.
- Abertura roda uma vez por sessão (`sessionStorage['noria.abertura']`).

## QA visual feito

Playwright, capturas em `web/_qa/` (35 imagens): 1500x940 e 390x860, tema escuro e claro,
em todas as telas, mais o menu lateral aberto no celular. Corrigido a partir das imagens:

- Satoshi não carregava (a URL combinada do Fontshare devolvia General Sans) → dois `<link>`.
- Acento de "NÓRIA" cortado no logotipo (`line-height: 1` → `1.25`).
- Erro cru de validação do FastAPI aparecendo na tela → virou frase; `#/missoes/abc` agora dá
  estado vazio em vez de erro.
- Detalhe da missão despejava JSON gigante → tabela genérica (10 linhas, "Mostrando 10 de N",
  colunas de código em mono sem separador de milhar).
- Centavos perdidos em valores vindos como número.
- Botão "Abrir missão" quebrando em duas linhas.
- Zona de arrastar arquivo com borda partida (label inline → block).
- Cabeçalho no celular: título com reticências, chip do usuário escondido, botões só com ícone.
- Botão de menu aparecendo no desktop (`.btn` sobrescrevia `.botao-menu`).

## Pendências e pontos fracos, honestamente

- **Mapa de conhecimento não existe como visual.** A API não expõe rota de índice semântico,
  então a tela Conhecimento entrega importação de arquivo e acervo de artefatos. O mapa
  (distinto do grafo de execução) fica pendente de rota no backend.
- **Aprovações nunca foi vista com dado.** O banco tem 0 pendências; o fluxo de aprovar/recusar
  está codificado contra o contrato, mas não foi exercido de ponta a ponta.
- **Poll em vez de stream.** `GET /api/eventos?desde=<id>` a cada 4 s; sem SSE/WebSocket.
- **Tela de missão em curso não testada com execução viva.** Não havia missão em andamento
  durante o desenvolvimento (0 em curso); o progresso por tarefa foi validado só com missões
  já encerradas.
- **Cache do navegador.** `index.html` referencia CSS/JS sem versão; depois de editar arquivos
  o navegador pode servir a versão antiga (aconteceu no QA). Vale adicionar `?v=` nos links
  ou cabeçalho `Cache-Control` na API antes de usar isso em produção.
- **Sem testes automatizados** de interface — a verificação foi visual.
- A visão geral tem espaço vazio no painel "Missões por estado" quando quase todas as missões
  estão no mesmo estado; funciona, mas o equilíbrio visual ali não ficou ótimo.
