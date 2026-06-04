"""
extrator.py — Lê PDF de contrato social ou cartão CNPJ e extrai dados estruturados
Estratégias em ordem:
  1. pdfplumber (texto nativo)
  2. pypdf (fallback nativo)
  3. OCR via tesseract (PDFs gerados como imagem)
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

def extrair_texto_nativo(pdf):
    t = ""
    if HAS_PLUMBER:
        try:
            with pdfplumber.open(pdf) as p:
                t = "\n".join(pg.extract_text() or "" for pg in p.pages)
        except: pass
    if not t.strip() and HAS_PYPDF:
        try:
            r = PdfReader(pdf)
            t = "\n".join(pg.extract_text() or "" for pg in r.pages)
        except: pass
    return t

def extrair_texto_ocr(pdf):
    partes = []
    with tempfile.TemporaryDirectory() as tmp:
        prefix = os.path.join(tmp, "pag")
        subprocess.run(["pdftoppm", "-jpeg", "-r", "250", pdf, prefix],
                       capture_output=True, timeout=120)
        imgs = sorted(Path(tmp).glob("*.jpg"))
        if not imgs:
            subprocess.run(["pdftoppm", "-png", "-r", "250", pdf, prefix],
                           capture_output=True, timeout=120)
            imgs = sorted(Path(tmp).glob("*.png"))
        for img_path in imgs:
            try:
                # Tesseract via CLI (mais compatível)
                for lang in ["por+eng", "por", "eng"]:
                    r = subprocess.run(
                        ["tesseract", str(img_path), "stdout", "--psm", "6", "-l", lang],
                        capture_output=True, text=True, timeout=60)
                    if r.returncode == 0:
                        partes.append(r.stdout)
                        break
            except: pass
    return "\n".join(partes)

def extrair_texto(pdf):
    t = extrair_texto_nativo(pdf)
    if len(t.strip()) > 100:
        return t, "nativo"
    t = extrair_texto_ocr(pdf)
    return t, "ocr"


# ── HELPERS ───────────────────────────────────────────────────────────────────

def lim(s):
    return re.sub(r'\s+', ' ', s or "").strip()

def first(*patterns, texto="", flags=re.IGNORECASE):
    for pat in patterns:
        m = re.search(pat, texto, flags | re.DOTALL)
        if m:
            gs = [g for g in m.groups() if g]
            if gs: return lim(gs[0])
    return ""


# ── EXTRATORES ────────────────────────────────────────────────────────────────

def ext_cnpj(t):
    for m in re.findall(r'\d{2}[\.\s]?\d{3}[\.\s]?\d{3}[\s\/]?\d{4}[.\-\s]?\d{2}', t):
        d = re.sub(r'\D', '', m)
        if len(d) == 14:
            return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    return ""


def ext_razao(t):
    # Cartão CNPJ: campo NOME EMPRESARIAL (ignora linhas mascaradas com xxx)
    m = re.search(r'NOME\s+EMPRESARIAL\s*\n\s*([^\n]+)', t, re.I)
    if m and not re.match(r'^[x\s]+$', m.group(1), re.I):
        return lim(m.group(1))
    # Contrato/alteração: linha isolada com nome + LTDA/ME/etc (sem pular linhas)
    # Usa [^ \n] para evitar capturar múltiplas linhas
    for m in re.finditer(
        r'^([A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-ZÁÉÍÓÚÂÊÔÃÕÇ &\.]{5,60}(?:LTDA|ME|EIRELI|S\.A\.|EPP|MEI)\.?)\s*$',
        t, re.M):
        nome = lim(m.group(1))
        # Rejeita se tiver "Nome" (cabeçalho tabela) ou outros artefatos
        if len(nome) < 100 and 'Nome' not in nome and 'TERMO' not in nome:
            return nome
    return first(
        r'(?:denominada?|girará sob a denominação de|nome:\s*)([A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-ZÁÉÍÓÚÂÊÔÃÕÇ\s\&\.\,\-]{5,80}(?:LTDA|ME|EIRELI|S\.A\.|EPP|MEI)\.?)',
        r'(?:Raz[aã]o Social)\s*[:\-]?\s*([^\n]{5,80})',
        r'([A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-ZÁÉÍÓÚÂÊÔÃÕÇ\s\&\.]{5,60}(?:LTDA|ME|EIRELI|S\.A\.|EPP|MEI)\.?)',
        texto=t
    )


def ext_atividade(t):
    # Cartão CNPJ: linha após "ATIVIDADE ECONOMICA PRINCIPAL"
    m = re.search(r'ATIVIDADE.{1,40}PRINCIPAL\s*\n\s*([^\n]+)', t, re.I)
    if m:
        linha = m.group(1).strip()
        linha = re.sub(r'^[\d\.]+[-\s]+[\d\-]+\s*-\s*', '', linha).strip()
        if linha: return linha
    # Alteração contratual: linha após "atividades econômicas:"
    m = re.search(
        r'atividades\s+econ[oô]micas[:\s]*\n?\s*([A-ZÁÉÍÓÚÂÊÔÃÕÇ][^\n]{10,300})',
        t, re.I)
    if m:
        atv = lim(m.group(1))
        if len(atv) > 10: return atv
    # Contrato social: "tem por objeto ... Descrição"
    m = re.search(
        r'tem por objeto[^:\n]*?[:\n]\s*([^\n\.]{10,200})',
        t, re.I | re.DOTALL)
    if m:
        atv = lim(m.group(1))
        if len(atv) > 10 and 'exercício' not in atv.lower()[:20]:
            return atv
    return first(
        r'(?:Atividade Principal|ramo de atividade)\s*[:\-]?\s*([^\n]{15,200})',
        r'(?:CNAE|c[oó]digo de atividade)\s*[:\-]?\s*[\d\.]+\s*[-–]\s*([^\n]{10,120})',
        r'objeto social[^:\n]*?:\s*([^\n\.]{15,200})',
        texto=t
    )


def ext_cnaes(t):
    """Extrai CNAEs principal e secundários do cartão CNPJ."""
    cnaes = []
    # CNAE principal
    m = re.search(r'ATIVIDADE.{1,40}PRINCIPAL\s*\n\s*([^\n]+)', t, re.I)
    if m:
        linha = m.group(1).strip()
        if re.match(r'[\d]+[.\-]', linha):
            cnaes.append('Principal: ' + linha)
    # Bloco secundários
    bloco = re.search(
        r'ATIVIDADES.{1,40}SECUNDARIAS\s*\n(.*?)(?:CODIGO.{1,40}NATUREZA|LOGRADOURO\s+NUMERO|CEP\s+BAIRRO)',
        t, re.I | re.DOTALL)
    if bloco:
        for linha in bloco.group(1).split('\n'):
            linha = linha.strip()
            # Linha de CNAE: começa com número como "47.63-6-02 -"
            if re.match(r'\d{2}[\. ]\d{2}[-]\d[-]\d{2}\s*-', linha):
                cnaes.append(linha)
            elif cnaes and linha and not re.match(r'[A-Z]{4,}\s+[A-Z]', linha):
                # Continuação de linha anterior
                if not re.match(r'\d{2}[\./]', linha):
                    cnaes[-1] = cnaes[-1] + ' ' + linha
    # Fallback 1: código CNAE genérico sem espaço
    if not cnaes:
        for cod, desc in re.findall(r'(\d{2}[\. ]\d{2}[-]\d[-]\d{2})\s*[-–]\s*([^\n]+)', t):
            entrada = cod + ' - ' + lim(desc)
            if not any(cod in c for c in cnaes):
                cnaes.append(entrada)

    # Fallback 2: objeto social por extenso (alteração contratual sem código CNAE)
    if not cnaes:
        # Captura múltiplas linhas até encontrar início de nova cláusula
        m = re.search(
            r'atividades\s+econ[oô]micas[:\s]*\n?((?:(?!CL[AÁ]USULA|DO\s+INÍCIO|DO\s+CAPITAL)[^\n]+\n?){1,5})',
            t, re.I)
        if m:
            obj = lim(m.group(1))
            if len(obj) > 10:
                cnaes.append('Objeto social: ' + obj)

    return cnaes


def ext_capital(t):
    v = first(
        r'[Cc]apital\s+[Ss]ocial.*?R\$\s*([\d\.\,]+)',
        r'[Cc]apital\s+(?:subscrito|integralizado).*?R\$\s*([\d\.\,]+)',
        texto=t
    )
    return f"R$ {v}" if v else ""


def ext_socios(t):
    socios = set()
    # Padrão: "Nome Sobrenome, brasileiro(a), ..."
    for m in re.finditer(
        r'([A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+(?:\s+(?:de\s+|da\s+|do\s+)?[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+){1,4})'
        r'\s*,\s*(?:brasileir[oa])',
        t, re.I):
        nome = lim(m.group(1))
        if len(nome) > 5: socios.add(nome)
    # Padrão alternativo: "I - Nome Sobrenome, ..."
    for m in re.finditer(
        r'(?:^|\n)\s*[IVX]+\s*[-–]\s*([A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+(?:\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+){1,4})\s*,',
        t, re.M):
        nome = lim(m.group(1))
        if len(nome) > 5: socios.add(nome)
    # Tabela JUCERJA: "CPF Nome" - mas só se for sócio (não apenas requerente/contador)
    # Busca no bloco de Capital Social: somente quem tem quotas é sócio
    bloco_capital = re.search(r'(?:Capital\s+Social|Quadro\s+de\s+S[oó]cios).*?', t, re.I | re.DOTALL)
    cpf_socios = set(re.findall(r'(\d{3}\.\d{3}\.\d{3}-\d{2})', 
                                bloco_capital.group(0) if bloco_capital else t[:2000]))
    for m in re.finditer(r'(\d{3}\.\d{3}\.\d{3}-\d{2})\s+([A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-ZÁÉÍÓÚÂÊÔÃÕÇ\s]+)', t):
        cpf_candidato = m.group(1)
        nome = lim(m.group(2))
        # Só adiciona se o CPF aparece na seção do capital social
        if 8 < len(nome) < 60 and cpf_candidato in cpf_socios:
            socios.add(nome)
    # Cartão CNPJ: sócios no quadro societário
    bloco = first(r'(?:s[oó]cios?|quadro societ[aá]rio)\s*[:\-]?\s*((?:[^\n]+\n){1,15})', texto=t)
    if bloco:
        for linha in bloco.split('\n'):
            m = re.match(r'^([A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+(?:\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+){1,4})', linha.strip())
            if m: socios.add(lim(m.group(1)))
    excl = {'Ltda','Eireli','Brasil','Social','Capital','Objeto','Contrato','Nacional','Presumido','Limitada','Empresaria'}
    return [s for s in socios if len(s) > 8 and s not in excl][:8]


def ext_endereco(t):
    """
    Monta endereço completo.
    Prioridade 1: layout do cartão CNPJ da Receita Federal (campos em tabela).
    Prioridade 2: campos separados por label (LOGRADOURO:, BAIRRO:, etc).
    Prioridade 3: fallback genérico.
    """
    # ── Alteração contratual: "CLÁUSULA SEGUNDA - Rua ..., CEP: XXXXX" ──
    m_cl2 = re.search(
        r'CL[AÁ]USULA\s+SEGUNDA\s*[-–]\s*([^\n]{10,200}CEP[:\s]*[\d\.\-]+)', t, re.I)
    if m_cl2: return lim(m_cl2.group(1))

    # ── Cartão CNPJ: linha única "R VITAL BRASIL 587 LOTE 16" ──
    lograd_m = re.search(
        r'LOGRADOURO\s+NUMERO\s+COMPLEMENTO\s*\n\s*([^\n]+)', t, re.I)

    # Linha CEP: "28.621-480 CONEGO NOVA FRIBURGO RJ"
    # Grupos: (CEP, Bairro_1token, Municipio_resto, UF_2letras)
    cep_m = re.search(
        r'(\d{2}[\. -]?\d{3}[\. -]?\d{3})\s+(\S+)\s+(.+?)\s+([A-Z]{2})\s*(?:\n|$)',
        t, re.I | re.M)

    UFSVALIDAS = {
        'AC','AL','AP','AM','BA','CE','DF','ES','GO','MA','MT','MS',
        'MG','PA','PB','PR','PE','PI','RJ','RN','RS','RO','RR','SC','SP','SE','TO'
    }
    if cep_m and cep_m.group(4).upper() not in UFSVALIDAS:
        cep_m = None

    if lograd_m and cep_m:
        rua_num    = lograd_m.group(1).strip()
        cep_val    = cep_m.group(1)
        bairro_val = cep_m.group(2).strip()
        munic_val  = cep_m.group(3).strip()
        uf_val     = cep_m.group(4).strip().upper()
        return f"{rua_num} — {bairro_val} — {munic_val}/{uf_val} — CEP {cep_val}"

    # ── Campos com labels separados ──
    lograd  = re.search(r'LOGRADOURO\s*[:\-]?\s*([^\n]+)', t, re.I)
    numero  = re.search(r'N[ÚU]MERO\s*[:\-]?\s*([^\n]+)', t, re.I)
    compl   = re.search(r'COMPLEMENTO\s*[:\-]?\s*([^\n]+)', t, re.I)
    bairro  = re.search(r'BAIRRO(?:/DISTRITO)?\s*[:\-]?\s*([^\n]+)', t, re.I)
    munic   = re.search(r'MUNIC[IÍ]PIO\s*[:\-]?\s*([^\n]+)', t, re.I)
    uf      = re.search(r'\bUF\s*[:\-]?\s*([A-Z]{2})\b', t)
    cep     = re.search(r'CEP\s*[:\-]?\s*([\d\.\-]+)', t, re.I)
    if lograd:
        partes = []
        rua = lograd.group(1).strip()
        if numero and re.sub(r'\s', '', numero.group(1)) not in ('', 'S/N', 'SN', '0'):
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

    # ── Tabela JUCERJA: "CNPJ Rua X Bairro Municipio UF" ──
    m = re.search(
        r'\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\s+((?:Rua|Av\.|Avenida|Alameda)\s+[^\n]+?)\s+([A-ZÁÉÍÓÚÂÊÔÃÕÇ]+)\s+([A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-ZÁÉÍÓÚÂÊÔÃÕÇ\s]+?)\s+([A-Z]{2})\s*$',
        t, re.M | re.I)
    if m:
        _ufs = {'AC','AL','AP','AM','BA','CE','DF','ES','GO','MA','MT','MS','MG','PA','PB','PR','PE','PI','RJ','RN','RS','RO','RR','SC','SP','SE','TO'}
        if m.group(4).upper() in _ufs:
            return f'{m.group(1).strip()} — {m.group(2)} — {m.group(3).strip()}/{m.group(4).upper()}'
    # ── Contrato social: "sede na Av. X, nº N, Bairro, Cidade/UF" ──
    m = re.search(
        r'(?:sede|endereço|domicílio|situada?)\s+(?:na|em|à|no)?\s*'
        r'([A-ZÁÉÍÓÚ][^\n]{15,200}(?:nº|n\.|número|\d+)[^\n]{0,100})',
        t, re.I)
    if m: return lim(m.group(1).rstrip(','))

    # ── Fallback genérico ──
    return first(
        r'(?:Rua|Av\.|Avenida|Alameda|Travessa|Rod\.|Rodovia|Praça)\s+[^\n]{10,120}',
        r'Localiza[çc][aã]o\s*[:\-]?\s*([^\n]{10,150})',
        texto=t
    )


def ext_data(t):
    """Extrai data de abertura — cartão CNPJ e contratos sociais."""
    # Cartão CNPJ formato 1: "CADASTRAL 24/08/2018"
    m = re.search(r'CADASTRAL\s+(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{4})', t, re.I)
    if m: return m.group(1).strip()
    # Cartão CNPJ formato 2: CNPJ e data na mesma linha
    m = re.search(r'\d{2}[\. ]\d{3}[\. ]\d{3}\/\d{4}[.\-]\d{2}\s+\S+.*?(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{4})', t, re.I)
    if m: return m.group(1).strip()
    # Campo explícito
    m = re.search(r'DATA\s+DE\s+ABERTURA[^\d]*(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{4})', t, re.I | re.DOTALL)
    if m: return m.group(1).strip()
    # Linha "ABERTURA\n24/08/2018" separada
    m = re.search(r'ABERTURA\s*\n\s*(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{4})', t, re.I)
    if m: return m.group(1).strip()
    # Contrato: "atividades a partir de 15/08/2018"
    m = re.search(r'atividades\s+a\s+partir\s+de\s+(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{4})', t, re.I)
    if m: return m.group(1).strip()
    return first(
        r'(?:constitu[iíi]da?|fundada?|celebrado?)\s+(?:em|no dia)?\s*(\d{1,2}[\s\/\-\.]+(?:de\s+)?(?:janeiro|fevereiro|março|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro|\d{1,2})[\s\/\-\.]+(?:de\s+)?\d{4})',
        r'[Dd]ata\s+(?:de\s+)?(?:abertura|constitu[iíi][çc][aã]o)\s*[:\-]?\s*(\d{1,2}[\s\/\-\.]\d{1,2}[\s\/\-\.]\d{4})',
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
    # Cartão CNPJ: busca PORTE seguido de valor (mesma linha ou próxima)
    m = re.search(r'\bPORTE\b[^\n]{0,30}\b(MEI|ME|EPP)\b', t, re.I)
    if m: return m.group(1).upper()
    # OCR pode separar em linhas: "PORTE\nME"
    m = re.search(r'\bPORTE\b\s*\n\s*(MEI|ME|EPP)\b', t, re.I)
    if m: return m.group(1).upper()
    # Linha do título: "THEMARE   ME\n"
    m = re.search(r'(?:TITULO|TÍTULO).{1,100}?\n[^\n]+?\s+(MEI|ME|EPP)\s*\n', t, re.I | re.DOTALL)
    if m: return m.group(1).upper()
    # Cartão: "Porte ME" na linha de informações gerais
    m = re.search(r'\bPorte\b[^\n]*\b(MEI|ME|EPP)\b', t)
    if m: return m.group(1).upper()

    tl = t.lower()
    # Contrato/junta: "Microempresa" ou "Empresa de Pequeno Porte" explícito
    m = re.search(r'\bMicroempresa\b', t)
    if m: return 'ME'
    m = re.search(r'Empresa\s+de\s+Pequeno\s+Porte', t, re.I)
    if m: return 'EPP'
    if 'microempreendedor individual' in tl: return 'MEI'
    if cap:
        # "R$ 96.000,00" → remove separador de milhar (.), converte vírgula em decimal
        _c = re.sub(r'R\$\s*', '', cap).strip()
        _c = _c.replace('.', '').replace(',', '.')
        try:
            v = float(re.sub(r'[^\d\.]', '', _c))
            if   v <= 81_000:    return 'MEI'
            elif v <= 360_000:   return 'ME'
            elif v <= 4_800_000: return 'EPP'
            else:                return 'Médio Porte'
        except: pass
    if 'microempresa' in tl: return 'ME'
    if 'empresa de pequeno porte' in tl: return 'EPP'
    if 'eireli' in tl: return 'ME'
    return ''


def ext_email(t):
    # Cartão CNPJ: linha após "ENDERECO ELETRONICO TELEFONE"
    m = re.search(r'ENDERECO\s+ELETRONICO\s+TELEFONE\s*\n\s*(\S+@\S+)', t, re.I)
    if m: return lim(m.group(1))
    # Campo explícito de e-mail da empresa (não do requerente)
    # E-mail explícito do cartão CNPJ (após "ENDERECO ELETRONICO")
    # Não busca campo "E-mail:" pois pode ser do requerente (henriquelima etc)
    pass  # já feito acima com ENDERECO ELETRONICO
    # Busca todos os emails e filtra por prioridade
    emails = re.findall(r'[\w\.\-\+]+@[\w\-]+\.[\w\.\-]+', t)
    # 1ª prioridade: domínio corporativo próprio (não gmail/outlook/yahoo/hotmail)
    pessoais = {'hotmail', 'outlook', 'live'}  # apenas serviços sem domínio próprio
    for e in emails:
        if not any(x in e.lower() for x in ['gov.br', 'receita', 'junta']):
            dom = e.split('@')[-1].split('.')[0].lower()
            if dom not in pessoais:
                return e
    # Nenhum email corporativo encontrado — retorna vazio (melhor que email errado)
    return ""


def ext_telefone(t):
    """Extrai telefone — prioriza campo explícito do cartão CNPJ."""
    # Cartão CNPJ: "email@x.com  (21) 8868-0098" na mesma linha
    m = re.search(
        r'ENDERECO\s+ELETRONICO\s+TELEFONE\s*\n\s*\S+\s+(\(?\d{2}\)?\s*[\d\s\-]{7,})',
        t, re.I)
    if m:
        tel = m.group(1).strip()
        if len(re.sub(r'\D', '', tel)) >= 8:
            return tel
    # Campo TELEFONE explícito
    m = re.search(r'TELEFONE\s*[:\-]?\s*(\(?\d{2}\)?\s*[\d\s\-\.]{7,})', t, re.I)
    if m:
        tel = m.group(1).strip()
        if len(re.sub(r'\D', '', tel)) >= 8:
            return tel
    # Fallback: padrão brasileiro (XX) XXXXX-XXXX ou (XX) XXXX-XXXX
    for m in re.findall(r'\(\d{2}\)\s*\d{4,5}[\s\-]?\d{4}', t):
        d = re.sub(r'\D', '', m)
        if 10 <= len(d) <= 11:
            return m.strip()
    return ""


def ext_nome_grupo(t, razao):
    # Cartão CNPJ: TITULO DO ESTABELECIMENTO (nome de fantasia)
    m = re.search(
        r'(?:TITULO|TÍTULO)\s+DO\s+ESTABELECIMENTO[^\n]*\n\s*([^\n]+?)\s+(?:MEI|ME|EPP|PORTE)\b',
        t, re.I)
    if m: return lim(m.group(1))
    n = first(
        r'[Nn]ome [Ff]antasia\s*[:\-]?\s*([^\n]{5,60})',
        r'[Nn]ome do [Gg]rupo\s*[:\-]?\s*([^\n]{5,60})',
        texto=t
    )
    if n: return n
    if razao and 'grupo' in razao.lower(): return razao
    if razao:
        return re.sub(r'\b(LTDA|ME|EIRELI|EPP|S\.A\.?|MEI)\b', '', razao, flags=re.I).strip().title()
    return ""


def ext_campo(t, *labels):
    """Extrai valor de campos no formato 'Label: Valor' do formulário S&C."""
    for label in labels:
        m = re.search(rf'{re.escape(label)}\s*[:\-]?\s*([^\n]{{3,200}})', t, re.IGNORECASE)
        if m:
            val = lim(m.group(1)).strip(' ,;:-')
            if val and val not in ('—', 'N/A', '', '-'):
                return val
    return ""


# ── FUNÇÃO PRINCIPAL ──────────────────────────────────────────────────────────

def extrair_dados(pdf):
    texto, metodo = extrair_texto(pdf)

    if not texto.strip():
        return {"erro": "Não foi possível extrair texto do PDF."}

    cnpj    = ext_cnpj(texto)
    razao   = ext_razao(texto)
    capital = ext_capital(texto)
    socios  = ext_socios(texto)
    cnaes   = ext_cnaes(texto)

    atividade = ext_campo(texto, "Atividade Principal") or ext_atividade(texto)
    honorario = ext_campo(texto, "Valor do Honorário", "Valor do Honorario") or ""
    inicio_trab = ext_campo(texto, "Início do Trabalho", "Inicio do Trabalho")
    inicio_cob  = ext_campo(texto, "Início da Cobrança", "Inicio da Cobranca")
    decimo      = ext_campo(texto, "Décimo Terceiro", "Decimo Terceiro")
    obs         = ext_campo(texto, "Observações", "Observacoes")
    tipo_servico = ext_campo(texto, "Tipo de Serviço", "Tipo de Servico")
    qtd_cnpj    = ext_campo(texto, "Quantidade de CNPJ", "Qtd de CNPJ")
    executivo   = ext_campo(texto, "Executivo De Vendas Responsável", "Executivo De Vendas")
    cs_resp     = ext_campo(texto, "Sucesso do Cliente Responsável", "Sucesso do Cliente")
    contador    = ext_campo(texto, "Atual Contador", "Contador")
    contato_cont = ext_campo(texto, "Contato do Contador")
    perfil      = ext_campo(texto, "Como esse Cliente é", "Como esse Cliente e")
    expectativa = ext_campo(texto, "Qual a Expectativa", "Expectativa")
    canal       = ext_campo(texto, "Como ele Prefere a Comunicação", "Como ele Prefere")
    dor         = ext_campo(texto, "Qual a Dor", "Dor del")
    espera      = ext_campo(texto, "O Que ele Espera da Gente")
    meta_curto  = ext_campo(texto, "Metas de Curto Prazo", "Meta de Curto Prazo")
    meta_medio  = ext_campo(texto, "Metas de Médio Prazo", "Meta de Médio Prazo")
    criterio    = ext_campo(texto, "Critérios de Sucesso", "Criterios de Sucesso")
    curva       = ext_campo(texto, "Potencial de Curva")
    prob_int    = ext_campo(texto, "Problemas Internos")
    prob_ext    = ext_campo(texto, "Problemas Externos")
    parcelamento = ext_campo(texto, "Possui Parcelamento")
    domestica   = ext_campo(texto, "Possui Doméstica", "Possui Domestica")
    prod_rural  = ext_campo(texto, "Possui Produtor Rural")
    softwares   = ext_campo(texto, "Ferramentas/Softwares", "Ferramentas")
    processos_int = ext_campo(texto, "Processos Internos que se Conectam")
    email_report = ext_campo(texto, "Email para Recebimento do Report")
    pessoa_op   = ext_campo(texto, "Pessoa-chave operacional")
    pessoa_fin  = ext_campo(texto, "Pessoa-chave financeira")
    decisor     = ext_campo(texto, "Decisor final", "Camisa 10")

    endereco   = ext_campo(texto, "Localização", "Localizacao") or ext_endereco(texto)
    data_const = ext_campo(texto, "Data Prevista de Início", "Data de Constituição") or ext_data(texto)
    regime_raw = ext_campo(texto, "Tributação", "Tributacao", "Regime")
    regime = ext_regime(regime_raw or texto)

    nome_grupo = ext_nome_grupo(texto, razao)
    email      = email_report or ext_email(texto)
    telefone   = ext_telefone(texto)

    if curva:
        m = re.search(r'\b([ABC])\b', curva.upper())
        curva = m.group(1) if m else curva

    socio_op  = pessoa_op  or (socios[0] if socios else "")
    socio_fin = pessoa_fin or (socios[1] if len(socios) > 1 else "")

    npages = 0
    if HAS_PLUMBER:
        try:
            with pdfplumber.open(pdf) as p: npages = len(p.pages)
        except: pass

    return {
        "nomeGrupo":          nome_grupo,
        "razaoSocial":        razao,
        "cnpj":               cnpj,
        "atividadePrincipal": atividade,
        "porte":              inferir_porte(texto, capital),
        "capitalSocial":      capital,
        "regime":             regime,
        "localizacao":        endereco,
        "dataConstituicao":   data_const,
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
        "email":              email,
        "emailGuias":         "",
        "telefone":           telefone,
        "pessoaOperacional":  socio_op,
        "pessoaFinanceira":   socio_fin,
        "decisor":            decisor,
        "canal":              canal,
        "qtdCNPJ":            qtd_cnpj,
        "parcelamento":       parcelamento,
        "domestica":          domestica,
        "produtorRural":      prod_rural,
        "softwares":          softwares,
        "processosInternos":  processos_int,
        "cnaes":              cnaes,
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
