"""Knowledge corpus text (`seed-data-spec.md` section 11): supplier notes, operational product
notes and the app glossary. Written from templates with seeded variation, no model involved.

Supplier facts are read from the catalogue, so every number in the text matches the supplier
table. Plain Indian English, no dashes, no locations. Text only: embeddings arrive in Prompt 7.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from seed.model import Catalog, SupplierSpec, make_uuid, tenant_uuid
from seed.rng import stream

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
CHUNK_TOKENS = 400
OVERLAP_TOKENS = 50


@dataclass
class Doc:
    doc_type: str
    title: str
    source_ref: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    tenant_scoped: bool = True


def tokens_of(text: str) -> int:
    """Rough token count: about 1.3 tokens per English word."""
    return max(1, round(len(text.split()) * 1.3))


def chunk_text(text: str, target: int = CHUNK_TOKENS, overlap: int = OVERLAP_TOKENS) -> list[str]:
    """Split at sentence ends into chunks of about `target` tokens, repeating `overlap` tokens."""
    sentences = [s.strip() for s in re.split(r"(?<=[.])\s+", text.strip()) if s.strip()]
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for sentence in sentences:
        n = tokens_of(sentence)
        if current and size + n > target:
            chunks.append(" ".join(current))
            tail: list[str] = []
            used = 0
            for prev in reversed(current):
                if used + tokens_of(prev) > overlap:
                    break
                tail.insert(0, prev)
                used += tokens_of(prev)
            current, size = tail, used
        current.append(sentence)
        size += n
    if current:
        chunks.append(" ".join(current))
    return chunks


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _pick(rng: np.random.Generator, options: tuple[str, ...]) -> str:
    return options[int(rng.integers(0, len(options)))]


def _days(numbers: list[int]) -> str:
    names = [WEEKDAYS[n - 1] for n in numbers]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _rupees(paise_value: int | None) -> str:
    if not paise_value:
        return "not set"
    return "₹" + f"{paise_value // 100:,}"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def supplier_docs(catalog: Catalog, rng: np.random.Generator) -> list[Doc]:
    docs: list[Doc] = []
    medical = catalog.profile.is_medical
    for s in catalog.suppliers:
        if s.planted == "cash_vendor":
            continue
        docs.append(_terms_doc(s, rng))
        docs.append(_delivery_doc(s, rng))
        docs.append(_festival_doc(s, rng, medical))
    return docs


def _terms_doc(s: SupplierSpec, rng: np.random.Generator) -> Doc:
    pay = (
        "Payment is due on delivery."
        if s.payment_terms_days == 0
        else _pick(
            rng,
            (
                f"Payment is due {_plural(s.payment_terms_days, 'day')} after delivery.",
                f"The credit period is {_plural(s.payment_terms_days, 'day')} from the invoice date.",
                f"Invoices are payable within {_plural(s.payment_terms_days, 'day')}.",
            ),
        )
    )
    window = s.return_window_days or 0
    returns = _pick(
        rng,
        (
            f"Damaged or wrong items can be returned within {_plural(window, 'day')} of delivery.",
            f"Report breakage and wrong supply within {_plural(window, 'day')} of delivery to get a credit note.",
            f"The return window for damaged or wrongly supplied goods is {_plural(window, 'day')} from delivery.",
        ),
    )
    if s.accepts_expiry_returns:
        w = s.expiry_return_window_days or 60
        expiry = _pick(
            rng,
            (
                f"Stock close to expiry is taken back if it is returned at least {w} days before the expiry date.",
                f"Expiry returns are accepted. Send the stock up to {w} days before it expires.",
                f"The supplier accepts near expiry returns within {w} days of the expiry date.",
            ),
        )
    else:
        expiry = _pick(
            rng,
            (
                "Expired or near expiry stock is not taken back.",
                "The supplier does not accept expiry returns, so order short dated lines in small quantities.",
                "There is no return for expiry. Check dates before accepting a delivery.",
            ),
        )
    text = f"{s.name}. Terms and returns. {pay} {returns} {expiry}"
    return Doc(
        "supplier_policy",
        f"{s.name}: terms and returns",
        f"{s.code}:terms",
        text,
        {"supplier_code": s.code, "topic": "terms"},
    )


def _delivery_doc(s: SupplierSpec, rng: np.random.Generator) -> Doc:
    order_days = _days(s.order_weekdays)
    delivery = _days(s.delivery_weekdays)
    lead = s.default_lead_time_days or 1
    first = _pick(
        rng,
        (
            f"Place orders on {order_days}. The supplier delivers on {delivery}.",
            f"Orders are taken on {order_days} and goods arrive on {delivery}.",
            f"Order on {order_days}. Delivery days are {delivery}.",
        ),
    )
    time = _pick(
        rng,
        (
            f"The usual delivery time is {_plural(lead, 'day')}.",
            f"Expect delivery {_plural(lead, 'day')} after the order, moved to the next delivery day.",
            f"Delivery time is normally {_plural(lead, 'day')}.",
        ),
    )
    late = _pick(
        rng,
        (
            f"Deliveries are now and then late by 1 to {s.delay_days_max} days.",
            f"A late delivery of up to {_plural(s.delay_days_max, 'day')} happens from time to time.",
            f"Plan for a delay of up to {_plural(s.delay_days_max, 'day')} on some orders.",
        ),
    )
    minimum = _pick(
        rng,
        (
            f"The minimum order value is {_rupees(s.min_order_value)}.",
            f"Orders below {_rupees(s.min_order_value)} are not accepted.",
            f"Keep each order at or above {_rupees(s.min_order_value)}.",
        ),
    )
    scheme = _pick(
        rng,
        (
            "Bulk schemes are announced by circular. Check the scheme dates before you buy extra stock.",
            "From time to time the supplier offers a scheme on larger orders. Compare it with how fast the item sells.",
            "Scheme offers are shared by the representative. A scheme is worth taking only if the stock sells before it expires.",
        ),
    )
    text = f"{s.name}. Delivery and pricing notes. {first} {time} {late} {minimum} {scheme}"
    return Doc(
        "supplier_policy",
        f"{s.name}: delivery and pricing",
        f"{s.code}:delivery",
        text,
        {"supplier_code": s.code, "topic": "delivery"},
    )


def _festival_doc(s: SupplierSpec, rng: np.random.Generator, medical: bool) -> Doc:
    if medical:
        body = _pick(
            rng,
            (
                "Medicine supply keeps its normal schedule through festival weeks. Transport can be slower for a day around Diwali.",
                "Festival weeks change delivery very little. Order a day earlier before Diwali and Ganesh Chaturthi.",
                "Deliveries run as usual in festival weeks. Allow one extra day around Diwali.",
            ),
        )
    else:
        body = _pick(
            rng,
            (
                "Around Diwali expect deliveries to take 2 extra days. Around Ganesh Chaturthi and Navratri allow 1 extra day.",
                "Festival weeks are busy. Place Diwali orders two weeks early and add 2 days to the delivery time.",
                "Diwali orders move slower, by about 2 days. Ganesh Chaturthi and Navratri add about 1 day.",
            ),
        )
    text = f"{s.name}. Festival schedule notes. {body}"
    return Doc(
        "supplier_policy",
        f"{s.name}: festival schedule",
        f"{s.code}:festival",
        text,
        {"supplier_code": s.code, "topic": "festival"},
    )


MEDICAL_NOTES: tuple[tuple[str, str], ...] = (
    (
        "Storing strips and bottles",
        "Keep strips and bottles in their cartons on shelves away from direct sunlight, damp walls and heat. Keep the stock room dry and the floor clear so cartons are never stored on the ground.",
    ),
    (
        "Selling the earliest expiry first",
        "Place new stock behind older stock of the same item. At billing, sell the batch with the earliest expiry date first. Check the batch number on the strip against the bill.",
    ),
    (
        "Checking a delivery",
        "At delivery, match each line with the invoice. Check the batch number, expiry date and quantity on the carton. Refuse cartons that are damaged or have less than the expected shelf life, and note it on the invoice.",
    ),
    (
        "Handling expired stock",
        "Move expired stock to a marked tray the same day it is found. Do not bill it. Record a write off with the batch number and quantity, then return or dispose of it as the supplier policy says.",
    ),
    (
        "Weekly review of near expiry stock",
        "Once a week, list batches that expire within 90 days. Ask the supplier about returns where the policy allows. Move slow items to the front of the shelf and avoid reordering them until the stock falls.",
    ),
    (
        "Items that need a fridge",
        "Keep items marked for cold storage in the fridge. Write the date the pack was opened on the label. Check the fridge at opening and closing time.",
    ),
    (
        "Damaged and broken stock",
        "Record broken bottles and torn cartons as damage with a short note. Keep the broken item until the supplier confirms the credit note.",
    ),
    (
        "Scheduled medicines shelf",
        "Keep items marked Schedule H on a separate rack that customers cannot reach. Keep the bill copy for those items.",
    ),
    (
        "Counting the shelf",
        "Count a part of the shelf every month and enter the count in the system. Count the fast sellers and the costly items more often. A difference of one or two strips is normal and is corrected by the count.",
    ),
    (
        "Returning stock to a supplier",
        "Pack the items with the batch number, expiry date and quantity listed. Send the list with the carton. Record the return in the system on the day the carton leaves.",
    ),
    (
        "Quarantine for doubtful stock",
        "If a batch looks wrong, put it in the quarantine tray and stop billing it. Ask the supplier before you decide to write it off or return it.",
    ),
)


def medical_note_docs(rng: np.random.Generator) -> list[Doc]:
    count = int(rng.integers(8, 12))
    order = rng.permutation(len(MEDICAL_NOTES))[:count]
    return [
        Doc(
            "product_note",
            MEDICAL_NOTES[int(i)][0],
            f"note:{int(i) + 1:02d}",
            MEDICAL_NOTES[int(i)][1],
            {"topic": "operations"},
        )
        for i in order
    ]


GLOSSARY: tuple[tuple[str, str], ...] = (
    (
        "Forecast error",
        "Forecast error is the share of sales that the forecast missed on average. A lower number means the forecast was closer to what sold.",
    ),
    (
        "Forecast tendency",
        "Forecast tendency shows whether forecasts run high or low. A positive number means the forecast was usually above the sales.",
    ),
    (
        "Buffer stock",
        "Buffer stock is extra stock kept in case sales run higher than expected or a delivery is late. It is larger for items that sell unevenly.",
    ),
    (
        "Days to cover",
        "Days to cover is the number of days the stock you can count on will last at the expected sales rate.",
    ),
    (
        "Delivery time",
        "Delivery time is the number of days a supplier takes to deliver after you place the order. The plan adds days around festivals when the setting is on.",
    ),
    (
        "Minimum order",
        "Minimum order is the smallest quantity or value a supplier accepts. If the shortfall is below it, the plan raises the quantity to the minimum.",
    ),
    (
        "Pack of",
        "Pack of is the number of units in one supplier pack. Orders are placed in whole packs, so the quantity is rounded up to the next pack.",
    ),
    (
        "Shortfall",
        "Shortfall is how much you are short before pack rounding. It is the stock needed to cover the days to cover plus the buffer stock, minus the stock you can count on.",
    ),
    (
        "Stock you can count on",
        "Stock you can count on is sellable stock plus confirmed deliveries, minus reserved stock. Deliveries that are overdue are not counted.",
    ),
    (
        "Sell earliest expiry first",
        "Sell earliest expiry first means each sale takes stock from the batch that expires soonest. It lowers the amount that expires unsold.",
    ),
    (
        "Stock that may expire",
        "Stock that may expire is the quantity likely to expire before it sells, based on the expected sales and the expiry dates of each batch.",
    ),
    (
        "Not selling",
        "Not selling stock has had no sales for a long time while the item was on the shelf. Items that were out of stock are marked unverified instead.",
    ),
    (
        "Extra stock",
        "Extra stock is more than the expected sales need over the extra stock horizon. It is shown so you can avoid buying more of it.",
    ),
    (
        "Forecast confidence",
        "Forecast confidence is High, Fair or Low. It depends on how much clean sales history exists, how close past forecasts were and whether the delivery time is known.",
    ),
)

FORMULAS: tuple[tuple[str, str], ...] = (
    (
        "How the suggested quantity is worked out",
        "The plan starts with the sales expected over the days to cover. It adds buffer stock and subtracts the stock you can count on. The result is the shortfall. The shortfall is raised to the minimum order if needed and rounded up to whole packs. The numbers on the plan come from the stored sales and stock records, and the assistant never changes them.",
    ),
    (
        "How buffer stock is set",
        "Buffer stock grows with how unevenly an item sells, with the delivery time and with the service level in the settings. A higher service level means a larger buffer.",
    ),
    (
        "How the budget is shared",
        "When the budget is less than the total need, lines are ranked by a priority score. The score weighs the chance of running out, the value of the sales at risk, the forecast confidence and a small penalty for extra stock. Lines are funded in order, in whole packs, until the budget is used.",
    ),
    (
        "How the expiry limit works",
        "For items with expiry dates the plan limits the quantity so that new stock is expected to sell before its sellable shelf life ends. The limit is shown on the line with a reason.",
    ),
    (
        "How festivals change the numbers",
        "A festival effect is applied only when past sales show a clear and repeated rise for the category. If there is not enough evidence the plan keeps the normal forecast and shows the numbers as not enough evidence.",
    ),
)

GUIDES: tuple[tuple[str, str], ...] = (
    (
        "How to record a sale",
        "Open Sales and choose New bill. Search for an item by name, barcode or code, press Enter to add it and set the quantity. Check the payment mode and save the bill. A warning appears if the stock is short or if the same bill looks like a duplicate.",
    ),
    (
        "How to record a return",
        "Open the bill from Sales and choose Return. Pick the lines and quantities. Choose whether the item goes back on the shelf, is damaged or has expired. The refund is worked out for you.",
    ),
    (
        "How to receive goods",
        "Open Purchases, find the order and choose Receive. Enter the quantity that arrived for each line. For items with expiry dates enter the batch number, the expiry date and the MRP. Save the receipt and the stock updates at once.",
    ),
    (
        "How to read the Monday plan",
        "The plan lists what to buy this week, what not to buy, what to watch and where stock may expire. Each line shows the reason in plain words and a tag for whether a number was observed, calculated or assumed. Open a line to see the stock, the expected sales and the supplier terms.",
    ),
    (
        "How to approve or edit a line",
        "On the Buy tab, approve a line as it is, or change the quantity in whole packs and give a reason. You can also reject a line. Your choices are saved with the plan and are used to explain later plans.",
    ),
    (
        "How to export the plan",
        "Use the download buttons on the plan to get a PDF, an Excel file or a CSV file. The numbers match across all three. The file name carries the week and the shop name.",
    ),
)


def app_docs() -> list[Doc]:
    docs = [
        Doc(
            "app_knowledge",
            f"Glossary: {name}",
            f"glossary:{i + 1:02d}",
            text,
            {"kind": "glossary"},
            tenant_scoped=False,
        )
        for i, (name, text) in enumerate(GLOSSARY)
    ]
    docs += [
        Doc(
            "app_knowledge",
            title,
            f"formula:{i + 1:02d}",
            text,
            {"kind": "formula"},
            tenant_scoped=False,
        )
        for i, (title, text) in enumerate(FORMULAS)
    ]
    docs += [
        Doc(
            "app_knowledge",
            title,
            f"guide:{i + 1:02d}",
            text,
            {"kind": "guide"},
            tenant_scoped=False,
        )
        for i, (title, text) in enumerate(GUIDES)
    ]
    return docs


def build_corpus(catalog: Catalog, base_seed: int) -> list[Doc]:
    """Tenant scoped documents for one tenant. Global documents come from `app_docs`."""
    rng = stream(base_seed, catalog.profile.index, "corpus")
    docs = supplier_docs(catalog, rng)
    if catalog.profile.is_medical:
        docs += medical_note_docs(rng)
    return docs


def document_rows(
    docs: list[Doc], catalog: Catalog | None, created: Any
) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
    """Rows for `knowledge_documents` and `knowledge_chunks`. Embeddings stay empty."""
    ti = catalog.profile.index if catalog else 15
    tenant = tenant_uuid(catalog.profile) if catalog else None
    doc_rows: list[tuple[Any, ...]] = []
    chunk_rows: list[tuple[Any, ...]] = []
    for i, doc in enumerate(docs):
        doc_id = make_uuid(ti, 21, i + 1)
        scoped = doc.tenant_scoped
        doc_rows.append(
            (
                doc_id,
                tenant if scoped else None,
                doc.doc_type,
                doc.title,
                doc.source_ref,
                json.dumps(doc.metadata),
                content_hash(doc.text),
                created,
            )
        )
        for j, piece in enumerate(chunk_text(doc.text)):
            chunk_rows.append(
                (
                    make_uuid(ti, 22, len(chunk_rows) + 1),
                    doc_id,
                    tenant if scoped else None,
                    j,
                    piece,
                    tokens_of(piece),
                    json.dumps({"doc_type": doc.doc_type, "title": doc.title}),
                    created,
                )
            )
    return doc_rows, chunk_rows
