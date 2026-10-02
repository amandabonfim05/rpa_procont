import asyncio
import os
import re
import shutil
import time
import requests
from datetime import datetime

import pandas as pd
from playwright.async_api import async_playwright

from rpa_config import CONFIG, caminho, configurar_log, salvar_relatorio_execucao

ARQUIVO_PLANILHA = caminho(CONFIG["planilha_fluxo4"])
PASTA_DESTINO = caminho("parcelamento")
URL_REGULARIZE = "https://www.regularize.pgfn.gov.br"

SENHAS_PGFN = CONFIG["senhas_pgfn"]
MAX_TENTATIVAS = int(CONFIG["max_tentativas"])

API_KEY_2CAPTCHA = CONFIG["api_key_2captcha"]
SITE_KEY_HCAPTCHA = "00000000-0000-0000-0000-000000000000"

log = configurar_log("rpa2dif")


def encontrar_coluna_documento(df):
    colunas = [str(col).strip() for col in df.columns]
    possibilidades = ["CPF/CNPJ", "CPF CNPJ", "CPF_CNPJ", "CPF", "CNPJ", "Documento", "documento"]
    for possibilidade in possibilidades:
        for col in colunas:
            if col.lower() == possibilidade.lower():
                return col
    return None


def encontrar_coluna_razao(df):
    colunas = [str(col).strip() for col in df.columns]
    possibilidades = ["RAZAO", "RAZÃO", "RAZAO SOCIAL", "RAZÃO SOCIAL", "NOME", "CLIENTE", "NOME_CLIENTE"]
    for possibilidade in possibilidades:
        for col in colunas:
            if col.lower() == possibilidade.lower():
                return col
    return None


def encontrar_coluna_tipo(df):
    colunas = [str(col).strip() for col in df.columns]
    for col in colunas:
        if col.lower() == "tipo":
            return col
    return None


def tipos_de_fluxo(valor):
    if pd.isna(valor):
        return set()
    partes = str(valor).strip().lower().split(";")
    return {parte.strip() for parte in partes if parte.strip()}


def limpar_cpf_cnpj(valor):
    if pd.isna(valor):
        return ""
    valor = str(valor).strip()
    if valor.endswith(".0"):
        valor = valor[:-2]
    return re.sub(r"\D", "", valor)


def sanitizar_nome_arquivo(nome):
    if pd.isna(nome) or not str(nome).strip():
        return ""
    return re.sub(r'[\\/*?:"<>|]', "", str(nome)).strip()


async def obter_todos_os_contextos(page):
    paginas = page.context.pages
    contextos = []
    for p in paginas:
        try:
            await p.wait_for_load_state("domcontentloaded", timeout=2000)
        except Exception:
            pass
        contextos.append(p)
        contextos.extend(p.frames)
    return contextos


async def clicar_elemento_seguro(page, seletor_ou_locator, nome_descricao="Elemento"):
    contextos = await obter_todos_os_contextos(page)
    for ctx in contextos:
        try:
            if isinstance(seletor_ou_locator, str):
                alvo = ctx.locator(seletor_ou_locator).first
            else:
                alvo = seletor_ou_locator

            if await alvo.count() > 0 and await alvo.is_visible():
                try:
                    await alvo.scroll_into_view_if_needed()
                except Exception:
                    pass

                try:
                    await alvo.click(timeout=5000)
                    print(f"   -> Clicado com sucesso em '{nome_descricao}'.")
                    return True
                except Exception:
                    try:
                        await alvo.click(force=True, timeout=5000)
                        print(f"   -> Clique forçado em '{nome_descricao}'.")
                        return True
                    except Exception:
                        await alvo.evaluate("el => el.click()")
                        print(f"   -> Clique via JS em '{nome_descricao}'.")
                        return True
        except Exception:
            continue

    print(f"   -> [AVISO] Não foi possível clicar em '{nome_descricao}'.")
    return False


