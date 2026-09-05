# Brief — Interface da NÓRIA

Construir a interface completa da NÓRIA ligada à API real. Tudo em pt-BR.

## O que já existe (NÃO refazer, NÃO alterar)

- `web/css/tokens.css` — sistema de design completo. Use SÓ estes tokens.
  Sem cor literal nova no CSS. Tem tema claro em `[data-tema="claro"]` e
  `prefers-reduced-motion`.
- `web/js/abertura.js` — módulo ES. `abertura(el, aoTerminar)` e `pular()`.
  É a animação de inicialização. Chame no primeiro carregamento da sessão.
- `web/abertura-teste.html` — página de teste da abertura, mantenha.
- `web/js/ofx.js` — parser OFX (`window.NoriaOFX`), 846 linhas, funciona.
  Reaproveite na tela de Conhecimento/arquivos. Não reescreva.
- `IDENTIDADE.md` — decisões de marca.
- `ARQUITETURA.md` — contrato completo.

## O que APAGAR

`web/js/data.js` inteiro. É dado fictício. Nenhuma tela pode ler dele.
Se um número não vem da API, ele não aparece na tela.

## API

Base `/api`. Servidor de desenvolvimento já roda em `http://localhost:5200`
(uvicorn, `api.main:app`), servindo `web/` na raiz. Reinicie com o pplx-tool
`start_server` se precisar.

Login: `POST /api/entrar {email, senha}` → `{token, usuario}`.
Guarde o token e mande `Authorization: Bearer <token>` em tudo.
Credencial de teste: `humbertojunior86@gmail.com` / `pianetto`.

Rotas: `GET /api/eu`, `GET /api/panorama`, `GET /api/missoes`,
`POST /api/missoes {objetivo, contexto}`, `GET /api/missoes/{id}`,
`GET /api/missoes/{id}/entregas`, `POST /api/missoes/{id}/avancar`,
`POST /api/missoes/{id}/cancelar`, `GET /api/agentes`, `GET /api/agentes/{id}`,
`GET /api/eventos?desde=`, `GET /api/execucoes`, `GET /api/artefatos`,
`GET /api/artefatos/{id}/baixar`, `GET /api/aprovacoes`,
`POST /api/aprovacoes/{id}`, `GET /api/integracoes`,
`POST /api/integracoes/{id}/testar`, `GET /api/evidencias/{id}`.

Leia os campos exatos chamando as rotas. `GET /api/docs` tem o schema.

## Telas (menu lateral ~232px, cabeçalho ~64px)

1. **Visão geral** — panorama. Missões por estado, agentes habilitados vs sem
   integração, integrações com estado REAL, aprovações pendentes, achados
   abertos (validações reprovadas), últimas missões. Fluxo de eventos ao vivo
   (poll `GET /api/eventos?desde=<ultimo_id>` a cada 4s).
2. **Cérebro** — o núcleo em operação. Mostre o ciclo real: interpretação →
   plano → despacho → execução → validação em 6 camadas → conclusão. Alimente
   com eventos e execuções reais. Deve ficar lindo e legível, é a tela que o
   CEO abre. Nada de números decorativos.
3. **Missões** — lista + criação (campo de objetivo em texto livre) + detalhe.
   No detalhe: plano, tarefas com estado, critérios com resultado, tabela das
   6 camadas de validação, eventos em ordem, artefatos para baixar.
4. **Entregas** — cada entrega com resumo, afirmações e o lastro de cada uma
   (origem, trecho, data de consulta). Afirmação com `natureza != "fato"`
   aparece marcada como hipótese, nunca escondida. Sem evidência → diga isso.
5. **Agentes** — os 15. Habilitados e "sem integração" no mesmo lugar, e o
   sem integração mostra a limitação escrita. Nada de bolinha verde falsa.
6. **Conhecimento** — importação de arquivos com o parser OFX existente,
   e leitura de documentos indexados quando houver.
7. **Aprovações** — ações aguardando decisão, com o conteúdo exato e o botão
   de aprovar/ajustar/rejeitar. Tela vazia por enquanto: faça o estado vazio
   dizer "nenhuma ação aguardando decisão", não invente linhas.
8. **Integrações** — estado real de cada uma, botão testar.

## Regras que não se negociam

- Número sem origem na API não entra na tela.
- Integração desconectada nunca aparece verde.
- Estado vazio é escrito com clareza, nunca preenchido com exemplo.
- Dinheiro no formato brasileiro: `R$ 1.964.842,57`.
- Data no formato `10/08/2026`.
- O grafo de execução (o que rodou) é diferente do mapa de conhecimento
  (o que se sabe). Não misture os dois numa tela só.
- Tema claro funcionando. Movimento reduzido respeitado.
- Teclado: foco visível em tudo que é clicável.

## Qualidade

Screenshots com Playwright via pplx-tool `js_repl` em 1500×940 e 390×860,
tema escuro e claro, em CADA tela. Corrija texto quebrado, estouro, contraste
baixo. Só entregue depois de olhar as imagens.

Escreva o resumo do que foi feito em `web/INTERFACE.md`.
