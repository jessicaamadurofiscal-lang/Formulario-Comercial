"""
extrator.py — Lê PDF de contrato social ou formulário e extrai dados estruturados
Estratégias em ordem:
  1. pdfplumber (texto nativo — melhor para contratos sociais digitais)
  2. pypdf (fallback texto nativo)
  3. OCR via tesseract (para PDFs escaneados ou exportados como imagem)
Sem custo, sem internet, sem API.
"""

import re, sys, json, os, subprocess, tempfile
from pathlib import Path

try:
    import pdfplumber; HAS_PLUMBER = True
except ImportError:
    HAS_PLUMBER = False

try:
    from pypdf import PdfReader; HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False

try:
    import pytesseract
    from PIL import Image
    HAS_OCR = True
except ImportError:
    HAS_OCR = False


# ── EXTRAÇÃO DE TEXTO ─────────────────────────────────────────────────────────

def extrair_texto_nativo(pdf: str) -> str:
    texto = ""
    if HAS_PLUMBER:
        try:
            with pdfplumber.open(pdf) as p:
                texto = "\n".join(pg.extract_text() or "" for pg in p.pages)
        except Exception: pass
    if not texto.strip() and HAS_PYPDF:
        try:
            r = PdfReader(pdf)
            texto = "\n".join(pg.extract_text() or "" for pg in r.pages)
        except Exception: pass
    return texto

def extrair_texto_ocr(pdf: str) -> str:
    """Rasteriza o PDF e aplica OCR página por página."""
    texto_total = []
    with tempfile.TemporaryDirectory() as tmp:
        # Converte PDF → imagens via pdftoppm
        prefix = os.path.join(tmp, "pag")
        r = subprocess.run(
            ["pdftoppm", "-jpeg", "-r", "250", pdf, prefix],
            capture_output=True, timeout=120
        )
        imgs = sorted(Path(tmp).glob("*.jpg"))
        if not imgs:
            # Fallback: tenta com png
            subprocess.run(["pdftoppm", "-png", "-r", "250", pdf, prefix], capture_output=True, timeout=120)
            imgs = sorted(Path(tmp).glob("*.png"))

        for img_path in imgs:
            try:
                if HAS_OCR:
                    img = Image.open(str(img_path))
                    # Tenta português primeiro, fallback inglês
                    try:
                        t = pytesseract.image_to_string(img, lang="por+eng")
                    except Exception:
                        try:
                            t = pytesseract.image_to_string(img, lang="por")
                        except Exception:
                            t = pytesseract.image_to_string(img, lang="eng")
                    texto_total.append(t)
                else:
                    # Tesseract direto via CLI
                    r2 = subprocess.run(
                        ["tesseract", str(img_path), "stdout", "-l", "por+eng"],
                        capture_output=True, text=True, timeout=60
                    )
                    if r2.returncode != 0:
                        r2 = subprocess.run(
                            ["tesseract", str(img_path), "stdout", "-l", "eng"],
                            capture_output=True, text=True, timeout=60
                        )
                    texto_total.append(r2.stdout)
            except Exception as e:
                print(f"[OCR] {img_path.name}: {e}", file=sys.stderr)

    return "\n".join(texto_total)

def extrair_texto(pdf: str) -> tuple[str, str]:
    """Retorna (texto, método_usado)."""
    t = extrair_texto_nativo(pdf)
    if len(t.strip()) > 100:
        return t, "nativo"
    # PDF sem texto — usa OCR
    t = extrair_texto_ocr(pdf)
    return t, "ocr"


# ── HELPERS ───────────────────────────────────────────────────────────────────

def lim(s: str) -> str:
    return re.sub(r'\s+', ' ', s or "").strip()

def first(*patterns, texto="", flags=re.IGNORECASE) -> str:
    for pat in patterns:
        m = re.search(pat, texto, flags | re.DOTALL)
        if m:
            gs = [g for g in m.groups() if g]
            if gs: return lim(gs[0])
    return ""


# ── EXTRATORES ────────────────────────────────────────────────────────────────

