import calendar
from datetime import datetime, timedelta
import email
import io
import json
import logging
import os
import re
import smtplib
import sys
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import cv2
import ddddocr
import numpy as np
import pandas as pd
from PIL import Image
from playwright.sync_api import sync_playwright

# ============================================================
# LOCALIZAÇÃO BASE (funciona rodando .py OU .exe do PyInstaller)
# ============================================================

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# CONFIGURAÇÃO EXTERNA (config.json)
# Nenhuma credencial fica no código-fonte.
# ============================================================

CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

CONFIG_PADRAO = {
    "planilha": "RPA_NOTAS.xlsx",
    "email_remetente": "",
    "email_senha": "",
    "email_destinatario": "",
    "max_tentativas_login": 5,
}


def carregar_config():
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(CONFIG_PADRAO, f, indent=4, ensure_ascii=False)

        print(f"Arquivo de configuração criado em: {CONFIG_PATH}")
        print("Preencha os dados nele (planilha, e-mail, senha de app) e rode novamente.")
        sys.exit(1)

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)

    for chave, valor in CONFIG_PADRAO.items():
        config.setdefault(chave, valor)

    if not config["email_remetente"] or not config["email_senha"]:
        print(f"Erro: preencha 'email_remetente' e 'email_senha' em {CONFIG_PATH}")
        sys.exit(1)

    return config


CONFIG = carregar_config()

# ============================================================
# LOG EM ARQUIVO
# ============================================================

LOG_PATH = os.path.join(BASE_DIR, "rpa_log.txt")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)

log = logging.getLogger("rpa_notas")

# Lista global para armazenar as empresas do Local 2 que tiveram mensagens de alteração/diferentes do padrão
empresas_com_alteracao_local2 = []

# Inicializa o OCR
ocr = ddddocr.DdddOcr(show_ad=False)

PASTA_DOWNLOADS = os.path.join(BASE_DIR, "arq_rpa")

URLS_LOCAIS = {
    1: "https://nfse.salvador.ba.gov.br/default.aspx",  # Salvador
    2: "https://nfse.camacari.ba.gov.br/prefeituras/loginb.tela",  # Camaçari
    4: "https://ba-simoesfilho-pm-nfs.cloud.el.com.br/#/login",  # Simoes filho
}

CONFIG_EMAIL = {
    "servidor_smtp": "smtp.gmail.com",
    "porta": 587,
    "email_remetente": CONFIG["email_remetente"],
    "senha_app": CONFIG["email_senha"],
    "email_destinatario": CONFIG["email_destinatario"] or CONFIG["email_remetente"],
}


def limpar_nome_arquivo(nome):
    return re.sub(r'[\\/*?:"<>|]', "", str(nome)).strip().replace(" ", "_")


def obter_datas_mes_anterior():
    """Retorna a data inicial (1º dia) e final (último dia) do mês anterior no formato DD/MM/AAAA."""
    hoje = datetime.now()
    primeiro_dia_mes_atual = hoje.replace(day=1)
    ultimo_dia_mes_anterior = primeiro_dia_mes_atual - timedelta(days=1)
    primeiro_dia_mes_anterior = ultimo_dia_mes_anterior.replace(day=1)

    data_ini = primeiro_dia_mes_anterior.strftime("%d/%m/%Y")
    data_fim = ultimo_dia_mes_anterior.strftime("%d/%m/%Y")

    return data_ini, data_fim


def obter_competencia_mes_anterior():
    """Retorna o mês anterior ao que a RPA está rodando no formato MM/AAAA."""
    hoje = datetime.now()
    primeiro_dia_mes_atual = hoje.replace(day=1)
    ultimo_dia_mes_anterior = primeiro_dia_mes_atual - timedelta(days=1)
    return ultimo_dia_mes_anterior.strftime("%m/%Y")


