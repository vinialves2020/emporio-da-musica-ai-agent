"""ETL pipeline and relational SQLite engine for Empório da Música CSV datasets.

Performs automated data cleaning and anomaly detection on startup:
1. Parses JSON specifications (`specs`) into searchable attributes.
2. Normalizes customer phone numbers to digit-only strings for flexible lookup.
3. Reconciles active vs. expired promotions (`is_active == 1` vs `0`) and computes
   transparent promotional pricing + PIX 5% cash discount rules (non-cumulative per Section 6.2).
4. Detects and annotates catalog brand/model discrepancies in synthetic product rows
   (e.g., products 135-144 where product title and description mention different brands).
"""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from rapidfuzz import fuzz


def normalize_text(text: str) -> str:
    """Lowercase and strip accents from text for accent-insensitive search."""
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(text))
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


def digits_only(value: str | None) -> str:
    """Extract only numeric digits from phone or document strings."""
    if not value:
        return ""
    return re.sub(r"\D", "", str(value))


class StoreDatabase:
    """In-memory SQLite relational database with domain-aware query helpers."""

    CSV_FILES = {
        "categories": "desafio_tecnico_ai_eng - categories.csv",
        "customers": "desafio_tecnico_ai_eng - customers.csv",
        "orders": "desafio_tecnico_ai_eng - orders.csv",
        "order_items": "desafio_tecnico_ai_eng - order_items.csv",
        "products": "desafio_tecnico_ai_eng - products.csv",
        "promotions": "desafio_tecnico_ai_eng - promotions.csv",
    }

    # Known synthetic catalog anomalies in rows 135-144 where title brand != description brand
    SYNTHETIC_CATALOG_ANOMALIES = {
        135: "Note: Catalog title lists 'Music Man Bass 1X', while description references 'Fender Jazz Bass' (Alder/Ash).",
        136: "Note: Catalog title lists 'Ibanez Bass 2X', while description references 'Precision 4-string Bass'. Status: Discontinued.",
        137: "Note: Catalog title lists 'Yamaha Bass 3X', while description references 'Ibanez 5-string Active Bass' (specs list 4 strings).",
        139: "Note: Catalog title lists 'Bateria Acústica Yamaha Kit 1 Studio', while description references 'Pearl Export'.",
        140: "Note: Catalog title lists 'Bateria Acústica Pearl Kit 2 Studio', while description references 'Tama 100% Birch'.",
        142: "Note: Catalog title lists 'Teclado Sintetizador Korg Synth 1 Pro', while description references 'Roland 88-key SuperNATURAL' (specs list 61 keys).",
        144: "Note: Catalog title lists 'Teclado Sintetizador Roland Synth 3 Pro', while description references 'Yamaha 61-key Arranger'.",
    }

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.data_quality_report: list[str] = []
        self._load_and_clean_all()

    def _load_and_clean_all(self) -> None:
        """Load all CSV files, apply data cleaning & enrichment, and populate SQLite tables."""
        # 1. Categories
        cat_df = pd.read_csv(self.data_dir / self.CSV_FILES["categories"])
        cat_df["name_norm"] = cat_df["name"].apply(normalize_text)
        cat_df.to_sql("categories", self.conn, index=False, if_exists="replace")

        # 2. Customers
        cust_df = pd.read_csv(self.data_dir / self.CSV_FILES["customers"])
        cust_df["name_norm"] = cust_df["name"].apply(normalize_text)
        cust_df["phone_digits"] = cust_df["phone"].apply(digits_only)
        cust_df["email_norm"] = cust_df["email"].str.strip().str.lower()
        cust_df["city_norm"] = cust_df["city"].apply(normalize_text)

        # Check duplicate names or emails for data quality report
        dup_names = cust_df[cust_df.duplicated(subset=["name_norm"], keep=False)]
        if not dup_names.empty:
            self.data_quality_report.append(
                f"Detected customers sharing similar/identical names across different IDs "
                f"(e.g., Diego Castro IDs 13 & 47, Bruno Martins IDs 11 & 43). Disambiguation by email/phone enabled."
            )
        cust_df.to_sql("customers", self.conn, index=False, if_exists="replace")

        # 3. Promotions
        promo_df = pd.read_csv(self.data_dir / self.CSV_FILES["promotions"])
        promo_df["is_active"] = promo_df["is_active"].astype(int)
        promo_df.to_sql("promotions", self.conn, index=False, if_exists="replace")

        # Identify active promotions per product
        active_promos = (
            promo_df[promo_df["is_active"] == 1]
            .sort_values("discount_percent", ascending=False)
            .drop_duplicates(subset=["product_id"], keep="first")
            .set_index("product_id")
        )
        expired_promos = (
            promo_df[promo_df["is_active"] == 0]
            .sort_values("discount_percent", ascending=False)
            .drop_duplicates(subset=["product_id"], keep="first")
            .set_index("product_id")
        )

        # 4. Products
        prod_df = pd.read_csv(self.data_dir / self.CSV_FILES["products"])
        prod_df["price_brl"] = prod_df["price_brl"].astype(float)
        prod_df["stock_quantity"] = prod_df["stock_quantity"].astype(int)
        prod_df["name_norm"] = prod_df["name"].apply(normalize_text)
        prod_df["desc_norm"] = prod_df["description"].apply(normalize_text)

        # Parse JSON specs safely and enrich product records
        strings_list: list[str] = []
        electronics_list: list[str] = []
        color_list: list[str] = []
        specs_clean_list: list[str] = []
        has_active_promo_list: list[int] = []
        active_discount_pct_list: list[int] = []
        active_promo_name_list: list[str] = []
        promo_price_brl_list: list[float] = []
        pix_price_brl_list: list[float] = []
        expired_promo_info_list: list[str] = []
        catalog_note_list: list[str] = []

        for _, row in prod_df.iterrows():
            pid = int(row["product_id"])
            base_price = float(row["price_brl"])
            raw_specs = str(row.get("specs", "{}"))
            try:
                parsed_specs = json.loads(raw_specs)
            except json.JSONDecodeError:
                parsed_specs = {}

            strings_val = str(parsed_specs.get("strings", "")).lower()
            elec_val = str(parsed_specs.get("electronics", "")).lower()
            color_val = str(parsed_specs.get("color", ""))

            strings_list.append(strings_val)
            electronics_list.append(elec_val)
            color_list.append(color_val)
            specs_clean_list.append(json.dumps(parsed_specs, ensure_ascii=False))

            # Promotion calculation (Section 6.2: PIX 5% does NOT apply to already promotional prices)
            if pid in active_promos.index:
                disc_pct = int(active_promos.loc[pid, "discount_percent"])
                p_name = str(active_promos.loc[pid, "description"])
                final_promo_price = round(base_price * (1.0 - disc_pct / 100.0), 2)
                has_active_promo_list.append(1)
                active_discount_pct_list.append(disc_pct)
                active_promo_name_list.append(p_name)
                promo_price_brl_list.append(final_promo_price)
                # Non-cumulative: PIX price equals the promotional price when promo > 5%
                pix_price_brl_list.append(final_promo_price)
            else:
                has_active_promo_list.append(0)
                active_discount_pct_list.append(0)
                active_promo_name_list.append("")
                promo_price_brl_list.append(base_price)
                pix_price_brl_list.append(round(base_price * 0.95, 2))

            if pid in expired_promos.index:
                exp_pct = int(expired_promos.loc[pid, "discount_percent"])
                exp_name = str(expired_promos.loc[pid, "description"])
                expired_promo_info_list.append(f"{exp_name} ({exp_pct}% OFF - EXPIRED)")
            else:
                expired_promo_info_list.append("")

            catalog_note_list.append(self.SYNTHETIC_CATALOG_ANOMALIES.get(pid, ""))

        prod_df["strings_type"] = strings_list
        prod_df["has_electronics"] = electronics_list
        prod_df["color"] = color_list
        prod_df["specs_json"] = specs_clean_list
        prod_df["has_active_promo"] = has_active_promo_list
        prod_df["active_discount_percent"] = active_discount_pct_list
        prod_df["active_promo_name"] = active_promo_name_list
        prod_df["effective_price_brl"] = promo_price_brl_list
        prod_df["pix_price_brl"] = pix_price_brl_list
        prod_df["expired_promo_info"] = expired_promo_info_list
        prod_df["catalog_note"] = catalog_note_list

        prod_df.to_sql("products", self.conn, index=False, if_exists="replace")

        # 5. Orders & Order Items
        orders_df = pd.read_csv(self.data_dir / self.CSV_FILES["orders"])
        orders_df["tracking_code"] = orders_df["tracking_code"].fillna("").astype(str)
        orders_df["estimated_delivery"] = orders_df["estimated_delivery"].fillna("").astype(str)
        orders_df["notes"] = orders_df["notes"].fillna("").astype(str)
        orders_df.to_sql("orders", self.conn, index=False, if_exists="replace")

        items_df = pd.read_csv(self.data_dir / self.CSV_FILES["order_items"])
        items_df.to_sql("order_items", self.conn, index=False, if_exists="replace")

        self.data_quality_report.append(
            f"Loaded {len(prod_df)} products across {len(cat_df)} categories "
            f"(Categories 6 'Madeiras', 7 'Metais', and 8 'Cordas Orquestrais' currently have 0 products in CSV)."
        )
        self.data_quality_report.append(
            "Identified product #96 (Giannini GF-3D) with status='active' but stock_quantity=0 (treated as out-of-stock), "
            "product #136 (Ibanez Bass 2X) with status='discontinued' despite stock_quantity=13, "
            "and product #130 (Kala KA-ABP-CTG) with status='coming_soon' (and referenced in pending/historical orders #3 and #14)."
        )

    def get_Payment_Installments_Summary(self, price: float) -> dict[str, Any]:
        """Compute exact installment options according to Section 3.1 of Store Policy Manual.

        Rules from Section 3.1:
        - Up to 3x interest-free: no minimum installment (except below R$ 50.00).
        - 4x to 6x interest-free: minimum installment of R$ 80.00.
        - 7x to 12x interest-free: minimum installment of R$ 100.00.
        - Combined payment (e.g., PIX + card): allowed for purchases above R$ 2,000.00.
        """
        max_installments = 1
        for n in range(12, 0, -1):
            installment_val = price / n
            if n <= 3 and installment_val >= 50.0:
                max_installments = max(max_installments, n)
                break
            elif 4 <= n <= 6 and installment_val >= 80.0:
                max_installments = max(max_installments, n)
                break
            elif 7 <= n <= 12 and installment_val >= 100.0:
                max_installments = max(max_installments, n)
                break

        return {
            "max_interest_free_installments": max_installments,
            "installment_value_brl": round(price / max_installments, 2),
            "allows_combined_payment": price > 2000.0,
        }

    def search_products(
        self,
        query: str | None = None,
        category: str | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        strings_type: str | None = None,
        has_electronics: bool | None = None,
        only_in_stock: bool = False,
        include_discontinued: bool = True,
        limit: int = 15,
    ) -> dict[str, Any]:
        """Search and filter the product catalog with fuzzy matching, specs filtering, and promotion awareness."""
        cursor = self.conn.cursor()
        sql = """
            SELECT p.*, c.name AS category_name
            FROM products p
            LEFT JOIN categories c ON p.category_id = c.category_id
        """
        rows = [dict(r) for r in cursor.execute(sql).fetchall()]

        # 1. Category filter
        empty_category_warning = None
        if category:
            cat_norm = normalize_text(category)
            # Map common synonyms
            cat_synonyms = {
                "violao": "violoes",
                "violoes": "violoes",
                "acoustic guitar": "violoes",
                "guitarra": "guitarras",
                "electric guitar": "guitarras",
                "baixo": "baixos",
                "contrabaixo": "baixos",
                "bass": "baixos",
                "bateria": "baterias",
                "percussao": "baterias",
                "drums": "baterias",
                "teclado": "teclados",
                "piano": "teclados",
                "sintetizador": "teclados",
                "ukulele": "ukuleles",
                "sopro": "instrumentos de sopro",
                "saxofone": "instrumentos de sopro",
                "flauta": "instrumentos de sopro",
                "trompete": "instrumentos de sopro",
                "violino": "cordas orquestrais",
                "violoncelo": "cordas orquestrais",
                "orquestral": "cordas orquestrais",
            }
            mapped_cat = cat_synonyms.get(cat_norm, cat_norm)

            filtered_by_cat = [
                r
                for r in rows
                if mapped_cat in normalize_text(r["category_name"] or "")
                or cat_norm in normalize_text(r["category_name"] or "")
                or cat_norm in r["name_norm"]
            ]

            if not filtered_by_cat:
                # Check if it's one of the valid categories that happen to have 0 products in CSV
                all_cats = [
                    dict(c)
                    for c in cursor.execute("SELECT * FROM categories").fetchall()
                ]
                for c in all_cats:
                    if mapped_cat in c["name_norm"] or cat_norm in c["name_norm"]:
                        empty_category_warning = (
                            f"Category '{c['name']}' ({c['description']}) is registered in the store, "
                            f"but currently has 0 items available in the active catalog database."
                        )
            rows = filtered_by_cat

        # 2. Strings type filter ("nylon", "steel" / "aco", "7 cordas")
        if strings_type:
            st_norm = normalize_text(strings_type)
            if st_norm in ("aco", "steel"):
                rows = [r for r in rows if r["strings_type"] == "steel"]
            elif st_norm in ("nylon", "nailon"):
                rows = [r for r in rows if r["strings_type"] == "nylon"]
            elif "7" in st_norm:
                rows = [r for r in rows if "7 cordas" in r["name_norm"]]

        # 3. Electronics filter (eletroacústico vs acústico puro)
        if has_electronics is not None:
            target_elec = "yes" if has_electronics else "no"
            rows = [
                r
                for r in rows
                if r["has_electronics"] == target_elec
                or (has_electronics and "eletrico" in r["name_norm"])
            ]

        # 4. Stock and Status filters
        if not include_discontinued:
            rows = [r for r in rows if r["status"] != "discontinued"]

        if only_in_stock:
            rows = [
                r
                for r in rows
                if r["status"] == "active" and int(r["stock_quantity"]) > 0
            ]

        # 5. Price filters (check both list price and effective promotional price)
        if min_price is not None:
            rows = [
                r
                for r in rows
                if float(r["price_brl"]) >= min_price
                or float(r["effective_price_brl"]) >= min_price
            ]
        if max_price is not None:
            rows = [
                r
                for r in rows
                if float(r["price_brl"]) <= max_price
                or float(r["effective_price_brl"]) <= max_price
            ]

        # 6. Query text matching (exact substring + token overlap + RapidFuzz similarity)
        if query and query.strip():
            q_norm = normalize_text(query)
            stopwords = {
                "violao",
                "violoes",
                "guitarra",
                "baixo",
                "ukulele",
                "bateria",
                "teclado",
                "instrumento",
                "modelo",
                "marca",
                "de",
                "da",
                "do",
                "com",
                "para",
            }
            q_tokens = [t for t in q_norm.split() if t not in stopwords] or q_norm.split()

            # Check if there is an exact substring match in product name first
            exact_name_matches = [r for r in rows if q_norm in r["name_norm"]]
            if exact_name_matches and len(q_tokens) >= 2:
                rows = exact_name_matches
            else:
                scored_rows: list[tuple[float, dict[str, Any]]] = []
                for r in rows:
                    searchable = f"{r['name_norm']} {r['desc_norm']} {normalize_text(r['category_name'] or '')}"
                    exact_in_name = q_norm in r["name_norm"]
                    token_hits = sum(1 for t in q_tokens if t in searchable)
                    token_ratio = token_hits / max(len(q_tokens), 1)
                    fuzzy_name = fuzz.partial_ratio(q_norm, r["name_norm"]) / 100.0
                    fuzzy_full = fuzz.token_set_ratio(q_norm, searchable) / 100.0

                    score = (
                        (2.0 if exact_in_name else 0.0)
                        + (1.5 * token_ratio)
                        + (0.8 * fuzzy_name)
                        + (0.5 * fuzzy_full)
                    )
                    if exact_in_name or token_ratio >= 0.5 or fuzzy_name >= 0.72:
                        scored_rows.append((score, r))

                scored_rows.sort(key=lambda x: (-x[0], float(x[1]["effective_price_brl"])))
                rows = [r for _, r in scored_rows]
        else:
            # Sort by in-stock active first, then by price ascending
            rows.sort(
                key=lambda r: (
                    0 if (r["status"] == "active" and r["stock_quantity"] > 0) else 1,
                    float(r["effective_price_brl"]),
                )
            )

        total_matches = len(rows)
        results = [self._format_product_record(r) for r in rows[:limit]]

        # If a specific product was searched and is out of stock or discontinued, suggest alternatives
        alternatives: list[dict[str, Any]] = []
        if results and len(results) <= 3:
            first = results[0]
            if not first["is_available_now"]:
                alt_cursor = self.conn.cursor()
                alt_rows = [
                    dict(a)
                    for a in alt_cursor.execute(
                        """
                        SELECT p.*, c.name AS category_name
                        FROM products p
                        LEFT JOIN categories c ON p.category_id = c.category_id
                        WHERE p.category_id = ?
                          AND p.product_id != ?
                          AND p.status = 'active'
                          AND p.stock_quantity > 0
                        ORDER BY ABS(p.price_brl - ?) ASC
                        LIMIT 3
                        """,
                        (first["category_id"], first["product_id"], first["list_price_brl"]),
                    ).fetchall()
                ]
                alternatives = [self._format_product_record(a) for a in alt_rows]

        return {
            "total_matches": total_matches,
            "returned_count": len(results),
            "empty_category_warning": empty_category_warning,
            "products": results,
            "suggested_alternatives_for_unavailable": alternatives,
        }

    def _format_product_record(self, r: dict[str, Any]) -> dict[str, Any]:
        """Format a raw product database row into a rich, policy-compliant dictionary."""
        list_price = float(r["price_brl"])
        effective_price = float(r["effective_price_brl"])
        pix_price = float(r["pix_price_brl"])
        has_promo = bool(r["has_active_promo"])
        stock_qty = int(r["stock_quantity"])
        status = str(r["status"])

        is_available = status == "active" and stock_qty > 0
        if status == "discontinued":
            availability_label = "Discontinued (No longer part of catalog - offer equivalent models)"
        elif status == "coming_soon":
            availability_label = "Coming Soon (Pre-launch / Not yet in regular stock)"
        elif stock_qty <= 0:
            availability_label = "Temporarily Out of Stock (0 units)"
        else:
            availability_label = f"In Stock ({stock_qty} units available)"

        installments = self.get_Payment_Installments_Summary(effective_price)

        record: dict[str, Any] = {
            "product_id": int(r["product_id"]),
            "name": r["name"],
            "category_id": int(r["category_id"]),
            "category_name": r.get("category_name", ""),
            "status": status,
            "stock_quantity": stock_qty,
            "is_available_now": is_available,
            "availability_summary": availability_label,
            "list_price_brl": list_price,
            "has_active_promotion": has_promo,
            "effective_price_brl": effective_price,
            "pix_price_brl": pix_price,
            "payment_options": {
                "pix_cash_brl": pix_price,
                "pix_note": (
                    "Promotional price already applied (5% PIX discount is non-cumulative with promotions per Section 6.2)"
                    if has_promo
                    else "Includes 5% PIX cash discount off list price"
                ),
                "max_interest_free_installments": f"Até {installments['max_interest_free_installments']}x de R$ {installments['installment_value_brl']:.2f} sem juros no Cartão de Crédito",
                "allows_combined_payment": installments["allows_combined_payment"],
            },
            "description": r["description"],
            "specs": json.loads(r["specs_json"]) if r.get("specs_json") else {},
        }

        if has_promo:
            record["active_promotion"] = {
                "campaign_name": r["active_promo_name"],
                "discount_percent": int(r["active_discount_percent"]),
                "original_price_brl": list_price,
                "promotional_price_brl": effective_price,
                "policy_reminder": "Always present original price, discount percentage, and promotional price together (Section 6.2).",
            }

        if r.get("expired_promo_info"):
            record["expired_promotion_history"] = r["expired_promo_info"]

        if r.get("catalog_note"):
            record["catalog_note"] = r["catalog_note"]

        return record

    def get_promotions(self, include_expired: bool = False) -> dict[str, Any]:
        """Retrieve active (and optionally expired) promotions joined with product details."""
        cursor = self.conn.cursor()
        sql = """
            SELECT pr.promotion_id, pr.product_id, pr.discount_percent,
                   pr.description AS campaign_name, pr.is_active,
                   p.name AS product_name, p.price_brl AS original_price_brl,
                   p.stock_quantity, p.status AS product_status,
                   c.name AS category_name
            FROM promotions pr
            JOIN products p ON pr.product_id = p.product_id
            LEFT JOIN categories c ON p.category_id = c.category_id
        """
        if not include_expired:
            sql += " WHERE pr.is_active = 1"
        sql += " ORDER BY pr.is_active DESC, pr.discount_percent DESC"

        rows = [dict(r) for r in cursor.execute(sql).fetchall()]
        active_list = []
        expired_list = []

        for r in rows:
            orig = float(r["original_price_brl"])
            disc = int(r["discount_percent"])
            promo_price = round(orig * (1.0 - disc / 100.0), 2)
            item = {
                "promotion_id": int(r["promotion_id"]),
                "product_id": int(r["product_id"]),
                "product_name": r["product_name"],
                "category_name": r["category_name"],
                "campaign_name": r["campaign_name"],
                "discount_percent": disc,
                "original_price_brl": orig,
                "promotional_price_brl": promo_price,
                "is_active": bool(r["is_active"]),
                "stock_quantity": int(r["stock_quantity"]),
                "product_status": r["product_status"],
            }
            if r["is_active"]:
                active_list.append(item)
            else:
                expired_list.append(item)

        result: dict[str, Any] = {
            "active_promotions_count": len(active_list),
            "active_promotions": active_list,
            "policy_rules": (
                "Promotions are non-cumulative (5% PIX discount does not stack on promotional prices). "
                "Subject to stock availability (no rain check). Must display original price + % discount + promotional price."
            ),
        }
        if include_expired:
            result["expired_promotions_count"] = len(expired_list)
            result["expired_promotions"] = expired_list
        return result

    def lookup_order_or_customer(
        self,
        order_id: int | None = None,
        customer_name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        tracking_code: str | None = None,
        reference_date: date | None = None,
    ) -> dict[str, Any]:
        """Look up orders and customer records with full item breakdown and return eligibility."""
        ref_date = reference_date or date(2026, 3, 23)
        cursor = self.conn.cursor()

        matched_customer_ids: set[int] = set()
        matched_order_ids: set[int] = set()

        if order_id is not None:
            matched_order_ids.add(int(order_id))

        if tracking_code and tracking_code.strip():
            tc_clean = tracking_code.strip().upper()
            rows = cursor.execute(
                "SELECT order_id, customer_id FROM orders WHERE UPPER(tracking_code) = ?",
                (tc_clean,),
            ).fetchall()
            for r in rows:
                matched_order_ids.add(int(r["order_id"]))
                matched_customer_ids.add(int(r["customer_id"]))

        if email and email.strip():
            em_clean = email.strip().lower()
            rows = cursor.execute(
                "SELECT customer_id FROM customers WHERE email_norm = ?", (em_clean,)
            ).fetchall()
            for r in rows:
                matched_customer_ids.add(int(r["customer_id"]))

        if phone and phone.strip():
            ph_digits = digits_only(phone)
            if len(ph_digits) >= 4:
                rows = cursor.execute(
                    "SELECT customer_id FROM customers WHERE phone_digits LIKE ?",
                    (f"%{ph_digits}%",),
                ).fetchall()
                for r in rows:
                    matched_customer_ids.add(int(r["customer_id"]))

        if customer_name and customer_name.strip():
            cname_norm = normalize_text(customer_name)
            all_custs = cursor.execute("SELECT * FROM customers").fetchall()
            for c in all_custs:
                if (
                    cname_norm in c["name_norm"]
                    or fuzz.partial_ratio(cname_norm, c["name_norm"]) >= 85
                ):
                    matched_customer_ids.add(int(c["customer_id"]))

        # If we found order IDs first, include their customers
        if matched_order_ids:
            placeholders = ",".join("?" for _ in matched_order_ids)
            rows = cursor.execute(
                f"SELECT customer_id FROM orders WHERE order_id IN ({placeholders})",
                tuple(matched_order_ids),
            ).fetchall()
            for r in rows:
                matched_customer_ids.add(int(r["customer_id"]))

        # Fetch customer profiles
        customers_found: list[dict[str, Any]] = []
        if matched_customer_ids:
            placeholders = ",".join("?" for _ in matched_customer_ids)
            c_rows = cursor.execute(
                f"SELECT * FROM customers WHERE customer_id IN ({placeholders})",
                tuple(matched_customer_ids),
            ).fetchall()
            for c in c_rows:
                customers_found.append(
                    {
                        "customer_id": int(c["customer_id"]),
                        "name": c["name"],
                        "phone": c["phone"],
                        "email": c["email"],
                        "city": c["city"],
                        "is_campo_grande_metro": c["city_norm"] == "campo grande",
                    }
                )

            # Also get all orders for matched customers if no specific order_id was locked
            if order_id is None:
                o_rows = cursor.execute(
                    f"SELECT order_id FROM orders WHERE customer_id IN ({placeholders})",
                    tuple(matched_customer_ids),
                ).fetchall()
                for o in o_rows:
                    matched_order_ids.add(int(o["order_id"]))

        # Fetch full order details
        orders_found: list[dict[str, Any]] = []
        if matched_order_ids:
            placeholders = ",".join("?" for _ in sorted(matched_order_ids))
            o_rows = cursor.execute(
                f"""
                SELECT o.*, c.name AS customer_name, c.city AS customer_city,
                       c.email AS customer_email, c.phone AS customer_phone
                FROM orders o
                LEFT JOIN customers c ON o.customer_id = c.customer_id
                WHERE o.order_id IN ({placeholders})
                ORDER BY o.order_date DESC
                """,
                tuple(sorted(matched_order_ids)),
            ).fetchall()

            for o in o_rows:
                oid = int(o["order_id"])
                item_rows = cursor.execute(
                    """
                    SELECT oi.quantity, p.product_id, p.name AS product_name,
                           p.price_brl AS catalog_unit_price_brl, c.name AS category_name
                    FROM order_items oi
                    LEFT JOIN products p ON oi.product_id = p.product_id
                    LEFT JOIN categories c ON p.category_id = c.category_id
                    WHERE oi.order_id = ?
                    """,
                    (oid,),
                ).fetchall()

                items_list = [
                    {
                        "product_id": int(ir["product_id"]),
                        "product_name": ir["product_name"],
                        "category": ir["category_name"],
                        "quantity": int(ir["quantity"]),
                        "catalog_unit_price_brl": float(ir["catalog_unit_price_brl"]),
                    }
                    for ir in item_rows
                ]

                eligibility = self.evaluate_return_or_exchange_eligibility(
                    order_row=dict(o), reference_date=ref_date
                )

                orders_found.append(
                    {
                        "order_id": oid,
                        "customer_id": int(o["customer_id"]),
                        "customer_name": o["customer_name"],
                        "customer_city": o["customer_city"],
                        "order_date": o["order_date"],
                        "status": o["status"],
                        "total_brl": float(o["total_brl"]),
                        "payment_method": o["payment_method"],
                        "tracking_code": o["tracking_code"] or None,
                        "estimated_delivery": o["estimated_delivery"] or None,
                        "notes": o["notes"] or None,
                        "items": items_list,
                        "return_and_warranty_eligibility": eligibility,
                    }
                )

        disambiguation_needed = len(customers_found) > 1 and order_id is None
        return {
            "found": bool(customers_found or orders_found),
            "reference_date_used": ref_date.isoformat(),
            "disambiguation_notice": (
                "Multiple customer profiles matched this name. Please verify the customer's email, phone, or city before sharing sensitive details."
                if disambiguation_needed
                else None
            ),
            "customers": customers_found,
            "orders": orders_found,
        }

    def evaluate_return_or_exchange_eligibility(
        self, order_row: dict[str, Any], reference_date: date
    ) -> dict[str, Any]:
        """Evaluate an order against Section 4 (Returns/Exchanges) and Section 8 (Warranty)."""
        status = str(order_row.get("status", "")).lower()
        order_date_str = str(order_row.get("order_date", ""))
        est_delivery_str = str(order_row.get("estimated_delivery", ""))

        def _parse_d(s: str) -> date | None:
            try:
                return datetime.strptime(s, "%Y-%m-%d").date()
            except ValueError:
                return None

        order_d = _parse_d(order_date_str)
        delivery_d = _parse_d(est_delivery_str)

        if status == "cancelled":
            return {
                "can_return_for_regret_7d": False,
                "can_exchange_for_preference_7d": False,
                "can_exchange_for_defect_store_30d": False,
                "under_legal_warranty_90d": False,
                "explanation": f"O Pedido #{order_row['order_id']} já consta com status 'cancelado' ({order_row.get('notes') or 'sem motivo registrado'}).",
            }

        if status in ("pending", "confirmed"):
            return {
                "can_return_for_regret_7d": True,
                "can_exchange_for_preference_7d": True,
                "can_exchange_for_defect_store_30d": True,
                "under_legal_warranty_90d": True,
                "explanation": (
                    f"O Pedido #{order_row['order_id']} está com status '{status}' e ainda não foi entregue. "
                    "O cliente pode solicitar o cancelamento/alteração imediata ou exercer o Direito de Arrependimento (Seção 4.1 — CDC) "
                    "em até 7 dias corridos após o recebimento."
                ),
            }

        if status == "shipped":
            return {
                "can_return_for_regret_7d": True,
                "can_exchange_for_preference_7d": True,
                "can_exchange_for_defect_store_30d": True,
                "under_legal_warranty_90d": True,
                "explanation": (
                    f"O Pedido #{order_row['order_id']} está em trânsito ('shipped', rastreio: {order_row.get('tracking_code')}, "
                    f"previsão de entrega: {est_delivery_str}). Assim que receber o produto, você terá 7 dias corridos para exercer o "
                    "Direito de Arrependimento (frete de devolução por conta da loja e reembolso em até 10 dias úteis) ou Troca por Preferência."
                ),
            }

        # Delivered orders: compare against delivery_d (for regret/legal warranty) and order_d (for 30-day store defect exchange)
        days_since_delivery = (reference_date - delivery_d).days if delivery_d else 999
        days_since_purchase = (reference_date - order_d).days if order_d else 999

        regret_ok = 0 <= days_since_delivery <= 7
        pref_ok = 0 <= days_since_delivery <= 7
        defect_store_ok = 0 <= days_since_purchase <= 30
        legal_warranty_ok = 0 <= days_since_delivery <= 90

        return {
            "reference_date": reference_date.isoformat(),
            "order_date": order_date_str,
            "delivery_date": est_delivery_str,
            "days_since_purchase": days_since_purchase,
            "days_since_delivery": days_since_delivery,
            "can_return_for_regret_7d": regret_ok,
            "can_exchange_for_preference_7d": pref_ok,
            "can_exchange_for_defect_store_30d": defect_store_ok,
            "under_legal_warranty_90d": legal_warranty_ok,
            "explanation": (
                f"Entregue em {est_delivery_str} (há {days_since_delivery} dias) e comprado em {order_date_str} (há {days_since_purchase} dias) "
                f"considerando a data de referência {reference_date.isoformat()}. "
                f"Arrependimento / Troca por Preferência (7 dias corridos do recebimento): {'ELEGÍVEL' if regret_ok else 'PRAZO EXPIRADO (>7 dias corridos após o recebimento)'}. "
                f"Troca Direta na Loja por Defeito (30 dias corridos da compra): {'ELEGÍVEL' if defect_store_ok else 'PRAZO EXPIRADO (>30 dias da compra; acionar Garantia do Fabricante com intermediação da loja)'}. "
                f"Garantia Legal CDC (90 dias do recebimento): {'VIGENTE' if legal_warranty_ok else 'EXPIRADA (>90 dias do recebimento; verificar Garantia do Fabricante de 6m a 2 anos)'}."
            ),
        }
