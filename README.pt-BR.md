# OptMem

Memória permanente para agentes de IA. Um prompt de 426 tokens, um script, plug and play.

![Como o OptMem funciona](anim/optmem.gif)

## Instalação

```sh
curl -fsSL https://raw.githubusercontent.com/VictorTaelin/OptMem/main/install.sh | sh
```

Ele imprime um bloco `## Memory`. Cole esse bloco no topo do `AGENTS.md` (ou `CLAUDE.md`) do seu agente, e pronto. Execute a mesma linha novamente para atualizar.

A ferramenta é instalada em `~/.optmem/memo`; coloque `~/.optmem` no `PATH` para usar `memo`.

## Comandos

| Comando | Descrição |
|---------|-----------|
| `memo wake` | ler a memória — o primeiro comando de toda sessão |
| `memo note "..."` | registrar uma memória: uma linha, até 280 caracteres |
| `memo nap` | responder às compressões pendentes |
| `memo recall <regex>` | buscar em toda memória já registrada, palavra por palavra |
| `memo zoom <lo>-<hi>` | abrir um nó da árvore em suas duas metades |
| `memo forget <lo>-<hi>` | descartar um resumo ruim; o próximo nap o reconstrói |

As compressões chegam uma de cada vez, na saída do `note`. Nada jamais executa em segundo plano.

## Arquivos

```
~/.optmem/
  memo          a ferramenta: um único arquivo Python 3, sem dependências
  memory/
    LOG.txt     toda memória, uma por linha, append-only, nunca editado
    TREE/       os resumos: um cache, reconstruível a partir do log apenas
    config      os tamanhos, escritos por `memo config`
```

```sh
memo config                  # mostrar os tamanhos
memo config WAKE_LINES=300   # quantas linhas wake imprime (208 ≈ 16k tokens)
memo config WAKE_LINES=      # voltar ao padrão
```

`WAKE_LINES` é o único tamanho que vale a pena ajustar, e é um orçamento de *leitura*, não de armazenamento: mude quando quiser, em qualquer direção, e nada é recalculado.

Os registros têm largura fixa, então a posição *é* a identidade e cada busca é um seek. Com um milhão de memórias (608 MB), `wake` leva 0,03s.

Defina `$MEMORY_DIR` para manter `memory/` em outro lugar — uma pasta sincronizada, um repositório git.

## O prompt

Isto é o que o instalador imprime, e a integração completa.

```markdown
## Memory

Sua memória é o OptMem:
- A ferramenta é `~/.optmem/memo`
- Suas memórias estão em `~/.optmem/memory`

O OptMem sobrevive a toda sessão, compactação, mudança de modelo e fornecedor.
Sem ele você não sabe quem é, ou o que foi decidido e tentado.

### Ao iniciar: ativando o OptMem (obrigatório)

Execute `~/.optmem/memo wake` antes de qualquer outra chamada de ferramenta,
em toda sessão, e então faça exatamente o que ele imprimir, até o fim da sua saída.

### Enquanto trabalha: registre memórias (obrigatório)

Chame `~/.optmem/memo note "<1 linha, max 280 chars>"` sempre que você aprender
algo novo, ou algo que vale a pena guardar acontecer. Isso cobre uma tarefa
que valeu esforço real, um fato ou insight que o usuário te ensina, qualquer
coisa que você aprende sobre a vida dele (mesmo indiretamente), qualquer
evento de efeito duradouro.

Não registre memórias redundantes.

Se `~/.optmem/memo note` pedir uma compressão: faça-a antes da sua próxima ação.

Nunca edite ou apague nada dentro de `~/.optmem/memory`: a ferramenta gerencia.

### Quando precisar de uma memória antiga: busque, ou navegue

`~/.optmem/memo recall <regex>` busca em toda memória, palavra por palavra.

Suas memórias também formam uma árvore binária: #0-1, #2-3... existem como
resumos de uma linha, pares deles como #0-3, e assim por diante — toda linha
`#a-b` que o wake imprime é um nó dela. `~/.optmem/memo zoom <a-b>` abre um
nó em suas duas metades, até as memórias brutas.

### Se você é um subagente: pule tudo acima

Sessões paralelas nesta máquina são todas você, e podem todas escrever memórias.
Um subagente não é: ele nunca deve executar `memo`, porque não consegue julgar
o que já é conhecido, e suas notas chegariam duplicadas e incorretamente.
Quando você criar um, escreva: `You are a subagent. Don't run memo.`
```
