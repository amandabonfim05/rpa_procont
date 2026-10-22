import asyncio
import os
import re
from datetime import datetime

import pandas as pd
from playwright.async_api import async_playwright


from rpa_config import CONFIG, caminho, configurar_log, salvar_relatorio_execucao

ARQUIVO_PLANILHA = caminho(CONFIG["planilha_fluxo1"])
CHROME_CDP = CONFIG["chrome_cdp"]
PASTA_DESTINO = caminho("parcelamento")

log = configurar_log("rpap2")


def encontrar_coluna_documento(df):
    colunas = [str(col).strip() for col in df.columns]

    possibilidades = [
        "CPF/CNPJ",
        "CPF CNPJ",
        "CPF_CNPJ",
        "CPF",
        "CNPJ",
        "Documento",
        "documento",
    ]

    for possibilidade in possibilidades:
        for col in colunas:
            if col.lower() == possibilidade.lower():
                return col

    return None


def encontrar_coluna_razao(df):
    colunas = [str(col).strip() for col in df.columns]

    possibilidades = [
        "RAZAO",
        "RAZÃO",
        "RAZAO SOCIAL",
        "RAZÃO SOCIAL",
        "NOME",
        "CLIENTE",
        "NOME_CLIENTE",
    ]

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

    return {
        parte.strip()
        for parte in partes
        if parte.strip()
    }


def limpar_cpf_cnpj(valor):
    if pd.isna(valor):
        return ""

    valor = str(valor).strip()

    if valor.endswith(".0"):
        valor = valor[:-2]

    valor = re.sub(r"\D", "", valor)

    return valor


def sanitizar_nome_arquivo(nome):
    if pd.isna(nome) or not str(nome).strip():
        return ""

    nome = re.sub(
        r'[\\/*?:"<>|]',
        "",
        str(nome)
    )

    return nome.strip()


async def localizar_botao_alterar_cnpj(page, campo_cnpj):
    print("\nProcurando o botão Alterar relacionado ao campo do CNPJ...")

    seletor_alterar = 'input[type="button"][value="Alterar"]'

    try:
        botao = campo_cnpj.locator(
            "xpath=following::input[@type='button' and @value='Alterar'][1]"
        )

        if await botao.count() > 0:
            visivel = await botao.is_visible()
            habilitado = await botao.is_enabled()

            print(
                f"Botão Alterar encontrado após CNPJ. "
                f"Visível: {visivel}, Habilitado: {habilitado}"
            )

            if visivel and habilitado:
                return botao

    except Exception as erro:
        print(
            f"Erro procurando Alterar após CNPJ: {erro}"
        )

    try:
        ancestral = campo_cnpj.locator(
            "xpath=ancestor::*[.//input[@type='button' and @value='Alterar']][1]"
        )

        botoes = ancestral.locator(seletor_alterar)
        quantidade = await botoes.count()

        print(
            f"Botões encontrados no container: {quantidade}"
        )

        for i in range(quantidade):
            botao = botoes.nth(i)

            if (
                await botao.is_visible()
                and await botao.is_enabled()
            ):
                return botao

    except Exception:
        pass

    try:
        botoes = page.locator(seletor_alterar)
        quantidade = await botoes.count()

        print(
            f"Total de botões Alterar encontrados: {quantidade}"
        )

        if quantidade >= 2:
            botao = botoes.nth(1)

            if (
                await botao.is_visible()
                and await botao.is_enabled()
            ):
                print(
                    "Segundo botão Alterar selecionado."
                )
                return botao

    except Exception:
        pass

    print("\nProcurando Alterar nos iframes...")

    for indice_frame, frame in enumerate(page.frames):
        if frame == page.main_frame:
            continue

        try:
            campo_frame = frame.locator("#txtNIPapel2")

            if await campo_frame.count() == 0:
                continue

            botao_frame = campo_frame.locator(
                "xpath=following::input[@type='button' and @value='Alterar'][1]"
            )

            if await botao_frame.count() > 0:
                if (
                    await botao_frame.is_visible()
                    and await botao_frame.is_enabled()
                ):
                    print(
                        f"Alterar encontrado no frame #{indice_frame}."
                    )

                    return botao_frame

        except Exception:
            continue

    return None


async def fechar_dialogo_alterar(page):
    print("\nProcurando botão X para fechar o diálogo...")

    seletor_fechar = (
        'a.ui-dialog-titlebar-close.'
        'ui-corner-all[role="button"]'
    )

    try:
        botoes_fechar = page.locator(seletor_fechar)
        quantidade = await botoes_fechar.count()

        print(
            f"Botões de fechar encontrados: {quantidade}"
        )

        for i in range(quantidade):
            botao_fechar = botoes_fechar.nth(i)

            try:
                if not await botao_fechar.is_visible():
                    continue

                print(
                    f"Botão fechar visível encontrado (#{i + 1})."
                )

                await botao_fechar.click(
                    force=True,
                    timeout=10000
                )

                print("Diálogo fechado com sucesso.")
                return True

            except Exception as erro:
                print(
                    f"Erro ao clicar no fechar #{i + 1}: {erro}"
                )

    except Exception as erro:
        print(f"Erro procurando botão fechar: {erro}")

    for indice_frame, frame in enumerate(page.frames):
        if frame == page.main_frame:
            continue

        try:
            botoes_fechar = frame.locator(seletor_fechar)
            quantidade = await botoes_fechar.count()

            for i in range(quantidade):
                botao_fechar = botoes_fechar.nth(i)

                try:
                    if await botao_fechar.is_visible():
                        await botao_fechar.click(
                            force=True,
                            timeout=10000
                        )

                        print(
                            f"Diálogo fechado no frame #{indice_frame}."
                        )
                        return True

                except Exception:
                    continue

        except Exception:
            continue

    print("\nAVISO: botão X do diálogo não foi encontrado.")
    return False


async def clicar_alterar_e_fechar(page, campo_cnpj):
    botao_alterar = await localizar_botao_alterar_cnpj(page, campo_cnpj)

    if botao_alterar is None:
        raise Exception(
            "Não foi encontrado o botão Alterar correspondente ao CNPJ."
        )

    print("\nBOTÃO ALTERAR DO CNPJ ENCONTRADO.")

    try:
        await botao_alterar.scroll_into_view_if_needed()
    except Exception:
        pass

    await page.wait_for_timeout(500)

    print("\nClicando no Alterar do CNPJ...")
    clique_realizado = False

    try:
        await botao_alterar.click(timeout=10000)
        clique_realizado = True
        print("Clique normal executado.")
    except Exception:
        try:
            await botao_alterar.click(force=True, timeout=10000)
            clique_realizado = True
            print("Clique forçado executado.")
        except Exception:
            try:
                await botao_alterar.dispatch_event("click")
                clique_realizado = True
                print("Evento de clique disparado.")
            except Exception as erro:
                print(f"Falha ao clicar no botão Alterar: {erro}")

    if not clique_realizado:
        raise Exception("Não foi possível clicar no Alterar do CNPJ.")

    print("\nAguardando resposta do Alterar...")
    await page.wait_for_timeout(2000)

    print("\nFechando o diálogo...")
    await fechar_dialogo_alterar(page)
    await page.wait_for_timeout(1000)