async def passar_mouse_elemento(page, seletor_ou_locator, nome_descricao="Elemento"):
    contextos = await obter_todos_os_contextos(page)
    for ctx in contextos:
        try:
            if isinstance(seletor_ou_locator, str):
                alvo = ctx.locator(seletor_ou_locator).first
            else:
                alvo = seletor_ou_locator

            if await alvo.count() > 0 and await alvo.is_visible():
                try:
                    await alvo.scroll_into_view_if_needed()
                except Exception:
                    pass

                try:
                    await alvo.hover(timeout=5000)
                    print(f"   -> Mouse posicionado sobre '{nome_descricao}'.")
                    return True
                except Exception:
                    await alvo.evaluate("""el => {
                        let evOver = new MouseEvent('mouseover', {bubbles: true, cancelable: true, view: window});
                        let evEnter = new MouseEvent('mouseenter', {bubbles: true, cancelable: true, view: window});
                        el.dispatchEvent(evOver);
                        el.dispatchEvent(evEnter);
                    }""")
                    print(f"   -> Mouseover acionado via JS em '{nome_descricao}'.")
                    return True
        except Exception:
            continue

    print(f"   -> [AVISO] Não foi possível posicionar o mouse sobre '{nome_descricao}'.")
    return False


def resolver_hcaptcha_api(sitekey, page_url):
    if not API_KEY_2CAPTCHA:
        return None
    try:
        print("   [2CAPTCHA] Enviando requisição para solução automática do captcha...")
        res = requests.post("http://2captcha.com/in.php", data={
            'key': API_KEY_2CAPTCHA,
            'method': 'hcaptcha',
            'sitekey': sitekey,
            'pageurl': page_url,
            'json': 1
        }).json()

        if res.get("status") != 1:
            print(f"   [2CAPTCHA] Erro ao enviar captcha: {res}")
            return None

        captcha_id = res["request"]
        url_res = f"http://2captcha.com/res.php?key={API_KEY_2CAPTCHA}&action=get&id={captcha_id}&json=1"

        for _ in range(30):
            time.sleep(5)
            r = requests.get(url_res).json()
            if r.get("status") == 1:
                print("   [2CAPTCHA] Token do hCAPTCHA obtido com sucesso!")
                return r["request"]
            elif r.get("request") != "CAPCHA_NOT_READY":
                break
    except Exception as e:
        print(f"   [2CAPTCHA] Falha na comunicação com a API: {e}")
    return None


async def injetar_token_hcaptcha(page, token):
    await page.evaluate(f"""
        (token) => {{
            let hInput = document.querySelector('textarea[name="h-captcha-response"]');
            if (hInput) {{
                hInput.value = token;
                hInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
                hInput.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }}

            let gInput = document.querySelector('textarea[name="g-recaptcha-response"]');
            if (gInput) {{
                gInput.value = token;
                gInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
                gInput.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }}

            if (window.hcaptcha && typeof window.hcaptcha.getRespByWidgetId === 'function') {{
                try {{
                    let widgetIds = Object.keys(window.hcaptcha._widgets || {{}});
                    if (widgetIds.length > 0) {{
                        let wId = widgetIds[0];
                        if (window.hcaptcha._widgets[wId].callback) {{
                            window.hcaptcha._widgets[wId].callback(token);
                        }}
                    }}
                }} catch (e) {{}}
            }}
        }}
    """, token)


async def tratar_hcaptcha_se_existir(page):
    hcaptcha_frame = page.locator("iframe[src*='hcaptcha.com'], iframe[title*='hCaptcha']").first
    if await hcaptcha_frame.count() > 0 and await hcaptcha_frame.is_visible():
        print("\n   [ATENÇÃO] hCaptcha detectado na tela!")

        if API_KEY_2CAPTCHA:
            token = resolver_hcaptcha_api(SITE_KEY_HCAPTCHA, page.url)
            if token:
                await injetar_token_hcaptcha(page, token)
                await page.wait_for_timeout(2000)
                return

        print("   👉 Por favor, resolva o hCaptcha na janela do Chrome...")
        while await hcaptcha_frame.count() > 0 and await hcaptcha_frame.is_visible():
            await page.wait_for_timeout(2000)

        print("   ✅ hCaptcha validado! Prosseguindo...\n")