def obter_feriados_salvador(ano):
    """
    Retorna a lista de feriados nacionais e municipais de Salvador para o ano especificado.
    """
    feriados = {
        f"01/01/{ano}",  # Confraternização Universal
        f"02/02/{ano}",  # Iemanjá
        f"29/03/{ano}",  # Aniversário de Salvador
        f"21/04/{ano}",  # Tiradentes
        f"01/05/{ano}",  # Dia do Trabalhador
        f"24/06/{ano}",  # São João
        f"02/07/{ano}",  # Independência da Bahia
        f"07/09/{ano}",  # Independência do Brasil
        f"12/10/{ano}",  # Nossa Senhora Aparecida
        f"28/10/{ano}",  # Dia do Servidor Público
        f"02/11/{ano}",  # Finados
        f"15/11/{ano}",  # Proclamação da República
        f"20/11/{ano}",  # Dia da Consciência Negra
        f"08/12/{ano}",  # Nossa Senhora da Conceição
        f"25/12/{ano}",  # Natal
    }

    # Feriados móveis calculados (Algoritmo de Butcher)
    a = ano % 19
    b = ano // 100
    c = ano % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    L = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * L) // 451
    mes_pascoa = (h + L - 7 * m + 114) // 31
    dia_pascoa = ((h + L - 7 * m + 114) % 31) + 1

    data_pascoa = datetime(ano, mes_pascoa, dia_pascoa)
    sexta_santa = data_pascoa - timedelta(days=2)
    carnaval = data_pascoa - timedelta(days=47)
    corpus_christi = data_pascoa + timedelta(days=60)

    feriados.add(sexta_santa.strftime("%d/%m/%Y"))
    feriados.add(carnaval.strftime("%d/%m/%Y"))
    feriados.add(corpus_christi.strftime("%d/%m/%Y"))

    return feriados


def calcular_vencimento_dia_10(data_ref=None):
    """
    Calcula o dia 10 do mês que a RPA está rodando.
    Se for sábado, domingo ou feriado em Salvador, retrocede para o dia útil anterior.
    """
    if data_ref is None:
        data_ref = datetime.now()

    dt_venc = datetime(data_ref.year, data_ref.month, 10)
    feriados_salvador = obter_feriados_salvador(data_ref.year)

    while True:
        data_str = dt_venc.strftime("%d/%m/%Y")
        is_fim_de_semana = dt_venc.weekday() >= 5
        is_feriado = data_str in feriados_salvador

        if not is_fim_de_semana and not is_feriado:
            return data_str

        dt_venc -= timedelta(days=1)