def ext_cnpj(t):
    for m in re.findall(r'\d{2}[\.\s]?\d{3}[\.\s]?\d{3}[\s\/]?\d{4}[-\s]?\d{2}', t):
        d = re.sub(r'\D','',m)
        if len(d)==14:
            return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    return ""

def ext_razao(t):
    """Extrai razão social — prioriza campo NOME EMPRESARIAL do cartão CNPJ."""
    import re as _re
    m = _re.search(r'NOME\s+EMPRESARIAL\s*\n\s*([^\n]+)', t, _re.I)
    if m: return lim(m.group(1))
    return first(
        r'(?:denominada?|empresa|sociedade|firma)\s+["\']?([A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-ZÁÉÍÓÚÂÊÔÃÕÇ\s\&\.\,\-]{5,80})["\']?',
        r'(?:Raz[aã]o Social)\s*[:\-]?\s*([^\n]{5,80})',
        r'([A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-ZÁÉÍÓÚÂÊÔÃÕÇ\s\&\.]{5,60}(?:LTDA|ME|EIRELI|S\.A\.|EPP|MEI)\.?)',
        texto=t
    )


def ext_atividade(t):
    # Campo do cartão CNPJ: linha após "ATIVIDADE ECONOMICA PRINCIPAL"
    m = re.search(r'ATIVIDADE.{1,30}PRINCIPAL\s*\n\s*([^\n]+)', t, re.I)
    if m:
        linha = m.group(1).strip()
        # Remove o código CNAE do início: "47.81-4-00 - Descrição" -> "Descrição"
        linha = re.sub(r'^[\d\.\-]+\s*-\s*', '', linha).strip()
        if linha: return linha
    return first(
        r'(?:Atividade Principal|objeto social|ramo de atividade)\s*[:\-]?\s*([^\n]{15,200})',
        r'(?:CNAE|c[oó]digo de atividade)\s*[:\-]?\s*[\d\.]+\s*[-–]\s*([^\n]{10,120})',
        r'tem por objeto\s+(?:social\s+)?(.{15,200}?)(?:\.|$)',
        texto=t
    )

def ext_capital(t):
    v = first(
        r'(?:capital social|Capital Social|Valor do Honor[aá]rio)\s*[:\-]?\s*R\$\s*([\d\.\,]+)',
        r'R\$\s*([\d\.\,]+)\s*\(.*?reais',
        texto=t
    )
    # "Valor do Honorário" é honorário, não capital — tratado separado
    cap = first(
        r'[Cc]apital\s+[Ss]ocial.*?R\$\s*([\d\.\,]+)',
        r'[Cc]apital\s+(?:subscrito|integralizado).*?R\$\s*([\d\.\,]+)',
        texto=t
    )
    return f"R$ {cap}" if cap else ""

def ext_honorario(t):
    v = first(
        r'[Vv]alor do [Hh]onor[aá]rio\s*[:\-]?\s*R\$\s*([\d\.\,]+)',
        r'[Hh]onor[aá]rio[s]?\s*[:\-]?\s*R\$\s*([\d\.\,]+)',
        texto=t
    )
    return f"R$ {v}" if v else ""

def ext_socios(t):
    socios = set()
    for m in re.findall(
        r'([A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+(?:\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+){1,5})'
        r'(?:,|\s+)(?:portador|inscrito|CPF|brasileiro|brasileira)',
        t, re.IGNORECASE
    ): socios.add(lim(m))

    bloco = first(r'(?:s[oó]cios?|quadro societ[aá]rio)\s*[:\-]?\s*((?:[^\n]+\n){1,15})', texto=t)
    if bloco:
        for linha in bloco.split('\n'):
            m = re.match(r'^([A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+(?:\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+){1,4})', linha.strip())
            if m: socios.add(lim(m.group(1)))

    excl = {'Ltda','Eireli','Brasil','Social','Capital','Objeto','Contrato','Nacional','Presumido'}
    return [s for s in socios if len(s)>8 and s not in excl][:8]

