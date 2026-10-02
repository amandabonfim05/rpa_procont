import os
import re
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ==========================================
# CONFIGURAÇÕES E PARÂMETROS
# ==========================================
from rpa_config import CONFIG, caminho, configurar_log, salvar_relatorio_execucao

NOME_PASTA = "parcelamento"
PASTA_PARCELAMENTOS = caminho(NOME_PASTA)

log = configurar_log("rpa2taskdo")
resultados = []


def perguntar_data_alvo():
    """Pergunta a data ao usuário no console, validando o formato DD/MM/AAAA.
    Se o usuário só apertar Enter, usa o valor salvo no config.json."""

    data_padrao = CONFIG.get("data_alvo_taskdo", "")

    while True:
        if data_padrao:
            entrada = input(
                f"\nDigite a data de protocolo (DD/MM/AAAA) "
                f"[Enter para usar {data_padrao}]: "
            ).strip()

            if not entrada:
                return data_padrao
        else:
            entrada = input("\nDigite a data de protocolo (DD/MM/AAAA): ").strip()

        if re.match(r"^\d{2}/\d{2}/\d{4}$", entrada):
            return entrada

        print("Data inválida. Use o formato DD/MM/AAAA, por exemplo 25/09/2026.")


DATA_ALVO = perguntar_data_alvo()
print(f"\nUsando {DATA_ALVO} como data de protocolo para esta execução.")


def fechar_modal_se_aberto(driver):
    """Fecha o modal de movimentação/anexos caso ainda esteja visível na tela."""
    try:
        xpath_btn_fechar = "//div[contains(@class, 'ui-dialog') and contains(@style, 'display: block')]//a[contains(@class, 'ui-dialog-titlebar-close')]"
        btn_fechar = driver.find_elements(By.XPATH, xpath_btn_fechar)
        if btn_fechar and btn_fechar[0].is_displayed():
            driver.execute_script("arguments[0].click();", btn_fechar[0])
            time.sleep(1.5)
    except Exception:
        pass


def extrair_tipo_e_empresa(nome_arquivo):
    """
    Extrai o nome da empresa e o tipo de parcelamento com base no nome do arquivo.
    Exemplo: AMANDA_0000000000_INSS.pdf -> Empresa: AMANDA, Tipo: INSS
    """
    nome_sem_ext = os.path.splitext(nome_arquivo)[0]
    
    # Identifica o tipo do parcelamento baseado em palavras-chave no nome do arquivo
    nome_upper = nome_sem_ext.upper()
    
    if "SIMPLES_NACIONAL" in nome_upper or "SIMPLES NACIONAL" in nome_upper:
        tipo_parcelamento = "SIMPLES_NACIONAL"
    elif "RELP" in nome_upper:
        tipo_parcelamento = "RELP"
    elif "DCTFWEB" in nome_upper:
        tipo_parcelamento = "DCTFWEB"
    elif "PARCELAMENTO_ORDINARIO" in nome_upper or "INSS" in nome_upper:
        tipo_parcelamento = "INSS"
    elif "PGFN" in nome_upper and "PESSOA_FISICA" in nome_upper:
        tipo_parcelamento = "PGFN_PF"
    elif "PGFN" in nome_upper:
        tipo_parcelamento = "PGFN"
    else:
        tipo_parcelamento = "GERAL"

    # Extrai a empresa removendo CNPJ e sufixos conhecidos
    empresa = re.split(r'_\d{14}|_\d{2}\.\d{3}\.\d{3}', nome_sem_ext)[0]
    # Remove sufixos comuns de categoria se ainda estiverem colados
    empresa = re.sub(r'_(INSS|SIMPLES_NACIONAL|SIMPLES|RELP|DCTFWEB|PARCELAMENTO_ORDINARIO|PGFN.*)$', '', empresa, flags=re.IGNORECASE)
    
    return empresa.strip().upper(), tipo_parcelamento


