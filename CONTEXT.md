# Card OCR Prompt Optimization

This context names the evaluation goals used when optimizing gift card OCR prompts.

## Language

**Gift Card Code Recognition Optimization**:
An optimization goal focused only on recognizing redeemable gift card code values.
_Avoid_: Card type optimization, metadata optimization

**Gift Card Code Optimization Boundary**:
Gift card code recognition optimization may change code extraction, number output, and code-candidate detection rules across simple, complex, and complete OCR prompts. It must not change physical-versus-electronic type classification, brand, country, currency, or denomination rules.
_Avoid_: Card type optimization boundary, metadata optimization boundary

**Card Type Recognition Optimization**:
An optimization goal focused only on recognizing whether a gift card code belongs to a physical card or an electronic code.
_Avoid_: cardType optimization, country optimization, currency optimization, denomination optimization

**Card Type**:
The physical form classification of a gift card code, either physical card or electronic code.
_Avoid_: Brand, cardType, country, currency, denomination

**Card Type Evaluation Set**:
A manually labeled dataset for card type recognition optimization. Each row contains `card_image`, `origin`, and `golden_type`.
_Avoid_: Gift card code evaluation set, metadata evaluation set

**Gift Card Code Evaluation Set**:
A manually labeled dataset for gift card code recognition optimization. Each row contains `card_image`, `origin`, and `md5_card_number`.
_Avoid_: Card type evaluation set, metadata evaluation set

**golden_type**:
The manually labeled answer for card type recognition. Its value repeats `Physics` or `E-codes` once per card image in the same row; mixed-type rows are outside the current scope.
_Avoid_: type, cardType, denomination

**Card Type Match**:
A card type prediction is correct when the predicted type value equals or contains the manually labeled `golden_type`. For multiple card images in one row, predicted type values are concatenated in image order before matching.
_Avoid_: Code match, brand match, metadata match

**Card Type Optimization Boundary**:
Card type recognition optimization may change only the `type` classification rules for physical card versus electronic code, and those changes apply to both complex and complete OCR prompts. It must not change gift card code extraction, detection, output format, brand, country, currency, denomination, or number rules.
_Avoid_: Code optimization boundary, metadata optimization boundary

## Example Dialogue

Dev: Is this experiment optimizing card type?
Domain expert: Only if it measures physical card versus electronic code. Brand and amount are separate concerns.

Dev: Should a card type optimization change redemption code extraction rules?
Domain expert: No. Code recognition and card type recognition are separate optimization goals.