def ext_endereco(t):
    """Monta endereço completo — cobre o layout real do cartão CNPJ da Receita Federal."""
    import re as _re

    # ── Layout cartão CNPJ: campos em colunas ──
    # Linha única com rua+numero+complemento após "LOGRADOURO NUMERO COMPLEMENTO"
    lograd_m = _re.search(
        r'LOGRADOURO\s+N[ÚU]MERO\s+COMPLEMENTO\s*\n\s*([^\n]+)', t, _re.I)
    cep_m = _re.search(
        r'(\d{2}[. -]\d{3}[. -]\d{3})\s+(\S+)\s+(.+?)\s+([A-Z]{2})\s*$',
        t, _re.I | _re.M)
    _ufs = {'AC','AL','AP','AM','BA','CE','DF','ES','GO','MA','MT','MS','MG','PA','PB','PR','PE','PI','RJ','RN','RS','RO','RR','SC','SP','SE','TO'}
    if cep_m and cep_m.group(4).upper() not in _ufs:
        cep_m = None

    if lograd_m and cep_m:
        rua_num = lograd_m.group(1).strip()
        cep_val    = cep_m.group(1)
        bairro_val = cep_m.group(2).strip()
        munic_val  = cep_m.group(3).strip()
        uf_val     = cep_m.group(4).strip()
        partes_end = [rua_num]
        if bairro_val: partes_end.append(bairro_val)
        partes_end.append(f'{munic_val}/{uf_val}')
        partes_end.append(f'CEP {cep_val}')
        return ' — '.join(partes_end)

    # ── Layout com campos separados (ex: contrato social) ──
    lograd  = _re.search(r'LOGRADOURO\s*[:\-]?\s*([^\n]+)', t, _re.I)
    numero  = _re.search(r'N[ÚU]MERO\s*[:\-]?\s*([^\n]+)', t, _re.I)
    compl   = _re.search(r'COMPLEMENTO\s*[:\-]?\s*([^\n]+)', t, _re.I)
    bairro  = _re.search(r'BAIRRO(?:/DISTRITO)?\s*[:\-]?\s*([^\n]+)', t, _re.I)
    munic   = _re.search(r'MUNIC[IÍ]PIO\s*[:\-]?\s*([^\n]+)', t, _re.I)
    uf      = _re.search(r'\bUF\s*[:\-]?\s*([A-Z]{2})\b', t)
    cep     = _re.search(r'CEP\s*[:\-]?\s*([\d\.\-]+)', t, _re.I)

    if lograd:
        partes = []
        rua = lograd.group(1).strip()
        if numero and _re.sub(r'\s','',numero.group(1)) not in ('','S/N','SN','0'):
            rua = rua + ', ' + numero.group(1).strip()
        partes.append(rua)
        if compl and compl.group(1).strip():
            partes.append(compl.group(1).strip())
        if bairro: partes.append(bairro.group(1).strip())
        cidade = ''
        if munic: cidade = munic.group(1).strip()
        if uf:    cidade = (cidade + '/' + uf.group(1)) if cidade else uf.group(1)
        if cidade: partes.append(cidade)
        if cep:   partes.append('CEP ' + cep.group(1).strip())
        return ' — '.join(p for p in partes if p)

    # ── Fallback genérico ──
    return first(
        r'(?:Rua|Av\.|Avenida|Alameda|Travessa)\s+[^\n]{10,120}',
        r'Localiza[çc][aã]o\s*[:\-]?\s*([^\n]{10,150})',
        texto=t
    )