async def verificar_mensagem_erro_login(page):
    seletores_erro = [
        ".alert-danger",
        ".mensagem-erro",
        ".ui-messages-error",
        "div[role='alert']",
        "span.text-danger"
    ]
    for s in seletores_erro:
        elem = page.locator(s).first
        if await elem.count() > 0 and await elem.is_visible():
            texto = await elem.inner_text()
            if texto and any(p in texto.lower() for p in ["inválid", "incorret", "não confere", "erro", "falha", "hcaptcha", "captcha"]):
                return texto.strip()
    return None


async def realizar_login_pgfn(page, cnpj_cliente):
    print("\n--- INICIANDO LOGIN PGFN ---")
    await page.wait_for_timeout(2000)

    seletor_tab_pj = "#tabPJ-link, a[role='tab']:has-text('Pessoa Jurídica')"
    await clicar_elemento_seguro(page, seletor_tab_pj, "Aba Pessoa Jurídica")
    await page.wait_for_timeout(1000)

    xpath_input_cnpj = "xpath=//input[@formcontrolname='identificacao' or contains(@placeholder, 'CNPJ')]"
    input_cnpj = page.locator(xpath_input_cnpj).first
    await input_cnpj.wait_for(state="visible", timeout=10000)

    xpath_input_senha_pgfn = "xpath=//input[@formcontrolname='senha' or @type='password']"
    input_senha_pgfn = page.locator(xpath_input_senha_pgfn).first

    xpath_btn_continuar_pgfn = "xpath=//button[contains(@class, 'btn-primary') and contains(., 'Continuar')]"

    for i, senha in enumerate(SENHAS_PGFN, start=1):
        print(f"\n   Tentativa {i} de {len(SENHAS_PGFN)} com senha...")

        await input_cnpj.fill("")
        await input_cnpj.fill(cnpj_cliente)
        print(f"   🔑 CNPJ '{cnpj_cliente}' preenchido!")

        await input_senha_pgfn.wait_for(state="visible", timeout=10000)
        await input_senha_pgfn.fill("")
        await input_senha_pgfn.fill(senha)
        print("   🔑 Senha preenchida!")
        await page.wait_for_timeout(1000)

        await tratar_hcaptcha_se_existir(page)

        btn_continuar_pgfn = page.locator(xpath_btn_continuar_pgfn).first
        await btn_continuar_pgfn.wait_for(state="visible", timeout=10000)

        try:
            await btn_continuar_pgfn.click(timeout=5000)
        except Exception:
            await btn_continuar_pgfn.evaluate("el => el.click()")

        print("   ➡️ Botão 'Continuar' clicado. Aguardando resposta...")
        await page.wait_for_timeout(4000)

        msg_erro = await verificar_mensagem_erro_login(page)

        if not msg_erro and (await input_senha_pgfn.count() == 0 or not await input_senha_pgfn.is_visible()):
            print("   ✅ Login efetuado com SUCESSO!")
            return True

        if msg_erro:
            print(f"   ❌ Falha no login com a senha {i}: {msg_erro}")
        else:
            print(f"   ⚠️ A senha {i} não avançou a página. Tentando a próxima...")

        await page.wait_for_timeout(1000)

    raise Exception(f"Não foi possível realizar o login para o CNPJ {cnpj_cliente} com nenhuma das senhas fornecidas.")


async def selecionar_linha_grid_especifica(contexto, indice_alvo=0):
    try:
        linhas = contexto.locator("tr.conteudoGrid, tr[data-rk], tr[role='row'].ui-widget-content")
        total_linhas = await linhas.count()
        encontradas = 0

        for idx in range(total_linhas):
            linha = linhas.nth(idx)
            if await linha.is_visible():
                try:
                    texto = await linha.inner_text()
                except Exception:
                    texto = await linha.text_content()

                texto_upper = " ".join((texto or "").split()).upper()

                if "DEFERIDA" in texto_upper and "CONSOLIDADA" in texto_upper:
                    if encontradas == indice_alvo:
                        print(f"   [SELEÇÃO DA LINHA INTERNA] Selecionando negociação DEFERIDA E CONSOLIDADA (#{indice_alvo + 1})...")
                        celula = linha.locator("td div.ui-dt-c").first
                        if await celula.count() > 0:
                            try:
                                await celula.click(timeout=3000)
                            except Exception:
                                await celula.evaluate("el => el.click()")
                        else:
                            try:
                                await linha.click(timeout=3000)
                            except Exception:
                                await linha.evaluate("el => el.click()")

                        return True
                    encontradas += 1

    except Exception as e:
        print(f"   [AVISO] Erro ao tentar selecionar a linha 'DEFERIDA E CONSOLIDADA' na grid interna: {e}")
    
    return False