def tratar_imagem_captcha(png_bytes):
    """Trata a imagem usando OpenCV para remover ruídos do CAPTCHA."""
    nparr = np.frombuffer(png_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(
        gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    cleaned = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
    cleaned = cv2.bitwise_not(cleaned)

    _, encoded_img = cv2.imencode(".png", cleaned)
    return encoded_img.tobytes()


def resolver_captcha_com_tratamento(page):
    """Captura, filtra a imagem do CAPTCHA e faz a leitura pelo OCR."""
    try:
        captcha_bytes = page.locator("#img1").screenshot()
        bytes_limpos = tratar_imagem_captcha(captcha_bytes)
        texto_captcha = ocr.classification(bytes_limpos)
        texto_limpo = re.sub(r"\W+", "", texto_captcha).strip()

        print(f"   [🔍] CAPTCHA lido (tratado): {texto_limpo}")
        return texto_limpo
    except Exception as e:
        print(f"   [!] Erro no processamento do CAPTCHA: {e}")
        return None


def salvar_download(download, razao_social):
    if not os.path.exists(PASTA_DOWNLOADS):
        os.makedirs(PASTA_DOWNLOADS)

    nome_base = limpar_nome_arquivo(razao_social)
    nome_original = download.suggested_filename
    _, extensao = os.path.splitext(nome_original)
    if not extensao:
        extensao = ".pdf"

    caminho_arquivo = os.path.join(PASTA_DOWNLOADS, f"{nome_base}{extensao}")

    contador = 1
    while os.path.exists(caminho_arquivo):
        caminho_arquivo = os.path.join(
            PASTA_DOWNLOADS, f"{nome_base}_{contador}{extensao}"
        )
        contador += 1

    download.save_as(caminho_arquivo)
    print(f"   [💾] Arquivo salvo em: {caminho_arquivo}")


def salvar_bytes_direto(conteudo_bytes, razao_social):
    """Salva os bytes do PDF diretamente em disco."""
    if not os.path.exists(PASTA_DOWNLOADS):
        os.makedirs(PASTA_DOWNLOADS)

    nome_base = limpar_nome_arquivo(razao_social)
    caminho_arquivo = os.path.join(PASTA_DOWNLOADS, f"{nome_base}.pdf")

    contador = 1
    while os.path.exists(caminho_arquivo):
        caminho_arquivo = os.path.join(
            PASTA_DOWNLOADS, f"{nome_base}_{contador}.pdf"
        )
        contador += 1

    with open(caminho_arquivo, "wb") as f:
        f.write(conteudo_bytes)
    print(f"   [💾] Arquivo PDF salvo diretamente em: {caminho_arquivo}")


def enviar_email_com_anexos(alteracoes_local2=None):
    if not os.path.exists(PASTA_DOWNLOADS):
        print("\n[!] Pasta arq_rpa não encontrada. Nenhum e-mail enviado.")
        return

    arquivos = [
        os.path.join(PASTA_DOWNLOADS, f)
        for f in os.listdir(PASTA_DOWNLOADS)
        if os.path.isfile(os.path.join(PASTA_DOWNLOADS, f))
    ]

    if not arquivos and not alteracoes_local2:
        print("\n[!] Nenhum arquivo para anexar e nenhuma alteração para reportar.")
        return

    print(
        f"\n[✉️] Preparando e-mail com {len(arquivos)} arquivo(s) anexado(s)..."
    )

    msg = MIMEMultipart()
    msg["From"] = CONFIG_EMAIL["email_remetente"]
    msg["To"] = CONFIG_EMAIL["email_destinatario"]
    msg["Subject"] = "RPA Consultas - Arquivos Baixados"

    corpo = "Olá,\n\nSegue em anexo os arquivos baixados durante a execução do robô.\n\n"

    # Adiciona aviso caso haja alterações no Local 2 (Camaçari)
    if alteracoes_local2:
        corpo += "⚠️ ATENÇÃO: FORAM DETECTADAS ALTERAÇÕES / MENSAGENS DIFERENTES NO LOCAL 2 (CAMAÇARI):\n"
        corpo += "-" * 60 + "\n"
        for item in alteracoes_local2:
            corpo += f"• Empresa: {item['empresa']}\n  Mensagem: {item['mensagem']}\n\n"
        corpo += "-" * 60 + "\n\n"

    corpo += "Atenciosamente,\nRPA Automático."
    msg.attach(MIMEText(corpo, "plain"))

    for caminho_file in arquivos:
        try:
            with open(caminho_file, "rb") as attachment:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(attachment.read())
                encoders.encode_base64(part)

                nome_anexo = os.path.basename(caminho_file)
                part.add_header(
                    "Content-Disposition",
                    f"attachment; filename= {nome_anexo}",
                )
                msg.attach(part)
        except Exception as e:
            print(f"   [X] Erro ao anexar {caminho_file}: {e}")

    try:
        server = smtplib.SMTP(
            CONFIG_EMAIL["servidor_smtp"], CONFIG_EMAIL["porta"]
        )
        server.starttls()
        server.login(
            CONFIG_EMAIL["email_remetente"], CONFIG_EMAIL["senha_app"]
        )
        server.sendmail(
            CONFIG_EMAIL["email_remetente"],
            CONFIG_EMAIL["email_destinatario"],
            msg.as_string(),
        )
        server.quit()
        print("[✓] E-mail enviado com sucesso!")
    except Exception as e:
        log.error(f"Falha no envio do e-mail: {e}")
        print(f"[X] Falha no envio do e-mail: {e}")


def realizar_consulta_guias(page):
    """Garante a navegação até 'Emissão Guias', seleciona o mês atual e clica em CONSULTAR (Salvador)."""
    mes_atual = str(datetime.now().month)

    if not page.is_visible("#ddlMes"):
        if page.is_visible("a[href='../../site/contribuinte/Default.aspx']"):
            print("   [🌐] Clicando em 'Acessar Nota Salvador'...")
            page.click("a[href='../../site/contribuinte/Default.aspx']")
            page.wait_for_load_state("networkidle")

        print("   [📑] Clicando em 'Emissão Guias'...")
        page.click("text=Emissão Guias")
        page.wait_for_load_state("networkidle")

    print(f"   [📅] Selecionando o mês atual ({mes_atual})...")
    page.select_option("#ddlMes", mes_atual)

    print("   [🔍] Clicando no botão 'CONSULTAR'...")
    page.click("#btConsulta")
    page.wait_for_load_state("networkidle")


def fechar_modais_existentes(page):
    """Verifica repetidamente e clica em botões 'Fechar' caso existam avisos na tela."""
    seletor_fechar = "span.p-button-label:has-text('Fechar'), button:has(span.p-button-label:has-text('Fechar'))"

    while True:
        try:
            btn_fechar = page.locator(seletor_fechar).first
            if btn_fechar.is_visible(timeout=3000):
                print("   [❌] Modal/Aviso detectado. Clicando em 'Fechar'...")
                btn_fechar.click()
                page.wait_for_timeout(1000)
            else:
                break
        except Exception:
            break


def localizar_elemento_nos_frames(page, seletor, timeout=10000):
    """
    Percorre a página principal e todos os frames em busca de um seletor.
    Retorna uma tupla (frame_encontrado, locator_encontrado).
    """
    tempo_inicio = datetime.now()
    while (datetime.now() - tempo_inicio).total_seconds() * 1000 < timeout:
        # Tenta na página principal
        try:
            loc = page.locator(seletor).first
            if loc.is_visible():
                return page, loc
        except Exception:
            pass

        # Tenta em cada frame
        for frame in page.frames:
            try:
                loc = frame.locator(seletor).first
                if loc.is_visible():
                    return frame, loc
            except Exception:
                continue

        page.wait_for_timeout(500)

    raise Exception(f"Elemento '{seletor}' não foi encontrado em nenhum frame após {timeout}ms.")


def clicar_item_menu_local_2(page, id_elemento, acao_javascript=None):
    """Clica no item do menu lateral buscando em todos os frames ou disparando JS."""
    seletor = f"#{id_elemento}"
    try:
        frame, loc = localizar_elemento_nos_frames(page, seletor, timeout=8000)
        loc.click()
        print(f"   [✓] Clique com sucesso em '{seletor}' no frame: {getattr(frame, 'name', 'principal')}")
    except Exception as e:
        print(f"   [!] Clique direto no elemento {seletor} falhou. Tentando via script JS...")
        if acao_javascript:
            for frame in page.frames:
                try:
                    frame.evaluate(acao_javascript)
                    print(f"   [✓] Executou Script JS ({acao_javascript}) no frame: {frame.name}")
                    break
                except Exception:
                    continue
        else:
            raise e


def processar_local_2(page, razao_social):
    """
    Executa o fluxo pós-login para o Local 2 (Camaçari / ISS-Web Contribuinte).
    Procura os menus nos frames corretos, preenche a competência e o vencimento ajustado.
    Verifica a mensagem resultante após a consulta.
    """
    print(f"   [🚀] Iniciando navegação pós-login do Local 2 para {razao_social}...")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)

    competencia = obter_competencia_mes_anterior()
    dt_vencimento = calcular_vencimento_dia_10()

    print(f"   [📅] Competência (Mês Anterior): {competencia}")
    print(f"   [📅] Data de Vencimento Ajustada: {dt_vencimento}")

    # 1. Clicar em 'ISS-Web Contribuinte' (#itemTextLink4)
    print("   [📂] Clicando em 'ISS-Web Contribuinte'...")
    clicar_item_menu_local_2(page, "itemTextLink4", "clickOnFolder('4')")
    page.wait_for_timeout(1000)

    # 2. Clicar em 'Escrituração' (#itemTextLink7)
    print("   [📂] Clicando em 'Escrituração'...")
    clicar_item_menu_local_2(page, "itemTextLink7", "clickOnFolder('7')")
    page.wait_for_timeout(1000)

    # 3. Clicar em 'Tomador' (#itemTextLink15)
    print("   [📂] Clicando em 'Tomador'...")
    clicar_item_menu_local_2(page, "itemTextLink15", "clickOnFolder('15')")
    page.wait_for_timeout(1000)

    # 4. Clicar em 'Guia ISS Retenção' (#itemTextLink19)
    print("   [📑] Clicando em 'Guia ISS Retenção'...")
    clicar_item_menu_local_2(
        page,
        "itemTextLink19",
        "clickOnLink('19', '/issweb/calcularGuiaRetencao.tela?goThere=' + Math.round(10000*Math.random()), 'basefrm')"
    )
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)

    # Localiza o formulário no frame 'basefrm'
    frame_form, campo_comp = localizar_elemento_nos_frames(page, "#competenciaFatoGerador", timeout=12000)

    # 5. Preencher a Competência (Mês anterior)
    print(f"   [✏️] Preenchendo competência com: {competencia}")
    campo_comp.click()
    campo_comp.fill("")
    campo_comp.type(competencia, delay=50)

    # 6. Preencher Vencimento (Dia 10 do mês atual ou útil anterior)
    seletor_venc = "#dtVencimento"
    print(f"   [✏️] Preenchendo vencimento com: {dt_vencimento}")
    campo_venc = frame_form.locator(seletor_venc)
    campo_venc.click()
    campo_venc.fill("")
    campo_venc.type(dt_vencimento, delay=50)

    # 7. Clicar em 'Consultar'
    seletor_btn_consultar = "#btnInf_Consultar"
    print("   [🔍] Clicando no botão 'Consultar'...")
    btn_consultar = frame_form.locator(seletor_btn_consultar)
    btn_consultar.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(3000)

    # 8. Capturar e verificar mensagem exibida na tela após consulta
    try:
        seletor_msg = "table.mensagem, td.mensagem, div.mensagem, .msgErro, .msgInformacao, table:has-text('Informação')"
        frame_msg, loc_msg = localizar_elemento_nos_frames(page, seletor_msg, timeout=5000)
        texto_mensagem = loc_msg.inner_text().strip()
        print(f"   [💬] Mensagem capturada na tela:\n{texto_mensagem}")

        # Normaliza textos para comparação flexível (ignorando espaços extras/quebras de linha despadronizadas)
        texto_limpo = " ".join(texto_mensagem.split()).lower()
        frase_esperada_limpa = "informação sucesso. não há iss a pagar."

        if frase_esperada_limpa not in texto_limpo:
            print(f"   [⚠️] ALTERAÇÃO DETECTADA! Mensagem diferente da padrão para {razao_social}.")
            empresas_com_alteracao_local2.append({
                "empresa": razao_social,
                "mensagem": texto_mensagem
            })
        else:
            print("   [✓] Mensagem padrão confirmada (Sem ISS a pagar).")

    except Exception as e_msg:
        print(f"   [!] Não foi possível capturar a mensagem de resultado/aviso: {e_msg}")
        empresas_com_alteracao_local2.append({
            "empresa": razao_social,
            "mensagem": f"Não foi possível confirmar a mensagem na tela. Erro/Status: {e_msg}"
        })

    print(f"   [✓] Fluxo do Local 2 concluído para {razao_social}!")