def arquivo_corresponde_ao_link(tipo_arquivo, nome_link_site):
    """
    Verifica se a categoria do arquivo corresponde ao nome do link aberto no site.
    """
    link_upper = nome_link_site.upper()
    
    if tipo_arquivo == "SIMPLES_NACIONAL" and ("SIMPLES NACIONAL NORMAL" in link_upper or "SIMPLES NACIONAL 60" in link_upper):
        return True
    if tipo_arquivo == "RELP" and "RELP" in link_upper:
        return True
    if tipo_arquivo == "DCTFWEB" and "DCTFWEB" in link_upper:
        return True
    if tipo_arquivo == "INSS" and ("INSS RECEITA FEDERAL" in link_upper or "INSS" in link_upper or "PARCELAMENTO ORDINARIO" in link_upper):
        return True
    if tipo_arquivo == "PGFN_PF" and "PESSOA FISICA PGFN" in link_upper:
        return True
    if tipo_arquivo == "PGFN" and "PGFN DIVIDA ATIVA" in link_upper:
        return True
    if tipo_arquivo == "GERAL" and "PARCELAMENTO" in link_upper:
        return True
        
    return False


def obter_arquivos_locais(diretorio):
    """Lê todos os arquivos do diretório e retorna seus metadados."""
    if not os.path.exists(diretorio):
        print(f"❌ ERRO: A pasta '{diretorio}' não foi encontrada.")
        return []

    arquivos = [
        f for f in os.listdir(diretorio)
        if os.path.isfile(os.path.join(diretorio, f)) and not f.startswith(".")
    ]

    lista_arquivos = []
    for arq in arquivos:
        empresa, tipo = extrair_tipo_e_empresa(arq)
        caminho_abs = os.path.abspath(os.path.join(diretorio, arq))
        lista_arquivos.append({
            "arquivo": arq,
            "caminho_abs": caminho_abs,
            "empresa": empresa,
            "tipo": tipo
        })

    return lista_arquivos


