# Example 3: Price Inquiry, Active vs. Expired Promotions & Non-Cumulative PIX Rule

**Scenario Overview:**
- Demonstrates consulting exact pricing for **Takamine GD20** (`product_id=95`) via `search_products` and `calculate_payment_and_shipping`, noting that its historical 12% promotion (`promotion_id=4`) is expired (`is_active=0`), while applying the 5% PIX discount (`R$ 2,089.05`), up to 12x interest-free installments (`12x de R$ 183.25`), and Combined Payment eligibility (`> R$ 2,000.00`).
- Demonstrates querying active promotions (`get_promotions`) and enforcing **Section 6.2 (Non-Cumulativity)**: showing why the 5% PIX discount does **not** stack on top of **Crafter HT-100 Folk Aço Natural** (`18% OFF`, from `R$ 2,399.00` to `R$ 1,967.18`).

---

### Turn 1

**👤 Customer:**
> Quanto custa o Takamine GD20?

**🔧 Tool Calls Executed:**
```json
[
  {
    "tool_name": "search_products",
    "arguments": {
      "query": "takamine gd20",
      "only_in_stock": false
    }
  },
  {
    "tool_name": "calculate_payment_and_shipping",
    "arguments": {
      "amount_brl": 2199.0,
      "city": "Campo Grande",
      "is_promotional_price": false
    }
  }
]
```

**🎸 Empório da Música (Agent):**
> Olá! Tudo bem? 🎶
>
> 🎸 **Takamine GD20 Dreadnought Natural** *(Código #95 — Categoria: Violões)*
> - **Descrição:** Violão dreadnought Takamine com tampo sólido em cedro. Excelente para fingerstyle com timbre quente e definido.
> - ✅ **Disponibilidade:** **Em estoque!** (5 unidades disponíveis para pronta entrega)
> - 💰 **Preço de Tabela:** **R$ 2,199.00**
> - ⚡ **Preço no PIX (5% de desconto à vista):** **R$ 2,089.05** *(economia de R$ 109.95!)*
>   * *(Nota de transparência: este modelo já participou da campanha 'Oferta Especial (12% OFF - EXPIRED)', que encontra-se encerrada no momento).*
> - 💳 **Parcelamento no Cartão:** **Até 12x de R$ 183.25 sem juros no Cartão de Crédito** (ou à vista no Débito / Boleto por R$ 2,199.00).
> - 🤝 **Pagamento Combinado:** Como o valor supera R$ 2.000,00, você pode combinar formas de pagamento (ex.: dar uma entrada no PIX e parcelar o restante no cartão — Seção 3.1)!
> - 🚚 **Frete (Campo Grande e Região):** **FRETE GRÁTIS** (compras acima de R$ 500,00), entregue por motoboy próprio em **1 a 3 dias úteis**! Para outras cidades, enviamos via SEDEX (2–5 dias úteis), Jadlog (3–8 dias úteis) ou PAC (5–12 dias úteis) com seguro incluso.
> - 🔧 **Especificações Técnicas:** `top: Cedro Sólido, back_sides: Sapele, neck: Mogno, strings: steel, scale: 650mm, electronics: no, color: Natural`
>
> Ficou com alguma dúvida ou quer que eu simule o parcelamento/frete de algum modelo específico? Estou à disposição!

---

### Turn 2

**👤 Customer:**
> E quais instrumentos estão em promoção ativa hoje? Se eu pagar um item promocional no PIX, ganho mais 5% de desconto?

**🔧 Tool Call Executed:**
```json
{
  "tool_name": "get_promotions",
  "arguments": {
    "include_expired": false
  }
}
```

**🎸 Empório da Música (Agent):**
> Olá! Tudo bem? 🎶
>
> 🏷️ **Promoções Ativas no Sistema Agora** *(Consultado em tempo real — Seção 6)*:
> - **Ohana CK-20 Concert Natural** (Ukuleles) — Campanha *Desconto Exclusivo*:
>   * De ~~R$ 549.00~~ por **R$ 439.20** (**20% de desconto**)
>   * Estoque atual: **6 unidades**
> - **Crafter HT-100 Folk Aço Natural** (Violões) — Campanha *Desconto Exclusivo*:
>   * De ~~R$ 2,399.00~~ por **R$ 1,967.18** (**18% de desconto**)
>   * Estoque atual: **3 unidades**
> - **Kalani KAL-700T Tenor Natural** (Ukuleles) — Campanha *Oferta Especial*:
>   * De ~~R$ 359.00~~ por **R$ 323.10** (**10% de desconto**)
>   * Estoque atual: **11 unidades**
> - **Taylor 110e Dreadnought Natural** (Violões) — Campanha *Desconto Exclusivo*:
>   * De ~~R$ 5,999.00~~ por **R$ 5,519.08** (**8% de desconto**)
>   * Estoque atual: **4 unidades**
>
> 📌 **Regras Importantes de Promoção (Seção 6.2):**
> - **Não-cumulatividade:** Promoções não são cumulativas — o desconto de 5% do PIX **não** se aplica sobre preços que já estão em promoção.
> - **Estoque:** Sujeitas à disponibilidade em estoque (sem reserva de preço / *rain check*).
>
> Ficou com alguma dúvida ou quer que eu simule o parcelamento/frete de algum modelo específico? Estou à disposição!