async def baixar_darfs_elegiveis_regularize(page, nome_identificador_arquivo):
    """
    Analisar a tabela e emitir a parcela que atende às condições:
    1. Possui o botão com o ícone de emissão de DARF (imprimir.png / NNimpressaoDarf).
    2. O mês e ano de vencimento é MENOR OU IGUAL ao mês/ano atual da execução.
    """
    hoje = datetime.now().date()
    mes_atual = hoje.month
    ano_atual = hoje.year

    print(f"\n   [DARF PGFN] Buscando parcelas com botão de emissão ativos no mês/ano $\\le$ {mes_atual:02d}/{ano_atual}...")

    contextos = await obter_todos_os_contextos(page)
    padroes_data = [
        r"\b(\d{2}/\d{2}/\d{4})\b",
        r"\b(\d{2}-\d{2}-\d{4})\b",
        r"\b(\d{2}\.\d{2}\.\d{4})\b",
    ]

    total_baixados = 0
    seletor_btn_impressao = 'a[id*="NNimpressaoDarf"], img[src*="imprimir.png"], img[title*="Não emitido"], a:has(img[src*="imprimir"])'

    for ctx in contextos:
        try:
            linhas = ctx.locator("tr")
            qtd_linhas = await linhas.count()

            if qtd_linhas == 0:
                continue

            for i in range(qtd_linhas):
                linha = linhas.nth(i)
                if not await linha.is_visible():
                    continue

                btn_impressao = linha.locator(seletor_btn_impressao).first
                tem_btn_impressao = await btn_impressao.count() > 0 and await btn_impressao.is_visible()

                if not tem_btn_impressao:
                    continue

                texto_linha = await linha.inner_text()
                texto_normalizado = " ".join((texto_linha or "").split()).upper()

                datas_encontradas = []
                for padrao in padroes_data:
                    matches = re.findall(padrao, texto_normalizado)
                    for m in matches:
                        v_data = m.replace("-", "/").replace(".", "/")
                        try:
                            d_obj = datetime.strptime(v_data, "%d/%m/%Y").date()
                            datas_encontradas.append(d_obj)
                        except ValueError:
                            continue

                if not datas_encontradas:
                    print("   -> Não foi possível identificar data na linha. Verificando botão...")
                    data_ref = hoje
                else:
                    data_ref = datas_encontradas[0]

                # Filtro: Apenas parcelas cujo vencimento seja menor ou igual ao mês/ano atual
                ano_parcela = data_ref.year
                mes_parcela = data_ref.month

                eh_mes_anterior_ou_atual = (ano_parcela < ano_atual) or (ano_parcela == ano_atual and mes_parcela <= mes_atual)

                if not eh_mes_anterior_ou_atual:
                    print(f"   -> Parcela {data_ref.strftime('%d/%m/%Y')} é de mês futuro ({mes_parcela:02d}/{ano_parcela} > {mes_atual:02d}/{ano_atual}). Pulando...")
                    continue

                print(f"   [ELEGÍVEL] Parcela {data_ref.strftime('%d/%m/%Y')} encontrada com botão ativo no mês vigente ({mes_atual:02d}/{ano_atual}). Emitindo...")

                try:
                    await btn_impressao.click(timeout=3000)
                except Exception:
                    try:
                        celula_alvo = linha.locator("td div.ui-dt-c").first
                        if await celula_alvo.count() > 0:
                            await celula_alvo.click(timeout=3000)
                        else:
                            await linha.click(timeout=3000)
                    except Exception:
                        await linha.evaluate("""el => {
                            let btn = el.querySelector('a[id*="NNimpressaoDarf"], img[src*="imprimir.png"]') || el;
                            btn.click();
                        }""")

                await page.wait_for_timeout(1500)

                print("   [ELEGÍVEL] Clicando no botão 'Emitir' (btnEmitir)...")
                seletor_btn_emitir = 'button[id*="btnEmitir"], #formResumoParcelamentoDarf\\:btnEmitir, button:has-text("Emitir")'
                
                clicou_emitir = await clicar_elemento_seguro(page, seletor_btn_emitir, "Botão Emitir")
                
                if not clicou_emitir:
                    btn_emitir_ctx = ctx.locator(seletor_btn_emitir).first
                    if await btn_emitir_ctx.count() > 0:
                        try:
                            await btn_emitir_ctx.click(timeout=3000)
                        except Exception:
                            await btn_emitir_ctx.evaluate("el => el.click()")

                await page.wait_for_timeout(2500)

                print("   [ELEGÍVEL] Clicando no link para baixar o arquivo DARF (emitirDarf)...")
                seletor_link_download = 'a[id*="emitirDarf"], #formResumoParcelamentoDarf\\:emitirDarf'

                os.makedirs(PASTA_DESTINO, exist_ok=True)
                sufixo = f"_{total_baixados + 1}" if total_baixados > 0 else ""
                nome_arquivo = f"{sanitizar_nome_arquivo(nome_identificador_arquivo)}_PGFN{sufixo}.pdf"
                caminho_completo = os.path.join(PASTA_DESTINO, nome_arquivo)

                try:
                    async with page.expect_download(timeout=15000) as download_info:
                        link_download = ctx.locator(seletor_link_download).first
                        if await link_download.count() > 0:
                            try:
                                await link_download.click(timeout=4000)
                            except Exception:
                                await link_download.evaluate("el => el.click()")
                        else:
                            await clicar_elemento_seguro(page, seletor_link_download, "Link Download DARF")

                    download = await download_info.value
                    await download.save_as(caminho_completo)
                    print(f"   [SUCESSO] DARF PGFN salvo com sucesso em: {caminho_completo}")
                    total_baixados += 1
                    await page.wait_for_timeout(2000)

                except Exception as erro_dl:
                    print(f"   Aviso: Download do DARF não capturado ou expirou: {erro_dl}")

            if total_baixados > 0:
                break

        except Exception as e:
            print(f"   Aviso ao ler tabela de DARFs PGFN: {e}")

    return total_baixados


