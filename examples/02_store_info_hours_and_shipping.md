# Example 2: General Store Information, Opening Hours, Shipping & LGPD Policy

**Scenario Overview:**
- Demonstrates Hybrid RAG retrieval (`search_store_policies`) over `data/políticas_da_loja.pdf`.
- Accurately answers store address (`Rua 14 de Maio, 3200 — Centro, Campo Grande/MS`), contact numbers (landline `(67) 3341-4444` and remote WhatsApp `(67) 3321-4500`), business hours (Mon–Fri 09:00–18:00, Sat 09:00–13:00, Sun/Holidays Closed), and shipping policies for both Campo Grande and interior cities (`PAC`, `SEDEX`, `Jadlog`).

---

### Turn 1

**👤 Customer:**
> Qual o endereço da loja e qual o horário de funcionamento durante a semana e no sábado?

**🔧 Tool Call Executed:**
```json
{
  "tool_name": "search_store_policies",
  "arguments": {
    "query": "endereço telefone whatsapp email cnpj sobre a loja horário de funcionamento segunda sexta sábado domingo feriados"
  }
}
```

**🎸 Empório da Música (Agent):**
> Olá! Tudo bem? 🎶
>
> 📍 **Endereço e Contatos da Empório da Música** *(Seção 1.2 e Seção 7 do Manual)*:
> - **Endereço Físico:** Rua 14 de Maio, 3200 — Centro, Campo Grande – MS, CEP 79202-333
> - **Telefone Fixo / Geral:** (67) 3341-4444
> - **WhatsApp de Atendimento Remoto:** (67) 3321-4500
> - **E-mail:** contato@emporiodamusica.com.br
> - **Razão Social / CNPJ:** Empório da Música Instrumentos Musicais Ltda. (CNPJ: 12.345.678/0001-90)
> - **Sobre nós:** Fundada em 2008 em Campo Grande/MS, somos especializados exclusivamente em instrumentos musicais (+300 modelos nacionais e importados).
>
> 🕒 **Horário de Funcionamento** *(Seção 2 — Loja Física e WhatsApp)*:
> - **Segunda a Sexta-feira:** das **09:00 às 18:00**
> - **Sábado:** das **09:00 às 13:00**
> - **Domingos e Feriados:** **Fechado** *(com atendimento automático fora do expediente)*
> - *Nota:* Em datas especiais (Black Friday, Aniversário da Loja em Agosto e Natal), o horário pode ser estendido mediante aviso prévio nas redes sociais e WhatsApp.
>
> Ficou com alguma dúvida ou quer que eu simule o parcelamento/frete de algum modelo específico? Estou à disposição!

---

### Turn 2

**👤 Customer:**
> E como funciona o frete para Campo Grande e para Dourados? Meus dados ficam seguros pela LGPD?

**🔧 Tool Call Executed:**
```json
{
  "tool_name": "search_store_policies",
  "arguments": {
    "query": "política de frete entregas campo grande outras cidades pac sedex jadlog privacidade proteção de dados lgpd exclusão"
  }
}
```

**🎸 Empório da Música (Agent):**
> Olá! Tudo bem? 🎶
>
> 🚚 **Política de Frete e Entregas** *(Seção 5)*:
> 1. **Região Metropolitana de Campo Grande/MS:**
>    - **Frete Grátis** para pedidos acima de **R$ 500,00**!
>    - Pedidos abaixo de R$ 500,00: **taxa fixa de R$ 35,00**.
>    - **Prazo e Entrega:** **1 a 3 dias úteis** via **motoboy próprio** (entramos em contato por telefone antes da entrega).
> 2. **Outras Cidades (Interior de MS e demais Estados):**
>    - **SEDEX (Correios):** 2 a 5 dias úteis *(com rastreamento e seguro incluído)*
>    - **Jadlog (.package):** 3 a 8 dias úteis *(com rastreamento e seguro incluído)*
>    - **PAC (Correios):** 5 a 12 dias úteis *(com rastreamento e seguro incluído)*
>    - *Observação:* Instrumentos de grande porte (baterias acústicas, pianos digitais, contrabaixos) podem exigir cotação individual. Em caso de avaria no transporte, recuse o recebimento no ato e nos avise imediatamente!
>
> 🔒 **Privacidade e Proteção de Dados — LGPD (Lei nº 13.709/2018)** *(Seção 9)*:
> - Seus dados (nome, telefone, e-mail, endereço) são usados exclusivamente para processamento/entrega de pedidos, avisos de status/rastreio, envio de promoções (apenas mediante seu consentimento explícito) e obrigações fiscais.
> - **Jamais compartilhamos seus dados com terceiros** para fins de marketing, e você pode solicitar a exclusão a qualquer momento pelo nosso WhatsApp ou e-mail.
>
> Ficou com alguma dúvida ou quer que eu simule o parcelamento/frete de algum modelo específico? Estou à disposição!