def executar_logica_2(driver, nome_empresa, caminhos_arquivos_abs):
    """
    Função dedicada para anexar arquivos, salvar e realizar todo o fluxo final de protocolo e encerramento.
    """
    print(f"--> [LÓGICA 2] Executando anexação e protocolo para '{nome_empresa}'...")

    try:
        # 1. Clicar na aba 'Anexos'
        xpath_aba_anexos = "//a[contains(@href, 'tabViewMovimento') and contains(normalize-space(.), 'Anexos')]"
        aba_anexos = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, xpath_aba_anexos))
        )
        
        driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", aba_anexos)
        time.sleep(0.5)
        
        try:
            aba_anexos.click()
        except Exception:
            driver.execute_script("arguments[0].click();", aba_anexos)
            
        print("   📌 Aba 'Anexos' clicada com sucesso!")
        time.sleep(1.5)

        # 2. Inserir TODOS os arquivos correspondentes da empresa
        xpath_input_file = "//input[@type='file' and contains(@id, 'fileUpload')]"

        if isinstance(caminhos_arquivos_abs, str):
            caminhos_arquivos_abs = [caminhos_arquivos_abs]

        caminhos_arquivos_abs = [
            os.path.abspath(caminho)
            for caminho in caminhos_arquivos_abs
            if os.path.isfile(caminho)
        ]

        if not caminhos_arquivos_abs:
            raise FileNotFoundError(f"Nenhum arquivo válido encontrado para a empresa '{nome_empresa}'.")

        print(f"   📎 Total de anexos para '{nome_empresa}': {len(caminhos_arquivos_abs)}")

        for numero_arquivo, caminho_arquivo_abs in enumerate(caminhos_arquivos_abs, start=1):
            input_file = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, xpath_input_file))
            )

            nome_arquivo = os.path.basename(caminho_arquivo_abs)

            # Injeta o arquivo no input
            input_file.send_keys(caminho_arquivo_abs)
            print(f"   📎 Anexo {numero_arquivo}/{len(caminhos_arquivos_abs)} selecionado: '{nome_arquivo}'")
            time.sleep(1.5)

            # Tenta acionar o upload
            try:
                xpath_btn_upload = "//div[contains(@class, 'ui-fileupload-content')]//button[contains(@class, 'ui-fileupload-upload') or .//span[contains(text(),'Enviar') or contains(text(),'Upload')]]"
                btns = driver.find_elements(By.XPATH, xpath_btn_upload)
                
                if btns and btns[0].is_displayed():
                    driver.execute_script("arguments[0].click();", btns[0])
                    print("   ⬆️ Upload acionado via botão da fila...")
                else:
                    driver.execute_script(
                        """
                        var uploadWidget = PrimeFaces.widgets[Object.keys(PrimeFaces.widgets).find(k => k.includes('fileUpload'))];
                        if (uploadWidget) {
                            uploadWidget.upload();
                        } else {
                            var input = document.querySelector("input[type='file'][id*='fileUpload']");
                            if (input) input.dispatchEvent(new Event('change', { bubbles: true }));
                        }
                        """
                    )
                    print("   ⬆️ Upload acionado via JS PrimeFaces Widget...")
            except Exception as e_up:
                print(f"   ⚠️ Aviso ao acionar upload: {e_up}")

            time.sleep(3)

        print(f"   ✅ Todos os {len(caminhos_arquivos_abs)} anexos foram enviados para '{nome_empresa}'.")

        # 3. Clicar no botão 'Salvar' (Aba Anexos)
        xpath_btn_salvar = "//button[contains(@id, 'btnSalvar') or .//span[normalize-space(text())='Salvar'] or contains(normalize-space(.), 'Salvar')]"
        btn_salvar = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.XPATH, xpath_btn_salvar))
        )
        
        driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", btn_salvar)
        time.sleep(1)

        try:
            btn_salvar.click()
        except Exception:
            driver.execute_script("arguments[0].click();", btn_salvar)

        print("   💾 Botão 'Salvar' (Anexos) clicado! Aguardando processamento AJAX...")
        time.sleep(4)

        # 4. Marcar o Checkbox 'Selecionar Todos' da tabela de anexos
        id_chk_input = "tabViewMovimento:selecionarTodos_input"
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, id_chk_input))
            )

            driver.execute_script(
                """
                var el = document.getElementById(arguments[0]);
                if (el) {
                    if (!el.checked) {
                        el.click();
                        var evt = document.createEvent('HTMLEvents');
                        evt.initEvent('change', true, true);
                        el.dispatchEvent(evt);
                    }
                }
                """, 
                id_chk_input
            )
            print("   ☑️ Checkbox 'Selecionar Todos Anexos' marcado!")
            time.sleep(2)
        except Exception as err_chk:
            print(f"   ⚠️ Alerta ao marcar checkbox 'Selecionar Todos Anexos': {err_chk}")

        # 5. Clicar no botão 'Gerar protocolo'
        xpath_btn_protocolo = "//button[contains(@id, 'btnProtocolo') or .//span[normalize-space(text())='Gerar protocolo'] or contains(normalize-space(.), 'Gerar protocolo')]"
        btn_protocolo = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, xpath_btn_protocolo))
        )

        driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", btn_protocolo)
        time.sleep(0.5)

        try:
            btn_protocolo.click()
        except Exception:
            driver.execute_script("arguments[0].click();", btn_protocolo)

        print("   📄 Botão 'Gerar protocolo' clicado com sucesso!")
        time.sleep(3.5)

        # 6. Marcar o Checkbox 'Selecionar Todos E-mails'
        id_emails_chk = "clienteEmailsForm:selecionarTodos_input"
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, id_emails_chk))
            )

            driver.execute_script(
                """
                var el = document.getElementById(arguments[0]);
                if (el) {
                    if (!el.checked) {
                        el.click();
                        var evt = document.createEvent('HTMLEvents');
                        evt.initEvent('change', true, true);
                        el.dispatchEvent(evt);
                    }
                }
                """, 
                id_emails_chk
            )
            print("   ✉️ Checkbox 'Selecionar Todos E-mails' marcado!")
            time.sleep(2)
        except Exception as err_email_chk:
            print(f"   ⚠️ Alerta ao marcar checkbox de e-mails: {err_email_chk}")

        # 7. Clicar no botão 'Enviar'
        xpath_btn_enviar = "//button[contains(@id, 'clienteEmailsForm') and (contains(@id, 'j_idt') or .//span[normalize-space(text())='Enviar'])]"
        try:
            btn_enviar = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, xpath_btn_enviar))
            )
            driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", btn_enviar)
            time.sleep(0.5)

            try:
                btn_enviar.click()
            except Exception:
                driver.execute_script("arguments[0].click();", btn_enviar)

            print("   🚀 Botão 'Enviar' clicado com sucesso!")
            time.sleep(4)
        except Exception as err_enviar:
            print(f"   ❌ Erro ao clicar no botão 'Enviar': {err_enviar}")

        # 8. Clicar na aba 'Movimentação'
        xpath_aba_movimentacao = "//a[@href='#tabViewMovimento:dialogTabMovimentacao' or contains(normalize-space(.), 'Movimentação')]"
        try:
            aba_movimentacao = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, xpath_aba_movimentacao))
            )
            driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", aba_movimentacao)
            time.sleep(0.5)

            try:
                aba_movimentacao.click()
            except Exception:
                driver.execute_script("arguments[0].click();", aba_movimentacao)

            print("   📌 Aba 'Movimentação' clicada com sucesso!")
            time.sleep(2)
        except Exception as err_aba_mov:
            print(f"   ❌ Erro ao clicar na aba Movimentação: {err_aba_mov}")

        # 9. Clicar na label/checkbox 'Finalizar'
        xpath_label_finalizar = "//label[@for='tabViewMovimento:finalizar']"
        try:
            label_finalizar = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, xpath_label_finalizar))
            )
            driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", label_finalizar)
            time.sleep(0.5)

            try:
                label_finalizar.click()
            except Exception:
                driver.execute_script("arguments[0].click();", label_finalizar)

            print("   ✅ Label/Option 'Finalizar' clicada com sucesso!")
            time.sleep(1.5)
        except Exception as err_fin:
            print(f"   ❌ Erro ao clicar no label Finalizar: {err_fin}")

        # 10. Clicar no botão 'Salvar' final da aba Movimentação
        xpath_btn_salvar_final = "//button[contains(@id, 'tabViewMovimento') and (contains(@class, 'btn-success') or .//span[text()='Salvar'])]"
        try:
            btn_salvar_final = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, xpath_btn_salvar_final))
            )
            driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", btn_salvar_final)
            time.sleep(0.5)

            try:
                btn_salvar_final.click()
            except Exception:
                driver.execute_script("arguments[0].click();", btn_salvar_final)

            print("   💾 Botão 'Salvar' final clicado com sucesso!")
            time.sleep(4)
        except Exception as err_salvar_fin:
            print(f"   ❌ Erro ao clicar no botão Salvar final: {err_salvar_fin}")

    except Exception as e:
        print(f"   ❌ Erro durante o processo para '{nome_empresa}': {e}")
    finally:
        fechar_modal_se_aberto(driver)


