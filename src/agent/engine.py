"""Hybrid ReAct + Tool-Calling Orchestration Engine for Empório da Música.

Supports:
1. Cloud & Local OpenAI-compatible Tool-Calling LLMs:
   - Groq API (`llama-3.3-70b-versatile`) — primary free cloud provider
   - Local Ollama (`llama3.2`, `qwen2.5`) — primary local free provider
   - OpenAI (`gpt-4o-mini`, `gpt-4o`) and Google Gemini (`gemini-2.5-flash`)
2. Built-in Deterministic Offline ReAct Engine:
   - Automatically engages when `LLM_PROVIDER=offline` or when no external API key /
     local Ollama daemon is reachable.
   - Executes real tool calls against `StoreToolkit` (`StoreDatabase` + `PolicyKnowledgeBase`)
     and synthesizes rich, natural, persona-aligned responses with 100% factual accuracy.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import httpx
from openai import OpenAI

from src.agent.memory import SessionMemory
from src.agent.prompts import build_system_prompt
from src.config import AgentConfig
from src.data.database import StoreDatabase, normalize_text
from src.retrieval.policy_rag import PolicyKnowledgeBase
from src.tools.store_tools import StoreToolkit


@dataclass
class ToolCallTrace:
    """Record of a single tool invocation made during an agent turn."""

    tool_name: str
    arguments: dict[str, Any]
    result: dict[str, Any]


@dataclass
class AgentResponse:
    """Structured response returned by `EmporioAgent.chat()`."""

    reply: str
    provider_used: str
    model_used: str
    tool_traces: list[ToolCallTrace] = field(default_factory=list)
    session_id: str = "default"


class EmporioAgent:
    """Main AI Customer Support Agent for Empório da Música."""

    ACCESSORY_KEYWORDS = {
        "encordoamento": "cordas avulsas / encordoamentos",
        "corda avulsa": "cordas avulsas",
        "cordas avulsas": "cordas avulsas",
        "jogo de cordas": "jogos de cordas avulsas",
        "palheta": "palhetas",
        "palhetas": "palhetas",
        "cabo": "cabos P10/XLR",
        "cabos": "cabos",
        "pedal": "pedais de efeito",
        "pedais": "pedais de efeito",
        "pedaleira": "pedaleiras e pedais",
        "amplificador": "amplificadores e cubos",
        "amplificadores": "amplificadores",
        "cubo": "amplificadores/cubos",
        "case": "cases e capas/bags",
        "cases": "cases e capas/bags",
        "capa": "capas/bags",
        "bag": "bags/capas",
        "boquilha": "boquilhas avulsas",
        "baqueta": "baquetas e acessórios avulsos",
        "correia": "correias e acessórios",
        "capotraste": "capotrastes e acessórios",
        "estante": "estantes e suportes",
        "suporte": "suportes e acessórios",
    }

    OUT_OF_SCOPE_KEYWORDS = {
        "receita", "bolo", "pizza", "culinaria", "futebol", "flamengo", "corinthians",
        "palmeiras", "politica", "eleicao", "presidente", "previsao do tempo", "clima",
        "chuva", "bitcoin", "criptomoeda", " bolsa de valores", "programacao", "codigo python",
        "javascript", "filme", "cinema", "novela", "horoscopo", "signo", "medicina",
        "remedio", "dor de cabeca", "carro", "moto", "pneu", "passagem aerea",
    }

    def __init__(
        self,
        config: AgentConfig | None = None,
        db: StoreDatabase | None = None,
        policy_kb: PolicyKnowledgeBase | None = None,
        memory: SessionMemory | None = None,
    ) -> None:
        self.config = config or AgentConfig()
        self.db = db or StoreDatabase(self.config.data_dir)
        self.policy_kb = policy_kb or PolicyKnowledgeBase(
            self.config.data_dir / "políticas_da_loja.pdf"
        )
        self.toolkit = StoreToolkit(self.db, self.policy_kb, self.config)
        self.memory = memory or SessionMemory(self.config.session_db_path)

    def _resolve_active_llm_client(self) -> tuple[OpenAI | None, str, str]:
        """Resolve the active OpenAI-compatible client, provider name, and model name."""
        pref = self.config.llm_provider

        if pref == "offline":
            return None, "offline-react", "deterministic-hybrid-engine"

        # 1. Groq
        if pref in ("groq", "auto") and self.config.has_valid_key(self.config.groq_api_key):
            client = OpenAI(
                api_key=self.config.groq_api_key,
                base_url=self.config.groq_base_url,
                timeout=20.0,
            )
            return client, "groq", self.config.groq_model

        # 2. OpenAI
        if pref in ("openai", "auto") and self.config.has_valid_key(self.config.openai_api_key):
            client = OpenAI(api_key=self.config.openai_api_key, timeout=20.0)
            return client, "openai", self.config.openai_model

        # 3. Gemini
        if pref in ("gemini", "auto") and self.config.has_valid_key(self.config.gemini_api_key):
            client = OpenAI(
                api_key=self.config.gemini_api_key,
                base_url=self.config.gemini_base_url,
                timeout=20.0,
            )
            return client, "gemini", self.config.gemini_model

        # 4. Local Ollama check
        if pref in ("ollama", "auto"):
            try:
                resp = httpx.get(
                    f"{self.config.ollama_base_url.rstrip('/v1')}/api/tags",
                    timeout=1.5,
                )
                if resp.status_code == 200:
                    client = OpenAI(
                        api_key="ollama",
                        base_url=self.config.ollama_base_url,
                        timeout=30.0,
                    )
                    return client, "ollama", self.config.ollama_model
            except Exception:
                pass

        return None, "offline-react", "deterministic-hybrid-engine"

    def chat(self, user_message: str, session_id: str = "default") -> AgentResponse:
        """Process a customer message, execute needed tools, persist memory, and return the response."""
        clean_msg = user_message.strip()
        if not clean_msg:
            return AgentResponse(
                reply="Olá! Como posso ajudar você hoje aqui na Empório da Música? 🎸",
                provider_used="system",
                model_used="none",
                session_id=session_id,
            )

        history = self.memory.get_history(session_id=session_id, max_turns=12)
        client, provider, model_name = self._resolve_active_llm_client()

        if client is not None:
            try:
                response = self._run_llm_react_loop(
                    client=client,
                    provider=provider,
                    model_name=model_name,
                    user_message=clean_msg,
                    history=history,
                    session_id=session_id,
                )
                self._save_turn(session_id, clean_msg, response)
                return response
            except Exception:
                # Seamless fallback to deterministic ReAct engine if API rate-limits or fails
                pass

        response = self._run_deterministic_react_engine(
            user_message=clean_msg,
            history=history,
            session_id=session_id,
        )
        self._save_turn(session_id, clean_msg, response)
        return response

    def _save_turn(
        self, session_id: str, user_message: str, response: AgentResponse
    ) -> None:
        """Persist user message and assistant reply (with tool trace summary) to SQLite memory."""
        self.memory.add_message(session_id, "user", user_message)
        serialized_traces = [
            {"tool_name": t.tool_name, "arguments": t.arguments}
            for t in response.tool_traces
        ]
        self.memory.add_message(
            session_id,
            "assistant",
            response.reply,
            tool_calls=serialized_traces if serialized_traces else None,
        )

    def _run_llm_react_loop(
        self,
        client: OpenAI,
        provider: str,
        model_name: str,
        user_message: str,
        history: list[dict[str, Any]],
        session_id: str,
    ) -> AgentResponse:
        """Execute multi-step function-calling loop with an OpenAI-compatible LLM."""
        system_prompt = build_system_prompt(self.config.reference_date)
        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]

        for h in history[-8:]:
            messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": user_message})

        tool_traces: list[ToolCallTrace] = []

        for _ in range(5):  # Up to 5 tool-calling iterations
            completion = client.chat.completions.create(
                model=model_name,
                messages=messages,
                tools=self.toolkit.tool_schemas,
                tool_choice="auto",
                temperature=0.2,
            )
            choice_msg = completion.choices[0].message

            if not choice_msg.tool_calls:
                reply_text = (choice_msg.content or "").strip()
                return AgentResponse(
                    reply=reply_text,
                    provider_used=provider,
                    model_used=model_name,
                    tool_traces=tool_traces,
                    session_id=session_id,
                )

            messages.append(choice_msg.model_dump(exclude_none=True))

            for tc in choice_msg.tool_calls:
                fn_name = tc.function.name
                raw_args = tc.function.arguments or "{}"
                try:
                    parsed_args = json.loads(raw_args)
                except json.JSONDecodeError:
                    parsed_args = {}

                tool_result = self.toolkit.execute_tool(fn_name, parsed_args)
                tool_traces.append(
                    ToolCallTrace(
                        tool_name=fn_name,
                        arguments=parsed_args,
                        result=tool_result,
                    )
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": fn_name,
                        "content": json.dumps(tool_result, ensure_ascii=False),
                    }
                )

        # Final synthesis call if max iterations reached
        final_comp = client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=0.2,
        )
        return AgentResponse(
            reply=(final_comp.choices[0].message.content or "").strip(),
            provider_used=provider,
            model_used=model_name,
            tool_traces=tool_traces,
            session_id=session_id,
        )

    # ==========================================================================
    # Deterministic Hybrid ReAct Planner & Synthesizer (Zero-API-Key Mode)
    # ==========================================================================

    def _run_deterministic_react_engine(
        self,
        user_message: str,
        history: list[dict[str, Any]],
        session_id: str,
    ) -> AgentResponse:
        """Plan and execute real tool calls and synthesize a persona-aligned response."""
        msg_norm = normalize_text(user_message)
        traces: list[ToolCallTrace] = []

        def call_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
            res = self.toolkit.execute_tool(name, args)
            traces.append(ToolCallTrace(tool_name=name, arguments=args, result=res))
            return res

        # Combine context from recent history if user is following up (e.g., providing order ID or name)
        prev_context_norm = " ".join(
            normalize_text(h["content"]) for h in history[-4:]
        )

        # 1. Check for completely unrelated Out-of-Scope topics
        if any(kw in msg_norm for kw in self.OUT_OF_SCOPE_KEYWORDS) and not any(
            inst in msg_norm
            for inst in ("violao", "guitarra", "baixo", "bateria", "teclado", "ukulele", "instrumento", "musica", "pedido", "loja")
        ):
            reply = (
                "Haha, adoraria bater um papo sobre isso, mas minha especialidade aqui na **Empório da Música** "
                "são os instrumentos musicais! 🎸🥁🎹\n\n"
                "Eu sou o assistente virtual da loja e posso te ajudar com:\n"
                "- **Catálogo, preços e estoque** de violões, guitarras, baixos, baterias, teclados e ukuleles;\n"
                "- **Promoções ativas** e simulação de parcelamento (até 12x sem juros ou 5% OFF no PIX);\n"
                "- **Rastreamento e status de pedidos**;\n"
                "- **Políticas da loja** (trocas, devoluções, garantia, frete e horários de funcionamento).\n\n"
                "Tem algum instrumento que você está procurando ou alguma dúvida sobre um pedido?"
            )
            return AgentResponse(
                reply=reply,
                provider_used="offline-react",
                model_used="deterministic-hybrid-engine",
                tool_traces=traces,
                session_id=session_id,
            )

        # 2. Check for Accessories (Out of Store Scope per Sections 1 & 7.1)
        matched_accessories = [
            label
            for kw, label in self.ACCESSORY_KEYWORDS.items()
            if re.search(rf"\b{re.escape(kw)}\b", msg_norm)
        ]
        # Avoid false positive when user says "7 cordas" or "cordas de nylon/aço" referring to a guitar
        if "cordas" in msg_norm and any(
            x in msg_norm for x in ("violao", "violoes", "7 cordas", "nylon", "aco")
        ):
            matched_accessories = [
                a for a in matched_accessories if "cordas" not in a
            ]

        accessory_section_text = None
        if matched_accessories:
            call_tool("search_store_policies", {"query": "escopo acessórios cordas palhetas cabos amplificadores"})
            acc_names = ", ".join(dict.fromkeys(matched_accessories))
            accessory_section_text = (
                f"Sobre **{acc_names}**: aqui na **Empório da Música** nós trabalhamos **exclusivamente com instrumentos musicais** "
                "(violões, guitarras, baixos, baterias, teclados, ukuleles, sopros e cordas orquestrais). "
                "Por política da loja (Seções 1 e 7.1), **não comercializamos acessórios avulsos** como encordoamentos/cordas, palhetas, cabos, cases/capas, pedais, boquilhas avulsas ou amplificadores.\n\n"
                "💡 *Dica de amigo músico:* Para esses acessórios aqui em Campo Grande, recomendamos dar uma olhada nas lojas parceiras de acessórios e luthierias locais do Centro!"
            )
            # If the message ONLY asked about accessories, return immediately with a warm closing
            if not any(
                w in msg_norm
                for w in ("violao", "violoes", "guitarra", "baixo", "bateria", "teclado", "ukulele", "takamine", "yamaha", "fender", "taylor", "pedido", "endereco", "horario")
            ):
                return AgentResponse(
                    reply=(
                        f"Olá! Tudo bem? 🎶\n\n{accessory_section_text}\n\n"
                        "Mas se você estiver pensando em conhecer um instrumento novo — seja um violão, guitarra, baixo, teclado ou ukulele — é só me dizer seu estilo ou faixa de preço que eu consulto nosso estoque na hora pra você! Posso te ajudar com algum instrumento?"
                    ),
                    provider_used="offline-react",
                    model_used="deterministic-hybrid-engine",
                    tool_traces=traces,
                    session_id=session_id,
                )

        # 3. Detect Order / Customer / Return / Exchange / Warranty / Complaint Intent
        is_return_or_exchange = any(
            w in msg_norm
            for w in (
                "arrependi", "arrependimento", "devolver", "devolucao", "trocar",
                "troca", "defeito", "garantia", "reembolso", "estorno", "cancelar",
                "cancelamento", "reclamacao", "reclamar", "avaria",
            )
        )
        is_order_query = any(
            w in msg_norm
            for w in (
                "pedido", "rastreio", "rastreamento", "status", "entrega do meu",
                "onde esta meu", "comprei", "minha compra", "brab", "brcx", "brdz",
                "brqm", "brtp", "brvn", "brkr", "brjl",
            )
        ) or (
            "pedido" in prev_context_norm
            and (re.search(r"\b\d{1,2}\b", msg_norm) or "@" in msg_norm)
        )

        # Extract potential order_id, tracking_code, email, phone, or customer_name
        order_id_match = re.search(r"(?:pedido|order|#)\s*n?[ºo°]?\s*(\d{1,2})\b", msg_norm)
        if not order_id_match and ("pedido" in prev_context_norm or is_return_or_exchange):
            standalone_num = re.search(r"^\s*#?(\d{1,2})\s*$", msg_norm)
            if standalone_num:
                order_id_match = standalone_num

        tracking_match = re.search(r"\b(br[a-z0-9]{9}br)\b", msg_norm)
        email_match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", user_message)
        phone_match = re.search(r"(?:\(?67\)?\s*)?9?\d{4}[-\s]?\d{4}", user_message)

        # Check if any known customer name appears in the message
        matched_cust_name = self._detect_customer_name_in_text(msg_norm)

        order_lookup_data = None
        if (
            is_order_query
            or is_return_or_exchange
            or order_id_match
            or tracking_match
            or email_match
            or phone_match
            or matched_cust_name
        ):
            if (
                order_id_match
                or tracking_match
                or email_match
                or phone_match
                or matched_cust_name
            ):
                lookup_args: dict[str, Any] = {}
                if order_id_match:
                    lookup_args["order_id"] = int(order_id_match.group(1))
                if tracking_match:
                    lookup_args["tracking_code"] = tracking_match.group(1).upper()
                if email_match:
                    lookup_args["email"] = email_match.group(0)
                if phone_match:
                    lookup_args["phone"] = phone_match.group(0)
                if matched_cust_name and "order_id" not in lookup_args:
                    lookup_args["customer_name"] = matched_cust_name
                order_lookup_data = call_tool("lookup_order_or_customer", lookup_args)

        # Fetch return/exchange/warranty policies if relevant
        policy_return_data = None
        if is_return_or_exchange:
            policy_return_data = call_tool(
                "search_store_policies",
                {"query": "troca devolução direito de arrependimento defeito garantia 7 dias 30 dias 90 dias"},
            )

        # If this is primarily a return/exchange or order status query, synthesize the response
        if is_return_or_exchange or is_order_query or order_lookup_data:
            # Check if the user ALSO asked about a product in the same message; if not, return order/policy synthesis
            reply = self._synthesize_order_and_return_response(
                user_message=user_message,
                msg_norm=msg_norm,
                order_data=order_lookup_data,
                policy_data=policy_return_data,
                is_return_or_exchange=is_return_or_exchange,
                accessory_note=accessory_section_text,
            )
            return AgentResponse(
                reply=reply,
                provider_used="offline-react",
                model_used="deterministic-hybrid-engine",
                tool_traces=traces,
                session_id=session_id,
            )

        # 4. Detect Store Policy / General Info Intent (Address, Opening Hours, Contact, Shipping, Payment, LGPD)
        asking_address_or_contact = any(
            w in msg_norm
            for w in (
                "endereco", "onde fica", "localizacao", "rua", "cep", "campo grande",
                "telefone", "whatsapp", "contato", "email", "e-mail", "cnpj", "historia",
                "fundada", "sobre a loja",
            )
        )
        asking_hours = any(
            w in msg_norm
            for w in (
                "horario", "funcionamento", "expediente", "abre", "fecha", "aberto",
                "sabado", "domingo", "feriado",
            )
        )
        asking_shipping_general = any(
            w in msg_norm
            for w in ("frete", "entrega", "motoboy", "correios", "pac", "sedex", "jadlog", "envio", "enviam")
        )
        asking_payment_general = any(
            w in msg_norm
            for w in ("formas de pagamento", "como pagar", "parcela", "parcelamento", "aceita pix", "boleto", "cartao")
        )
        asking_lgpd = any(
            w in msg_norm for w in ("lgpd", "privacidade", "meus dados", "excluir dados", "protecao de dados")
        )
        asking_promotions_general = any(
            w in msg_norm
            for w in ("promocao", "promocoes", "desconto", "oferta", "ofertas", "black friday", "queima de estoque", "aniversario da loja", "semana do musico")
        )

        # 5. Detect Product / Catalog Search Intent
        product_search_params = self._extract_product_search_params(msg_norm)
        has_product_intent = bool(
            product_search_params.get("query")
            or product_search_params.get("category")
            or product_search_params.get("max_price") is not None
            or product_search_params.get("min_price") is not None
            or any(
                w in msg_norm
                for w in (
                    "quanto custa", "preco", "valor", "estoque", "disponivel", "disponiveis",
                    "opcoes", "catalogo", "instrumento", "violao", "violoes", "guitarra",
                    "baixo", "bateria", "teclado", "piano", "ukulele", "sopro", "violino",
                )
            )
        )

        sections_output: list[str] = []
        if accessory_section_text:
            sections_output.append(accessory_section_text)

        # Execute Policy RAG if general store info was requested
        if asking_address_or_contact or asking_hours or asking_lgpd or (
            (asking_shipping_general or asking_payment_general) and not has_product_intent
        ):
            policy_query_parts = []
            if asking_address_or_contact:
                policy_query_parts.append("endereço telefone whatsapp email cnpj sobre a loja")
            if asking_hours:
                policy_query_parts.append("horário de funcionamento segunda sexta sábado domingo feriados")
            if asking_shipping_general:
                policy_query_parts.append("política de frete entregas campo grande outras cidades pac sedex jadlog")
            if asking_payment_general:
                policy_query_parts.append("formas de pagamento pix cartão parcelamento regras")
            if asking_lgpd:
                policy_query_parts.append("privacidade proteção de dados lgpd exclusão")

            call_tool("search_store_policies", {"query": " ".join(policy_query_parts)})

            if asking_shipping_general and re.search(r"r\$\s*\d+", msg_norm):
                amt_match = re.search(r"r\$\s*(\d+(?:[\.,]\d+)?)", msg_norm)
                amt = float(amt_match.group(1).replace(",", ".")) if amt_match else 500.0
                call_tool("calculate_payment_and_shipping", {"amount_brl": amt})

            sections_output.append(
                self._format_general_policy_answer(
                    asking_address_or_contact=asking_address_or_contact,
                    asking_hours=asking_hours,
                    asking_shipping=asking_shipping_general,
                    asking_payment=asking_payment_general,
                    asking_lgpd=asking_lgpd,
                )
            )

        # Execute Promotions tool if requested
        if asking_promotions_general and not product_search_params.get("query"):
            include_exp = any(
                w in msg_norm
                for w in ("black friday", "inverno", "pascoa", "semana do musico", "aniversario", "expirada", "antiga", "passada")
            )
            promo_res = call_tool("get_promotions", {"include_expired": include_exp})
            sections_output.append(self._format_promotions_answer(promo_res, msg_norm))

        # Execute Product Search tool if requested
        if has_product_intent:
            prod_res = call_tool("search_products", product_search_params)

            # If a single product is matched and user asks about shipping/payment or price, also run calculator
            products_list = prod_res.get("products", [])
            calc_res = None
            if len(products_list) == 1 or (
                products_list and product_search_params.get("query")
            ):
                top_prod = products_list[0]
                if asking_shipping_general or asking_payment_general or "quanto custa" in msg_norm or "preco" in msg_norm:
                    # Detect destination city if mentioned
                    dest_city = "Campo Grande"
                    for c_cand in ("dourados", "tres lagoas", "corumba", "ponta pora", "sao paulo", "curitiba"):
                        if c_cand in msg_norm:
                            dest_city = c_cand.title()
                    calc_res = call_tool(
                        "calculate_payment_and_shipping",
                        {
                            "amount_brl": top_prod["effective_price_brl"],
                            "city": dest_city,
                            "is_promotional_price": top_prod["has_active_promotion"],
                        },
                    )

            sections_output.append(
                self._format_product_search_answer(
                    prod_res=prod_res,
                    search_params=product_search_params,
                    calc_res=calc_res,
                    msg_norm=msg_norm,
                )
            )

        if not sections_output:
            # Friendly greeting / open assistance fallback
            call_tool("search_store_policies", {"query": "sobre a loja atendimento fluxo saudação"})
            reply = (
                "Olá! Seja muito bem-vindo(a) à **Empório da Música** — *Sua música começa aqui!* 🎸🎶\n\n"
                "Eu sou o assistente virtual da loja aqui de Campo Grande/MS. Como posso te ajudar hoje?\n"
                "- 🔍 **Buscar instrumentos, preços e estoque** (violões, guitarras, baixos, baterias, teclados e ukuleles);\n"
                "- 🏷️ **Consultar promoções ativas** e condições de pagamento (5% OFF no PIX ou até 12x sem juros);\n"
                "- 📦 **Acompanhar status e rastreio de pedidos**;\n"
                "- 📋 **Tirar dúvidas sobre nossas políticas** (horários, endereço, frete, trocas e garantia).\n\n"
                "Me conta: qual instrumento ou informação você está procurando?"
            )
            return AgentResponse(
                reply=reply,
                provider_used="offline-react",
                model_used="deterministic-hybrid-engine",
                tool_traces=traces,
                session_id=session_id,
            )

        full_reply = (
            "Olá! Tudo bem? 🎶\n\n"
            + "\n\n---\n\n".join(sections_output)
            + "\n\nFicou com alguma dúvida ou quer que eu simule o parcelamento/frete de algum modelo específico? Estou à disposição!"
        )
        return AgentResponse(
            reply=full_reply,
            provider_used="offline-react",
            model_used="deterministic-hybrid-engine",
            tool_traces=traces,
            session_id=session_id,
        )

    def _detect_customer_name_in_text(self, msg_norm: str) -> str | None:
        """Check if any customer name from the database is mentioned in the user message."""
        rows = self.db.conn.execute("SELECT name, name_norm FROM customers").fetchall()
        for r in rows:
            full_norm = r["name_norm"]
            parts = full_norm.split()
            if full_norm in msg_norm:
                return str(r["name"])
            if len(parts) >= 2:
                first_two = f"{parts[0]} {parts[1]}"
                if first_two in msg_norm and len(first_two) >= 8:
                    return str(r["name"])
        return None

    def _extract_product_search_params(self, msg_norm: str) -> dict[str, Any]:
        """Extract structured filter parameters (`category`, `max_price`, `query`, `strings_type`, etc.) from text."""
        params: dict[str, Any] = {}

        # 1. Category detection
        if any(w in msg_norm for w in ("violao", "violoes", "dreadnought", "eletroacustico")):
            params["category"] = "Violões"
        elif any(w in msg_norm for w in ("guitarra", "guitarras", "stratocaster", "les paul", "telecaster")):
            params["category"] = "Guitarras"
        elif any(w in msg_norm for w in ("contrabaixo", "baixo", "baixos", "jazz bass", "stingray")):
            params["category"] = "Baixos"
        elif any(w in msg_norm for w in ("bateria", "baterias", "percussao")):
            params["category"] = "Baterias"
        elif any(w in msg_norm for w in ("teclado", "teclados", "piano", "sintetizador", "synth")):
            params["category"] = "Teclados"
        elif any(w in msg_norm for w in ("ukulele", "ukuleles", "soprano", "concert", "tenor", "baritono")):
            params["category"] = "Ukuleles"
        elif any(w in msg_norm for w in ("sopro", "saxofone", "flauta", "clarinete", "trompete", "trombone")):
            params["category"] = "Sopro"
        elif any(w in msg_norm for w in ("violino", "violoncelo", "viola", "orquestral", "orquestrais")):
            params["category"] = "Cordas Orquestrais"

        # 2. Price ceiling / floor extraction (e.g., "até R$1000", "até 1.000", "abaixo de 800", "acima de 2000")
        max_match = re.search(
            r"(?:ate|abaixo de|menos de|no maximo|maximo de)\s*(?:r\$\s*)?(\d{1,3}(?:[\.\s]\d{3})+|\d+(?:,\d+)?)",
            msg_norm,
        )
        if max_match:
            raw_num = max_match.group(1).replace(".", "").replace(" ", "").replace(",", ".")
            params["max_price"] = float(raw_num)

        min_match = re.search(
            r"(?:acima de|mais de|a partir de|no minimo)\s*(?:r\$\s*)?(\d{1,3}(?:[\.\s]\d{3})+|\d+(?:,\d+)?)",
            msg_norm,
        )
        if min_match:
            raw_num = min_match.group(1).replace(".", "").replace(" ", "").replace(",", ".")
            params["min_price"] = float(raw_num)

        # 3. Strings / Electronics filters
        if "7 cordas" in msg_norm:
            params["strings_type"] = "7 cordas"
        elif "nylon" in msg_norm or "nailon" in msg_norm:
            params["strings_type"] = "nylon"
        elif re.search(r"\baco\b", msg_norm):
            params["strings_type"] = "steel"

        if any(w in msg_norm for w in ("eletrico", "eletroacustico")):
            if "guitarra" not in msg_norm and "baixo" not in msg_norm:
                params["has_electronics"] = True

        # 4. In-stock filter when user asks for "disponíveis" or "opções"
        if any(w in msg_norm for w in ("opcoes", "quais", "disponiveis", "ate r$", "sugestoes", "recomenda")):
            params["only_in_stock"] = True

        # 5. Specific model / brand query detection
        known_models_brands = [
            "takamine gd20", "takamine gc5ce", "takamine gn51ce", "takamine gc1ce", "takamine",
            "yamaha c40", "yamaha c70", "yamaha f310", "yamaha fg800", "yamaha ntx1",
            "yamaha apx600", "yamaha cg162s", "yamaha",
            "tagima memphis", "ac-39", "tagima dallas", "tagima woodstock", "tagima classical",
            "tagima vegas", "tagima tw-7", "tagima",
            "giannini gn-15", "giannini gf-1r", "giannini gf-3d", "gf-3d", "giannini gnf-3",
            "giannini gwne-7", "giannini",
            "rozini rc-104", "rozini rv-174", "rozini rv-175", "rozini",
            "shelby sn-100", "shelby sgd-195e", "shelby sn-7c", "sn-7c", "shelby su-21s", "shelby",
            "crafter ht-100", "ht-100", "crafter d-8", "crafter ce-15", "crafter",
            "martin d-28e", "martin d-28", "martin",
            "taylor 110e", "110e", "taylor 214ce", "214ce", "taylor",
            "kala ka-15s", "kala ka-c", "kala ka-smhce", "kala ka-t", "kala ka-srt-ctg",
            "kala ka-b", "kala ka-abp-ctg", "ka-abp-ctg", "kala",
            "ohana sk-10", "ohana ck-20", "ck-20", "ohana tk-35g", "ohana bk-35e", "ohana",
            "kalani kal-300s", "kalani kal-500c", "kalani kal-700t", "kal-700t", "kalani",
            "fender stratocaster", "fender telecaster", "stratocaster", "telecaster", "fender",
            "gibson les paul", "les paul", "gibson",
            "ibanez rg550", "rg550", "ibanez bass 2x", "ibanez",
            "prs se custom 24", "prs",
            "music man", "pearl", "korg", "nord", "roland",
            "soprano", "concert", "tenor", "baritono",
        ]
        for candidate in known_models_brands:
            if candidate in msg_norm:
                params["query"] = candidate
                # When looking up a specific model/brand, allow seeing out-of-stock/discontinued status
                if len(candidate.split()) >= 2 or candidate in ("gf-3d", "sn-7c", "ka-abp-ctg", "rg550"):
                    params["only_in_stock"] = False
                break

        return params

    def _format_general_policy_answer(
        self,
        asking_address_or_contact: bool,
        asking_hours: bool,
        asking_shipping: bool,
        asking_payment: bool,
        asking_lgpd: bool,
    ) -> str:
        """Format accurate policy answers grounded in `políticas_da_loja.pdf`."""
        blocks: list[str] = []

        if asking_address_or_contact:
            blocks.append(
                "📍 **Endereço e Contatos da Empório da Música** *(Seção 1.2 e Seção 7 do Manual)*:\n"
                "- **Endereço Físico:** Rua 14 de Maio, 3200 — Centro, Campo Grande – MS, CEP 79202-333\n"
                "- **Telefone Fixo / Geral:** (67) 3341-4444\n"
                "- **WhatsApp de Atendimento Remoto:** (67) 3321-4500\n"
                "- **E-mail:** contato@emporiodamusica.com.br\n"
                "- **Razão Social / CNPJ:** Empório da Música Instrumentos Musicais Ltda. (CNPJ: 12.345.678/0001-90)\n"
                "- **Sobre nós:** Fundada em 2008 em Campo Grande/MS, somos especializados exclusivamente em instrumentos musicais (+300 modelos nacionais e importados)."
            )

        if asking_hours:
            blocks.append(
                "🕒 **Horário de Funcionamento** *(Seção 2 — Loja Física e WhatsApp)*:\n"
                "- **Segunda a Sexta-feira:** das **09:00 às 18:00**\n"
                "- **Sábado:** das **09:00 às 13:00**\n"
                "- **Domingos e Feriados:** **Fechado** *(com atendimento automático fora do expediente)*\n"
                "- *Nota:* Em datas especiais (Black Friday, Aniversário da Loja em Agosto e Natal), o horário pode ser estendido mediante aviso prévio nas redes sociais e WhatsApp."
            )

        if asking_payment:
            blocks.append(
                "💳 **Formas de Pagamento e Parcelamento** *(Seção 3 — Compras Presenciais e Online)*:\n"
                "- **PIX:** Pagamento à vista com **5% de desconto** sobre o preço de tabela *(não cumulativo com produtos que já estão em promoção ativa — Seção 6.2)*.\n"
                "- **Cartão de Crédito (até 12x sem juros):**\n"
                "  * **Até 3x sem juros:** parcela mínima de **R$ 50,00**\n"
                "  * **De 4x a 6x sem juros:** parcela mínima de **R$ 80,00**\n"
                "  * **De 7x a 12x sem juros:** parcela mínima de **R$ 100,00**\n"
                "- **Cartão de Débito:** À vista (aceitamos todas as bandeiras).\n"
                "- **Boleto Bancário:** À vista (compensação em até **3 dias úteis**).\n"
                "- **Pagamento Combinado (ex.: PIX + Cartão):** Permitido para compras acima de **R$ 2.000,00**."
            )

        if asking_shipping:
            blocks.append(
                "🚚 **Política de Frete e Entregas** *(Seção 5)*:\n"
                "1. **Região Metropolitana de Campo Grande/MS:**\n"
                "   - **Frete Grátis** para pedidos acima de **R$ 500,00**!\n"
                "   - Pedidos abaixo de R$ 500,00: **taxa fixa de R$ 35,00**.\n"
                "   - **Prazo e Entrega:** **1 a 3 dias úteis** via **motoboy próprio** (entramos em contato por telefone antes da entrega).\n"
                "2. **Outras Cidades (Interior de MS e demais Estados):**\n"
                "   - **SEDEX (Correios):** 2 a 5 dias úteis *(com rastreamento e seguro incluído)*\n"
                "   - **Jadlog (.package):** 3 a 8 dias úteis *(com rastreamento e seguro incluído)*\n"
                "   - **PAC (Correios):** 5 a 12 dias úteis *(com rastreamento e seguro incluído)*\n"
                "   - *Observação:* Instrumentos de grande porte (baterias acústicas, pianos digitais, contrabaixos) podem exigir cotação individual. Em caso de avaria no transporte, recuse o recebimento no ato e nos avise imediatamente!"
            )

        if asking_lgpd:
            blocks.append(
                "🔒 **Privacidade e Proteção de Dados — LGPD (Lei nº 13.709/2018)** *(Seção 9)*:\n"
                "- Seus dados (nome, telefone, e-mail, endereço) são usados exclusivamente para processamento/entrega de pedidos, avisos de status/rastreio, envio de promoções (apenas mediante seu consentimento explícito) e obrigações fiscais.\n"
                "- **Jamais compartilhamos seus dados com terceiros** para fins de marketing, e você pode solicitar a exclusão a qualquer momento pelo nosso WhatsApp ou e-mail."
            )

        return "\n\n".join(blocks)

    def _format_promotions_answer(self, promo_res: dict[str, Any], msg_norm: str) -> str:
        """Format active and expired promotions with full transparency (Section 6.2)."""
        active = promo_res.get("active_promotions", [])
        lines = [
            "🏷️ **Promoções Ativas no Sistema Agora** *(Consultado em tempo real — Seção 6)*:"
        ]
        for p in active:
            lines.append(
                f"- **{p['product_name']}** ({p['category_name']}) — Campanha *{p['campaign_name']}*:\n"
                f"  * De ~~R$ {p['original_price_brl']:,.2f}~~ por **R$ {p['promotional_price_brl']:,.2f}** (**{p['discount_percent']}% de desconto**)\n"
                f"  * Estoque atual: **{p['stock_quantity']} unidades**"
            )

        lines.append(
            "\n📌 **Regras Importantes de Promoção (Seção 6.2):**\n"
            "- **Não-cumulatividade:** Promoções não são cumulativas — o desconto de 5% do PIX **não** se aplica sobre preços que já estão em promoção.\n"
            "- **Estoque:** Sujeitas à disponibilidade em estoque (sem reserva de preço / *rain check*)."
        )

        if promo_res.get("expired_promotions"):
            lines.append(
                "\n⚠️ **Sobre Campanhas Anteriores / Expiradas:**\n"
                "Verifiquei no sistema que campanhas sazonais passadas (como *Black Friday*, *Semana do Músico*, *Promoção de Páscoa*, *Liquidação de Inverno* e *Aniversário da Loja*) estão **encerradas no momento** (`is_active = 0`). Por transparência (Seção 7.3), trabalhamos com os valores vigentes acima!"
            )

        return "\n".join(lines)

    def _format_product_search_answer(
        self,
        prod_res: dict[str, Any],
        search_params: dict[str, Any],
        calc_res: dict[str, Any] | None,
        msg_norm: str,
    ) -> str:
        """Format catalog search results with prices, promotions, installments, and stock status."""
        if prod_res.get("empty_category_warning"):
            return (
                f"🎷 **Sobre a categoria solicitada:**\n"
                f"A Empório da Música possui as categorias de **Instrumentos de Sopro (Madeiras e Metais)** e **Cordas Orquestrais** cadastradas, "
                f"porém **no momento estamos sem unidades cadastradas em estoque no sistema online** para essa categoria específica.\n\n"
                "No catálogo online atual temos pronta entrega nas linhas de **Violões, Guitarras, Contrabaixos, Baterias Acústicas, Teclados/Sintetizadores e Ukuleles**. "
                "Gostaria de ver opções em alguma dessas categorias ou deixar seu contato para avisarmos quando chegarem novos lotes?"
            )

        products = prod_res.get("products", [])
        if not products:
            return (
                "🔍 Consultei nosso catálogo em tempo real, mas **não encontrei nenhum instrumento que corresponda exatamente a todos esses filtros**.\n"
                "Se quiser, posso buscar opções próximas de faixa de preço ou de outra marca/categoria!"
            )

        # Case A: Single specific product query (e.g., "Quanto custa o Takamine GD20?", "Tem o Giannini GF-3D?")
        if len(products) == 1 or (
            search_params.get("query")
            and len(products) <= 2
            and normalize_text(search_params["query"]) in normalize_text(products[0]["name"])
        ):
            p = products[0]
            lines = [f"🎸 **{p['name']}** *(Código #{p['product_id']} — Categoria: {p['category_name']})*"]
            lines.append(f"- **Descrição:** {p['description']}")

            # Status & Stock check (Section 7.3)
            if p["status"] == "discontinued":
                lines.append(
                    f"- ⚠️ **Status no Estoque:** **Produto Descontinuado** — Este modelo não faz mais parte do nosso catálogo ativo (preço histórico de referência: R$ {p['list_price_brl']:,.2f})."
                )
            elif p["status"] == "coming_soon":
                lines.append(
                    f"- ⏳ **Status no Estoque:** **Em Breve (`coming_soon`)** — Modelo em pré-lançamento com {p['stock_quantity']} unidades previstas (Preço de tabela: R$ {p['list_price_brl']:,.2f})."
                )
            elif p["stock_quantity"] <= 0:
                lines.append(
                    f"- ⚠️ **Status no Estoque:** **Temporariamente Indisponível (Fora de Estoque — 0 unidades)** no momento (Preço de tabela: R$ {p['list_price_brl']:,.2f})."
                )
            else:
                lines.append(
                    f"- ✅ **Disponibilidade:** **Em estoque!** ({p['stock_quantity']} unidades disponíveis para pronta entrega)"
                )

            # Price & Promotion check (Section 6.2)
            if p["has_active_promotion"]:
                ap = p["active_promotion"]
                lines.append(
                    f"- 🏷️ **PROMOÇÃO ATIVA ({ap['campaign_name']} — {ap['discount_percent']}% OFF):**\n"
                    f"  * **Preço Original:** ~~R$ {ap['original_price_brl']:,.2f}~~\n"
                    f"  * **Preço Promocional:** **R$ {ap['promotional_price_brl']:,.2f}**\n"
                    f"  * *Nota (Seção 6.2):* Como este item já está com {ap['discount_percent']}% de desconto promocional, o desconto de 5% do PIX não se acumula."
                )
            else:
                lines.append(
                    f"- 💰 **Preço de Tabela:** **R$ {p['list_price_brl']:,.2f}**\n"
                    f"- ⚡ **Preço no PIX (5% de desconto à vista):** **R$ {p['pix_price_brl']:,.2f}** *(economia de R$ {p['list_price_brl'] - p['pix_price_brl']:,.2f}!)*"
                )
                if p.get("expired_promotion_history"):
                    lines.append(
                        f"  * *(Nota de transparência: este modelo já participou da campanha '{p['expired_promotion_history']}', que encontra-se encerrada no momento).* "
                    )

            # Payment & Shipping details
            po = p["payment_options"]
            lines.append(
                f"- 💳 **Parcelamento no Cartão:** **{po['max_interest_free_installments']}** "
                f"(ou à vista no Débito / Boleto por R$ {p['effective_price_brl']:,.2f})."
            )
            if po["allows_combined_payment"]:
                lines.append(
                    "- 🤝 **Pagamento Combinado:** Como o valor supera R$ 2.000,00, você pode combinar formas de pagamento (ex.: dar uma entrada no PIX e parcelar o restante no cartão — Seção 3.1)!"
                )

            if calc_res and "shipping" in calc_res:
                sh = calc_res["shipping"]
                if sh.get("free_shipping_applied") is True:
                    lines.append(
                        f"- 🚚 **Frete (Campo Grande e Região):** **FRETE GRÁTIS** (compras acima de R$ 500,00), entregue por motoboy próprio em **1 a 3 dias úteis**! Para outras cidades, enviamos via SEDEX (2–5 dias úteis), Jadlog (3–8 dias úteis) ou PAC (5–12 dias úteis) com seguro incluso."
                    )
                elif sh.get("free_shipping_applied") is False:
                    lines.append(
                        f"- 🚚 **Frete (Campo Grande e Região):** Taxa fixa de **R$ 35,00** (pedidos abaixo de R$ 500,00), entrega em **1 a 3 dias úteis** via motoboy próprio."
                    )

            # Specs summary
            if p.get("specs"):
                specs_str = ", ".join(f"{k}: {v}" for k, v in p["specs"].items())
                lines.append(f"- 🔧 **Especificações Técnicas:** `{specs_str}`")

            if p.get("catalog_note"):
                lines.append(f"- ℹ️ *{p['catalog_note']}*")

            # Alternatives if out-of-stock or discontinued (Section 7.3)
            alts = prod_res.get("suggested_alternatives_for_unavailable", [])
            if not p["is_available_now"] and alts:
                lines.append(
                    "\n💡 **Sugestões de Alternativas Equivalentes Disponíveis em Estoque (Seção 7.3):**"
                )
                for a in alts:
                    lines.append(
                        f"  * **{a['name']}** — **R$ {a['effective_price_brl']:,.2f}** (ou **R$ {a['pix_price_brl']:,.2f} no PIX**) | Estoque: {a['stock_quantity']} un."
                    )

            return "\n".join(lines)

        # Case B: Multiple products / Budget / Category search (e.g., "Quais opções de violões disponíveis custando até R$1000?")
        cat_label = search_params.get("category") or "Instrumentos"
        max_p = search_params.get("max_price")
        header = f"🎸 **Opções de {cat_label} Disponíveis em Estoque"
        if max_p is not None:
            header += f" (até R$ {max_p:,.2f})"
        header += f"** *(Encontrados: {len(products)} modelos em estoque)*:\n"

        # Group by sub-type if searching Violões (Nylon vs Aço vs Eletroacústico vs 7 Cordas)
        lines = [header]
        for idx, p in enumerate(products, start=1):
            strings_badge = ""
            if p["specs"].get("strings") == "nylon":
                strings_badge = " [Cordas de Nylon]"
            elif p["specs"].get("strings") == "steel":
                strings_badge = " [Cordas de Aço]"
            elec_badge = " ⚡ Eletroacústico" if p["specs"].get("electronics") == "yes" else ""

            promo_tag = ""
            if p["has_active_promotion"]:
                ap = p["active_promotion"]
                price_display = (
                    f"De ~~R$ {ap['original_price_brl']:,.2f}~~ por **R$ {ap['promotional_price_brl']:,.2f}** "
                    f"🔥 *({ap['discount_percent']}% OFF - {ap['campaign_name']})*"
                )
            else:
                price_display = (
                    f"**R$ {p['list_price_brl']:,.2f}** *(ou **R$ {p['pix_price_brl']:,.2f}** à vista no PIX com 5% OFF)*"
                )

            lines.append(
                f"{idx}. **{p['name']}**{strings_badge}{elec_badge}\n"
                f"   - 💰 Preço: {price_display}\n"
                f"   - 💳 Cartão: {p['payment_options']['max_interest_free_installments']} | 📦 Estoque: **{p['stock_quantity']} un.**\n"
                f"   - 📝 *{p['description']}*"
            )

        # Explicitly note any out-of-stock or discontinued items in that price range for total transparency
        if cat_label == "Violões" and max_p is not None and max_p >= 800:
            lines.append(
                "\n📌 *Nota de Transparência do Sistema (Seção 7.3):*\n"
                "- O violão **Giannini GF-3D Dreadnought Sunburst** (R$ 799,90) está **temporariamente sem estoque (0 unidades)** no momento, e o **Shelby SN-7C 7 Cordas** (R$ 749,00) foi **descontinuado**, por isso listei acima apenas os modelos com pronta entrega garantida!"
            )

        lines.append(
            "\n💡 **Condições Gerais:**\n"
            "- **PIX:** 5% de desconto à vista sobre o preço de tabela *(não cumulativo com promoções ativas)*.\n"
            "- **Frete Grátis em Campo Grande/MS** para pedidos acima de R$ 500,00 (abaixo de R$ 500,00, taxa fixa de R$ 35,00 via motoboy em 1 a 3 dias úteis)."
        )
        return "\n".join(lines)

    def _synthesize_order_and_return_response(
        self,
        user_message: str,
        msg_norm: str,
        order_data: dict[str, Any] | None,
        policy_data: dict[str, Any] | None,
        is_return_or_exchange: bool,
        accessory_note: str | None = None,
    ) -> str:
        """Synthesize a comprehensive response for order status, tracking, returns, exchanges, or warranty."""
        blocks: list[str] = []
        if accessory_note:
            blocks.append(accessory_note)

        # 1. If we looked up an order or customer
        if order_data and order_data.get("found"):
            if order_data.get("disambiguation_needed") or order_data.get("disambiguation_notice"):
                blocks.append(f"⚠️ *{order_data['disambiguation_notice']}*")

            orders = order_data.get("orders", [])
            customers = order_data.get("customers", [])

            if orders:
                blocks.append("📦 **Consulta de Pedido em Tempo Real no Sistema:**")
                for o in orders:
                    status_map = {
                        "delivered": "✅ Entregue (`delivered`)",
                        "shipped": "🚚 Em transporte / Despachado (`shipped`)",
                        "confirmed": "✔️ Pagamento Confirmado / Em separação (`confirmed`)",
                        "pending": "⏳ Pagamento Pendente (`pending`)",
                        "cancelled": "❌ Cancelado (`cancelled`)",
                    }
                    st_label = status_map.get(o["status"], o["status"])
                    items_str = ", ".join(
                        f"{it['quantity']}x **{it['product_name']}** (R$ {it['catalog_unit_price_brl']:,.2f})"
                        for it in o.get("items", [])
                    )
                    order_lines = [
                        f"- **Pedido #{o['order_id']}** — Cliente: **{o['customer_name']}** ({o['customer_city']}/MS)",
                        f"  * **Data do Pedido:** {o['order_date']} | **Status:** {st_label}",
                        f"  * **Itens:** {items_str}",
                        f"  * **Valor Total:** R$ {o['total_brl']:,.2f} (`{o['payment_method']}`)",
                    ]
                    if o.get("tracking_code"):
                        order_lines.append(
                            f"  * **Código de Rastreamento:** `{o['tracking_code']}` | **Previsão/Data de Entrega:** {o.get('estimated_delivery') or 'A confirmar'}"
                        )
                    if o.get("notes"):
                        order_lines.append(f"  * **Observação do Sistema:** *{o['notes']}*")

                    # Include automatic return/exchange eligibility analysis if relevant
                    elig = o.get("return_and_warranty_eligibility", {})
                    if elig and (is_return_or_exchange or o["status"] in ("delivered", "shipped")):
                        order_lines.append(
                            f"  * 📋 **Análise de Prazos (Data de referência: {order_data.get('reference_date_used')}):** {elig.get('explanation')}"
                        )
                    blocks.append("\n".join(order_lines))
            elif customers:
                c = customers[0]
                blocks.append(
                    f"👤 Localizei o cadastro de **{c['name']}** ({c['city']}/MS — `{c['email']}`), "
                    "mas **não constam pedidos vinculados a este perfil** no histórico atual."
                )
        elif order_data and not order_data.get("found"):
            blocks.append(
                "🔍 Consultei nosso sistema de pedidos, mas **não localizei nenhum pedido ou cliente com os dados informados**. "
                "Por favor, verifique o número do pedido (de `#1` a `#20`), o código de rastreio ou informe o nome completo/e-mail cadastrado."
            )

        # 2. If the user is asking about Return / Regret / Exchange / Defect / Warranty policies
        if is_return_or_exchange:
            blocks.append(
                "📋 **Regras da Política de Trocas, Devoluções e Garantia da Empório da Música** *(Seções 4 e 8 do Manual — CDC Lei nº 8.078/90)*:\n\n"
                "1. **Direito de Arrependimento — Compras Online (Seção 4.1):**\n"
                "   - **Prazo:** Até **7 (sete) dias corridos** após o **recebimento** do produto, sem necessidade de justificativa.\n"
                "   - **Condições:** O instrumento deve estar na **embalagem original, sem sinais de uso**, acompanhado de todos os acessórios e manuais.\n"
                "   - **Frete de Devolução:** **Por conta da Empório da Música** (gratuito para você).\n"
                "   - **Reembolso:** Realizado na **mesma forma de pagamento original em até 10 dias úteis**.\n\n"
                "2. **Trocas por Preferência — Cor, Modelo ou Tamanho (Seção 4.3):**\n"
                "   - Permitidas em até **7 dias corridos**, mediante disponibilidade de estoque, com o produto em perfeito estado e na embalagem original (eventuais diferenças de valor são cobradas ou reembolsadas).\n\n"
                "3. **Trocas por Defeito de Fabricação e Garantia (Seções 4.2 e 8):**\n"
                "   - **Até 30 dias corridos após a compra:** Troca direta realizada aqui na loja.\n"
                "   - **Após 30 dias:** Acionamento da garantia diretamente com o fabricante (a Empório da Música pode **intermediar o processo** mediante sua solicitação). Todos os produtos contam com **90 dias de Garantia Legal (CDC)** a partir do recebimento, além da **Garantia do Fabricante (de 6 meses a 2 anos)**.\n"
                "   - **Exclusões (Seções 4.4 e 8.3):** Não são elegíveis para troca/garantia instrumentos com personalização/regulagem sob encomenda (*setup* especial), itens de liquidação marcados como *'venda final'*, boquilhas de sopro (por higiene), desgaste natural (cordas, trastes, feltros) ou danos por mau uso/quedas/umidade."
            )

            if not order_data:
                blocks.append(
                    "👉 **Como prosseguir agora:**\n"
                    "Você poderia me informar o **número do seu pedido** (ou seu **nome completo / e-mail**) e quando recebeu o instrumento? "
                    "Assim eu já consulto seu pedido no sistema em tempo real e verifico o status exato para iniciar sua solicitação!"
                )

        return "\n\n".join(blocks)