async def clicar_emissao_parcela(page):
    print("\nLocalizando Emissão de Parcela...")

    seletor = "#ctl00_contentPlaceH_emitirDas"
    alvo = page

    if await page.locator(seletor).count() == 0:
        for frame in page.frames:
            if await frame.locator(seletor).count() > 0:
                alvo = frame
                print("Elemento 'Emissão de Parcela' encontrado dentro de um iframe.")
                break

    link = alvo.locator(seletor).first

    try:
        await link.wait_for(state="attached", timeout=15000)
    except Exception:
        raise Exception("O botão/link 'Emissão de Parcela' não foi encontrado.")

    try:
        await link.scroll_into_view_if_needed()
    except Exception:
        pass

    print("\nExecutando clique em Emissão de Parcela...")

    try:
        await link.evaluate("el => el.click()")
        print("Clique via JS executado com sucesso.")
    except Exception as erro_js:
        print(f"Clique via JS falhou: {erro_js}. Tentando clique do Playwright...")
        try:
            await link.click(force=True, timeout=10000)
            print("Clique nativo forçado executado.")
        except Exception as erro_click:
            raise Exception(f"Falha ao clicar no botão Emissão de Parcela: {erro_click}")


async def clicar_emissao_parcela_relp(page):
    print("\nLocalizando Emissão de Parcela do RELP (#ctl00_contentPlaceH_linkButtonEmitirDAS)...")

    seletor = "#ctl00_contentPlaceH_linkButtonEmitirDAS"
    alvo = page

    if await page.locator(seletor).count() == 0:
        for frame in page.frames:
            if await frame.locator(seletor).count() > 0:
                alvo = frame
                print("Elemento 'Emissão de Parcela (RELP) encontrado dentro de um iframe.")
                break

    link = alvo.locator(seletor).first

    try:
        await link.wait_for(state="attached", timeout=15000)
    except Exception:
        raise Exception("O botão/link 'Emissão de Parcela' do RELP não foi encontrado.")

    try:
        await link.scroll_into_view_if_needed()
    except Exception:
        pass

    print("\nExecutando clique em Emissão de Parcela (RELP)...")

    try:
        await link.evaluate("el => el.click()")
        print("Clique via JS executado com sucesso.")
    except Exception as erro_js:
        print(f"Clique via JS falhou: {erro_js}. Tentando clique do Playwright...")
        try:
            await link.click(force=True, timeout=10000)
            print("Clique nativo forçado executado.")
        except Exception as erro_click:
            raise Exception(f"Falha ao clicar no botão Emissão de Parcela do RELP: {erro_click}")


async def resolver_e_continuar_captcha(page):
    print("\nTratando o modal do Captcha...")
    await page.wait_for_timeout(1000)

    checkbox_clicado = False

    for frame in page.frames:
        try:
            chk = frame.locator("#checkbox")
            if await chk.count() > 0 and await chk.is_visible():
                await chk.click()
                print("Clique no checkbox do Captcha executado com sucesso!")
                checkbox_clicado = True
                break
        except Exception:
            continue

    if not checkbox_clicado:
        print("Aviso: Checkbox do captcha não encontrado nos frames ativos.")

    print("Aguardando validação do hCaptcha...")
    await page.wait_for_timeout(5000)

    print("Procurando o botão 'Continuar' do Captcha após pausa maior...")

    seletor_continuar = (
        'input[value="Continuar"], '
        'button:has-text("Continuar"), '
        'span:has-text("Continuar"), '
        '.ui-button:has-text("Continuar")'
    )

    contextos_busca = [page] + page.frames
    clique_sucesso = False

    for ctx in contextos_busca:
        try:
            btn = ctx.locator(seletor_continuar).first

            if await btn.count() > 0 and await btn.is_visible():
                print("Botão 'Continuar' do Captcha localizado! Aguardando 5s antes do clique...")
                await page.wait_for_timeout(5000)
                try:
                    await btn.click(timeout=3000)
                    clique_sucesso = True
                except Exception:
                    try:
                        await btn.click(force=True, timeout=3000)
                        clique_sucesso = True
                    except Exception:
                        await btn.evaluate("el => el.click()")
                        clique_sucesso = True

                if clique_sucesso:
                    print("Clique no botão 'Continuar' do Captcha executado!")
                    break

        except Exception:
            continue

    if not clique_sucesso:
        print("\nAVISO: O botão Continuar do Captcha não aceitou o clique automático.")

    print("\nAguardando processamento pós-envio...")
    await page.wait_for_timeout(3000)


async def clicar_logo_ecac(page):
    print("\nTentando clicar no botão/logo e-CAC...")

    seletor_logo = "#logoEcac"
    contextos = [page] + page.frames
    clique_realizado = False

    for ctx in contextos:
        try:
            logo = ctx.locator(seletor_logo).first

            if await logo.count() > 0 and await logo.is_visible():
                print("Logo e-CAC localizado! Clicando para retornar ao menu principal...")
                try:
                    await logo.click(timeout=3000)
                    clique_realizado = True
                except Exception:
                    try:
                        await logo.click(force=True, timeout=3000)
                        clique_realizado = True
                    except Exception:
                        await logo.evaluate("el => el.click()")
                        clique_realizado = True

                if clique_realizado:
                    print("Clique no e-CAC executado com sucesso!")
                    await page.wait_for_timeout(2000)
                    break

        except Exception:
            continue

    if not clique_realizado:
        print("Aviso: Não foi possível localizar ou clicar no logo e-CAC.")


async def clicar_todos_imprimir_das(page, nome_identificador_arquivo):
    print("\nProcurando todos os botões de impressão do DAS...")

    seletor_imprimir = (
        'a[id*="LinkButtonEmitirDas"], '
        'input[value*="Imprimir"], '
        'button:has-text("Imprimir")'
    )

    contextos = [page] + page.frames

    for ctx in contextos:
        botoes = ctx.locator(seletor_imprimir)
        qtd = await botoes.count()

        if qtd > 0:
            print(f"Encontrado(s) {qtd} botão(ões) de emissão/impressão de DAS.")

            os.makedirs(PASTA_DESTINO, exist_ok=True)

            for i in range(qtd):
                botao = botoes.nth(i)
                id_botao = await botao.get_attribute("id") or f"Botão #{i + 1}"

                print(f"[{i + 1}/{qtd}] Clicando no botão: {id_botao}...")

                sufixo = f"_{i + 1}" if qtd > 1 else ""
                nome_arquivo = f"{sanitizar_nome_arquivo(nome_identificador_arquivo)}{sufixo}.pdf"
                caminho_completo = os.path.join(PASTA_DESTINO, nome_arquivo)

                try:
                    async with page.expect_download(timeout=10000) as download_info:
                        try:
                            await botao.click(timeout=3000)
                        except Exception:
                            try:
                                await botao.click(force=True, timeout=3000)
                            except Exception:
                                await botao.evaluate("el => el.click()")

                    download = await download_info.value
                    await download.save_as(caminho_completo)
                    print(f"[SUCESSO] Arquivo salvo em: {caminho_completo}")

                except Exception as erro_dl:
                    print(f"Aviso: Download automático não capturado pelo Playwright ({erro_dl}).")

                await page.wait_for_timeout(2000)

            return True

    print("Nenhum botão de impressão de DAS foi encontrado.")
    return False


