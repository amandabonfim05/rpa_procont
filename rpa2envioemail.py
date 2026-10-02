import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

# ==========================================
# CONFIGURAÇÕES DE E-MAIL
# ==========================================
from rpa_config import CONFIG, caminho, configurar_log

EMAIL_REMETENTE = CONFIG["email_remetente"]
SENHA_APP_GMAIL = CONFIG["email_senha"]
EMAIL_DESTINATARIO = CONFIG["email_destinatario"] or EMAIL_REMETENTE

PASTA_PARCELAMENTOS = caminho("parcelamento")
ASSUNTO_EMAIL = "Documentos de Parcelamento - Setor Fiscal"

log = configurar_log("rpa2envioemail")

# ==========================================
# FUNÇÃO DE ENVIO DE E-MAIL
# ==========================================

def enviar_arquivos_parcelamento():
    print("=" * 70)
    print("RPA PROCONT - DISPARO DE E-MAILS")
    print("=" * 70)

    # 1. Validação da pasta local
    if not os.path.exists(PASTA_PARCELAMENTOS):
        print(f"❌ ERRO: A pasta '{PASTA_PARCELAMENTOS}' não foi localizada.")
        return

    # 2. Listar arquivos da pasta
    arquivos = [
        f for f in os.listdir(PASTA_PARCELAMENTOS)
        if os.path.isfile(os.path.join(PASTA_PARCELAMENTOS, f)) and not f.startswith(".")
    ]

    if not arquivos:
        print(f"⚠️ NENHUM arquivo encontrado dentro da pasta '{PASTA_PARCELAMENTOS}'.")
        return

    print(f"📁 Total de {len(arquivos)} arquivo(s) localizado(s) para anexar:\n")
    for arq in arquivos:
        print(f"   • {arq}")

    # 3. Montagem da Mensagem MIME
    msg = MIMEMultipart()
    msg['From'] = EMAIL_REMETENTE
    msg['To'] = EMAIL_DESTINATARIO
    msg['Subject'] = ASSUNTO_EMAIL

    corpo_mensagem = f"""
    Olá, equipe do Setor Fiscal,

    Segue em anexo a lista com todos os documentos de parcelamento baixados pelo RPA PROCONT ({len(arquivos)} arquivo(s)).

    Atenciosamente,
    Automação RPA PROCONT - HMAILTON JR
    """
    msg.attach(MIMEText(corpo_mensagem, 'plain'))

    # 4. Anexar todos os arquivos da pasta
    print("\n📎 Anexando arquivos ao e-mail...")
    for arq in arquivos:
        caminho_completo = os.path.join(PASTA_PARCELAMENTOS, arq)
        try:
            with open(caminho_completo, "rb") as f:
                part = MIMEApplication(f.read(), Name=arq)
                part['Content-Disposition'] = f'attachment; filename="{arq}"'
                msg.attach(part)
                print(f"   ✅ Anexado: {arq}")
        except Exception as err:
            print(f"   ❌ Falha ao anexar {arq}: {err}")

    # 5. Conexão e envio via SMTP do Gmail
    try:
        print(f"\n📧 Conectando ao servidor SMTP do Gmail para enviar a {EMAIL_DESTINATARIO}...")
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(EMAIL_REMETENTE, SENHA_APP_GMAIL)
        
        server.send_message(msg)
        server.quit()
        
        print("\n🚀 E-mail enviado com sucesso com todos os anexos de parcelamento!")

    except Exception as e:
        log.error(f"Erro ao enviar e-mail via SMTP: {e}")
        print(f"\n❌ ERRO ao enviar e-mail via SMTP: {e}")

# ==========================================
# EXECUÇÃO
# ==========================================
if __name__ == "__main__":
    enviar_arquivos_parcelamento()