async def navegar_ate_grid_principal(page):
    print("1. Clicando em 'Ciente'...")
    await clicar_elemento_seguro(page, 'button.btn.btn-primary:has-text("Ciente")', "Ciente")
    await page.wait_for_timeout(1500)

    print("2. Clicando em 'Fechar'...")
    await clicar_elemento_seguro(page, 'button.btn.btn-primary:has-text("Fechar")', "Fechar")
    await page.wait_for_timeout(1500)

    print("3. Clicando em 'Negociar Dívida'...")
    await clicar_elemento_seguro(page, 'span.place-info-box-text:has-text("Negociar Dívida")', "Negociar Dívida")
    await page.wait_for_timeout(2000)

    print("4. Clicando em 'Acessar'...")
    await clicar_elemento_seguro(page, 'button.btn.btn-primary.mt-2:has-text("Acessar")', "Acessar")
    await page.wait_for_timeout(3000)

    print("5. Clicando em 'CONSULTAR'...")
    await clicar_elemento_seguro(page, 'span.place-info-box-text:has-text("CONSULTAR")', "CONSULTAR")
    await page.wait_for_timeout(2000)

    print("6. Clicando em 'Continuar'...")
    pagina_alvo = page
    try:
        async with page.context.expect_page(timeout=5000) as popup_info:
            await clicar_elemento_seguro(page, 'button.btn.btn-primary:has-text("Continuar")', "Continuar")
        
        nova_aba = await popup_info.value
        await nova_aba.wait_for_load_state("domcontentloaded")
        print(f"   [POP-UP DETECTADO] Sisparnet aberto em nova guia: {nova_aba.url}")
        pagina_alvo = nova_aba
    except Exception:
        print("   [INFO] Continuando no mesmo contexto/aba...")

    print("   Aguardando o carregamento da tabela de negociações no Sisparnet...")
    await page.wait_for_timeout(6000)
    return pagina_alvo