async def processar_resultado_parcelas(page, nome_identificador_arquivo):
    print("\nVerificando o resultado pós-captcha...")

    seletor_ok = "#popup_ok"
    seletor_btn_continuar_parcelas = "#ctl00_contentPlaceH_btnContinuar"

    contextos = [page] + page.frames
    popup_encontrado = False

    for ctx in contextos:
        try:
            btn_ok = ctx.locator(seletor_ok).first

            if await btn_ok.count() > 0 and await btn_ok.is_visible():
                print("Popup de alerta detectado!")

                try:
                    msg = await ctx.locator("#popup_message").first.text_content()
                    if msg:
                        print(f"Mensagem do Alerta: {msg.strip()}")
                except Exception:
                    pass

                print("Clicando no botão OK do alerta...")

                try:
                    await btn_ok.click(timeout=3000)
                except Exception:
                    try:
                        await btn_ok.click(force=True, timeout=3000)
                    except Exception:
                        await btn_ok.evaluate("el => el.click()")

                print("Alerta fechado com sucesso!")
                popup_encontrado = True
                await page.wait_for_timeout(1000)
                break

        except Exception:
            continue

    if not popup_encontrado:
        print("Nenhum alerta detectado. Verificando tela de emissão de parcelas...")
        btn_continuar_clicado = False

        for ctx in contextos:
            try:
                btn_continuar = ctx.locator(seletor_btn_continuar_parcelas).first

                if await btn_continuar.count() > 0 and await btn_continuar.is_visible():
                    print("Botão 'Continuar' da tela de parcelas localizado! Clicando...")

                    try:
                        await btn_continuar.click(timeout=3000)
                        btn_continuar_clicado = True
                    except Exception:
                        try:
                            await btn_continuar.click(force=True, timeout=3000)
                            btn_continuar_clicado = True
                        except Exception:
                            await btn_continuar.evaluate("el => el.click()")
                            btn_continuar_clicado = True

                    if btn_continuar_clicado:
                        print("Clique no 'Continuar' das parcelas executado com sucesso!")
                        await page.wait_for_timeout(3000)
                        await clicar_todos_imprimir_das(page, nome_identificador_arquivo)
                        break

            except Exception:
                continue

        if not btn_continuar_clicado:
            print(
                "Aviso: Nem o popup nem o botão Continuar das parcelas foram encontrados. "
                "Tentando buscar botões de impressão diretamente..."
            )
            await clicar_todos_imprimir_das(page, nome_identificador_arquivo)


async def consultar_relp(ecac_page, context, nome_identificador_arquivo):
    print("\n--- Iniciando segunda consulta: RELP (LC 193/2022) ---")
    await ecac_page.wait_for_timeout(2000)

    print("1. Clicando em Simples Nacional...")
    simples_nacional = ecac_page.locator("#btn266 a", has_text="Simples Nacional").first
    await simples_nacional.wait_for(state="visible", timeout=20000)
    await simples_nacional.click(force=True)
    await ecac_page.wait_for_timeout(1000)

    print("2. Clicando em Parcelar dívidas do SN pela LC 193/2022 (RELP)...")
    opcao_relp = ecac_page.locator('a[href="Aplicacao.aspx?id=10036&origem=menu"]:visible').first
    await opcao_relp.wait_for(state="visible", timeout=20000)

    p_relp = ecac_page
    abriu_nova_aba = False

    try:
        async with context.expect_page(timeout=5000) as new_page_info:
            await opcao_relp.click(force=True)

        p_relp = await new_page_info.value
        await p_relp.wait_for_load_state()
        abriu_nova_aba = True
        print("Aplicação RELP aberta em uma nova aba.")
    except Exception:
        print("Aplicação RELP aberta na mesma aba.")

    print("3. Clicando em Emissão de Parcela no RELP...")
    await clicar_emissao_parcela_relp(p_relp)

    print("4. Resolvendo Captcha no RELP...")
    await resolver_e_continuar_captcha(p_relp)

    print("5. Processando resultado das parcelas do RELP...")
    await processar_resultado_parcelas(p_relp, f"{nome_identificador_arquivo}_RELP")

    if abriu_nova_aba:
        print("Finalizado RELP. Fechando a aba e voltando ao e-CAC principal...")
        await p_relp.close()
        await ecac_page.bring_to_front()
    else:
        await clicar_logo_ecac(ecac_page)


