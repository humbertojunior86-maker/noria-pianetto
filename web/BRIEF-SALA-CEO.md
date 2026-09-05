# Briefing — Sala do CEO

## O pedido, nas palavras do dono da empresa

> "Senti falta da tela do CEO que observa tudo acontecendo e sua equipe de
> agentes trabalhando e os grandes números"

Três coisas, nesta ordem de importância:

1. **Os grandes números** — o dinheiro real da Pianetto, em tipografia grande,
   legível de longe. Esta tela vai ficar aberta numa TV na sala dele.
2. **A equipe de agentes trabalhando** — os 15 agentes visíveis ao mesmo tempo,
   cada um com o que fez e se está trabalhando agora.
3. **Tudo acontecendo** — a operação em movimento, ao vivo.

Ele é CEO de transportadora, não analista de dados. A tela responde
"está tudo de pé?" em três segundos, sem ele clicar em nada.

## Onde entra

- Arquivo novo: `web/js/telas/ceo.js`
- Registrar em `web/js/app.js`:
  - Em `TELAS`, como **primeiro item**, antes de `visao`:
    `{ id: 'ceo', rotulo: 'Sala do CEO', icone: 'visao', grupo: 'Operação', carregar: () => import('./telas/ceo.js') }`
  - Em `TITULOS`: `ceo: ['Sala do CEO', 'A empresa inteira num olhar, com a hora de cada número']`
  - Trocar a rota padrão para `ceo` (hoje cai em `visao`) — procure onde o hash
    vazio é resolvido em `rotaAtual()`.
- Em `web/js/api.js`, acrescentar:
  `export const ceo = (forcar) => pedir('/ceo' + (forcar ? '?forcar=true' : ''));`
- Ícone: se `icone('visao')` não servir, acrescente um novo em `web/js/ui.js`
  seguindo o padrão dos existentes (traço, sem preenchimento).

## A API

`GET /api/ceo` → devolve exatamente esta forma (valores reais de agora):

```json
{
  "empresa": { "nome": "PIANETTO TRANSPORTES E LOGISTICA LTDA", "cnpj": "43.976.512/0001-09" },
  "erp": {
    "pulso": { "linhas": [{ "ctes_hoje": 68, "receita_hoje": 354499.45,
                            "ctes_mes": 737, "receita_mes": 3796215.92,
                            "ctes_12m": 37337, "receita_12m": 219384666.55 }],
               "consultada_em": "2026-09-05T14:20:11-03:00" },
    "carteira": { "linhas": [
        { "id_tipo": 1, "qt": 4192, "aberto": 20425127.91, "qt_vencido": 2719, "vencido": 10969591.15 },
        { "id_tipo": 2, "qt": 6207, "aberto": 55051686.68, "qt_vencido": 856,  "vencido": 1801820.55 }],
      "consultada_em": "..." },
    "concentracao": { "linhas": [
        { "raiz": "35825580", "nome": "MOTZ TRANSPORTES LTDA - SC", "receita": 84898377.43, "pct": 38.7 },
        { "raiz": "40181584", "nome": "ADAPTA", "receita": 17087574.42, "pct": 7.79 }],
      "consultada_em": "..." },
    "serie": { "linhas": [{ "mes": "2025-09", "qt": 2755, "receita": 15465548.02 }, "... 13 meses ..."],
               "consultada_em": "..." }
  },
  "lido_em": "2026-09-05T14:20:11-03:00",
  "equipe": [
    { "codigo": "tesouraria.conciliador", "nome": "Marta", "papel": "Conciliadora de tesouraria",
      "area": "Tesouraria", "situacao": "habilitado", "limitacao": null,
      "tarefas": 9, "trabalhando_agora": false, "ultima_vez": "2026-09-05T13:50:58-03:00" }
  ],
  "operacao": {
    "em_curso": [{ "id": 12, "objetivo": "...", "estado": "executando", "criada_em": "..." }],
    "concluidas_hoje": 11, "evidencias_hoje": 20, "consultas_hoje": 29,
    "reprovacoes_abertas": 0, "aprovacoes_pendentes": 0
  },
  "gerado_em": "..."
}
```

**id_tipo 1 = a receber. id_tipo 2 = a pagar.** Não inverta — já errei isso uma vez.

Qualquer bloco de `erp` pode vir `{ "erro": "...", "linhas": [] }` se a consulta
falhar. Nesse caso mostre o motivo escrito no lugar do número, nunca um zero.
**Zero inventado é pior que buraco assumido.**

O servidor guarda os números do ERP por 60 s. Recarregue a tela a cada 60 s
sozinho. O botão "Reler agora" chama `api.ceo(true)`.

## O que a tela mostra

### 1. Faixa dos grandes números (topo, o que se lê da porta)

Quatro números em tipografia enorme (`--text-hero` ou maior, 48–64px):

| Número | Fonte | Apoio embaixo |
|---|---|---|
| **Receita 12 meses** | `pulso.receita_12m` | `pulso.ctes_12m` CT-es · ticket médio |
| **Faturado no mês** | `pulso.receita_mes` | `pulso.ctes_mes` CT-es · comparado ao mesmo dia do mês anterior, se der |
| **A receber em aberto** | `carteira` id_tipo 1 `aberto` | `qt` títulos · **`vencido` em vermelho com o %** |
| **A pagar em aberto** | `carteira` id_tipo 2 `aberto` | `qt` títulos · `vencido` |

