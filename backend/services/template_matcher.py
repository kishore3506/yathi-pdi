import re
from typing import Dict, Any, List, Optional

try:
    from ..database import CUSTOMER_CATALOG, get_db
    from .stg_report import TEMPLATE_NAME as STG_TEMPLATE_NAME
    from .ksb_report import TEMPLATE_NAME as KSB_TEMPLATE_NAME
    from .crompton_report import TEMPLATE_NAME as CROMPTON_TEMPLATE_NAME
except (ImportError, ValueError):
    from database import CUSTOMER_CATALOG, get_db
    from services.stg_report import TEMPLATE_NAME as STG_TEMPLATE_NAME
    from services.ksb_report import TEMPLATE_NAME as KSB_TEMPLATE_NAME
    from services.crompton_report import TEMPLATE_NAME as CROMPTON_TEMPLATE_NAME

CATALOG_CUSTOMERS = {
    label.casefold(): customer["name"]
    for customer in CUSTOMER_CATALOG
    for label in (customer["name"], customer["code"])
}

SUPPORTED_CUSTOMERS = {
    "havells": "Havells",
    "hil": "Havells",
    "crompton": "Crompton",
    "cgcel": "Crompton",
    "kbs": "KSB",
    "ksb": "KSB",
    "kbl": "KSB",
    "koel": "KOEL",
    "kirloskar": "KOEL"
}

class TemplateMatcher:
    def __init__(self):
        pass

    def normalize_customer(self, company_str: Optional[str]) -> Optional[str]:
        if not company_str:
            return None
        norm = company_str.strip().lower()
        if norm in CATALOG_CUSTOMERS:
            return CATALOG_CUSTOMERS[norm]
        words = re.findall(r'[a-z0-9]+', norm)
        
        # Exact word match
        for key, canonical in SUPPORTED_CUSTOMERS.items():
            if key in words or key == norm:
                return canonical
        # Substring match if clear
        if "havell" in norm: return "Havells"
        if "crompton" in norm: return "Crompton"
        if "kbs" in norm or "ksb" in norm: return "KSB"
        if "koel" in norm: return "KOEL"
        
        return None

    def normalize_product_type(self, ptype: Optional[str]) -> str:
        if not ptype:
            return ""
        return ptype.strip().lower()

    def match_template(
        self,
        company_name: str,
        product_type: str,
        product_model: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Deterministic matching engine for Yathi Pumps:
        1. Recognize the customer in the catalog.
        2. Query registered active templates for that customer.
        3. Match product_type (exact or normalized keyword).
        """
        canonical_customer = self.normalize_customer(company_name)
        if not canonical_customer:
            return {
                "matched": False,
                "company_supported": False,
                "template_id": None,
                "template_name": None,
                "message": f"Customer '{company_name}' is missing from the PDI customer catalog.",
                "available_templates": []
            }

        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("SELECT id, name FROM companies WHERE LOWER(name) = LOWER(?)", (canonical_customer,))
        comp = cursor.fetchone()
        if not comp:
            conn.close()
            return {
                "matched": False,
                "company_supported": True,
                "template_id": None,
                "template_name": None,
                "message": f"Customer '{canonical_customer}' not configured in database.",
                "available_templates": []
            }
        
        company_id = comp["id"]
        
        cursor.execute("""
            SELECT id, product_type, product_model, template_name, file_path, primary_sheet, is_active
            FROM pdi_templates
            WHERE company_id = ? AND is_active = 1
        """, (company_id,))
        templates = [dict(row) for row in cursor.fetchall()]
        conn.close()

        if canonical_customer == "STG":
            templates = [template for template in templates if template["template_name"] == STG_TEMPLATE_NAME]
        if canonical_customer == "KSB":
            templates = [template for template in templates if template["template_name"] == KSB_TEMPLATE_NAME] or templates
        if canonical_customer == "Crompton":
            templates = [template for template in templates if template["template_name"] == CROMPTON_TEMPLATE_NAME] or templates

        if not templates:
            return {
                "matched": False,
                "company_supported": True,
                "template_id": None,
                "template_name": None,
                "message": f"No active PDI templates registered for {canonical_customer}. Please upload one in Template Management.",
                "available_templates": []
            }

        p_norm = self.normalize_product_type(product_type)

        if canonical_customer == "Havells":
            candidates = [
                template for template in templates
                if self.normalize_product_type(template["product_type"]) == "surface pump"
            ]
            if not candidates:
                return {
                    "matched": False,
                    "company_supported": True,
                    "template_id": None,
                    "template_name": None,
                    "message": "The registered Havells Surface Pump PDI template is unavailable.",
                    "available_templates": templates
                }
        else:
            exact_matches = [
                template for template in templates
                if self.normalize_product_type(template["product_type"]) == p_norm
            ]

            if not exact_matches:
                keyword_matches = []
                for template in templates:
                    template_product_type = self.normalize_product_type(template["product_type"])
                    if template_product_type in p_norm or p_norm in template_product_type:
                        keyword_matches.append(template)
                    elif "pump" in p_norm and "pump" in template_product_type:
                        keyword_matches.append(template)
                candidates = keyword_matches if keyword_matches else templates
            else:
                candidates = exact_matches

        if len(candidates) >= 1:
            best = candidates[0]
            return {
                "matched": True,
                "company_supported": True,
                "template_id": best["id"],
                "template_name": best["template_name"],
                "product_type": best["product_type"],
                "customer_name": canonical_customer,
                "primary_sheet": best["primary_sheet"],
                "message": f"Successfully matched {canonical_customer} template '{best['template_name']}'.",
                "available_templates": candidates
            }
        else:
            return {
                "matched": False,
                "company_supported": True,
                "template_id": None,
                "template_name": None,
                "message": f"No matching template for '{product_type}'.",
                "available_templates": templates
            }