async def clicar_darf_parcela_fluxo3(page, nome_identificador_arquivo):
    print("\n9. Verificando parcelas para emissão...")

    hoje = datetime.now().date()
    mes_atual = (hoje.year, hoje.month)

    contextos = [page] + page.frames

    padroes_data = [
        r"\b(\d{2}/\d{2}/\d{4})\b",
        r"\b(\d{2}-\d{2}-\d{4})\b",
        r"\b(\d{2}\.\d{2}\.\d{4})\b",
    ]

    total_marcadas = 0
    contexto_valido = None

    for ctx in contextos:
        try:
            linhas = ctx.locator("tr")
            quantidade_linhas = await linhas.count()

            if quantidade_linhas == 0:
                continue

            print(f"   Analisando {quantidade_linhas} linhas na tabela...")

            for indice_linha in range(quantidade_linhas):
                linha = linhas.nth(indice_linha)

                try:
                    if not await linha.is_visible():
                        continue
                except Exception:
                    continue

                try:
                    texto_linha = await linha.inner_text()
                except Exception:
                    try:
                        texto_linha = await linha.text_content()
                    except Exception:
                        continue

                texto_normalizado = " ".join((texto_linha or "").split())

                if not texto_normalizado:
                    continue

                texto_lower = texto_normalizado.lower()

                data_encontrada = None

                for padrao in padroes_data:
                    resultado_data = re.search(padrao, texto_normalizado)

                    if resultado_data:
                        valor_data = resultado_data.group(1).replace("-", "/").replace(".", "/")
                        try:
                            data_encontrada = datetime.strptime(valor_data, "%d/%m/%Y").date()
                            break
                        except ValueError:
                            continue

                if data_encontrada is None:
                    continue

                mes_parcela = (data_encontrada.year, data_encontrada.month)

                print(
                    f"   Linha {indice_linha + 1}: Data={data_encontrada.strftime('%d/%m/%Y')} | "
                    f"Mês Parcela={mes_parcela} | Mês Atual={mes_atual}"
                )

                situacao_paga = "paga" in texto_lower or any(
                    termo in texto_lower
                    for termo in ["pago", "quitada", "quitado", "liquidada", "liquidado"]
                )

                if situacao_paga:
                    print("   Parcela está paga/quitada. Ignorando.")
                    continue

                if mes_parcela > mes_atual:
                    print("   Parcela é de mês posterior ao atual. Ignorando.")
                    continue

                print("   [ELEGÍVEL] Parcela não paga e pertencente ao mês atual ou anterior.")

                checkbox = linha.locator('input[type="checkbox"]').first

                if await checkbox.count() == 0:
                    checkbox = linha.locator(
                        'div[role="checkbox"], .ui-chkbox-box, .ui-checkbox, span.ui-checkbox-icon'
                    ).first

                if await checkbox.count() == 0:
                    print("   Checkbox da parcela não encontrado.")
                    continue

                try:
                    await checkbox.scroll_into_view_if_needed()
                except Exception:
                    pass

                checkbox_marcado = False

                try:
                    tipo = await checkbox.get_attribute("type")

                    if tipo == "checkbox":
                        try:
                            checkbox_marcado = await checkbox.is_checked()
                        except Exception:
                            checkbox_marcado = False

                        if not checkbox_marcado:
                            try:
                                await checkbox.check(force=True, timeout=5000)
                            except Exception:
                                await checkbox.click(force=True, timeout=5000)

                        checkbox_marcado = True

                    else:
                        await checkbox.click(force=True, timeout=5000)
                        checkbox_marcado = True

                except Exception as erro_checkbox:
                    print(f"   Clique no checkbox falhou: {erro_checkbox}")
                    try:
                        await checkbox.evaluate("el => el.click()")
                        checkbox_marcado = True
                    except Exception as erro_js:
                        print(f"   Falha ao clicar no checkbox via JS: {erro_js}")

                if checkbox_marcado:
                    total_marcadas += 1
                    contexto_valido = ctx
                    print(f"   [MARCADA] Parcela {indice_linha + 1} selecionada com sucesso.")

            if total_marcadas > 0:
                break

        except Exception as erro_contexto:
            print(f"   Aviso ao verificar contexto para DARF: {erro_contexto}")

    if total_marcadas == 0:
        print("\nNenhuma parcela elegível (não paga e <= mês atual) foi encontrada.")
        return False

    print(f"\nTotal de {total_marcadas} parcela(s) selecionada(s).")
    print("\nProcurando e clicando em 'Emitir DARF de parcela'...")

    seletor_emitir = (
        'button:has-text("Emitir DARF de parcela"), '
        'button[label="Emitir DARF de parcela"], '
        'input[value*="Emitir DARF de parcela"]'
    )

    botao_emitir = None

    for ctx in [contexto_valido, page] + page.frames:
        if ctx is None:
            continue
        try:
            candidatos = ctx.locator(seletor_emitir)
            if await candidatos.count() > 0:
                for i in range(await candidatos.count()):
                    cand = candidatos.nth(i)
                    if await cand.is_visible():
                        botao_emitir = cand
                        break
            if botao_emitir is not None:
                break
        except Exception:
            continue

    if botao_emitir is None:
        print("Botão 'Emitir DARF de parcela' não foi encontrado.")
        return False

    try:
        await botao_emitir.scroll_into_view_if_needed()
    except Exception:
        pass

    try:
        await botao_emitir.click(timeout=5000)
    except Exception:
        try:
            await botao_emitir.click(force=True, timeout=5000)
        except Exception:
            await botao_emitir.evaluate("el => el.click()")

    print("Botão 'Emitir DARF de parcela' clicado com sucesso.")
    await page.wait_for_timeout(3000)

    print("\nProcurando e clicando em 'Imprimir DARF' para realizar o download...")

    seletor_imprimir = (
        'button:has-text("Imprimir DARF"), '
        'button[label="Imprimir DARF"], '
        'input[value*="Imprimir DARF"]'
    )

    botao_imprimir = None

    for ctx in [contexto_valido, page] + page.frames:
        if ctx is None:
            continue
        try:
            candidatos = ctx.locator(seletor_imprimir)
            if await candidatos.count() > 0:
                for i in range(await candidatos.count()):
                    cand = candidatos.nth(i)
                    if await cand.is_visible():
                        botao_imprimir = cand
                        break
            if botao_imprimir is not None:
                break
        except Exception:
            continue

    if botao_imprimir is None:
        print("Botão 'Imprimir DARF' não foi encontrado.")
        return False

    try:
        await botao_imprimir.scroll_into_view_if_needed()
    except Exception:
        pass

    os.makedirs(PASTA_DESTINO, exist_ok=True)
    nome_arquivo = f"{sanitizar_nome_arquivo(nome_identificador_arquivo)}_PARCELAMENTO_ORDINARIO.pdf"
    caminho_completo = os.path.join(PASTA_DESTINO, nome_arquivo)

    try:
        async with page.expect_download(timeout=15000) as download_info:
            try:
                await botao_imprimir.click(timeout=5000)
            except Exception:
                try:
                    await botao_imprimir.click(force=True, timeout=5000)
                except Exception:
                    await botao_imprimir.evaluate("el => el.click()")

        download = await download_info.value
        await download.save_as(caminho_completo)
        print(f"   [SUCESSO] DARF salvo em: {caminho_completo}")
        await page.wait_for_timeout(2000)
        return True

    except Exception as erro_download:
        print(f"   Aviso: Download não foi capturado automaticamente: {erro_download}")

    return False


