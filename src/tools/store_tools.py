"""Domain Toolkit for the Empório da Música AI Agent.

Exposes 5 deterministic tools with OpenAI-compatible JSON schemas:
1. `search_products`: Catalog search by name, brand, category, price range, strings, electronics, stock.
2. `get_promotions`: Check active vs. expired promotional campaigns and non-cumulative discount rules.
3. `lookup_order_or_customer`: Real-time order status, tracking code, items, and customer profile lookup.
4. `calculate_payment_and_shipping`: Exact PIX/installment breakdown + shipping cost/carrier calculator.
5. `search_store_policies`: Hybrid RAG search over `políticas_da_loja.pdf`.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from src.config import AgentConfig
from src.data.database import StoreDatabase, normalize_text
from src.retrieval.policy_rag import PolicyKnowledgeBase


class StoreToolkit:
    """Binds the relational `StoreDatabase` and `PolicyKnowledgeBase` into callable LLM tools."""

    def __init__(
        self,
        db: StoreDatabase,
        policy_kb: PolicyKnowledgeBase,
        config: AgentConfig | None = None,
    ) -> None:
        self.db = db
        self.policy_kb = policy_kb
        self.config = config or AgentConfig()

    @property
    def tool_schemas(self) -> list[dict[str, Any]]:
        """Return OpenAI/Groq/Ollama function-calling JSON schemas."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "search_products",
                    "description": (
                        "Search the Empório da Música instrument catalog for prices, stock availability, "
                        "technical specifications, and active promotions. MUST be called before answering "
                        "any question about product prices, stock, models, or budget recommendations."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Product name, brand, or keyword (e.g., 'Takamine GD20', 'Yamaha', 'Fender', '7 cordas', 'soprano'). Omit to list all in category.",
                            },
                            "category": {
                                "type": "string",
                                "description": "Instrument category (e.g., 'Violões', 'Guitarras', 'Baixos', 'Baterias', 'Teclados', 'Ukuleles', 'Sopro', 'Cordas Orquestrais').",
                            },
                            "min_price": {
                                "type": "number",
                                "description": "Minimum price filter in BRL (R$).",
                            },
                            "max_price": {
                                "type": "number",
                                "description": "Maximum price filter in BRL (R$), e.g., 1000 for 'até R$1000'.",
                            },
                            "strings_type": {
                                "type": "string",
                                "enum": ["nylon", "steel", "7 cordas"],
                                "description": "Filter guitars/violões by string material ('nylon', 'steel' for aço, or '7 cordas').",
                            },
                            "has_electronics": {
                                "type": "boolean",
                                "description": "True for electro-acoustic (elétrico/eletroacústico) instruments, False for purely acoustic.",
                            },
                            "only_in_stock": {
                                "type": "boolean",
                                "description": "Set to True when the user specifically asks for available/in-stock options ('disponíveis'). Set to False when checking a specific model so you can see if it is out-of-stock or discontinued.",
                            },
                        },
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_promotions",
                    "description": (
                        "List active promotional discounts in the store (and optionally expired campaigns "
                        "like Black Friday, Semana do Músico, Aniversário da Loja) along with promotion rules."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "include_expired": {
                                "type": "boolean",
                                "description": "Set to True if the customer asks about a past/expired promotion (e.g., Black Friday, Páscoa, Semana do Músico) or why a discount is no longer active.",
                            }
                        },
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "lookup_order_or_customer",
                    "description": (
                        "Look up customer orders, order status (delivered, shipped, confirmed, pending, cancelled), "
                        "tracking codes, purchased items, and automatic eligibility for 7-day regret return, "
                        "30-day store defect exchange, and 90-day legal warranty."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "order_id": {
                                "type": "integer",
                                "description": "Numeric order ID (e.g., 8, 17, 18).",
                            },
                            "customer_name": {
                                "type": "string",
                                "description": "Customer full or partial name (e.g., 'Ana Carolina', 'Pedro Henrique', 'Lucas Mendes').",
                            },
                            "email": {
                                "type": "string",
                                "description": "Customer email address.",
                            },
                            "phone": {
                                "type": "string",
                                "description": "Customer phone number.",
                            },
                            "tracking_code": {
                                "type": "string",
                                "description": "Shipping tracking code (e.g., 'BRJL5544332BR').",
                            },
                        },
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "calculate_payment_and_shipping",
                    "description": (
                        "Calculate exact PIX discount, credit card interest-free installment tiers (3x, 6x, 12x), "
                        "combined payment eligibility, and shipping cost/delivery time for a given amount or product and city."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "amount_brl": {
                                "type": "number",
                                "description": "Total purchase value in BRL (R$).",
                            },
                            "city": {
                                "type": "string",
                                "description": "Destination city (e.g., 'Campo Grande', 'Dourados', 'Três Lagoas', 'Corumbá', 'São Paulo').",
                            },
                            "is_promotional_price": {
                                "type": "boolean",
                                "description": "Whether amount_brl is already a discounted promotional price (since 5% PIX discount is non-cumulative).",
                            },
                        },
                        "required": ["amount_brl"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "search_store_policies",
                    "description": (
                        "Search the official Empório da Música Store Policies & Procedures Manual (`políticas_da_loja.pdf`) "
                        "for store address, opening hours, contact info, payment rules, return/exchange/regret policies, "
                        "shipping/tracking rules, warranty coverage, LGPD privacy, or out-of-scope accessory guidelines."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Topic or question to search in the policy manual (e.g., 'horário de funcionamento endereço', 'troca devolução arrependimento', 'formas de pagamento parcelamento', 'garantia', 'frete entrega').",
                            }
                        },
                        "required": ["query"],
                    },
                },
            },
        ]

    def calculate_payment_and_shipping(
        self,
        amount_brl: float,
        city: str | None = None,
        is_promotional_price: bool = False,
    ) -> dict[str, Any]:
        """Compute exact payment breakdown and shipping policy for an order value and destination city."""
        price = float(amount_brl)
        pix_price = price if is_promotional_price else round(price * 0.95, 2)

        # Build detailed installment table per Section 3.1
        valid_installments: list[dict[str, Any]] = []
        for n in range(1, 13):
            inst_val = round(price / n, 2)
            if n == 1:
                valid_installments.append({"installments": 1, "value_brl": price, "rule": "1x credit/debit"})
            elif n <= 3 and inst_val >= 50.0:
                valid_installments.append({"installments": n, "value_brl": inst_val, "rule": "Up to 3x (min R$ 50/installment)"})
            elif 4 <= n <= 6 and inst_val >= 80.0:
                valid_installments.append({"installments": n, "value_brl": inst_val, "rule": "4x-6x (min R$ 80/installment)"})
            elif 7 <= n <= 12 and inst_val >= 100.0:
                valid_installments.append({"installments": n, "value_brl": inst_val, "rule": "7x-12x (min R$ 100/installment)"})

        max_inst = valid_installments[-1] if valid_installments else {"installments": 1, "value_brl": price}

        # Shipping calculation per Section 5.1 & 5.2
        city_norm = normalize_text(city or "Campo Grande")
        is_cg = "campo grande" in city_norm

        if is_cg:
            shipping_info = {
                "region": "Região Metropolitana de Campo Grande/MS",
                "shipping_cost_brl": 0.0 if price >= 500.0 else 35.0,
                "free_shipping_applied": price >= 500.0,
                "delivery_method": "Motoboy próprio (cliente é contactado por telefone antes da entrega)",
                "estimated_delivery_time": "1 a 3 dias úteis",
                "insurance_included": True,
            }
        else:
            shipping_info = {
                "region": f"Outras Cidades ({city or 'Interior/Outros Estados'})",
                "shipping_cost_note": "Calculado automaticamente com base no CEP, peso e dimensões (instrumentos de grande porte como baterias, pianos digitais e contrabaixos podem exigir cotação individual).",
                "carriers": [
                    {"modality": "SEDEX (Correios)", "estimated_time": "2 a 5 dias úteis", "tracking": True, "insurance": "Incluído"},
                    {"modality": "Jadlog (.package)", "estimated_time": "3 a 8 dias úteis", "tracking": True, "insurance": "Incluído"},
                    {"modality": "PAC (Correios)", "estimated_time": "5 a 12 dias úteis", "tracking": True, "insurance": "Incluído"},
                ],
                "damage_policy": "Todos os envios possuem seguro. Em caso de avaria no transporte, recusar o recebimento no ato e contatar a loja imediatamente.",
            }

        return {
            "base_amount_brl": price,
            "is_promotional_price": is_promotional_price,
            "payment_methods": {
                "pix": {
                    "final_price_brl": pix_price,
                    "discount_applied": not is_promotional_price,
                    "explanation": (
                        "Preço já promocional — desconto de 5% do PIX não é cumulativo com promoções (Seção 6.2)."
                        if is_promotional_price
                        else f"R$ {pix_price:.2f} à vista no PIX (5% de desconto sobre R$ {price:.2f})."
                    ),
                },
                "debit_card": f"R$ {price:.2f} à vista (todas as bandeiras)",
                "boleto": f"R$ {price:.2f} à vista (compensação em até 3 dias úteis)",
                "credit_card": {
                    "max_option": f"Até {max_inst['installments']}x de R$ {max_inst['value_brl']:.2f} sem juros",
                    "all_valid_tiers": valid_installments,
                },
                "combined_payment_allowed": price > 2000.0,
                "combined_payment_rule": (
                    "Permitida combinação de formas de pagamento (ex.: PIX + Cartão) pois a compra é acima de R$ 2.000,00."
                    if price > 2000.0
                    else "Combinação de formas de pagamento (PIX + Cartão) disponível apenas para compras acima de R$ 2.000,00."
                ),
            },
            "shipping": shipping_info,
        }

    def execute_tool(self, name: str, arguments: dict[str, Any] | str) -> dict[str, Any]:
        """Dispatch a tool call by name and return a structured JSON-serializable dict."""
        if isinstance(arguments, str):
            try:
                args = json.loads(arguments) if arguments.strip() else {}
            except json.JSONDecodeError:
                args = {}
        else:
            args = dict(arguments or {})

        try:
            if name == "search_products":
                return self.db.search_products(
                    query=args.get("query"),
                    category=args.get("category"),
                    min_price=float(args["min_price"]) if args.get("min_price") is not None else None,
                    max_price=float(args["max_price"]) if args.get("max_price") is not None else None,
                    strings_type=args.get("strings_type"),
                    has_electronics=args.get("has_electronics"),
                    only_in_stock=bool(args.get("only_in_stock", False)),
                )
            elif name == "get_promotions":
                return self.db.get_promotions(
                    include_expired=bool(args.get("include_expired", False))
                )
            elif name == "lookup_order_or_customer":
                return self.db.lookup_order_or_customer(
                    order_id=int(args["order_id"]) if args.get("order_id") is not None else None,
                    customer_name=args.get("customer_name"),
                    email=args.get("email"),
                    phone=args.get("phone"),
                    tracking_code=args.get("tracking_code"),
                    reference_date=self.config.reference_date,
                )
            elif name == "calculate_payment_and_shipping":
                return self.calculate_payment_and_shipping(
                    amount_brl=float(args.get("amount_brl", 0.0)),
                    city=args.get("city"),
                    is_promotional_price=bool(args.get("is_promotional_price", False)),
                )
            elif name == "search_store_policies":
                return self.policy_kb.search(query=str(args.get("query", "")))
            else:
                return {"error": f"Unknown tool '{name}'."}
        except Exception as exc:
            return {"error": f"Tool execution error in '{name}': {exc}"}