def ext_data(t):
    """Extrai data de abertura — entende o layout do cartão CNPJ da Receita Federal."""
    import re as _re
    # Cartão CNPJ: data aparece na linha "... CADASTRAL  24/08/2018"
    m = _re.search(r'CADASTRAL\s+(\d{2}[/\-\.]\d{2}[/\-\.]\d{4})', t, _re.I)
    if m: return m.group(1).strip()
    # Campo explícito
    m = _re.search(r'DATA\s+DE\s+ABERTURA[^\d]*(\d{2}[/\-\.]\d{2}[/\-\.]\d{4})', t, _re.I)
    if m: return m.group(1).strip()
    return first(
        r'(?:constitu[iíi]da?|fundada?|celebrado?)\s+(?:em|no dia)?\s*(\d{1,2}[\s/\-\.]+(?:de\s+)?(?:janeiro|fevereiro|março|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro|\d{1,2})[\s/\-\.]+(?:de\s+)?\d{4})',
        r'[Dd]ata\s+(?:de\s+)?(?:abertura|constitu[iíi][çc][aã]o)\s*[:\-]?\s*(\d{1,2}[\s/\-\.]\d{1,2}[\s/\-\.]\d{4})',
        texto=t
    )


def ext_regime(t):
    tl = t.lower()
    if 'simples nacional' in tl: return 'Simples Nacional'
    if 'lucro presumido'  in tl: return 'Lucro Presumido'
    if 'lucro real'       in tl: return 'Lucro Real'
    if 'microempreendedor' in tl or ' mei ' in tl: return 'MEI'
    return ''

def inferir_porte(t, cap):
    """Infere porte — prioriza campo PORTE explícito do cartão CNPJ."""
    import re as _re
    tl = t.lower()

    # Campo PORTE explícito do cartão CNPJ (ex: "PORTE\nME" ou "THEMARE ME\n")
    m = _re.search(r'\bPORTE\b[^\n]*?\b(MEI|ME|EPP)\b', t, _re.I)
    if not m:
        # Pode estar no final da linha do nome fantasia: "THEMARE                ME"
        m = _re.search(r'(?:TITULO|TÍTULO)[^\n]*\n[^\n]+?\s+(MEI|ME|EPP)\s*\n', t, _re.I)
    if m: return m.group(1).upper()

    if 'microempreendedor individual' in tl: return 'MEI'
    if cap:
        d = re.sub(r'[^\d]','', cap.replace(',','.').split('.')[0])
        try:
            v = float(d)
            if   v <= 81_000:    return 'MEI'
            elif v <= 360_000:   return 'ME'
            elif v <= 4_800_000: return 'EPP'
            else:                return 'Médio Porte'
        except: pass
    if 'microempresa' in tl or ' me ' in tl: return 'ME'
    if 'empresa de pequeno porte' in tl: return 'EPP'
    if 'eireli' in tl: return 'ME'
    return ''


def ext_cnaes(t):
    cnaes = []
    pat_principal = re.search(
        r'ATIVIDADE.{1,30}PRINCIPAL\s*\n\s*([^\n]+)', t, re.I)
    if pat_principal:
        linha = pat_principal.group(1).strip()
        if re.match(r'[\d]+[.\-]', linha):
            cnaes.append('Principal: ' + linha)
    bloco = re.search(
        r'ATIVIDADES.{1,30}SECUNDARIAS\s*\n(.*?)(?:CODIGO.{1,30}NATUREZA|LOGRADOURO|CEP\s+BAIRRO)',
        t, re.I | re.DOTALL)
    if bloco:
        for linha in bloco.group(1).split('\n'):
            linha = linha.strip()
            if re.match(r'\d{2}[. ]\d{2}[-]\d[-]\d{2}\s*-', linha):
                cnaes.append(linha)
            elif cnaes and linha and not re.match(r'[A-Z]{4,}\s+[A-Z]', linha):
                if not re.match(r'\d{2}[./]', linha):
                    cnaes[-1] = cnaes[-1] + ' ' + linha
    if not cnaes:
        for cod, desc in re.findall(r'(\d{2}[. ]\d{2}[-]\d[-]\d{2})\s*[-]\s*([^\n]+)', t):
            entrada = cod + ' - ' + lim(desc)
            if not any(cod in c for c in cnaes):
                cnaes.append(entrada)
    return cnaes



def ext_email(t):
    emails = re.findall(r'[\w\.\-\+]+@[\w\-]+\.[\w\.\-]+', t)
    for e in emails:
        if not any(x in e for x in ['gov.br','receita','junta']): return e
    return emails[0] if emails else ""