async def consultar_parcelamento_ordinario(ecac_page, context, nome_identificador_arquivo):
    print("\n--- Iniciando terceira consulta: Pagamentos e Parcelamentos ---")
    await ecac_page.wait_for_timeout(2000)

    print("1. Clicando em Pagamentos e Parcelamentos...")
    btn_pagamentos = ecac_page.locator('a:has-text("Pagamentos e Parcelamentos")').first
    await btn_pagamentos.wait_for(state="visible", timeout=20000)
    await btn_pagamentos.click(force=True)
    await ecac_page.wait_for_timeout(1000)

    print("2. Clicando em Parcelamento - Solicitar e acompanhar...")
    opcao_parcelamento = ecac_page.locator('a[href="Aplicacao.aspx?id=10014&origem=menu"]:visible').first
    await opcao_parcelamento.wait_for(state="visible", timeout=20000)

    p_parc = ecac_page
    abriu_nova_aba = False

    try:
        async with context.expect_page(timeout=5000) as new_page_info:
            await opcao_parcelamento.click(force=True)

        p_parc = await new_page_info.value
        await p_parc.wait_for_load_state()
        abriu_nova_aba = True
        print("Aplicação de Parcelamento aberta em uma nova aba.")
    except Exception:
        print("Aplicação de Parcelamento aberta na mesma aba.")

    print("3. Clicando em 'Consultar informações de seus parcelamentos'...")

    seletor_consultar_info = (
        'a[href*="/consultar-parcelamento/consultar-parcelamento"], '
        'a:has-text("Consultar informações de seus parcelamentos")'
    )

    btn_consultar = None
    contextos = [p_parc] + p_parc.frames

    for ctx in contextos:
        try:
            candidatos = ctx.locator(seletor_consultar_info)
            quantidade = await candidatos.count()

            for i in range(quantidade):
                candidato = candidatos.nth(i)
                try:
                    if await candidato.is_visible():
                        btn_consultar = candidato
                        break
                except Exception:
                    continue

            if btn_consultar is not None:
                break
        except Exception:
            continue

    if btn_consultar is None:
        raise Exception("Não foi encontrado o botão 'Consultar informações de seus parcelamentos'.")

    await btn_consultar.wait_for(state="visible", timeout=15000)

    try:
        await btn_consultar.scroll_into_view_if_needed()
    except Exception:
        pass

    try:
        await btn_consultar.click(force=True, timeout=5000)
    except Exception:
        await btn_consultar.evaluate("el => el.click()")

    print("Clique em 'Consultar informações de seus parcelamentos' executado.")
    await p_parc.wait_for_timeout(2500)

    print("4. Procurando o botão 'Consultar'...")
    seletor_consultar = 'button[label="Consultar"], button:has-text("Consultar")'
    btn_consultar_final = None

    for ctx in [p_parc] + p_parc.frames:
        try:
            candidatos = ctx.locator(seletor_consultar)
            quantidade = await candidatos.count()

            for i in range(quantidade):
                candidato = candidatos.nth(i)
                try:
                    if await candidato.is_visible():
                        btn_consultar_final = candidato
                        break
                except Exception:
                    continue

            if btn_consultar_final is not None:
                break
        except Exception:
            continue

    if btn_consultar_final is not None:
        try:
            await btn_consultar_final.click(force=True, timeout=5000)
        except Exception:
            await btn_consultar_final.evaluate("el => el.click()")

        print("Clique no botão 'Consultar' executado.")
        await p_parc.wait_for_timeout(3000)
    else:
        print("Botão 'Consultar' não apareceu. Continuando.")

    print("5. Procurando o botão hamburguer...")
    seletor_hamburguer = 'button[type="button"].icone.hamburguer'
    btn_hamburguer = None
    contexto_hamburguer = None

    for ctx in [p_parc] + p_parc.frames:
        try:
            candidatos = ctx.locator(seletor_hamburguer)
            quantidade = await candidatos.count()

            for i in range(quantidade):
                candidato = candidatos.nth(i)
                try:
                    if await candidato.is_visible():
                        btn_hamburguer = candidato
                        contexto_hamburguer = ctx
                        break
                except Exception:
                    continue

            if btn_hamburguer is not None:
                break
        except Exception:
            continue

    if btn_hamburguer is None:
        print("Botão hamburguer não apareceu. Retornando ao e-CAC.")
        if abriu_nova_aba:
            await p_parc.close()
            await ecac_page.bring_to_front()
        else:
            await clicar_logo_ecac(ecac_page)
        return

    try:
        await btn_hamburguer.scroll_into_view_if_needed()
    except Exception:
        pass

    print("Botão hamburguer encontrado. Executando clique...")
    clique_hamburguer = False

    try:
        await btn_hamburguer.click(force=True, timeout=5000)
        clique_hamburguer = True
    except Exception:
        try:
            await btn_hamburguer.evaluate("el => el.click()")
            clique_hamburguer = True
        except Exception as erro:
            print(f"Falha ao clicar no hamburguer: {erro}")

    if not clique_hamburguer:
        print("Não foi possível clicar no hamburguer. Retornando ao e-CAC.")
        if abriu_nova_aba:
            await p_parc.close()
            await ecac_page.bring_to_front()
        else:
            await clicar_logo_ecac(ecac_page)
        return

    print("Botão hamburguer clicado.")
    await p_parc.wait_for_timeout(1000)

    print("6. Clicando em 'Emitir Documento de Arrecadação'...")
    seletor_darf_menu = (
        'a[role="menuitem"].ui-menuitem-link'
        ':has-text("Emitir Documento de Arrecadação")'
    )

    btn_darf_menu = None
    contextos_menu = []

    if contexto_hamburguer is not None:
        contextos_menu.append(contexto_hamburguer)
    if p_parc not in contextos_menu:
        contextos_menu.append(p_parc)

    for frame in p_parc.frames:
        if frame not in contextos_menu:
            contextos_menu.append(frame)

    for ctx in contextos_menu:
        try:
            candidatos = ctx.locator(seletor_darf_menu)
            quantidade = await candidatos.count()

            for i in range(quantidade):
                candidato = candidatos.nth(i)
                try:
                    if await candidato.is_visible():
                        btn_darf_menu = candidato
                        break
                except Exception:
                    continue

            if btn_darf_menu is not None:
                break
        except Exception:
            continue

    if btn_darf_menu is None:
        for ctx in contextos_menu:
            try:
                candidato = ctx.get_by_role(
                    "menuitem",
                    name="Emitir Documento de Arrecadação",
                    exact=True
                ).first

                if await candidato.count() > 0 and await candidato.is_visible():
                    btn_darf_menu = candidato
                    break
            except Exception:
                continue

    if btn_darf_menu is None:
        print("Botão 'Emitir Documento de Arrecadação' não apareceu. Retornando ao e-CAC.")
        if abriu_nova_aba:
            await p_parc.close()
            await ecac_page.bring_to_front()
        else:
            await clicar_logo_ecac(ecac_page)
        return

    try:
        await btn_darf_menu.scroll_into_view_if_needed()
    except Exception:
        pass

    try:
        await btn_darf_menu.click(force=True, timeout=5000)
    except Exception:
        await btn_darf_menu.evaluate("el => el.click()")

    print("Menu 'Emitir Documento de Arrecadação' clicado.")
    await p_parc.wait_for_timeout(1500)

    print("7. Selecionando a opção 'Parcela'...")
    seletor_label_parcela = 'label.ui-radiobutton-label:has-text("Parcela")'
    radio_label = None

    for ctx in [p_parc] + p_parc.frames:
        try:
            candidatos = ctx.locator(seletor_label_parcela)
            quantidade = await candidatos.count()

            for i in range(quantidade):
                candidato = candidatos.nth(i)
                try:
                    if await candidato.is_visible():
                        radio_label = candidato
                        break
                except Exception:
                    continue

            if radio_label is not None:
                break
        except Exception:
            continue

    if radio_label is None:
        print("Opção 'Parcela' não apareceu. Retornando ao e-CAC.")
        if abriu_nova_aba:
            await p_parc.close()
            await ecac_page.bring_to_front()
        else:
            await clicar_logo_ecac(ecac_page)
        return

    try:
        await radio_label.scroll_into_view_if_needed()
    except Exception:
        pass

    radio_clicado = False
    try:
        await radio_label.click(force=True, timeout=5000)
        radio_clicado = True
    except Exception:
        try:
            await radio_label.evaluate("el => el.click()")
            radio_clicado = True
        except Exception as erro:
            print(f"Não foi possível selecionar a opção Parcela: {erro}")

    if not radio_clicado:
        print("Não foi possível selecionar a opção Parcela. Retornando ao e-CAC.")
        if abriu_nova_aba:
            await p_parc.close()
            await ecac_page.bring_to_front()
        else:
            await clicar_logo_ecac(ecac_page)
        return

    print("Opção 'Parcela' selecionada com sucesso.")
    await p_parc.wait_for_timeout(500)

    print("8. Clicando em 'Confirmar'...")
    seletor_confirmar = 'button[label="Confirmar"], button:has-text("Confirmar")'
    btn_confirmar = None

    for ctx in [p_parc] + p_parc.frames:
        try:
            candidatos = ctx.locator(seletor_confirmar)
            quantidade = await candidatos.count()

            for i in range(quantidade):
                candidato = candidatos.nth(i)
                try:
                    if await candidato.is_visible():
                        btn_confirmar = candidato
                        break
                except Exception:
                    continue

            if btn_confirmar is not None:
                break
        except Exception:
            continue

    if btn_confirmar is None:
        print("Botão 'Confirmar' não apareceu. Retornando ao e-CAC.")
        if abriu_nova_aba:
            await p_parc.close()
            await ecac_page.bring_to_front()
        else:
            await clicar_logo_ecac(ecac_page)
        return

    try:
        await btn_confirmar.scroll_into_view_if_needed()
    except Exception:
        pass

    confirmar_clicado = False
    try:
        await btn_confirmar.click(force=True, timeout=5000)
        confirmar_clicado = True
    except Exception:
        try:
            await btn_confirmar.evaluate("el => el.click()")
            confirmar_clicado = True
        except Exception as erro:
            print(f"Erro ao clicar em Confirmar: {erro}")

    if not confirmar_clicado:
        print("Não foi possível clicar em Confirmar. Retornando ao e-CAC.")
        if abriu_nova_aba:
            await p_parc.close()
            await ecac_page.bring_to_front()
        else:
            await clicar_logo_ecac(ecac_page)
        return

    print("Botão 'Confirmar' clicado.")
    await p_parc.wait_for_timeout(2500)

    print("9. Verificando se existem parcelas não pagas de meses iguais ou anteriores ao atual...")
    darf_emitido = await clicar_darf_parcela_fluxo3(p_parc, nome_identificador_arquivo)

    if darf_emitido:
        print("DARF do fluxo 3 processado e emitido com sucesso.")
    else:
        print("Nenhuma parcela elegível para emissão do DARF foi encontrada.")

    print("10. Retornando ao e-CAC...")

    if abriu_nova_aba:
        try:
            await p_parc.close()
        except Exception:
            pass
        await ecac_page.bring_to_front()
    else:
        await clicar_logo_ecac(ecac_page)


