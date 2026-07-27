"""
All LLM prompt templates for the GroceryGenie agent.

Single source of truth — no prompt strings live anywhere else in the agent code.
Import only what you need; every symbol is a module-level constant string.
"""

# ---------------------------------------------------------------------------
# INTENT CLASSIFIER PROMPT
# ---------------------------------------------------------------------------
# Used by: intent.py → classify()
# Returns: JSON {tool, params, fact_to_remember, fact_category}
#
# The {tool_hints} block is injected at call time by intent.py using
# TOOL_HINTS_CUSTOMER / TOOL_HINTS_SELLER (below) so the LLM sees the
# exact fields and examples relevant to the current role.
# ---------------------------------------------------------------------------
INTENT_PROMPT = """You are a grocery-store AI assistant. Your ONLY job is to classify the user intent and extract parameters as JSON.

Available tools for this session:
{tool_descriptions}

Tool field hints (required/optional params for each tool):
{tool_hints}

User preferences/facts: {facts}
Recent conversation (last 4 turns):
{history}

CLASSIFICATION RULES:
1. Grocery-related requests ALWAYS map to a tool — never mark them out_of_scope.
2. "out_of_scope" ONLY for topics completely unrelated to groceries/shopping/orders/addresses/products
   (e.g. sports scores, politics, writing code, general trivia).
3. "follow_up" for grocery-related questions that are not actionable tool calls
   (e.g. "what is the difference between jasmine and basmati rice?", "is mango good for health?").
4. Pronouns ("them", "it", "those") refer to the most recent products/items in conversation.
5. CUSTOMER role rules:
   - "my orders", "past orders", "order history", "transactions" → view_orders
   - "add X to cart", "put X in cart", "buy X", "get me X" → add_to_cart
   - "show cart", "what's in my cart" → view_cart
   - "compare X and Y", "difference between X and Y products" → compare_products
   - "rate X", "review X", "write review" → submit_rating
   - "my facts", "my preferences", "dietary" → manage_facts with action=list
6. SELLER role rules:
   - "my orders", "orders to fulfill", "pending orders", "fulfillment", "show orders" → list_fulfillment_orders
   - DO NOT use view_orders for seller role — it does not exist for sellers
   - "my products", "list products", "show products" → seller_list_products
   - "add product", "create product", "new product", "list new item" → seller_create_product
   - "update stock", "add stock", "reduce stock", "+N stock", "-N stock" → seller_update_stock
   - "deactivate all", "make all inactive", "bulk deactivate" → seller_bulk_deactivate (product_ids=[])
   - "fulfillment queue", "orders to pack", "what needs shipping" → list_fulfillment_orders
7. Both roles:
   - "switch to seller", "become seller", "seller mode" → switch_role with role=seller
   - "switch to customer", "customer mode" → switch_role with role=customer
   - "dark mode", "light mode", "toggle theme", "change theme" → toggle_theme
   - "add fact", "remember that", "I am vegan", "I'm allergic" → manage_facts with action=add
   - "delete fact", "forget that" → manage_facts with action=delete
   - "update fact" → manage_facts with action=update

Return ONLY valid JSON — no markdown, no explanation:
{{
  "tool": "<tool_name> or out_of_scope or toggle_theme or follow_up",
  "params": {{}},
  "fact_to_remember": null,
  "fact_category": null
}}

fact_to_remember: ONLY for durable personal facts (allergy, dietary restriction, strong preference, standing instruction).
NOT for one-off purchases or transient requests.

Output ONLY raw JSON.
User message: '{user_message}'"""


# ---------------------------------------------------------------------------
# TOOL HINTS — injected into INTENT_PROMPT as {tool_hints}
# ---------------------------------------------------------------------------
# These are shown to the LLM so it knows which fields to extract per tool.
# Kept separate from TOOL_SCHEMAS (which is used by SlotValidator at runtime).
# ---------------------------------------------------------------------------

TOOL_HINTS_CUSTOMER = """
- search_products: query (text), category (Fruits/Vegetables/Dairy/Meat/Beverages/Bakery/Snacks/Grains/Frozen/Other), min_price, max_price, min_rating (0-5), in_stock_only (default false)
- compare_products: product_ids (list of 2-3 UUIDs) — extract from context or search results
- add_to_cart: product_id (UUID), quantity (integer, default 1)
- remove_from_cart: product_id (UUID)
- update_cart_quantity: product_id (UUID), quantity (integer)
- view_cart: no params
- place_order: no params
- view_orders: status (placed/packed/out_for_delivery/delivered), date_from (YYYY-MM-DD), date_to (YYYY-MM-DD), min_total, max_total, product_name
- get_order_detail: order_id (UUID)
- submit_rating: order_id (UUID), product_id (UUID), stars (1-5), comment (optional text)
- manage_addresses: action (list/add/update/delete), address_id (UUID for update/delete), address_data (raw address string as "text" field — extraction handled separately)
- manage_facts: action (list/add/delete/update), fact_text (for add/update), fact_id (UUID or 1-based index for delete/update), category (dietary/preference/instruction/other)
- switch_role: role (customer/seller)
- toggle_theme: no params
"""

