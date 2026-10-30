# Last.fm Scrobbler para YouTube Music

Sincroniza automaticamente o histórico de reproduções do **YouTube Music** com o **Last.fm**, rodando **de hora em hora** no **GitHub Actions**, sem depender de um computador ligado.

## Sumário

- [Visão geral](#visão-geral)
- [Pré-requisitos](#pré-requisitos)
- [Instalação local](#instalação-local)
- [Configuração do Last.fm](#configuração-do-lastfm)
- [Configuração do YouTube Music](#configuração-do-youtube-music)
- [GitHub Actions](#github-actions)
- [Operação](#operação)
- [Decisões técnicas](#decisões-técnicas)
- [Limitações conhecidas](#limitações-conhecidas)
- [Troubleshooting](#troubleshooting)
- [Testes e qualidade](#testes-e-qualidade)

## Visão geral

### Objetivo

O YouTube Music não envia scrobbles ao Last.fm. Este projeto lê o histórico da sua conta, identifica o que foi tocado desde a última sincronização e envia essas reproduções ao Last.fm, evitando duplicações entre execuções.

### Como funciona a sincronização

1. O estado da última sincronização é restaurado (um artifact do GitHub Actions).
2. A sessão do Last.fm é validada antes de qualquer alteração.
3. O histórico do YouTube Music é lido com o `ytmusicapi` (cerca de 200 itens mais recentes).
4. O histórico atual é comparado com o *snapshot* salvo na execução anterior para descobrir o que é novo (ver [Controle de duplicações](#controle-de-duplicações)).
5. Entradas inválidas são descartadas (sem título, sem artista, podcasts, vídeos de usuários, faixas de até 30 segundos).
6. Cada reprodução nova recebe um **horário estimado** (o YouTube Music não informa horários; ver [Horários estimados](#horários-estimados)).
7. O novo estado (snapshot + fila de envio) é gravado **antes** do envio.
8. Os scrobbles são enviados ao Last.fm em lotes de até 50, do mais antigo para o mais recente. Após cada lote aceito, o estado é gravado novamente.
9. O estado é salvo como artifact para a próxima execução e um resumo é exibido no log.

### Tecnologias

| Item | Uso |
| --- | --- |
| Python 3.14 | Linguagem |
| [`ytmusicapi`](https://ytmusicapi.readthedocs.io/) 1.12.3 | Leitura do histórico do YouTube Music |
| [`pylast`](https://github.com/pylast/pylast) 7.2.0 | Autenticação e chamadas à API do Last.fm |
| `python-dotenv` | Carrega o `.env` em execuções locais |
| `truststore` | Usa o repositório de certificados do sistema operacional nas conexões HTTPS |
| `tzdata` | Base de fusos horários (necessária no Windows) |
| GitHub Actions | Agendamento, segredos e persistência do estado (artifacts) |
| `pytest` e `ruff` | Testes e verificação de qualidade (somente desenvolvimento) |

### Fluxo de execução automática

```
schedule (minuto 17 de cada hora) ou execução manual
  └─ checkout → Python 3.14 → pip install -r requirements.txt
       └─ restaura o artifact "sync-state" mais recente (se existir)
            └─ python -m scrobbler --state-file state/state.json [--dry-run]
                 └─ salva state/state.json como novo artifact "sync-state" (exceto em dry-run)
```

### Estrutura do projeto

| Arquivo | Responsabilidade |
| --- | --- |
| `scrobbler/__main__.py` | CLI (`python -m scrobbler`), logging, carregamento do `.env` e tratamento de erros |
| `scrobbler/config.py` | Variáveis de ambiente obrigatórias, fuso horário e caminho padrão do estado |
| `scrobbler/ytmusic.py` | Validação do `browser.json` e leitura do histórico, com erros traduzidos |
| `scrobbler/history.py` | Modelos (`Play`, `Scrobble`), normalização de metadados e regras de descarte |
| `scrobbler/selection.py` | Detecção incremental das reproduções novas e estimativa de horários |
| `scrobbler/state.py` | Leitura e gravação atômica do estado de sincronização |
| `scrobbler/lastfm.py` | Envio em lotes, retentativas com backoff, scrobbles ignorados e geração da session key |
| `scrobbler/sync.py` | Orquestração da sincronização e resumo da execução |
| `.github/workflows/scrobble.yml` | Execução de hora em hora e manual no GitHub Actions |
| `tests/` | Testes automatizados (todas as APIs externas simuladas) |

## Pré-requisitos

- **Python 3.14** (versão usada localmente e no GitHub Actions).
- **Git**.
- Conta no **YouTube Music** com o histórico ativado (o histórico do YouTube não pode estar pausado).
- Conta no **Last.fm**.
- Uma **API Key** e um **Shared Secret** do Last.fm (gratuitos).
- Um navegador (Firefox, Chrome ou Edge) logado no YouTube Music para gerar o `browser.json`.

## Instalação local

Os comandos abaixo são para **Windows/PowerShell**.

```powershell
git clone https://github.com/mateusvcsmoura/lastfm-scrobbler-youtubemusic.git
cd lastfm-scrobbler-youtubemusic

py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
```

Se o PowerShell bloquear o `Activate.ps1`, libere scripts locais para o seu usuário ou chame o Python do ambiente diretamente (`.\.venv\Scripts\python.exe`):

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### Configurar o `.env`

O `.env` é ignorado pelo Git. Se ainda não existir, crie-o a partir do modelo:

```powershell
Copy-Item .env.example .env
```

| Variável | Conteúdo |
| --- | --- |
| `LASTFM_API_KEY` | API Key do Last.fm |
| `LASTFM_API_SECRET` | Shared Secret do Last.fm |
| `LASTFM_SESSION_KEY` | Session key gerada com `python -m scrobbler --login-lastfm` |
| `BROWSER_JSON` | Caminho do `browser.json` (padrão `browser.json`) **ou** o conteúdo JSON completo |

Variáveis já definidas no ambiente têm prioridade sobre o `.env`.

### Preparar a autenticação

1. Preencha `LASTFM_API_KEY` e `LASTFM_API_SECRET` ([Configuração do Last.fm](#configuração-do-lastfm)).
2. Gere a `LASTFM_SESSION_KEY` com `python -m scrobbler --login-lastfm`.
3. Gere o `browser.json` ([Configuração do YouTube Music](#configuração-do-youtube-music)).

### Executar

```powershell
python -m scrobbler --dry-run
```

O `--dry-run` valida as credenciais, lê o histórico e mostra o que seria enviado, **sem enviar scrobbles e sem gravar estado**.

```powershell
python -m scrobbler
```

Envia de fato. O estado local fica em `state/state.json` (ignorado pelo Git); use `--state-file` para outro caminho.

> **Importante:** o estado local e o estado do GitHub Actions são independentes. Se você enviar scrobbles localmente **e** pelo Actions, as mesmas músicas serão enviadas duas vezes. Depois de ativar o workflow, use localmente apenas o `--dry-run`.

## Configuração do Last.fm

### API Key e Shared Secret

1. Acesse <https://www.last.fm/api/account/create> logado na sua conta.
2. Preencha nome e descrição do aplicativo (os demais campos podem ficar vazios).
3. Copie a **API key** para `LASTFM_API_KEY` e o **Shared secret** para `LASTFM_API_SECRET`.
4. As chaves ficam disponíveis depois em <https://www.last.fm/api/accounts>.

### Autenticação escolhida: session key

O projeto usa **somente session key** (`LASTFM_SESSION_KEY`), sem usuário e senha:

- A senha nunca é armazenada no `.env` nem nos secrets do GitHub.
- A session key não expira; deixa de valer apenas se o acesso do aplicativo for revogado em <https://www.last.fm/settings/applications>.
- É gerada pelo fluxo oficial de autorização web do Last.fm (`auth.getToken` → autorização no navegador → `auth.getSession`).

Para gerar:

```powershell
python -m scrobbler --login-lastfm
```

O comando mostra um link. Abra-o, clique em **Yes, allow access**, volte ao terminal e pressione **Enter**. A session key é exibida no terminal; copie-a para `LASTFM_SESSION_KEY` no `.env` e no secret do GitHub. Não compartilhe esse valor.

### Validar a conexão

```powershell
python -m scrobbler --dry-run
```

A linha `Last.fm autenticado como <usuário>` confirma que API key, secret e session key estão corretos.

## Configuração do YouTube Music

### Estratégia: `browser.json`

A autenticação usa os headers de uma sessão logada do navegador (`browser.json`), suportada pelo `ytmusicapi`:

- Funciona igualmente no seu computador e no GitHub Actions, com um único secret.
- Segundo a documentação do `ytmusicapi`, as credenciais duram **cerca de 2 anos**, desde que você **não faça logout** dessa sessão no navegador. Na prática há uma segunda condição: o YouTube **rotaciona os cookies enquanto houver uma aba do YouTube aberta** com essa sessão, e os cookies exportados antes da rotação deixam de valer (orientação documentada pelo [yt-dlp](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies)). Neste projeto, um `browser.json` exportado com a janela anônima ainda aberta parou de funcionar em menos de um dia. Por isso a sessão exportada nunca pode voltar a ser aberta no navegador.
- A alternativa OAuth exige um projeto no Google Cloud com um cliente OAuth próprio; enquanto o app do Google Cloud estiver em modo *Testing*, o refresh token expira em 7 dias, o que inviabiliza a execução autônoma.

O conteúdo é validado antes do uso: precisa ser um objeto JSON com o cookie `__Secure-3PAPISID` e o header `authorization` (`SAPISIDHASH ...`). Um arquivo vazio ou `{}` é rejeitado com erro claro; nunca é tratado como autenticação válida.

### Gerar o `browser.json`

Use uma **janela anônima/privada** criada só para isso, para que a sessão exportada nunca mais seja aberta (e rotacionada) pelo navegador.

1. Feche outras janelas anônimas. Abra uma **nova janela anônima** (Firefox: Ctrl+Shift+P; Chrome/Edge: Ctrl+Shift+N), com **uma única aba**.
2. Acesse <https://music.youtube.com> e faça login.
3. Abra as ferramentas de desenvolvedor (**F12**) → aba **Network/Rede** e filtre por `browse`.
4. Clique em **Biblioteca** e selecione uma requisição **POST** para `browse?...` com status **200**.
5. Copie os headers da requisição:
   - **Firefox:** botão direito na requisição → *Copiar* → *Copiar cabeçalhos da requisição*.
   - **Chrome/Edge:** em *Headers → Request Headers*, copie tudo a partir de `accept: */*` até o fim da seção.
6. **Imediatamente** feche a janela anônima inteira, **sem fazer logout** (o conteúdo copiado continua na área de transferência). Não abra o YouTube nessa sessão de novo.
7. No terminal, dentro do projeto e com o ambiente virtual ativo:

   ```powershell
   ytmusicapi browser
   ```

8. Cole os headers e finalize com **Enter**, **Ctrl+Z**, **Enter** (Windows). O arquivo `browser.json` será criado na pasta atual.
9. Valide com `python -m scrobbler --dry-run`.

Não use cookies de uma sessão que você continua usando no navegador do dia a dia: o navegador vai rotacioná-los e o `browser.json` deixará de valer.

O `browser.json` contém cookies da sua conta Google. Ele está no `.gitignore`; nunca o envie ao GitHub.

### Levar as credenciais ao GitHub Actions com segurança

Copie o **conteúdo completo** do arquivo para o secret `BROWSER_JSON` (o valor pode ter várias linhas):

```powershell
Get-Content browser.json -Raw | Set-Clipboard
```

No GitHub Actions o JSON é lido diretamente da variável de ambiente; nenhum arquivo de credenciais é gravado no runner.

### Renovar quando expirar

Sinais de expiração: erros como `YouTube Music não reconheceu a sessão do browser.json` (o YouTube responde "Sign in to view your history") ou `Resposta inesperada do YouTube Music ao ler o histórico`.

1. Gere um novo `browser.json` seguindo os passos acima.
2. Atualize o arquivo local e o secret `BROWSER_JSON` no GitHub.
3. Rode o workflow manualmente com dry-run para validar.

Enquanto a autenticação estiver quebrada, o estado não é alterado; as reproduções que continuarem no histórico (até cerca de 200 músicas e 13 dias) serão recuperadas na próxima execução bem-sucedida.

## GitHub Actions

O workflow **Scrobble YouTube Music** (`.github/workflows/scrobble.yml`) roda **de hora em hora, no minuto 17** (`cron: "17 * * * *"`, com `timezone: America/Sao_Paulo`), e também pode ser disparado manualmente.

Por que de hora em hora: o histórico do YouTube Music guarda cada música uma única vez (ver [Controle de duplicações](#controle-de-duplicações)), então repetições só são detectadas entre uma sincronização e outra. Execuções frequentes capturam mais repetições e deixam os horários estimados mais próximos dos reais. Por que o minuto 17: a documentação do GitHub informa que o início de cada hora é o horário de maior carga, quando agendamentos atrasam ou podem ser descartados.

Limites considerados:

- **GitHub Actions:** o intervalo mínimo de agendamento é de 5 minutos. Cada execução leva cerca de 1 minuto; em repositório público os minutos dos runners padrão são gratuitos, e em repositório privado o consumo (~720 min/mês) cabe na franquia gratuita de 2.000 min/mês, desde que não haja outros workflows grandes.
- **Last.fm:** os termos não fixam um número de requisições, apenas proíbem uso abusivo; cada execução faz 1 validação de sessão e no máximo alguns envios.
- **YouTube Music:** a API não é oficial e não tem limite documentado; cada execução faz uma única leitura do histórico.

### Criar os secrets

1. Abra o repositório no GitHub e clique em **Settings** (aba superior; exige permissão de administrador).
2. No menu lateral, abra **Secrets and variables → Actions**.
3. Na aba **Secrets**, clique em **New repository secret** para cada item:

| Nome exato | Conteúdo |
| --- | --- |
| `LASTFM_API_KEY` | API key do Last.fm |
| `LASTFM_API_SECRET` | Shared secret do Last.fm |
| `LASTFM_SESSION_KEY` | Session key gerada por `python -m scrobbler --login-lastfm` |
| `BROWSER_JSON` | Conteúdo completo do `browser.json` (o JSON, não o caminho) |

Os valores dos secrets são mascarados automaticamente nos logs.

### Permissões

O workflow declara permissões mínimas para o `GITHUB_TOKEN`:

- `contents: read` — checkout do código.
- `actions: read` — listar e baixar o artifact de estado da execução anterior.

O upload de artifacts usa o token de runtime do próprio Actions e não precisa de permissão adicional. O workflow não faz commits nem push.

### Verificar se o agendamento está habilitado

1. Abra a aba **Actions** do repositório. Se o Actions estiver desativado, habilite em **Settings → Actions → General → Actions permissions**.
2. Selecione o workflow **Scrobble YouTube Music** na lista à esquerda.
3. Se aparecer um aviso de workflow desativado (o GitHub desativa agendamentos de repositórios públicos sem atividade por 60 dias), clique em **Enable workflow**.
4. Agendamentos usam o arquivo do branch padrão (`main`).

### Executar manualmente

1. **Actions → Scrobble YouTube Music → Run workflow**.
2. A opção **Dry-run** vem **marcada** por padrão: valida credenciais e mostra o que seria enviado, sem enviar e sem salvar estado.
3. Para sincronizar de verdade, desmarque **Dry-run** e clique em **Run workflow**.

Execuções reais manuais são seguras: usam e atualizam o mesmo estado do agendamento, e a próxima execução agendada enviará apenas o que for tocado depois.

### Consultar logs e identificar falhas

1. **Actions** → clique na execução desejada → job **scrobble**.
2. Passo **Restaurar estado anterior**: informa se o estado foi restaurado ou se é a primeira execução.
3. Passo **Sincronizar**: lista as músicas (com horário estimado), avisos e o **Resumo** final.
4. Execuções com ✗ vermelho falharam; a última linha `ERROR` do passo **Sincronizar** explica o motivo (ver [Troubleshooting](#troubleshooting)).
5. O estado salvo pode ser baixado em **Artifacts → sync-state** na página da execução.

Os logs contêm títulos e artistas das músicas enviadas (as mesmas informações publicadas no seu perfil do Last.fm). Em repositórios públicos, os logs do Actions são públicos.

### Concorrência e horário

- `concurrency: scrobble` garante uma execução por vez; uma execução disparada durante outra aguarda na fila, sem cancelar a atual.
- O GitHub **não garante** o horário exato: execuções agendadas podem atrasar em horários de alta carga e, raramente, ser descartadas. A sincronização tolera atrasos e execuções perdidas (ver [Operação](#operação)).
- `timeout-minutes: 15` impede execuções presas.

## Operação

### Controle de duplicações

O histórico do YouTube Music **não possui identificador por reprodução** nem horário. Ele é uma lista ordenada da mais recente para a mais antiga, com cerca de 200 itens, em que cada música aparece **uma única vez**: ao tocar de novo uma música, ela é movida para o topo. O `videoId` identifica a música, não a reprodução.

Por isso o projeto guarda um **snapshot** com os `videoId`s do histórico ao final de cada sincronização e, na execução seguinte, procura o ponto em que o histórico atual "encaixa" no snapshot:

1. Para cada posição `k` do histórico atual, considera os itens a partir de `k` e remove do snapshot as músicas que não aparecem mais nesse trecho (subiram para o topo, foram removidas do histórico ou saíram do limite de 200).
2. Se os 20 primeiros itens desse trecho coincidirem com o início do snapshot filtrado, `k` é a fronteira: tudo acima de `k` é novo.
3. Se nenhuma posição encaixar (por exemplo, mais de 200 músicas novas desde a última execução ou histórico limpo), apenas músicas da seção **Today** são consideradas, mais as da seção **Yesterday** se a última sincronização aconteceu antes do início de ontem. Um aviso é registrado no log. Isso evita reenviar o dia anterior inteiro, ao custo de perder músicas tocadas entre a última sincronização e a meia-noite nesse caso raro.

Exemplo (mais recente à esquerda):

```
snapshot anterior:  A B C D E
histórico atual:    X C A B D E   → novas: X (inédita) e C (tocada de novo)
```

Garantias e regras adicionais:

- Músicas diferentes com o mesmo título continuam distintas (a chave é o `videoId`; sem ele, artista + título).
- Uma reprodução repetida de uma música mais antiga é detectada e enviada novamente.
- Uma entrada da seção **Yesterday** nunca é enviada se a última sincronização já aconteceu depois da meia-noite.
- **Primeira execução** (sem estado): envia somente as músicas da seção **Today**; o histórico antigo nunca é importado automaticamente.

### Horários estimados

O `get_history()` só informa a seção em que a música está (`Today`, `Yesterday`, `This week`, `Last week`, ou mês e ano). O Last.fm exige o horário de início de cada reprodução (Unix timestamp em UTC), então o projeto aplica uma política fixa:

1. As reproduções novas são encadeadas de trás para frente a partir do horário da execução: a mais recente termina "agora" e cada anterior termina quando a seguinte começa, usando a duração da faixa (180 s quando desconhecida).
2. **Today** fica entre 00:00 de hoje (São Paulo) e agora; **Yesterday** fica no dia anterior, antes de 00:00 de hoje.
3. Nenhum horário fica antes da última sincronização nem mais de 13 dias no passado (margem para o limite do Last.fm a scrobbles antigos).
4. Se as músicas não couberem nesse intervalo, são distribuídas uniformemente dentro dele, preservando a ordem.

Esses horários são **estimativas**: nos logs aparecem como `(horário estimado)`. O Last.fm não tem um campo para marcar estimativas, então no seu perfil eles aparecem como horários comuns. A ordem das músicas e o dia (hoje/ontem) são preservados; a hora exata não corresponde à reprodução real.

O cliente envia `timeZone=America/Sao_Paulo` no contexto das requisições ao YouTube Music para que "Today" e "Yesterday" sigam o dia de São Paulo. Isso reproduz o que o cliente web oficial envia, mas o efeito não pôde ser verificado sem credenciais reais.

### Armazenamento do estado

O estado é um JSON pequeno (`state/state.json`):

```json
{
  "version": 1,
  "synced_at": "2026-10-29T23:00:04-03:00",
  "history": ["videoId mais recente", "..."],
  "pending": [
    {"artist": "Artista", "title": "Faixa", "timestamp": 1793311200, "album": "Álbum", "duration": 215}
  ]
}
```

- `history`: snapshot do histórico usado na detecção incremental.
- `synced_at`: horário da última sincronização.
- `pending`: scrobbles já preparados que ainda não foram aceitos pelo Last.fm.

No GitHub Actions, ele é salvo como artifact **`sync-state`** ao final de toda execução real (inclusive as que falham, para preservar o progresso parcial), com retenção de 30 dias. A execução seguinte baixa o artifact não expirado mais recente pela API do GitHub.

Por que artifacts:

- **Cache do Actions** é feito para dependências: pode ser removido a qualquer momento por limite de espaço e é descartado após 7 dias sem acesso.
- **Commits automáticos** poluiriam o histórico do repositório e exigiriam permissão de escrita no código.
- **Artifacts** têm retenção explícita, podem ser baixados e inspecionados pela interface e exigem só `actions: read` para leitura.

Se o estado for perdido (sem execuções por mais de 30 dias ou artifacts apagados), a próxima execução se comporta como a primeira: envia apenas **Today**. Isso é intencional, pois o Last.fm recusa scrobbles antigos de qualquer forma.

### O que acontece quando algo falha

| Situação | Comportamento |
| --- | --- |
| Credencial ausente ou inválida | Erro claro, workflow falha, estado não é alterado |
| YouTube Music fora do ar ou autenticação expirada | Workflow falha, estado não é alterado; a próxima execução recupera o que ainda estiver no histórico |
| Last.fm indisponível (códigos 8, 11, 16, 29, HTTP 5xx ou falha de rede) | Até 3 tentativas com espera de 10 s e 20 s |
| Last.fm continua falhando | Scrobbles não aceitos ficam em `pending`, o workflow falha e eles são enviados primeiro na próxima execução |
| Lote recusado pelo Last.fm (outros códigos, exceto autenticação) | Sem retentativa do lote; os itens são reenviados um por vez e somente o item recusado é descartado (registrado como `ERROR`/aviso no log), para não bloquear a fila |
| Scrobble ignorado pelo Last.fm (filtro, horário antigo/futuro, limite diário) | Registrado no log e no resumo; não é reenviado |
| Execução atrasada ou perdida | Recuperada se houver menos de ~200 músicas novas e menos de 13 dias desde a última sincronização |
| Execução cancelada | O estado é gravado de forma atômica (arquivo temporário + `os.replace`) e salvo no artifact |
| Estado corrompido | Erro claro sem enviar nada; veja como reinicializar abaixo |

### Modo dry-run

`python -m scrobbler --dry-run` (ou a opção **Dry-run** na execução manual):

- valida as credenciais do Last.fm (chamada somente leitura `user.getInfo`) e do YouTube Music;
- lê o estado existente e o histórico;
- lista cada scrobble que seria enviado, com horário estimado;
- **não** envia scrobbles, **não** grava o estado local e, no Actions, **não** salva artifact.

### Recuperar ou reinicializar o estado

- **Inspecionar:** baixe o artifact `sync-state` na página de uma execução e abra o `state.json`.
- **Reinicializar:** apague os artifacts `sync-state` (ícone de lixeira em **Artifacts** na página de cada execução, ou pela API). A próxima execução será tratada como a primeira e enviará apenas as músicas da seção **Today**. Se você reinicializar no mesmo dia de uma sincronização já feita, as músicas de hoje que já foram enviadas serão enviadas de novo; prefira reinicializar antes de ouvir músicas no dia ou aceite essas duplicações.

## Decisões técnicas

- **Detecção por snapshot em vez de filtrar `Yesterday`:** o script de referência enviava tudo que estivesse em `Yesterday` com o horário atual. Isso duplicava músicas em execuções manuais, perdia o que fosse tocado entre a execução e a meia-noite e marcava tudo com o mesmo horário. O snapshot resolve as três situações.
- **Fila `pending` gravada antes do envio:** segue a recomendação do Last.fm de manter uma fila persistente de scrobbles não enviados e enviá-los antes dos novos, em ordem.
- **Uso de `pylast._Request`:** `pylast.scrobble_many` descarta a resposta da API, o que impede saber quais scrobbles foram ignorados. O projeto monta os parâmetros de `track.scrobble` e usa `pylast._Request` para obter a resposta XML, mantendo assinatura, sessão e tratamento de erros do pylast. Por ser uma API interna, a versão do `pylast` está fixada e coberta por testes.
- **Artista principal:** apenas o primeiro artista é enviado como `artist`. Enviar "Artista A, Artista B" cria artistas inexistentes no Last.fm e fragmenta as estatísticas.
- **Itens descartados:** episódios de podcast (`MUSIC_VIDEO_TYPE_PODCAST_EPISODE`) e vídeos enviados por usuários (`MUSIC_VIDEO_TYPE_UGC`, cujo "artista" é o nome do canal), além de faixas de até 30 s (regra do Last.fm). Músicas, clipes oficiais e uploads pessoais são enviados.
- **`truststore`:** o `ytmusicapi` usa `requests`, que por padrão confia apenas no pacote `certifi`. Em computadores com antivírus ou proxy que inspecionam HTTPS, isso causa `CERTIFICATE_VERIFY_FAILED`. O `truststore` (já dependência do pylast) faz o Python usar os certificados do sistema operacional, mantendo a verificação TLS ativa.
- **Idioma `en`:** o cliente do YouTube Music é criado com `language="en"` para que os nomes das seções (`Today`, `Yesterday`) sejam previsíveis.
- **Dependências fixadas:** `requirements.txt` fixa todas as dependências, inclusive as transitivas, para instalações reproduzíveis.

## Limitações conhecidas

- **Sem horários reais:** todos os horários enviados são estimados (ver [Horários estimados](#horários-estimados)).
- **Histórico limitado:** o `get_history()` retorna cerca de 200 itens, sem paginação. Mais de ~200 músicas diferentes entre duas execuções faz as mais antigas se perderem.
- **Repetições:** uma música tocada várias vezes entre duas execuções (na prática, dentro da mesma hora) aparece uma única vez no histórico e gera **um** scrobble. Repetições em horas diferentes, com outras músicas no meio, são detectadas. Tocar de novo a(s) música(s) que estavam no topo do histórico na última sincronização, na mesma ordem, não altera o histórico e não é detectável.
- **Tempo ouvido:** o Last.fm pede scrobble apenas quando metade da faixa (ou 4 minutos) foi ouvida. O YouTube Music não informa quanto foi ouvido, então músicas puladas que entraram no histórico também são enviadas.
- **Seções desconhecidas:** se o YouTube Music mudar os nomes das seções, a data de cada música deixa de ser conhecida e os horários passam a ser estimados apenas entre a última sincronização e o momento da execução.
- **Atrasos do GitHub Actions:** agendamentos podem atrasar ou ser descartados; repositórios públicos sem atividade por 60 dias têm o agendamento desativado.
- **Expiração das credenciais:** o `browser.json` deixa de funcionar se você fizer logout daquela sessão, se a sessão for reaberta no navegador (rotação de cookies) ou após cerca de 2 anos. O Google não documenta a duração desses cookies; se expirarem com frequência mesmo seguindo o passo a passo, a alternativa é migrar para OAuth do `ytmusicapi`, que exige um projeto no Google Cloud. O `ytmusicapi` 1.12.3 marca a autenticação por navegador como *deprecated* na ajuda do comando `ytmusicapi browser` (a documentação oficial ainda a descreve normalmente); uma versão futura pode exigir migração para OAuth.
- **Limites do Last.fm:** scrobbles antigos demais (na prática, por volta de 14 dias), no futuro, acima do limite diário ou filtrados pelo Last.fm são ignorados (códigos 1 a 5) e aparecem no log.
- **Contas de marca (Brand Accounts):** não suportadas; o histórico lido é o da conta principal da sessão.
- **Duplicações residuais possíveis:** (a) falha de rede depois que o Last.fm já aceitou um lote, seguida de retentativa; (b) interrupção entre a resposta do Last.fm e a gravação do estado; (c) estado reinicializado no mesmo dia de uma sincronização; (d) envios reais simultâneos pelo computador local e pelo Actions. *Exactly-once* não é possível sem identificadores por reprodução.

## Troubleshooting

| Sintoma | Causa provável | Solução |
| --- | --- | --- |
| `Variáveis de ambiente obrigatórias ausentes: ...` | Secret ou variável do `.env` vazio | Crie o secret com o nome exato listado em [GitHub Actions](#criar-os-secrets) ou preencha o `.env` |
| `Last.fm recusou as credenciais (código 9 ...)` | Session key inválida ou acesso revogado | Rode `python -m scrobbler --login-lastfm` e atualize `LASTFM_SESSION_KEY` |
| `Last.fm recusou as credenciais (código 10 ou 13 ...)` | API key ou secret incorretos | Confira em <https://www.last.fm/api/accounts> |
| `BROWSER_JSON não contém o cookie __Secure-3PAPISID ...` | Headers copiados de uma requisição errada ou sem login | Gere o `browser.json` de novo a partir de uma requisição `browse` logada |
| `BROWSER_JSON deve conter o JSON ... ou o caminho de um arquivo existente` | Caminho errado no `.env` ou secret com conteúdo incompleto | Use o caminho correto localmente; no GitHub, cole o JSON inteiro |
| `YouTube Music não reconheceu a sessão do browser.json` | Cookies rotacionados (sessão reaberta no navegador ou janela deixada aberta após exportar), logout ou expiração | Gere um novo `browser.json` seguindo exatamente [Gerar o `browser.json`](#gerar-o-browserjson) e atualize o secret |
| `Resposta inesperada do YouTube Music` | Sessão inválida ou mudança na estrutura do YouTube Music | Gere um novo `browser.json`; se persistir, atualize o `ytmusicapi` |
| `CERTIFICATE_VERIFY_FAILED` local | Inspeção HTTPS por antivírus/proxy | O projeto já usa `truststore`; confirme que o certificado do antivírus/proxy está instalado no Windows |
| `0 músicas encontradas no histórico` | Histórico pausado ou conta diferente | Verifique o histórico em <https://music.youtube.com/history> com a mesma conta |
| Workflow não executa de hora em hora | Agendamento desativado, Actions desabilitado ou atraso do GitHub | Veja [Verificar se o agendamento está habilitado](#verificar-se-o-agendamento-está-habilitado); atrasos são recuperados na execução seguinte |
| `Last.fm ignorou (horário muito antigo)` | Pendências antigas demais | Nada a fazer; o Last.fm não aceita scrobbles antigos |
| `Last.fm ignorou (artista/faixa filtrado)` | Filtro de spam do Last.fm | Metadados do YouTube Music rejeitados pelo Last.fm; não há correção automática |
| `Envio interrompido; N scrobbles ficam pendentes` | Last.fm indisponível | Serão reenviados na próxima execução; rode manualmente se quiser antecipar |
| `Arquivo de estado inválido` | Artifact corrompido | Reinicialize o estado (seção [Recuperar ou reinicializar o estado](#recuperar-ou-reinicializar-o-estado)) |
| Passo **Restaurar estado anterior** falhou | API do GitHub indisponível ou permissão `actions: read` removida | Rode novamente; a sincronização não é executada sem estado confiável |
| `Histórico atual não se alinha ao snapshot anterior` | Mais de ~200 músicas novas, histórico limpo ou conta trocada | Apenas músicas de hoje (e de ontem, se a última sincronização foi antes de ontem) são enviadas; confira o resultado no Last.fm |
| `Lote recusado; reenviando um scrobble por vez` | Algum item tem dados recusados pela API | Os demais itens são enviados; o item recusado aparece em `Last.fm ignorou (...)` |
| Músicas duplicadas no Last.fm | Ver [Limitações conhecidas](#limitações-conhecidas) | Remova os scrobbles duplicados pelo perfil do Last.fm; evite execuções reais locais com o Actions ativo |

## Testes e qualidade

```powershell
python -m pytest
python -m ruff check .
python -m ruff format --check .
```

Os testes simulam o YouTube Music e o Last.fm (nenhuma chamada real, nenhum scrobble enviado) e cobrem normalização de metadados, entradas inválidas, histórico vazio, detecção de músicas novas, prevenção de duplicações entre execuções, repetições legítimas, persistência do estado, falhas de envio e de autenticação, credenciais ausentes, fusos horários e o modo dry-run.

O `ruff` foi escolhido por reunir lint e formatação numa única ferramenta leve; a configuração está no `pyproject.toml`.