async def clicar_elemento_seguro(page, seletor_ou_locator, nome_descricao="Elemento"):
    """Função auxiliar para clicar com fallback em seletores do Regularize/PGFN."""
    contextos = [page] + page.frames
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


async def baixar_darfs_elegiveis_regularize(page, nome_identificador_arquivo):
    """Analisar a tabela de parcelas do Regularize e baixar apenas parcelas <= mês/ano atual."""
    hoje = datetime.now().date()
    mes_atual = (hoje.year, hoje.month)

    print(f"\n   [DARF PGFN] Verificando parcelas elegíveis para emissão (mês/ano <= {mes_atual[1]}/{mes_atual[0]})...")

    contextos = [page] + page.frames
    padroes_data = [
        r"\b(\d{2}/\d{2}/\d{4})\b",
        r"\b(\d{2}-\d{2}-\d{4})\b",
        r"\b(\d{2}\.\d{2}\.\d{4})\b",
    ]

    total_baixados = 0

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

                btn_imprimir = linha.locator(
                    'img[src*="imprimir.png"], '
                    'img[id*="NNimprimirDarf"], '
                    'input[id*="NNimprimirDarf"], '
                    'a[id*="NNimprimirDarf"], '
                    'button:has-text("Emitir"), '
                    'button:has-text("Imprimir")'
                ).first

                if await btn_imprimir.count() == 0:
                    continue

                texto_linha = await linha.inner_text()
                texto_normalizado = " ".join((texto_linha or "").split())

                data_encontrada = None
                for padrao in padroes_data:
                    res_data = re.search(padrao, texto_normalizado)
                    if res_data:
                        v_data = res_data.group(1).replace("-", "/").replace(".", "/")
                        try:
                            data_encontrada = datetime.strptime(v_data, "%d/%m/%Y").date()
                            break
                        except ValueError:
                            continue

                if data_encontrada:
                    mes_parcela = (data_encontrada.year, data_encontrada.month)
                    print(f"   Analisando Parcela: Vencimento={data_encontrada.strftime('%d/%m/%Y')} | Mês={mes_parcela}")

                    if mes_parcela > mes_atual:
                        print("   -> Parcela com vencimento futuro. Ignorando.")
                        continue
                else:
                    print("   -> Data de vencimento não identificada na linha. Processando...")

                print("   [ELEGÍVEL] Executando download do DARF PGFN...")

                os.makedirs(PASTA_DESTINO, exist_ok=True)
                sufixo = f"_{total_baixados + 1}" if total_baixados > 0 else ""
                nome_arquivo = f"{sanitizar_nome_arquivo(nome_identificador_arquivo)}_PGFN{sufixo}.pdf"
                caminho_completo = os.path.join(PASTA_DESTINO, nome_arquivo)

                try:
                    async with page.expect_download(timeout=12000) as download_info:
                        try:
                            await btn_imprimir.click(timeout=4000)
                        except Exception:
                            try:
                                await btn_imprimir.click(force=True, timeout=4000)
                            except Exception:
                                await btn_imprimir.evaluate("el => el.click()")

                    download = await download_info.value
                    await download.save_as(caminho_completo)
                    print(f"   [SUCESSO] DARF PGFN salvo em: {caminho_completo}")
                    total_baixados += 1
                    await page.wait_for_timeout(2000)

                except Exception as erro_dl:
                    print(f"   Aviso: Download do DARF não capturado: {erro_dl}")

            if total_baixados > 0:
                break

        except Exception as e:
            print(f"   Aviso ao ler tabela de DARFs PGFN: {e}")

    return total_baixados