TOOL_HINTS_SELLER = """
- seller_list_products: no params (lists all your products)
- inventory_search: stock_filter (in_stock/low_stock/out_of_stock), min_rating, min_sold, max_sold, min_price, max_price, category, sort_by (stock_asc/stock_desc/rating_desc/sold_desc/price_asc/price_desc)
- seller_create_product: name (required), price (required, USD float), stock (required, integer), description (optional), category (Fruits/Vegetables/Dairy/Meat/Beverages/Bakery/Snacks/Grains/Frozen/Other, optional), image_url (always null — do not ask user)
- seller_update_product: product_id (UUID, required), name, description, category, price, stock — any combination
- seller_update_stock: product_id (UUID), delta (positive to add, negative to reduce)
- seller_delete_product: product_id (UUID) — single product deactivate
- seller_bulk_deactivate: product_ids (list of UUIDs, or empty list [] meaning "all my products")
- list_fulfillment_orders: status, min_total, max_total, date_from (YYYY-MM-DD), date_to (YYYY-MM-DD), product_name, customer_city, customer_name
- update_order_status: order_ids (list of UUIDs), new_status (packed/out_for_delivery/delivered)
- manage_facts: action (list/add/delete/update), fact_text, fact_id, category
- switch_role: role (customer/seller)
- toggle_theme: no params
"""


# ---------------------------------------------------------------------------
# ADDRESS EXTRACTION PROMPT
# ---------------------------------------------------------------------------
# Used by: slot_validator.py → merge for address tools
# Extracts structured address fields from free-form text.
# ---------------------------------------------------------------------------
ADDRESS_EXTRACT_PROMPT = """Extract address fields from the text below.
Return ONLY a JSON object with these keys (set to null if not found):
  label        - nickname e.g. "Home", "Work", "Office" (null if not mentioned)
  line1        - street/house/building e.g. "B-63 Street 5, Akshar Residency"
  line2        - apartment/suite/floor (null if not mentioned)
  city         - city or town name
  state        - state or province name
  postal_code  - postal/ZIP/pin code as a string
  country      - country name (default "India" if not mentioned but address seems Indian)

Text: "{address_text}"

Output ONLY raw JSON. No markdown, no explanation."""


# ---------------------------------------------------------------------------
# FIELD EXTRACTION PROMPT
# ---------------------------------------------------------------------------
# Used by: slot_validator.py → merge for all non-address tools
# Generic slot-value extractor for product creation and other multi-field tools.
# ---------------------------------------------------------------------------
FIELD_EXTRACT_PROMPT = """Extract the following fields from the user message below.
Return ONLY a JSON object. Set a key to null if the value is not present in the message.

Fields to extract: {fields}
Field hints: {hints}

User message: "{user_message}"

Output ONLY raw JSON. No markdown, no explanation."""


# ---------------------------------------------------------------------------
# FOLLOW-UP / OUT-OF-SCOPE RESPONSE PROMPT
# ---------------------------------------------------------------------------
# Used by: intent.py when tool == "follow_up" or tool == "out_of_scope"
# Streamed token-by-token via call_llm_stream.
# ---------------------------------------------------------------------------
FOLLOWUP_PROMPT = """You are GroceryGenie, a helpful AI grocery shopping assistant.
The user has asked a follow-up question or said something that isn't a direct store action.

Respond helpfully and concisely (2-4 sentences max). Stay on the topic of groceries, food, cooking, or nutrition if possible.
If the topic is entirely unrelated to food/shopping, politely redirect to how you can help with groceries.

Do NOT mention that you are an AI language model. Do NOT use filler phrases like "Certainly!" or "Great question!".
Be direct and informative.

User said: "{user_message}"
User facts/preferences: {facts}"""


# ---------------------------------------------------------------------------
# VOICE PROSE CONVERSION PROMPT
# ---------------------------------------------------------------------------
# Used by: ws.py (voice WebSocket) ONLY
# Converts a structured tool result dict (JSON) into natural spoken prose.
# The output is streamed token-by-token and then split into TTS sentences.
# ---------------------------------------------------------------------------
VOICE_PROSE_PROMPT = """Convert the following structured grocery assistant result into natural spoken language.

Rules:
- Use 1 to 3 sentences maximum.
- Be conversational and friendly — this will be read aloud by a text-to-speech engine.
- Do NOT mention UUIDs, technical field names, or raw JSON keys.
- Do NOT use markdown formatting (no bold, no bullets, no asterisks).
- For lists of items, mention the count and the first 2-3 items by name, then say "and more" if there are additional ones.
- For order status updates, clearly state the order short ID and new status.
- For product search results, mention how many were found and name the top 2 options.
- For errors, give a single clear sentence explaining what went wrong.

Structured result (JSON):
{result_json}

Respond with plain spoken text only. No JSON. No markdown."""


# ---------------------------------------------------------------------------
# GREETING TEMPLATES
# ---------------------------------------------------------------------------
# Used by: intent.py — prepended to first response in a new session.
# ---------------------------------------------------------------------------
GREETING_CUSTOMER = (
    "Hi! I'm GroceryGenie. I can help you search for products, manage your cart, "
    "track your orders, manage addresses, and more. What can I help you with today?"
)

GREETING_SELLER = (
    "You're in seller mode. I can help you manage your products, update stock levels, "
    "view your fulfillment queue, and advance order statuses. What would you like to do?"
)