def ext_telefone(t):
    """Extrai telefone — entende o layout em colunas do cartão CNPJ."""
    import re as _re
    # Cartão CNPJ: "ENDERECO ELETRONICO  TELEFONE\n  email@x.com  (21) 8868-0098"
    m = _re.search(
        r'ENDERECO\s+ELETRONICO\s+TELEFONE\s*\n\s*\S+\s+(\(?\d{2}\)?\s*[\d\s\-]{7,})',
        t, _re.I)
    if m:
        tel = m.group(1).strip()
        if len(_re.sub(r'\D','',tel)) >= 8:
            return tel
    # Campo TELEFONE explícito
    m = _re.search(r'TELEFONE\s*[:\-]?\s*(\(?\d{2}\)?\s*[\d\s\-\.]{7,})', t, _re.I)
    if m:
        tel = m.group(1).strip()
        if len(_re.sub(r'\D','',tel)) >= 8:
            return tel
    # Fallback: qualquer número com DDD
    for m in _re.findall(r'(?:\(?\d{2}\)?\s?)?(?:9\s?)?\d{4}[\s\-]?\d{4}', t):
        if len(_re.sub(r'\D','',m)) >= 8:
            return m.strip()
    return ""


def ext_nome_grupo(t, razao):
    n = first(
        r'[Nn]ome [Ff]antasia\s*[:\-]?\s*([^\n]{5,60})',
        r'[Nn]ome do [Gg]rupo\s*[:\-]?\s*([^\n]{5,60})',
        r'[Gg]rupo\s+([A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-ZÁÉÍÓÚÂÊÔÃÕÇ\s]{3,40})',
        texto=t
    )
    if n: return n
    if razao and 'grupo' in razao.lower(): return razao
    if razao:
        return re.sub(r'\b(LTDA|ME|EIRELI|EPP|S\.A\.?|MEI)\b','',razao,flags=re.I).strip().title()
    return ""

# Campos extras para o formulário comercial S&C
def ext_campo(t, *labels):
    """Extrai valor de campos no formato 'Label: Valor' do formulário."""
    for label in labels:
        m = re.search(rf'{re.escape(label)}\s*[:\-]?\s*([^\n]{{3,200}})', t, re.IGNORECASE)
        if m:
            val = lim(m.group(1))
            # Remove artefatos de OCR
            val = re.sub(r'^[:\-\s]+','', val).strip()
            if val and val not in ('—','N/A','','-'): return val
    return ""


# ── FUNÇÃO PRINCIPAL ──────────────────────────────────────────────────────────