async def consultar_pgfn_regularize(ecac_page, context, nome_identificador_arquivo):
    print("\n--- Iniciando quarta consulta: Dívida Ativa da União (PGFN / Regularize) ---")
    await ecac_page.wait_for_timeout(2000)

    print("1. Clicando na aba 'Dívida Ativa da União' (#btn255)...")
    btn_divida_ativa = ecac_page.locator(
        '#btn255, #btn255 a, a:has-text("Dívida Ativa da União")'
    ).first
    await btn_divida_ativa.wait_for(state="visible", timeout=20000)
    await btn_divida_ativa.click(force=True)
    await ecac_page.wait_for_timeout(1000)

    print("2. Clicando em 'PGFN - Todos os serviços do Regularize'...")
    link_regularize = ecac_page.locator(
        'a[href*="/Servicos/ATBHE/PGFN/consultaDebitos/app.aspx"]:visible'
    ).first
    await link_regularize.wait_for(state="visible", timeout=20000)

    p_regularize = ecac_page
    abriu_nova_aba = False

    try:
        async with context.expect_page(timeout=10000) as new_page_info:
            await link_regularize.click(force=True)

        p_regularize = await new_page_info.value
        await p_regularize.wait_for_load_state()
        abriu_nova_aba = True
        print("[SUCESSO] Página do Regularize da PGFN aberta em uma nova aba!")
    except Exception as erro:
        print(f"Aplicação do Regularize aberta na mesma aba ou erro de navegação: {erro}")

    await p_regularize.wait_for_timeout(3000)

    # NAVEGAÇÃO INICIAL NO REGULARIZE
    print("3. Clicando em 'Ciente'...")
    await clicar_elemento_seguro(p_regularize, 'button.btn.btn-primary:has-text("Ciente")', "Ciente")
    await p_regularize.wait_for_timeout(1500)

    print("4. Clicando em 'Fechar'...")
    await clicar_elemento_seguro(p_regularize, 'button.btn.btn-primary:has-text("Fechar")', "Fechar")
    await p_regularize.wait_for_timeout(1500)

    print("5. Clicando em 'Negociar Dívida'...")
    await clicar_elemento_seguro(p_regularize, 'span.place-info-box-text:has-text("Negociar Dívida")', "Negociar Dívida")
    await p_regularize.wait_for_timeout(2000)

    print("6. Clicando em 'Acessar'...")
    await clicar_elemento_seguro(p_regularize, 'button.btn.btn-primary.mt-2:has-text("Acessar")', "Acessar")
    await p_regularize.wait_for_timeout(3000)

    print("7. Clicando em 'CONSULTAR'...")
    await clicar_elemento_seguro(p_regularize, 'span.place-info-box-text:has-text("CONSULTAR")', "CONSULTAR")
    await p_regularize.wait_for_timeout(2000)

    print("8. Clicando em 'Continuar'...")
    await clicar_elemento_seguro(p_regularize, 'button.btn.btn-primary:has-text("Continuar")', "Continuar")
    await p_regularize.wait_for_timeout(3000)

    # ITERAÇÃO DE NEGOCIAÇÕES ELEGÍVEIS
    print("9. Analisando negociações elegíveis...")
    indice_processamento = 0

    while True:
        contextos = [p_regularize] + p_regularize.frames
        linha_alvo = None

        for ctx in contextos:
            try:
                # Busca por todas as linhas da tabela da PGFN
                linhas = ctx.locator("tbody[id*='listaParc'] tr, tr.conteudoGrid, tr[role='row']")
                qtd = await linhas.count()

                if qtd == 0:
                    linhas = ctx.locator("tr")
                    qtd = await linhas.count()

                count_elegiveis = 0
                for i in range(qtd):
                    l = linhas.nth(i)
                    if not await l.is_visible():
                        continue

                    try:
                        texto = await l.inner_text()
                    except Exception:
                        texto = await l.text_content()

                    texto_upper = " ".join((texto or "").split()).upper()

                    # Valida se possui palavras-chave válidas como DEFERIDA, CONSOLIDADA ou AGUARDANDO
                    eh_elegivel = any(
                        palavra in texto_upper
                        for palavra in [
                            "DEFERID",
                            "CONSOLIDADA",
                            "AGUARDANDO PAGAMENTO",
                            "EM ANDAMENTO",
                        ]
                    )

                    if eh_elegivel:
                        if count_elegiveis == indice_processamento:
                            linha_alvo = l
                            break
                        count_elegiveis += 1

                if linha_alvo is not None:
                    break

            except Exception as e:
                print(f"   Aviso na leitura da grid de dívidas: {e}")
                continue

        if linha_alvo is None:
            print("   -> Nenhuma outra negociação elegível encontrada na tabela.")
            break

        indice_processamento += 1
        print(f"\n   [PROCESSANDO NEGOCIAÇÃO #{indice_processamento}] Clicando no item da tabela...")

        try:
            await linha_alvo.click(timeout=5000)
        except Exception:
            try:
                await linha_alvo.click(force=True, timeout=5000)
            except Exception:
                await linha_alvo.evaluate("el => el.click()")

        await p_regularize.wait_for_timeout(1500)

        # Acessar Opção "Consulta"
        print("   -> Clicando em 'Consulta'...")
        await clicar_elemento_seguro(
            p_regularize,
            '#formListaDarf\\:idbtnConsulta, button:has-text("Consulta"), input[value="Consulta"], input[id*="idbtnConsulta"]',
            "Consulta"
        )
        await p_regularize.wait_for_timeout(2000)

        # Emissão do Documento
        print("   -> Clicando em 'Emissão de Documento' / 'Documento de arrecadação'...")
        clicou_emissao = await clicar_elemento_seguro(
            p_regularize,
            'span.ui-menuitem-text:has-text("Emissão de Documento"), a:has-text("Emissão de Documento")',
            "Emissão de Documento"
        )

        if clicou_emissao:
            await p_regularize.wait_for_timeout(1500)

            await clicar_elemento_seguro(
                p_regularize,
                'a[id*="cabecalho"]:has-text("Documento de arrecadação"), a:has-text("Documento de arrecadação")',
                "Documento de Arrecadação (Menu)"
            )
            await p_regularize.wait_for_timeout(2500)

            # Seleciona a linha de detalhe da conta/negociação
            for ctx in [p_regularize] + p_regularize.frames:
                try:
                    linha_detalhe = ctx.locator("tr.conteudoGrid, tr[role='row']").first
                    if await linha_detalhe.count() > 0 and await linha_detalhe.is_visible():
                        try:
                            await linha_detalhe.click(timeout=3000)
                        except Exception:
                            await linha_detalhe.evaluate("el => el.click()")
                        break
                except Exception:
                    continue

            await p_regularize.wait_for_timeout(1500)

            print("   -> Clicando no botão para gerar o DARF...")
            await clicar_elemento_seguro(
                p_regularize,
                '#formListaDarf\\:idbtnDarf, button:has-text("Documento de Arrecadação"), input[value*="Arrecadação"]',
                "Documento de Arrecadação (Botão)"
            )
            await p_regularize.wait_for_timeout(3000)

        # Executa o download caso as parcelas tenham sido exibidas
        await baixar_darfs_elegiveis_regularize(p_regularize, nome_identificador_arquivo)

        # RETORNA À CONSULTA PRINCIPAL PARA PROCESSAR A PRÓXIMA CONTA
        print("   -> Retornando ao menu para consultar as negociações restantes...")
        await clicar_elemento_seguro(
            p_regularize,
            'span.place-info-box-text:has-text("CONSULTAR"), button:has-text("Voltar"), a:has-text("Voltar")',
            "Voltar / CONSULTAR"
        )
        await p_regularize.wait_for_timeout(2500)

        await clicar_elemento_seguro(
            p_regularize,
            'button.btn.btn-primary:has-text("Continuar")',
            "Continuar"
        )
        await p_regularize.wait_for_timeout(3000)

    # FINALIZAÇÃO E FECHAMENTO
    if abriu_nova_aba:
        print("Finalizado Regularize PGFN. Fechando a aba e voltando ao e-CAC principal...")
        await p_regularize.close()
        await ecac_page.bring_to_front()
    else:
        await clicar_logo_ecac(ecac_page)