async def contar_negociacoes_deferidas(pagina_alvo):
    contextos = await obter_todos_os_contextos(pagina_alvo)
    count = 0

    for ctx in contextos:
        try:
            linhas = ctx.locator("tr.ui-widget-content, tr.conteudoGrid, tr[role='row']")
            qtd = await linhas.count()

            for i in range(qtd):
                l = linhas.nth(i)
                if not await l.is_visible():
                    continue

                try:
                    texto = await l.inner_text()
                except Exception:
                    texto = await l.text_content()

                texto_upper = " ".join((texto or "").split()).upper()

                if "SITUAÇÃO DA CONTA" in texto_upper or "VINCULAÇÃO" in texto_upper:
                    continue

                if "DEFERIDA" in texto_upper and "CONSOLIDADA" in texto_upper:
                    count += 1

        except Exception as e:
            print(f"   Aviso ao contar negociações: {e}")

    return count


async def processar_negocicao_por_indice(pagina_alvo, idx_deferida, total_deferidas, nome_identificador_arquivo):
    print(f"\n   >>> PROCESSANDO DEFERIDA E CONSOLIDADA {idx_deferida + 1} DE {total_deferidas} <<<")

    contextos = await obter_todos_os_contextos(pagina_alvo)
    linha_alvo = None
    frame_alvo = None

    count_encontradas = 0
    for ctx in contextos:
        try:
            linhas = ctx.locator("tr.ui-widget-content, tr.conteudoGrid, tr[role='row']")
            qtd = await linhas.count()

            for i in range(qtd):
                l = linhas.nth(i)
                if not await l.is_visible():
                    continue

                try:
                    texto = await l.inner_text()
                except Exception:
                    texto = await l.text_content()

                texto_upper = " ".join((texto or "").split()).upper()

                if "SITUAÇÃO DA CONTA" in texto_upper or "VINCULAÇÃO" in texto_upper:
                    continue

                if "DEFERIDA" in texto_upper and "CONSOLIDADA" in texto_upper:
                    if count_encontradas == idx_deferida:
                        linha_alvo = l
                        frame_alvo = ctx
                        break
                    count_encontradas += 1

            if linha_alvo is not None:
                break

        except Exception as e:
            print(f"   Aviso na busca da grid principal: {e}")

    if linha_alvo is None:
        print(f"   [AVISO] Não foi possível localizar a negociação #{idx_deferida + 1}.")
        return

    print(f"   Clicando na negociação {idx_deferida + 1}/{total_deferidas}...")
    try:
        celula_clicavel = linha_alvo.locator("td div.ui-dt-c").first
        if await celula_clicavel.count() > 0:
            await celula_clicavel.click(force=True, timeout=5000)
        else:
            await linha_alvo.click(force=True, timeout=5000)
    except Exception:
        await linha_alvo.evaluate("""el => {
            let div = el.querySelector('div.ui-dt-c');
            if (div) div.click(); else el.click();
        }""")

    await pagina_alvo.wait_for_timeout(2000)

    print("   -> Clicando no botão 'Consulta'...")
    seletor_btn_consulta = '#formListaDarf\\:idbtnConsulta, input[value="Consulta"], button:has-text("Consulta"), input[id*="idbtnConsulta"]'
    
    clicou_consulta = await clicar_elemento_seguro(pagina_alvo, seletor_btn_consulta, "Consulta")

    if not clicou_consulta and frame_alvo is not None:
        try:
            btn_cons = frame_alvo.locator(seletor_btn_consulta).first
            if await btn_cons.count() > 0:
                await btn_cons.click(force=True)
        except Exception:
            pass

    await pagina_alvo.wait_for_timeout(3000)

    print("   -> Posicionando o mouse sobre 'Emissão de Documento'...")
    seletor_emissao_doc = 'span.ui-menuitem-text:has-text("Emissão de Documento"), a:has-text("Emissão de Documento"), td:has-text("Emissão de Documento")'
    
    hovered_emissao = await passar_mouse_elemento(pagina_alvo, seletor_emissao_doc, "Emissão de Documento")

    if hovered_emissao:
        await pagina_alvo.wait_for_timeout(1500)

        print("   -> Clicando em 'Documento de arrecadação' no menu suspenso...")
        clicou_doc_arrecadacao = await clicar_elemento_seguro(
            pagina_alvo,
            'a[id*="cabecalho"]:has-text("Documento de arrecadação"), a:has-text("Documento de arrecadação"), span:has-text("Documento de arrecadação")',
            "Documento de Arrecadação (Menu)"
        )

        if not clicou_doc_arrecadacao:
            contextos_atuais = await obter_todos_os_contextos(pagina_alvo)
            for ctx in contextos_atuais:
                try:
                    opcao_sub = ctx.locator('a:has-text("Documento de arrecadação")').first
                    if await opcao_sub.count() > 0:
                        await opcao_sub.evaluate("el => el.click()")
                        print("   -> Clique via JS executado em 'Documento de arrecadação'.")
                        clicou_doc_arrecadacao = True
                        break
                except Exception:
                    continue

        await pagina_alvo.wait_for_timeout(2500)

        contextos_atuais = await obter_todos_os_contextos(pagina_alvo)
        linha_selecionada = False
        for ctx in contextos_atuais:
            if await selecionar_linha_grid_especifica(ctx, indice_alvo=idx_deferida):
                linha_selecionada = True
                break

        if not linha_selecionada:
            print(f"   [AVISO] Falha ao selecionar a linha interna da negociação DEFERIDA #{idx_deferida + 1}.")

        await pagina_alvo.wait_for_timeout(1500)

        print("   -> Clicando no botão para gerar o DARF...")
        await clicar_elemento_seguro(
            pagina_alvo,
            '#formListaDarf\\:idbtnDarf, button:has-text("Documento de Arrecadação"), input[value*="Arrecadação"]',
            "Documento de Arrecadação (Botão)"
        )
        await pagina_alvo.wait_for_timeout(3000)

    # Processa os downloads
    await baixar_darfs_elegiveis_regularize(pagina_alvo, f"{nome_identificador_arquivo}_DEF_{idx_deferida + 1}")


