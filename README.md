# RPA PROCONT

Automação em Python para consultas, downloads e envio de documentos relacionados ao setor fiscal e ao parcelamento/regularização tributária.

Este repositório reúne scripts de RPA (Robotic Process Automation) para interagir com portais públicos e sistemas do setor fiscal, processar arquivos em planilhas, baixar documentos e enviar relatórios por e-mail.

## Visão geral

O projeto foi estruturado para automatizar rotinas recorrentes de:

- consulta de notas e guias em portais municipais;
- processamento de empresas/CPFs/CNPJs a partir de planilhas Excel;
- leitura de CAPTCHA com OCR;
- download de PDFs e documentos fiscais;
- envio automático de anexos por e-mail;
- integração com sistemas externos como Task.do;
- geração de executáveis Windows via PyInstaller.

## Scripts principais

- `consultaNotas.py` — consulta de notas e emissão/baixas em portais municipais (Salvador, Camaçari e Simões Filho).
- `consultaRelPend.py` — rotina de consulta de relatórios pendentes.
- `rpap2.py` — fluxo principal de automação para e-CAC / processamento de empresas.
- `rpa2dif.py` — fluxo de parcelamento/Regularize PGFN para geração de DARFs e documentos de parcelamento.
- `rpa2envioemail.py` — envio de e-mails com anexos para o setor fiscal.
- `rpa2taskdo.py` — integração com Task.do.
- `rpa_config.py` — configuração compartilhada e utilitários de log/relatório.

## Estrutura do repositório

```text
rpa_procont/
├── .github/
│   └── workflows/
│       ├── build.yml
│       ├── build-pipeline.yml
│       └── build-notas.yml
├── consultaNotas.py
├── consultaRelPend.py
├── rpap2.py
├── rpa2dif.py
├── rpa2envioemail.py
├── rpa2taskdo.py
├── rpa_config.py
├── README.md
└── config.json  # gerado automaticamente na primeira execução
```

## Requisitos

- Python 3.11
- Google Chrome instalado no ambiente
- Bibliotecas Python:

```bash
pip install pandas openpyxl playwright pyinstaller opencv-python ddddocr numpy pillow requests
```

Dependendo do script executado, pode ser necessário instalar bibliotecas extras conforme o workflow do GitHub Actions do projeto.

## Configuração

Ao executar qualquer script pela primeira vez, o sistema tenta criar um arquivo `config.json` na pasta do projeto.

Esse arquivo armazena configurações sensíveis e de ambiente, como:

- planilhas de entrada;
- e-mails remetente/destinatário;
- senha de app do Gmail;
- senhas de acesso aos sistemas;
- chave da API 2Captcha;
- parâmetros de execução.

Exemplo de estrutura esperada:

```json
{
  "planilha_fluxo1": "teste3.xlsx",
  "planilha_fluxo4": "teste5.xlsx",
  "chrome_cdp": "http://127.0.0.1:9222",
  "senhas_pgfn": ["Senha1", "Senha2"],
  "email_remetente": "",
  "email_senha": "",
  "email_destinatario": "",
  "api_key_2captcha": "",
  "data_alvo_taskdo": "25/09/2026",
  "max_tentativas": 2
}
```

## Como usar

1. Ajuste o arquivo `config.json` com os valores corretos para sua operação.
2. Coloque as planilhas exigidas na pasta do projeto.
3. Execute o script desejado:

```bash
python consultaNotas.py
```

ou

```bash
python rpa2dif.py
```

Os scripts podem gerar:

- relatórios em Excel;
- arquivos PDF baixados;
- logs em `rpa_log.txt`;
- e-mails com anexos;
- executáveis `.exe` para uso em ambiente Windows.

## Build dos executáveis

O repositório já inclui workflows do GitHub Actions para compilar os `.exe` usando PyInstaller.

Fluxos presentes:

- `build.yml`
- `build-pipeline.yml`
- `build-notas.yml`

Esses workflows instalam as dependências e geram artefatos prontos para download.

## Observações importantes

- Os scripts usam Playwright e Chrome para navegar em portais web automaticamente.
- Algumas operações dependem de autenticação e de arquivos externos, como planilhas de entrada e credenciais seguras.
- O projeto foi pensado para execução local e para geração de executáveis Windows em ambiente corporativo.
- A segurança é tratada separando credenciais em `config.json`, em vez de deixá-las hardcoded no código.

## Licença

Este repositório não informa uma licença explícita no arquivo principal cadastrado. Verifique com o responsável do projeto antes de redistribuir ou reutilizar o código em produção.

## Autor

Projeto mantido por Amanda Bonfim.

## Status

Em desenvolvimento e automatização para rotinas fiscais e de parcelamento tributário.