async def main():
    print("=" * 70)
    print("RPA PROCONT - INICIANDO")
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

    if coluna_documento is None:
        print("\nERRO: Não encontrei a coluna de CPF/CNPJ.")
        return

    if coluna_tipo is None:
        print("\nERRO: Não encontrei a coluna 'TIPO' na planilha.")
        return

    print(f"\nColuna para CPF/CNPJ: {coluna_documento}")
    if coluna_razao:
        print(f"Coluna para Razão Social: {coluna_razao}")
    else:
        print("Aviso: Coluna de Razão Social não encontrada. Usando apenas CPF/CNPJ.")

    print(f"Coluna para TIPO: {coluna_tipo}")
    print(f"Registros encontrados: {len(df)}")

    async with async_playwright() as p:
        print("\nConectando ao Chrome na porta 9222...")
        try:
            browser = await p.chromium.connect_over_cdp(CHROME_CDP)
        except Exception as erro:
            print(f"\nERRO AO CONECTAR AO CHROME: {erro}")
            return

        contexts = browser.contexts
        if not contexts:
            print("\nERRO: Nenhum contexto do Chrome foi encontrado.")
            return

        context = contexts[0]
        pages = context.pages

        if not pages:
            print("\nERRO: Nenhuma aba encontrada no Chrome.")
            return

        ecac_page = pages[-1]

        print("=" * 70)
        print(f"ABA ENCONTRADA - URL atual: {ecac_page.url}")
        print("=" * 70)

        resultados = []

        for indice, linha in df.iterrows():
            valor_documento = linha[coluna_documento]
            cpf_cnpj = limpar_cpf_cnpj(valor_documento)
            valor_tipo = linha[coluna_tipo]
            tipo_fluxo = tipos_de_fluxo(valor_tipo)

            executar_fluxo_3 = "fluxo 3" in tipo_fluxo
            executar_fluxo_4 = "fluxo 4" in tipo_fluxo

            razao_social_planilha = (
                sanitizar_nome_arquivo(linha[coluna_razao]) if coluna_razao else ""
            )

            if razao_social_planilha:
                base_nome_arquivo = f"{razao_social_planilha}_{cpf_cnpj}"
            else:
                base_nome_arquivo = cpf_cnpj

            if not cpf_cnpj:
                print(f"\nREGISTRO {indice + 1}: CPF/CNPJ vazio. Pulando.")
                continue

            print("\n" + "=" * 70)
            print(f"REGISTRO {indice + 1} DE {len(df)} | NOME: {razao_social_planilha} | CPF/CNPJ: {cpf_cnpj}")
            print(f"TIPO: {valor_tipo} | Fluxo 3: {'SIM' if executar_fluxo_3 else 'NÃO'} | Fluxo 4: {'SIM' if executar_fluxo_4 else 'NÃO'}")
            print("=" * 70)

            try:
                await ecac_page.bring_to_front()

                print("\n1. Clicando em Alterar perfil de acesso...")
                btn_perfil = ecac_page.locator("#btnPerfil").first
                await btn_perfil.wait_for(state="visible", timeout=20000)
                await btn_perfil.click()

                print("\n2. Preenchendo CPF/CNPJ...")
                campo_cnpj = ecac_page.locator("#txtNIPapel2").first
                await campo_cnpj.wait_for(state="visible", timeout=20000)
                await campo_cnpj.fill("")
                await campo_cnpj.fill(cpf_cnpj)

                valor_preenchido = await campo_cnpj.input_value()
                if valor_preenchido != cpf_cnpj:
                    raise Exception("O valor preenchido no campo não corresponde ao CPF/CNPJ.")

                print("\n3. Clicando no Alterar do CNPJ...")
                await clicar_alterar_e_fechar(ecac_page, campo_cnpj)

                print("\n4. Aguardando atualização do perfil...")
                await ecac_page.wait_for_timeout(3000)

                print("\n5. Clicando em Simples Nacional...")
                simples_nacional = ecac_page.locator("#btn266 a", has_text="Simples Nacional").first
                await simples_nacional.wait_for(state="visible", timeout=20000)
                await simples_nacional.click(force=True)

                print("\n6. Clicando em Solicitar, acompanhar e emitir DAS...")
                opcao_parcelamento = ecac_page.locator('a[href="Aplicacao.aspx?id=188&origem=menu"]').first
                await opcao_parcelamento.wait_for(state="visible", timeout=20000)

                p_primeiro_fluxo = ecac_page
                abriu_nova_aba_1 = False

                try:
                    async with context.expect_page(timeout=5000) as new_page_info:
                        await opcao_parcelamento.click(force=True)

                    p_primeiro_fluxo = await new_page_info.value
                    await p_primeiro_fluxo.wait_for_load_state()
                    abriu_nova_aba_1 = True
                    print("Aplicação aberta em uma nova aba.")
                except Exception:
                    print("Aplicação aberta na mesma aba.")

                print("\n7. Clicando em Emissão de Parcela...")
                await clicar_emissao_parcela(p_primeiro_fluxo)

                print("\n8. Resolvendo Captcha...")
                await resolver_e_continuar_captcha(p_primeiro_fluxo)

                print("\n9. Verificando tela de parcelas / alertas...")
                await processar_resultado_parcelas(p_primeiro_fluxo, f"{base_nome_arquivo}_SIMPLES_NACIONAL")

                if abriu_nova_aba_1:
                    print("\n9.1. Fechando aba do primeiro fluxo e voltando ao e-CAC principal...")
                    await p_primeiro_fluxo.close()
                    await ecac_page.bring_to_front()
                else:
                    print("\n9.1. Clicando no e-CAC para retornar ao menu principal...")
                    await clicar_logo_ecac(ecac_page)

                print("\n10. Consulta Secundária: RELP (LC 193/2022)")
                await consultar_relp(ecac_page, context, base_nome_arquivo)

                if executar_fluxo_3:
                    print("\n11. TIPO contém 'fluxo 3'. Executando Consulta Terceira...")
                    await consultar_parcelamento_ordinario(ecac_page, context, base_nome_arquivo)
                else:
                    print("\n11. TIPO não contém 'fluxo 3'. Consulta Terceira não será executada.")

                if executar_fluxo_4:
                    print("\n12. TIPO contém 'fluxo 4'. Executando Consulta Quarta...")
                    await consultar_pgfn_regularize(ecac_page, context, base_nome_arquivo)
                else:
                    print("\n12. TIPO não contém 'fluxo 4'. Consulta Quarta não será executada.")

                resultados.append({
                    "Linha": indice + 2,
                    "Razao_Social": razao_social_planilha,
                    "CPF_CNPJ": cpf_cnpj,
                    "Status": "OK",
                    "Erro": "",
                })

            except Exception as erro:
                log.error(f"Falha no registro {indice + 1} (CNPJ {cpf_cnpj}): {erro}")
                print(f"\n[ERRO NO REGISTRO {indice + 1}]: {erro}")
                resultados.append({
                    "Linha": indice + 2,
                    "Razao_Social": razao_social_planilha,
                    "CPF_CNPJ": cpf_cnpj,
                    "Status": "ERRO",
                    "Erro": f"{type(erro).__name__}: {erro}",
                })
                try:
                    await ecac_page.bring_to_front()
                    await clicar_logo_ecac(ecac_page)
                except Exception:
                    pass

        salvar_relatorio_execucao(resultados, "fluxo1_ecac")


if __name__ == "__main__":
    asyncio.run(main())