def navegar_e_pesquisar_dam_local_4(page, data_inicio, data_fim):
    """Executa os cliques de menu e preenchimento de datas para a pesquisa do Local 4."""
    fechar_modais_existentes(page)

    seletor_subst = "a#dropdown01.nav-link.dropdown-toggle:has-text('Substituição Tributária'), a:has-text('Substituição Tributária')"
    print("   [📂] Clicando em 'Substituição Tributária'...")
    page.wait_for_selector(seletor_subst, state="visible", timeout=10000)
    page.click(seletor_subst)
    page.wait_for_timeout(500)

    seletor_dam = "a.dropdown-item[href='#/declaracaoSubstituicao'], a:has-text('Emissão DAM')"
    print("   [📑] Clicando em 'Emissão DAM'...")
    page.wait_for_selector(seletor_dam, state="visible", timeout=10000)
    page.click(seletor_dam)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1500)

    fechar_modais_existentes(page)

    campo_ini = "input[placeholder='Data Inicial']"
    campo_fim = "input[placeholder='Data Final']"

    page.wait_for_selector(campo_ini, state="visible", timeout=10000)

    page.click(campo_ini)
    page.fill(campo_ini, "")
    page.type(campo_ini, data_inicio, delay=50)

    page.click(campo_fim)
    page.fill(campo_fim, "")
    page.type(campo_fim, data_fim, delay=50)

    seletor_pesquisar = "button:has(span.p-button-label:has-text('Pesquisar')), span.p-button-label:has-text('Pesquisar')"
    print("   [🔍] Clicando em 'Pesquisar'...")
    page.click(seletor_pesquisar)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(3000)