# ==========================================
# INÍCIO DO ROBÔ (RPA)
# ==========================================

driver = webdriver.Chrome()
driver.maximize_window()

try:
    url_login = "https://www.taskdo.com.br/app/index.xhtml"
    driver.get(url_login)
    print("\n[AÇÃO MANUAL] Por favor, faça o login na TaskDO...")

    WebDriverWait(driver, 300).until(
        lambda d: "index.xhtml" not in d.current_url or "painel.xhtml" in d.current_url or "paginas" in d.current_url
    )
    print("[LOGIN CONFIRMADO] Iniciando busca no painel...\n")
    time.sleep(3)

    # Obtém todos os arquivos presentes na pasta parcelamento
    todos_arquivos = obter_arquivos_locais(PASTA_PARCELAMENTOS)
    print(f"📁 Total de arquivos locais carregados: {len(todos_arquivos)}")

    # Localiza o bloco da data alvo na tela
    xpath_data = f"//span[contains(@class, 'bg-orange') and contains(text(), '{DATA_ALVO}')]"
    try:
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.XPATH, xpath_data)))
        print(f"✅ Bloco da data '{DATA_ALVO}' localizado no painel!")
    except Exception:
        print(f"⚠️ Alerta: Data {DATA_ALVO} não encontrada na tela.")

    # Busca todos os links/labels de parcelamentos abaixo da data alvo
    xpath_links_data = (
        f"//span[contains(@class, 'bg-orange') and contains(text(), '{DATA_ALVO}')]"
        f"/following::label[contains(@class, 'ui-outputlabel') and starts-with(normalize-space(text()), 'PARCELAMENTO')]"
        f"[not(preceding::span[contains(@class, 'bg-orange')][1][not(contains(text(), '{DATA_ALVO}'))])]"
    )

    links_elementos = driver.find_elements(By.XPATH, xpath_links_data)
    total_links = len(links_elementos)
    print(f"🔗 Encontrados {total_links} link(s) para a data {DATA_ALVO}.\n")

    for idx in range(total_links):
        # Reobter lista de elementos atualizada no DOM após navegações anteriores
        links_elementos = driver.find_elements(By.XPATH, xpath_links_data)
        if idx >= len(links_elementos):
            break

        el_link = links_elementos[idx]
        nome_link_site = el_link.text.strip()

        print(f"\n==================================================")
        print(f"👉 Clicando no Link #{idx + 1}/{total_links}: '{nome_link_site}'")
        print(f"==================================================")

        driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", el_link)
        time.sleep(1)

        try:
            el_link.click()
        except Exception:
            driver.execute_script("arguments[0].click();", el_link)

        time.sleep(3)

        # Filtra os arquivos que correspondem ao tipo desse link do site
        arquivos_do_link = [
            item for item in todos_arquivos
            if arquivo_corresponde_ao_link(item["tipo"], nome_link_site)
        ]

        if not arquivos_do_link:
            print(f"ℹ️ Nenhum arquivo local correspondente para o link '{nome_link_site}'.")
            continue

        # Agrupa arquivos por empresa
        mapa_empresas = {}
        for item in arquivos_do_link:
            emp = item["empresa"]
            if emp not in mapa_empresas:
                mapa_empresas[emp] = []
            mapa_empresas[emp].append(item["caminho_abs"])

        # Para cada empresa do link, procura a linha no site e envia os anexos
        for empresa, caminhos_arquivos in mapa_empresas.items():
            print(f"\n   🔍 Procurando cliente '{empresa}' na tabela...")

            xpath_linha_empresa = f"//tr[td[contains(normalize-space(.), '{empresa}')]]"

            try:
                linha = WebDriverWait(driver, 8).until(
                    EC.presence_of_element_located((By.XPATH, xpath_linha_empresa))
                )

                xpath_btn_acoes = ".//button[@title='Movimentações' or contains(@class, 'btn-text-success')]"
                btn_acoes = WebDriverWait(linha, 5).until(
                    EC.element_to_be_clickable((By.XPATH, xpath_btn_acoes))
                )

                driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", btn_acoes)
                time.sleep(0.5)

                try:
                    btn_acoes.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", btn_acoes)

                print(f"   ✅ Botão 'Movimentações' clicado para '{empresa}'!")

                # Executa o fluxo completo de upload, salvar, protocolo e envio
                executar_logica_2(driver, empresa, caminhos_arquivos)

                resultados.append({
                    "Empresa": empresa,
                    "Link": nome_link_site,
                    "Status": "OK",
                    "Erro": "",
                })

            except Exception as err:
                log.error(f"Falha na empresa '{empresa}' (link '{nome_link_site}'): {err}")
                print(f"   ❌ Empresa '{empresa}' não foi encontrada na tabela do link '{nome_link_site}' ou falhou: {err}")
                fechar_modal_se_aberto(driver)
                resultados.append({
                    "Empresa": empresa,
                    "Link": nome_link_site,
                    "Status": "ERRO",
                    "Erro": f"{type(err).__name__}: {err}",
                })

finally:
    salvar_relatorio_execucao(resultados, "taskdo")
    print("\n🏁 Processamento concluído!")