Hoje (`receita_hoje` / `ctes_hoje`) vai numa linha viva acima ou ao lado,
menor, com um ponto pulsando: "hoje, até agora: 68 CT-es · R$ 354.499,45".

Use `f.dinheiro()` e `f.numero()` de `./fmt.js` — já estão em padrão brasileiro.
Para os números gigantes, considere abreviar (R$ 219,4 mi) **com o valor exato
no `title` e escrito por extenso logo abaixo em corpo pequeno**. O CEO precisa
do número redondo para pensar e do exato para conferir.

### 2. A curva do faturamento

Gráfico de barras ou área com os 13 meses de `serie.linhas`. Sem biblioteca
externa: SVG escrito à mão, como o resto do sistema. O último mês está em curso
— marque como parcial (barra vazada / hachurada), senão parece queda de 83%.
Rótulo do mês em `mmm/aa`. Ao passar o mouse, valor e quantidade.

### 3. Risco de concentração

`concentracao.linhas`. Uma barra horizontal empilhada dos 8 grupos + "demais",
e a lista com nome, receita e %.

O primeiro é o **Grupo MOTZ com 38,7% de toda a receita**. Isso é o maior risco
estrutural da empresa e a tela deve dizer isso com todas as letras, em tom de
alerta (`--atencao` acima de 25%, `--erro` acima de 35%): "38,7% da receita vem
de um cliente só. Se ele sair, sai um terço da empresa."

### 4. A equipe de agentes (o coração da tela)

Os 15 agentes de `equipe` numa grade, todos visíveis sem rolar dentro do bloco.
Cada cartão:

- Inicial ou monograma do nome num círculo
- **Nome** (Marta, Otávio…) e o papel embaixo, menor
- Área
- Estado com sinal claro:
  - `trabalhando_agora: true` → ponto pulsando em `--acento`, "trabalhando agora"
  - `habilitado` → ponto sólido `--ok`, "de prontidão · N tarefas · última há X"
  - `sem_integracao` → apagado, `--tinta-4`, e a `limitacao` escrita
- Os habilitados vêm primeiro (a API já ordena assim)

Os 13 sem integração **não são erro nem enfeite** — são o mapa do que falta
construir. Deixe isso legível, não escondido. Um contador honesto no cabeçalho
do bloco: "2 de 15 operando · 13 esperando integração".

Tempo relativo ("há 4 min") é melhor que carimbo aqui. Escreva um ajudante
pequeno no próprio arquivo se `fmt.js` não tiver.

### 5. A operação acontecendo

- **Missões em curso** (`operacao.em_curso`): se houver, cada uma com estado e
  há quanto tempo. Se vazio, uma frase honesta e tranquila: "Nenhuma missão em
  curso. As próximas abrem sozinhas amanhã às 6h30."
- **O dia em números**: `concluidas_hoje`, `evidencias_hoje`, `consultas_hoje`,
  `reprovacoes_abertas`, `aprovacoes_pendentes`. Reprovações e aprovações
  pendentes acima de zero ficam em `--atencao`/`--erro` e viram link para a tela
  correspondente.
- **Fluxo ao vivo**: reaproveite o pulso de eventos que a tela `cerebro.js` já
  usa (`api.eventos(desde)`), últimos 8, com hora. Copie o padrão de lá, não
  invente outro.

## Regras que não se negociam

1. **Nada de número inventado.** Tudo vem da API. Sem dado, escreva o motivo.
2. **Todo número carrega a hora em que foi lido.** Um rodapé por bloco ou um
   carimbo no topo: "números do ERP lidos às 14:20:11". É a regra da casa e é o
   que diferencia a NÓRIA de um dashboard qualquer.
3. **Não altere** `css/tokens.css` nem `js/abertura.js`.
4. Use os tokens existentes. Fundo `--painel`, tinta `--tinta`/`--tinta-2`,
   `--acento` (#50D6BC) só para o que importa, `--ok`, `--atencao`, `--erro`.
   O acento não pode virar tinta de parágrafo.
5. **Tema claro tem que funcionar** (`[data-tema="claro"]`). Nada de cor fixa
   escrita à mão; só variável.
6. Responsivo: em 390px vira uma coluna, os grandes números continuam grandes.
7. Português do Brasil em tudo, inclusive comentário de código. Sem emoji.
8. CSS novo vai no fim de `css/app.css`, com um comentário separando a seção.
   Prefixe as classes com `ceo-` para não colidir.
9. Comentário de código explica **por que**, não o quê.
10. Limpe o intervalo de recarga quando a tela sair (o padrão das outras telas
    já faz isso — siga).

## Como saber que ficou bom

Abra `http://localhost:5201`, entre com `humbertojunior86@gmail.com` /
`pianetto`, e verifique com Playwright em 1500×940 e 390×860, **nos dois temas**:

- Os quatro grandes números aparecem legíveis de longe e batem com a API
- Os 15 agentes cabem na tela sem rolagem interna
- O alerta do MOTZ está visível e alarmante
- Nenhum texto quebrado, cortado, ou vazando
- Nenhum erro no console
- Alternar tema não quebra nada

Salve as capturas em `web/_qa/ceo-*.png`.

Ao terminar, relate: o que ficou pronto, o que **não** conseguiu fazer e por
quê. Não maquie. Buraco assumido é informação; buraco escondido é defeito.