async def executar_sessao_unica(p, cnpj_cliente, base_nome_arquivo, indice_alvo=0):
    user_data_dir = os.path.abspath(f"./chrome_profile_temp_{cnpj_cliente}")
    if os.path.exists(user_data_dir):
        try:
            shutil.rmtree(user_data_dir)
        except Exception:
            pass

    print("🌐 Abrindo nova instância do Chrome para sessão isolada...")

    context = await p.chromium.launch_persistent_context(
        user_data_dir=user_data_dir,
        headless=False,
        channel="chrome",
        args=[
            "--start-maximized",
            "--disable-blink-features=AutomationControlled",
            "--disable-web-security",
            "--no-sandbox"
        ],
        ignore_default_args=["--enable-automation"]
    )

    page = context.pages[0] if len(context.pages) > 0 else await context.new_page()

    total_deferidas = 0
    try:
        await page.goto(URL_REGULARIZE, timeout=60000, wait_until="domcontentloaded")
        await realizar_login_pgfn(page, cnpj_cliente)
        
        pagina_alvo = await navegar_ate_grid_principal(page)
        
        total_deferidas = await contar_negociacoes_deferidas(pagina_alvo)
        print(f"   [CONTAGEM] Total de negociações 'DEFERIDA E CONSOLIDADA' na tela: {total_deferidas}")

        if total_deferidas > 0 and indice_alvo < total_deferidas:
            await processar_negocicao_por_indice(pagina_alvo, indice_alvo, total_deferidas, base_nome_arquivo)

    finally:
        print("🛑 Fechando a instância do Chrome e salvando alterações...")
        await context.close()

    return total_deferidas