def processar_local_4(page, razao_social):
    """Executa o fluxo pós-login para o Local 4 (Simões Filho / Cloud EL)."""
    print(f"   [🚀] Iniciando fluxo pós-login para Local 4 ({razao_social})...")
    page.wait_for_load_state("networkidle")

    data_inicio, data_fim = obter_datas_mes_anterior()
    print(f"   [📅] Período a consultar: {data_inicio} até {data_fim}")

    navegar_e_pesquisar_dam_local_4(page, data_inicio, data_fim)

    seletor_checkbox = ".p-checkbox-icon, .p-checkbox, div.p-checkbox-box"
    seletor_gerar_dam = "button:has(span.p-button-label:has-text('Gerar DAM')), button.p-button-success, span.p-button-label:has-text('Gerar DAM')"

    qtd_registros = page.locator(seletor_checkbox).count()

    if qtd_registros == 0:
        print("   [ℹ] Nenhum registro/checkbox encontrado para o período.")
        return

    print(f"   [📋] Encontrado(s) {qtd_registros} registro(s) para processamento.")

    for idx in range(qtd_registros):
        print(f"\n   --- Processando Registro {idx + 1} de {qtd_registros} ---")

        if idx > 0:
            print("   [🔄] Saindo e entrando novamente na tela para processar o próximo item...")
            navegar_e_pesquisar_dam_local_4(page, data_inicio, data_fim)

        try:
            checkboxes = page.locator(seletor_checkbox)
            if checkboxes.count() > idx and checkboxes.nth(idx).is_visible(timeout=5000):
                print(f"   [☑] Clicando no checkbox (índice {idx})...")
                checkboxes.nth(idx).click()
                page.wait_for_timeout(1000)

                if page.locator(seletor_gerar_dam).count() > 0 and page.locator(seletor_gerar_dam).first.is_visible(timeout=5000):
                    print("   [📄] Clicando no botão 'Gerar DAM'...")
                    try:
                        with page.expect_download(timeout=10000) as download_info:
                            page.locator(seletor_gerar_dam).first.click()
                        download = download_info.value
                        salvar_download(download, razao_social)
                        print(f"   [✓] Registro {idx + 1} baixado com sucesso!")
                    except Exception as err_dl:
                        print(f"   [!] Erro no disparo do download para registro {idx + 1}: {err_dl}")
                else:
                    print("   [!] Botão 'Gerar DAM' não ficou visível após marcar o checkbox.")
            else:
                print(f"   [!] Checkbox do índice {idx} não está mais visível.")
        except Exception as e_item:
            print(f"   [❌] Falha no processamento do registro {idx + 1}: {e_item}")

    print(f"   [✓] Concluído o processamento de todos os registros do Local 4 para {razao_social}!")