def extrair_dados(pdf: str) -> dict:
    texto, metodo = extrair_texto(pdf)

    if not texto.strip():
        return {"erro": "Não foi possível extrair texto. Verifique se o PDF está legível."}

    # Contagem de páginas
    npages = 0
    if HAS_PLUMBER:
        try:
            with pdfplumber.open(pdf) as p: npages = len(p.pages)
        except: pass

    cnpj    = ext_cnpj(texto)
    # Nome fantasia do cartão CNPJ
    import re as _re
    _fantasia = _re.search(r'(?:TITULO|TÍTULO)\s+DO\s+ESTABELECIMENTO[^\n]*\n\s*([^\n]+?)\s+(?:MEI|ME|EPP|PORTE)\b', texto, _re.I)
    nome_fantasia = lim(_fantasia.group(1)) if _fantasia else ''
    # Email principal
    _email_cnpj = _re.search(r'ENDERECO\s+ELETRONICO\s+TELEFONE\s*\n\s*(\S+)', texto, _re.I)
    if _email_cnpj: email_cnpj = _email_cnpj.group(1).strip()
    else: email_cnpj = ''

    razao   = ext_razao(texto)
    capital = ext_capital(texto)
    socios  = ext_socios(texto)
    cnaes   = ext_cnaes(texto)
    cnaes   = ext_cnaes(texto)

    # Tenta extrair campos do formulário S&C (preenchido)
    nome_grupo      = ext_campo(texto, "Nome do Grupo")
    atividade       = ext_campo(texto, "Atividade Principal") or ext_atividade(texto)
    honorario       = ext_campo(texto, "Valor do Honorário", "Valor do Honorario") or ext_honorario(texto)
    inicio_trab     = ext_campo(texto, "Início do Trabalho", "Inicio do Trabalho")
    inicio_cob      = ext_campo(texto, "Início da Cobrança", "Inicio da Cobrança de Honorário")
    decimo          = ext_campo(texto, "Décimo Terceiro", "Decimo Terceiro")
    obs             = ext_campo(texto, "Observações", "Observacoes", "Observação")
    tipo_servico    = ext_campo(texto, "Tipo de Serviço", "Tipo de Servico", "Tipo de Servic")
    qtd_cnpj        = ext_campo(texto, "Quantidade de CNPJ", "Qtd de CNPJ")
    executivo       = ext_campo(texto, "Executivo De Vendas Responsável", "Executivo De Vendas")
    cs_resp         = ext_campo(texto, "Sucesso do Cliente Responsável", "Sucesso do Cliente")
    contador        = ext_campo(texto, "Atual Contador", "Contador")
    contato_cont    = ext_campo(texto, "Contato do Contador")
    perfil          = ext_campo(texto, "Como esse Cliente é", "Como esse Cliente e")
    expectativa     = ext_campo(texto, "Qual a Expectativa", "Expectativa")
    canal           = ext_campo(texto, "Como ele Prefere a Comunicação", "Como ele Prefere")
    dor             = ext_campo(texto, "Qual a Dor", "Dor del")
    espera          = ext_campo(texto, "O Que ele Espera da Gente")
    meta_curto      = ext_campo(texto, "Metas de Curto Prazo", "Meta de Curto Prazo")
    meta_medio      = ext_campo(texto, "Metas de Médio Prazo", "Meta de Médio Prazo")
    criterio        = ext_campo(texto, "Critérios de Sucesso", "Criterios de Sucesso")
    curva           = ext_campo(texto, "Potencial de Curva")
    prob_int        = ext_campo(texto, "Problemas Internos")
    prob_ext        = ext_campo(texto, "Problemas Externos")
    impacto         = ext_campo(texto, "Impacto Atual das Dores")
    parcelamento    = ext_campo(texto, "Possui Parcelamento")
    domestica       = ext_campo(texto, "Possui Doméstica", "Possui Domestica")
    prod_rural      = ext_campo(texto, "Possui Produtor Rural")
    softwares       = ext_campo(texto, "Ferramentas/Softwares", "Ferramentas")
    processos_int   = ext_campo(texto, "Processos Internos que se Conectam")
    email_report    = ext_campo(texto, "Email para Recebimento do Report")
    email_guias     = ext_campo(texto, "Email para Recebimento das Guias")
    pessoa_op       = ext_campo(texto, "Pessoa-chave operacional")
    pessoa_fin      = ext_campo(texto, "Pessoa-chave financeira")
    decisor         = ext_campo(texto, "Decisor final", "Decisor Final", "Camisa 10")

    # Campos de contrato social (quando não é formulário)
    if not razao:   razao   = ext_campo(texto, "Razão Social", "Razao Social")
    if not cnpj:    cnpj    = ""
    endereco   = ext_campo(texto, "Localização", "Localizacao", "Endereço", "Endereco") or ext_endereco(texto)
    data_const = ext_campo(texto, "Data Prevista de Início", "Data de Constituição") or ext_data(texto)

    regime_raw = ext_campo(texto, "Tributação", "Tributacao", "Regime")
    regime = ext_regime(regime_raw or texto)

    # Nome do grupo: prioridade ao campo explícito
    if not nome_grupo:
        nome_grupo = ext_nome_grupo(texto, razao)

    # Sócios: tenta pegar dos campos do formulário
    if not socios:
        pco = ext_campo(texto, "Pessoa-chave operacional") or ext_campo(texto, "Executivo") or ""
        pcf = ext_campo(texto, "Pessoa-chave financeira") or ""
        socios_form = [s for s in [pco, pcf] if s]
        socios = socios_form if socios_form else socios

    socio_op  = pessoa_op  or (socios[0] if socios else "")
    socio_fin = pessoa_fin or (socios[1] if len(socios)>1 else "")

    email    = email_report or ext_email(texto)
    telefone = ext_telefone(texto)

    # Normaliza curva (A/B/C)
    if curva:
        m = re.search(r'\b([ABC])\b', curva.upper())
        curva = m.group(1) if m else curva

    return {
        # Dados do grupo
        "nomeGrupo":          nome_grupo or nome_fantasia,
        "razaoSocial":        razao,
        "cnpj":               cnpj,
        "atividadePrincipal": atividade,
        "porte":              inferir_porte(texto, capital),
        "capitalSocial":      capital,
        "regime":             regime,
        "localizacao":        endereco,
        "dataConstituicao":   data_const,
        # Tributário
        "tipoServico":        tipo_servico,
        "honorario":          honorario,
        "inicioTrabalho":     inicio_trab,
        "inicioCobranca":     inicio_cob,
        "decimoTerceiro":     decimo,
        "contadorAtual":      contador,
        "contatoContador":    contato_cont,
        "executivo":          executivo,
        "csResponsavel":      cs_resp,
        "obsGerais":          obs,
        # Comercial
        "perfilCliente":      perfil,
        "expectativa":        expectativa,
        "dorCliente":         dor,
        "esperaDaGente":      espera,
        "metaCurto":          meta_curto,
        "metaMedio":          meta_medio,
        "criterioSucesso":    criterio,
        "curva":              curva,
        "probInterno":        prob_int,
        "probExterno":        prob_ext,
        # Contatos
        "email":              email,
        "emailGuias":         email_guias,
        "telefone":           telefone,
        "pessoaOperacional":  socio_op,
        "pessoaFinanceira":   socio_fin,
        "decisor":            decisor,
        "canal":              canal,
        # Operacional
        "qtdCNPJ":            qtd_cnpj,
        "parcelamento":       parcelamento,
        "domestica":          domestica,
        "produtorRural":      prod_rural,
        "softwares":          softwares,
        "processosInternos":  processos_int,
        # CNAEs
        "cnaes":              cnaes,
        # Metadados
        "todosSocios":        socios,
        "_metodo":            metodo,
        "_paginas":           npages or 1,
        "_chars":             len(texto),
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"erro": "Uso: python extrator.py arquivo.pdf"}))
        sys.exit(1)
    dados = extrair_dados(sys.argv[1])
    print(json.dumps(dados, ensure_ascii=False, indent=2))


