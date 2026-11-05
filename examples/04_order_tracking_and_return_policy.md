# Example 4: Non-Trivial Order Lookup + Return/Exchange & Warranty Policy Application

**Scenario Overview:**
- Demonstrates a multi-turn, non-trivial customer support workflow combining **Policy RAG** (`search_store_policies`) and **Real-Time Order Inspection** (`lookup_order_or_customer`).
- In **Turn 1**, the customer asks *"Me arrependi da minha compra, posso devolver meu pedido?"* without providing an order ID. The agent explains the exact **Right of Regret (7 calendar days after delivery)**, **Preference Exchange (7 days)**, and **Defect/Warranty (30 days store / 90 days legal CDC)** rules from Sections 4 & 8, and asks for the customer's Order ID or name.
- In **Turn 2**, the customer identifies two cases: **Order #8** (Ana Carolina Ferreira — `shipped`, tracking `BRJL5544332BR`) and **Order #7** (Letícia Gonçalves Rocha — `delivered` on `2026-02-17`). The agent inspects both orders in real time and applies the date-math rules accurately.

---

### Turn 1

**👤 Customer:**
> Me arrependi da minha compra, posso devolver meu pedido?

**🔧 Tool Call Executed:**
```json
{
  "tool_name": "search_store_policies",
  "arguments": {
    "query": "troca devolução direito de arrependimento defeito garantia 7 dias 30 dias 90 dias"
  }
}
```

**🎸 Empório da Música (Agent):**
> 📋 **Regras da Política de Trocas, Devoluções e Garantia da Empório da Música** *(Seções 4 e 8 do Manual — CDC Lei nº 8.078/90)*:
>
> 1. **Direito de Arrependimento — Compras Online (Seção 4.1):**
>    - **Prazo:** Até **7 (sete) dias corridos** após o **recebimento** do produto, sem necessidade de justificativa.
>    - **Condições:** O instrumento deve estar na **embalagem original, sem sinais de uso**, acompanhado de todos os acessórios e manuais.
>    - **Frete de Devolução:** **Por conta da Empório da Música** (gratuito para você).
>    - **Reembolso:** Realizado na **mesma forma de pagamento original em até 10 dias úteis**.
>
> 2. **Trocas por Preferência — Cor, Modelo ou Tamanho (Seção 4.3):**
>    - Permitidas em até **7 dias corridos**, mediante disponibilidade de estoque, com o produto em perfeito estado e na embalagem original (eventuais diferenças de valor são cobradas ou reembolsadas).
>
> 3. **Trocas por Defeito de Fabricação e Garantia (Seções 4.2 e 8):**
>    - **Até 30 dias corridos após a compra:** Troca direta realizada aqui na loja.
>    - **Após 30 dias:** Acionamento da garantia diretamente com o fabricante (a Empório da Música pode **intermediar o processo** mediante sua solicitação). Todos os produtos contam com **90 dias de Garantia Legal (CDC)** a partir do recebimento, além da **Garantia do Fabricante (de 6 meses a 2 anos)**.
>    - **Exclusões (Seções 4.4 e 8.3):** Não são elegíveis para troca/garantia instrumentos com personalização/regulagem sob encomenda (*setup* especial), itens de liquidação marcados como *'venda final'*, boquilhas de sopro (por higiene), desgaste natural (cordas, trastes, feltros) ou danos por mau uso/quedas/umidade.
>
> 👉 **Como prosseguir agora:**
> Você poderia me informar o **número do seu pedido** (ou seu **nome completo / e-mail**) e quando recebeu o instrumento? Assim eu já consulto seu pedido no sistema em tempo real e verifico o status exato para iniciar sua solicitação!

---

### Turn 2

**👤 Customer:**
> Sou a Ana Carolina Ferreira, meu pedido é o #8. Como está o rastreio dele e já posso pedir a devolução?