def executar_rpa():
    caminho_planilha = os.path.join(BASE_DIR, CONFIG["planilha"])

    if not os.path.exists(caminho_planilha):
        print(f"Erro: a planilha '{caminho_planilha}' não foi encontrada.")
        log.critical(f"Planilha não encontrada: {caminho_planilha}")
        return

    df = pd.read_excel(
        caminho_planilha,
        header=1,
        dtype={
            "CNPJ/CPF/CEI/CAEPF": str,
            "SENHA SEFAZ": str,
            "RAZAO": str,
            "LOCAL": float,
        },
    )

    df = df.dropna(subset=["CNPJ/CPF/CEI/CAEPF"])

    resultados = []

    with sync_playwright() as p:
        # Usa o Google Chrome já instalado na máquina (channel="chrome"),
        # em vez do Chromium interno do Playwright — assim não é preciso
        # baixar/embutir um navegador separado para distribuir o .exe.
        browser = p.chromium.launch(headless=False, channel="chrome")
        context = browser.new_context(accept_downloads=True)

        for index, linha in df.iterrows():
            cpf_cnpj = str(linha["CNPJ/CPF/CEI/CAEPF"]).strip()
            senha = str(linha["SENHA SEFAZ"]).strip()
            razao_social = str(linha.get("RAZAO", "Empresa")).strip()

            try:
                local_num = int(linha["LOCAL"])
            except (ValueError, TypeError):
                local_num = 1

            url_destino = URLS_LOCAIS.get(local_num, URLS_LOCAIS[1])

            # Loop para repetir 2 vezes em cada CNPJ/CPF
            for execucao in range(1, 3):
                print(
                    f"\n[+] Processando ({index + 1}/{len(df)}) - Execução {execucao}/2: {razao_social}"
                )
                print(f"    CNPJ/CPF: {cpf_cnpj} | Local: {local_num}")

                try:
                    resultado_execucao = processar_empresa(
                        context, cpf_cnpj, senha, razao_social, local_num, url_destino
                    )
                    resultados.append({
                        "Linha": index + 2,
                        "Razao_Social": razao_social,
                        "CPF_CNPJ": cpf_cnpj,
                        "Local": local_num,
                        "Execucao": execucao,
                        "Status": "OK" if resultado_execucao else "LOGIN_FALHOU",
                        "Erro": "",
                    })
                except Exception as erro_geral:
                    log.error(
                        f"Erro inesperado processando {razao_social} ({cpf_cnpj}), "
                        f"execução {execucao}: {erro_geral}"
                    )
                    print(f"   [❌] Erro inesperado, seguindo para o próximo: {erro_geral}")
                    resultados.append({
                        "Linha": index + 2,
                        "Razao_Social": razao_social,
                        "CPF_CNPJ": cpf_cnpj,
                        "Local": local_num,
                        "Execucao": execucao,
                        "Status": "ERRO",
                        "Erro": f"{type(erro_geral).__name__}: {erro_geral}",
                    })

        browser.close()

    salvar_relatorio_execucao(resultados)
    enviar_email_com_anexos(alteracoes_local2=empresas_com_alteracao_local2)