# Adicionar limpeza de artefatos OCR ao final de extrair_dados já está implícita
# nos patterns acima — esta função pode ser chamada externamente para limpar
def limpar_artefatos(d: dict) -> dict:
    """Remove prefixos residuais de OCR dos valores."""
    prefixos = [
        r'^(?:dele?|dela|do|da|de|que)\s*[:\-]?\s*',
        r'^\s*\(Até \d+ (?:Meses?|Ano)\)\s*[:\-]?\s*',
        r'^\s*para o Cliente\s*[:\-]?\s*',
        r'^\s*\(Camisa 10\)\s*[:\-]?\s*',
        r'^\s*Responsavel?\s*[:\-]?\s*',
        r'^\s*[aà] Comunicag[aã]o\s*[:\-]?\s*',
        r'^\s*\(Considerar Filiais\)\s*[:\-]?\s*',
        r'^\s*de Parcelamento\s*[:\-]?\s*',
        r'^\s*que já? U\s*Pe?\s*$',
        r'^\s*ao Servi[çc]o Contratado\s*[:\-]?\s*$',
        r'^\s*\?\s*',
    ]
    resultado = {}
    for k, v in d.items():
        if isinstance(v, str) and v:
            for pat in prefixos:
                v = re.sub(pat, '', v, flags=re.IGNORECASE).strip()
            v = v.strip(' ,;:-')
        resultado[k] = v
    return resultado
