"""
Configuração compartilhada do pipeline de RPAs do Procont.

Nenhuma credencial fica no código-fonte dos scripts: tudo vem de um
único config.json salvo ao lado dos executáveis/.py. Na primeira
execução de qualquer um dos 4 scripts, se o arquivo não existir,
ele é criado em branco e o script para, pedindo para preencher.
"""

import os
import sys
import json
import logging
from datetime import datetime


if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

# Um mesmo "run id" é compartilhado pelos 4 scripts quando rodam a
# partir do .bat (via variável de ambiente RPA_RUN_ID), para que os
# relatórios dos 4 fiquem fáceis de agrupar. Rodando um script sozinho
# para testar, ele gera um run id novo na hora.
RUN_ID = os.environ.get("RPA_RUN_ID") or datetime.now().strftime("%Y%m%d_%H%M%S")

CONFIG_PADRAO = {
    "planilha_fluxo1": "teste3.xlsx",
    "planilha_fluxo4": "teste5.xlsx",
    "chrome_cdp": "http://127.0.0.1:9222",
    "senhas_pgfn": ["Hamilton1", "Hamilton1@", "Hamilton1"],
    "email_remetente": "",
    "email_senha": "",
    "email_destinatario": "",
    "api_key_2captcha": "",
    "data_alvo_taskdo": "25/09/2026",
    "max_tentativas": 2,
}


def carregar_config():
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(CONFIG_PADRAO, f, indent=4, ensure_ascii=False)

        print(f"Arquivo de configuração criado em: {CONFIG_PATH}")
        print("Preencha os dados nele (planilhas, e-mail, senhas PGFN) e rode novamente.")
        sys.exit(1)

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)

    for chave, valor in CONFIG_PADRAO.items():
        config.setdefault(chave, valor)

    return config


CONFIG = carregar_config()


def caminho(nome_arquivo):
    """Resolve um nome de arquivo relativo à pasta onde os scripts/exe estão."""
    return os.path.join(BASE_DIR, nome_arquivo)


def configurar_log(nome_logger):
    """Log compartilhado: todos os scripts do pipeline escrevem no mesmo
    rpa_log.txt, cada linha identificando de qual script veio."""
    log_path = os.path.join(BASE_DIR, "rpa_log.txt")

    logger = logging.getLogger(nome_logger)
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        formato = logging.Formatter(
            f"%(asctime)s [{nome_logger}] [%(levelname)s] %(message)s"
        )

        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formato)
        logger.addHandler(file_handler)

    return logger


def salvar_relatorio_execucao(resultados, nome_etapa):
    """Salva um .xlsx com o resultado de cada item processado nesta etapa.
    Usa pandas, que já é dependência dos scripts."""
    import pandas as pd

    if not resultados:
        print(f"\n[{nome_etapa}] Nenhum item processado, relatório não gerado.")
        return None

    df_resultado = pd.DataFrame(resultados)

    nome_arquivo = f"relatorio_{nome_etapa}_{RUN_ID}.xlsx"
    caminho_relatorio = caminho(nome_arquivo)

    df_resultado.to_excel(caminho_relatorio, index=False)

    total = len(resultados)
    erros = [r for r in resultados if r.get("Status") == "ERRO"]

    print(f"\n══════════════════════════════════════════")
    print(f"RESUMO - {nome_etapa}")
    print(f"══════════════════════════════════════════")
    print(f"Total processado: {total}")
    print(f"OK: {total - len(erros)}")
    print(f"Com erro: {len(erros)}")
    print(f"Relatório salvo em: {caminho_relatorio}")

    if erros:
        print(f"\nItens com erro em {nome_etapa}:")
        for r in erros:
            identificador = r.get("CPF_CNPJ") or r.get("Empresa") or "?"
            print(f" - {identificador}: {r.get('Erro', '')}")

    print(f"══════════════════════════════════════════")

    return caminho_relatorio