def salvar_relatorio_execucao(resultados):
    if not resultados:
        print("\nNenhuma empresa foi processada, relatório de execução não gerado.")
        return

    df_resultado = pd.DataFrame(resultados)

    nome_arquivo = f"relatorio_execucao_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    caminho_relatorio = os.path.join(BASE_DIR, nome_arquivo)

    df_resultado.to_excel(caminho_relatorio, index=False)

    total = len(resultados)
    erros = [r for r in resultados if r["Status"] in ("ERRO", "LOGIN_FALHOU")]

    print("\n══════════════════════════════════════════")
    print("RESUMO DA EXECUÇÃO")
    print("══════════════════════════════════════════")
    print(f"Total processado: {total}")
    print(f"OK: {total - len(erros)}")
    print(f"Com erro/login falhou: {len(erros)}")
    print(f"Relatório salvo em: {caminho_relatorio}")

    log.info(f"Execução finalizada. Total={total} OK={total - len(erros)} Erros={len(erros)}")

    if erros:
        print("\nEmpresas com erro:")
        for r in erros:
            print(f" - {r['CPF_CNPJ']} ({r['Razao_Social']}) exec {r['Execucao']}: {r['Status']} {r['Erro']}")

    print("══════════════════════════════════════════")


def processar_empresa(context, cpf_cnpj, senha, razao_social, local_num, url_destino):
    """Faz login e processa uma empresa em uma execução. Retorna True/False
    conforme o login teve sucesso ou não. Garante que a página seja
    fechada mesmo se algo der errado no meio do processamento."""

    page = context.new_page()
    page.on(
        "download",
        lambda download, r=razao_social: salvar_download(download, r),
    )

    try:
        sucesso_login = False
        max_tentativas = int(CONFIG["max_tentativas_login"])

        for tentativa in range(1, max_tentativas + 1):
            print(f"   [👉] Tentativa de Login {tentativa}/{max_tentativas}...")

            try:
                page.goto(url_destino, wait_until="networkidle")

                if local_num == 2:
                    seletor_usuario_l2 = "#usuario"
                    seletor_senha_l2 = "#senha"
                    seletor_btn_entrar_l2 = "#btnInf_Entrar"

                    page.wait_for_selector(seletor_usuario_l2, timeout=10000)

                    print("   [👤] Clicando e preenchendo o usuário (CPF/CNPJ)...")
                    page.click(seletor_usuario_l2)
                    page.fill(seletor_usuario_l2, cpf_cnpj)

                    print("   [🔑] Clicando e preenchendo a senha...")
                    page.click(seletor_senha_l2)
                    page.fill(seletor_senha_l2, senha)

                    print("   [🚪] Clicando em 'Entrar'...")
                    page.click(seletor_btn_entrar_l2)
                    page.wait_for_load_state("networkidle")
                    page.wait_for_timeout(3000)

                    sucesso_login = True
                    print("   [✓] Login efetuado com SUCESSO no Local 2!")
                    break

                elif local_num == 4:
                    seletor_user = "input[placeholder*='CPF'], input[placeholder*='CNPJ'], #username, #txtLogin, input[type='text']"
                    seletor_pass = "input[type='password'], #password, #txtSenha"

                    page.wait_for_selector(seletor_user, timeout=10000)
                    page.fill(seletor_user, cpf_cnpj)
                    page.fill(seletor_pass, senha)

                    btn_login = "button:has-text('Entrar'), button:has-text('Login'), #cmdLogin"
                    page.click(btn_login)
                    page.wait_for_timeout(3000)

                    sucesso_login = True
                    print("   [✓] Login efetuado com SUCESSO!")
                    break
                else:
                    page.fill("#txtLogin", cpf_cnpj)
                    page.fill("#txtSenha", senha)

                    texto_captcha = resolver_captcha_com_tratamento(page)

                    if texto_captcha:
                        page.fill("#tbCaptcha", texto_captcha)
                        page.click("#cmdLogin")
                        page.wait_for_timeout(3000)

                        if not page.is_visible("#txtLogin"):
                            print("   [✓] Login efetuado com SUCESSO!")
                            sucesso_login = True
                            break
                        else:
                            print(
                                "   [!] CAPTCHA incorreto, recarregando para tentar novamente..."
                            )

            except Exception as e:
                print(f"   [X] Erro na tentativa {tentativa}: {e}")

        # -------------------------------------------------------------
        # AÇÕES APÓS O LOGIN
        # -------------------------------------------------------------
        if sucesso_login:
            try:
                if local_num == 4:
                    processar_local_4(page, razao_social)
                elif local_num == 2:
                    processar_local_2(page, razao_social)
                else:
                    realizar_consulta_guias(page)

                    seletor_emitir = "a:has-text('EMITIR GUIA')"
                    qtd_guias = page.locator(seletor_emitir).count()

                    if qtd_guias == 0:
                        print(
                            f"   [ℹ️] Nenhuma guia encontrada para {razao_social}."
                        )
                    else:
                        print(
                            f"   [📋] Encontrada(s) {qtd_guias} guia(s) para emissão."
                        )

                        for i in range(qtd_guias):
                            print(
                                f"\n   --- Processando Guia {i + 1} de {qtd_guias} ---"
                            )

                            if i > 0:
                                print(
                                    "   [🔄] Repetindo fluxo de seleção de mês e consulta..."
                                )
                                realizar_consulta_guias(page)

                            print(
                                f"   [📄] Clicando em 'EMITIR GUIA' (Índice {i})..."
                            )
                            page.locator(seletor_emitir).nth(i).click()
                            page.wait_for_load_state("networkidle")

                            if page.is_visible("#btGerarGuia"):
                                print("   [🖨️] Clicando em 'IMPRIMIR GUIA'...")
                                page.click("#btGerarGuia")
                                page.wait_for_load_state("networkidle")

                            page.wait_for_timeout(2000)

                            baixou_com_sucesso = False
                            seletor_btn_pdf = '#download, button#download, cr-icon-button#download, [aria-label="Fazer download"], [title="Fazer download"]'

                            try:
                                print("   [⬇] Tentando clicar no botão de download do visualizador de PDF...")
                                with page.expect_download(timeout=8000) as download_info:
                                    btn_dl = page.locator(seletor_btn_pdf).first
                                    if btn_dl.is_visible(timeout=3000):
                                        btn_dl.click()
                                    else:
                                        for f_item in page.frames:
                                            btn_f = f_item.locator(seletor_btn_pdf).first
                                            if btn_f.is_visible(timeout=1000):
                                                btn_f.click()
                                                break

                                download = download_info.value
                                salvar_download(download, razao_social)
                                baixou_com_sucesso = True
                            except Exception as err_pdf1:
                                print(f"   [!] Clique no botão do visualizador não disparou download nativo: {err_pdf1}")

                            if not baixou_com_sucesso:
                                try:
                                    print("   [⌨️] Tentando acionar download via atalho 'Control+s'...")
                                    with page.expect_download(timeout=5000) as download_info:
                                        page.keyboard.press("Control+s")
                                    download = download_info.value
                                    salvar_download(download, razao_social)
                                    baixou_com_sucesso = True
                                except Exception as err_pdf2:
                                    print(f"   [!] Atalho de teclado não concluiu o download: {err_pdf2}")

                            if not baixou_com_sucesso:
                                try:
                                    print("   [🔗] Tentando extrair a URL do PDF (embed/iframe) para download via requisição...")
                                    elem_pdf = page.locator("embed, iframe#ifraPrintPDF, iframe, object").first
                                    pdf_src = None
                                    if elem_pdf.count() > 0:
                                        pdf_src = elem_pdf.get_attribute("src")

                                    if pdf_src:
                                        if not pdf_src.startswith("http"):
                                            pdf_src = "https://nfse.salvador.ba.gov.br/site/contribuinte/guia/" + pdf_src.lstrip("/")

                                        res = page.request.get(pdf_src)
                                        if res.ok:
                                            salvar_bytes_direto(res.body(), razao_social)
                                            baixou_com_sucesso = True
                                except Exception as err_pdf3:
                                    print(f"   [!] Falha ao tentar requisição direta do PDF: {err_pdf3}")

                            if page.is_visible("#btVoltar"):
                                print("   [🔙] Clicando em 'VOLTAR'...")
                                page.click("#btVoltar")
                                page.wait_for_load_state("networkidle")

                        print(
                            f"   [✓] Todas as guias ({qtd_guias}) foram processadas para {razao_social}!"
                        )

            except Exception as e:
                log.error(f"Erro ao processar dados para {razao_social}: {e}")
                print(
                    f"   [❌] Erro ao processar dados para {razao_social}: {e}"
                )
        else:
            print(
                f"   [❌] Não foi possível logar para {razao_social} após {max_tentativas} tentativas."
            )

        return sucesso_login

    finally:
        page.close()


if __name__ == "__main__":
    executar_rpa()