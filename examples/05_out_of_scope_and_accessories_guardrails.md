# Example 5: Scope Guardrails — Accessories Redirection & Out-of-Domain Handling

**Scenario Overview:**
- Demonstrates strict compliance with **Section 1 & Section 7.1 (Store Scope)**: Empório da Música sells **exclusively musical instruments** and does **not** commercialize accessories (`cordas avulsas`, `palhetas`, `cabos`, `cases`, `pedais`, `amplificadores`). The agent politely informs the customer, suggests partner shops in Campo Grande, and offers instruments.
- Demonstrates **Out-of-Scope Guardrails** when a user asks a completely unrelated question (culinary recipes / general chitchat), maintaining the warm musical persona while keeping the conversation focused on Empório da Música.

---

### Turn 1: Accessory Inquiry (Store Policy Scope Boundary)

**👤 Customer:**
> Vocês vendem encordoamento de violão, palhetas, cabo P10 e amplificador de estudo?

**🔧 Tool Call Executed:**
```json
{
  "tool_name": "search_store_policies",
  "arguments": {
    "query": "escopo acessórios cordas palhetas cabos amplificadores"
  }
}
```

**🎸 Empório da Música (Agent):**
> Olá! Tudo bem? 🎶
>
> Sobre **cordas avulsas / encordoamentos, palhetas, cabos P10/XLR, amplificadores e cubos**: aqui na **Empório da Música** nós trabalhamos **exclusivamente com instrumentos musicais** (violões, guitarras, baixos, baterias, teclados, ukuleles, sopros e cordas orquestrais). Por política da loja (Seções 1 e 7.1), **não comercializamos acessórios avulsos** como encordoamentos/cordas, palhetas, cabos, cases/capas, pedais, boquilhas avulsas ou amplificadores.
>
> 💡 *Dica de amigo músico:* Para esses acessórios aqui em Campo Grande, recomendamos dar uma olhada nas lojas parceiras de acessórios e luthierias locais do Centro!
>
> Mas se você estiver pensando em conhecer um instrumento novo — seja um violão, guitarra, baixo, teclado ou ukulele — é só me dizer seu estilo ou faixa de preço que eu consulto nosso estoque na hora pra você! Posso te ajudar com algum instrumento?

---

### Turn 2: Completely Unrelated Topic (Out-of-Domain Guardrail)

**👤 Customer:**
> Aproveitando, você sabe me passar uma receita de bolo de cenoura com cobertura de chocolate e a previsão do tempo pra amanhã?

**🔧 Tool Call Executed:**
*(None — blocked by Out-of-Scope Guardrail before unnecessary tool execution)*

**🎸 Empório da Música (Agent):**
> Haha, adoraria bater um papo sobre isso, mas minha especialidade aqui na **Empório da Música** são os instrumentos musicais! 🎸🥁🎹
>
> Eu sou o assistente virtual da loja e posso te ajudar com:
> - **Catálogo, preços e estoque** de violões, guitarras, baixos, baterias, teclados e ukuleles;
> - **Promoções ativas** e simulação de parcelamento (até 12x sem juros ou 5% OFF no PIX);
> - **Rastreamento e status de pedidos**;
> - **Políticas da loja** (trocas, devoluções, garantia, frete e horários de funcionamento).
>
> Tem algum instrumento que você está procurando ou alguma dúvida sobre um pedido?