async def main():
    print("=" * 70)
    print("RPA REGULARIZE PGFN - INICIANDO")
    print("=" * 70)

    os.makedirs(PASTA_DESTINO, exist_ok=True)

    if not os.path.exists(ARQUIVO_PLANILHA):
        print(f"\nERRO: A planilha '{ARQUIVO_PLANILHA}' não foi encontrada.")
        return

    try:
        df = pd.read_excel(ARQUIVO_PLANILHA, dtype=str)
    except Exception as erro:
        print(f"\nERRO AO LER A PLANILHA: {erro}")
        return

    df.columns = [str(coluna).strip() for coluna in df.columns]

    coluna_documento = encontrar_coluna_documento(df)
    coluna_razao = encontrar_coluna_razao(df)
    coluna_tipo = encontrar_coluna_tipo(df)

    if coluna_documento is None or coluna_tipo is None:
        print("\nERRO: Colunas obrigatórias não encontradas na planilha.")
        return

    resultados = []

    async with async_playwright() as p:
        for indice, linha in df.iterrows():
            valor_documento = linha[coluna_documento]
            cpf_cnpj = limpar_cpf_cnpj(valor_documento)
            valor_tipo = linha[coluna_tipo]
            tipo_fluxo = tipos_de_fluxo(valor_tipo)

            if "fluxo 4" not in tipo_fluxo or not cpf_cnpj:
                continue

            razao_social_planilha = sanitizar_nome_arquivo(linha[coluna_razao]) if coluna_razao else ""
            base_nome_arquivo = f"{razao_social_planilha}_{cpf_cnpj}" if razao_social_planilha else cpf_cnpj

            print("\n" + "=" * 70)
            print(f"REGISTRO {indice + 1} DE {len(df)} | CLIENTE: {razao_social_planilha} | CPF/CNPJ: {cpf_cnpj}")
            print("=" * 70)

            sucesso = False
            ultimo_erro = ""
            total_deferidas = 0

            for tentativa in range(1, MAX_TENTATIVAS + 1):
                try:
                    total_deferidas = await executar_sessao_unica(
                        p, cpf_cnpj, base_nome_arquivo, indice_alvo=0
                    )

                    if total_deferidas > 1:
                        for idx in range(1, total_deferidas):
                            print(f"\n[REABRINDO CHROME] Iniciando nova sessão limpa para processar a negociação {idx + 1} de {total_deferidas}...")
                            await executar_sessao_unica(
                                p, cpf_cnpj, base_nome_arquivo, indice_alvo=idx
                            )

                    sucesso = True
                    break

                except Exception as erro:
                    ultimo_erro = f"{type(erro).__name__}: {erro}"
                    log.error(
                        f"Falha no CNPJ {cpf_cnpj} (tentativa {tentativa}/{MAX_TENTATIVAS}): {ultimo_erro}"
                    )
                    print(f"\n   [ERRO] Falha ao processar {cpf_cnpj}: {ultimo_erro}")

                    if tentativa < MAX_TENTATIVAS:
                        print("   Tentando novamente com uma sessão de Chrome nova...")

            if sucesso:
                print(f"\n   [OK] Finalizado o processamento de todas as negociações para {cpf_cnpj}.")
                resultados.append({
                    "Linha": indice + 2,
                    "Razao_Social": razao_social_planilha,
                    "CPF_CNPJ": cpf_cnpj,
                    "Status": "OK",
                    "Negociacoes_Encontradas": total_deferidas,
                    "Erro": "",
                })
            else:
                print(f"\n   [FALHOU] {cpf_cnpj} não pôde ser processado após {MAX_TENTATIVAS} tentativa(s). Seguindo para o próximo.")
                resultados.append({
                    "Linha": indice + 2,
                    "Razao_Social": razao_social_planilha,
                    "CPF_CNPJ": cpf_cnpj,
                    "Status": "ERRO",
                    "Negociacoes_Encontradas": "",
                    "Erro": ultimo_erro,
                })

    salvar_relatorio_execucao(resultados, "fluxo4_pgfn")


if __name__ == "__main__":
    asyncio.run(main())