**🔧 Tool Calls Executed:**
```json
[
  {
    "tool_name": "lookup_order_or_customer",
    "arguments": {
      "order_id": 8,
      "customer_name": "Ana Carolina Ferreira"
    }
  },
  {
    "tool_name": "search_store_policies",
    "arguments": {
      "query": "troca devolução direito de arrependimento defeito garantia 7 dias 30 dias 90 dias"
    }
  }
]
```

**🎸 Empório da Música (Agent):**
> 📦 **Consulta de Pedido em Tempo Real no Sistema:**
>
> - **Pedido #8** — Cliente: **Ana Carolina Ferreira** (Campo Grande/MS)
>   * **Data do Pedido:** 2026-02-15 | **Status:** 🚚 Em transporte / Despachado (`shipped`)
>   * **Itens:** 1x **Kala KA-C Concert Mogno** (R$ 349.90)
>   * **Valor Total:** R$ 349.90 (`debit`)
>   * **Código de Rastreamento:** `BRJL5544332BR` | **Previsão/Data de Entrega:** 2026-02-28
>   * 📋 **Análise de Prazos (Data de referência: 2026-03-23):** O Pedido #8 está em trânsito ('shipped', rastreio: BRJL5544332BR, previsão de entrega: 2026-02-28). Assim que receber o produto, você terá 7 dias corridos para exercer o Direito de Arrependimento (frete de devolução por conta da loja e reembolso em até 10 dias úteis) ou Troca por Preferência.
>
> 📋 **Regras da Política de Trocas, Devoluções e Garantia da Empório da Música** *(Seções 4 e 8 do Manual — CDC Lei nº 8.078/90)*:
>
> 1. **Direito de Arrependimento — Compras Online (Seção 4.1):**
>    - **Prazo:** Até **7 (sete) dias corridos** após o **recebimento** do produto, sem necessidade de justificativa.
>    - **Condições:** O instrumento deve estar na **embalagem original, sem sinais de uso**, acompanhado de todos os acessórios e manuais.
>    - **Frete de Devolução:** **Por conta da Empório da Música** (gratuito para você).
>    - **Reembolso:** Realizado na **mesma forma de pagamento original em até 10 dias úteis**.

---

### Turn 3

**👤 Customer:**
> E minha irmã Letícia Gonçalves Rocha (Pedido #7), ela ainda consegue devolver por arrependimento ou acionar garantia se tiver defeito?

**🔧 Tool Calls Executed:**
```json
[
  {
    "tool_name": "lookup_order_or_customer",
    "arguments": {
      "order_id": 7,
      "customer_name": "Letícia Gonçalves Rocha"
    }
  },
  {
    "tool_name": "search_store_policies",
    "arguments": {
      "query": "troca devolução direito de arrependimento defeito garantia 7 dias 30 dias 90 dias"
    }
  }
]
```

**🎸 Empório da Música (Agent):**
> 📦 **Consulta de Pedido em Tempo Real no Sistema:**
>
> - **Pedido #7** — Cliente: **Letícia Gonçalves Rocha** (Campo Grande/MS)
>   * **Data do Pedido:** 2026-02-03 | **Status:** ✅ Entregue (`delivered`)
>   * **Itens:** 1x **Shelby SU-21S Soprano Sunburst** (R$ 159.90)
>   * **Valor Total:** R$ 159.90 (`credit_3x`)
>   * **Código de Rastreamento:** `BRKR1122334BR` | **Previsão/Data de Entrega:** 2026-02-17
>   * 📋 **Análise de Prazos (Data de referência: 2026-03-23):** Entregue em 2026-02-17 (há 34 dias) e comprado em 2026-02-03 (há 48 dias) considerando a data de referência 2026-03-23. Arrependimento / Troca por Preferência (7 dias corridos do recebimento): PRAZO EXPIRADO (>7 dias corridos após o recebimento). Troca Direta na Loja por Defeito (30 dias corridos da compra): PRAZO EXPIRADO (>30 dias da compra; acionar Garantia do Fabricante com intermediação da loja). Garantia Legal CDC (90 dias do recebimento): VIGENTE.
