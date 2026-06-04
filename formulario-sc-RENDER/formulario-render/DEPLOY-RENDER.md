# Deploy no Render — Formulário Comercial S&C
### Guia passo a passo · ~10 minutos · Gratuito

---

## O que você vai precisar

- Conta no GitHub (gratuita) → https://github.com
- Conta no Render (gratuita) → https://render.com
- Os arquivos desta pasta

---

## PASSO 1 — Criar repositório no GitHub

1. Acesse **github.com** e faça login
2. Clique em **"New repository"** (botão verde)
3. Nome: `formulario-sc`
4. Marque **"Private"** (para não ser público)
5. Clique em **"Create repository"**
6. Na página seguinte, clique em **"uploading an existing file"**
7. Arraste **todos os arquivos** desta pasta para lá
   (app.py, extrator.py, requirements.txt, render.yaml, e a pasta public/)
8. Clique em **"Commit changes"**

> **Dica:** Se preferir usar o GitHub Desktop (mais fácil):
> Baixe em https://desktop.github.com, faça login e arraste a pasta.

---

## PASSO 2 — Criar o serviço no Render

1. Acesse **render.com** → clique em **"Get Started for Free"**
2. Faça login com sua conta do **GitHub** (mais prático)
3. No dashboard, clique em **"New +"** → **"Web Service"**
4. Selecione o repositório **`formulario-sc`**
5. Preencha os campos:

   | Campo | Valor |
   |-------|-------|
   | Name | `formulario-sc` |
   | Region | `Ohio (US East)` ou o mais próximo |
   | Branch | `main` |
   | Runtime | `Python 3` |
   | Build Command | *(deixe em branco — o render.yaml cuida)* |
   | Start Command | `python app.py` |
   | Plan | **Free** |

6. Clique em **"Create Web Service"**

---

## PASSO 3 — Aguardar o build

O Render vai:
- Instalar o Python
- Instalar Tesseract OCR (para ler PDFs escaneados)
- Instalar as dependências (pdfplumber, pypdf, Pillow, pytesseract)
- Iniciar o servidor

**Tempo estimado: 3 a 8 minutos** na primeira vez.

Você acompanha o log em tempo real na tela.
Quando aparecer `FORMULARIO COMERCIAL - SOUSA & COUTO` nos logs, está pronto.

---

## PASSO 4 — Acessar e compartilhar

Após o deploy, o Render dará um link como:
```
https://formulario-sc.onrender.com
```

Compartilhe esse link com a equipe — funciona em qualquer navegador,
celular ou computador, sem instalar nada.

---

## Observações importantes

### Plano gratuito do Render
- O serviço "hiberna" após 15 minutos sem uso
- Na primeira abertura depois de inativo, demora ~30 segundos para acordar
- Para uso contínuo da equipe, isso não é problema
- Se quiser sem hibernação: plano Starter (~$7/mês)

### Atualizações
Para atualizar o sistema depois, basta fazer upload dos arquivos
atualizados no GitHub — o Render faz o redeploy automaticamente.

### Segurança
O sistema não tem login por padrão. Se quiser restringir acesso,
me avise que adiciono uma senha simples.

---

## Estrutura de arquivos para o GitHub

```
formulario-sc/           ← raiz do repositório
├── app.py               ← servidor
├── extrator.py          ← leitura de PDF
├── requirements.txt     ← dependências Python
├── render.yaml          ← configuração do Render
└── public/
    └── index.html       ← interface do formulário
```

---

Dúvidas → time de Processos S&C ou abra uma issue no GitHub.
